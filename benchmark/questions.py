"""Benchmark questions shared by every version (v0-v2).

Each question:
  id      unique id
  type    "explain" | "debug" | "complete"
  code    the code the user is looking at
  ask     what the user asks about it
  check   how we grade the answer:
            {"kind": "tests", "entry": <function name>, "tests": <python asserts>}
            {"kind": "keywords", "groups": [[...], [...]]}
              -> every group must have at least one word present in the answer
"""

QUESTIONS = [
    # ------------------------------------------------------------------ EXPLAIN
    {
        "id": "e1", "type": "explain",
        "code": '''def f(xs):
    seen = set()
    out = []
    for x in xs:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out
''',
        "ask": "Explain what this function does.",
        "check": {"kind": "keywords", "groups": [["duplicate", "unique"], ["order"]]},
    },
    {
        "id": "e2", "type": "explain",
        "code": '''def g(a, t):
    lo, hi = 0, len(a) - 1
    while lo <= hi:
        m = (lo + hi) // 2
        if a[m] == t:
            return m
        if a[m] < t:
            lo = m + 1
        else:
            hi = m - 1
    return -1
''',
        "ask": "Explain what this function does.",
        "check": {"kind": "keywords", "groups": [["binary search"], ["sorted"]]},
    },
    {
        "id": "e3", "type": "explain",
        "code": '''from functools import lru_cache

@lru_cache(maxsize=None)
def h(n):
    return n if n < 2 else h(n - 1) + h(n - 2)
''',
        "ask": "Explain what this function does and why the decorator is used.",
        "check": {"kind": "keywords", "groups": [["fibonacci"], ["cache", "memoiz", "memois"]]},
    },
    {
        "id": "e4", "type": "explain",
        "code": '''def k(s):
    return sum(1 for c in s.lower() if c in "aeiou")
''',
        "ask": "Explain what this function does.",
        "check": {"kind": "keywords", "groups": [["vowel"], ["count", "number of"]]},
    },
    {
        "id": "e5", "type": "explain",
        "code": '''def p(s):
    s = "".join(ch.lower() for ch in s if ch.isalnum())
    return s == s[::-1]
''',
        "ask": "Explain what this function does.",
        "check": {"kind": "keywords", "groups": [["palindrome"], ["alphanumeric", "punctuation", "non-alphanumeric", "letters and digits", "case"]]},
    },
    {
        "id": "e6", "type": "explain",
        "code": '''from collections import Counter

def top(text, n=3):
    words = text.lower().split()
    return Counter(words).most_common(n)
''',
        "ask": "Explain what this function does.",
        "check": {"kind": "keywords", "groups": [["word"], ["frequen", "most common", "most_common", "occurr"]]},
    },
    # -------------------------------------------------------------------- DEBUG
    {
        "id": "d1", "type": "debug",
        "code": '''def average(nums):
    total = 0
    for n in nums:
        total += n
    return total / (len(nums) - 1)
''',
        "ask": "This function returns the wrong value. Find and fix the bug.",
        "check": {"kind": "tests", "entry": "average", "tests": '''
assert average([1, 2, 3]) == 2
assert average([10]) == 10
assert average([2, 4, 6, 8]) == 5
'''},
    },
    {
        "id": "d2", "type": "debug",
        "code": '''def factorial(n):
    result = 1
    for i in range(1, n):
        result *= i
    return result
''',
        "ask": "factorial(5) should be 120 but it is wrong. Find and fix the bug.",
        "check": {"kind": "tests", "entry": "factorial", "tests": '''
assert factorial(0) == 1
assert factorial(1) == 1
assert factorial(5) == 120
'''},
    },
    {
        "id": "d3", "type": "debug",
        "code": '''def is_prime(n):
    for i in range(2, n):
        if n % i == 0:
            return True
    return False
''',
        "ask": "This prime checker gives wrong answers. Find and fix the bug(s).",
        "check": {"kind": "tests", "entry": "is_prime", "tests": '''
assert is_prime(2) is True
assert is_prime(13) is True
assert is_prime(15) is False
assert is_prime(1) is False
assert is_prime(0) is False
'''},
    },
    {
        "id": "d4", "type": "debug",
        "code": '''def add_item(item, items=[]):
    items.append(item)
    return items
''',
        "ask": "Calling add_item('a') then add_item('b') returns ['a', 'b'] the second time instead of ['b']. Fix it.",
        "check": {"kind": "tests", "entry": "add_item", "tests": '''
assert add_item("a") == ["a"]
assert add_item("b") == ["b"]
assert add_item("c", ["x"]) == ["x", "c"]
'''},
    },
    {
        "id": "d5", "type": "debug",
        "code": '''def find_max(nums):
    best = 0
    for n in nums:
        if n > best:
            best = n
    return best
''',
        "ask": "find_max([-3, -1, -2]) returns 0. Find and fix the bug.",
        "check": {"kind": "tests", "entry": "find_max", "tests": '''
assert find_max([-3, -1, -2]) == -1
assert find_max([1, 5, 3]) == 5
assert find_max([7]) == 7
'''},
    },
    {
        "id": "d6", "type": "debug",
        "code": '''def search(a, t):
    lo, hi = 0, len(a) - 1
    while lo < hi:
        m = (lo + hi) // 2
        if a[m] == t:
            return m
        if a[m] < t:
            lo = m + 1
        else:
            hi = m - 1
    return -1
''',
        "ask": "search([1, 3, 5], 5) returns -1 even though 5 is in the list. Find and fix the bug.",
        "check": {"kind": "tests", "entry": "search", "tests": '''
assert search([1, 3, 5], 5) == 2
assert search([1, 3, 5], 1) == 0
assert search([1, 3, 5], 4) == -1
assert search([4], 4) == 0
assert search([], 4) == -1
'''},
    },
    # ----------------------------------------------------------------- COMPLETE
    {
        "id": "c1", "type": "complete",
        "code": '''def is_anagram(a: str, b: str) -> bool:
    """Return True if a and b are anagrams, ignoring case and spaces."""
''',
        "ask": "Finish this function.",
        "check": {"kind": "tests", "entry": "is_anagram", "tests": '''
assert is_anagram("Listen", "Silent") is True
assert is_anagram("Dormitory", "dirty room") is True
assert is_anagram("abc", "abd") is False
'''},
    },
    {
        "id": "c2", "type": "complete",
        "code": '''def flatten(lst):
    """Flatten a list nested to any depth. flatten([1, [2, [3, [4]]]]) -> [1, 2, 3, 4]"""
''',
        "ask": "Finish this function.",
        "check": {"kind": "tests", "entry": "flatten", "tests": '''
assert flatten([1, [2, [3, [4]]]]) == [1, 2, 3, 4]
assert flatten([]) == []
assert flatten([[1, 2], [], [3]]) == [1, 2, 3]
'''},
    },
    {
        "id": "c3", "type": "complete",
        "code": '''def chunk(lst, n):
    """Split lst into consecutive lists of size n (the last may be shorter).
    chunk([1, 2, 3, 4, 5], 2) -> [[1, 2], [3, 4], [5]]"""
''',
        "ask": "Finish this function.",
        "check": {"kind": "tests", "entry": "chunk", "tests": '''
assert chunk([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
assert chunk([], 3) == []
assert chunk([1, 2, 3], 3) == [[1, 2, 3]]
'''},
    },
    {
        "id": "c4", "type": "complete",
        "code": '''def roman_to_int(s: str) -> int:
    """Convert a Roman numeral (I, V, X, L, C, D, M) to an integer. 'MCMXCIV' -> 1994"""
''',
        "ask": "Finish this function.",
        "check": {"kind": "tests", "entry": "roman_to_int", "tests": '''
assert roman_to_int("III") == 3
assert roman_to_int("IV") == 4
assert roman_to_int("LVIII") == 58
assert roman_to_int("MCMXCIV") == 1994
'''},
    },
    {
        "id": "c5", "type": "complete",
        "code": '''def merge_intervals(intervals):
    """Merge overlapping [start, end] intervals and return them sorted.
    [[1, 3], [2, 6], [8, 10]] -> [[1, 6], [8, 10]]"""
''',
        "ask": "Finish this function.",
        "check": {"kind": "tests", "entry": "merge_intervals", "tests": '''
assert merge_intervals([[1, 3], [2, 6], [8, 10]]) == [[1, 6], [8, 10]]
assert merge_intervals([[8, 10], [1, 3]]) == [[1, 3], [8, 10]]
assert merge_intervals([[1, 4], [4, 5]]) == [[1, 5]]
assert merge_intervals([]) == []
'''},
    },
    {
        "id": "c6", "type": "complete",
        "code": '''def word_count(text: str) -> dict:
    """Count words case-insensitively, ignoring punctuation (. , ! ?).
    word_count("Hi, hi! Bye.") -> {"hi": 2, "bye": 1}"""
''',
        "ask": "Finish this function.",
        "check": {"kind": "tests", "entry": "word_count", "tests": '''
assert word_count("Hi, hi! Bye.") == {"hi": 2, "bye": 1}
assert word_count("") == {}
assert word_count("A a A") == {"a": 3}
'''},
    },
]
