"""Joker synergy evaluation — assess joker combinations and build potential.

This module evaluates:
1. Pairwise joker synergies (e.g., Blueprint + any strong joker)
2. Build archetype coherence (are jokers working toward the same goal?)
3. Scaling potential (how much stronger will this lineup get over time?)
4. Missing pieces (what joker would complete a powerful combo?)

Used by shop evaluation to prefer jokers that synergize with existing lineup.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from .scoring import Card, Joker, HandLevel, find_best_hands


# ============================================================
# Synergy Definitions
# ============================================================

# Pairwise synergies: (joker_a, joker_b) -> multiplier bonus
# These are combos that are more than the sum of their parts
PAIRWISE_SYNERGIES: dict[frozenset[str], float] = {
    # Blueprint/Brainstorm copy combos — copy the strongest joker
    frozenset({"Blueprint", "The Duo"}): 3.0,
    frozenset({"Blueprint", "The Trio"}): 3.0,
    frozenset({"Blueprint", "The Family"}): 3.0,
    frozenset({"Blueprint", "The Order"}): 3.0,
    frozenset({"Blueprint", "The Tribe"}): 3.0,
    frozenset({"Blueprint", "Baron"}): 2.5,
    frozenset({"Blueprint", "Hologram"}): 2.5,
    frozenset({"Blueprint", "Steel Joker"}): 2.5,
    frozenset({"Brainstorm", "The Duo"}): 3.0,
    frozenset({"Brainstorm", "The Trio"}): 3.0,

    # Mult stacking — multiple mult sources compound
    frozenset({"Jolly Joker", "Smiley Face"}): 1.5,
    frozenset({"Wrathful Joker", "Greedy Joker"}): 1.3,
    frozenset({"Lusty Joker", "Greedy Joker"}): 1.3,

    # xMult stacking — multiple xMult sources multiply each other
    frozenset({"The Duo", "Hologram"}): 2.0,
    frozenset({"The Duo", "Steel Joker"}): 2.0,
    frozenset({"Vampire", "Hologram"}): 2.0,
    frozenset({"Campfire", "Hologram"}): 2.0,
    frozenset({"Card Sharp", "The Duo"}): 1.8,

    # Scaling combos — compound growth
    frozenset({"Hologram", "DNA"}): 2.5,  # DNA adds cards, Hologram scales with them
    frozenset({"Constellation", "Celestial Pack"}): 1.5,  # More planets = more xMult
    frozenset({"Fortune Teller", "Celestial Pack"}): 1.3,

    # Retrigger combos — retrigger + per-card effects
    frozenset({"Hack", "Even Steven"}): 1.5,
    frozenset({"Hack", "Odd Todd"}): 1.5,
    frozenset({"Hack", "Fibonacci"}): 2.0,
    frozenset({"Sock and Buskin", "Scary Face"}): 1.8,
    frozenset({"Sock and Buskin", "Smiley Face"}): 1.8,
    frozenset({"Sock and Buskin", "Photograph"}): 2.0,

    # Rule-changing + scoring combos
    frozenset({"Four Fingers", "The Tribe"}): 2.5,  # 4-card flush + xMult on flush
    frozenset({"Four Fingers", "The Order"}): 2.5,  # 4-card straight + xMult on straight
    frozenset({"Shortcut", "The Order"}): 2.0,      # Easier straights + xMult
    frozenset({"Smeared Joker", "The Tribe"}): 2.0,  # Easier flushes + xMult
    frozenset({"Pareidolia", "Scary Face"}): 2.0,    # All cards = face + chips on face
    frozenset({"Pareidolia", "Smiley Face"}): 2.0,   # All cards = face + mult on face
    frozenset({"Pareidolia", "Sock and Buskin"}): 2.5,  # All cards retrigger
    frozenset({"Pareidolia", "Photograph"}): 2.0,    # First face = xMult, all are face

    # Economy + scaling
    frozenset({"Cloud 9", "Hologram"}): 1.3,  # Money for rerolls + scaling
}

# Archetype-defining joker groups
# If you have 2+ jokers from the same group, you're building that archetype
ARCHETYPE_CORES = {
    "flush": {"The Tribe", "Smeared Joker", "Four Fingers", "Splash",
              "Lusty Joker", "Greedy Joker", "Wrathful Joker", "Gluttonous Joker"},
    "pairs": {"The Duo", "Jolly Joker", "Zany Joker", "Madness",
              "Sly Joker", "Wily Joker"},
    "straight": {"The Order", "Shortcut", "Four Fingers", "Runner",
                 "Fibonacci", "Even Steven", "Odd Todd", "Hack"},
    "face_cards": {"Photograph", "Scary Face", "Smiley Face", "Sock and Buskin",
                   "Pareidolia", "Baron", "Triboulet"},
    "xmult_stack": {"Hologram", "Steel Joker", "Glass Joker", "Vampire",
                    "Campfire", "Lucky Cat", "Card Sharp", "Acrobat"},
    "scaling": {"Constellation", "Green Joker", "Red Card", "Blue Joker",
                "Hiker", "Fortune Teller", "Wee Joker", "Obelisk"},
}

# Jokers that are universally good (don't need synergy)
UNIVERSAL_GOOD = {
    "Blueprint", "Brainstorm", "Triboulet",  # S+ tier
    "Vampire", "Campfire",  # xMult that works with anything
    "Hologram",  # xMult scaling
    "Hack",  # Retrigger low cards (always useful)
}

# Scaling jokers: value increases over time
SCALING_RATE = {
    "Green Joker": 1.0,      # +1 mult/hand played
    "Red Card": 0.5,          # +3 mult per skip (rare)
    "Blue Joker": 0.3,        # +chips per remaining card in deck
    "Constellation": 1.5,     # +0.1 xMult per planet used
    "Hologram": 2.0,          # +0.25 xMult per card added to deck
    "Fortune Teller": 0.8,    # +1 mult per tarot used
    "Wee Joker": 1.0,         # +8 chips per 2 scored
    "Obelisk": 0.5,           # xMult grows when most played hand not played
    "Campfire": 1.5,          # xMult grows on sell
    "Lucky Cat": 1.0,         # xMult grows on lucky trigger
    "Vampire": 1.0,           # xMult grows on enhancement consumed
    "Card Sharp": 0.5,        # xMult if same hand played twice in a row
    "Hiker": 1.5,             # +5 chips permanently per card played
}


# ============================================================
# Synergy Scoring
# ============================================================

@dataclass
class SynergyReport:
    """Report on joker lineup synergy."""
    total_synergy: float       # Sum of all pairwise synergy bonuses
    archetype_coherence: float # 0-1, how focused the build is
    scaling_potential: float   # Expected score growth per ante
    missing_pieces: list[str]  # Jokers that would complete combos
    best_synergy_pair: tuple[str, str, float] | None  # Best existing pair
    dominant_archetype: str    # Most represented archetype
    details: list[str]         # Human-readable synergy notes


def evaluate_synergy(jokers: list[Joker]) -> SynergyReport:
    """Evaluate the synergy of a joker lineup."""
    names = {j.name for j in jokers}
    details = []

    # 1. Pairwise synergies
    total_synergy = 0.0
    best_pair = None
    for pair, bonus in PAIRWISE_SYNERGIES.items():
        if pair.issubset(names):
            a, b = sorted(pair)
            total_synergy += bonus
            if best_pair is None or bonus > best_pair[2]:
                best_pair = (a, b, bonus)
            details.append(f"{a} + {b}: {bonus:.1f}x synergy")

    # 2. Archetype coherence
    arch_scores = {}
    for arch, core_jokers in ARCHETYPE_CORES.items():
        overlap = names & core_jokers
        if overlap:
            arch_scores[arch] = len(overlap)

    if arch_scores:
        best_arch = max(arch_scores, key=arch_scores.get)
        max_count = arch_scores[best_arch]
        total_typed = sum(arch_scores.values())
        coherence = max_count / max(total_typed, 1)
        details.append(f"Build: {best_arch} ({max_count} core jokers, {coherence:.0%} coherence)")
    else:
        coherence = 0.0
        best_arch = None

    # 3. Scaling potential
    scaling = 0.0
    for j in jokers:
        rate = SCALING_RATE.get(j.name, 0)
        if rate > 0:
            scaling += rate
            details.append(f"{j.name}: scaling rate {rate:.1f}/ante")

    # 4. Missing pieces — what would complete a combo?
    missing = []
    for pair, bonus in PAIRWISE_SYNERGIES.items():
        if bonus >= 2.0:  # Only suggest high-value combos
            in_hand = pair & names
            if len(in_hand) == 1:
                needed = list(pair - names)[0]
                missing.append(needed)

    # Deduplicate
    missing = list(dict.fromkeys(missing))[:5]

    return SynergyReport(
        total_synergy=total_synergy,
        archetype_coherence=coherence,
        scaling_potential=scaling,
        missing_pieces=missing,
        best_synergy_pair=best_pair,
        dominant_archetype=best_arch or "none",
        details=details,
    )


def evaluate_joker_synergy_with_lineup(
    new_joker_name: str,
    existing_jokers: list[Joker],
) -> float:
    """Score how well a new joker synergizes with the existing lineup.

    Returns a synergy bonus (0.0 = no synergy, 3.0+ = amazing fit).
    """
    names = {j.name for j in existing_jokers}
    bonus = 0.0

    # Check pairwise synergies with existing jokers
    for pair, syn_value in PAIRWISE_SYNERGIES.items():
        if new_joker_name in pair:
            partner = list(pair - {new_joker_name})[0]
            if partner in names:
                bonus += syn_value

    # Check archetype fit
    for arch, core_jokers in ARCHETYPE_CORES.items():
        if new_joker_name in core_jokers:
            existing_in_arch = len(names & core_jokers)
            if existing_in_arch >= 1:
                bonus += 0.5 * existing_in_arch  # More existing = better fit

    # Universal good jokers always get a small bonus
    if new_joker_name in UNIVERSAL_GOOD:
        bonus += 1.0

    # Scaling jokers get bonus in early game (more time to compound)
    if new_joker_name in SCALING_RATE:
        bonus += 0.5

    return bonus


# ============================================================
# Board Valuation — estimate lineup strength for future blinds
# ============================================================

def estimate_board_strength(
    jokers: list[Joker],
    hand_levels: HandLevel | None = None,
    ante: int = 1,
) -> dict:
    """Estimate the overall strength of the current board.

    Returns dict with:
    - expected_score: avg score across sample hands
    - max_score: best score from samples
    - scaling_per_ante: expected score growth per ante
    - blind_reach: estimated max ante this board can reach
    - synergy: SynergyReport
    """
    from .strategy import _make_sample_hands

    if hand_levels is None:
        hand_levels = HandLevel()

    # Score across sample hands
    samples = _make_sample_hands(12)
    scores = []
    for hand in samples:
        results = find_best_hands(hand, jokers, hand_levels, max_size=5, top_n=1)
        if results:
            scores.append(results[0].final_score)

    avg_score = sum(scores) / len(scores) if scores else 0
    max_score = max(scores) if scores else 0

    # Synergy analysis
    synergy = evaluate_synergy(jokers)

    # Estimate blind reach based on score vs blind targets
    # Ante targets (approximate): A1=300/450/600, A2=800/1200/1600, A3=2000/3000/4000
    # A4=5000/7500/10000, A5=11000/16500/22000, A6=20000/30000/40000
    # A7=35000/52500/70000, A8=50000/75000/100000
    ante_boss_targets = {
        1: 600, 2: 1600, 3: 4000, 4: 10000,
        5: 22000, 6: 40000, 7: 70000, 8: 100000,
    }

    # With 4 hands and scaling, estimate max reachable ante
    # Assume 4 hands per blind, score grows with scaling jokers
    blind_reach = 1
    projected_score = avg_score
    scaling_mult = 1.0 + synergy.scaling_potential * 0.1  # 10% per scaling unit per ante

    for a in range(ante, 9):
        # 4 hands worth of score
        total_round_score = projected_score * 4
        boss_target = ante_boss_targets.get(a, 100000)
        if total_round_score >= boss_target:
            blind_reach = a + 1
            projected_score *= scaling_mult
        else:
            break

    return {
        "expected_score": avg_score,
        "max_score": max_score,
        "scaling_per_ante": synergy.scaling_potential,
        "blind_reach": min(blind_reach, 8),
        "synergy": synergy,
        "num_jokers": len(jokers),
    }
