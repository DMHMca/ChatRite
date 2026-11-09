"""ChatRite Dictate: switch it on once and it keeps listening, typing what you say into whichever window has focus.

Runs on your own PC (Whisper on the graphics card). Nothing is sent anywhere except the one-off model download
and a check for updates on GitHub Pages. Hotkey (default Ctrl+Alt+M) switches listening on and off.
"""
VERSION = 12

import os
import json
import re
import sys
import time
import queue
import threading
import csv
import io
import shutil
import configparser
import subprocess
import urllib.request
from collections import deque

APP = "ChatRite"
DATA = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP)
INSTALL = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), APP, "dictate")
UPDATE_URL = "https://dmhmca.github.io/ChatRite/dictate/"
INI = os.path.join(DATA, "dictate.ini")
VOCAB = os.path.join(DATA, "vocabulary.txt")
DICT_LOCAL = os.path.join(DATA, "dictionary.csv")        # this PC's copy of the shared dictionary
DICT_BASE = os.path.join(DATA, "dictionary.synced")      # what the two copies agreed on last time
LOG = os.path.join(DATA, "dictate-log.txt")
RATE = 16000
BLOCK = 320  # 20 ms

DEFAULTS = {
    "hotkey": "ctrl+alt+m",
    "model": "large-v3-turbo",
    "silence_ms": "600",       # a pause this long ends a phrase
    "min_speech_ms": "300",    # a sound with less speech than this is ignored (lower it if short words go missing)
    "idle_timeout_s": "90",    # switch off after this long without speech (0 = never)
    "threshold": "0",          # 0 = work it out from the room noise
    "microphone": "",          # part of a device name; empty = Windows default
    "beeps": "yes",
    "auto_stops": "no",        # yes = let Whisper put a full stop or comma at every pause
    "polish_wait_s": "5",      # after you say "polish", wait this long before typing again
    "smart_stops": "no",      # yes =the local model decides, from the grammar, where a sentence ends
    "stops_model": "",         # empty = the model ChatRite uses (settings.ini), else qwen2.5:7b
    "device": "auto",          # auto = graphics card if it works, else processor; cpu = processor only
    "cpu_model": "base.en",    # the model used on the processor (small.en is more accurate but about 5x slower)
    "model_folder": "",        # where speech models are stored; empty = the Windows default (on C)
    "boost_quiet": "no",       # yes = raise quiet speech to a good level before recognising it
    "floating_button": "no",   # yes = a round on-screen button that starts and stops listening (for tablet mode)
    "button_size": "96",       # size of that button in pixels
    "shared_dictionary": "",   # full path of dictionary.csv in a synced folder (Google Drive); empty = look for a ChatRite folder in My Drive
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


# --- the personal dictionary: "heard,meant" lines (the same file format Voice In exports), shared between PCs
def parse_dictionary(text):
    """All entries as {heard (lower case): meant}. Entries like <enter> are kept so they survive a sync."""
    d = {}
    try:
        for row in csv.reader(io.StringIO(text.lstrip("﻿"))):
            if len(row) < 2:
                continue
            heard = re.sub(r"\s+", " ", row[0].strip().lower()).strip(" .,")
            meant = ",".join(row[1:]).strip() if len(row) > 2 else row[1].strip()
            if heard and meant:
                d[heard] = meant
    except Exception:
        pass
    return d


def write_dictionary_text(d):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for k in sorted(d):
        w.writerow([k, d[k]])
    return buf.getvalue()


def read_dictionary(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return parse_dictionary(f.read())
    except Exception:
        return {}


def write_dictionary(path, d):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(write_dictionary_text(d))


def merge_three(base, local, shared, shared_newer=True):
    """Merge two copies of the dictionary that both started from base. A change on one side wins over no change
    on the other (so a deletion travels too); if both changed the same word, the newer copy wins."""
    out = {}
    for k in set(base) | set(local) | set(shared):
        b, l, s = base.get(k), local.get(k), shared.get(k)
        if l == s:
            r = l
        elif l == b:
            r = s
        elif s == b:
            r = l
        elif l is None or s is None:
            r = l if s is None else s
        else:
            r = s if shared_newer else l
        if r is not None:
            out[k] = r
    return out


def find_shared_dictionary(setting):
    setting = (setting or "").strip()
    if setting:
        return setting
    cands = []
    for letter in "GHIJKLMNOPQRSTUVWXYZ":
        cands.append(letter + ":\\My Drive\\ChatRite")
    home = os.path.expanduser("~")
    cands += [os.path.join(home, "My Drive", "ChatRite"), os.path.join(home, "Google Drive", "My Drive", "ChatRite"),
              os.path.join(home, "Google Drive", "ChatRite")]
    for c in cands:
        if os.path.isdir(c):
            return os.path.join(c, "dictionary.csv")
    return ""


def sync_dictionary(local, shared, base_path):
    """Brings this PC's copy and the shared copy together. Returns 'local only', 'unavailable' or 'synced'."""
    if not shared:
        return "local only"
    if not os.path.isdir(os.path.dirname(shared)):
        return "unavailable"
    l, s, b = read_dictionary(local), read_dictionary(shared), read_dictionary(base_path)
    try:
        newer = os.path.getmtime(shared) >= os.path.getmtime(local) if os.path.exists(shared) and os.path.exists(local) else True
    except Exception:
        newer = True
    m = merge_three(b, l, s, newer)
    if m != l or not os.path.exists(local):
        write_dictionary(local, m)
    if m != s or not os.path.exists(shared):
        write_dictionary(shared, m)
    if m != b:
        write_dictionary(base_path, m)
    return "synced"


def active_entries(d):
    """The entries that can be applied by this program (not the <enter>, <capitalize>, <case:...> commands)."""
    return {k: v for k, v in d.items() if not re.fullmatch(r"<[^<>]*>", v.strip()) and k != v.strip()}


def compile_dictionary(d):
    """One pass over the text, longest spoken phrase first, so a replacement is never replaced again."""
    entries = active_entries(d)
    if not entries:
        return None
    keys = sorted(entries, key=len, reverse=True)
    def spoken(k):
        # a short abbreviation may come out as "P.E.", "P E" or "p-e" as well as "PE"
        if re.fullmatch(r"[a-z]{2,3}", k):
            return r"[.\s-]?".join(re.escape(c) for c in k)
        return r"\s+".join(re.escape(w) for w in k.split())
    alt = "|".join(spoken(k) for k in keys)
    rx = re.compile(r"(?P<pre>\s*)(?<![A-Za-z0-9'])(?P<w>" + alt + r")(?![A-Za-z0-9'])(?P<post>[.,]?)(?P<sp>\s*)", re.I)
    return rx, entries


def apply_dictionary(compiled, text):
    if not compiled or not text:
        return text
    rx, entries = compiled

    def fix(m):
        meant = entries.get(re.sub(r"\s+", " ", m.group("w").lower()))
        if meant is None:
            meant = entries.get(re.sub(r"[^a-z]", "", m.group("w").lower()))   # "P.E." is the entry "pe"
        if meant is None:
            return m.group(0)
        pre, post, sp = m.group("pre"), m.group("post"), m.group("sp")
        if post and meant.rstrip()[-1:] in ".,!?":
            post = ""   # the entry already ends with its own stop
        if not re.search(r"[A-Za-z0-9]", meant):   # a spoken mark such as comma, colon, dash or slash
            if meant in ("-", "/"):
                return meant                          # joins the words either side
            return meant + sp                         # sits against the word before it and takes Whisper's own stop or comma
        if not meant[0].isalnum():                    # such as .com: sits against the word before it
            return meant + post + sp
        return pre + meant + post + sp
    return rx.sub(fix, text)


def dictionary_names(d, limit=80):
    """Short targets worth telling Whisper about and keeping their capitals (not snippets or marks)."""
    out = []
    for v in active_entries(d).values():
        v = v.strip()
        if 1 < len(v) <= 30 and len(v.split()) <= 3 and re.search(r"[A-Za-z]", v) and not re.search(r"[<>]", v) and v not in out:
            out.append(v)
    return out[:limit]


def all_names():
    names = load_vocab()
    for n in dictionary_names(read_dictionary(DICT_LOCAL)):
        if n not in names:
            names.append(n)
    return names


def build_prompt(names, previous):
    parts = ["British English spelling."]
    if names:
        parts.append("Names and terms: " + ", ".join(names[:60]) + ".")
    if previous:
        parts.append(previous[-120:])
    return " ".join(parts)


HALLUCINATIONS = {"thank you", "thanks for watching", "thank you for watching", "you", "bye", "bye bye"}  # "so" and "okay" are real words you may dictate alone, so they are kept
# Whisper invents these from silence or breathing (they come from the video subtitles it learned from).
# They are dropped even when said twice in a row, or one after another.
HALLUCINATED_PHRASES = [
    "im going to show you how to do this", "in this video im going to show you how to do this",
    "im going to show you how to do it", "i will show you how to do this", "lets get started",
    "thank you so much for watching", "thank you for watching", "thanks for watching", "thanks for listening",
    "please subscribe", "dont forget to subscribe", "subscribe to my channel", "see you in the next video",
    "see you next time", "bye for now", "thank you very much",
]


def is_hallucination(text):
    n = " " + normalise(text) + " "
    for p in sorted(HALLUCINATED_PHRASES, key=len, reverse=True):
        n = re.sub(r"(?<![a-z])" + p + r"(?![a-z])", " ", n)
    return not n.split() and bool(normalise(text))


STARTERS = set("and but so because which that the a an to of in on for with as if or then than my your our their his her its it this these those we you they he she there when while although though".split())


def normalise(text):
    return re.sub(r"[^a-z ]", "", text.lower()).strip()


NUMBER_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
NUMBER_WORDS["a"] = 1


def parse_delete(text):
    """Spoken editing, worded like the Voice In extension so there is one set of commands to remember:
    'delete word', 'delete last word', 'delete last 3 words', 'delete that' (the last phrase, or the selection),
    'select all', 'undo', and 'delete everything'. Returns None for anything else."""
    t = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", text.lower())).strip()
    if t in ("delete that", "erase that", "scratch that", "ignore that"):
        return ("delete_that", 0)
    if t in ("select all", "select everything"):
        return ("select_all", 0)
    if t in ("undo", "undo that"):
        return ("undo", 0)
    if re.fullmatch(r"(?:delete|erase|remove|clear) (?:everything|all|all text|all of it)", t):
        return ("delete_all", 0)
    m = re.fullmatch(r"(?:delete|erase|remove) (?:the )?(?:(?:last|previous|final) )?(?:(\w+) )?words?", t)
    if m:
        w = m.group(1)
        if w is None:
            return ("delete_words", 1)
        n = int(w) if w.isdigit() else NUMBER_WORDS.get(w)
        if n and 1 <= n <= 50:
            return ("delete_words", n)
    return None


def parse_command(text):
    dl = parse_delete(text)
    if dl:
        return dl
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
    if t in ("polish", "polish that", "polish it", "polish this", "polish the text", "chatrite polish", "chat right polish",
             "polished", "polish up", "polish it up", "i turn"):  # "i turn" is how the small model often hears "polish"
        return ("polish", 0)
    return None


NOISES = set("ahem hmm hm mm mmm mhm um uh er erm ah huh cough coughs coughing sniff sniffs sigh sighs laughs laughter music applause".split())
KEEP_CAPITAL = set("monday tuesday wednesday thursday friday saturday sunday january february march april may june july august september october november december".split())
SPOKEN = [(r"full stop", "."), (r"comma", ","), (r"semi[\s-]?colon", ";"), (r"colon", ":"), (r"question mark", "?"), (r"exclamation (?:mark|point)", "!")]


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
        self.typed = []   # what was typed, phrase by phrase, so a spoken "delete" knows how many characters to remove
        self.tail = ""    # the same text joined up (recent part only)
        self.dictionary = None   # the compiled personal dictionary

    def set_dictionary(self, d, names=None):
        self.dictionary = compile_dictionary(d)
        if names is not None:
            self.names = set(n.lower() for n in names)

    def reset(self):
        self.last = ""
        self.clear_tail()

    def newline(self, n):
        self.last = "\n"
        self.remember("\n" * n)

    # --- spoken deleting: counted from what Dictate itself typed, never from the editor's idea of a word
    def remember(self, s):
        if s:
            self.typed = (self.typed + [s])[-200:]
            self.tail = (self.tail + s)[-4000:]

    def clear_tail(self):
        self.typed = []
        self.tail = ""

    def pop_phrase(self):
        """Forget the last typed phrase; returns how many characters it was."""
        if not self.typed:
            return 0
        s = self.typed.pop()
        self.tail = self.tail[:len(self.tail) - len(s)] if len(s) <= len(self.tail) else ""
        return len(s)

    def pop_words(self, n):
        """Forget the last n words (and the space before each); returns how many characters that was."""
        s = self.tail
        for _ in range(n):
            m = re.search(r"[ \t]*\S+\s*$", s)
            if not m:
                break
            s = s[:m.start()]
        count = len(self.tail) - len(s)
        self.tail = s
        self.typed = []   # phrase boundaries no longer match, so "delete that" must not remove the rest
        return count

    def prepare(self, text):
        text = " ".join(text.split())
        # sounds in brackets or asterisks, such as [coughs] or (laughs)
        text = " ".join(re.sub(r"\[[^\]]*\]|\([^)]*\)|\*[^*]*\*", " ", text).split())
        text = " ".join(apply_dictionary(self.dictionary, text).split())   # the personal dictionary
        # Whisper marks a phrase that starts or stops mid-thought with "..."; a pause is not an ellipsis.
        text = re.sub(r"^(?:\.{2,}|…)\s*", "", text)
        text = re.sub(r"\s*(?:\.{2,}|…)$", "", text)
        text = re.sub(r"\s*(?:\.{2,}|…)\s*", ", ", text)
        if not self.auto_stops:
            text = re.sub(r"[\s.,;:?]+$", "", text)
        for words, mark in SPOKEN:
            text = re.sub(r"[\s,.]*\b" + words + r"\b[.,]?", mark, text, flags=re.I)
        # "period" is a common word, so it only counts as punctuation when it ends the phrase
        text = re.sub(r"[\s,.]*\bperiod\s*[.,]?$", ".", text, flags=re.I)
        text = re.sub(r"([.,?!;:])(?=[A-Za-z])", r"\1 ", text)
        text = re.sub(r"([.?!]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)
        text = text.strip()
        if not text:
            return ""
        if normalise(text) in HALLUCINATIONS or is_hallucination(text):
            return ""
        words = normalise(text).split()
        if words and all(w in NOISES for w in words):
            return ""
        sentence_start = bool(self.last) and (self.last.endswith("\n") or bool(re.search(r"[.?!][\"')\]]*$", self.last)))
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
        # a new sentence or a new line starts with a capital, whatever the speech engine gave us
        if sentence_start:
            text = re.sub(r"[A-Za-z]", lambda m: m.group(0).upper(), text, count=1) if re.match(r"\s*[A-Za-z]", text) else text
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
                else:
                    # a short, quiet word can fall under the minimum; say so (numbers only) so it is not lost silently
                    log("ignored a very short sound: %d ms of speech, the minimum is %d ms" % (
                        self.speech * BLOCK * 1000 // RATE, self.min_speech_n * BLOCK * 1000 // RATE))
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


def select_field():
    """Select all the text in the text box being typed in: Ctrl+Home, then Ctrl+Shift+End.
    Unlike Ctrl+A this stays inside the edit field; with no edit field focused it selects nothing, not the whole page."""
    press_keys([0x11, 0x24])
    time.sleep(0.05)
    press_keys([0x11, 0x10, 0x23])
    time.sleep(0.05)


def press_backspace(n):
    """Press Backspace n times in the focused window."""
    ctypes, INPUT, KEYBDINPUT = _win()
    n = max(0, min(int(n), 4000))
    for i in range(0, n, 10):                 # small paced batches, so the program keeps up with every one
        k = min(10, n - i)
        arr = (INPUT * (k * 2))()
        for j in range(k):
            for q, fl in ((0, 0), (1, 0x0002)):
                x = arr[j * 2 + q]
                x.type = 1
                x.u.ki = KEYBDINPUT(0x08, 0, fl, 0, 0)
        ctypes.windll.user32.SendInput(len(arr), arr, ctypes.sizeof(INPUT))
        time.sleep(0.01)
    time.sleep(0.1)                           # let the last deletions land before anything else is typed


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
        self.names = all_names()

    def load(self, say):
        add_cuda_dlls()
        from faster_whisper import WhisperModel
        import numpy as np
        name = self.s.get("model")
        folder = self.s.get("model_folder", "").strip() or None
        want_cpu = self.s.get("device", "auto").strip().lower() == "cpu"
        if not want_cpu:
            try:
                say("Loading the speech model (the very first start downloads it, about 1.6 GB)...")
                self.model = WhisperModel(name, device="cuda", compute_type="float16", download_root=folder)
                list(self.model.transcribe(np.zeros(RATE, dtype="float32"), language="en")[0])
                self.device = "graphics card"
            except Exception as e:
                log("GPU failed: %r" % (e,))
                say("The graphics card could not be used, so using the processor instead (slower).")
                self.model = None
        if self.model is None:
            cpu_name = self.s.get("cpu_model", "base.en").strip() or "base.en"
            say("Loading the speech model for the processor (%s)..." % cpu_name)
            self.model = WhisperModel(cpu_name, device="cpu", compute_type="int8",
                                      cpu_threads=min(8, os.cpu_count() or 4), download_root=folder)
            list(self.model.transcribe(np.zeros(RATE, dtype="float32"), language="en")[0])
            self.device = "processor"
        log("model ready on %s" % self.device)

    def transcribe(self, audio, previous):
        if self.s.get("boost_quiet", "no") == "yes":
            # quiet microphone (some tablets): bring the loudest part of the phrase up to a good level
            peak = float(abs(audio).max()) if len(audio) else 0.0
            if 0.0 < peak < 0.3:
                audio = (audio * (0.3 / peak)).astype("float32")
        segs, info = self.model.transcribe(
            audio, language="en", beam_size=5, temperature=0.0,
            condition_on_previous_text=False, without_timestamps=True,
            initial_prompt=build_prompt(self.names, previous))
        parts = []
        for sg in segs:
            if sg.no_speech_prob > 0.6 and sg.avg_logprob < -0.8:
                log("dropped a segment: no_speech %.2f, logprob %.2f" % (sg.no_speech_prob, sg.avg_logprob))
                continue
            if sg.avg_logprob < -1.5:
                log("dropped a segment: logprob %.2f" % sg.avg_logprob)
                continue
            if sg.no_speech_prob > 0.85:  # almost certainly silence, however sure the words look
                continue
            if getattr(sg, "compression_ratio", 0) > 2.4:  # the same words over and over
                continue
            parts.append(sg.text.strip())
        return " ".join(p for p in parts if p)


class FloatButton:
    """A round button that stays on top of every window; a tap starts or stops listening.
    It never takes the focus, so the text box you are typing in keeps it. Drag it to move it."""

    def __init__(self, app):
        self.app = app
        self.size = max(48, int(app.s.get("button_size", "96") or 96))
        self.shown = True
        self.reset = False
        self.drawn = None

    def run(self):
        try:
            self._run()
        except Exception as e:
            log("floating button failed: %r" % (e,))

    def _run(self):
        # inside a virtual environment Tk may not find its support files, so point it at the base install
        for var, sub, probe in (("TCL_LIBRARY", "tcl8.6", "init.tcl"), ("TK_LIBRARY", "tk8.6", "tk.tcl")):
            p = os.path.join(sys.base_prefix, "tcl", sub)
            if not os.environ.get(var) and os.path.exists(os.path.join(p, probe)):
                os.environ[var] = p
        import tkinter as tk
        import ctypes
        app = self.app
        s = self.size
        pos_file = os.path.join(DATA, "button-position.txt")
        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        key = "#010203"
        root.configure(bg=key)
        root.attributes("-transparentcolor", key)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        x, y = sw - s - 40, sh - s - 140
        try:
            a, b = open(pos_file).read().split(",")
            x, y = int(a), int(b)
        except Exception:
            pass
        x = min(max(0, x), sw - s)
        y = min(max(0, y), sh - s)
        root.geometry("%dx%d+%d+%d" % (s, s, x, y))
        cv = tk.Canvas(root, width=s, height=s, bg=key, highlightthickness=0, bd=0)
        cv.pack()
        root.update_idletasks()
        root.update()
        # never take the focus away from the window being typed into
        user32 = ctypes.windll.user32
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
        ex = user32.GetWindowLongPtrW(hwnd, -20)
        user32.SetWindowLongPtrW(hwnd, -20, ex | 0x08000000 | 0x00000080)  # no-activate, tool window
        from ctypes import wintypes
        user32.MonitorFromWindow.restype = ctypes.c_void_p
        user32.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_uint]

        def on_screen():
            return bool(user32.MonitorFromWindow(hwnd, 0))   # 0 = none if it is on no display

        def back_to_corner():
            # a display was unplugged or the layout changed: bring the button home to the bottom right
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            w, h = r.right - r.left, r.bottom - r.top
            sw2, sh2 = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
            user32.SetWindowPos(hwnd, -1, max(0, sw2 - w - 40), max(0, sh2 - h - 140), 0, 0, 0x0001 | 0x0010)
            log("floating button moved back to the corner")

        def draw(state):
            cv.delete("all")
            m = max(4, s // 12)
            if state == "listening":      # blue disc, white centre (same as the tray icon)
                cv.create_oval(m, m, s - m, s - m, fill="#1E64C8", outline="#FFFFFF", width=3)
                c, r = s // 2, s // 8
                cv.create_oval(c - r, c - r, c + r, c + r, fill="#FFFFFF", outline="")
            elif state == "working":      # amber square
                cv.create_rectangle(m, m, s - m, s - m, fill="#E6A000", outline="#FFFFFF", width=3)
            else:                         # grey ring
                cv.create_oval(m, m, s - m, s - m, fill="#F2F2F2", outline="#787878", width=max(6, s // 12))

        st = {"x": 0, "y": 0, "wx": 0, "wy": 0, "moved": False}

        def press(e):
            st.update(x=e.x_root, y=e.y_root, wx=root.winfo_x(), wy=root.winfo_y(), moved=False)

        def move(e):
            dx, dy = e.x_root - st["x"], e.y_root - st["y"]
            if abs(dx) + abs(dy) > 12:
                st["moved"] = True
            if st["moved"]:
                root.geometry("+%d+%d" % (st["wx"] + dx, st["wy"] + dy))
                place_polish(st["wx"] + dx, st["wy"] + dy)

        def release(e):
            if st["moved"]:
                try:
                    with open(pos_file, "w") as f:
                        f.write("%d,%d" % (root.winfo_x(), root.winfo_y()))
                except Exception:
                    pass
            elif app.engine.model is not None:      # a tap, once the speech model is loaded
                threading.Thread(target=app.toggle, daemon=True).start()

        cv.bind("<ButtonPress-1>", press)
        cv.bind("<B1-Motion>", move)
        cv.bind("<ButtonRelease-1>", release)

        # --- the sparkle button: a tap polishes the text in the box you are typing in
        # it is fastened to the start button: always just above it (below it when there is no room), and they move together
        gap = 6
        pw = tk.Toplevel(root)
        pw.overrideredirect(True)
        pw.attributes("-topmost", True)
        pw.configure(bg=key)
        pw.attributes("-transparentcolor", key)
        px, py = x, y - s - gap
        if py < 0:
            py = y + s + gap
        pw.geometry("%dx%d+%d+%d" % (s, s, px, py))

        def place_polish(nx, ny):
            ty = ny - s - gap
            if ty < 0:
                ty = ny + s + gap
            pw.geometry("+%d+%d" % (nx, ty))
        pcv = tk.Canvas(pw, width=s, height=s, bg=key, highlightthickness=0, bd=0)
        pcv.pack()
        pw.update_idletasks()
        pw.update()
        phwnd = user32.GetParent(pw.winfo_id()) or pw.winfo_id()
        pex = user32.GetWindowLongPtrW(phwnd, -20)
        user32.SetWindowLongPtrW(phwnd, -20, pex | 0x08000000 | 0x00000080)  # no-activate, tool window
        pst = {"x": 0, "y": 0, "wx": 0, "wy": 0, "moved": False, "until": 0.0, "drawn": None}

        def draw_polish(busy):
            pcv.delete("all")
            m = max(4, s // 12)
            if busy:                      # amber while it works
                pcv.create_oval(m, m, s - m, s - m, fill="#E6A000", outline="#FFFFFF", width=3)
                col = "#FFFFFF"
            else:                         # pale disc, blue sparkle
                pcv.create_oval(m, m, s - m, s - m, fill="#F2F2F2", outline="#1E64C8", width=max(4, s // 20))
                col = "#1E64C8"

            def star(cx, cy, big, small):
                pts = [cx, cy - big, cx + small, cy - small, cx + big, cy, cx + small, cy + small,
                       cx, cy + big, cx - small, cy + small, cx - big, cy, cx - small, cy - small]
                pcv.create_polygon(pts, fill=col, outline="")

            c = s / 2
            star(c - s * 0.05, c + s * 0.05, s * 0.27, s * 0.07)
            star(c + s * 0.19, c - s * 0.2, s * 0.12, s * 0.035)

        def polish_home():
            # put the sparkle button just above the start button
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            ny = r.top - s - gap
            if ny < 0:
                ny = r.bottom + gap
            user32.SetWindowPos(phwnd, -1, max(0, r.left), ny, 0, 0, 0x0001 | 0x0010)

        def ppress(e):
            pst.update(x=e.x_root, y=e.y_root, wx=root.winfo_x(), wy=root.winfo_y(), moved=False)

        def pmove(e):
            # dragging the sparkle moves the start button too, and the sparkle follows it
            dx, dy = e.x_root - pst["x"], e.y_root - pst["y"]
            if abs(dx) + abs(dy) > 12:
                pst["moved"] = True
            if pst["moved"]:
                root.geometry("+%d+%d" % (pst["wx"] + dx, pst["wy"] + dy))
                place_polish(pst["wx"] + dx, pst["wy"] + dy)

        def prelease(e):
            if pst["moved"]:
                try:
                    with open(pos_file, "w") as f:
                        f.write("%d,%d" % (root.winfo_x(), root.winfo_y()))
                except Exception:
                    pass
            else:
                # a double tap: one stray touch (a finger scrolling past, a palm) must not start a polish
                now = time.time()
                if now - pst.get("tap", 0.0) <= 0.8:
                    pst["tap"] = 0.0
                    pst["until"] = now + float(app.s.get("polish_wait_s", "5")) + 1
                    threading.Thread(target=app.polish_now, daemon=True).start()
                else:
                    pst["tap"] = now

        pcv.bind("<ButtonPress-1>", ppress)
        pcv.bind("<B1-Motion>", pmove)
        pcv.bind("<ButtonRelease-1>", prelease)

        def tick():
            try:
                if app.state != self.drawn:
                    draw(app.state)
                    self.drawn = app.state
                busy = time.time() < pst["until"]
                if busy != pst["drawn"]:
                    draw_polish(busy)
                    pst["drawn"] = busy
                hidden = root.state() == "withdrawn"
                if self.shown and hidden:
                    root.deiconify()
                    pw.deiconify()
                elif not self.shown and not hidden:
                    root.withdraw()
                    pw.withdraw()
                if self.shown:
                    root.attributes("-topmost", True)
                    pw.attributes("-topmost", True)
                    need = self.reset or not on_screen()
                    if need:
                        self.reset = False
                        back_to_corner()
                    if need or not user32.MonitorFromWindow(phwnd, 0):
                        polish_home()
            except Exception:
                pass
            root.after(300, tick)

        draw("off")
        tick()
        log("floating button shown")
        root.mainloop()


class App:
    def __init__(self):
        self.s = load_settings()
        self.state = "off"
        self.button = None
        self.engine = Engine(self.s)
        self.out = Output(all_names(), self.s.get("auto_stops", "no") == "yes", make_boundary(self.s))
        self.dict_seen = None   # (size, time) of this PC's copy when it was last loaded
        self.q = queue.Queue()
        self.listening = False
        self.busy = False
        self.stream = None
        self.worker = None
        self.icon = None
        self.selected = False   # true just after the spoken "select all"
        self.hold_until = 0.0   # nothing is typed or deleted before this time (a polish is pasting)
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
        self.state = state
        try:
            self.icon.icon = self.img(state)
            self.icon.title = {"listening": "ChatRite Dictate: listening", "working": "ChatRite Dictate: working",
                               "off": "ChatRite Dictate: off (%s to start)" % self.s.get("hotkey")}[state]
        except Exception:
            pass

    def polish_now(self):
        # same signal as the spoken word "polish": ChatRite picks the file up and polishes the text box
        try:
            with open(os.path.join(DATA, "polish.now"), "w", encoding="utf-8") as f:
                f.write("now")
            log("polish asked for (button)")
            self.out.last = "."  # the polished text ends a sentence, and the next phrase follows a space
            self.out.clear_tail()  # the text was replaced
            # speech heard meanwhile waits in the queue until the paste has finished, as with the spoken "polish"
            self.hold_until = time.time() + float(self.s.get("polish_wait_s", "5"))
        except Exception as e:
            log("polish button failed: %r" % (e,))

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
                        min_speech_s=int(self.s.get("min_speech_ms", "300")) / 1000.0,
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

    def do_delete(self, cmd):
        """Spoken deleting, counted from the text Dictate typed itself (see Output.pop_phrase and pop_words)."""
        kind, n = cmd
        o = self.out
        time.sleep(0.15)                      # let the text typed just before land in the box first
        selected = self.selected              # "select all" came just before
        self.selected = False
        if kind == "select_all":
            select_field()
            self.selected = True
            log("selected all")
            return
        if kind == "undo":
            press_keys([0x11, 0x5A])
            o.clear_tail()                    # what the editor undid is unknown
            o.last = ""
            log("undo")
            return
        if kind == "delete_that" and selected:
            press_backspace(1)                # removes the selection
            o.clear_tail()
            o.last = "\n"
            log("deleted the selection")
            return
        if kind == "delete_all":
            # select the whole text box, then Backspace (not Delete: in a file list Backspace only goes up a folder,
            # Delete would bin the files)
            select_field()
            press_backspace(1)
            o.clear_tail()
            o.last = "\n"  # an empty box: the next phrase starts with a capital letter
            log("deleted everything")
            return
        count = o.pop_phrase() if kind == "delete_that" else o.pop_words(n)
        if count:
            press_backspace(count)
            rest = o.tail[-200:].strip()
            o.last = rest
            log("deleted %d characters (%s)" % (count, "last phrase" if kind == "delete_that" else "%d word(s)" % n))
        elif kind == "delete_words":
            # nothing typed by Dictate is on record (typed by hand, pasted or polished): let the editor count the words
            for _ in range(n):
                press_keys([0x11, 0x08])
            o.last = ""
            log("deleted %d word(s) with Ctrl+Backspace" % n)
        else:
            log("nothing to delete: Dictate has typed nothing since it started listening")

    def handle(self, audio):
        t0 = time.time()
        self.set_state("working")
        try:
            text = self.engine.transcribe(audio, self.out.last)
            secs = time.time() - t0
            wait = self.hold_until - time.time()
            if wait > 0:
                time.sleep(wait)   # a polish is still pasting: do not type or delete on top of it
            cmd = parse_command(text) if text else None
            if self.selected and not (cmd and cmd[0] in ("delete_that", "select_all")):
                # typing or another command replaces the selection, so what was typed before is gone
                self.selected = False
                self.out.clear_tail()
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
                self.out.clear_tail()  # the pasted length is unknown
            elif cmd and cmd[0] in ("delete_that", "delete_words", "delete_all", "select_all", "undo"):
                self.do_delete(cmd)
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
                self.out.clear_tail()  # the text was replaced
            else:
                typed = self.out.prepare(text)
                if typed:
                    type_text(typed)
                    self.out.remember(typed)
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

    # --- personal dictionary, shared through a synced folder
    def refresh_dictionary(self):
        shared = find_shared_dictionary(self.s.get("shared_dictionary", ""))
        try:
            status = sync_dictionary(DICT_LOCAL, shared, DICT_BASE)
        except Exception as e:
            status = "sync failed"
            log("dictionary sync failed: %r" % (e,))
        try:
            st = os.stat(DICT_LOCAL)
            seen = (st.st_size, st.st_mtime)
        except Exception:
            seen = None
        if seen != self.dict_seen:
            d = read_dictionary(DICT_LOCAL)
            names = load_vocab()
            for n in dictionary_names(d):
                if n not in names:
                    names.append(n)
            self.out.set_dictionary(d, names)
            self.engine.names = names
            self.dict_seen = seen
            log("dictionary: %d entries, %d usable here (%s)" % (len(d), len(active_entries(d)), status))
        return status

    def dictionary_loop(self):
        while True:
            self.refresh_dictionary()
            time.sleep(60)

    def edit_dictionary(self):
        shared = find_shared_dictionary(self.s.get("shared_dictionary", ""))
        path = DICT_LOCAL
        if shared and os.path.exists(shared):
            path = shared
        elif not os.path.exists(DICT_LOCAL):
            try:
                write_dictionary(DICT_LOCAL, {})
            except Exception:
                return
        try:
            subprocess.Popen(["notepad.exe", path])
        except Exception:
            pass

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
        threading.Thread(target=self.dictionary_loop, daemon=True).start()
        if self.s.get("floating_button", "no") == "yes":
            self.button = FloatButton(self)
            threading.Thread(target=self.button.run, daemon=True).start()

    def toggle_button(self):
        if self.button is not None:
            self.button.shown = not self.button.shown

    def home_button(self):
        if self.button is not None:
            self.button.shown = True
            self.button.reset = True

    def run(self):
        import pystray
        menu = pystray.Menu(
            pystray.MenuItem("Start or stop listening (%s)" % self.s.get("hotkey"), lambda i, it: self.toggle(), default=True),
            pystray.MenuItem("Show or hide the floating button", lambda i, it: self.toggle_button()),
            pystray.MenuItem("Bring the floating button back to the corner", lambda i, it: self.home_button()),
            pystray.MenuItem("Edit my words and names",lambda i, it: os.startfile(VOCAB) if os.path.exists(VOCAB) else None),
            pystray.MenuItem("Edit my dictionary (shared)", lambda i, it: self.edit_dictionary()),
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
    try:  # if the program ever dies hard, leave a note of where (no text of yours is in it)
        import faulthandler
        global _crash_file
        _crash_file = open(os.path.join(DATA, "dictate-crash.txt"), "a")
        faulthandler.enable(file=_crash_file, all_threads=True)
    except Exception:
        pass
    try:  # sharp, correctly sized floating button on high-resolution screens
        import ctypes
        try:  # per-monitor aware, so the button keeps its size when displays come and go
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass
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
