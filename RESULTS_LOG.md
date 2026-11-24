# Results Log

All real test results, version by version. The final presentation is made from this file and the `results/` folder.

**Computer used:** Windows 11, 15.6 GB RAM.
**Main model:** `deepseek-coder:6.7b` in Ollama (runs about 69% on GPU, 31% on CPU, context 4096).

## Summary

| Version | Main change | Score | Speed |
|---|---|---|---|
| v0 | Test set, model asked directly | 16/18 | first words 2.63 s, full answer 13.14 s |
| v1 | VS Code extension + server | 17/18 | first words 3.09 s, full answer 12.55 s |
| v2 | Project search | 18/18 normal, 5/8 cross-file (was 1/8) | first words 0.71 s, full answer 10.32 s |
| v3 | Grey suggestions | 45% of suggestions useful | 0.35 s per suggestion |
| v4 | Bug fixes + Change Code | Change Code 10/12 (8/12 without search) | 3.3 s per change |

Note: v0 and v1 "first words" times are about 2 s too slow because of the `localhost` problem found in v2. The scores are not affected.

---

## v0: Test set (model asked directly)

**What was built**
- 18 test questions: 6 explain, 6 find bug, 6 complete the code.
- Automatic marking: code answers are run with small tests, explain answers are checked for key words.
- Checked the marking itself: correct solutions pass and the buggy originals fail, so the tests can't give false scores.

**Problems on the way**
- 17 Nov: the first run failed with Ollama error `500`. The model couldn't load with only about 2.5 GB RAM free. Added an automatic retry and a clear error message. *(Good "challenges" slide item.)*

**Results (17 Nov)**
- Quick test (`v0-test`, questions e1 + d1): 2/2, first words 2.64 s, full answer 11.36 s.
- **Full test (`v0`): 16/18 (89%)**

  | Type | Score |
  |---|---|
  | Explain | 6/6 |
  | Find bug | 6/6 |
  | Complete | 4/6 |

  - First words: 2.63 s (median). Full answer: 13.14 s (median), 13.91 s (average).
  - Slowest: explain answers, 13–26 s (long text). Fastest: completions, 4.8–8 s.

**The 2 failures (both real model mistakes)**
- **c4 roman_to_int:** right logic, but it wrote `roman[i]` instead of `roman_values[s[i]]`, so it crashed (`NameError`). A typo.
- **c5 merge_intervals:** right method, but it didn't check for an empty list, so `[]` crashed (`IndexError`). A missed edge case.

**What we learned**
- The model alone is already good at single functions. Its weak spots are small slips and edge cases.
- About 13 s per answer is too slow for typing suggestions, so v3 needs a faster setup.

**Screenshots:** `v0_quick_test.png`, `v0_full_run.png`

---

## v1: Basic assistant

**What was built (17 Nov)**
- VS Code extension: right-click **Explain Code** / **Find Bug**. The answer appears word by word in a side panel, with timing.
- Server (FastAPI) between VS Code and Ollama, with `/explain`, `/debug`, `/complete` and `/health`.
- A different instruction for each task. For example, Find Bug: "explain each bug in 1–2 lines, then give the full fixed code". Complete: "handle edge cases such as empty input".
- Same model and settings as v0 (temperature 0, seed 42, context 4096).

**Also fixed or improved**
- The model stays loaded in memory for 30 minutes, so there is no reload delay between questions.
- A new question cancels the old one, so answers don't get mixed up.
- Big files are cut to 8,000 characters around the cursor, to fit the model's limit.
- Clear error messages: "Cannot reach Ollama", "Cannot reach the backend" plus the command to start it.

**Results (`v1`, through the server): 17/18 (94%), up from 16/18**

| | v0 | v1 |
|---|---|---|
| Explain | 6/6 | 6/6 |
| Find bug | 6/6 | 5/6 |
| Complete | 4/6 | **6/6** |
| First words (median) | 2.63 s | 3.09 s |
| Full answer (median) | 13.14 s | 12.55 s |
| Full answer (average) | 13.91 s | 12.82 s |

- **Fixed:** c4 (no typo this time) and c5 (now handles an empty list, probably thanks to the "handle edge cases" instruction).
- **New failure, d6 binary search:** the model misunderstood the bug and rewrote the whole function in a different style. The rewrite was wrong: `search([1,3,5], 1)` returned -1. The real fix was one character (`<` to `<=`).
  Lesson: small models sometimes rewrite everything instead of making the smallest fix.
- First words got about 0.5 s slower because the prompt is longer and goes through the server. Answers are shorter and more focused, so the full time went down.

**Screenshots**
- `v1_find_bug_panel.png`: Find Bug on `average` (lines 4–9). It correctly found `len(scores) - 1` and fixed it. First words in 1.4 s. The fix is right, but its explanation is a bit off.
- `v1_explain_panel.png`: Explain on lines 21–31. First words 1.4 s, full answer 18.3 s.
  **Problem:** it explained the whole file, not just the selection, because the extra 30 lines around it covered everything. It also didn't notice that `top_students` sorts from lowest to highest (the hidden bug).
- `v1_benchmark.png`: terminal summary of the test run.

---

## v2: Project search

**What was built (17 Nov)**
- The project's files are split into pieces (one function or class each, using Python's `ast`). Other languages use 60-line pieces that overlap by 10 lines.
- Each piece is turned into 768 numbers with `nomic-embed-text`, so similar code can be found. The index is saved in `.assistant_index/`, and a SHA-1 hash tells which files changed.
- When you ask a question, two kinds of search run:
  - **Name search:** finds the code for functions and names your selection uses.
  - **Meaning search:** finds the 3 pieces most similar in meaning.
- Only changed files are re-processed, and a file is updated every time you save it.
- The side panel shows which files were used ("Used project code: file:lines"). The status bar shows the index size.

**Also fixed or improved**
- **`localhost` → `127.0.0.1` (big discovery).** On this Windows PC, every call to `localhost` lost about 2 s, because Windows tries IPv6 first and Ollama only listens on IPv4. The same call took 2.28 s with `localhost` and 0.30 s with `127.0.0.1`. Search went from 2.3 s to 0.3 s, and first words from about 2.6 s to 0.62 s. *(Good "challenges" slide item.)*
- Fixed "explains the whole file": the prompt now marks the SELECTED CODE separately and says "only explain the selected code".
- Added "make the smallest fix" to Find Bug (because of v1's d6 failure).
- Search used to send up to 7 pieces (too much noise). Tuned it to send 1–4 of the right pieces. For example, x3 now gets only `find_user` from `users.py`.
  Similarity scores: right piece about 0.74–0.79, unrelated about 0.55.
- Indexing speed: the shop project (6 files) gives 13 pieces. First build 26.5 s (includes loading the model); re-check with no changes 0.01 s.
- If the search model is missing, the assistant still answers, just without search.

**New test: 8 cross-file questions** (`benchmark/crossfile.py`)
- Based on a small shop project. To answer, the model needs facts from other files:
  - prices are stored in paise
  - `fmt()` only accepts whole numbers
  - discount codes are percentages
  - `find_user` raises `UserNotFound`
  - dates look like 25/12/2024
  - stock is stored under `qty_left`
- Checked: correct answers pass, buggy originals fail, and "guessing without seeing the files" fails.

**Results (17 Nov)**

| | Search OFF (`v1-cross`) | Search ON (`v2-cross`) |
|---|---|---|
| **Total** | **1/8** | **5/8** |
| Complete | 1/4 | 4/4 |
| Find bug | 0/3 | 1/3 |
| Explain | 0/1 | 0/1 |
| First words | 0.71 s | 1.25 s |
| Full answer (median) | 9.35 s | 13.31 s (average 13.97 s) |

- **Without search**, the model guessed wrong about the other files: wrong key `due_date` (real key is `due`), wrong data structure for `PRODUCTS`, missing `qty` in `in_stock()`, passing decimals to `fmt()`, not handling `UserNotFound`, wrong discount maths, unknown notebook price.
- **With search, the 3 failures:**
  - x3 greet: right fix (`except UserNotFound`) but forgot to import `UserNotFound`. A model slip.
  - x4 add_tip: knew `fmt` needs a whole number, but typed `bill.paise` instead of `bill_paise`. A model slip.
  - x5 price_tag: **search miss.** It found `get_price` and `fmt`, but not the `PRODUCTS` table, so the model made up the price. (Fixed in v4.)
- Cost of search: first words +0.54 s, full answer about +4 s (longer prompts give longer answers).
- The search-OFF run used the v2 server with search switched off, so it has the same prompt fixes. The difference is caused by search alone.

**Normal 18 questions (`v2`, search on): 18/18, the first perfect score**
- Explain 6/6, find bug 6/6, complete 6/6.
- First words **0.71 s** (v1: 3.09 s, mostly thanks to the `localhost` fix). Full answer 10.32 s (median), 11.31 s (average).
- d6 now passes, probably thanks to the "make the smallest fix" rule.

**Trying it in VS Code**
- Find Bug on `scholarship` (`report.py`): search found exactly the right code (`load_marks` in `school_utils.py`, which doubles the marks). Search 0.20 s, first words 0.62 s, full answer 10.1 s.
  **But the model still missed the real bug** (the limit 45 should be 90 after doubling).
  Lesson: search gave it the right facts, but a 6.7B model doesn't always use them.

**Screenshots**
- `v2_crossfile_with_rag.png`, `v1_crossfile_no_rag.png`, `v2_standard_benchmark.png`: test results.
- `v2_find_bug_scholarship.png`: Find Bug on `scholarship` (lines 10–13). Status bar: "Local AI: 3 files · 10 chunks". Search was perfect (only `school_utils.py:11-18`). First words 1.3 s, full answer 13.1 s.
  But the model missed the real bug, made up a "missing file" bug, and wrongly said `load_marks` has a try/except.
- `v2_explain_top_students.png`: Explain on `demo.py` lines 21–31. First words 1.7 s, full answer 20.3 s.
  - Better than v1: it now explains only `top_students`, and says it sorts "lowest to highest". But it still says it returns "the top n students", so it describes the bug without pointing it out.
  - New problem: search added 3 unrelated pieces (`school_utils.py:11-18`, `report.py:4-7`, `school_utils.py:4-8`). `demo.py` doesn't use them; they only matched the topic "students and marks".

---

## v3: Grey suggestions

**What was built (17 Nov)**
- Server `/autocomplete`: the model sees the code before and after the cursor and fills in the middle.
- Uses a small, fast model: **qwen2.5-coder:1.5b-base** (986 MB). The 6.7B model is still used for Explain and Find Bug.
- Writes at most 64 tokens and stops at a blank line. Context 2048. Remembers the last 256 answers (cache). Removes text that repeats what is already after the cursor.
- Extension: waits 300 ms after you stop typing, cancels old requests, sends 60 lines before and 20 after the cursor, and only suggests at the end of a line.
- Status bar shows the last speed and how many suggestions you accepted. There is an on/off switch.
- `/health` loads both models when VS Code starts.
- Two ways to measure:
  1. `eval_autocomplete.py` hides 40 real lines and checks if the suggestion matches.
  2. The extension saves every shown and accepted suggestion to `results/autocomplete_log.csv`.

**First quick test:** 6 hidden lines, 282–547 ms each (all under 1 s). Cache hit 0 ms.
Examples: `w.writeheader()` was exactly right. `raise SystemExit(...)` became `raise RuntimeError(...)`: sensible, but not exact.

**Problem noticed:** the very first suggestion took over 60 s while the model loaded, and Ollama **unloaded the 6.7B model** to make room. Switching between Explain and suggestions could cause reload delays. (Confirmed and fixed in v4.)

**Results: small vs big model (40 hidden lines, cache off)**

| | Small 1.5B (`v3`) | Big 6.7B (`v3-big`) |
|---|---|---|
| Exactly right | 11/40 | 14/40 |
| Useful (80%+ similar) | **18/40 (45%)** | 20/40 (50%) |
| Median time | **346 ms** | 3,344 ms |
| 90% of suggestions under | **714 ms** | 4,883 ms |
| Under 1 second | **98%** | 0% |

- **The small model is about 10× faster and only 5 points less useful.** The big model never met the 1-second goal, so the small model is the right choice.
- Real use in VS Code (`--usage`): only 1 suggestion logged so far (327 ms, not accepted). Too few for an accept rate; needs real users.

**Screenshots**
- `v3_big_model_benchmark.png`: big-model test results.
- `v3_ghost_text.png`: typing `def is_even` shows the whole function in grey. **v3 works end to end.**
- `v3_find_bug_large_file.png`: Find Bug on a whole 95-line file with about 9 planted bugs (`v3test.py`).
  - First words **17.0 s**, full answer **104 s** (normally about 1 s / 10 s).
  - Some fixes were right (undefined `total_books`, missing `()` on `save_to_file`), but some were made up, like "add `from v3test import Book`" when `Book` is in the same file.
  - **Search bug found:** it sent part of the same file back as "related code" (`v3test.py:1-60`). The file had syntax errors, so it couldn't be split by function, and the duplicate check missed it because the file had unsaved changes. (Fixed in v4.)
  - The 17 s was probably caused by model swapping plus the very long prompt.
  - Lesson: on a big file with many bugs, the 6.7B model gives believable but partly wrong fixes. Smaller selections work much better.

---

## v4: Bug fixes + Change Code

### Fixes (24 Nov)

| Problem (found in) | Fix | Test |
|---|---|---|
| Same file sent back as "related code" (v3) | VS Code now sends the selected line numbers, and search skips pieces of the same file that overlap them | Whole `v3test.py` with unsaved changes: before, `v3test.py:1-60` was sent back; after, it isn't |
| Search missed the `PRODUCTS` table, x5 (v2) | Search goes one step further: if a found function uses something else in its file, that is fetched too | x5: before it got `catalog.py:10-12` + `money.py:9-13`; after it also gets `catalog.py:1-9` (the `PRODUCTS` table) |
| Ollama unloading the big model (v3) | `/health` now checks which models are really loaded, and VS Code shows a warning if one was dropped | See below |

**Model unloading, confirmed and fixed**
- First check: after loading the small model, **only the small model was still loaded**. Ollama had dropped the 6.7B model. This confirms the v3 suspicion.
- Fix: set `OLLAMA_MAX_LOADED_MODELS=3` and restart Ollama.
- After the fix: **all 3 models stayed loaded together** (`deepseek-coder:6.7b`, `qwen2.5-coder:1.5b-base`, `nomic-embed-text`).
- Still to do: rerun the cross-file test to see if x5 now passes.

### New feature: Change Code (24 Nov)

**How it works**
1. Select code, right-click → **Change Code** (or `Ctrl+Alt+E`), and type what to change.
2. The server uses the same project search as Find Bug and asks the model for only the new code.
3. The answer is cleaned up: code taken out of the answer, indentation matched to your selection.
4. Two checks for Python:
   - Is it valid Python?
   - Does it use any name that is never defined or imported?
   If a check fails, the model gets **one more try**, with the exact problem. Example: "it uses `UserNotFound` (defined in users.py) without importing it".
5. Old and new code open side by side. **Accept** puts it in the file (`Ctrl+Z` undoes it). **Reject** changes nothing.
6. If you typed in the file while waiting, it won't apply the change, for safety.
7. Every Accept and Reject is saved in `results/edit_log.csv`, to measure how often people accept changes.

**New test: 12 Change Code tasks** (`benchmark/edits.py`)
- 7 simple single-file changes.
- 1 change to a method inside a class (checks that the indentation is fixed).
- 4 changes that need facts from the shop project.
- Checked: all 12 original codes fail, and a correct change passes all 12.

**Results**

| | Simple (8) | Needs project (4) | Total | Time (median) |
|---|---|---|---|---|
| No search (`v4-edit-norag`) | 8/8 | **0/4** | 8/12 | 2.9 s |
| Search + valid-Python check (`v4-edit-syntaxonly`) | 8/8 | 1/4 | 9/12 | 3.4 s |
| Search + both checks (`v4-edit`) | 8/8 | **2/4** | **10/12** | 3.3 s |

- **Without search, all 4 project tasks failed**, for the same reasons as in v2: it wrote `$1000.00` (didn't know prices are in paise or about `fmt`), didn't handle `UserNotFound`, and read dates in the wrong format.
- **The "undefined name" check fixed p3.** The first answer forgot to import `UserNotFound`. The retry message said where it is, and the second answer passed. This is the same mistake that failed x3 in v2, now caught automatically.
- **Still failing:**
  - p1: **search miss.** It found `get_price` and `PRODUCTS` but not `fmt`, so it formatted the price by hand (`₹10.0`).
  - p2: **model slip.** Right discount maths, but it returned `1800.0` instead of the whole number `1800`.
- Change Code is much faster than Find Bug (about 3 s vs 10 s), because the answer is only code, with no explanation. (The 15 s on s1 in `v4-edit` was the model loading.)

**Trying it in VS Code**
- The first F5 test window didn't load the extension at all. VS Code's log said the extension system "did not start in 10 seconds". Closing the window and pressing F5 again fixed it. Not caused by our code.
- After that, Change Code worked end to end: side-by-side view, Accept and Reject.
- **Real try on a C file** (`dfs.c`, lines 9–20). Instruction: "change the dfs function to bfs".
  - The window worked as planned: instruction box, side-by-side view, Accept / Reject, and the message showed "not checked" (C is not checked), 18.64 s, and the files used.
  - **But the answer was wrong.** The model only renamed `dfs` to `bfs` (2 lines changed). The code is still a recursive depth-first search; a real breadth-first search needs a queue.
  - **Search problem:** for a C file it used Python files (`school_utils.py:11-18`, `demo.py:11-18`, `v3test.py:51-94`). They only matched by topic. This made the prompt longer and probably the answer slower (18.6 s vs about 3 s in the tests).
  - Lessons: (1) asking for a different algorithm is too big a change for the 6.7B model; small, specific instructions work better. (2) Search should only use files of the same language. *(Fix idea for v4.)*
  - Screenshots: `v4_change_code_input.png` (instruction box), `v4_change_code_diff.png` (side-by-side view with Accept / Reject).

### Still to do in v4
- Fix the `fmt` search miss (p1).
- Rerun the 18 normal and 8 cross-file questions with the v4 fixes.
- Real users: classmates use it and we measure how often they accept suggestions and changes.
