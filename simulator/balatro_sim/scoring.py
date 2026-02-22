"""Scoring engine — calculates chips × mult for a played hand.

Implements the real Balatro scoring pipeline:
1. Start with hand-type base chips & base mult (from hand level)
2. For each scoring card (left to right):
   - Add card's chip value
   - Apply card enhancement effects
   - Apply card edition effects
3. For each held-in-hand card: apply Steel Card xMult
4. For each joker (left to right): apply joker scoring effect + edition
5. final_score = chips × mult

This module handles base scoring WITHOUT joker effects.
Joker scoring will be layered on top in jokers.py (Phase 3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .enums import HandType, Enhancement, Edition, HAND_BASE, PLANET_BONUS
from .cards import Card, JokerCard


@dataclass
class HandLevels:
    """Tracks planet card upgrades for each hand type."""
    levels: dict[str, int] = field(default_factory=lambda: {ht.value: 1 for ht in HandType})

    def get_base(self, hand_type: HandType) -> tuple[int, int]:
        """Return (chips, mult) for a hand type at its current level."""
        base_chips, base_mult = HAND_BASE[hand_type]
        level = self.levels.get(hand_type.value, 1)
        bonus_chips, bonus_mult = PLANET_BONUS[hand_type]
        extra = level - 1
        return (base_chips + bonus_chips * extra, base_mult + bonus_mult * extra)

    def level_up(self, hand_type: HandType, amount: int = 1):
        self.levels[hand_type.value] = self.levels.get(hand_type.value, 1) + amount

    def copy(self) -> "HandLevels":
        hl = HandLevels()
        hl.levels = dict(self.levels)
        return hl


@dataclass
class ScoreResult:
    """Result of scoring a hand."""
    hand_type: HandType
    chips: float
    mult: float
    final_score: float  # floor(chips × mult)
    scoring_indices: list[int]  # which cards were scoring

    def __repr__(self) -> str:
        return f"{self.hand_type.value}: {int(self.chips)} × {self.mult:.1f} = {int(self.final_score)}"


def calculate_score(
    played_cards: list[Card],
    hand_type: HandType,
    scoring_indices: list[int],
    hand_levels: HandLevels,
    held_cards: Optional[list[Card]] = None,
    jokers: Optional[list[JokerCard]] = None,
) -> ScoreResult:
    """Calculate the score for a played hand.

    Args:
        played_cards: Cards that were played.
        hand_type: The identified hand type.
        scoring_indices: Indices into played_cards that are scoring.
        hand_levels: Current hand level upgrades.
        held_cards: Cards remaining in hand (for Steel card etc).
        jokers: Active jokers (scoring effects applied in Phase 3).

    Returns:
        ScoreResult with chips, mult, and final score.
    """
    # Step 1: Base chips and mult from hand type + level
    base_chips, base_mult = hand_levels.get_base(hand_type)
    chips = float(base_chips)
    mult = float(base_mult)

    # Step 2: For each scoring card (left to right), add chip value + enhancements
    scoring_cards = [played_cards[i] for i in scoring_indices]
    for card in scoring_cards:
        if card.debuffed:
            continue

        # Card chip value
        chips += card.chip_value

        # Enhancement effects on the card itself
        chips, mult = _apply_card_enhancement(card, chips, mult)

        # Edition effects on the card
        chips, mult = _apply_card_edition(card, chips, mult)

    # Step 3: Held-in-hand card effects (Steel cards)
    if held_cards:
        for card in held_cards:
            if card.debuffed:
                continue
            if card.enhancement == Enhancement.STEEL:
                mult *= 1.5
            # Steel + edition
            if card.enhancement == Enhancement.STEEL:
                chips, mult = _apply_card_edition(card, chips, mult)

    # Step 4: Joker effects
    if jokers:
        from .jokers import apply_joker_scoring
        chips, mult = apply_joker_scoring(
            jokers, played_cards, scoring_indices, hand_type,
            held_cards or [], chips, mult,
        )

    # Step 5: Final score
    final = max(0, int(chips * mult))

    return ScoreResult(
        hand_type=hand_type,
        chips=chips,
        mult=mult,
        final_score=final,
        scoring_indices=scoring_indices,
    )


def _apply_card_enhancement(card: Card, chips: float, mult: float) -> tuple[float, float]:
    """Apply a card's enhancement effect to chips/mult."""
    enh = card.enhancement
    if enh == Enhancement.BONUS:
        chips += 30
    elif enh == Enhancement.MULT:
        mult += 4
    elif enh == Enhancement.GLASS:
        mult *= 2  # Glass: x2 mult (but 1/4 chance to destroy)
    elif enh == Enhancement.STONE:
        chips += 50  # Already counted in chip_value, but Stone replaces rank chips
        # Stone cards don't have a rank, so chip_value already returns 50
        # We need to NOT double-count. chip_value handles it.
        chips -= 50  # Undo since chip_value already added 50
    elif enh == Enhancement.LUCKY:
        # Lucky: 1/5 chance +20 mult, 1/15 chance +$20
        # For deterministic scoring, we use expected value
        mult += 4.0  # EV: 20 * 0.2 = 4
    elif enh == Enhancement.GOLD:
        pass  # Gold: +$3 at end of round (not a scoring effect)
    # Wild, Steel handled elsewhere
    return chips, mult


def _apply_card_edition(card: Card, chips: float, mult: float) -> tuple[float, float]:
    """Apply a card's edition effect to chips/mult."""
    ed = card.edition
    if ed == Edition.FOIL:
        chips += 50
    elif ed == Edition.HOLOGRAPHIC:
        mult += 10
    elif ed == Edition.POLYCHROME:
        mult *= 1.5
    return chips, mult
