"""Backend: FastAPI between the VS Code extension and Ollama.

Run from the project folder:
    .\\.venv\\Scripts\\python.exe -m uvicorn server.app:app --port 8000

Endpoints:
    POST /explain /debug /complete  -> stream plain text back
                                       (header X-Context-Sources lists the project code used)
    POST /edit                      -> Change Code: JSON with the new code        [v4]
    POST /index                     -> (re)index the project, or one saved file   [v2]
    GET  /health                    -> checks Ollama and loads the model into memory
"""
import asyncio
import json
import os
import time

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from server import autocomplete as ac
from server import edit as ed
from server.rag import Chunk, get_index

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.environ.get("ASSISTANT_MODEL", "deepseek-coder:6.7b")
OPTIONS = {"temperature": 0, "seed": 42, "num_ctx": 4096}
KEEP_ALIVE = "30m"  # keep the model in memory between requests

SYSTEM = ("You are a senior software developer helping a student inside VS Code. "
          "Be accurate and concise. Use markdown, and put code in fenced code blocks.")

TASKS = {
    "explain": ("Explain what the SELECTED CODE does. Start with a one-sentence summary, then "
                "explain the key steps. If it uses a well-known algorithm or technique, name it. "
                "Only explain the selected code: use the reference code just to understand it, "
                "and point out if the selected code would behave unexpectedly."),
    "debug": ("Find the bug(s) in the SELECTED CODE. Check how it uses functions and data from the "
              "reference code, since the bug may come from a wrong assumption about them. Explain "
              "each bug in 1-2 lines, then give the full corrected code in a single code block. "
              "Make the smallest fix; keep the same function names and signatures."),
    "complete": ("Complete the SELECTED CODE. Give the full function in a single code block, keep "
                 "the given name, signature and imports, and use the project's existing functions "
                 "and data exactly as defined in the reference code. Handle edge cases such as "
                 "empty input."),
    "edit": ed.TASK,  # v4: Change Code
}

app = FastAPI(title="Local AI Coding Assistant", version="0.4.0")


class AskRequest(BaseModel):
    code: str                       # the selection (or whole file)
    question: str = ""              # optional extra instruction from the user
    language: str = "python"
    context: str | None = None      # surrounding lines from the same file
    file_path: str | None = None
    project_root: str | None = None  # v2: search this project for related code
    use_rag: bool = True             # False = behave like v1 (for the benchmark comparison)
    start_line: int | None = None    # v4: 1-based lines of `code` in file_path, so search can
    end_line: int | None = None      #     skip same-file chunks the model already sees


class IndexRequest(BaseModel):
    project_root: str
    file_path: str | None = None     # just this file (on save); omit for the whole project


def build_messages(mode: str, req: AskRequest, related: list[Chunk]) -> list[dict]:
    lang = req.language or ""
    parts = []
    if related:
        blocks = "\n\n".join(f"# {c.label}\n{c.text}" for c in related)
        parts.append("Related code from other parts of the project (reference only):\n"
                     f"```{lang}\n{blocks}\n```")
    if req.context and req.context.strip() != req.code.strip():
        name = os.path.basename(req.file_path) if req.file_path else "the current file"
        parts.append(f"Surrounding code from {name} (reference only, do not explain it):\n"
                     f"```{lang}\n{req.context}\n```")
    parts.append(f"SELECTED CODE (this is what the user is asking about):\n```{lang}\n{req.code}\n```")
    parts.append(TASKS[mode])
    if req.question:
        parts.append(f"CHANGE REQUESTED: {req.question}" if mode == "edit" else req.question)
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": "\n\n".join(parts)}]


def find_related(req: AskRequest) -> list[Chunk]:
    if not (req.use_rag and req.project_root and os.path.isdir(req.project_root)):
        return []
    try:
        index = get_index(req.project_root)
        return index.retrieve(req.code, req.question, req.file_path,
                              already_sent=(req.context or "") + "\n" + req.code,
                              sent_lines=(req.start_line, req.end_line)
                              if req.start_line and req.end_line else None)
    except httpx.HTTPError as e:  # embedding model missing / Ollama down: answer without search
        print(f"[rag] search skipped: {e}", flush=True)
        return []


async def stream_ollama(messages: list[dict], mode: str):
    body = {"model": MODEL, "messages": messages, "stream": True,
            "options": OPTIONS, "keep_alive": KEEP_ALIVE}
    t0 = time.perf_counter()
    first = None
    try:
        async with httpx.AsyncClient(timeout=600) as client:
            for attempt in range(3):
                async with client.stream("POST", f"{OLLAMA_URL}/api/chat", json=body) as r:
                    if r.status_code == 500 and attempt < 2:  # model failed to load, retry
                        await r.aread()
                        await asyncio.sleep(5)
                        continue
                    if r.status_code != 200:
                        msg = (await r.aread()).decode(errors="ignore")
                        yield f"\n\n**Ollama error {r.status_code}:** {msg}"
                        return
                    async for line in r.aiter_lines():
                        if not line:
                            continue
                        data = json.loads(line)
                        text = data.get("message", {}).get("content", "")
                        if text:
                            if first is None:
                                first = time.perf_counter() - t0
                            yield text
                        if data.get("done"):
                            break
                    break
    except httpx.ConnectError:
        yield "\n\n**Cannot reach Ollama.** Start the Ollama app and try again."
        return
    total = time.perf_counter() - t0
    print(f"[{mode}] first token {first or total:.2f}s, total {total:.2f}s", flush=True)


def answer(mode: str, req: AskRequest) -> StreamingResponse:
    if not req.code.strip():
        raise HTTPException(400, "No code was sent.")
    t0 = time.perf_counter()
    related = find_related(req)
    if related:
        print(f"[{mode}] search {time.perf_counter() - t0:.2f}s, using: "
              + ", ".join(c.label for c in related), flush=True)
    return StreamingResponse(stream_ollama(build_messages(mode, req, related), mode),
                             media_type="text/plain; charset=utf-8",
                             headers={"X-Context-Sources": json.dumps([c.label for c in related])})


@app.post("/explain")
def explain(req: AskRequest):
    return answer("explain", req)


@app.post("/debug")
def debug(req: AskRequest):
    return answer("debug", req)


@app.post("/complete")
def complete(req: AskRequest):
    return answer("complete", req)


async def chat_once(messages: list[dict]) -> str:
    """Whole answer at once (Change Code needs the complete code before it can show a diff)."""
    body = {"model": MODEL, "messages": messages, "stream": False,
            "options": OPTIONS, "keep_alive": KEEP_ALIVE}
    async with httpx.AsyncClient(timeout=600) as client:
        for attempt in range(3):
            r = await client.post(f"{OLLAMA_URL}/api/chat", json=body)
            if r.status_code == 500 and attempt < 2:  # model failed to load, retry
                await asyncio.sleep(5)
                continue
            r.raise_for_status()
            return r.json()["message"]["content"]
    return ""


def _read_small(path: str | None, limit: int = 500_000) -> str:
    """The saved file the edit goes into (its imports and globals count as 'defined')."""
    try:
        if path and os.path.isfile(path) and os.path.getsize(path) <= limit:
            with open(path, encoding="utf-8", errors="ignore") as f:
                return f.read()
    except OSError:
        pass
    return ""


def _where_defined(name: str, req: AskRequest, related: list[Chunk]) -> str:
    """' (defined in users.py)' if project search knows where `name` lives, so the retry
    can say what to import."""
    chunks = list(related)
    if req.use_rag and req.project_root and os.path.isdir(req.project_root):
        try:
            chunks += get_index(req.project_root).chunks
        except httpx.HTTPError:
            pass
    for c in chunks:
        if name in c.names:
            return f" (defined in {c.path})"
    return ""


@app.post("/edit")
async def edit(req: AskRequest):
    """v4: Change Code. `question` is what the user wants changed. Returns JSON:
    {code, valid, retried, error, sources, seconds}. valid is None for non-Python code
    or when the selection itself is not complete Python (so it cannot be checked)."""
    if not req.code.strip():
        raise HTTPException(400, "No code was sent.")
    if not req.question.strip():
        raise HTTPException(400, "Say what to change.")
    t0 = time.perf_counter()
    related = await run_in_threadpool(find_related, req)
    messages = build_messages("edit", req, related)
    try:
        answer = await chat_once(messages)
    except httpx.ConnectError:
        raise HTTPException(503, "Cannot reach Ollama. Start the Ollama app and try again.")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Ollama error: {e}")
    code = ed.clean(answer, req.code)

    # Python: make sure it parses and doesn't use undefined names. Only if the selection
    # itself parsed, otherwise a half-selected block (e.g. just an `else:` branch) would
    # always look "broken".
    checkable = req.language == "python" and ed.syntax_error(req.code) is None
    file_text = "\n".join([req.context or "", req.code, _read_small(req.file_path)])

    def problem(new_code: str) -> str | None:
        err = ed.syntax_error(new_code)
        if err:
            return f"a syntax error: {err}"
        missing = ed.undefined_names(new_code, file_text)
        if missing:
            return "it uses " + ", ".join(f"`{m}`{_where_defined(m, req, related)}" for m in missing) \
                + " without defining or importing it"
        return None

    error = problem(code) if checkable else None
    retried = False
    if error:
        retried = True
        print(f"[edit] retrying: {error}", flush=True)
        messages += [{"role": "assistant", "content": answer},
                     {"role": "user", "content": f"That code has a problem: {error}. Reply "
                      "with the full corrected code in a single code block, nothing else."}]
        try:
            answer = await chat_once(messages)
            code = ed.clean(answer, req.code)
            error = problem(code)
        except httpx.HTTPError:
            pass  # keep the first answer and report it as not valid

    seconds = round(time.perf_counter() - t0, 2)
    print(f"[edit] {seconds}s, valid={None if not checkable else not error}, retried={retried}, "
          f"using: {', '.join(c.label for c in related) or 'no project code'}", flush=True)
    return {"code": code, "valid": (not error) if checkable else None, "retried": retried,
            "error": error, "sources": [c.label for c in related], "seconds": seconds}


class EditEvent(BaseModel):
    event: str                      # "accepted" | "rejected"
    language: str | None = None
    lines: int | None = None
    instruction_chars: int | None = None
    seconds: float | None = None
    valid: bool | None = None
    retried: bool | None = None


@app.post("/edit/event")
def edit_event(req: EditEvent):
    ed.log_event({**req.model_dump(), "model": MODEL})
    return {"ok": True}


class CompleteRequest(BaseModel):
    prefix: str                     # code before the cursor
    suffix: str = ""                # code after the cursor
    language: str = "python"
    model: str | None = None        # override (used by the benchmark to compare models)
    use_cache: bool = True          # the benchmark turns this off to measure real model speed


class EventRequest(BaseModel):
    event: str                      # "shown" | "accepted"
    id: str
    latency_ms: int | None = None
    cached: bool | None = None
    chars: int | None = None
    language: str | None = None


@app.post("/autocomplete")
def autocomplete(req: CompleteRequest):
    """v3: grey inline suggestion. Returns JSON, not a stream (the editor needs the whole text)."""
    try:
        result = ac.complete(req.prefix, req.suffix, req.model, req.use_cache)
    except httpx.HTTPError as e:
        raise HTTPException(503, f"Autocomplete model not available: {e}")
    return result


@app.post("/autocomplete/event")
def autocomplete_event(req: EventRequest):
    ac.log_event({**req.model_dump(), "model": ac.AUTOCOMPLETE_MODEL})
    return {"ok": True}


@app.post("/index")
async def index(req: IndexRequest):
    if not os.path.isdir(req.project_root):
        raise HTTPException(400, "project_root is not a folder")
    t0 = time.perf_counter()
    try:
        idx = await run_in_threadpool(get_index, req.project_root)
        stats = await run_in_threadpool(idx.update, req.file_path)
    except httpx.HTTPError as e:
        raise HTTPException(503, f"Embedding failed (is nomic-embed-text pulled?): {e}")
    stats["seconds"] = round(time.perf_counter() - t0, 2)
    print(f"[index] {req.file_path or req.project_root}: {stats}", flush=True)
    return stats


@app.get("/health")
async def health():
    """Checks Ollama is up and loads the model so the first real request is fast."""
    try:
        async with httpx.AsyncClient(timeout=600) as client:
            r = await client.post(f"{OLLAMA_URL}/api/generate",
                                  json={"model": MODEL, "keep_alive": KEEP_ALIVE})
            r.raise_for_status()
            # v3: also load the small autocomplete model (ignore if it isn't pulled)
            await client.post(f"{OLLAMA_URL}/api/generate",
                              json={"model": ac.AUTOCOMPLETE_MODEL, "keep_alive": KEEP_ALIVE})
            # v4: check both really stayed in memory. If Ollama unloaded one to make room,
            # every switch between Explain and autocomplete reloads a model (17 s first token in v3).
            ps = (await client.get(f"{OLLAMA_URL}/api/ps")).json()
    except httpx.HTTPError as e:
        raise HTTPException(503, f"Ollama not ready: {e}")
    loaded = [m["name"] for m in ps.get("models", [])]
    missing = [m for m in (MODEL, ac.AUTOCOMPLETE_MODEL) if m not in loaded]
    warning = None
    if missing:
        warning = (f"Ollama unloaded {', '.join(missing)} to make room. Set the environment "
                   "variable OLLAMA_MAX_LOADED_MODELS=3, restart Ollama, and close other big apps.")
        print(f"[health] WARNING: {warning}", flush=True)
    return {"ok": True, "model": MODEL, "autocomplete_model": ac.AUTOCOMPLETE_MODEL,
            "loaded": loaded, "warning": warning}
