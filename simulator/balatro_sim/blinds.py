"""Boss blind definitions and effect system.

Each boss blind has effects that hook into different game phases:
- on_round_start: modify state when round begins
- on_pre_play: validate/modify before a hand is played
- on_post_play: trigger after a hand is scored
- on_draw: modify cards as they're drawn
- on_discard: trigger after discarding
- debuff_check: determine if a card should be debuffed
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .state import GameState
    from .cards import Card


class BossEffect(str, Enum):
    """Categories of boss blind effects for AI reasoning."""
    DEBUFF_SUIT = "debuff_suit"       # Debuffs cards of a specific suit
    DEBUFF_FACE = "debuff_face"       # Debuffs face cards
    RESTRICT_PLAY = "restrict_play"   # Restricts how you can play
    MODIFY_SCORE = "modify_score"     # Modifies scoring
    MODIFY_ECONOMY = "modify_economy" # Affects money
    MODIFY_HAND = "modify_hand"       # Changes hand/discard counts
    MODIFY_CARDS = "modify_cards"     # Flips/hides/discards cards
    MODIFY_JOKERS = "modify_jokers"   # Affects jokers
    SCALE_BLIND = "scale_blind"       # Increases blind target


@dataclass
class BossBlind:
    """Definition of a boss blind."""
    key: str                    # e.g. "bl_hook"
    name: str                   # e.g. "The Hook"
    description: str            # Player-facing description
    effect_type: BossEffect
    min_ante: int = 1           # Earliest ante this boss can appear
    debuff_suit: Optional[str] = None  # For suit-debuff bosses

    def apply_round_start(self, state: "GameState") -> "GameState":
        """Apply effects at the start of a round. Override in specific bosses."""
        return _ROUND_START_EFFECTS.get(self.key, _noop)(state, self)

    def apply_debuffs(self, state: "GameState") -> "GameState":
        """Apply card debuffs based on boss effect."""
        return _apply_debuffs(state, self)

    def validate_play(self, state: "GameState", card_indices: tuple[int, ...]) -> Optional[str]:
        """Check if a play is legal under this boss. Returns error message or None."""
        return _PLAY_VALIDATORS.get(self.key, lambda s, i, b: None)(state, card_indices, self)

    def on_post_play(self, state: "GameState") -> "GameState":
        """Effects after a hand is played and scored."""
        return _POST_PLAY_EFFECTS.get(self.key, _noop)(state, self)

    def on_post_discard(self, state: "GameState") -> "GameState":
        """Effects after discarding."""
        return _POST_DISCARD_EFFECTS.get(self.key, _noop)(state, self)

    def modify_blind_chips(self, base_chips: int) -> int:
        """Modify the blind chip target."""
        if self.key == "bl_wall":
            return base_chips * 2
        return base_chips

    def modify_scoring(self, chips: float, mult: float, state: "GameState") -> tuple[float, float]:
        """Modify chips/mult during scoring."""
        if self.key == "bl_flint":
            # Halve base chips and mult (applied to hand-type base, not total)
            # This is handled in scoring integration, not here
            pass
        return chips, mult


# ============================================================
# Boss Blind Registry
# ============================================================

# All 25 base-game boss blinds
BOSS_BLINDS: dict[str, BossBlind] = {}


def _register(key: str, name: str, desc: str, effect: BossEffect,
              min_ante: int = 1, debuff_suit: str = None) -> BossBlind:
    b = BossBlind(key=key, name=name, description=desc, effect_type=effect,
                  min_ante=min_ante, debuff_suit=debuff_suit)
    BOSS_BLINDS[key] = b
    return b


# --- Suit debuff bosses ---
_register("bl_club", "The Club", "All Club cards are debuffed",
          BossEffect.DEBUFF_SUIT, debuff_suit="Clubs")
_register("bl_goad", "The Goad", "All Spade cards are debuffed",
          BossEffect.DEBUFF_SUIT, debuff_suit="Spades")
_register("bl_window", "The Window", "All Diamond cards are debuffed",
          BossEffect.DEBUFF_SUIT, debuff_suit="Diamonds")
_register("bl_head", "The Head", "All Heart cards are debuffed",
          BossEffect.DEBUFF_SUIT, debuff_suit="Hearts")

# --- Face card debuff ---
_register("bl_plant", "The Plant", "All face cards are debuffed",
          BossEffect.DEBUFF_FACE)

# --- Restrict play ---
_register("bl_psychic", "The Psychic", "Must play 5 cards",
          BossEffect.RESTRICT_PLAY)
_register("bl_eye", "The Eye", "No repeat hand types this round",
          BossEffect.RESTRICT_PLAY, min_ante=2)
_register("bl_mouth", "The Mouth", "Only play 1 hand type this round",
          BossEffect.RESTRICT_PLAY, min_ante=2)

# --- Modify scoring ---
_register("bl_flint", "The Flint", "Base chips and mult are halved",
          BossEffect.MODIFY_SCORE, min_ante=2)
_register("bl_arm", "The Arm", "Decrease level of played poker hand by 1",
          BossEffect.MODIFY_SCORE, min_ante=2)
_register("bl_ox", "The Ox", "Playing a #? hand sets money to $0",
          BossEffect.MODIFY_ECONOMY)

# --- Modify hand/discard counts ---
_register("bl_water", "The Water", "Start with 0 discards",
          BossEffect.MODIFY_HAND)
_register("bl_needle", "The Needle", "Play only 1 hand",
          BossEffect.MODIFY_HAND, min_ante=2)
_register("bl_manacle", "The Manacle", "-1 hand size",
          BossEffect.MODIFY_HAND, min_ante=2)

# --- Modify cards ---
_register("bl_hook", "The Hook", "Discards 2 random cards per hand played",
          BossEffect.MODIFY_CARDS)
_register("bl_fish", "The Fish", "Cards drawn after play are face down",
          BossEffect.MODIFY_CARDS)
_register("bl_house", "The House", "All cards are drawn face down",
          BossEffect.MODIFY_CARDS)
_register("bl_wheel", "The Wheel", "1 in 7 cards drawn face down",
          BossEffect.MODIFY_CARDS)
_register("bl_mark", "The Mark", "All face cards drawn face down",
          BossEffect.MODIFY_CARDS)
_register("bl_serpent", "The Serpent", "After play or discard, always draw to full hand",
          BossEffect.MODIFY_CARDS)
_register("bl_pillar", "The Pillar", "Cards played previously this ante are debuffed",
          BossEffect.MODIFY_CARDS, min_ante=2)

# --- Scale blind ---
_register("bl_wall", "The Wall", "Extra large blind",
          BossEffect.SCALE_BLIND)

# --- Modify jokers ---
_register("bl_cerulean", "Cerulean Bell", "Forces 1 card to always be selected",
          BossEffect.MODIFY_CARDS, min_ante=2)
_register("bl_crimson", "Crimson Heart", "1 random joker disabled each hand",
          BossEffect.MODIFY_JOKERS, min_ante=3)
_register("bl_amber", "Amber Acorn", "Flips and shuffles all jokers",
          BossEffect.MODIFY_JOKERS, min_ante=3)
_register("bl_verdant", "Verdant Leaf", "All cards debuffed until 1 joker sold",
          BossEffect.MODIFY_JOKERS, min_ante=3)


# ============================================================
# Effect Implementations
# ============================================================

def _noop(state: "GameState", boss: BossBlind) -> "GameState":
    return state


# --- Round Start Effects ---

def _water_round_start(state: "GameState", boss: BossBlind) -> "GameState":
    state.discards_left = 0
    return state


def _needle_round_start(state: "GameState", boss: BossBlind) -> "GameState":
    state.hands_left = 1
    return state


def _manacle_round_start(state: "GameState", boss: BossBlind) -> "GameState":
    state.hand_size -= 1
    # Trim hand if over new limit
    while len(state.hand) > state.hand_size and state.hand:
        card = state.hand.pop()
        state.discard_pile.append(card)
    return state


def _hook_round_start(state: "GameState", boss: BossBlind) -> "GameState":
    # Hook discards 2 random cards per hand played — handled in on_post_play
    return state


def _serpent_round_start(state: "GameState", boss: BossBlind) -> "GameState":
    # Serpent: draw to full hand after every play/discard — handled in post hooks
    return state


def _pillar_round_start(state: "GameState", boss: BossBlind) -> "GameState":
    # Pillar debuffs cards played previously this ante — debuffs applied in apply_debuffs
    return state


_ROUND_START_EFFECTS: dict[str, Callable] = {
    "bl_water": _water_round_start,
    "bl_needle": _needle_round_start,
    "bl_manacle": _manacle_round_start,
    "bl_hook": _hook_round_start,
    "bl_serpent": _serpent_round_start,
    "bl_pillar": _pillar_round_start,
}


# --- Play Validators ---

def _psychic_validate(state: "GameState", indices: tuple[int, ...], boss: BossBlind) -> Optional[str]:
    if len(indices) < 5 and len(state.hand) >= 5:
        return "The Psychic requires playing 5 cards"
    return None


def _eye_validate(state: "GameState", indices: tuple[int, ...], boss: BossBlind) -> Optional[str]:
    from .hands import evaluate_hand
    played = [state.hand[i] for i in indices]
    hand_type, _ = evaluate_hand(played)
    if hand_type.value in state.hands_played_this_round:
        return f"The Eye: cannot repeat {hand_type.value}"
    return None


def _mouth_validate(state: "GameState", indices: tuple[int, ...], boss: BossBlind) -> Optional[str]:
    from .hands import evaluate_hand
    played = [state.hand[i] for i in indices]
    hand_type, _ = evaluate_hand(played)
    if state.hands_played_this_round and hand_type.value not in state.hands_played_this_round:
        return f"The Mouth: must play {list(state.hands_played_this_round)[0]}"
    return None


_PLAY_VALIDATORS: dict[str, Callable] = {
    "bl_psychic": _psychic_validate,
    "bl_eye": _eye_validate,
    "bl_mouth": _mouth_validate,
}


# --- Post-Play Effects ---

def _hook_post_play(state: "GameState", boss: BossBlind) -> "GameState":
    """Discard 2 random cards from hand."""
    if len(state.hand) <= 0:
        return state
    n_discard = min(2, len(state.hand))
    if state.rng:
        for i in range(n_discard):
            if not state.hand:
                break
            idx = state.rng.pseudorandom_int("boss_hook", 0, len(state.hand) - 1)
            card = state.hand.pop(idx)
            state.discard_pile.append(card)
    else:
        for _ in range(n_discard):
            if state.hand:
                state.discard_pile.append(state.hand.pop(0))
    return state


def _eye_post_play(state: "GameState", boss: BossBlind) -> "GameState":
    """Track played hand types for The Eye."""
    # hand type tracking is done in engine after scoring
    return state


def _mouth_post_play(state: "GameState", boss: BossBlind) -> "GameState":
    """Track played hand type for The Mouth."""
    return state


def _arm_post_play(state: "GameState", boss: BossBlind) -> "GameState":
    """Decrease level of the played hand type by 1."""
    # Actual level decrease is handled in engine after scoring
    return state


def _ox_post_play(state: "GameState", boss: BossBlind) -> "GameState":
    """If the most played hand type was played, set money to $0."""
    # Checked in engine after scoring
    return state


def _serpent_post_play(state: "GameState", boss: BossBlind) -> "GameState":
    """Draw back to full hand after playing."""
    while len(state.hand) < state.hand_size and state.draw_pile:
        state.hand.append(state.draw_pile.pop(0))
    return state


_POST_PLAY_EFFECTS: dict[str, Callable] = {
    "bl_hook": _hook_post_play,
    "bl_eye": _eye_post_play,
    "bl_mouth": _mouth_post_play,
    "bl_arm": _arm_post_play,
    "bl_ox": _ox_post_play,
    "bl_serpent": _serpent_post_play,
}


# --- Post-Discard Effects ---

def _serpent_post_discard(state: "GameState", boss: BossBlind) -> "GameState":
    """Draw back to full hand after discarding."""
    while len(state.hand) < state.hand_size and state.draw_pile:
        state.hand.append(state.draw_pile.pop(0))
    return state


_POST_DISCARD_EFFECTS: dict[str, Callable] = {
    "bl_serpent": _serpent_post_discard,
}


# --- Debuff Application ---

def _apply_debuffs(state: "GameState", boss: BossBlind) -> "GameState":
    """Apply card debuffs based on boss blind effect."""
    if boss.effect_type == BossEffect.DEBUFF_SUIT and boss.debuff_suit:
        for card in state.hand:
            if card.suit.value == boss.debuff_suit:
                card.debuffed = True
        for card in state.draw_pile:
            if card.suit.value == boss.debuff_suit:
                card.debuffed = True

    elif boss.key == "bl_plant":
        for card in state.hand:
            if card.is_face:
                card.debuffed = True
        for card in state.draw_pile:
            if card.is_face:
                card.debuffed = True

    elif boss.key == "bl_pillar":
        played_keys = state.boss_cards_played_this_ante
        for card in state.hand:
            card_key = f"{card.rank.value}_{card.suit.value}"
            if card_key in played_keys:
                card.debuffed = True

    elif boss.key == "bl_verdant":
        # All cards debuffed until a joker is sold
        if not state.boss_joker_sold:
            for card in state.hand:
                card.debuffed = True
            for card in state.draw_pile:
                card.debuffed = True

    return state


# ============================================================
# Boss Selection
# ============================================================

# Pool of bosses available per ante range
def get_boss_pool(ante: int) -> list[BossBlind]:
    """Get the pool of possible boss blinds for a given ante."""
    return [b for b in BOSS_BLINDS.values() if b.min_ante <= ante]


def select_boss_blind(
    ante: int,
    rng: Optional["RNGState"] = None,
    excluded: Optional[set[str]] = None,
) -> BossBlind:
    """Select a boss blind for the given ante.

    Args:
        ante: Current ante number.
        rng: RNG state for deterministic selection.
        excluded: Set of boss keys to exclude (recently seen).

    Returns:
        Selected BossBlind.
    """
    pool = get_boss_pool(ante)
    if excluded:
        pool = [b for b in pool if b.key not in excluded]
    if not pool:
        # Fallback: use full pool if exclusions removed everything
        pool = get_boss_pool(ante)

    if rng:
        return rng.random_element(f"boss_ante_{ante}", pool)
    else:
        import random
        return random.choice(pool)


# ============================================================
# Skip Tags
# ============================================================

class SkipTag(str, Enum):
    """Tags awarded for skipping blinds."""
    UNCOMMON = "Uncommon Tag"       # Free Uncommon Joker
    RARE = "Rare Tag"               # Free Rare Joker
    NEGATIVE = "Negative Tag"       # Next shop joker is free + Negative
    FOIL = "Foil Tag"               # Next shop joker is Foil
    HOLO = "Holographic Tag"        # Next shop joker is Holographic
    POLY = "Polychrome Tag"         # Next shop joker is Polychrome
    INVESTMENT = "Investment Tag"   # +$25 after beating boss
    VOUCHER = "Voucher Tag"         # Adds a Voucher to next shop
    BOSS = "Boss Tag"               # Rerolls boss blind
    STANDARD = "Standard Tag"       # Free Standard Pack
    CHARM = "Charm Tag"             # Free Arcana Pack
    METEOR = "Meteor Tag"           # Free Celestial Pack
    BUFFOON = "Buffoon Tag"         # Free Buffoon Pack
    HANDY = "Handy Tag"             # +$1 per hand played this run
    GARBAGE = "Garbage Tag"         # +$1 per unused discard this run
    ETHEREAL = "Ethereal Tag"       # Free Spectral Pack
    COUPON = "Coupon Tag"           # All shop items free next shop
    DOUBLE = "Double Tag"           # Duplicates next tag
    JUGGLE = "Juggle Tag"           # +3 hand size next round
    D6 = "D6 Tag"                   # Free rerolls next shop
    ECONOMY = "Economy Tag"         # Max interest cap +$5
    ORBITAL = "Orbital Tag"         # +3 levels to a hand type
    TOP_UP = "Top-up Tag"           # Fill joker slots with Common jokers


# Simplified tag pool (weighted by ante)
_BASE_TAG_POOL = [
    SkipTag.UNCOMMON, SkipTag.RARE, SkipTag.FOIL, SkipTag.HOLO,
    SkipTag.POLY, SkipTag.INVESTMENT, SkipTag.VOUCHER, SkipTag.BOSS,
    SkipTag.STANDARD, SkipTag.CHARM, SkipTag.METEOR, SkipTag.BUFFOON,
    SkipTag.HANDY, SkipTag.GARBAGE, SkipTag.ETHEREAL, SkipTag.COUPON,
    SkipTag.DOUBLE, SkipTag.JUGGLE, SkipTag.D6, SkipTag.ECONOMY,
    SkipTag.ORBITAL, SkipTag.TOP_UP,
]


def select_skip_tag(rng: Optional["RNGState"] = None, ante: int = 1) -> SkipTag:
    """Select a random skip tag."""
    if rng:
        return rng.random_element(f"skip_tag_{ante}", _BASE_TAG_POOL)
    else:
        import random
        return random.choice(_BASE_TAG_POOL)
