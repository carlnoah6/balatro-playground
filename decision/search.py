"""Search-based discard evaluator — replaces heuristic should_discard.

Enumerates discard combinations of non-scoring cards, estimates expected
score after drawing replacements via Monte Carlo, picks the best option.

Key design decisions (Epoch 1 v4):
- Only discard non-scoring cards (cards not in best hand)
- Require higher improvement threshold when discards are scarce
- Account for opportunity cost: saving discards for later hands
- Prefer fewer discards when improvement is marginal
- 20 Monte Carlo samples per combo (sufficient for ranking)
"""

from __future__ import annotations

import random
from itertools import combinations

from .scoring import Card, Joker, HandLevel, ScoreBreakdown, find_best_hands


def evaluate_discard_options(
    hand_cards: list[Card],
    jokers: list[Joker],
    hand_levels: HandLevel,
    draw_pile: list[Card],
    chips_needed: float,
    hands_left: int,
    discards_left: int,
    boss_blind: str = "",
    n_samples: int = 20,
) -> tuple[str, list[int], float, str]:
    """Evaluate discard options and return the best action.

    Returns:
        (action, card_indices, expected_score, reasoning)
        action: "play" or "discard"
    """
    if not hand_cards:
        return ("play", [], 0.0, "No cards")

    # Evaluate current best hand (no discard)
    best_now = find_best_hands(hand_cards, jokers, hand_levels, top_n=1, boss_blind=boss_blind)
    if not best_now:
        return ("play", list(range(min(5, len(hand_cards)))), 0.0, "Cannot evaluate")

    play_score = best_now[0].final_score
    play_indices = best_now[0].all_cards
    play_type = best_now[0].hand_type

    # If we can clear the blind, just play
    if play_score >= chips_needed and chips_needed > 0:
        return ("play", play_indices, play_score,
                f"Play {play_type} for {play_score:.0f} >= {chips_needed:.0f}")

    # If no discards left, last hand, or empty draw pile — must play
    if discards_left <= 0 or hands_left <= 1 or not draw_pile:
        return ("play", play_indices, play_score,
                f"Play {play_type} ({play_score:.0f}) — no discard possible")

    # Only consider discarding non-scoring cards
    scoring_set = set(play_indices)
    non_scoring = [i for i in range(len(hand_cards)) if i not in scoring_set]

    if not non_scoring:
        return ("play", play_indices, play_score,
                f"Play {play_type} ({play_score:.0f}) — all cards scoring")

    # === Dynamic threshold based on game state ===
    # When discards are scarce, require much higher improvement to justify using one
    # When we have plenty of discards, be more willing to search
    chips_remaining = max(chips_needed - 0, 1)  # chips still needed this blind
    score_ratio = play_score / chips_remaining if chips_remaining > 0 else 1.0

    # Base threshold: 50% improvement required
    # Adjusted down when: many discards left, far from clearing, weak hand
    # Adjusted up when: few discards left, close to clearing, decent hand
    if discards_left >= 3 and score_ratio < 0.3:
        # Desperate: weak hand, plenty of discards → lower threshold
        threshold = 1.3  # 30% improvement
    elif discards_left >= 2 and score_ratio < 0.5:
        # Struggling: mediocre hand, some discards → moderate threshold
        threshold = 1.5  # 50% improvement
    elif discards_left == 1:
        # Last discard: only use if massive improvement expected
        threshold = 2.0  # 100% improvement
    else:
        # Default: require significant improvement
        threshold = 1.5  # 50% improvement

    # If we're close to clearing (>70% of target), be conservative with discards
    if score_ratio > 0.7:
        threshold = max(threshold, 2.0)

    # Evaluate discard combos (only non-scoring cards)
    max_d = min(discards_left, len(non_scoring), 5)
    best_action = "play"
    best_indices = play_indices
    best_expected = play_score
    best_reason = f"Play {play_type} ({play_score:.0f})"
    best_n_discard = 0

    for n_discard in range(1, max_d + 1):
        # Penalize using more discards: each additional discard needs more justification
        discard_penalty = 1.0 + (n_discard - 1) * 0.1  # +10% per extra discard

        for combo in combinations(non_scoring, n_discard):
            combo_set = set(combo)
            remaining = [hand_cards[i] for i in range(len(hand_cards)) if i not in combo_set]

            draw_count = min(n_discard, len(draw_pile))
            if draw_count == 0:
                continue

            total_score = 0.0
            clears = 0

            for _ in range(n_samples):
                drawn = random.sample(draw_pile, draw_count)
                new_hand = remaining + drawn

                bests = find_best_hands(new_hand, jokers, hand_levels, top_n=1, boss_blind=boss_blind)
                if bests:
                    score = bests[0].final_score
                    total_score += score
                    if score >= chips_needed:
                        clears += 1

            expected = total_score / n_samples
            clear_rate = clears / n_samples

            # Effective score: raw expected + bonus for clear probability
            effective = expected
            if chips_needed > 0 and clear_rate > 0:
                effective = expected + clear_rate * chips_needed * 0.5

            # Apply threshold with discard penalty
            required = best_expected * threshold * discard_penalty
            if effective > required:
                best_expected = effective
                best_action = "discard"
                best_indices = list(combo)
                best_n_discard = n_discard
                card_names = " ".join(f"{hand_cards[i].rank}{hand_cards[i].suit[0]}" for i in combo)
                best_reason = (f"Discard [{card_names}] E[score]={expected:.0f} "
                              f"clear={clear_rate*100:.0f}% vs play {play_type}({play_score:.0f})")

    return (best_action, best_indices, best_expected, best_reason)
