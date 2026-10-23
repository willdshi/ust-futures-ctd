"""Which delivery day forwards are taken to (pure).

Light model (design 5.11, docs/decisions.md): the last delivery day if the CTD's carry is
positive, the first if negative; one date for the whole basket. The full model's decision
rule (5.2) replaces this later.
"""

from datetime import date


def light_horizon(first: date, last: date, ctd_fwd_first: float, ctd_fwd_last: float) -> date:
    """``last`` if the CTD's forward clean price falls from ``first`` to ``last`` (positive carry), else ``first``.

    The CTD is the bond with the cheapest converted forward at ``last``; pass its forward clean
    prices at both dates. A tie counts as positive carry.
    """
    return last if ctd_fwd_last <= ctd_fwd_first else first
