"""v2 benchmark: questions that need code from OTHER files in benchmark/project/.

The model sees only the snippet (as if it is being written in project/checkout.py).
To answer correctly it must know facts that live in other files, for example:
  - prices are integer paise, not rupees            (catalog.py, money.py)
  - fmt() only accepts int paise                     (money.py)
  - discount codes are percentages                   (config.py)
  - find_user raises UserNotFound, never returns None (users.py)
  - dates look like 25/12/2024                       (dates.py, records.py)
  - stock is stored under "qty_left"                 (catalog.py)

Run:  python eval.py --target server --tag v2-cross --questions benchmark.crossfile
      python eval.py --target server --tag v1-cross --questions benchmark.crossfile --no-rag
"""
from pathlib import Path

PROJECT = str(Path(__file__).parent / "project")
FILE = str(Path(PROJECT) / "checkout.py")  # the (new) file the user is typing in


def q(id, type, code, ask, check):
    return {"id": id, "type": type, "code": code, "ask": ask, "check": check,
            "project_root": PROJECT, "file_path": FILE}


QUESTIONS = [
    q("x1", "complete", '''from catalog import get_price
from money import fmt

def line_total(sku, qty):
    """Total price for qty of sku, formatted for display like the rest of the shop."""
''', "Finish this function.",
      {"kind": "tests", "entry": "line_total", "tests": '''
assert line_total("pen", 2) == "₹20.00", line_total("pen", 2)
assert line_total("notebook", 3) == "₹136.50"
'''}),

    q("x2", "complete", '''from catalog import get_price
from config import DISCOUNT_CODES, TAX_RATE

def checkout_total(cart, code=None):
    """cart is {sku: qty}. Apply the discount code if it is valid, then add tax.
    Return the final total in paise, rounded to an int."""
''', "Finish this function.",
      {"kind": "tests", "entry": "checkout_total", "tests": '''
assert checkout_total({"pen": 2}) == 2360
assert checkout_total({"pen": 2}, "SAVE10") == 2124
assert checkout_total({"pen": 2}, "BOGUS") == 2360
assert checkout_total({"bag": 1}, "HALF") == 53041
'''}),

    q("x3", "debug", '''from users import find_user

def greet(users, email):
    user = find_user(users, email)
    if user is None:
        return "Hello, guest"
    return "Hello, " + user["name"]
''', "greet should return 'Hello, guest' for an email that is not registered, "
     "but it crashes instead. Find and fix the bug.",
      {"kind": "tests", "entry": "greet", "tests": '''
users = [{"email": "Asha@Example.com", "name": "Asha"}]
assert greet(users, "asha@example.com ") == "Hello, Asha"
assert greet(users, "nobody@example.com") == "Hello, guest"
'''}),

    q("x4", "debug", '''from money import fmt

def add_tip(bill_paise, tip_percent):
    """Return the bill plus tip, formatted for display."""
    tip = bill_paise * tip_percent / 100
    return fmt(bill_paise + tip)
''', "add_tip(1000, 15) crashes. Find and fix the bug.",
      {"kind": "tests", "entry": "add_tip", "tests": '''
assert add_tip(1000, 15) == "₹11.50"
assert add_tip(999, 10) == "₹10.99"
assert add_tip(1000, 0) == "₹10.00"
'''}),

    q("x5", "explain", '''from catalog import get_price
from money import fmt

def price_tag(sku):
    return fmt(get_price(sku))
''', "What exactly does price_tag('notebook') return? Give the exact value.",
      {"kind": "keywords", "groups": [["45.50"]]}),

    q("x6", "complete", '''from catalog import PRODUCTS
from config import LOW_STOCK

def restock_report():
    """Return a sorted list of the skus that need restocking (stock below LOW_STOCK)."""
''', "Finish this function.",
      {"kind": "tests", "entry": "restock_report", "tests": '''
assert restock_report() == ["eraser", "notebook", "ruler"], restock_report()
'''}),

    q("x7", "complete", '''from dates import parse_date

def is_overdue(order, today):
    """order is one of our order records; today is a date string in the same format as the records.
    Return True if the order was due before today."""
''', "Finish this function.",
      {"kind": "tests", "entry": "is_overdue", "tests": '''
order = {"id": 1, "user": "asha@example.com", "items": {"pen": 2}, "due": "05/03/2024"}
assert is_overdue(order, "06/03/2024") is True
assert is_overdue(order, "05/03/2024") is False
assert is_overdue(order, "01/04/2023") is False
'''}),

    q("x8", "debug", '''from catalog import get_price, in_stock

def buy(sku, qty, wallet_paise):
    """Return the wallet balance (paise) after buying, or an error message."""
    if not in_stock(sku):
        return "out of stock"
    cost = get_price(sku) * qty
    if cost > wallet_paise:
        return "not enough money"
    return wallet_paise - cost
''', "buy('pen', 2, 5000) crashes with a TypeError. Find and fix the bug.",
      {"kind": "tests", "entry": "buy", "tests": '''
assert buy("pen", 2, 5000) == 3000
assert buy("pen", 100, 10**7) == "out of stock"
assert buy("eraser", 1, 5000) == "out of stock"
assert buy("pen", 2, 100) == "not enough money"
'''}),
]
