"""Which delivery day forwards are taken to (pure).

Light model (design 5.2 and 5.11):
the last delivery day if the basket's probability-weighted carry is positive, the first if
negative; one date for the whole basket. A bond's carry here is its converted forward at the first
delivery day minus at the last (positive: holding it to the last day pays), and the weights are
the option-implied probabilities of being CTD (``model.probabilities``, interval midpoints
rescaled to sum to 1), read with the envelope at the last delivery day. Weighting by probability
rather than following today's CTD keeps the date from flipping each time two bonds of opposite
carry trade places. The full model's decision rule (5.2) replaces this later.
"""

from datetime import date


def weighted_carry(weights: dict[str, float], conv_first: dict[str, float], conv_last: dict[str, float]) -> float:
    """``Σ p_i (F_first,i − F_last,i) / CF_i``, in price points per 100 face of futures: the carry
    of holding the deliverable to the last delivery day, weighted by each bond's probability of
    being CTD. ``conv_*`` are converted forward clean prices (forward / CF) on each day."""
    return sum(p * (conv_first[c] - conv_last[c]) for c, p in weights.items())


def light_horizon(first: date, last: date, carry: float) -> date:
    """``last`` if the probability-weighted carry (``weighted_carry``) is positive, else ``first``.
    A tie counts as positive carry."""
    return last if carry >= 0 else first
