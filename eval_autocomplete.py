"""v3 benchmark: how fast are grey suggestions, and how often are they right?

Benchmark mode (repeatable):
    python eval_autocomplete.py --tag v3                                   # small model
    python eval_autocomplete.py --tag v3-big --model deepseek-coder:6.7b   # compare with the big model

  Picks 40 real lines from Python files in this project, hides each one, and asks the
  server to fill the gap (cursor placed after the line's indentation, just like typing).
    exact  = suggestion's first line is exactly the hidden line
    useful = at least 80% similar (difflib), i.e. accepting it saves most of the typing
  Latency is measured like the extension sees it (HTTP round trip), with the cache off.

Usage mode (real typing in VS Code):
    python eval_autocomplete.py --usage
  Summarises results/autocomplete_log.csv: suggestions shown, accepted, acceptance rate, latency.
"""
import argparse
import csv
import difflib
import json
import random
import statistics
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).parent
SERVER_URL = "http://127.0.0.1:8000"
RESULTS = ROOT / "results"
SOURCES = ["benchmark/project/*.py", "samples/*.py", "server/rag.py",
           "server/autocomplete.py", "eval.py"]


def pick_cases(n: int, seed: int = 0):
    candidates = []
    for pattern in SOURCES:
        for f in sorted(ROOT.glob(pattern)):
            lines = f.read_text(encoding="utf-8").splitlines(keepends=True)
            for i, line in enumerate(lines):
                s = line.strip()
                indent = line[: len(line) - len(line.lstrip())]
                if (indent and 8 <= len(s) <= 90 and not s.startswith(("#", '"""', "'''"))
                        and not s.endswith(('"""', "'''"))):
                    prefix = "".join(lines[:i]) + indent
                    suffix = "".join(lines[i + 1:])
                    candidates.append({"file": f.relative_to(ROOT).as_posix(), "line": i + 1,
                                       "prefix": prefix, "suffix": "\n" + suffix, "expected": s})
    random.Random(seed).shuffle(candidates)
    return candidates[:n]


def percentile(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, int(round(p / 100 * (len(values) - 1))))]


def benchmark(args):
    cases = pick_cases(args.n)
    client = httpx.Client(timeout=120)
    print(f"Warming up {args.model or 'default autocomplete model'} (not timed)...")
    client.post(f"{SERVER_URL}/autocomplete", json={"prefix": "def add(a, b):\n    ", "suffix": "",
                                                     "model": args.model, "use_cache": False}).raise_for_status()
    rows = []
    for c in cases:
        t0 = time.perf_counter()
        r = client.post(f"{SERVER_URL}/autocomplete", json={
            "prefix": c["prefix"], "suffix": c["suffix"], "model": args.model, "use_cache": False})
        r.raise_for_status()
        ms = (time.perf_counter() - t0) * 1000
        got = r.json()["completion"].split("\n", 1)[0].strip()
        ratio = difflib.SequenceMatcher(None, got, c["expected"]).ratio()
        row = {"file": c["file"], "line": c["line"], "latency_ms": round(ms),
               "model_ms": r.json()["model_ms"], "exact": got == c["expected"],
               "useful": ratio >= 0.8, "similarity": round(ratio, 2),
               "expected": c["expected"], "got": got}
        rows.append(row)
        mark = "EXACT " if row["exact"] else "useful" if row["useful"] else "miss  "
        print(f"{mark} {ms:6.0f} ms  {c['file']}:{c['line']:<4} want: {c['expected'][:40]:<40} got: {got[:40]}")

    RESULTS.mkdir(exist_ok=True)
    with open(RESULTS / f"{args.tag}_autocomplete.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    lat = [r["latency_ms"] for r in rows]
    summary = {
        "tag": args.tag, "model": args.model or "server default (qwen2.5-coder:1.5b-base)",
        "cases": len(rows),
        "exact": sum(r["exact"] for r in rows), "useful": sum(r["useful"] for r in rows),
        "useful_pct": round(100 * sum(r["useful"] for r in rows) / len(rows)),
        "median_ms": round(statistics.median(lat)), "p90_ms": percentile(lat, 90),
        "under_1s_pct": round(100 * sum(l < 1000 for l in lat) / len(lat)),
    }
    (RESULTS / f"{args.tag}_autocomplete_summary.json").write_text(json.dumps(summary, indent=2))
    print("\n" + json.dumps(summary, indent=2))


def usage():
    log = RESULTS / "autocomplete_log.csv"
    if not log.exists():
        print("No usage yet. Type in VS Code with the extension running first.")
        return
    rows = list(csv.DictReader(open(log, encoding="utf-8")))
    shown = [r for r in rows if r["event"] == "shown"]
    accepted = [r for r in rows if r["event"] == "accepted"]
    lat = [int(r["latency_ms"]) for r in shown if r["latency_ms"]]
    summary = {
        "suggestions_shown": len(shown), "accepted": len(accepted),
        "acceptance_pct": round(100 * len(accepted) / len(shown)) if shown else 0,
        "median_ms": round(statistics.median(lat)) if lat else None,
        "p90_ms": percentile(lat, 90) if lat else None,
        "under_1s_pct": round(100 * sum(l < 1000 for l in lat) / len(lat)) if lat else None,
        "cached_pct": round(100 * sum(r["cached"] == "True" for r in shown) / len(shown)) if shown else 0,
    }
    (RESULTS / "v3_usage_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="v3")
    ap.add_argument("--model", help="override the autocomplete model, e.g. deepseek-coder:6.7b")
    ap.add_argument("-n", type=int, default=40, help="number of hidden lines to test")
    ap.add_argument("--usage", action="store_true", help="summarise real usage from VS Code instead")
    a = ap.parse_args()
    usage() if a.usage else benchmark(a)
