"""ChatRite on the Surface Pro: runs Whisper on the Snapdragon NPU for ChatRite Dictate.

Not part of the self-updating program. It runs in its own native ARM64 Python (the NPU cannot be reached from
the emulated x64 Python that Dictate uses), started and talked to by Dictate when `engine = npu` is set.

Talk: Dictate sends 4 bytes (little-endian count of samples) then that many float32 samples at 16 kHz on stdin.
This program answers with one line of JSON on its real stdout: {"text": "...", "logprob": -0.3, "secs": 0.3}.
It first prints {"ready": true}. It exits when stdin closes. No audio or text is ever written to disk or the log.

Usage: python npu_helper.py <model folder with encoder.onnx and decoder.onnx>
Needs: onnxruntime, onnxruntime-qnn, numpy, transformers (tokenizer and feature extractor only, no torch).
"""
import os
import sys
import json
import struct
import time

# Keep the real stdout for our answers; anything the NPU libraries print goes to stderr instead.
OUT = os.fdopen(os.dup(1), "wb", buffering=0)
os.dup2(2, 1)

import numpy as np
import onnxruntime as ort
import onnxruntime_qnn as q
from transformers import WhisperTokenizer, WhisperFeatureExtractor

DEC_LEN = 200
MASK_NEG = -100.0
VOCAB = 51865
SAMPLES_30S = 16000 * 30


def reply(obj):
    OUT.write((json.dumps(obj) + "\n").encode("utf-8"))


def open_session(path, dev_type):
    devs = [d for d in ort.get_ep_devices() if d.ep_name == "QNNExecutionProvider" and d.device.type == dev_type]
    if not devs:
        raise RuntimeError("no NPU found")
    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    so.add_provider_for_devices(devs, {
        "enable_htp_fp16_precision": "1",
        "htp_performance_mode": "burst",
        "htp_graph_finalization_optimization_mode": "3",
        "offload_graph_io_quantization": "1",
    })
    return ort.InferenceSession(path, sess_options=so)


class Whisper:
    def __init__(self, folder):
        ort.register_execution_provider_library(q.get_ep_name(), q.get_library_path())
        self.tok = WhisperTokenizer.from_pretrained("openai/whisper-base")
        self.fe = WhisperFeatureExtractor.from_pretrained("openai/whisper-base")
        self.enc = open_session(os.path.join(folder, "encoder.onnx"), ort.OrtHardwareDeviceType.NPU)
        self.dec = open_session(os.path.join(folder, "decoder.onnx"), ort.OrtHardwareDeviceType.NPU)
        self.dec_in = {i.name: i for i in self.dec.get_inputs()}
        self.enc_out = [o.name for o in self.enc.get_outputs()]
        self.dec_out = [o.name for o in self.dec.get_outputs()]
        self.logits = [n for n in self.dec_out if "cache" not in n][0]
        self.layers = sum(1 for n in self.dec_in if n.startswith("k_cache_self") and n.endswith("_in"))
        t = self.tok.convert_tokens_to_ids
        self.prefix = [t("<|startoftranscript|>"), t("<|en|>"), t("<|transcribe|>"), t("<|notimestamps|>")]
        self.eot = t("<|endoftext|>")

    def chunk(self, audio):
        feats = self.fe(audio, sampling_rate=16000, return_tensors="np")["input_features"].astype(np.float16)
        cross = dict(zip(self.enc_out, self.enc.run(None, {"input_features": feats})))
        sk = {i: np.zeros(self.dec_in["k_cache_self_%d_in" % i].shape, np.float16) for i in range(self.layers)}
        sv = {i: np.zeros(self.dec_in["v_cache_self_%d_in" % i].shape, np.float16) for i in range(self.layers)}
        mask = np.full((1, 1, 1, DEC_LEN), MASK_NEG, np.float16)
        cur = self.prefix[0]
        toks, lps = [], []
        for n in range(DEC_LEN - 1):
            mask[:, :, :, DEC_LEN - n - 1] = 0.0
            feed = {"input_ids": np.array([[cur]], np.int32), "position_ids": np.array([n], np.int32),
                    "attention_mask": mask}
            for i in range(self.layers):
                feed["k_cache_self_%d_in" % i] = sk[i]
                feed["v_cache_self_%d_in" % i] = sv[i]
            feed.update(cross)
            res = dict(zip(self.dec_out, self.dec.run(None, feed)))
            for i in range(self.layers):
                sk[i] = res["k_cache_self_%d_out" % i]
                sv[i] = res["v_cache_self_%d_out" % i]
            if n + 1 < len(self.prefix):
                cur = self.prefix[n + 1]       # the language and task tokens are fed in, not guessed
                continue
            lg = res[self.logits].reshape(-1)[:VOCAB].astype(np.float32)
            nxt = int(np.argmax(lg))
            if nxt == self.eot:
                break
            lp = float(lg[nxt] - (lg.max() + np.log(np.exp(lg - lg.max()).sum())))
            toks.append(nxt)
            lps.append(lp)
            cur = nxt
        text = self.tok.decode(toks, skip_special_tokens=True).strip()
        return text, (sum(lps) / len(lps) if lps else 0.0)

    def transcribe(self, audio):
        pieces, lps = [], []
        for s in range(0, max(1, len(audio)), SAMPLES_30S):
            text, lp = self.chunk(audio[s:s + SAMPLES_30S])
            if text:
                pieces.append(text)
                lps.append(lp)
        return " ".join(pieces), (min(lps) if lps else 0.0)


def read_exact(f, n):
    buf = b""
    while len(buf) < n:
        b = f.read(n - len(buf))
        if not b:
            return None
        buf += b
    return buf


def main():
    w = Whisper(sys.argv[1])
    w.transcribe(np.zeros(16000, np.float32))   # warm-up, so the first real phrase is not slow
    reply({"ready": True})
    stdin = sys.stdin.buffer
    while True:
        head = read_exact(stdin, 4)
        if head is None:
            return
        n = struct.unpack("<I", head)[0]
        raw = read_exact(stdin, n * 4)
        if raw is None:
            return
        t0 = time.time()
        try:
            text, lp = w.transcribe(np.frombuffer(raw, dtype="<f4"))
            reply({"text": text, "logprob": lp, "secs": round(time.time() - t0, 3)})
        except Exception as e:
            reply({"error": repr(e)[:200]})


main()
