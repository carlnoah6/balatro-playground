"""Action types for the Balatro simulator."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Action:
    """Base action type."""
    pass


@dataclass(frozen=True)
class SelectBlind(Action):
    """Choose to play the current blind."""
    pass


@dataclass(frozen=True)
class SkipBlind(Action):
    """Skip the current blind (Small/Big only)."""
    pass


@dataclass(frozen=True)
class PlayHand(Action):
    """Play selected cards from hand."""
    card_indices: tuple[int, ...]  # indices into hand (frozen for hashing)

    def __post_init__(self):
        # Ensure sorted tuple for consistent hashing
        if not isinstance(self.card_indices, tuple):
            object.__setattr__(self, 'card_indices', tuple(sorted(self.card_indices)))


@dataclass(frozen=True)
class DiscardHand(Action):
    """Discard selected cards from hand."""
    card_indices: tuple[int, ...]

    def __post_init__(self):
        if not isinstance(self.card_indices, tuple):
            object.__setattr__(self, 'card_indices', tuple(sorted(self.card_indices)))


@dataclass(frozen=True)
class BuyShopItem(Action):
    """Buy an item from the shop."""
    item_index: int


@dataclass(frozen=True)
class SellJoker(Action):
    """Sell a joker."""
    joker_index: int


@dataclass(frozen=True)
class SellConsumable(Action):
    """Sell a consumable."""
    consumable_index: int


@dataclass(frozen=True)
class UseConsumable(Action):
    """Use a consumable card."""
    consumable_index: int
    target_cards: tuple[int, ...] = ()


@dataclass(frozen=True)
class RerollShop(Action):
    """Reroll the shop."""
    pass


@dataclass(frozen=True)
class LeaveShop(Action):
    """Leave the shop, proceed to next blind."""
    pass
