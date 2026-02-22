"""Balatro scoring engine — accurate sequential chip/mult calculation.

Implements the real Balatro scoring pipeline (matching EFHIII calculator):
  1. Start with hand-type base chips & base mult (from hand level)
  2. For each scoring card (left to right):
     - Add card's chip value (rank chips + enhancement chips)
     - Apply card enhancement mult effects (+mult or xMult)
     - Apply card edition effects (foil +50 chips, holo +10 mult, poly x1.5)
     - For each joker (left to right): apply per-card-scored triggers
     - If Red Seal: retrigger the card
  3. For each held-in-hand card: apply Steel Card xMult, joker held-card effects
  4. For each joker (left to right):
     - Apply joker's independent scoring effect
     - Apply joker edition (foil/holo/poly)
  5. final_score = chips × mult

Key difference from v1: mult is accumulated SEQUENTIALLY, not separated into
add_mult/x_mult pools. This means joker ORDER matters — matching real Balatro.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations
from typing import Optional


# ============================================================
# Constants
# ============================================================

RANK_VALUES = {
    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8,
    "9": 9, "10": 10, "Jack": 10, "Queen": 10, "King": 10, "Ace": 11,
    # Short aliases
    "J": 10, "Q": 10, "K": 10, "A": 11,
}

RANK_NUM = {
    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8,
    "9": 9, "10": 10, "Jack": 11, "Queen": 12, "King": 13, "Ace": 14,
    # Short aliases used by Card constructor and game state
    "J": 11, "Q": 12, "K": 13, "A": 14,
}

FACE_RANKS = {"Jack", "Queen", "King", "J", "Q", "K"}

# Balatro base scoring for each hand type: (base_chips, base_mult, rank)
HAND_BASE = {
    "Flush Five":       (160, 16, 12),
    "Flush House":      (140, 14, 11),
    "Five of a Kind":   (120, 12, 10),
    "Straight Flush":   (100,  8,  9),
    "Four of a Kind":   ( 60,  7,  8),
    "Full House":       ( 40,  4,  7),
    "Flush":            ( 35,  4,  6),
    "Straight":         ( 30,  4,  5),
    "Three of a Kind":  ( 30,  3,  4),
    "Two Pair":         ( 20,  2,  3),
    "Pair":             ( 10,  2,  2),
    "High Card":        (  5,  1,  1),
}

# Planet card level-up bonuses: (chips_per_level, mult_per_level)
PLANET_BONUS = {
    "Flush Five":       (50, 3),
    "Flush House":      (40, 4),
    "Five of a Kind":   (35, 3),
    "Straight Flush":   (40, 4),
    "Four of a Kind":   (30, 3),
    "Full House":       (25, 2),
    "Flush":            (15, 2),
    "Straight":         (30, 3),
    "Three of a Kind":  (20, 2),
    "Two Pair":         (20, 2),
    "Pair":             (15, 1),
    "High Card":        (10, 1),
}

# Hand types that "contain" sub-types (for joker triggers like Jolly Joker)
HAND_CONTAINS = {
    "Flush Five":      {"Flush Five", "Five of a Kind", "Four of a Kind", "Three of a Kind", "Pair", "Flush"},
    "Flush House":     {"Flush House", "Full House", "Three of a Kind", "Pair", "Flush"},
    "Five of a Kind":  {"Five of a Kind", "Four of a Kind", "Three of a Kind", "Pair"},
    "Straight Flush":  {"Straight Flush", "Straight", "Flush"},
    "Four of a Kind":  {"Four of a Kind", "Three of a Kind", "Pair"},
    "Full House":      {"Full House", "Three of a Kind", "Two Pair", "Pair"},
    "Flush":           {"Flush"},
    "Straight":        {"Straight"},
    "Three of a Kind": {"Three of a Kind", "Pair"},
    "Two Pair":        {"Two Pair", "Pair"},
    "Pair":            {"Pair"},
    "High Card":       {"High Card"},
}


# ============================================================
# Data Types
# ============================================================

@dataclass
class Card:
    """A playing card with all Balatro modifiers."""
    rank: str       # "2"-"10", "Jack", "Queen", "King", "Ace"
    suit: str       # "Hearts", "Diamonds", "Clubs", "Spades"
    enhancement: str = ""
    edition: str = ""
    seal: str = ""
    index: int = 0  # position in hand
    debuffed: bool = False  # boss blind debuff — card contributes nothing

    @property
    def chip_value(self) -> int:
        return RANK_VALUES.get(self.rank, 0)

    @property
    def rank_num(self) -> int:
        return RANK_NUM.get(self.rank, 0)

    @property
    def is_face(self) -> bool:
        return self.rank in FACE_RANKS

    @classmethod
    def from_state(cls, data: dict, index: int = 0) -> "Card":
        enh = data.get("enhancement", "")
        if enh in ("Default Base", "Base", ""):
            enh = ""
        return cls(
            rank=data.get("value", data.get("rank", "?")),
            suit=data.get("suit", "?"),
            enhancement=enh,
            edition=data.get("edition", ""),
            seal=data.get("seal", ""),
            index=index,
        )


@dataclass
class Joker:
    """A joker card with runtime state from the game."""
    name: str
    id: str = ""
    edition: str = ""
    rarity: str = ""
    sell_value: int = 0
    # Runtime state from card.ability.extra (number or dict)
    extra: int | float | dict | None = None
    # Direct ability fields
    mult: float = 0
    t_mult: float = 0
    t_chips: float = 0
    x_mult: float = 0

    def get_extra(self, key: str, default=0):
        """Get a value from extra dict, or return extra if it's a number."""
        if isinstance(self.extra, dict):
            return self.extra.get(key, default)
        if isinstance(self.extra, (int, float)) and key == "value":
            return self.extra
        return default

    @classmethod
    def from_state(cls, data: dict) -> "Joker":
        return cls(
            name=data.get("name", "?"),
            id=data.get("id", ""),
            edition=data.get("edition", ""),
            rarity=data.get("rarity", ""),
            sell_value=data.get("sell_value", 0),
            extra=data.get("extra"),
            mult=data.get("mult", 0),
            t_mult=data.get("t_mult", 0),
            t_chips=data.get("t_chips", 0),
            x_mult=data.get("x_mult", 0),
        )


@dataclass
class HandLevel:
    """Tracks planet card upgrades for each hand type."""
    levels: dict[str, int] = field(default_factory=lambda: {k: 1 for k in HAND_BASE})
    _game_base: dict[str, tuple[int, int]] = field(default_factory=dict)
    played_counts: dict[str, int] = field(default_factory=dict)

    def get_base(self, hand_type: str) -> tuple[int, int]:
        """Return (chips, mult) for a hand type at its current level."""
        if hand_type in self._game_base:
            return self._game_base[hand_type]
        base_chips, base_mult, _ = HAND_BASE.get(hand_type, (5, 1, 1))
        level = self.levels.get(hand_type, 1)
        bonus_chips, bonus_mult = PLANET_BONUS.get(hand_type, (10, 1))
        extra_levels = level - 1
        return (base_chips + bonus_chips * extra_levels,
                base_mult + bonus_mult * extra_levels)

    @classmethod
    def from_game_state(cls, hand_levels_data: dict) -> "HandLevel":
        hl = cls()
        for name, data in hand_levels_data.items():
            if isinstance(data, dict):
                hl.levels[name] = data.get("level", 1)
                chips = data.get("chips", 0)
                mult = data.get("mult", 0)
                if chips > 0 or mult > 0:
                    hl._game_base[name] = (chips, mult)
                played = data.get("played", 0)
                if played > 0:
                    hl.played_counts[name] = played
        return hl


@dataclass
class ScoreBreakdown:
    """Detailed scoring breakdown for a hand."""
    hand_type: str
    hand_rank: int
    base_chips: int
    base_mult: int
    card_chips: int
    add_chips: int      # total added chips (from jokers, editions, enhancements)
    add_mult: int       # total added mult (for backward compat reporting)
    x_mult: float       # product of all xMult sources (for backward compat reporting)
    final_score: float
    scoring_cards: list[int]
    all_cards: list[int]

    @property
    def total_chips(self) -> int:
        return self.base_chips + self.card_chips + self.add_chips

    @property
    def total_mult(self) -> float:
        return (self.base_mult + self.add_mult) * self.x_mult


# ============================================================
# Hand Classification
# ============================================================

def _check_straight(ranks: list[int], shortcut: bool = False) -> bool:
    """Check if ranks form a straight (including A-2-3-4-5 and 10-J-Q-K-A).

    Args:
        shortcut: If True, straights can have gaps of 1 (Shortcut joker).
    """
    s = sorted(set(ranks))
    if len(s) < 5:
        return False

    if not shortcut:
        if s[-1] - s[0] == 4 and len(s) == 5:
            return True
        # Ace-low straight
        if set(s) == {14, 2, 3, 4, 5}:
            return True
    else:
        # Shortcut: allow gaps of 1 in a 5-card window
        # Check all 5-card windows in sorted unique ranks
        for i in range(len(s) - 4):
            window = s[i:i+5]
            if window[-1] - window[0] <= 5:  # max span of 5 allows one gap
                # Verify each consecutive gap is <= 2
                if all(window[j+1] - window[j] <= 2 for j in range(4)):
                    return True
        # Ace-low with shortcut: A,2,3,4,5 or A,2,3,4,6 or A,2,3,5,6 etc.
        if 14 in s:
            low = sorted([1 if r == 14 else r for r in s])
            for i in range(len(low) - 4):
                window = low[i:i+5]
                if window[-1] - window[0] <= 5:
                    if all(window[j+1] - window[j] <= 2 for j in range(4)):
                        return True
    return False


def _check_straight_4(ranks: list[int], shortcut: bool = False) -> bool:
    """Check if ranks form a 4-card straight (Four Fingers joker)."""
    s = sorted(set(ranks))
    if len(s) < 4:
        return False

    max_gap = 2 if shortcut else 1
    for i in range(len(s) - 3):
        window = s[i:i+4]
        if window[-1] - window[0] <= 3 + (1 if shortcut else 0):
            if all(window[j+1] - window[j] <= max_gap for j in range(3)):
                return True
    # Ace-low
    if 14 in s:
        low = sorted([1 if r == 14 else r for r in s])
        for i in range(len(low) - 3):
            window = low[i:i+4]
            if window[-1] - window[0] <= 3 + (1 if shortcut else 0):
                if all(window[j+1] - window[j] <= max_gap for j in range(3)):
                    return True
    return False


def classify_hand(cards: list[Card], jokers: list[Joker] | None = None) -> tuple[str, list[int]]:
    """Classify a set of cards into a poker hand type.

    Accounts for rule-changing jokers:
    - Shortcut: Straights can have gaps of 1
    - Four Fingers: Flushes/Straights need only 4 cards
    - Smeared Joker: Hearts=Diamonds, Clubs=Spades

    Returns (hand_type, scoring_card_indices).
    """
    if not cards:
        return ("High Card", [])

    # Detect rule-changing jokers
    joker_names = {j.name for j in (jokers or [])}
    has_shortcut = "Shortcut" in joker_names
    has_four_fingers = "Four Fingers" in joker_names
    has_smeared = "Smeared Joker" in joker_names

    n = len(cards)
    ranks = [c.rank_num for c in cards]

    # Suit handling: Smeared Joker merges red (Hearts/Diamonds) and black (Clubs/Spades)
    if has_smeared:
        suits = []
        for c in cards:
            if c.suit in ("Hearts", "Diamonds"):
                suits.append("Red")
            elif c.suit in ("Clubs", "Spades"):
                suits.append("Black")
            else:
                suits.append(c.suit)
    else:
        suits = [c.suit for c in cards]

    rc = Counter(ranks).most_common()

    # Flush detection
    flush_min = 4 if has_four_fingers else 5
    suit_counts = Counter(suits)
    is_flush = suit_counts.most_common(1)[0][1] >= flush_min if n >= flush_min else False
    flush_suit = suit_counts.most_common(1)[0][0] if is_flush else None

    # Straight detection
    straight_min = 4 if has_four_fingers else 5
    if has_four_fingers:
        is_straight = _check_straight_4(ranks, shortcut=has_shortcut) if n >= 4 else False
    else:
        is_straight = _check_straight(ranks, shortcut=has_shortcut) if n >= 5 else False

    # Five of a Kind
    if rc[0][1] >= 5:
        idxs = [i for i, c in enumerate(cards) if c.rank_num == rc[0][0]][:5]
        if is_flush:
            return ("Flush Five", idxs)
        return ("Five of a Kind", idxs)

    if is_flush and is_straight:
        return ("Straight Flush", list(range(n)))

    if rc[0][1] >= 4:
        quad_rank = rc[0][0]
        quad_idxs = [i for i, c in enumerate(cards) if c.rank_num == quad_rank]
        kicker = [i for i in range(n) if i not in quad_idxs]
        return ("Four of a Kind", quad_idxs + kicker[:1])

    if len(rc) >= 2 and rc[0][1] == 3 and rc[1][1] >= 2:
        trip_rank = rc[0][0]
        pair_rank = rc[1][0]
        trip_idxs = [i for i, c in enumerate(cards) if c.rank_num == trip_rank][:3]
        pair_idxs = [i for i, c in enumerate(cards) if c.rank_num == pair_rank][:2]
        scoring = trip_idxs + pair_idxs
        if is_flush:
            return ("Flush House", scoring)
        return ("Full House", scoring)

    if is_flush:
        return ("Flush", list(range(n)))

    if is_straight:
        return ("Straight", list(range(n)))

    if rc[0][1] == 3:
        trip_rank = rc[0][0]
        idxs = [i for i, c in enumerate(cards) if c.rank_num == trip_rank][:3]
        return ("Three of a Kind", idxs)

    if len(rc) >= 2 and rc[0][1] == 2 and rc[1][1] == 2:
        p1, p2 = rc[0][0], rc[1][0]
        idxs = [i for i, c in enumerate(cards) if c.rank_num in (p1, p2)]
        return ("Two Pair", idxs[:4])

    if rc[0][1] == 2:
        pair_rank = rc[0][0]
        idxs = [i for i, c in enumerate(cards) if c.rank_num == pair_rank][:2]
        return ("Pair", idxs)

    best_idx = max(range(n), key=lambda i: cards[i].rank_num)
    return ("High Card", [best_idx])


# ============================================================
# Sequential Score Calculation (matches real Balatro pipeline)
# ============================================================

class _ScoringContext:
    """Mutable scoring state passed through the pipeline."""
    __slots__ = ('chips', 'mult', 'hand_type', 'hand_contains',
                 'played_cards', 'scoring_idxs', 'held_cards', 'jokers',
                 'pareidolia', 'has_smeared', 'chance_multiplier',
                 'resolved_jokers', 'joker_extra_state',
                 '_report_add_chips', '_report_add_mult', '_report_x_mult',
                 'hand_levels')

    def __init__(self, base_chips: int, base_mult: int, hand_type: str,
                 played_cards: list[Card], scoring_idxs: list[int],
                 held_cards: list[Card] | None, jokers: list[Joker],
                 hand_levels: HandLevel | None = None):
        self.chips = base_chips
        self.mult = float(base_mult)
        self.hand_type = hand_type
        self.hand_contains = HAND_CONTAINS.get(hand_type, {hand_type})
        self.played_cards = played_cards
        self.scoring_idxs = scoring_idxs
        self.held_cards = held_cards or []
        self.jokers = jokers
        self.hand_levels = hand_levels or HandLevel()
        self.pareidolia = any(j.name == "Pareidolia" for j in jokers)
        self.has_smeared = any(j.name == "Smeared Joker" for j in jokers)
        # Oops! All 6s: doubles all probability-based effects
        self.chance_multiplier = 1
        for j in jokers:
            if j.name == "Oops! All 6s":
                self.chance_multiplier *= 2
        # Blueprint/Brainstorm resolution (computed once, used in per-card + independent)
        self.resolved_jokers = _resolve_blueprint_brainstorm(jokers)
        # Per-joker mutable state for per-card triggers (e.g. Photograph first-face tracking)
        self.joker_extra_state: dict[str, object] = {}
        # For backward-compat reporting
        self._report_add_chips = 0
        self._report_add_mult = 0
        self._report_x_mult = 1.0

    def suit_matches(self, card: Card, target_suit: str) -> bool:
        """Check if card matches target suit, accounting for Smeared Joker and Wild Card.

        EFHIII logic:
        - Wild Card (enhancement): matches ALL suits → card[SUIT] === true
        - Smeared Joker: Hearts=Diamonds (red), Clubs=Spades (black)
        """
        if card.enhancement == "Wild Card":
            return True
        if card.suit == target_suit:
            return True
        if self.has_smeared:
            RED = {"Hearts", "Diamonds"}
            BLACK = {"Clubs", "Spades"}
            if target_suit in RED and card.suit in RED:
                return True
            if target_suit in BLACK and card.suit in BLACK:
                return True
        return False

    def add_chips(self, n: int | float):
        self.chips += n
        self._report_add_chips += n

    def add_mult(self, n: int | float):
        self.mult += n
        self._report_add_mult += n

    def x_mult(self, n: float):
        self.mult *= n
        self._report_x_mult *= n


def _trigger_card_scored(ctx: _ScoringContext, card: Card):
    """Process a single scoring card trigger (chips + enhancement + edition + per-card jokers)."""
    # Debuffed cards contribute nothing (boss blind effect)
    if card.debuffed:
        return
    # --- Card chip value ---
    if card.enhancement == "Stone Card":
        ctx.add_chips(50)
    else:
        ctx.add_chips(card.chip_value)
        # Bonus Card enhancement
        if card.enhancement == "Bonus Card":
            ctx.add_chips(30)

    # --- Card enhancement mult/xMult ---
    if card.enhancement == "Mult Card":
        ctx.add_mult(4)
    elif card.enhancement == "Glass Card":
        ctx.x_mult(2.0)
    elif card.enhancement == "Lucky Card":
        # EFHIII: 1/5 chance for +20 mult. Oops! All 6s doubles probability.
        # Best-case mode: always triggers. Otherwise use expected value.
        chance = min(1.0, 0.2 * ctx.chance_multiplier)
        ctx.add_mult(20 * chance)  # E[mult] = 20 * chance

    # --- Card edition ---
    if card.edition == "Foil":
        ctx.add_chips(50)
    elif card.edition == "Holographic":
        ctx.add_mult(10)
    elif card.edition == "Polychrome":
        ctx.x_mult(1.5)

    # --- Per-card joker triggers (left to right) ---
    for ji, j in enumerate(ctx.jokers):
        target = ctx.resolved_jokers[ji] if ctx.resolved_jokers[ji] is not None else j
        _joker_on_card_scored(ctx, target, card)


def _joker_on_card_scored(ctx: _ScoringContext, joker: Joker, card: Card):
    """Joker effects that trigger per scoring card (suit/rank bonuses).

    EFHIII reference: triggerCard per-card joker section.
    All suit jokers support Smeared Joker + Wild Card via ctx.suit_matches().
    """
    name = joker.name
    is_face = card.is_face or ctx.pareidolia

    # --- Suit-based mult jokers (+3 mult) ---
    # EFHIII: checks card[SUIT] === TARGET || (SmearedJoker && card[SUIT] === PARTNER) || card[SUIT] === true (Wild)
    if name == "Greedy Joker" and ctx.suit_matches(card, "Diamonds"):
        ctx.add_mult(3)
    elif name == "Lusty Joker" and ctx.suit_matches(card, "Hearts"):
        ctx.add_mult(3)
    elif name == "Wrathful Joker" and ctx.suit_matches(card, "Spades"):
        ctx.add_mult(3)
    elif name == "Gluttonous Joker" and ctx.suit_matches(card, "Clubs"):
        ctx.add_mult(3)

    # --- Suit-based chip jokers ---
    # EFHIII: Arrowhead — Spades (or Clubs with Smeared, or Wild) → +50 chips
    elif name == "Arrowhead" and ctx.suit_matches(card, "Spades"):
        ctx.add_chips(50)

    # --- Suit-based mult (uncommon) ---
    # EFHIII: Onyx Agate — Clubs (or Spades with Smeared, or Wild) → +7 mult
    elif name == "Onyx Agate" and ctx.suit_matches(card, "Clubs"):
        ctx.add_mult(7)

    # --- Bloodstone: Hearts → 1 in 2 chance x1.5 mult ---
    # EFHIII: Hearts (or Diamonds with Smeared, or Wild) → x1.5 (probability-based)
    elif name == "Bloodstone" and ctx.suit_matches(card, "Hearts"):
        chance = min(1.0, 0.5 * ctx.chance_multiplier)
        ctx.x_mult(1.0 + 0.5 * chance)  # E[x] = chance*1.5 + (1-chance)*1.0

    # Rough Gem: Diamonds → +$1 (economy, no scoring effect)

    # --- Face card jokers ---
    # EFHIII: Scary Face — isFace → +30 chips
    elif name == "Scary Face" and is_face:
        ctx.add_chips(30)
    # EFHIII: Smiley Face — isFace → +5 mult
    elif name == "Smiley Face" and is_face:
        ctx.add_mult(5)

    # --- Rank-based jokers ---
    # EFHIII: Fibonacci — Ace, 2, 3, 5, 8 → +8 mult
    elif name == "Fibonacci" and card.rank in ("Ace", "2", "3", "5", "8"):
        ctx.add_mult(8)
    # EFHIII: Even Steven — even ranks 2,4,6,8,10 → +4 mult
    elif name == "Even Steven" and card.rank in ("2", "4", "6", "8", "10"):
        ctx.add_mult(4)
    # EFHIII: Odd Todd — odd ranks 3,5,7,9,Ace → +31 chips
    elif name == "Odd Todd" and card.rank in ("3", "5", "7", "9", "Ace"):
        ctx.add_chips(31)
    # EFHIII: Scholar — Ace → +20 chips, +4 mult
    elif name == "Scholar" and card.rank == "Ace":
        ctx.add_chips(20)
        ctx.add_mult(4)
    # EFHIII: Walkie Talkie — 4 or 10 → +10 chips, +4 mult
    elif name == "Walkie Talkie" and card.rank in ("10", "4"):
        ctx.add_chips(10)
        ctx.add_mult(4)

    # --- Triboulet: King or Queen → x2 mult ---
    elif name == "Triboulet" and card.rank in ("King", "Queen"):
        ctx.x_mult(2.0)

    # --- Photograph: FIRST face card only → x2 mult ---
    # EFHIII: jokersExtraValue[j] tracks which card was first; only triggers once
    elif name == "Photograph" and is_face:
        photo_key = f"photograph_{id(joker)}"
        if photo_key not in ctx.joker_extra_state:
            ctx.joker_extra_state[photo_key] = True
            ctx.x_mult(2.0)

    # --- Ancient Joker: matching suit (changes each round) → x1.5 mult ---
    # EFHIII: card[SUIT] === joker[VALUE] % 4 (or Wild, or Smeared partner)
    elif name == "Ancient Joker":
        # joker.extra stores the current suit index (0-3) or suit name
        val = joker.get_extra("value", None)
        if val is not None:
            # Map suit index to name if needed
            suit_map = {0: "Spades", 1: "Hearts", 2: "Clubs", 3: "Diamonds"}
            if isinstance(val, (int, float)):
                target = suit_map.get(int(abs(val)) % 4, "Hearts")
            else:
                target = str(val) if str(val) in suit_map.values() else "Hearts"
            if ctx.suit_matches(card, target):
                ctx.x_mult(1.5)

    # --- The Idol: specific rank+suit combo → x2 mult ---
    # EFHIII: card[SUIT] === joker[VALUE] % 4 && card[RANK] === floor(joker[VALUE]/4) % 13
    elif name == "The Idol":
        val = joker.get_extra("value", None)
        if val is not None and isinstance(val, (int, float)):
            suit_map = {0: "Spades", 1: "Hearts", 2: "Clubs", 3: "Diamonds"}
            rank_map = {0: "2", 1: "3", 2: "4", 3: "5", 4: "6", 5: "7",
                        6: "8", 7: "9", 8: "10", 9: "Jack", 10: "Queen",
                        11: "King", 12: "Ace"}
            target_suit = suit_map.get(int(abs(val)) % 4, "Hearts")
            target_rank = rank_map.get(int(abs(val) / 4) % 13, "Ace")
            if card.rank == target_rank and ctx.suit_matches(card, target_suit):
                ctx.x_mult(2.0)

    # --- Wee Joker: rank 2 → +8 chips (per-card trigger) ---
    elif name == "Wee Joker" and card.rank == "2":
        ctx.add_chips(8)

    # --- Hiker: +5 permanent chips per scored card ---
    # EFHIII: card[EXTRA_EXTRA_CHIPS] += 5 (both notStone and isFace branches)
    elif name == "Hiker":
        ctx.add_chips(5)


def _trigger_held_card_inner(ctx: _ScoringContext, card: Card):
    """Inner held-in-hand trigger (called once normally, again on retrigger).

    EFHIII triggerCardInHand logic:
    - Steel Card: x1.5 mult (both plusMult and timesMult)
    - Raised Fist: +2*chip_value of lowest held card (only for THE lowest card)
    - Shoot the Moon: +13 mult per Queen (not Stone)
    - Baron: x1.5 mult per King (not Stone)
    - No card edition effects on held cards (editions only trigger on scored cards)
    """
    if card.debuffed:
        return

    # Steel Card enhancement
    if card.enhancement == "Steel Card":
        ctx.x_mult(1.5)

    # Per-card held-in-hand joker effects (use resolved jokers for Blueprint/Brainstorm)
    for ji, j in enumerate(ctx.jokers):
        target = ctx.resolved_jokers[ji] if ctx.resolved_jokers[ji] is not None else j
        jname = target.name
        if jname == "Raised Fist":
            # EFHIII: only triggers for the specific lowest-rank card (compiledValues[j])
            # We store the lowest card reference in joker_extra_state
            rf_key = f"raised_fist_card_{id(j)}"
            lowest_card = ctx.joker_extra_state.get(rf_key)
            if lowest_card is card and card.enhancement != "Stone Card":
                ctx.add_mult(2 * card.chip_value)
        elif jname == "Baron" and card.rank == "King" and card.enhancement != "Stone Card":
            ctx.x_mult(1.5)
        elif jname == "Shoot the Moon" and card.rank == "Queen" and card.enhancement != "Stone Card":
            ctx.add_mult(13)


def _trigger_held_card(ctx: _ScoringContext, card: Card):
    """Process a held-in-hand card with retrigger support.

    EFHIII retrigger order:
    1. Base trigger (triggerCardInHand)
    2. Red Seal → retrigger once
    3. Mime (case 14) → retrigger once per Mime joker
    """
    if card.debuffed:
        return

    _trigger_held_card_inner(ctx, card)

    # Retriggers (only on first call, not recursive)
    # Red Seal retrigger
    if card.seal == "Red Seal":
        _trigger_held_card_inner(ctx, card)

    # Mime retrigger (EFHIII case 14: retrigger each held card once)
    # Also check resolved jokers (Blueprint/Brainstorm could copy Mime)
    for ji, j in enumerate(ctx.jokers):
        target = ctx.resolved_jokers[ji] if ctx.resolved_jokers[ji] is not None else j
        if target.name == "Mime":
            _trigger_held_card_inner(ctx, card)


def _trigger_joker_independent(ctx: _ScoringContext, joker: Joker):
    """Joker's independent scoring effect (not per-card). Applied left to right."""
    name = joker.name
    hand = ctx.hand_type
    contains = ctx.hand_contains
    played = ctx.played_cards
    scoring = ctx.scoring_idxs
    held = ctx.held_cards
    all_jokers = ctx.jokers

    # --- Flat mult jokers ---
    if name == "Joker":
        ctx.add_mult(4)

    elif name == "Jolly Joker":
        if "Pair" in contains:
            ctx.add_mult(8)
    elif name == "Zany Joker":
        if "Three of a Kind" in contains:
            ctx.add_mult(12)
    elif name == "Mad Joker":
        if "Two Pair" in contains:
            ctx.add_mult(10)
    elif name == "Crazy Joker":
        if "Straight" in contains:
            ctx.add_mult(12)
    elif name == "Droll Joker":
        if "Flush" in contains:
            ctx.add_mult(10)

    elif name == "Half Joker":
        if len(played) <= 3:
            ctx.add_mult(20)

    elif name == "Misprint":
        ctx.add_mult(12)  # avg of 0-23 (random)

    elif name == "Mystic Summit":
        # EFHIII: +15 mult if 0 discards remaining (joker[VALUE] !== 0 means condition met)
        val = joker.get_extra("value", 0)
        if val != 0:
            ctx.add_mult(15)
        # If val == 0, condition not met (has discards remaining), no effect

    elif name == "Green Joker":
        # Balatro source: mult_mod = self.ability.mult (cumulative, +1 per hand, -1 per discard)
        val = joker.mult
        if val and val > 0:
            ctx.add_mult(val)

    elif name == "Red Card":
        # Balatro source: mult_mod = self.ability.mult (cumulative, +extra per booster skipped)
        val = joker.mult
        if val and val > 0:
            ctx.add_mult(val)

    elif name == "Supernova":
        # Balatro source: mult_mod = G.GAME.hands[scoring_name].played
        # Number of times this hand type has been played this run
        played_count = ctx.hand_levels.played_counts.get(ctx.hand_type, 0)
        if played_count > 0:
            ctx.add_mult(played_count)

    elif name == "Ride the Bus":
        # Balatro source: mult_mod = self.ability.mult (cumulative, resets on face card)
        val = joker.mult
        if val and val > 0:
            ctx.add_mult(val)

    elif name == "Swashbuckler":
        # Balatro source: mult_mod = self.ability.mult (cumulative, = sum of sell values of other jokers)
        val = joker.mult
        if val and val > 0:
            ctx.add_mult(val)
            ctx.add_mult(val)
        else:
            total_sell = sum(j.sell_value for j in all_jokers if j.name != "Swashbuckler")
            ctx.add_mult(max(total_sell, 1))

    elif name == "Abstract Joker":
        ctx.add_mult(3 * len(all_jokers))

    # --- Flat chip jokers ---
    elif name == "Blue Joker":
        # EFHIII: compiledChips += 104 + 2 * joker[VALUE]
        # VALUE tracks deck size changes; game state extra = remaining cards in deck
        val = joker.get_extra("value", 0) or joker.t_chips
        if val:
            ctx.add_chips(2 * val)
        else:
            # Fallback: assume ~30 cards remaining
            ctx.add_chips(60)

    elif name == "Banner":
        # EFHIII: compiledChips += joker[VALUE] * 30 — VALUE = discards remaining
        val = joker.get_extra("value", 0) or joker.t_chips
        ctx.add_chips(val * 30)

    elif name == "Sly Joker":
        if "Pair" in contains:
            ctx.add_chips(50)
    elif name == "Wily Joker":
        if "Three of a Kind" in contains:
            ctx.add_chips(100)
    elif name == "Clever Joker":
        # EFHIII: hasTwoPair && !hasFourOfAKind
        if "Two Pair" in contains and "Four of a Kind" not in contains:
            ctx.add_chips(80)
    elif name == "Devious Joker":
        if "Straight" in contains:
            ctx.add_chips(100)
    elif name == "Crafty Joker":
        if "Flush" in contains:
            ctx.add_chips(80)

    elif name == "Stuntman":
        ctx.add_chips(250)

    elif name == "Raised Fist":
        # EFHIII: held-in-hand effect, NOT independent. Handled in _trigger_held_card_inner.
        # Pre-computation of lowest card is done before Phase 2 in calculate_score.
        pass

    # --- xMult jokers ---
    elif name == "The Duo":
        if "Pair" in contains:
            ctx.x_mult(2.0)
    elif name == "The Trio":
        if "Three of a Kind" in contains:
            ctx.x_mult(3.0)
    elif name == "The Family":
        if "Four of a Kind" in contains:
            ctx.x_mult(4.0)
    elif name == "The Order":
        if "Straight" in contains:
            ctx.x_mult(3.0)
    elif name == "The Tribe":
        if "Flush" in contains:
            ctx.x_mult(2.0)

    elif name == "Stencil Joker" or name == "Joker Stencil":
        # EFHIII: bigTimes(1 + joker[VALUE], this.mult) — VALUE = empty joker slots
        empty = max(0, 5 - len(all_jokers))
        if empty > 0:
            ctx.x_mult(1.0 + empty)

    elif name == "Loyalty Card":
        # EFHIII: x4 if joker[VALUE] === 0 (every 6th hand)
        val = joker.get_extra("value", 0)
        if val == 0:
            ctx.x_mult(4.0)

    elif name == "Acrobat":
        # EFHIII: x3 if joker[VALUE] !== 0 (last hand of round)
        val = joker.get_extra("value", 0)
        if val != 0:
            ctx.x_mult(3.0)

    elif name == "Blackboard":
        if held and all(c.suit in ("Spades", "Clubs") for c in held):
            ctx.x_mult(3.0)

    elif name == "Steel Joker":
        if held:
            steel_count = sum(1 for c in held if c.enhancement == "Steel Card")
            if steel_count:
                ctx.x_mult(1.0 + 0.2 * steel_count)

    elif name == "Hiker":
        # EFHIII: per-card trigger adds +4 permanent chips to each scored card
        # In independent section, we estimate based on accumulated extra chips
        # The actual per-card effect is handled in _joker_on_card_scored
        pass  # Hiker's effect is per-card, not independent

    # ============================================================
    # NEW: Missing jokers from EFHIII calculator (47 jokers)
    # ============================================================

    # --- Scaling mult jokers (use joker.extra for runtime state) ---
    elif name == "Fortune Teller":
        # EFHIII: bigAdd(joker[VALUE], this.mult) — VALUE = tarot cards used
        val = joker.get_extra("value", 0) or joker.mult
        ctx.add_mult(val)

    elif name == "Spare Trousers":
        # Balatro source: mult_mod = self.ability.mult (cumulative, +extra per Two Pair/Full House)
        # Lua exports ability.mult as joker.mult
        val = joker.mult
        if val and val > 0:
            ctx.add_mult(val)

    elif name == "Flash Card":
        # Balatro source: mult_mod = self.ability.mult (cumulative, +extra per reroll)
        val = joker.mult
        if val and val > 0:
            ctx.add_mult(val)

    elif name == "Ceremonial Dagger":
        # Balatro source: mult_mod = self.ability.mult (cumulative, +mult per boss defeated)
        val = joker.mult
        if val and val > 0:
            ctx.add_mult(val)

    elif name == "Erosion":
        # EFHIII: bigAdd(joker[VALUE] * 4, this.mult) — VALUE = cards below 52
        val = joker.get_extra("value", 0) or joker.mult
        ctx.add_mult(val * 4)

    elif name == "Bootstraps":
        # EFHIII: bigAdd(joker[VALUE] * 2, this.mult) — VALUE = floor(dollars/5)
        val = joker.get_extra("value", 0) or joker.mult
        ctx.add_mult(val * 2)

    elif name == "Gros Michel":
        ctx.add_mult(15)

    elif name == "Cavendish":
        # EFHIII: bigTimes(3, this.mult) — x3 mult
        ctx.x_mult(3.0)

    elif name == "Popcorn":
        # Balatro source: mult_mod = self.ability.mult (starts at 20, -5 per round played)
        val = joker.mult
        if val and val > 0:
            ctx.add_mult(val)

    elif name == "Ice Cream":
        # EFHIII: this.chips += 100 - joker[VALUE] * 5 — VALUE = hands played
        val = joker.get_extra("chips", 0) or joker.t_chips
        if isinstance(val, (int, float)) and val > 20:
            # val is already the current chips value
            ctx.add_chips(max(val, 0))
        else:
            # val is hands elapsed
            ctx.add_chips(max(100 - int(val) * 5, 0))

    elif name == "Runner":
        # EFHIII: if hasStraight: chips += 15*(VALUE+1), else: chips += 15*VALUE
        val = joker.get_extra("chips", 0) or joker.t_chips
        if "Straight" in contains:
            ctx.add_chips(15 * (val + 1))
        else:
            ctx.add_chips(15 * val)

    elif name == "Castle":
        # EFHIII: this.compiledChips += joker[VALUE] * 3 — VALUE = cards discarded of suit
        val = joker.get_extra("chips", 0) or joker.t_chips
        ctx.add_chips(val * 3)

    elif name == "Stone Joker":
        # EFHIII: this.compiledChips += joker[VALUE] * 25 — VALUE = stone cards in deck
        val = joker.get_extra("value", 0) or joker.t_chips
        ctx.add_chips(val * 25)

    elif name == "Square Joker":
        # EFHIII: if len==4: chips += 4*(VALUE+1), else: chips += 4*VALUE
        val = joker.get_extra("chips", 0) or joker.t_chips
        if len(played) == 4:
            ctx.add_chips(4 * (val + 1))
        else:
            ctx.add_chips(4 * val)

    elif name == "Wee Joker":
        # EFHIII compiled: compiledChips += joker[VALUE] * 8
        # Per-card trigger in _joker_on_card_scored adds +8 per 2 scored this hand
        # Independent section adds accumulated chips from previous hands
        # game state extra.chips = accumulated value (already count * 8)
        val = joker.get_extra("chips", 0) or joker.t_chips
        ctx.add_chips(val)

    elif name == "Bull":
        # EFHIII: this.chips += 2 * joker[VALUE] — VALUE = dollars held
        val = joker.get_extra("value", 0) or joker.t_chips
        ctx.add_chips(2 * val)

    # --- Scaling xMult jokers ---
    elif name == "Hologram":
        # xMult that grows (+0.25 per card added to deck)
        # Game stores final multiplier in ability.x_mult directly
        x = joker.x_mult if joker.x_mult > 1.0 else 1.0
        if x > 1.0:
            ctx.x_mult(x)

    elif name == "Campfire":
        # xMult that grows (+0.25 per card sold)
        x = joker.x_mult if joker.x_mult > 1.0 else 1.0
        if x > 1.0:
            ctx.x_mult(x)

    elif name == "Constellation":
        # xMult that grows (+0.1 per Planet used)
        val = joker.get_extra("value", 0) or joker.x_mult
        x = 1.0 + val * 0.1 if isinstance(val, (int, float)) and val < 20 else val
        if x and x > 1.0:
            ctx.x_mult(x)

    elif name == "Madness":
        # xMult that grows (+0.5 per blind selected)
        val = joker.get_extra("value", 0) or joker.x_mult
        x = 1.0 + val * 0.5 if isinstance(val, (int, float)) and val < 10 else val
        if x and x > 1.0:
            ctx.x_mult(x)

    elif name == "Glass Joker":
        # xMult that grows (+0.75 per Glass card destroyed)
        x = joker.x_mult if joker.x_mult > 1.0 else 1.0
        if x > 1.0:
            ctx.x_mult(x)

    elif name == "Vampire":
        # xMult that grows from consuming enhancements
        val = joker.get_extra("value", 0) or joker.x_mult
        x = 1.0 + val * 0.1 if isinstance(val, (int, float)) and val < 20 else val
        if x and x > 1.0:
            ctx.x_mult(x)

    elif name == "Obelisk":
        # xMult from consecutive non-most-played hands
        x = joker.x_mult if joker.x_mult > 1.0 else 1.0
        if x > 1.0:
            ctx.x_mult(x)

    elif name == "Lucky Cat":
        # xMult that grows per Lucky card trigger
        x = joker.x_mult if joker.x_mult > 1.0 else 1.0
        if x > 1.0:
            ctx.x_mult(x)

    elif name == "Canio":
        # xMult that grows (+1 per face card destroyed)
        val = joker.get_extra("value", 0) or joker.x_mult
        x = 1.0 + val if isinstance(val, (int, float)) and val < 20 else val
        if x and x > 1.0:
            ctx.x_mult(x)

    elif name == "Throwback":
        # xMult from blinds skipped
        val = joker.get_extra("value", 0) or joker.x_mult
        x = 1.0 + val * 0.25 if isinstance(val, (int, float)) and val < 20 else val
        if x and x > 1.0:
            ctx.x_mult(x)

    elif name == "Hit the Road":
        # xMult from Jacks discarded this round
        val = joker.get_extra("value", 0) or joker.x_mult
        x = 1.0 + val * 0.5 if isinstance(val, (int, float)) and val < 10 else val
        if x and x > 1.0:
            ctx.x_mult(x)

    elif name == "Ramen":
        # xMult (decreasing per discard)
        val = joker.get_extra("value", 0) or joker.x_mult
        x = 2.0 - val * 0.01 if isinstance(val, (int, float)) and val < 100 else val
        if x and x > 1.0:
            ctx.x_mult(x)

    elif name == "Yorick":
        # xMult after discarding enough cards
        val = joker.get_extra("value", 0) or joker.x_mult
        if val and val > 1.0:
            ctx.x_mult(val)

    # --- Conditional xMult jokers ---
    elif name == "Card Sharp":
        # EFHIII: x3 if this.hands[typeOfHand][PLAYED_THIS_ROUND] is true
        val = joker.get_extra("value", 0)
        if val:
            ctx.x_mult(3.0)

    elif name == "Seeing Double":
        # x2 if hand has scoring Club + scoring card of another suit
        suits = set()
        for i in scoring:
            suits.add(played[i].suit)
        if "Clubs" in suits and len(suits) >= 2:
            ctx.x_mult(2.0)

    elif name == "Flower Pot":
        # x3 if hand has Diamond+Club+Heart+Spade scoring cards
        suits = set()
        for i in scoring:
            suits.add(played[i].suit)
        if len(suits) >= 4:
            ctx.x_mult(3.0)

    elif name == "The Idol":
        # Per-card trigger only (handled in _joker_on_card_scored)
        # No independent scoring effect
        pass

    elif name == "Ancient Joker":
        # Per-card trigger only (handled in _joker_on_card_scored)
        # No independent scoring effect
        pass

    elif name == "Driver's License":
        # x3 if 16+ enhanced cards in deck
        val = joker.get_extra("value", 0)
        if val and val >= 16:
            ctx.x_mult(3.0)

    # --- Joker edition (applied after joker's own effect) ---
    # This is handled in calculate_score after calling this function


def _resolve_blueprint_brainstorm(jokers: list[Joker]) -> list[Joker | None]:
    """Resolve Blueprint/Brainstorm copy chains.

    EFHIII logic:
    - Blueprint (case 30): copies joker to the right, following chains
    - Brainstorm (case 77): copies leftmost joker, following chains
    - Both resolve chains: Blueprint→Blueprint→actual, Brainstorm→Blueprint→actual

    Returns a list parallel to jokers. None = use original, Joker = use this instead.
    """
    n = len(jokers)
    resolved: list[Joker | None] = [None] * n

    for ji, j in enumerate(jokers):
        if j.name not in ("Blueprint", "Brainstorm"):
            continue

        # Find the target joker by following the chain
        if j.name == "Blueprint":
            # Start from joker to the right
            if ji + 1 >= n:
                continue  # No joker to the right
            at = ji + 1
        else:
            # Brainstorm: start from leftmost (index 0)
            if ji == 0:
                continue  # Brainstorm IS the leftmost
            if jokers[0].name == "Brainstorm":
                continue  # Leftmost is also Brainstorm, no resolution
            at = 0

        # Follow Blueprint/Brainstorm chains (max n iterations to prevent infinite loops)
        for _ in range(n):
            if jokers[at].name == "Blueprint":
                if at + 1 < n:
                    at += 1
                else:
                    break
            elif jokers[at].name == "Brainstorm":
                if at != 0 and jokers[0].name != "Brainstorm":
                    at = 0
                else:
                    break
            else:
                # Found a real joker
                resolved[ji] = jokers[at]
                break

    return resolved


def calculate_score(
    played_cards: list[Card],
    jokers: list[Joker],
    hand_levels: HandLevel | None = None,
    held_cards: list[Card] | None = None,
) -> ScoreBreakdown:
    """Calculate the score for a played hand with full Balatro mechanics.

    Uses sequential mult accumulation matching real Balatro:
    - Chips accumulate additively
    - Mult accumulates sequentially (add_mult and x_mult interleave by trigger order)
    - Joker order matters

    Args:
        played_cards: Cards being played
        jokers: Active jokers
        hand_levels: Planet card upgrade levels
        held_cards: Cards remaining in hand (for held-card joker effects)

    Returns:
        ScoreBreakdown with full detail
    """
    if hand_levels is None:
        hand_levels = HandLevel()

    hand_type, scoring_idxs = classify_hand(played_cards, jokers)

    # Splash: all played cards count as scoring (EFHIII: involvedCards = cards)
    if any(j.name == "Splash" for j in jokers):
        scoring_idxs = list(range(len(played_cards)))

    base_chips, base_mult = hand_levels.get_base(hand_type)
    hand_rank = HAND_BASE.get(hand_type, (5, 1, 1))[2]

    ctx = _ScoringContext(
        base_chips=base_chips,
        base_mult=base_mult,
        hand_type=hand_type,
        played_cards=played_cards,
        scoring_idxs=scoring_idxs,
        held_cards=held_cards,
        jokers=jokers,
        hand_levels=hand_levels,
    )

    # DNA: if exactly 1 card played, add a copy to held cards
    # EFHIII: if(this.cards.length === 1) { this.cardsInHand.push(this.cards[0]); }
    if len(played_cards) == 1 and any(j.name == "DNA" for j in jokers):
        ctx.held_cards = list(ctx.held_cards) + [played_cards[0]]

    # Phase 1: Score each scoring card (left to right)
    first_scored = True
    pareidolia = any(j.name == "Pareidolia" for j in jokers)
    for idx in scoring_idxs:
        card = played_cards[idx]
        _trigger_card_scored(ctx, card)

        # Red Seal retrigger: re-trigger the entire card scoring
        if card.seal == "Red Seal":
            _trigger_card_scored(ctx, card)

        # Retrigger jokers (per-card)
        is_face = card.is_face or pareidolia
        for j in jokers:
            jn = j.name
            if jn == "Hack" and card.rank_num <= 5:
                _trigger_card_scored(ctx, card)
            elif jn == "Hanging Chad" and first_scored:
                _trigger_card_scored(ctx, card)
                _trigger_card_scored(ctx, card)
            elif jn == "Sock and Buskin" and is_face:
                _trigger_card_scored(ctx, card)
            elif jn == "Seltzer":
                _trigger_card_scored(ctx, card)
            elif jn == "Dusk":
                # EFHIII: retrigger if joker[VALUE] !== 0 (final hand of round)
                val = j.get_extra("value", 0)
                if val != 0:
                    _trigger_card_scored(ctx, card)

        first_scored = False

    # Pre-compute Raised Fist: find lowest rank held card (not Stone) for each Raised Fist joker
    # EFHIII compileCards case 28: compiledValues[j] = lowest rank card in hand
    for j in jokers:
        if j.name == "Raised Fist" and ctx.held_cards:
            eligible = [c for c in ctx.held_cards if c.enhancement != "Stone Card"]
            if eligible:
                # EFHIII: if multiple same-rank, uses the last one
                lowest_rank = min(c.rank_num for c in eligible)
                lowest_card = [c for c in eligible if c.rank_num == lowest_rank][-1]
                ctx.joker_extra_state[f"raised_fist_card_{id(j)}"] = lowest_card

    # Phase 2: Held-in-hand card effects
    # EFHIII: triggerCardInHand handles retriggers internally (Red Seal + Mime)
    for card in ctx.held_cards:
        _trigger_held_card(ctx, card)

    # Phase 3: Independent joker effects (left to right, ORDER MATTERS)
    # Blueprint/Brainstorm already resolved in ctx.resolved_jokers
    # Count Baseball Cards for per-joker uncommon bonus
    baseball_count = sum(1 for j in jokers if j.name == "Baseball Card")
    for ji, j in enumerate(jokers):
        target = ctx.resolved_jokers[ji]
        if target is not None:
            _trigger_joker_independent(ctx, target)
        else:
            _trigger_joker_independent(ctx, j)

        # Baseball Card: x1.5 per Baseball Card, applied after EACH Uncommon joker's trigger
        # EFHIII: if(this.BaseballCard && jokerRarities[j] === 2) { mult *= 1.5^BaseballCard }
        if baseball_count > 0 and j.rarity in ("2", 2, "Uncommon"):
            for _ in range(baseball_count):
                ctx.x_mult(1.5)

        # Joker edition effects (applied after joker's own effect)
        if j.edition == "Foil":
            ctx.add_chips(50)
        elif j.edition == "Holographic":
            ctx.add_mult(10)
        elif j.edition == "Polychrome":
            ctx.x_mult(1.5)

    # Final score
    final_score = ctx.chips * ctx.mult

    # Card chips = total chips added by cards (not base)
    card_chips = sum(
        (50 if played_cards[i].enhancement == "Stone Card"
         else played_cards[i].chip_value + (30 if played_cards[i].enhancement == "Bonus Card" else 0))
        for i in scoring_idxs
    )

    return ScoreBreakdown(
        hand_type=hand_type,
        hand_rank=hand_rank,
        base_chips=base_chips,
        base_mult=base_mult,
        card_chips=card_chips,
        add_chips=int(ctx._report_add_chips),
        add_mult=int(ctx._report_add_mult),
        x_mult=ctx._report_x_mult,
        final_score=final_score,
        scoring_cards=scoring_idxs,
        all_cards=list(range(len(played_cards))),
    )


# ============================================================
# Boss Blind Debuff Handling
# ============================================================

def _apply_boss_debuffs(cards: list[Card], boss_blind: str):
    """Mark cards as debuffed based on boss blind effect.

    In Balatro, debuffed cards don't contribute chips, mult, or trigger effects.
    """
    for card in cards:
        card.debuffed = False  # reset first

    if boss_blind == "The Plant":
        # Face cards are debuffed
        for card in cards:
            if card.is_face:
                card.debuffed = True
    elif boss_blind == "The Verdant":
        for card in cards:
            if card.suit == "Clubs":
                card.debuffed = True
    elif boss_blind == "The Crimson":
        for card in cards:
            if card.suit == "Hearts":
                card.debuffed = True
    elif boss_blind == "The Violet":
        for card in cards:
            if card.suit == "Spades":
                card.debuffed = True
    elif boss_blind == "The Amber":
        for card in cards:
            if card.suit == "Diamonds":
                card.debuffed = True
    elif boss_blind == "The Flint":
        # Base chips and mult are halved (handled in calculate_score, not per-card)
        pass
    elif boss_blind == "The Window":
        # Diamond cards are debuffed
        for card in cards:
            if card.suit == "Diamonds":
                card.debuffed = True
    elif boss_blind == "The Club":
        # Club cards are debuffed
        for card in cards:
            if card.suit == "Clubs":
                card.debuffed = True
    elif boss_blind == "The Goad":
        # Spade cards are debuffed
        for card in cards:
            if card.suit == "Spades":
                card.debuffed = True
    elif boss_blind == "The Head":
        # Heart cards are debuffed
        for card in cards:
            if card.suit == "Hearts":
                card.debuffed = True


# ============================================================
# Hand Finder — find the best hand from a set of cards
# ============================================================

def find_best_hands(
    hand_cards: list[Card],
    jokers: list[Joker],
    hand_levels: HandLevel | None = None,
    held_cards_fn=None,
    max_size: int = 5,
    top_n: int = 3,
    boss_blind: str = "",
) -> list[ScoreBreakdown]:
    """Find the top N scoring hands from available cards.

    Args:
        hand_cards: Cards in hand
        jokers: Active jokers
        hand_levels: Planet upgrade levels
        held_cards_fn: Optional callable(played_indices) -> held_cards
        max_size: Max cards per hand (usually 5)
        top_n: Number of top hands to return
        boss_blind: Boss blind name for debuff awareness

    Returns:
        List of ScoreBreakdown sorted by final_score descending
    """
    if hand_levels is None:
        hand_levels = HandLevel()

    # Mark debuffed cards based on boss blind
    if boss_blind:
        _apply_boss_debuffs(hand_cards, boss_blind)

    results: list[ScoreBreakdown] = []

    for n in range(min(max_size, len(hand_cards)), 0, -1):
        for combo in combinations(range(len(hand_cards)), n):
            played = [hand_cards[i] for i in combo]
            held = None
            if held_cards_fn:
                held = held_cards_fn(set(combo))
            else:
                held = [hand_cards[i] for i in range(len(hand_cards)) if i not in combo]

            breakdown = calculate_score(played, jokers, hand_levels, held)
            # Map scoring_cards back to original hand indices
            breakdown.all_cards = list(combo)
            breakdown.scoring_cards = [combo[i] for i in breakdown.scoring_cards]
            results.append(breakdown)

    results.sort(key=lambda b: b.final_score, reverse=True)
    return results[:top_n]
