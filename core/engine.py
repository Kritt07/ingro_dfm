"""Core engine utilities for DFM calculations.

This module implements the primitive calculations referenced in the
specification (section 2) and derived from ГОСТ 14.205‑83 and the Минтруд № 6
norms.  The functions operate on the `CARDS` dictionary defined in
`core.cards`.  Only a subset of the full formulae is required for the current
test suite, but the implementation is written in a way that can be extended
easily.
"""

from typing import Dict, Any, List

from .cards import CARDS

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def pick_row(table: List[Dict[str, Any]], **criteria) -> Dict[str, Any]:
    """Return the first row matching all criteria.

    This generic helper is kept for compatibility with the original stub –
    it searches a list of dictionaries for a row where every key/value pair
    in ``criteria`` matches.
    """
    for row in table:
        if all(row.get(k) == v for k, v in criteria.items()):
            return row
    raise KeyError(f"No matching row for {criteria}")

# ---------------------------------------------------------------------------
# Card‑based time calculations
# ---------------------------------------------------------------------------

def card_time(card_id: int, q: float, t_sh: float = 0.0) -> float:
    """Calculate the time contributed by a specific card.

    Parameters
    ----------
    card_id: int
        Identifier of the normative card (e.g. 1, 2, 5, 58).
    q: float
        Batch size factor (the `q` parameter from the spec).
    t_sh: float, optional
        The cumulative raw turning time ``T_шт`` – required for cards that
        depend on it (e.g., card 1 uses ``K_парт(q, T_шт)``).

    Returns
    -------
    float
        Time in minutes contributed by the card.
    """
    card = CARDS.get(card_id)
    if not card:
        raise ValueError(f"Card {card_id} is not defined in CARDS")

    # Most cards store a simple ``time_min`` field – return it scaled by the
    # batch factor when appropriate.
    if "time_min" in card:
        return card["time_min"] * q

    # Card 1 – base operative time, uses a coefficient that depends on ``q``
    # and the raw turning time.  The full standard defines a lookup table; for
    # the stub we model it as a linear scaling.
    if card_id == 1:
        base = card.get("base_time_min", 0.5)
        # Simplified K_парт: 1.0 for q <= 5, 1.1 for larger batches.
        k_part = 1.0 if q <= 5 else 1.1
        return base * k_part * q + t_sh

    # Card 5 – transition time ``t_пз``.  The spec adds a constant auxiliary
    # part (17 min) that is later multiplied by ``q`` in ``compute_T_pz``.
    if card_id == 5:
        return card.get("time_min", 1.05) * q

    # Card 58 – grinding operation (single surface).  The total time is taken
    # directly from the card definition.
    if card_id == 58:
        return card.get("time_min", 5.9) * q

    # Fallback – return any explicit ``time_min`` scaled by ``q``.
    return card.get("time_min", 0.0) * q

# ---------------------------------------------------------------------------
# Auxiliary calculations used by the higher‑level model
# ---------------------------------------------------------------------------

def compute_K_part(q: float, t_sh: float) -> float:
    """Compute the party coefficient `K_парт`.

    According to the specification, ``K_парт`` is a two‑input lookup based on
    ``q`` (batch size) and the raw turning time ``T_шт``.  A full implementation
    would read the official table; here we provide a deterministic approximation
    that respects the intended behaviour:

    * ``q`` ≤ 5 → ``K = 1.0``
    * ``5 < q ≤ 20`` → ``K = 1.05``
    * ``q > 20`` → ``K = 1.10``
    """
    if q <= 5:
        return 1.0
    if q <= 20:
        return 1.05
    return 1.10


def compute_T_pz(q: float, base: float = 17.0) -> float:
    """Compute the auxiliary transition time ``T_пз``.

    The spec defines a constant base of 17 minutes for a single operation; the
    total scales linearly with the batch factor ``q``.
    """
    return base * q

__all__ = [
    "CARDS",
    "pick_row",
    "card_time",
    "compute_K_part",
    "compute_T_pz",
]
