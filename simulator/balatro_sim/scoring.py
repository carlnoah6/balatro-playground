"""Scoring engine — full Balatro trigger pipeline.

Ported from decision/scoring.py (production engine) to use simulator types.

Pipeline:
1. Base chips & mult from hand type + level
2. Per scoring card (L→R): chips + enhancement + edition + per-card joker triggers
3. Retriggers per card: Red Seal, Hack, Hanging Chad, Sock&Buskin, Seltzer, Dusk
4. Held-in-hand card effects (Steel, held-card jokers) + retriggers (Red Seal, Mime)
5. Independent joker effects (L→R) + Blueprint/Brainstorm resolution
6. Joker editions after each joker's effect
7. final_score = floor(chips × mult)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .enums import (
    HandType, Enhancement, Edition, Seal, Suit, Rank,
    HAND_BASE, PLANET_BONUS, HAND_CONTAINS,
)
from .cards import Card, JokerCard


# ---------------------------------------------------------------------------
# HandLevels & ScoreResult (unchanged interface)
# ---------------------------------------------------------------------------

@dataclass
class HandLevels:
    """Tracks planet card upgrades for each hand type."""
    levels: dict[str, int] = field(default_factory=lambda: {ht.value: 1 for ht in HandType})

    def get_base(self, hand_type: HandType) -> tuple[int, int]:
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
    final_score: float
    scoring_indices: list[int]

    def __repr__(self) -> str:
        return f"{self.hand_type.value}: {int(self.chips)} × {self.mult:.1f} = {int(self.final_score)}"


# ---------------------------------------------------------------------------
# Scoring Context — accumulates chips/mult through the pipeline
# ---------------------------------------------------------------------------

class _ScoringContext:
    __slots__ = (
        "chips", "mult", "hand_type", "hand_contains",
        "played_cards", "scoring_idxs", "held_cards", "jokers",
        "hand_levels", "game_state",
        "pareidolia", "has_smeared", "chance_multiplier",
        "resolved_jokers", "joker_extra_state",
    )

    def __init__(
        self,
        base_chips: int,
        base_mult: int,
        hand_type: HandType,
        played_cards: list[Card],
        scoring_idxs: list[int],
        held_cards: list[Card],
        jokers: list[JokerCard],
        hand_levels: HandLevels,
        game_state: dict | None = None,
    ):
        self.chips = float(base_chips)
        self.mult = float(base_mult)
        self.hand_type = hand_type
        self.hand_contains = HAND_CONTAINS.get(hand_type, {hand_type})
        self.played_cards = played_cards
        self.scoring_idxs = scoring_idxs
        self.held_cards = held_cards
        self.jokers = jokers
        self.hand_levels = hand_levels
        self.game_state = game_state or {}
        self.pareidolia = any(j.key == "j_pareidolia" for j in jokers)
        self.has_smeared = any(j.key == "j_smeared" for j in jokers)
        self.chance_multiplier = 1
        for j in jokers:
            if j.key == "j_oops":
                self.chance_multiplier *= 2
        self.resolved_jokers = _resolve_blueprint_brainstorm(jokers)
        self.joker_extra_state: dict[str, object] = {}

    def suit_matches(self, card: Card, target: Suit) -> bool:
        """Check suit match accounting for Wild Card and Smeared Joker."""
        if card.enhancement == Enhancement.WILD:
            return True
        if card.suit == target:
            return True
        if self.has_smeared:
            RED = {Suit.HEARTS, Suit.DIAMONDS}
            BLACK = {Suit.CLUBS, Suit.SPADES}
            if target in RED and card.suit in RED:
                return True
            if target in BLACK and card.suit in BLACK:
                return True
        return False

    def add_chips(self, n: float):
        self.chips += n

    def add_mult(self, n: float):
        self.mult += n

    def x_mult(self, n: float):
        self.mult *= n


# ---------------------------------------------------------------------------
# Blueprint / Brainstorm resolution
# ---------------------------------------------------------------------------

def _resolve_blueprint_brainstorm(jokers: list[JokerCard]) -> list[JokerCard | None]:
    """Resolve Blueprint/Brainstorm copy chains.

    Blueprint copies the joker to its right.
    Brainstorm copies the leftmost joker.
    Chains resolve: Blueprint → Blueprint → X means both copy X.
    Returns list parallel to jokers: resolved[i] = effective joker (None = use self).
    """
    n = len(jokers)
    resolved: list[JokerCard | None] = [None] * n
    for i, j in enumerate(jokers):
        if j.key == "j_blueprint":
            # Walk right until non-Blueprint/Brainstorm found
            target = None
            for k in range(i + 1, n):
                if jokers[k].key not in ("j_blueprint", "j_brainstorm"):
                    target = jokers[k]
                    break
            resolved[i] = target  # None if no valid target
        elif j.key == "j_brainstorm":
            # Copy leftmost joker (if it's not itself)
            if n > 0 and jokers[0].key not in ("j_blueprint", "j_brainstorm"):
                resolved[i] = jokers[0]
            else:
                # Walk from left to find first non-copy joker
                for k in range(n):
                    if k != i and jokers[k].key not in ("j_blueprint", "j_brainstorm"):
                        resolved[i] = jokers[k]
                        break
    return resolved


# ---------------------------------------------------------------------------
# Per-card trigger: chips + enhancement + edition + per-card joker effects
# ---------------------------------------------------------------------------

def _trigger_card_scored(ctx: _ScoringContext, card: Card):
    """Process a single scoring card trigger."""
    if card.debuffed:
        return

    # Card chip value
    if card.enhancement == Enhancement.STONE:
        ctx.add_chips(50)
    else:
        ctx.add_chips(card.chip_value)
        if card.enhancement == Enhancement.BONUS:
            ctx.add_chips(30)

    # Card enhancement mult/xMult
    if card.enhancement == Enhancement.MULT:
        ctx.add_mult(4)
    elif card.enhancement == Enhancement.GLASS:
        ctx.x_mult(2.0)
    elif card.enhancement == Enhancement.LUCKY:
        chance = min(1.0, 0.2 * ctx.chance_multiplier)
        ctx.add_mult(20 * chance)

    # Card edition
    if card.edition == Edition.FOIL:
        ctx.add_chips(50)
    elif card.edition == Edition.HOLOGRAPHIC:
        ctx.add_mult(10)
    elif card.edition == Edition.POLYCHROME:
        ctx.x_mult(1.5)

    # Per-card joker triggers (L→R, using resolved jokers)
    for ji, j in enumerate(ctx.jokers):
        target = ctx.resolved_jokers[ji] if ctx.resolved_jokers[ji] is not None else j
        _joker_on_card_scored(ctx, target, card)


# ---------------------------------------------------------------------------
# Per-card joker effects (suit/rank/face bonuses)
# ---------------------------------------------------------------------------

def _joker_on_card_scored(ctx: _ScoringContext, joker: JokerCard, card: Card):
    """Joker effects that trigger per scoring card."""
    key = joker.key
    is_face = card.is_face or ctx.pareidolia

    # Suit-based +3 mult
    if key == "j_greedy_joker" and ctx.suit_matches(card, Suit.DIAMONDS):
        ctx.add_mult(3)
    elif key == "j_lusty_joker" and ctx.suit_matches(card, Suit.HEARTS):
        ctx.add_mult(3)
    elif key == "j_wrathful_joker" and ctx.suit_matches(card, Suit.SPADES):
        ctx.add_mult(3)
    elif key == "j_gluttenous_joker" and ctx.suit_matches(card, Suit.CLUBS):
        ctx.add_mult(3)

    # Suit-based chips
    elif key == "j_arrowhead" and ctx.suit_matches(card, Suit.SPADES):
        ctx.add_chips(50)

    # Suit-based mult (uncommon)
    elif key == "j_onyx_agate" and ctx.suit_matches(card, Suit.CLUBS):
        ctx.add_mult(7)

    # Bloodstone: Hearts → probability x1.5
    elif key == "j_bloodstone" and ctx.suit_matches(card, Suit.HEARTS):
        chance = min(1.0, 0.5 * ctx.chance_multiplier)
        ctx.x_mult(1.0 + 0.5 * chance)

    # Face card jokers
    elif key == "j_scary_face" and is_face:
        ctx.add_chips(30)
    elif key == "j_smiley" and is_face:
        ctx.add_mult(5)

    # Rank-based
    elif key == "j_fibonacci":
        if card.rank in (Rank.ACE, Rank.TWO, Rank.THREE, Rank.FIVE, Rank.EIGHT):
            ctx.add_mult(8)
    elif key == "j_even_steven":
        if card.rank.value in (2, 4, 6, 8, 10):
            ctx.add_mult(4)
    elif key == "j_odd_todd":
        if card.rank.value in (3, 5, 7, 9) or card.rank == Rank.ACE:
            ctx.add_chips(31)
    elif key == "j_scholar" and card.rank == Rank.ACE:
        ctx.add_chips(20)
        ctx.add_mult(4)
    elif key == "j_walkie_talkie":
        if card.rank in (Rank.TEN, Rank.FOUR):
            ctx.add_chips(10)
            ctx.add_mult(4)

    # Triboulet: King or Queen → x2
    elif key == "j_triboulet":
        if card.rank in (Rank.KING, Rank.QUEEN):
            ctx.x_mult(2.0)

    # Photograph: FIRST face card only → x2
    elif key == "j_photograph" and is_face:
        photo_key = f"photograph_{id(joker)}"
        if photo_key not in ctx.joker_extra_state:
            ctx.joker_extra_state[photo_key] = True
            ctx.x_mult(2.0)

    # Ancient Joker: matching suit → x1.5
    elif key == "j_ancient":
        val = joker.get_extra("value", None)
        if val is not None:
            suit_map = {0: Suit.SPADES, 1: Suit.HEARTS, 2: Suit.CLUBS, 3: Suit.DIAMONDS}
            if isinstance(val, (int, float)):
                target = suit_map.get(int(abs(val)) % 4, Suit.HEARTS)
            else:
                target = Suit.HEARTS
            if ctx.suit_matches(card, target):
                ctx.x_mult(1.5)

    # The Idol: specific rank+suit → x2
    elif key == "j_idol":
        val = joker.get_extra("value", None)
        if val is not None and isinstance(val, (int, float)):
            suit_map = {0: Suit.SPADES, 1: Suit.HEARTS, 2: Suit.CLUBS, 3: Suit.DIAMONDS}
            rank_map = {0: Rank.TWO, 1: Rank.THREE, 2: Rank.FOUR, 3: Rank.FIVE,
                        4: Rank.SIX, 5: Rank.SEVEN, 6: Rank.EIGHT, 7: Rank.NINE,
                        8: Rank.TEN, 9: Rank.JACK, 10: Rank.QUEEN, 11: Rank.KING,
                        12: Rank.ACE}
            target_suit = suit_map.get(int(abs(val)) % 4, Suit.HEARTS)
            target_rank = rank_map.get(int(abs(val) / 4) % 13, Rank.ACE)
            if card.rank == target_rank and ctx.suit_matches(card, target_suit):
                ctx.x_mult(2.0)

    # Hiker: +5 chips per scored card
    elif key == "j_hiker":
        ctx.add_chips(5)


# ---------------------------------------------------------------------------
# Held-in-hand card effects
# ---------------------------------------------------------------------------

def _trigger_held_card_inner(ctx: _ScoringContext, card: Card):
    """Inner held-in-hand trigger (Steel + held-card jokers)."""
    if card.debuffed:
        return

    # Steel Card: x1.5 mult
    if card.enhancement == Enhancement.STEEL:
        ctx.x_mult(1.5)

    # Per-card held-in-hand joker effects
    for ji, j in enumerate(ctx.jokers):
        target = ctx.resolved_jokers[ji] if ctx.resolved_jokers[ji] is not None else j
        jkey = target.key

        if jkey == "j_raised_fist":
            rf_key = f"raised_fist_card_{id(j)}"
            lowest_card = ctx.joker_extra_state.get(rf_key)
            if lowest_card is card and card.enhancement != Enhancement.STONE:
                ctx.add_mult(2 * card.chip_value)
        elif jkey == "j_baron":
            if card.rank == Rank.KING and card.enhancement != Enhancement.STONE:
                ctx.x_mult(1.5)
        elif jkey == "j_shoot_the_moon":
            if card.rank == Rank.QUEEN and card.enhancement != Enhancement.STONE:
                ctx.add_mult(13)


def _trigger_held_card(ctx: _ScoringContext, card: Card):
    """Process a held-in-hand card with retrigger support."""
    if card.debuffed:
        return

    _trigger_held_card_inner(ctx, card)

    # Red Seal retrigger
    if card.seal == Seal.RED:
        _trigger_held_card_inner(ctx, card)

    # Mime retrigger
    for ji, j in enumerate(ctx.jokers):
        target = ctx.resolved_jokers[ji] if ctx.resolved_jokers[ji] is not None else j
        if target.key == "j_mime":
            _trigger_held_card_inner(ctx, card)


# ---------------------------------------------------------------------------
# Independent joker effects (not per-card)
# ---------------------------------------------------------------------------

def _trigger_joker_independent(ctx: _ScoringContext, joker: JokerCard):
    """Joker's independent scoring effect. Applied left to right."""
    key = joker.key
    contains = ctx.hand_contains
    played = ctx.played_cards
    scoring = ctx.scoring_idxs
    held = ctx.held_cards
    all_jokers = ctx.jokers

    # ---- Flat mult jokers ----
    if key == "j_joker":
        ctx.add_mult(4)
    elif key == "j_jolly":
        if HandType.PAIR in contains:
            ctx.add_mult(8)
    elif key == "j_zany":
        if HandType.THREE_OF_A_KIND in contains:
            ctx.add_mult(12)
    elif key == "j_mad":
        if HandType.TWO_PAIR in contains:
            ctx.add_mult(10)
    elif key == "j_crazy":
        if HandType.STRAIGHT in contains:
            ctx.add_mult(12)
    elif key == "j_droll":
        if HandType.FLUSH in contains:
            ctx.add_mult(10)
    elif key == "j_half":
        if len(played) <= 3:
            ctx.add_mult(20)
    elif key == "j_misprint":
        ctx.add_mult(12)  # avg of 0-23

    elif key == "j_mystic_summit":
        val = joker.get_extra("value", 0)
        if val != 0:
            ctx.add_mult(15)

    elif key == "j_green_joker":
        val = joker.mult or 0
        hand_add = joker.get_extra("hand_add", 1) if isinstance(joker.extra, dict) else 1
        val += hand_add
        if val > 0:
            ctx.add_mult(val)

    elif key == "j_red_card":
        val = joker.mult
        if val and val > 0:
            ctx.add_mult(val)

    elif key == "j_supernova":
        # Number of times this hand type has been played
        gs = ctx.game_state
        played_count = gs.get("hands_played_counts", {}).get(ctx.hand_type.value, 0)
        if played_count > 0:
            ctx.add_mult(played_count)

    elif key == "j_ride_the_bus":
        val = joker.mult or 0
        has_face = any(c.is_face for c in played)
        if has_face:
            val = 0
        else:
            extra_add = joker.get_extra("value", 1) if isinstance(joker.extra, dict) else 1
            val += extra_add
        if val > 0:
            ctx.add_mult(val)

    elif key == "j_swashbuckler":
        val = joker.mult
        if val and val > 0:
            ctx.add_mult(val)

    # ---- Flat chip jokers ----
    elif key == "j_sly":
        if HandType.PAIR in contains:
            ctx.add_chips(50)
    elif key == "j_wily":
        if HandType.THREE_OF_A_KIND in contains:
            ctx.add_chips(100)
    elif key == "j_clever":
        if HandType.TWO_PAIR in contains:
            ctx.add_chips(80)
    elif key == "j_devious":
        if HandType.STRAIGHT in contains:
            ctx.add_chips(100)
    elif key == "j_crafty":
        if HandType.FLUSH in contains:
            ctx.add_chips(80)

    elif key == "j_banner":
        discards = ctx.game_state.get("discards_left", 0)
        ctx.add_chips(30 * discards)

    elif key == "j_abstract":
        n_jokers = len(all_jokers)
        ctx.add_mult(3 * n_jokers)

    elif key == "j_blue_joker":
        deck_remaining = ctx.game_state.get("remaining_deck", 0)
        ctx.add_chips(2 * deck_remaining)

    elif key == "j_runner":
        val = joker.t_chips
        if val and val > 0:
            ctx.add_chips(val)

    elif key == "j_ice_cream":
        val = joker.t_chips
        if val and val > 0:
            ctx.add_chips(val)

    elif key == "j_square":
        val = joker.t_chips
        if val and val > 0:
            ctx.add_chips(val)

    elif key == "j_popcorn":
        val = joker.mult
        if val and val > 0:
            ctx.add_mult(val)

    elif key == "j_bootstraps":
        dollars = ctx.game_state.get("dollars", 0)
        sets = dollars // 5
        ctx.add_mult(2 * sets)

    elif key == "j_wee":
        val = joker.t_chips
        if val and val > 0:
            ctx.add_chips(val)

    elif key == "j_fortune_teller":
        val = joker.mult
        if val and val > 0:
            ctx.add_mult(val)

    elif key == "j_flash":
        val = joker.mult
        if val and val > 0:
            ctx.add_mult(val)

    elif key == "j_trousers":
        val = joker.mult
        if val and val > 0:
            ctx.add_mult(val)

    elif key == "j_castle":
        val = joker.t_chips
        if val and val > 0:
            ctx.add_chips(val)

    elif key == "j_stone":
        # +25 chips per Stone Card in full deck
        stone_count = ctx.game_state.get("stone_cards_in_deck", 0)
        if stone_count > 0:
            ctx.add_chips(25 * stone_count)

    elif key == "j_loyalty_card":
        val = joker.get_extra("value", 0)
        if val != 0:
            ctx.x_mult(4.0)

    elif key == "j_gros_michel":
        ctx.add_mult(15)

    elif key == "j_cavendish":
        ctx.x_mult(3.0)

    # ---- xMult jokers ----
    elif key == "j_steel_joker":
        steel_count = ctx.game_state.get("steel_cards_in_deck", 0)
        if steel_count > 0:
            ctx.x_mult(1.0 + 0.2 * steel_count)

    elif key == "j_glass":
        glass_count = ctx.game_state.get("glass_cards_in_deck", 0)
        if glass_count > 0:
            ctx.x_mult(1.0 + 0.75 * glass_count)

    elif key == "j_hologram":
        val = joker.x_mult
        if val and val > 1:
            ctx.x_mult(val)

    elif key == "j_constellation":
        val = joker.x_mult
        if val and val > 1:
            ctx.x_mult(val)

    elif key == "j_lucky_cat":
        val = joker.x_mult
        if val and val > 1:
            ctx.x_mult(val)

    elif key == "j_vampire":
        val = joker.x_mult
        if val and val > 1:
            ctx.x_mult(val)

    elif key == "j_obelisk":
        val = joker.x_mult
        if val and val > 1:
            ctx.x_mult(val)

    elif key == "j_blackboard":
        # x3 if all held cards are Spades or Clubs
        if held and all(c.suit in (Suit.SPADES, Suit.CLUBS) for c in held):
            ctx.x_mult(3.0)
        elif not held:
            ctx.x_mult(3.0)

    elif key == "j_card_sharp":
        val = joker.get_extra("value", 0)
        if val != 0:
            ctx.x_mult(3.0)

    elif key == "j_acrobat":
        # x3 on last hand of round
        is_last = ctx.game_state.get("is_last_hand", False)
        if is_last:
            ctx.x_mult(3.0)

    elif key == "j_throwback":
        # x0.25 per skipped blind
        skipped = ctx.game_state.get("skipped_blinds", 0)
        if skipped > 0:
            ctx.x_mult(1.0 + 0.25 * skipped)

    elif key == "j_erosion":
        # +4 mult per card below 52 in deck
        deck_size = ctx.game_state.get("full_deck_size", 52)
        missing = max(0, 52 - deck_size)
        if missing > 0:
            ctx.add_mult(4 * missing)

    elif key == "j_stencil":
        # x1 per empty joker slot
        joker_slots = ctx.game_state.get("joker_slots", 5)
        filled = len(all_jokers)
        empty = max(0, joker_slots - filled)
        if empty > 0:
            ctx.x_mult(float(empty))

    # ---- Hand-type xMult jokers ----
    elif key == "j_duo":
        if HandType.PAIR in contains:
            ctx.x_mult(2.0)
    elif key == "j_trio":
        if HandType.THREE_OF_A_KIND in contains:
            ctx.x_mult(3.0)
    elif key == "j_family":
        if HandType.FOUR_OF_A_KIND in contains:
            ctx.x_mult(4.0)
    elif key == "j_order":
        if HandType.STRAIGHT in contains:
            ctx.x_mult(3.0)
    elif key == "j_tribe":
        if HandType.FLUSH in contains:
            ctx.x_mult(2.0)

    elif key == "j_stuntman":
        ctx.add_chips(250)

    # ---- Legendary jokers ----
    elif key == "j_canio":
        val = joker.x_mult
        if val and val > 1:
            ctx.x_mult(val)

    elif key == "j_yorick":
        val = joker.x_mult
        if val and val > 1:
            ctx.x_mult(val)

    elif key == "j_hit_the_road":
        val = joker.x_mult
        if val and val > 1:
            ctx.x_mult(val)

    elif key == "j_seeing_double":
        suits = set()
        for i in scoring:
            suits.add(played[i].suit)
        if Suit.CLUBS in suits and len(suits) >= 2:
            ctx.x_mult(2.0)

    elif key == "j_flower_pot":
        suits = set()
        for i in scoring:
            suits.add(played[i].suit)
        if len(suits) >= 4:
            ctx.x_mult(3.0)

    elif key == "j_drivers_license":
        val = joker.get_extra("value", 0)
        if val and val >= 16:
            ctx.x_mult(3.0)

    # Economy / utility jokers — no scoring effect
    # j_golden, j_egg, j_credit_card, j_delayed_grat, j_to_the_moon,
    # j_cloud_9, j_rocket, j_satellite, j_bull, j_trading, j_faceless,
    # j_rough_gem, j_ticket, j_diet_cola, j_ramen, j_gift, j_turtle_bean,
    # j_four_fingers, j_splash, j_shortcut, j_smeared, j_pareidolia,
    # j_hack, j_dusk, j_mime, j_sock_and_buskin, j_hanging_chad,
    # j_chaos, j_burglar, j_juggler, j_drunkard, j_troubadour,
    # j_merry_andy, j_marble, j_ceremonial, j_madness, j_riff_raff,
    # j_luchador, j_matador, j_mr_bones, j_invisible, j_showman,
    # j_cartomancer, j_astronomer, j_burnt, j_certificate, j_vagabond,
    # j_8_ball, j_sixth_sense, j_seance, j_superposition, j_space,
    # j_hallucination, j_todo_list, j_mail, j_reserved_parking,
    # j_business, j_dna, j_perkeo, j_chicot, j_oops, j_midas_mask,
    # j_selzer, j_brainstorm, j_blueprint


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------

def calculate_score(
    played_cards: list[Card],
    hand_type: HandType,
    scoring_indices: list[int],
    hand_levels: HandLevels,
    held_cards: Optional[list[Card]] = None,
    jokers: Optional[list[JokerCard]] = None,
    game_state: Optional[dict] = None,
) -> ScoreResult:
    """Calculate the score for a played hand using full Balatro trigger pipeline.

    Args:
        played_cards: Cards that were played.
        hand_type: The identified hand type.
        scoring_indices: Indices into played_cards that are scoring.
        hand_levels: Current hand level upgrades.
        held_cards: Cards remaining in hand.
        jokers: Active jokers.
        game_state: Optional dict with runtime state (dollars, deck info, etc).

    Returns:
        ScoreResult with chips, mult, and final score.
    """
    if jokers is None:
        jokers = []
    if held_cards is None:
        held_cards = []

    # Splash: all played cards count as scoring
    if any(j.key == "j_splash" for j in jokers):
        scoring_indices = list(range(len(played_cards)))

    base_chips, base_mult = hand_levels.get_base(hand_type)

    ctx = _ScoringContext(
        base_chips=base_chips,
        base_mult=base_mult,
        hand_type=hand_type,
        played_cards=played_cards,
        scoring_idxs=scoring_indices,
        held_cards=held_cards,
        jokers=jokers,
        hand_levels=hand_levels,
        game_state=game_state,
    )

    # DNA: if exactly 1 card played, add a copy to held cards
    if len(played_cards) == 1 and any(j.key == "j_dna" for j in jokers):
        ctx.held_cards = list(ctx.held_cards) + [played_cards[0]]

    # Phase 1: Score each scoring card (L→R) with retriggers
    first_scored = True
    for idx in scoring_indices:
        card = played_cards[idx]
        _trigger_card_scored(ctx, card)

        # Red Seal retrigger
        if card.seal == Seal.RED:
            _trigger_card_scored(ctx, card)

        # Retrigger jokers (per-card)
        is_face = card.is_face or ctx.pareidolia
        for j in jokers:
            jkey = j.key
            if jkey == "j_hack" and card.rank.value <= 5:
                _trigger_card_scored(ctx, card)
            elif jkey == "j_hanging_chad" and first_scored:
                _trigger_card_scored(ctx, card)
                _trigger_card_scored(ctx, card)
            elif jkey == "j_sock_and_buskin" and is_face:
                _trigger_card_scored(ctx, card)
            elif jkey == "j_selzer":
                _trigger_card_scored(ctx, card)
            elif jkey == "j_dusk":
                val = j.get_extra("value", 0)
                if val != 0:  # last hand of round
                    _trigger_card_scored(ctx, card)

        first_scored = False

    # Pre-compute Raised Fist: find lowest rank held card
    for j in jokers:
        if j.key == "j_raised_fist" and ctx.held_cards:
            eligible = [c for c in ctx.held_cards if c.enhancement != Enhancement.STONE]
            if eligible:
                lowest_rank = min(c.rank.value for c in eligible)
                lowest_card = [c for c in eligible if c.rank.value == lowest_rank][-1]
                ctx.joker_extra_state[f"raised_fist_card_{id(j)}"] = lowest_card

    # Phase 2: Held-in-hand card effects
    for card in ctx.held_cards:
        _trigger_held_card(ctx, card)

    # Phase 3: Independent joker effects (L→R)
    # Count Baseball Cards for uncommon bonus
    baseball_count = sum(1 for j in jokers if j.key == "j_baseball")
    for ji, j in enumerate(jokers):
        target = ctx.resolved_jokers[ji]
        if target is not None:
            _trigger_joker_independent(ctx, target)
        else:
            _trigger_joker_independent(ctx, j)

        # Baseball Card: x1.5 per Baseball Card for each Uncommon joker
        if baseball_count > 0:
            # Check rarity — JokerCard doesn't have rarity field, check via data
            from .data import JOKER_CATALOG, Rarity
            jdef = JOKER_CATALOG.get(j.key)
            if jdef and jdef.rarity == Rarity.UNCOMMON:
                for _ in range(baseball_count):
                    ctx.x_mult(1.5)

        # Joker edition effects (after joker's own effect)
        if j.edition == Edition.FOIL:
            ctx.add_chips(50)
        elif j.edition == Edition.HOLOGRAPHIC:
            ctx.add_mult(10)
        elif j.edition == Edition.POLYCHROME:
            ctx.x_mult(1.5)

    # Final score
    final = max(0, int(ctx.chips * ctx.mult))

    return ScoreResult(
        hand_type=hand_type,
        chips=ctx.chips,
        mult=ctx.mult,
        final_score=final,
        scoring_indices=scoring_indices,
    )
