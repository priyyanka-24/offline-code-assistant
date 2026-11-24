"""v4 benchmark: Change Code. Each task = selected code + an instruction + tests.

The server's new code is run with the tests (same grading as debug/complete).
  - s*: single-file changes
  - i1: the selection is an indented method inside a class; the new code is put back
        into the class ("wrap") before testing, so it also checks the indentation fix
  - p*: project changes that need facts from benchmark/project/ (paise, fmt, percent
        discount codes, UserNotFound, dd/mm/yyyy dates)

Run:  python eval.py --target edit --tag v4-edit --questions benchmark.edits
      python eval.py --target edit --tag v4-edit-norag --questions benchmark.edits --no-rag
"""
from pathlib import Path

PROJECT = str(Path(__file__).parent / "project")
FILE = str(Path(PROJECT) / "checkout.py")


def e(id, code, ask, entry, tests, project=False, wrap=None):
    q = {"id": id, "type": "edit", "code": code, "ask": ask,
         "check": {"kind": "tests", "entry": entry, "tests": tests}}
    if project:
        q.update(project_root=PROJECT, file_path=FILE)
    if wrap:
        q["wrap"] = wrap
    return q


QUESTIONS = [
    e("s1", '''def average(xs):
    return sum(xs) / len(xs)
''', "Return 0 for an empty list instead of crashing.", "average", '''
assert average([2, 4]) == 3
assert average([]) == 0
'''),

    e("s2", '''def top_students(scores, n):
    """scores is {name: marks}. Return the names of the n best students."""
    ranked = sorted(scores, key=lambda name: scores[name])
    return ranked[:n]
''', "It returns the lowest scores. Make it return the highest scores first.", "top_students", '''
s = {"a": 50, "b": 90, "c": 70}
assert top_students(s, 2) == ["b", "c"], top_students(s, 2)
assert top_students(s, 1) == ["b"]
'''),

    e("s3", '''def count_word(text, word):
    return text.split().count(word)
''', "Make the count case-insensitive.", "count_word", '''
assert count_word("The cat and the dog", "the") == 2
assert count_word("THE end", "The") == 1
'''),

    e("s4", '''def first_n(xs, n):
    return xs[:n]
''', "Make n optional with a default of 3.", "first_n", '''
assert first_n([1, 2, 3, 4, 5]) == [1, 2, 3]
assert first_n([1, 2, 3, 4], 2) == [1, 2]
'''),

    e("s5", '''def set_age(person, age):
    person["age"] = age
    return person
''', "Raise ValueError if age is negative.", "set_age", '''
assert set_age({}, 5) == {"age": 5}
try:
    set_age({}, -1)
    raise AssertionError("no ValueError")
except ValueError:
    pass
'''),

    e("s6", '''def min_max(xs):
    return min(xs), max(xs)
''', 'Return a dict with keys "min" and "max" instead of a tuple.', "min_max", '''
assert min_max([3, 1, 2]) == {"min": 1, "max": 3}
'''),

    e("s7", '''def total(values):
    t = 0
    for v in values:
        t += v
    return t
''', "Skip None values instead of crashing.", "total", '''
assert total([1, None, 2]) == 3
assert total([]) == 0
'''),

    e("i1", '''    def withdraw(self, amount):
        self.balance -= amount
        return True
''', "Do not allow the balance to go below zero: return False and leave the balance "
     "unchanged in that case.", "Account", '''
a = Account(100)
assert a.withdraw(30) is True and a.balance == 70
assert a.withdraw(500) is False and a.balance == 70
''', wrap='''class Account:
    def __init__(self, balance):
        self.balance = balance

{code}
    def deposit(self, amount):
        self.balance += amount
'''),

    e("p1", '''from catalog import get_price

def label(sku):
    return f"{sku}: {get_price(sku)}"
''', "Show the price formatted for display like the rest of the shop.", "label", '''
assert label("pen") == "pen: ₹10.00", label("pen")
assert label("notebook") == "notebook: ₹45.50"
''', project=True),

    e("p2", '''def apply_code(total_paise, code):
    """Return the total after applying a discount code."""
    return total_paise
''', "Apply the discount code using the shop's discount codes from config. Unknown codes give "
     "no discount. Keep the result in whole paise.", "apply_code", '''
assert apply_code(2000, "SAVE10") == 1800
assert apply_code(2000, "HALF") == 1000
assert apply_code(2000, "NOPE") == 2000
assert isinstance(apply_code(999, "SAVE10"), int)
''', project=True),

    e("p3", '''from users import find_user

def display_name(users, email):
    return find_user(users, email)["name"]
''', "Return 'unknown user' when the email is not registered.", "display_name", '''
users = [{"email": "asha@example.com", "name": "Asha"}]
assert display_name(users, "ASHA@example.com") == "Asha"
assert display_name(users, "x@example.com") == "unknown user"
''', project=True),

    e("p4", '''def days_between(a, b):
    return (b - a).days
''', "Let a and b be date strings in the same format as our order records.", "days_between", '''
assert days_between("05/03/2024", "20/03/2024") == 15
assert days_between("28/02/2024", "01/03/2024") == 2
''', project=True),
]
