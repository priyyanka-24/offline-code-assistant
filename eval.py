"""Benchmark runner. Every version is scored with this same script.

    python eval.py --target ollama --tag v0      # v0: ask the model directly
    python eval.py --target server --tag v1      # v1+: go through the FastAPI backend

Writes:
    results/<tag>.csv              one row per question
    results/<tag>_responses.jsonl  raw model answers (for debugging / the report)
    results/<tag>_summary.json     totals and latency
"""
import argparse
import csv
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

from benchmark.questions import QUESTIONS

OLLAMA_URL = "http://127.0.0.1:11434"
SERVER_URL = os.environ.get("SERVER_URL", "http://127.0.0.1:8000")
DEFAULT_MODEL = "deepseek-coder:6.7b"
RESULTS = Path(__file__).parent / "results"

FORMAT_HINT = {
    "explain": "",
    "debug": "\n\nReply with the full corrected function in a single ```python code block.",
    "complete": "\n\nReply with the full function in a single ```python code block.",
}


# ----------------------------------------------------------------- targets
def stream_ollama(prompt: str, model: str):
    """v0: send the question straight to Ollama. Yields text chunks."""
    body = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "options": {"temperature": 0, "seed": 42, "num_ctx": 4096},
    }
    for attempt in range(3):
        with httpx.stream("POST", f"{OLLAMA_URL}/api/generate", json=body, timeout=600) as r:
            if r.status_code == 500 and attempt < 2:
                # usually the model failed to load (not enough free RAM); wait and retry
                print(f"  Ollama error: {r.read().decode(errors='ignore')[:200]} -> retrying in 5s")
                time.sleep(5)
                continue
            if r.status_code != 200:
                raise SystemExit(f"Ollama returned {r.status_code}: {r.read().decode(errors='ignore')}")
            yield from _read_ollama_lines(r)
            return


def _read_ollama_lines(r):
        for line in r.iter_lines():
            if not line:
                continue
            data = json.loads(line)
            if data.get("response"):
                yield data["response"]
            if data.get("done"):
                break


USE_RAG = True  # set by --no-rag


def stream_server(q: dict, model: str):
    """v1+: send the question to our FastAPI backend, like the extension does."""
    body = {"code": q["code"], "question": q["ask"] + FORMAT_HINT[q["type"]],
            "language": "python", "file_path": q.get("file_path"),
            "project_root": q.get("project_root"), "use_rag": USE_RAG}
    with httpx.stream("POST", f"{SERVER_URL}/{q['type']}", json=body, timeout=600) as r:
        r.raise_for_status()
        for chunk in r.iter_text():
            if chunk:
                yield chunk


def edit_server(q: dict) -> dict:
    """v4: Change Code. Not streamed; the server returns the whole new code as JSON."""
    body = {"code": q["code"], "question": q["ask"], "language": "python",
            "file_path": q.get("file_path"), "project_root": q.get("project_root"),
            "use_rag": USE_RAG}
    r = httpx.post(f"{SERVER_URL}/edit", json=body, timeout=600)
    r.raise_for_status()
    return r.json()


def build_raw_prompt(q: dict) -> str:
    return f"{q['ask']}\n\n```python\n{q['code']}```{FORMAT_HINT[q['type']]}"


def ask(q: dict, target: str, model: str):
    """Returns (answer, seconds_to_first_token, total_seconds)."""
    gen = stream_ollama(build_raw_prompt(q), model) if target == "ollama" else stream_server(q, model)
    t0 = time.perf_counter()
    first = None
    parts = []
    for chunk in gen:
        if first is None:
            first = time.perf_counter() - t0
        parts.append(chunk)
    total = time.perf_counter() - t0
    return "".join(parts), (first if first is not None else total), total


# ------------------------------------------------------------------ grading
def extract_code(answer: str, entry: str) -> str:
    blocks = re.findall(r"```[a-zA-Z0-9_+-]*\s*\n(.*?)```", answer, re.S)
    with_entry = [b for b in blocks if f"def {entry}" in b]
    if with_entry:
        return with_entry[-1]  # last version is usually the fixed one
    if blocks:
        return "\n\n".join(blocks)
    return answer


def run_tests(code: str, tests: str, project_root: str | None = None) -> tuple[bool, str]:
    # cross-file questions import the sample project (catalog, money, ...)
    setup = f"import sys; sys.path.insert(0, {project_root!r})\n" if project_root else ""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "candidate.py"
        f.write_text(setup + code + "\n\n# ---- benchmark tests ----\n" + tests, encoding="utf-8")
        try:
            p = subprocess.run([sys.executable, "-I", str(f)], cwd=tmp, capture_output=True,
                               text=True, encoding="utf-8", errors="replace",
                               timeout=15, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return False, "timeout"
    if p.returncode == 0:
        return True, ""
    err = (p.stderr.strip().splitlines() or ["error"])[-1]
    return False, err[:200]


def grade(q: dict, answer: str) -> tuple[bool, str]:
    check = q["check"]
    if q["type"] == "edit":  # the answer is already clean code; put it back where it was selected
        code = q["wrap"].replace("{code}", answer) if "wrap" in q else answer
        return run_tests(code, check["tests"], q.get("project_root"))
    if check["kind"] == "keywords":
        text = answer.lower()
        missing = [g for g in check["groups"] if not any(w in text for w in g)]
        return (not missing), ("missing: " + " | ".join("/".join(g) for g in missing)) if missing else ""
    return run_tests(extract_code(answer, check["entry"]), check["tests"], q.get("project_root"))


# --------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["ollama", "server", "edit"], default="ollama",
                    help="edit = v4 Change Code (/edit), use with --questions benchmark.edits")
    ap.add_argument("--tag", default="v0", help="name for the results files, e.g. v0, v1")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--only", help="comma-separated ids, e.g. d1,c4")
    ap.add_argument("--questions", default="benchmark.questions",
                    help="module that defines QUESTIONS, e.g. benchmark.crossfile")
    ap.add_argument("--no-rag", action="store_true",
                    help="server target only: turn project search off (= v1 behaviour)")
    args = ap.parse_args()
    global USE_RAG
    USE_RAG = not args.no_rag

    questions = QUESTIONS
    if args.questions != "benchmark.questions":
        import importlib
        questions = importlib.import_module(args.questions).QUESTIONS
    if args.only:
        wanted = set(args.only.split(","))
        questions = [q for q in questions if q["id"] in wanted]

    RESULTS.mkdir(exist_ok=True)
    print(f"Warming up {args.model} (not timed)...")
    if args.target == "ollama":
        "".join(stream_ollama("Say OK.", args.model))
    else:
        httpx.get(f"{SERVER_URL}/health", timeout=600).raise_for_status()

    rows = []
    with open(RESULTS / f"{args.tag}_responses.jsonl", "w", encoding="utf-8") as log:
        for q in questions:
            extra = {}
            if args.target == "edit":
                t0 = time.perf_counter()
                res = edit_server(q)
                answer = res["code"]
                ttft = total = time.perf_counter() - t0  # not streamed: first = total
                extra = {"valid": res["valid"], "retried": res["retried"],
                         "sources": ";".join(res["sources"])}
            else:
                answer, ttft, total = ask(q, args.target, args.model)
            passed, detail = grade(q, answer)
            rows.append({"id": q["id"], "type": q["type"], "passed": passed,
                         "ttft_s": round(ttft, 2), "total_s": round(total, 2), "detail": detail,
                         **extra})
            log.write(json.dumps({"id": q["id"], "answer": answer, **extra}) + "\n")
            print(f"{q['id']:>4} {q['type']:<9} {'PASS' if passed else 'FAIL'}  "
                  f"first {ttft:5.2f}s  total {total:6.2f}s  {detail}")

    with open(RESULTS / f"{args.tag}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    by_type = {}
    for r in rows:
        t = by_type.setdefault(r["type"], [0, 0])
        t[0] += r["passed"]
        t[1] += 1
    summary = {
        "tag": args.tag, "target": args.target, "model": args.model,
        "questions": args.questions, "rag": args.target in ("server", "edit") and USE_RAG,
        "correct": sum(r["passed"] for r in rows), "total": len(rows),
        "by_type": {k: f"{a}/{b}" for k, (a, b) in by_type.items()},
        "median_first_token_s": round(statistics.median(r["ttft_s"] for r in rows), 2),
        "median_total_s": round(statistics.median(r["total_s"] for r in rows), 2),
        "mean_total_s": round(statistics.mean(r["total_s"] for r in rows), 2),
    }
    (RESULTS / f"{args.tag}_summary.json").write_text(json.dumps(summary, indent=2))
    print("\n" + json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
