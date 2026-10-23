"""The single street-convention pricing function (design 5.1), and what is derived from it (pure).

    P_dirty = Σ_k CF_k / (1 + y/2)^(w + k),  w = days to next coupon / days in the period

Every price, yield and DV01 goes through ``_flows``/``dirty_price``. Yields and coupons are
decimals; prices are per 100 face. Functions taking ``y`` accept a float or a numpy array
(e.g. a grid of shifted yields) and return the same shape.

Street convention prices the final coupon period with simple interest. No basket bond is
that close to maturity, so it isn't implemented: a bond in its final period raises.
"""

from datetime import date

import numpy as np
from scipy.optimize import brentq

from ctd.bonds.schedule import accrued, coupon_dates, prev_next_coupon


def _flows(coupon: float, maturity: date, settle: date) -> tuple[np.ndarray, np.ndarray]:
    """Cash flows per 100 face and their times in coupon periods from ``settle``."""
    n = len(coupon_dates(maturity, settle))
    if n < 2:
        raise ValueError(f"bond maturing {maturity} is in its final coupon period at {settle}; "
                         "street convention's simple-interest final period isn't implemented")
    prev, nxt = prev_next_coupon(maturity, settle)
    w = (nxt - settle).days / (nxt - prev).days
    cf = np.full(n, 100 * coupon / 2)
    cf[-1] += 100
    return cf, w + np.arange(n)


def _result(x: np.ndarray):
    return float(x) if x.ndim == 0 else x


def dirty_price(coupon: float, maturity: date, settle: date, y):
    cf, t = _flows(coupon, maturity, settle)
    v = 1 + np.asarray(y, dtype=float)[..., None] / 2
    return _result((cf * v ** -t).sum(axis=-1))


def clean_price(coupon: float, maturity: date, settle: date, y):
    return _result(np.asarray(dirty_price(coupon, maturity, settle, y)) - accrued(coupon, maturity, settle))


def dv01(coupon: float, maturity: date, settle: date, y):
    """Fall in price per 100 face for a 1bp rise in yield (positive): −∂P/∂y × 1e-4, analytic."""
    cf, t = _flows(coupon, maturity, settle)
    v = 1 + np.asarray(y, dtype=float)[..., None] / 2
    return _result((cf * t / 2 * v ** (-t - 1)).sum(axis=-1) * 1e-4)


def yield_from_clean(coupon: float, maturity: date, settle: date, clean: float) -> float:
    """Yield that reprices ``clean`` exactly through ``clean_price``."""
    return brentq(lambda y: clean_price(coupon, maturity, settle, y) - clean, -0.05, 0.5,
                  xtol=1e-15, rtol=4 * np.finfo(float).eps, maxiter=200)
