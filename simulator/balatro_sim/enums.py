"""Enumerations and constants for Balatro simulator."""

from __future__ import annotations
from enum import Enum, IntEnum


class Suit(str, Enum):
    SPADES = "Spades"
    HEARTS = "Hearts"
    CLUBS = "Clubs"
    DIAMONDS = "Diamonds"


class Rank(IntEnum):
    """Card ranks with numeric values for comparison. Ace = 14."""
    TWO = 2
    THREE = 3
    FOUR = 4
    FIVE = 5
    SIX = 6
    SEVEN = 7
    EIGHT = 8
    NINE = 9
    TEN = 10
    JACK = 11
    QUEEN = 12
    KING = 13
    ACE = 14

    @property
    def chip_value(self) -> int:
        """Chip value of this rank when scored."""
        if self.value <= 10:
            return self.value
        if self.value in (11, 12, 13):  # J, Q, K
            return 10
        return 11  # Ace

    @property
    def display(self) -> str:
        _map = {11: "J", 12: "Q", 13: "K", 14: "A"}
        return _map.get(self.value, str(self.value))

    @property
    def is_face(self) -> bool:
        return self.value in (11, 12, 13)


class Edition(str, Enum):
    NONE = ""
    FOIL = "Foil"
    HOLOGRAPHIC = "Holographic"
    POLYCHROME = "Polychrome"
    NEGATIVE = "Negative"


class Enhancement(str, Enum):
    NONE = ""
    BONUS = "Bonus"
    MULT = "Mult"
    WILD = "Wild"
    GLASS = "Glass"
    STEEL = "Steel"
    STONE = "Stone"
    GOLD = "Gold"
    LUCKY = "Lucky"


class Seal(str, Enum):
    NONE = ""
    GOLD = "Gold"
    RED = "Red"
    BLUE = "Blue"
    PURPLE = "Purple"


class Phase(str, Enum):
    BLIND_SELECT = "blind_select"
    PLAY_HAND = "play_hand"
    SHOP = "shop"
    PACK_OPEN = "pack_open"
    GAME_OVER = "game_over"


class HandType(str, Enum):
    """Poker hand types in Balatro, ordered by rank."""
    HIGH_CARD = "High Card"
    PAIR = "Pair"
    TWO_PAIR = "Two Pair"
    THREE_OF_A_KIND = "Three of a Kind"
    STRAIGHT = "Straight"
    FLUSH = "Flush"
    FULL_HOUSE = "Full House"
    FOUR_OF_A_KIND = "Four of a Kind"
    STRAIGHT_FLUSH = "Straight Flush"
    FIVE_OF_A_KIND = "Five of a Kind"
    FLUSH_HOUSE = "Flush House"
    FLUSH_FIVE = "Flush Five"

    @property
    def rank(self) -> int:
        return _HAND_RANK[self]


# Hand type rank (higher = better)
_HAND_RANK: dict[HandType, int] = {
    HandType.HIGH_CARD: 1,
    HandType.PAIR: 2,
    HandType.TWO_PAIR: 3,
    HandType.THREE_OF_A_KIND: 4,
    HandType.STRAIGHT: 5,
    HandType.FLUSH: 6,
    HandType.FULL_HOUSE: 7,
    HandType.FOUR_OF_A_KIND: 8,
    HandType.STRAIGHT_FLUSH: 9,
    HandType.FIVE_OF_A_KIND: 10,
    HandType.FLUSH_HOUSE: 11,
    HandType.FLUSH_FIVE: 12,
}

# Base chips and mult for each hand type at level 1
HAND_BASE: dict[HandType, tuple[int, int]] = {
    HandType.FLUSH_FIVE:       (160, 16),
    HandType.FLUSH_HOUSE:      (140, 14),
    HandType.FIVE_OF_A_KIND:   (120, 12),
    HandType.STRAIGHT_FLUSH:   (100,  8),
    HandType.FOUR_OF_A_KIND:   ( 60,  7),
    HandType.FULL_HOUSE:       ( 40,  4),
    HandType.FLUSH:            ( 35,  4),
    HandType.STRAIGHT:         ( 30,  4),
    HandType.THREE_OF_A_KIND:  ( 30,  3),
    HandType.TWO_PAIR:         ( 20,  2),
    HandType.PAIR:             ( 10,  2),
    HandType.HIGH_CARD:        (  5,  1),
}

# Planet card level-up bonuses per level: (chips, mult)
PLANET_BONUS: dict[HandType, tuple[int, int]] = {
    HandType.FLUSH_FIVE:       (50, 3),
    HandType.FLUSH_HOUSE:      (40, 4),
    HandType.FIVE_OF_A_KIND:   (35, 3),
    HandType.STRAIGHT_FLUSH:   (40, 4),
    HandType.FOUR_OF_A_KIND:   (30, 3),
    HandType.FULL_HOUSE:       (25, 2),
    HandType.FLUSH:            (15, 2),
    HandType.STRAIGHT:         (30, 3),
    HandType.THREE_OF_A_KIND:  (20, 2),
    HandType.TWO_PAIR:         (20, 2),
    HandType.PAIR:             (15, 1),
    HandType.HIGH_CARD:        (10, 1),
}

# Which sub-hand-types are "contained" in a hand type (for joker triggers)
HAND_CONTAINS: dict[HandType, set[HandType]] = {
    HandType.FLUSH_FIVE:      {HandType.FLUSH_FIVE, HandType.FIVE_OF_A_KIND, HandType.FOUR_OF_A_KIND, HandType.THREE_OF_A_KIND, HandType.PAIR, HandType.FLUSH},
    HandType.FLUSH_HOUSE:     {HandType.FLUSH_HOUSE, HandType.FULL_HOUSE, HandType.THREE_OF_A_KIND, HandType.PAIR, HandType.FLUSH},
    HandType.FIVE_OF_A_KIND:  {HandType.FIVE_OF_A_KIND, HandType.FOUR_OF_A_KIND, HandType.THREE_OF_A_KIND, HandType.PAIR},
    HandType.STRAIGHT_FLUSH:  {HandType.STRAIGHT_FLUSH, HandType.STRAIGHT, HandType.FLUSH},
    HandType.FOUR_OF_A_KIND:  {HandType.FOUR_OF_A_KIND, HandType.THREE_OF_A_KIND, HandType.PAIR},
    HandType.FULL_HOUSE:      {HandType.FULL_HOUSE, HandType.THREE_OF_A_KIND, HandType.TWO_PAIR, HandType.PAIR},
    HandType.FLUSH:           {HandType.FLUSH},
    HandType.STRAIGHT:        {HandType.STRAIGHT},
    HandType.THREE_OF_A_KIND: {HandType.THREE_OF_A_KIND, HandType.PAIR},
    HandType.TWO_PAIR:        {HandType.TWO_PAIR, HandType.PAIR},
    HandType.PAIR:            {HandType.PAIR},
    HandType.HIGH_CARD:       {HandType.HIGH_CARD},
}

# Blind base chip requirements per ante
BLIND_BASE_CHIPS: dict[int, dict[str, int]] = {
    1: {"Small": 300,   "Big": 450,   "Boss": 600},
    2: {"Small": 800,   "Big": 1200,  "Boss": 1600},
    3: {"Small": 2800,  "Big": 4200,  "Boss": 5600},
    4: {"Small": 6000,  "Big": 9000,  "Boss": 12000},
    5: {"Small": 11000, "Big": 16500, "Boss": 22000},
    6: {"Small": 20000, "Big": 30000, "Boss": 40000},
    7: {"Small": 35000, "Big": 52500, "Boss": 70000},
    8: {"Small": 50000, "Big": 75000, "Boss": 100000},
}

# Stake scaling multipliers
STAKE_SCALING: dict[int, float] = {
    1: 1.0,   # White
    2: 1.0,   # Red
    3: 1.0,   # Green
    4: 1.0,   # Black
    5: 1.0,   # Blue
    6: 1.0,   # Purple
    7: 1.0,   # Orange
    8: 1.0,   # Gold
}
