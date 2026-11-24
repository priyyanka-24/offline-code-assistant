"""v2: project search (RAG = retrieval-augmented generation).

1. Chunk:    split every code file into pieces, about one function/class each
             (Python: `ast`; other languages: 60-line windows overlapping by 10).
2. Embed:    turn each chunk into a vector with `nomic-embed-text` (via Ollama).
3. Store:    keep vectors in a numpy array, saved to <project>/.assistant_index/.
             Only files whose content hash changed are re-embedded.
4. Retrieve: for a question, pick the chunks most useful to the model:
               a) "symbol lookup": definitions of names the selected code uses
                  (e.g. it calls get_price(), so fetch the get_price chunk)
               b) "semantic search": chunks whose vector is closest (cosine)
                  to the vector of the question + code
             then fill up to a character budget.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx
import numpy as np

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")

CODE_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".cpp", ".h", ".hpp",
             ".cs", ".go", ".rb", ".php", ".rs", ".kt", ".swift"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "env", "__pycache__", "out", "dist",
             "build", ".assistant_index", ".vscode", ".idea", ".pytest_cache"}
MAX_FILE_BYTES = 200_000
MAX_FILES = 2000
WINDOW, OVERLAP = 60, 10
INDEX_DIR = ".assistant_index"

PY_KEYWORDS = {"def", "return", "if", "else", "elif", "for", "while", "in", "not", "and", "or",
               "import", "from", "as", "class", "try", "except", "finally", "with", "lambda",
               "None", "True", "False", "is", "pass", "break", "continue", "raise", "yield",
               "self", "print", "len", "range", "int", "str", "float", "list", "dict", "set",
               "sum", "min", "max", "sorted", "round", "open", "isinstance", "enumerate", "zip"}


@dataclass
class Chunk:
    path: str            # relative to the project root, with forward slashes
    start: int           # 1-based first line
    end: int             # 1-based last line
    text: str
    names: list[str] = field(default_factory=list)  # symbols this chunk defines

    @property
    def label(self) -> str:
        return f"{self.path}:{self.start}-{self.end}"


# ---------------------------------------------------------------- chunking
def chunk_python(path: str, src: str) -> list[Chunk]:
    lines = src.splitlines()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return chunk_windows(path, src)
    chunks, covered = [], set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = min([d.lineno for d in node.decorator_list] + [node.lineno])
            end = node.end_lineno or node.lineno
            names = [node.name]
            if isinstance(node, ast.ClassDef):
                names += [n.name for n in node.body
                          if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            chunks.append(Chunk(path, start, end, "\n".join(lines[start - 1:end]), names))
            covered.update(range(start, end + 1))
    # leftover module-level code (constants, data, imports) grouped into runs
    assigned = {}
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name):
                    assigned[t.id] = node.lineno
    run: list[int] = []
    for i in range(1, len(lines) + 2):
        if i <= len(lines) and i not in covered:
            run.append(i)
            continue
        text = "\n".join(lines[run[0] - 1:run[-1]]) if run else ""
        if text.strip() and not all(l.strip().startswith(("import ", "from ", "#")) or not l.strip()
                                    for l in text.splitlines()):
            names = [n for n, ln in assigned.items() if run[0] <= ln <= run[-1]]
            chunks.append(Chunk(path, run[0], run[-1], text, names))
        run = []
    return sorted(chunks, key=lambda c: c.start)


NAME_RE = re.compile(r"(?:function|class|def|interface|struct|fn|func)\s+([A-Za-z_]\w*)"
                     r"|(?:const|let|var)\s+([A-Za-z_]\w*)\s*=")


def chunk_windows(path: str, src: str) -> list[Chunk]:
    lines = src.splitlines()
    chunks = []
    for start in range(0, max(len(lines), 1), WINDOW - OVERLAP):
        part = lines[start:start + WINDOW]
        text = "\n".join(part)
        if text.strip():
            names = [a or b for a, b in NAME_RE.findall(text)]
            chunks.append(Chunk(path, start + 1, start + len(part), text, names))
        if start + WINDOW >= len(lines):
            break
    return chunks


def chunk_file(path: str, src: str) -> list[Chunk]:
    return chunk_python(path, src) if path.endswith(".py") else chunk_windows(path, src)


# --------------------------------------------------------------- embedding
def embed(texts: list[str], kind: str) -> np.ndarray:
    """kind = 'search_document' for chunks, 'search_query' for questions (nomic-embed-text prefixes)."""
    vecs = []
    for i in range(0, len(texts), 32):
        batch = [f"{kind}: {t[:6000]}" for t in texts[i:i + 32]]
        r = httpx.post(f"{OLLAMA_URL}/api/embed", json={"model": EMBED_MODEL, "input": batch,
                                                          "keep_alive": "30m"}, timeout=600)
        r.raise_for_status()
        vecs.extend(r.json()["embeddings"])
    arr = np.array(vecs, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    return arr / np.maximum(norms, 1e-8)  # unit length, so dot product = cosine similarity


# ------------------------------------------------------------------- index
class ProjectIndex:
    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.dir = self.root / INDEX_DIR
        self.chunks: list[Chunk] = []
        self.vecs = np.zeros((0, 768), dtype=np.float32)
        self.hashes: dict[str, str] = {}
        self.lock = threading.Lock()
        self._load()

    # -- persistence
    def _load(self):
        meta, vec_file = self.dir / "index.json", self.dir / "vectors.npy"
        if meta.exists() and vec_file.exists():
            data = json.loads(meta.read_text(encoding="utf-8"))
            if data.get("model") == EMBED_MODEL:
                self.chunks = [Chunk(**c) for c in data["chunks"]]
                self.hashes = data["hashes"]
                self.vecs = np.load(vec_file)

    def _save(self):
        self.dir.mkdir(exist_ok=True)
        (self.dir / ".gitignore").write_text("*\n")
        (self.dir / "index.json").write_text(json.dumps({
            "model": EMBED_MODEL, "hashes": self.hashes,
            "chunks": [asdict(c) for c in self.chunks]}), encoding="utf-8")
        np.save(self.dir / "vectors.npy", self.vecs)

    # -- updating
    def _files(self):
        count = 0
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for name in filenames:
                p = Path(dirpath) / name
                if p.suffix in CODE_EXTS and p.stat().st_size <= MAX_FILE_BYTES:
                    yield p
                    count += 1
                    if count >= MAX_FILES:
                        return

    def _rel(self, p: Path) -> str:
        return p.resolve().relative_to(self.root).as_posix()

    def update(self, only_file: str | None = None) -> dict:
        """Re-index changed files (or just one file). Returns stats."""
        with self.lock:
            if only_file:
                p = Path(only_file).resolve()
                if self.root not in p.parents:
                    return {"changed": 0, "chunks": len(self.chunks)}
                targets = [p] if p.exists() and p.suffix in CODE_EXTS else []
                gone = [] if targets else [self._rel(p)]
            else:
                targets = list(self._files())
                present = {self._rel(p) for p in targets}
                gone = [r for r in self.hashes if r not in present]

            new_chunks, changed = [], []
            for p in targets:
                rel = self._rel(p)
                src = p.read_text(encoding="utf-8", errors="ignore")
                h = hashlib.sha1(src.encode()).hexdigest()
                if self.hashes.get(rel) == h:
                    continue
                changed.append(rel)
                self.hashes[rel] = h
                new_chunks.extend(chunk_file(rel, src))
            for rel in gone:
                self.hashes.pop(rel, None)

            drop = set(changed) | set(gone)
            if drop or new_chunks:
                keep = [i for i, c in enumerate(self.chunks) if c.path not in drop]
                new_vecs = embed([f"# {c.path}\n{c.text}" for c in new_chunks], "search_document") \
                    if new_chunks else np.zeros((0, self.vecs.shape[1]), dtype=np.float32)
                self.chunks = [self.chunks[i] for i in keep] + new_chunks
                self.vecs = np.vstack([self.vecs[keep], new_vecs]) if keep else new_vecs
                self._save()
            return {"changed": len(changed) + len(gone), "chunks": len(self.chunks),
                    "files": len(self.hashes)}

    # -- searching
    def retrieve(self, code: str, question: str = "", file_path: str | None = None,
                 already_sent: str = "", k: int = 3, budget: int = 5000,
                 sent_lines: tuple[int, int] | None = None) -> list[Chunk]:
        if not self.chunks:
            return []
        current = None
        if file_path:
            try:
                current = self._rel(Path(file_path))
            except ValueError:
                pass

        def useful(c: Chunk) -> bool:
            # skip chunks the model already sees (the selection / surrounding lines)
            if c.path != current:
                return True
            if c.text.strip() and c.text.strip() in already_sent:
                return False
            # v4: also skip same-file chunks that overlap the selected lines. The text check
            # alone misses them when the editor has unsaved changes (v3 bug: a 95-line file
            # got lines 1-60 of itself sent back as "related code").
            if sent_lines and c.start <= sent_lines[1] and c.end >= sent_lines[0]:
                return False
            return True

        # a) symbol lookup: names used but not defined in the selected code
        used = set(re.findall(r"[A-Za-z_]\w*", code)) - PY_KEYWORDS
        defined = set(re.findall(r"(?:def|class)\s+([A-Za-z_]\w*)", code))
        wanted = used - defined
        by_symbol = [c for c in self.chunks if useful(c) and wanted & set(c.names)]

        # v4: one hop further. If a fetched chunk uses a name defined elsewhere in the
        # same file, fetch that too (v2 miss x5: got get_price but not the PRODUCTS
        # table it reads, so the model invented the price).
        have = {c.label for c in by_symbol}
        hop = []
        for c in by_symbol:
            inner = set(re.findall(r"[A-Za-z_]\w*", c.text)) - PY_KEYWORDS - set(c.names) - wanted
            for d in self.chunks:
                if (d.path == c.path and d.label not in have and useful(d)
                        and inner & set(d.names)):
                    hop.append(d)
                    have.add(d.label)
        by_symbol += hop

        # b) semantic search: top-k, and only chunks almost as similar as the best one
        q = embed([f"{question}\n{code}"], "search_query")[0]
        scores = self.vecs @ q
        order = [int(i) for i in np.argsort(-scores) if useful(self.chunks[int(i)])]
        best = float(scores[order[0]]) if order else 0.0
        by_meaning = [self.chunks[i] for i in order[:k] if scores[i] >= max(0.5, best - 0.08)]

        picked, used_chars, seen = [], 0, set()
        for c in by_symbol + by_meaning:
            if c.label in seen or used_chars + len(c.text) > budget:
                continue
            picked.append(c)
            seen.add(c.label)
            used_chars += len(c.text)
        return picked


_indexes: dict[str, ProjectIndex] = {}
_indexes_lock = threading.Lock()


def get_index(root: str) -> ProjectIndex:
    key = str(Path(root).resolve()).lower()
    with _indexes_lock:
        fresh = key not in _indexes
        if fresh:
            _indexes[key] = ProjectIndex(root)
    if fresh:  # first use since the server started: catch up on files changed while it was off
        _indexes[key].update()
    return _indexes[key]
