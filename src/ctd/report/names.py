"""Bond names as the report prints them."""

from datetime import date

EIGHTHS = {0: "", 1: "⅛", 2: "¼", 3: "⅜", 4: "½", 5: "⅝", 6: "¾", 7: "⅞"}


def bond_name(coupon: float, maturity: str) -> str:
    """``4¾% Feb-45`` (coupon in eighths where it is one, else in decimals)."""
    m = date.fromisoformat(maturity)
    eighths = coupon * 800
    if abs(eighths - round(eighths)) < 1e-6:
        whole, frac = divmod(round(eighths), 8)
        c = f"{whole if whole or not frac else ''}{EIGHTHS[frac]}"
    else:
        c = f"{coupon * 100:g}"
    return f"{c}% {m:%b-%y}"
