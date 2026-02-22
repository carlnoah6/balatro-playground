"""Hand type identification — Python port of Balatro's evaluate_poker_hand.

Identifies the best poker hand from a set of played cards, including
Balatro-specific types: Five of a Kind, Flush House, Flush Five.
"""

from __future__ import annotations

from collections import Counter
from typing import Optional

from .enums import Suit, Rank, HandType
from .cards import Card


def evaluate_hand(cards: list[Card]) -> tuple[HandType, list[int]]:
    """Evaluate played cards and return (hand_type, scoring_card_indices).

    Args:
        cards: The played cards (1-5 cards).

    Returns:
        (HandType, list of indices into `cards` that are scoring cards)
    """
    if not cards:
        return HandType.HIGH_CARD, []

    n = len(cards)
    ranks = [c.rank for c in cards]
    rank_counts = Counter(ranks)
    most_common = rank_counts.most_common()

    # Check flush (all same suit, accounting for Wild cards)
    is_flush = _check_flush(cards)

    # Check straight
    is_straight = _check_straight([r.value for r in ranks])

    # Count-based classifications
    max_count = most_common[0][1] if most_common else 0
    num_distinct = len(rank_counts)

    # Determine hand type (highest first)
    if max_count == 5 and is_flush:
        return HandType.FLUSH_FIVE, list(range(n))

    if max_count >= 3 and _has_pair_plus_three(most_common) and is_flush:
        return HandType.FLUSH_HOUSE, list(range(n))

    if max_count == 5:
        return HandType.FIVE_OF_A_KIND, list(range(n))

    if is_straight and is_flush:
        return HandType.STRAIGHT_FLUSH, list(range(n))

    if max_count == 4:
        scoring = _indices_of_rank(cards, most_common[0][0])
        return HandType.FOUR_OF_A_KIND, scoring

    if max_count == 3 and len(most_common) >= 2 and most_common[1][1] >= 2:
        return HandType.FULL_HOUSE, list(range(n))

    if is_flush:
        return HandType.FLUSH, list(range(n))

    if is_straight:
        return HandType.STRAIGHT, list(range(n))

    if max_count == 3:
        scoring = _indices_of_rank(cards, most_common[0][0])
        return HandType.THREE_OF_A_KIND, scoring

    if max_count == 2:
        pairs = [r for r, c in most_common if c == 2]
        if len(pairs) >= 2:
            scoring = []
            for r in pairs[:2]:
                scoring.extend(_indices_of_rank(cards, r))
            return HandType.TWO_PAIR, sorted(scoring)
        else:
            scoring = _indices_of_rank(cards, pairs[0])
            return HandType.PAIR, scoring

    # High card — only the highest card scores
    best_idx = max(range(n), key=lambda i: cards[i].rank.value)
    return HandType.HIGH_CARD, [best_idx]


def _check_flush(cards: list[Card]) -> bool:
    """Check if all cards share a suit (Wild cards match any suit)."""
    if len(cards) < 5:
        return False

    # Find the first non-wild card's suit
    base_suit: Optional[Suit] = None
    for c in cards:
        if not c.is_wild:
            base_suit = c.suit
            break

    if base_suit is None:
        return True  # All wild

    return all(c.matches_suit(base_suit) for c in cards)


def _check_straight(rank_values: list[int]) -> bool:
    """Check if rank values form a straight (including ace-low)."""
    s = sorted(set(rank_values))
    if len(s) < 5:
        return False

    # Normal straight
    if s[-1] - s[0] == 4 and len(s) == 5:
        return True

    # Ace-low: A-2-3-4-5
    if set(s) == {14, 2, 3, 4, 5}:
        return True

    return False


def _has_pair_plus_three(most_common: list[tuple[Rank, int]]) -> bool:
    """Check for full house pattern (3+2) in rank counts."""
    if len(most_common) < 2:
        return False
    counts = sorted([c for _, c in most_common], reverse=True)
    return counts[0] >= 3 and counts[1] >= 2


def _indices_of_rank(cards: list[Card], rank: Rank) -> list[int]:
    """Get indices of cards matching a specific rank."""
    return [i for i, c in enumerate(cards) if c.rank == rank]


def get_all_scoring_cards(cards: list[Card], hand_type: HandType) -> list[int]:
    """For a known hand type, determine which cards are 'scoring' cards.

    In Balatro, scoring cards are the ones that contribute to the hand type.
    Non-scoring cards in hand still exist but don't get per-card chip bonuses
    in the base scoring (though jokers may still reference them).
    """
    _, scoring = evaluate_hand(cards)
    return scoring
