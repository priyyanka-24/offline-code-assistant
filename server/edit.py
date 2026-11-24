"""v4: Change Code (select code, say what to change, get a new version to accept or reject).

The model's answer is turned into code that can be dropped straight back into the file:
  1. take the code out of the ``` block (or use the whole answer if there is none)
  2. fix the indentation so it matches the selected lines (e.g. a method inside a class)
  3. keep the trailing newline the same as the selection
  4. Python only: check the result parses and uses no undefined names (e.g. a missing
     import); if not, the caller asks the model once more, saying what is wrong
"""
from __future__ import annotations

import ast
import builtins
import csv
import re
import textwrap
import time
from pathlib import Path

LOG_FILE = Path(__file__).resolve().parent.parent / "results" / "edit_log.csv"

TASK = ("Change the SELECTED CODE as the user asks below. Use the reference code to get "
        "names, data and units right. Reply with ONLY the full new version of the selected "
        "code in a single code block, with no explanation. Keep the same indentation, names "
        "and signatures unless the user asks to change them, and do not repeat code that is "
        "outside the selection.")

FENCE_RE = re.compile(r"```[^\n`]*\n(.*?)```", re.S)


def extract_code(answer: str) -> str:
    """The code block from the answer (the longest one, if the model wrote several)."""
    blocks = FENCE_RE.findall(answer)
    if blocks:
        return max(blocks, key=len)
    # unfinished block ("```python\n..." with no closing fence) or no block at all
    text = re.sub(r"^```[^\n]*\n", "", answer.strip())
    return text.rstrip("`").rstrip()


def _indent_of(text: str) -> int | None:
    widths = [len(l) - len(l.lstrip()) for l in text.splitlines() if l.strip()]
    return min(widths) if widths else None


def match_indent(new: str, original: str) -> str:
    """Shift `new` so its least-indented line lines up with the selection's."""
    want, have = _indent_of(original), _indent_of(new)
    if want is None or have is None or want == have:
        return new
    body = textwrap.dedent(new)
    return textwrap.indent(body, " " * want) if want else body


def match_ending(new: str, original: str) -> str:
    new = new.rstrip("\n")
    return new + "\n" if original.endswith("\n") else new


def syntax_error(code: str) -> str | None:
    """None if the code parses as Python, else a short error message."""
    try:
        ast.parse(textwrap.dedent(code))
        return None
    except SyntaxError as e:
        return f"{e.msg} (line {e.lineno})"


BUILTINS = set(dir(builtins))
IDENT_RE = re.compile(r"[A-Za-z_]\w*")


def undefined_names(code: str, file_text: str = "") -> list[str]:
    """Names the new code uses but nothing defines: not the code itself, not builtins, and
    not anywhere in the file it goes into. Catches the "forgot to import it" slip
    (v2 x3 / v4 p3: `except UserNotFound` without importing UserNotFound).
    Deliberately simple and scope-blind, so it only flags names that appear nowhere at all."""
    try:
        tree = ast.parse(textwrap.dedent(code))
    except SyntaxError:
        return []
    used, defined = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            (used if isinstance(node.ctx, ast.Load) else defined).add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.arg):
            defined.add(node.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            defined.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            defined.add(node.name)
    elsewhere = set(IDENT_RE.findall(file_text))
    return sorted(used - defined - BUILTINS - elsewhere)


def clean(answer: str, original: str) -> str:
    return match_ending(match_indent(extract_code(answer), original), original)


def log_event(row: dict):
    """Append an accepted/rejected decision so we can report a real acceptance rate."""
    LOG_FILE.parent.mkdir(exist_ok=True)
    new = not LOG_FILE.exists()
    fields = ["time", "event", "language", "lines", "instruction_chars", "seconds", "valid",
              "retried", "model"]
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow({"time": time.strftime("%Y-%m-%d %H:%M:%S"), **row})
