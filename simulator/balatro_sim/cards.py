"""Card and Deck data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .enums import Suit, Rank, Edition, Enhancement, Seal


@dataclass
class Card:
    """A playing card with all Balatro modifiers."""
    rank: Rank
    suit: Suit
    edition: Edition = Edition.NONE
    enhancement: Enhancement = Enhancement.NONE
    seal: Seal = Seal.NONE
    debuffed: bool = False

    @property
    def chip_value(self) -> int:
        """Base chip value of this card when scored."""
        if self.enhancement == Enhancement.STONE:
            return 50  # Stone cards always give +50 chips
        return self.rank.chip_value

    @property
    def is_face(self) -> bool:
        return self.rank.is_face

    @property
    def is_wild(self) -> bool:
        return self.enhancement == Enhancement.WILD

    def matches_suit(self, suit: Suit) -> bool:
        """Check if card matches a suit (Wild cards match all suits)."""
        if self.is_wild:
            return True
        return self.suit == suit

    def display(self) -> str:
        suit_sym = {"Spades": "♠", "Hearts": "♥", "Clubs": "♣", "Diamonds": "♦"}
        s = f"{self.rank.display}{suit_sym.get(self.suit.value, '?')}"
        if self.enhancement != Enhancement.NONE:
            s += f"[{self.enhancement.value}]"
        if self.edition != Edition.NONE:
            s += f"({self.edition.value})"
        if self.seal != Seal.NONE:
            s += f"<{self.seal.value}>"
        return s

    def __repr__(self) -> str:
        return self.display()


@dataclass
class JokerCard:
    """A Joker with its runtime state."""
    key: str                    # e.g. 'j_joker', 'j_blueprint'
    name: str = ""              # display name
    edition: Edition = Edition.NONE
    eternal: bool = False
    perishable: bool = False
    rental: bool = False
    sell_value: int = 0
    extra: dict | int | float | None = field(default_factory=dict)  # joker-specific mutable state
    # Runtime ability fields from Lua card.ability.*
    mult: float = 0
    t_mult: float = 0
    t_chips: float = 0
    x_mult: float = 0

    def __post_init__(self):
        if not self.name:
            self.name = self.key.replace("j_", "").replace("_", " ").title()

    def get_extra(self, key: str, default=0):
        """Get a value from extra dict, or return extra if it's a number."""
        if isinstance(self.extra, dict):
            return self.extra.get(key, default)
        if isinstance(self.extra, (int, float)) and key == "value":
            return self.extra
        return default


@dataclass
class ConsumableCard:
    """A consumable (Tarot, Planet, Spectral)."""
    key: str
    name: str = ""
    card_type: str = ""  # "Tarot", "Planet", "Spectral"

    def __post_init__(self):
        if not self.name:
            self.name = self.key


class Deck:
    """Standard 52-card deck with modifications."""

    def __init__(self, cards: Optional[list[Card]] = None):
        if cards is not None:
            self.cards = list(cards)
        else:
            self.cards = self._standard_52()

    @staticmethod
    def _standard_52() -> list[Card]:
        """Create a standard 52-card deck."""
        cards = []
        for suit in Suit:
            for rank in Rank:
                cards.append(Card(rank=rank, suit=suit))
        return cards

    def copy(self) -> "Deck":
        return Deck([Card(c.rank, c.suit, c.edition, c.enhancement, c.seal) for c in self.cards])

    def __len__(self) -> int:
        return len(self.cards)

    def __iter__(self):
        return iter(self.cards)

    def __getitem__(self, idx):
        return self.cards[idx]
