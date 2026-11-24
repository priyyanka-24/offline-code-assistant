"""v3: grey inline suggestions (autocomplete) using fill-in-the-middle (FIM).

The model sees the code BEFORE the cursor (prefix) and AFTER it (suffix) and writes
only what belongs in between. Speed tricks:
  - small model (qwen2.5-coder:1.5b-base) instead of the 6.7B chat model
  - short context: last ~60 lines before / ~20 lines after the cursor (sent by the extension)
  - short output: at most 64 tokens, stop at a blank line
  - LRU cache: same prefix+suffix -> instant answer
  - the extension waits 300 ms after typing stops and cancels outdated requests
"""
from __future__ import annotations

import csv
import hashlib
import os
import time
from collections import OrderedDict
from pathlib import Path

import httpx

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
AUTOCOMPLETE_MODEL = os.environ.get("AUTOCOMPLETE_MODEL", "qwen2.5-coder:1.5b-base")
MAX_PREFIX, MAX_SUFFIX = 3000, 1000   # characters
NUM_PREDICT = 64
LOG_FILE = Path(__file__).resolve().parent.parent / "results" / "autocomplete_log.csv"

# Each model family marks "before / after / fill here" with its own special tokens.
FIM_TEMPLATES = {
    "qwen": ("<|fim_prefix|>{prefix}<|fim_suffix|>{suffix}<|fim_middle|>",
             ["<|endoftext|>", "<|fim_prefix|>", "<|fim_suffix|>", "<|fim_middle|>",
              "<|file_sep|>", "<|im_end|>"]),
    "deepseek": ("<｜fim▁begin｜>{prefix}<｜fim▁hole｜>{suffix}<｜fim▁end｜>",
                 ["<｜fim▁begin｜>", "<｜fim▁hole｜>", "<｜fim▁end｜>", "<|EOT|>"]),
    "codellama": ("<PRE> {prefix} <SUF>{suffix} <MID>", ["<EOT>"]),
}


def template_for(model: str):
    for key, tpl in FIM_TEMPLATES.items():
        if key in model:
            return tpl
    return FIM_TEMPLATES["qwen"]


class LRUCache:
    def __init__(self, size: int = 256):
        self.size, self.data = size, OrderedDict()

    def get(self, key):
        if key in self.data:
            self.data.move_to_end(key)
            return self.data[key]
        return None

    def put(self, key, value):
        self.data[key] = value
        self.data.move_to_end(key)
        if len(self.data) > self.size:
            self.data.popitem(last=False)


_cache = LRUCache()
_client = httpx.Client(timeout=60)


def clean(completion: str, suffix: str) -> str:
    """Trim the model output so it fits nicely at the cursor."""
    text = completion.rstrip()
    # drop text the model repeated from right after the cursor, e.g. a closing ")"
    first_after = suffix.split("\n", 1)[0].strip()
    if first_after and text.endswith(first_after):
        text = text[: -len(first_after)].rstrip()
    return text


def complete(prefix: str, suffix: str, model: str | None = None, use_cache: bool = True) -> dict:
    model = model or AUTOCOMPLETE_MODEL
    prefix, suffix = prefix[-MAX_PREFIX:], suffix[:MAX_SUFFIX]
    key = hashlib.sha1(f"{model}\0{prefix}\0{suffix}".encode()).hexdigest()
    t0 = time.perf_counter()
    hit = _cache.get(key) if use_cache else None
    if hit is not None:
        return {"completion": hit, "cached": True, "model_ms": 0,
                "server_ms": round((time.perf_counter() - t0) * 1000)}

    tpl, stops = template_for(model)
    body = {
        "model": model,
        "prompt": tpl.format(prefix=prefix, suffix=suffix),
        "raw": True,          # we wrote the special FIM tokens ourselves
        "stream": False,
        "keep_alive": "30m",
        "options": {"temperature": 0, "num_predict": NUM_PREDICT, "num_ctx": 2048,
                    "stop": stops + ["\n\n"]},
    }
    r = _client.post(f"{OLLAMA_URL}/api/generate", json=body)
    r.raise_for_status()
    data = r.json()
    text = clean(data.get("response", ""), suffix)
    _cache.put(key, text)
    return {"completion": text, "cached": False,
            "model_ms": round(data.get("total_duration", 0) / 1e6),
            "server_ms": round((time.perf_counter() - t0) * 1000)}


def log_event(row: dict):
    """Append a shown/accepted event so we can compute latency and acceptance rate."""
    LOG_FILE.parent.mkdir(exist_ok=True)
    new = not LOG_FILE.exists()
    fields = ["time", "event", "id", "latency_ms", "cached", "chars", "language", "model"]
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow({"time": time.strftime("%Y-%m-%d %H:%M:%S"), **row})
