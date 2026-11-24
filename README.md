# Local AI Coding Assistant

A coding helper for VS Code that runs fully on your own laptop. Your code never goes to the internet.

It can:
- **Explain Code**: tell you what the selected code does
- **Find Bug**: find mistakes and give a fix
- **Grey suggestions**: suggest the rest of a line while you type (press Tab to accept)
- **Change Code**: change selected code the way you ask, and let you accept or reject it

It is built in small versions (v0 → v4). Every version is tested with the same tests, so we can see if it got better.

## Results so far

| Version | What it added | Result |
|---|---|---|
| v0 | Test set, model asked directly | 16/18 correct, about 13 s per answer |
| v1 | VS Code extension + server | 17/18 correct |
| v2 | Project search (finds related code in other files) | Cross-file questions: 1/8 → 5/8. Normal tests: 18/18 |
| v3 | Grey suggestions while typing | 0.35 s per suggestion, 45% useful |
| v4 | Bug fixes + Change Code | Change Code: 10/12 correct, about 3 s |

All details are in [RESULTS_LOG.md](RESULTS_LOG.md).

## Authors

| Name | Roll No. | Branch |
|---|---|---|
| Priyanka Anand | 24UCC024 | Communication and Computer Engineering |
| Ayush Raj | 24UCS027 | Computer Science and Engineering |

## Development history

The project was built step by step in versions v0 to v4 between **17 and 24 November 2026**. Each version was tested before moving on. The dates, results and screenshots for every version are in [RESULTS_LOG.md](RESULTS_LOG.md).
This GitHub repository was created after v4. Changes from now on are added as separate commits.

## What you need

- **Ollama** with these 3 models (check with `ollama list`):
  - `deepseek-coder:6.7b` (answers questions)
  - `qwen2.5-coder:1.5b-base` (grey suggestions)
  - `nomic-embed-text` (project search)
- **Python** environment in `.venv`. Create it with:
  ```powershell
  python -m venv .venv
  .\.venv\Scripts\python.exe -m pip install -r requirements.txt
  ```
- **Node.js**, to build the extension. Run `npm install` once inside the `extension` folder.
- Set this once, so Ollama keeps all 3 models in memory:
  ```powershell
  setx OLLAMA_MAX_LOADED_MODELS 3
  ```
  Then quit Ollama and open it again.

## How to start

1. Open PowerShell in the project folder and start Ollama + the server together:
   ```powershell
   Start-Process "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe"; .\.venv\Scripts\python.exe -m uvicorn server.app:app --port 8000
   ```
   Leave this window open.
2. Open the project in VS Code and press **F5**.
   A second VS Code window opens with the `samples/` folder.
3. Check the bottom-right corner. You should see something like `Local AI: 4 files · 12 chunks`.
   That means it is working.

To stop: press `Ctrl+C` in the server window, then quit Ollama from the taskbar tray.

## How to use it

| Feature | How |
|---|---|
| Explain Code | Select code → right-click → **Explain Code** |
| Find Bug | Select code → right-click → **Find Bug** |
| Grey suggestions | Just type. Press **Tab** to accept, or keep typing to ignore |
| Change Code | Select code → right-click → **Change Code** (or `Ctrl+Alt+E`) → type what to change → check the side-by-side view → **Accept** or **Reject** |

Good files to try: `samples/demo.py` (has 3 planted bugs) and `samples/report.py` (its bug is caused by another file).

## How to run the tests

The server must be running first.

| Test | Command |
|---|---|
| v0: model alone, no server | `.\.venv\Scripts\python.exe eval.py --target ollama --tag v0` |
| 18 normal questions | `.\.venv\Scripts\python.exe eval.py --target server --tag v2` |
| 8 cross-file questions | `.\.venv\Scripts\python.exe eval.py --target server --tag v2-cross --questions benchmark.crossfile` |
| Same, with search off | add `--no-rag` and change the tag, e.g. `--tag v1-cross` |
| Grey suggestions (small model) | `.\.venv\Scripts\python.exe eval_autocomplete.py --tag v3` |
| Grey suggestions (big model) | `.\.venv\Scripts\python.exe eval_autocomplete.py --tag v3-big --model deepseek-coder:6.7b` |
| Your real accept rate for suggestions | `.\.venv\Scripts\python.exe eval_autocomplete.py --usage` |
| 12 Change Code tasks | `.\.venv\Scripts\python.exe eval.py --target edit --tag v4-edit --questions benchmark.edits` |
| Same, with search off | add `--no-rag` and use `--tag v4-edit-norag` |

Tips:
- Run only some questions: `--only e1,d1`
- Use a server on another port: `$env:SERVER_URL = "http://127.0.0.1:8001"`
- Results are saved in `results/` as `<tag>.csv`, `<tag>_summary.json` and `<tag>_responses.jsonl`.

### How answers are marked
- **Find Bug / Complete / Change Code**: the code from the answer is run with small tests (`assert`). It passes only if all tests pass.
- **Explain**: the answer must contain certain key words. Example: question e1 must say "duplicate" or "unique", and also "order".

## What is in each folder

| File / folder | What it does |
|---|---|
| `extension/src/extension.ts` | The VS Code extension: right-click menu, side panel, status bar |
| `extension/src/inline.ts` | Grey suggestions while typing |
| `extension/src/edit.ts` | Change Code: input box, side-by-side view, Accept / Reject |
| `server/app.py` | The server between VS Code and Ollama |
| `server/rag.py` | Project search: splits files into pieces and finds the related ones |
| `server/autocomplete.py` | Grey suggestions: small fast model, cache, usage log |
| `server/edit.py` | Change Code: cleans the answer and checks it is valid Python |
| `eval.py` | Runs the tests and saves the results |
| `eval_autocomplete.py` | Tests the grey suggestions |
| `benchmark/questions.py` | 18 normal questions (6 explain, 6 find bug, 6 complete) |
| `benchmark/crossfile.py` | 8 questions that need code from other files |
| `benchmark/edits.py` | 12 Change Code tasks |
| `benchmark/project/` | A small "shop" project used by the cross-file questions |
| `samples/` | Files to try the extension on |
| `results/` | All test results |
| `screenshots/` | Screenshots for the report |

## If something goes wrong

| Problem | Fix |
|---|---|
| Warning: "Ollama unloaded a model" | Run `setx OLLAMA_MAX_LOADED_MODELS 3`, then restart Ollama |
| No `Local AI` in the status bar after F5 | Close the test window, press `Shift+F5`, then `F5` again. Still stuck? Use `Ctrl+F5` |
| "The backend is not running" | Start the server (step 1 of "How to start") |
| "Port 8000 is already in use" | An old server is still running. Close it, or use `--port 8001` |
| Answers are very slow the first time | Normal. The model takes time to load once |
