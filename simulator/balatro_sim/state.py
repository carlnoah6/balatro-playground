"""Game state — the complete, serializable state of a Balatro game.

Designed for efficient copy (MCTS branching) and full determinism.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Optional

from .enums import Phase, Suit, Rank, HandType, BLIND_BASE_CHIPS
from .cards import Card, JokerCard, ConsumableCard, Deck
from .rng import RNGState
from .scoring import HandLevels

# TYPE_CHECKING avoids circular import
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .blinds import BossBlind, SkipTag


@dataclass
class GameState:
    """Complete game state. All fields needed to resume a game from any point."""

    # Identity
    seed: str = ""
    deck_type: str = "Red Deck"
    stake: int = 1

    # RNG
    rng: Optional[RNGState] = None

    # Phase
    phase: Phase = Phase.BLIND_SELECT
    ante: int = 1
    round_num: int = 0       # 0=Small, 1=Big, 2=Boss within an ante
    blind_type: str = "Small"
    blind_name: str = ""     # Boss blind name (e.g. "The Hook")
    blind_chips: int = 300   # Score target for current blind
    boss_blind_key: str = "" # Boss blind key for current ante (e.g. "bl_hook")

    # Boss blind tracking
    hands_played_this_round: list[str] = field(default_factory=list)  # HandType values played (for Eye/Mouth)
    first_hand_type: str = ""  # First hand type played this round (for Mouth)
    ox_target_hand: str = ""   # Hand type that triggers Ox ($0)
    face_down_indices: set[int] = field(default_factory=set)  # Indices of face-down cards in hand

    # Skip tags collected
    skip_tags: list[str] = field(default_factory=list)

    # Economy
    dollars: int = 4

    # Card zones
    full_deck: list[Card] = field(default_factory=list)  # All cards in the deck (template)
    draw_pile: list[Card] = field(default_factory=list)   # Cards available to draw
    hand: list[Card] = field(default_factory=list)        # Current hand
    discard_pile: list[Card] = field(default_factory=list)
    played_this_round: list[Card] = field(default_factory=list)

    # Resources
    hands_left: int = 4
    discards_left: int = 3
    round_chips: int = 0     # Chips accumulated this round

    # Collections
    jokers: list[JokerCard] = field(default_factory=list)
    consumables: list[ConsumableCard] = field(default_factory=list)
    vouchers: list[str] = field(default_factory=list)

    # Hand levels (planet upgrades)
    hand_levels: HandLevels = field(default_factory=HandLevels)

    # Limits
    hand_size: int = 8
    joker_slots: int = 5
    consumable_slots: int = 2

    # Shop
    shop_items: list = field(default_factory=list)
    reroll_cost: int = 5
    free_rerolls: int = 0

    # Scoring history (for analytics)
    hands_played_total: int = 0
    rounds_won: int = 0

    # Game result
    won: Optional[bool] = None  # None = in progress, True = won, False = lost

    # Shop state (real shop system, not serialized)
    _shop_state: object = field(default=None, repr=False, compare=False)

    @property
    def is_terminal(self) -> bool:
        return self.phase == Phase.GAME_OVER

    @property
    def blind_label(self) -> str:
        labels = {0: "Small", 1: "Big", 2: "Boss"}
        return labels.get(self.round_num, "Boss")

    def get_blind_target(self) -> int:
        """Get the chip target for the current blind."""
        ante_blinds = BLIND_BASE_CHIPS.get(self.ante, BLIND_BASE_CHIPS[8])
        return ante_blinds.get(self.blind_type, ante_blinds["Boss"])

    def copy(self) -> "GameState":
        """Deep copy for MCTS branching. Optimized to avoid full deepcopy."""
        new = GameState(
            seed=self.seed,
            deck_type=self.deck_type,
            stake=self.stake,
            rng=self.rng.copy() if self.rng else None,
            phase=self.phase,
            ante=self.ante,
            round_num=self.round_num,
            blind_type=self.blind_type,
            blind_name=self.blind_name,
            blind_chips=self.blind_chips,
            boss_blind_key=self.boss_blind_key,
            hands_played_this_round=list(self.hands_played_this_round),
            first_hand_type=self.first_hand_type,
            ox_target_hand=self.ox_target_hand,
            face_down_indices=set(self.face_down_indices),
            skip_tags=list(self.skip_tags),
            dollars=self.dollars,
            full_deck=[Card(c.rank, c.suit, c.edition, c.enhancement, c.seal) for c in self.full_deck],
            draw_pile=[Card(c.rank, c.suit, c.edition, c.enhancement, c.seal) for c in self.draw_pile],
            hand=[Card(c.rank, c.suit, c.edition, c.enhancement, c.seal) for c in self.hand],
            discard_pile=[Card(c.rank, c.suit, c.edition, c.enhancement, c.seal) for c in self.discard_pile],
            played_this_round=list(self.played_this_round),
            hands_left=self.hands_left,
            discards_left=self.discards_left,
            round_chips=self.round_chips,
            jokers=[copy.deepcopy(j) for j in self.jokers],
            consumables=list(self.consumables),
            vouchers=list(self.vouchers),
            hand_levels=self.hand_levels.copy(),
            hand_size=self.hand_size,
            joker_slots=self.joker_slots,
            consumable_slots=self.consumable_slots,
            shop_items=list(self.shop_items),
            reroll_cost=self.reroll_cost,
            free_rerolls=self.free_rerolls,
            hands_played_total=self.hands_played_total,
            rounds_won=self.rounds_won,
            won=self.won,
        )
        # Copy shop state if present (shallow — shop is regenerated each round)
        new._shop_state = copy.deepcopy(self._shop_state) if self._shop_state else None
        return new
