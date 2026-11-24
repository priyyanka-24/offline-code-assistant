"""All amounts in this project are stored as integer paise (1 rupee = 100 paise)."""
from config import CURRENCY_SYMBOL


def to_paise(rupees: float) -> int:
    return round(rupees * 100)


def fmt(paise: int) -> str:
    """Format paise for display: fmt(1050) -> '₹10.50'. Only accepts an int."""
    if not isinstance(paise, int):
        raise TypeError("fmt() needs whole paise as an int")
    return f"{CURRENCY_SYMBOL}{paise // 100}.{paise % 100:02d}"
