"""ChatRite Dictate: switch it on once and it keeps listening, typing what you say into whichever window has focus.

Runs on your own PC (Whisper on the graphics card). Nothing is sent anywhere except the one-off model download
and a check for updates on GitHub Pages. Hotkey (default Ctrl+Alt+M) switches listening on and off.
"""
VERSION = 11

import os
import json
import re
import sys
import time
import queue
import threading
import configparser
import subprocess
import urllib.request
from collections import deque

APP = "ChatRite"
DATA = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP)
INSTALL = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), APP, "dictate")
UPDATE_URL = "https://dmhmca.github.io/get-a-grip/dictate/"
INI = os.path.join(DATA, "dictate.ini")
VOCAB = os.path.join(DATA, "vocabulary.txt")
LOG = os.path.join(DATA, "dictate-log.txt")
RATE = 16000
BLOCK = 320  # 20 ms

DEFAULTS = {
    "hotkey": "ctrl+alt+m",
    "model": "large-v3-turbo",
    "silence_ms": "600",       # a pause this long ends a phrase
    "idle_timeout_s": "90",    # switch off after this long without speech (0 = never)
    "threshold": "0",          # 0 = work it out from the room noise
    "microphone": "",          # part of a device name; empty = Windows default
    "beeps": "yes",
    "auto_stops": "no",        # yes = let Whisper put a full stop or comma at every pause
    "polish_wait_s": "5",      # after you say "polish", wait this long before typing again
    "smart_stops": "no",      # yes =the local model decides, from the grammar, where a sentence ends
    "stops_model": "",         # empty = the model ChatRite uses (settings.ini), else qwen2.5:7b
}


def log(msg):
    try:
        os.makedirs(DATA, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + str(msg) + "\n")
    except Exception:
        pass


def load_settings():
    cp = configparser.ConfigParser()
    cp.read_dict({"dictate": DEFAULTS})
    try:
        cp.read(INI, encoding="utf-8")
    except Exception:
        pass
    if not os.path.exists(INI):
        try:
            os.makedirs(DATA, exist_ok=True)
            with open(INI, "w", encoding="utf-8") as f:
                f.write("[dictate]\n" + "".join("%s = %s\n" % kv for kv in DEFAULTS.items()))
        except Exception:
            pass
    return cp["dictate"]


# ---------------------------------------------------------------- pure logic (tested without a PC)
def load_vocab(path=VOCAB):
    """Names, one per line, and 'heard => meant' pairs (we keep the 'meant' word)."""
    names = []
    try:
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line[0] in ";#":
                    continue
                if "=>" in line:
                    line = line.split("=>")[-1].strip()
                if line and line not in names:
                    names.append(line)
    except Exception:
        pass
    return names


def build_prompt(names, previous):
    parts = ["British English spelling."]
    if names:
        parts.append("Names and terms: " + ", ".join(names[:60]) + ".")
    if previous:
        parts.append(previous[-120:])
    return " ".join(parts)


HALLUCINATIONS = {"thank you", "thanks for watching", "thank you for watching", "you", "bye", "bye bye", "so", "okay"}
STARTERS = set("and but so because which that the a an to of in on for with as if or then than my your our their his her its it this these those we you they he she there when while although though".split())


def normalise(text):
    return re.sub(r"[^a-z ]", "", text.lower()).strip()


def parse_command(text):
    t = normalise(text)
    if t in ("new line", "newline"):
        return ("newline", 1)
    if t in ("new paragraph", "next paragraph"):
        return ("newline", 2)
    if t in ("stop dictation", "stop listening", "chatrite off", "chat right off"):
        return ("stop", 0)
    if t in ("press enter", "press return", "hit enter", "carriage return", "cr", "c r", "press cr", "press c r"):
        return ("enter", 0)
    if t in ("paste that", "paste it", "paste this", "paste", "press paste", "paste the clipboard"):
        return ("paste", 0)
    if t in ("polish", "polish that", "polish it", "polish this", "polish the text", "chatrite polish", "chat right polish"):
        return ("polish", 0)
    return None


NOISES = set("ahem hmm hm mm mmm mhm um uh er erm ah huh cough coughs coughing sniff sniffs sigh sighs laughs laughter music applause".split())
KEEP_CAPITAL = set("monday tuesday wednesday thursday friday saturday sunday january february march april may june july august september october november december".split())
SPOKEN = [(r"full stop", "."), (r"comma", ","), (r"question mark", "?"), (r"exclamation (?:mark|point)", "!")]


OLLAMA = "http://127.0.0.1:11434"
BOUNDARY_PROMPT = """Text was dictated and has no punctuation. A pause came between PART A and PART B.
Decide from the grammar and meaning, not from the pause: does a NEW SENTENCE begin at the start of PART B?
Answer with one word: YES (a new sentence begins, and PART A was a statement), QUESTION (a new sentence begins, and PART A was a question), or NO (PART B continues the same sentence).

PART A: the meeting went well
PART B: we agreed to start in March
Answer: YES

PART A: I think the best way to do this is
PART B: to use a local model
Answer: NO

PART A: because I stop often
PART B: when I am thinking
Answer: NO

PART A: can you check the figures
PART B: I will send the invoice tomorrow
Answer: QUESTION

PART A: it looks fine I think except that now punctuation is not working
PART B: I would have expected a full stop after the word app
Answer: YES

PART A: and the second thing is that
PART B: the file is too large
Answer: NO

PART A: to see whether the
PART B: extraneous question marks have been reduced
Answer: NO

PART A: I wonder if this has actually fixed the problem
PART B: I think that it is missing some full stops
Answer: YES

PART A: it is putting in
PART B: full stops for every pause
Answer: NO

Remember that the start of PART B may have a capital letter only because it was typed first in a phrase; ignore capitals.

PART A: %s
PART B: %s
Answer:"""


def lower_start(text):
    """Whisper capitalises the start of every phrase, which would tempt the model to see a sentence start."""
    first = text.split()[0] if text.split() else ""
    if first and first[0].isupper() and first != "I" and not first.startswith("I'") and not (len(first) > 1 and first.isupper()):
        return text[0].lower() + text[1:]
    return text


def make_boundary(settings):
    """Returns a function that asks the local model whether a new sentence starts at a join, or None if switched off."""
    if settings.get("smart_stops", "no") != "yes":
        return None
    model = settings.get("stops_model", "").strip()
    if not model:
        try:
            cp = configparser.ConfigParser()
            cp.read(os.path.join(DATA, "settings.ini"), encoding="utf-8")
            model = cp.get("Tidy", "Model", fallback="")
        except Exception:
            model = ""
    model = model or "qwen2.5:7b"
    state = {"down_until": 0.0, "warned": False}

    def boundary(prev, new):
        if time.time() < state["down_until"]:
            return None
        body = json.dumps({"model": model, "stream": False, "keep_alive": "24h",
                           "options": {"temperature": 0, "num_predict": 4, "num_ctx": 8192},
                           "prompt": BOUNDARY_PROMPT % (prev[-200:], lower_start(new[:200]))}).encode("utf-8")
        try:
            req = urllib.request.Request(OLLAMA + "/api/generate", data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=4) as r:
                answer = json.loads(r.read().decode("utf-8")).get("response", "").strip().upper()
        except Exception as e:
            state["down_until"] = time.time() + 30
            if not state["warned"]:
                state["warned"] = True
                log("sentence check unavailable (is Ollama running?): %r" % (e,))
            return None
        if answer.startswith(("YES", "QUESTION")):  # a question mark is left to "question mark" or Polish
            return "."
        return None

    return boundary


class Output:
    """Decides what exactly to type for each phrase.

    A pause is not a full stop, so by default nothing is added at the end of a phrase; you say "full stop",
    "comma", "question mark" or "exclamation mark" where you want one. Coughs and other noises are dropped,
    and a phrase that continues a sentence starts with a small letter."""

    def __init__(self, names=None, auto_stops=False, boundary=None):
        self.boundary = boundary
        self.last = ""
        self.names = set(n.lower() for n in (names or []))
        self.auto_stops = auto_stops

    def reset(self):
        self.last = ""

    def newline(self, n):
        self.last = "\n"

    def prepare(self, text):
        text = " ".join(text.split())
        # sounds in brackets or asterisks, such as [coughs] or (laughs)
        text = " ".join(re.sub(r"\[[^\]]*\]|\([^)]*\)|\*[^*]*\*", " ", text).split())
        # Whisper marks a phrase that starts or stops mid-thought with "..."; a pause is not an ellipsis.
        text = re.sub(r"^(?:\.{2,}|…)\s*", "", text)
        text = re.sub(r"\s*(?:\.{2,}|…)$", "", text)
        text = re.sub(r"\s*(?:\.{2,}|…)\s*", ", ", text)
        if not self.auto_stops:
            text = re.sub(r"[\s.,;:?]+$", "", text)
        for words, mark in SPOKEN:
            text = re.sub(r"[\s,.]*\b" + words + r"\b[.,]?", mark, text, flags=re.I)
        text = re.sub(r"([.,?!;:])(?=[A-Za-z])", r"\1 ", text)
        text = re.sub(r"([.?!]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)
        text = text.strip()
        if not text:
            return ""
        if normalise(text) in HALLUCINATIONS:
            return ""
        words = normalise(text).split()
        if words and all(w in NOISES for w in words):
            return ""
        if self.last and not self.last.endswith("\n"):
            ended = re.search(r"[.?!][\"')\]]*$", self.last)
            if not ended and not re.search(r"[,;:]$", self.last) and self.boundary and not self.auto_stops:
                mark = self.boundary(self.last[-200:], text)  # None, "." or "?"
                if mark:
                    text = mark + " " + text[0].upper() + text[1:]
                    self.last = text.strip()
                    return text
            if not ended:
                first = text.split()[0].strip(",.;:!?\"')")
                low = first.lower()
                if (text[0].isupper() and low != "i" and not low.startswith("i'")
                        and not (len(first) > 1 and first.isupper())
                        and low not in self.names and low not in KEEP_CAPITAL):
                    text = text[0].lower() + text[1:]
            if text[0] not in ".,?!;:":
                text = " " + text
        self.last = text.strip()
        return text


class Endpointer:
    """Cuts a stream of 20 ms blocks into spoken phrases, using a pause as the end of a phrase."""

    def __init__(self, silence_s=0.6, min_speech_s=0.3, max_utt_s=25.0, preroll_s=0.35, threshold=0.0):
        import numpy as np
        self.np = np
        bs = BLOCK / RATE
        self.silence_n = max(1, int(silence_s / bs))
        self.min_speech_n = max(1, int(min_speech_s / bs))
        self.max_n = int(max_utt_s / bs)
        self.keep_tail_n = int(0.25 / bs)
        self.fixed = threshold
        self.noise = 0.003
        self.pre = deque(maxlen=max(1, int(preroll_s / bs)))
        self.in_speech = False
        self.run = 0
        self.buf = []
        self.silence = 0
        self.speech = 0
        self.last_speech_time = time.time()

    @property
    def thr(self):
        return self.fixed if self.fixed > 0 else max(0.006, self.noise * 3.5)

    def feed(self, blk):
        np = self.np
        rms = float(np.sqrt(np.mean(blk * blk)) + 1e-9)
        is_sp = rms > self.thr
        if is_sp:
            self.last_speech_time = time.time()
        out = []
        if not self.in_speech:
            if is_sp:
                self.noise += 0.0005 * (rms - self.noise)
            else:
                self.noise += 0.02 * (rms - self.noise)
            self.pre.append(blk)
            self.run = self.run + 1 if is_sp else 0
            if self.run >= 3:
                self.in_speech = True
                self.buf = list(self.pre)
                self.silence = 0
                self.speech = self.run
        else:
            self.buf.append(blk)
            if is_sp:
                self.silence = 0
                self.speech += 1
            else:
                self.silence += 1
            if self.silence >= self.silence_n or len(self.buf) >= self.max_n:
                extra = max(0, self.silence - self.keep_tail_n)
                blocks = self.buf[:len(self.buf) - extra] if extra else self.buf
                if self.speech >= self.min_speech_n:
                    out.append(np.concatenate(blocks))
                self.in_speech = False
                self.buf = []
                self.run = 0
                self.pre.clear()
        return out


# ---------------------------------------------------------------- Windows plumbing (typing, sound, single instance)
def add_cuda_dlls():
    """The pip packages nvidia-cublas-cu12 and nvidia-cudnn-cu12 carry the DLLs Whisper needs on the graphics card."""
    for p in list(sys.path):
        d = os.path.join(p, "nvidia")
        if os.path.isdir(d):
            for sub in os.listdir(d):
                b = os.path.join(d, sub, "bin")
                if os.path.isdir(b):
                    try:
                        os.add_dll_directory(b)
                    except Exception:
                        pass
                    os.environ["PATH"] = b + os.pathsep + os.environ.get("PATH", "")


def _win():
    import ctypes
    from ctypes import wintypes

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    return ctypes, INPUT, KEYBDINPUT


def type_text(s):
    """Type text into the focused window as if from the keyboard (Unicode, so accents and symbols work)."""
    import struct
    ctypes, INPUT, KEYBDINPUT = _win()
    s = s.replace("\r", " ").replace("\n", " ")
    data = s.encode("utf-16-le")
    units = struct.unpack("<%dH" % (len(data) // 2), data)
    for i in range(0, len(units), 40):
        chunk = units[i:i + 40]
        arr = (INPUT * (len(chunk) * 2))()
        for j, u in enumerate(chunk):
            for k, flags in ((0, 0x0004), (1, 0x0004 | 0x0002)):
                x = arr[j * 2 + k]
                x.type = 1
                x.u.ki = KEYBDINPUT(0, u, flags, 0, 0)
        ctypes.windll.user32.SendInput(len(arr), arr, ctypes.sizeof(INPUT))
        time.sleep(0.003)


def press_shift_enter(times):
    """A soft line break. Never a plain Enter, because that would SEND a message in a chat box."""
    ctypes, INPUT, KEYBDINPUT = _win()
    for _ in range(times):
        seq = [(0x10, 0), (0x0D, 0), (0x0D, 0x0002), (0x10, 0x0002)]
        arr = (INPUT * len(seq))()
        for i, (vk, fl) in enumerate(seq):
            arr[i].type = 1
            arr[i].u.ki = KEYBDINPUT(vk, 0, fl, 0, 0)
        ctypes.windll.user32.SendInput(len(arr), arr, ctypes.sizeof(INPUT))
        time.sleep(0.02)


def press_keys(vks):
    """Press keys together (for example Ctrl+V) in the focused window, then release them."""
    ctypes, INPUT, KEYBDINPUT = _win()
    seq = [(vk, 0) for vk in vks] + [(vk, 0x0002) for vk in reversed(vks)]
    arr = (INPUT * len(seq))()
    for i, (vk, fl) in enumerate(seq):
        arr[i].type = 1
        arr[i].u.ki = KEYBDINPUT(vk, 0, fl, 0, 0)
    ctypes.windll.user32.SendInput(len(arr), arr, ctypes.sizeof(INPUT))
    time.sleep(0.05)


def beep(kind, on=True):
    if not on:
        return
    try:
        import winsound
        {"on": lambda: (winsound.Beep(1100, 70), winsound.Beep(1500, 70)),
         "off": lambda: (winsound.Beep(900, 70), winsound.Beep(600, 110)),
         "warn": lambda: winsound.Beep(500, 200)}[kind]()
    except Exception:
        pass


_mutex = None


def already_running():
    global _mutex
    try:
        import ctypes
        _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\ChatRiteDictate")
        if ctypes.windll.kernel32.GetLastError() == 183:
            # let go of our own handle, or it would keep the marker alive after the old copy quits
            ctypes.windll.kernel32.CloseHandle(_mutex)
            _mutex = None
            return True
        return False
    except Exception:
        return False


# ---------------------------------------------------------------- the speech engine
class Engine:
    def __init__(self, settings):
        self.s = settings
        self.model = None
        self.device = "?"
        self.names = load_vocab()

    def load(self, say):
        add_cuda_dlls()
        from faster_whisper import WhisperModel
        import numpy as np
        name = self.s.get("model")
        try:
            say("Loading the speech model (only the very first start downloads it, about 1.6 GB)...")
            self.model = WhisperModel(name, device="cuda", compute_type="float16")
            list(self.model.transcribe(np.zeros(RATE, dtype="float32"), language="en")[0])
            self.device = "graphics card"
        except Exception as e:
            log("GPU failed: %r" % (e,))
            say("The graphics card could not be used, so using the processor instead (slower).")
            self.model = WhisperModel("small.en", device="cpu", compute_type="int8")
            self.device = "processor"
        log("model ready on %s" % self.device)

    def transcribe(self, audio, previous):
        segs, info = self.model.transcribe(
            audio, language="en", beam_size=5, temperature=0.0,
            condition_on_previous_text=False, without_timestamps=True,
            initial_prompt=build_prompt(self.names, previous))
        parts = []
        for sg in segs:
            if sg.no_speech_prob > 0.6 and sg.avg_logprob < -0.8:
                continue
            if sg.avg_logprob < -1.5:
                continue
            parts.append(sg.text.strip())
        return " ".join(p for p in parts if p)


class App:
    def __init__(self):
        self.s = load_settings()
        self.engine = Engine(self.s)
        self.out = Output(load_vocab(), self.s.get("auto_stops", "no") == "yes", make_boundary(self.s))
        self.q = queue.Queue()
        self.listening = False
        self.busy = False
        self.stream = None
        self.worker = None
        self.icon = None
        self.beeps = self.s.get("beeps", "yes") == "yes"
        self.stop_flag = threading.Event()

    # --- tray
    def img(self, state):
        from PIL import Image, ImageDraw
        im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        if state == "listening":      # solid blue disc, white centre
            d.ellipse((6, 6, 58, 58), fill=(30, 100, 200, 255))
            d.ellipse((24, 24, 40, 40), fill=(255, 255, 255, 255))
        elif state == "working":      # amber square
            d.rectangle((8, 8, 56, 56), fill=(230, 160, 0, 255))
        else:                         # grey ring
            d.ellipse((6, 6, 58, 58), outline=(120, 120, 120, 255), width=8)
        return im

    def say(self, text):
        log(text)
        try:
            self.icon.notify(text, "ChatRite Dictate")
        except Exception:
            pass

    def set_state(self, state):
        try:
            self.icon.icon = self.img(state)
            self.icon.title = {"listening": "ChatRite Dictate: listening", "working": "ChatRite Dictate: working",
                               "off": "ChatRite Dictate: off (%s to start)" % self.s.get("hotkey")}[state]
        except Exception:
            pass

    # --- listening
    def pick_device(self):
        import sounddevice as sd
        want = self.s.get("microphone", "").strip().lower()
        if not want:
            return None
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0 and want in d["name"].lower():
                return i
        return None

    def start(self):
        if self.listening:
            return
        if self.engine.model is None:
            self.say("Still loading the speech model. Try again in a moment.")
            beep("warn", self.beeps)
            return
        import sounddevice as sd
        self.out.reset()
        self.stop_flag.clear()
        self.q = queue.Queue()

        def cb(indata, frames, t, status):
            self.q.put(indata[:, 0].copy())

        try:
            self.stream = sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=BLOCK,
                                         device=self.pick_device(), callback=cb)
            self.stream.start()
        except Exception as e:
            log("microphone failed: %r" % (e,))
            self.say("Could not open the microphone: %s" % e)
            beep("warn", self.beeps)
            return
        self.listening = True
        self.worker = threading.Thread(target=self.loop, daemon=True)
        self.worker.start()
        self.set_state("listening")
        beep("on", self.beeps)
        log("listening started")

    def stop(self, why="stopped"):
        if not self.listening:
            return
        self.listening = False
        self.stop_flag.set()
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:
            pass
        self.set_state("off")
        beep("off", self.beeps)
        log("listening " + why)

    def toggle(self):
        if self.listening:
            self.stop("switched off")
        else:
            self.start()

    def loop(self):
        ep = Endpointer(silence_s=int(self.s.get("silence_ms", "600")) / 1000.0,
                        threshold=float(self.s.get("threshold", "0")))
        idle = float(self.s.get("idle_timeout_s", "90"))
        while not self.stop_flag.is_set():
            try:
                blk = self.q.get(timeout=0.2)
            except queue.Empty:
                blk = None
            if blk is not None:
                for utt in ep.feed(blk):
                    self.handle(utt)
            if idle > 0 and not ep.in_speech and time.time() - ep.last_speech_time > idle and self.q.empty():
                self.say("Switched off after %d seconds of quiet." % idle)
                self.stop("timed out")
                return

    def handle(self, audio):
        t0 = time.time()
        self.set_state("working")
        try:
            text = self.engine.transcribe(audio, self.out.last)
            secs = time.time() - t0
            cmd = parse_command(text) if text else None
            if cmd and cmd[0] == "newline":
                press_shift_enter(cmd[1])
                self.out.newline(cmd[1])
            elif cmd and cmd[0] == "enter":
                # only when asked for by voice: this is the one place a plain Enter is pressed (it sends chat messages)
                press_keys([0x0D])
                self.out.newline(1)
            elif cmd and cmd[0] == "paste":
                press_keys([0x11, 0x56])
                self.out.last = "."  # pasted text counts as a finished sentence; the next phrase starts a new one
            elif cmd and cmd[0] == "stop":
                self.stop("stopped by voice")
                return
            elif cmd and cmd[0] == "polish":
                # ChatRite (the other program) does the polishing: it takes the selection, or the whole box
                # a small signal file, which ChatRite checks for; sending the hotkey as keystrokes was not reliable
                with open(os.path.join(DATA, "polish.now"), "w", encoding="utf-8") as f:
                    f.write("now")
                log("polish asked for")
                # speech heard meanwhile waits in the queue, so nothing is lost; give the paste time to finish
                time.sleep(float(self.s.get("polish_wait_s", "5")))
                self.out.last = "."  # the polished text ends a sentence, and the next phrase follows a space
            else:
                typed = self.out.prepare(text)
                if typed:
                    type_text(typed)
            log("phrase %.1fs of speech, %.2fs to recognise, %d characters" % (len(audio) / RATE, secs, len(text)))
        except Exception as e:
            log("phrase failed: %r" % (e,))
        finally:
            if self.listening:
                self.set_state("listening")

    # --- updates
    def fetch(self, name):
        req = urllib.request.Request(UPDATE_URL + name + "?t=" + str(int(time.time())))
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode("utf-8")

    def check_update(self, manual=False):
        try:
            ver = int(re.sub(r"\D", "", self.fetch("version.txt")) or 0)
            if ver <= VERSION:
                if manual:
                    self.say("You have the newest version (%d)." % VERSION)
                return
            new = self.fetch("dictate.py")
            m = re.search(r"^VERSION = (\d+)\s*$", new, re.M)
            if not m or int(m.group(1)) != ver or "# CHATRITE-DICTATE-END" not in new:
                if manual:
                    self.say("The update did not download properly. Nothing was changed.")
                return
            me = os.path.abspath(__file__)
            try:
                import shutil
                shutil.copyfile(me, os.path.join(os.path.dirname(me), "dictate.previous.py"))
            except Exception:
                pass
            with open(me + ".new", "w", encoding="utf-8", newline="\n") as f:
                f.write(new)
            os.replace(me + ".new", me)
            self.say("Updated to version %d. Restarting..." % ver)
            time.sleep(1.5)
            self.stop("restarting for an update")
            subprocess.Popen([sys.executable, me])
            os._exit(0)
        except Exception as e:
            log("update check failed: %r" % (e,))
            if manual:
                self.say("Could not check for updates just now.")

    def update_loop(self):
        time.sleep(20)
        while True:
            self.check_update(False)
            time.sleep(6 * 3600)

    # --- start-up
    def background(self, icon):
        icon.visible = True
        try:
            self.engine.load(self.say)
            self.say("Ready. Press %s to start listening, and again to stop. (Using the %s.)" % (self.s.get("hotkey"), self.engine.device))
        except Exception as e:
            log("model load failed: %r" % (e,))
            self.say("Could not load the speech model: %s" % e)
        try:
            import keyboard
            keyboard.add_hotkey(self.s.get("hotkey"), self.toggle)
        except Exception as e:
            log("hotkey failed: %r" % (e,))
            self.say("Could not set the hotkey: %s" % e)
        threading.Thread(target=self.update_loop, daemon=True).start()

    def run(self):
        import pystray
        menu = pystray.Menu(
            pystray.MenuItem("Start or stop listening (%s)" % self.s.get("hotkey"), lambda i, it: self.toggle(), default=True),
            pystray.MenuItem("Edit my words and names", lambda i, it: os.startfile(VOCAB) if os.path.exists(VOCAB) else None),
            pystray.MenuItem("Settings file", lambda i, it: os.startfile(INI)),
            pystray.MenuItem("Open the log folder", lambda i, it: os.startfile(DATA)),
            pystray.MenuItem("Check for updates now", lambda i, it: threading.Thread(target=self.check_update, args=(True,), daemon=True).start()),
            pystray.MenuItem("Version %d" % VERSION, None, enabled=False),
            pystray.MenuItem("Quit", lambda i, it: (self.stop("quit"), i.stop())),
        )
        self.icon = pystray.Icon("chatrite-dictate", self.img("off"), "ChatRite Dictate: loading", menu)
        self.icon.run(setup=self.background)


def main():
    os.makedirs(DATA, exist_ok=True)
    try:  # pythonw has no console; keep any library messages in the log
        sys.stdout = sys.stderr = open(os.path.join(DATA, "dictate-console.txt"), "a", buffering=1, encoding="utf-8")
    except Exception:
        pass
    # after an update the old copy is still shutting down for a moment, so wait for it before giving up
    for _ in range(20):
        if not already_running():
            break
        time.sleep(0.5)
    else:
        return
    App().run()


if __name__ == "__main__":
    main()
# CHATRITE-DICTATE-END
