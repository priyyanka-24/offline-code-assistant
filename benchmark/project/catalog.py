PRODUCTS = {
    "pen":      {"price": 1000, "qty_left": 50},   # price in paise
    "notebook": {"price": 4550, "qty_left": 3},
    "eraser":   {"price": 500,  "qty_left": 0},
    "bag":      {"price": 89900, "qty_left": 12},
    "ruler":    {"price": 1500, "qty_left": 4},
}


def get_price(sku: str) -> int:
    """Price of one item, in paise."""
    return PRODUCTS[sku]["price"]


def in_stock(sku: str, qty: int) -> bool:
    """True if at least qty items are left."""
    return PRODUCTS[sku]["qty_left"] >= qty
