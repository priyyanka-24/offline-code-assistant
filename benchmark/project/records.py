"""Sample order records. Each order: {"id", "user", "items": {sku: qty}, "due"} (due is a record date)."""

ORDERS = [
    {"id": 1, "user": "asha@example.com", "items": {"pen": 2}, "due": "05/03/2024"},
    {"id": 2, "user": "ravi@example.com", "items": {"bag": 1, "ruler": 2}, "due": "20/03/2024"},
]
