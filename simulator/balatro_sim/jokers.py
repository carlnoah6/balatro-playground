"""Joker scoring effects — DEPRECATED, now integrated into scoring.py.

This file is kept as a compatibility shim. All joker scoring logic
has been moved into scoring.py's trigger pipeline for proper
interleaving of chips/mult/xMult operations.
"""

from __future__ import annotations


def apply_joker_scoring(*args, **kwargs):
    """Deprecated — joker scoring is now handled inside calculate_score()."""
    raise NotImplementedError(
        "apply_joker_scoring is deprecated. "
        "Joker effects are now integrated into scoring.py's trigger pipeline."
    )
