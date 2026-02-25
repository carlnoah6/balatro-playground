"""Game state tracker — reconstructs game state from database logs.

Tracks owned jokers, used vouchers, played hand types across antes
to build accurate ShopConfig for each shop visit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .shop import ShopConfig, JOKER_BY_KEY, VOUCHER_BY_KEY


# Map display names → internal keys for jokers
_JOKER_NAME_TO_KEY: dict[str, str] = {}
for _key, _j in JOKER_BY_KEY.items():
    _JOKER_NAME_TO_KEY[_j[1]] = _key

# Map display names → internal keys for vouchers
_VOUCHER_NAME_TO_KEY: dict[str, str] = {}
for _key, _v in VOUCHER_BY_KEY.items():
    _VOUCHER_NAME_TO_KEY[_v.name] = _key


@dataclass
class GameState:
    """Accumulated game state at a point in time."""
    used_jokers: dict[str, bool] = field(default_factory=dict)
    used_vouchers: dict[str, bool] = field(default_factory=dict)
    played_hands: set[str] = field(default_factory=set)
    enhancement_cards: set[str] = field(default_factory=set)
    pool_flags: dict[str, bool] = field(default_factory=dict)

    def to_shop_config(self, ante: int) -> ShopConfig:
        """Build a ShopConfig reflecting current game state."""
        config = ShopConfig()
        config.used_jokers = dict(self.used_jokers)
        config.used_vouchers = dict(self.used_vouchers)
        config.played_hands = set(self.played_hands)
        config.enhancement_cards = set(self.enhancement_cards)
        config.pool_flags = dict(self.pool_flags)

        # Voucher effects on shop config
        if self.used_vouchers.get("v_overstock_plus"):
            config.joker_max = 4
        elif self.used_vouchers.get("v_overstock_norm"):
            config.joker_max = 3

        if self.used_vouchers.get("v_illusion"):
            config.has_illusion = True

        # Stake modifiers (White Stake = no eternals/perishables/rentals)
        # TODO: track stake from run data

        # first_shop_buffoon is a one-time flag: the very first get_pack()
        # call in the run returns a forced Buffoon Pack. That happens in
        # ante 1's first shop. For ante 2+, the flag is already set.
        if ante >= 2:
            config.first_shop_buffoon = True

        return config


def joker_name_to_key(name: str) -> Optional[str]:
    """Convert display name to internal key."""
    return _JOKER_NAME_TO_KEY.get(name)


def voucher_name_to_key(name: str) -> Optional[str]:
    """Convert display name to internal key."""
    return _VOUCHER_NAME_TO_KEY.get(name)


def extract_game_state_at_shops(rows: list[tuple]) -> dict[int, GameState]:
    """Extract game state at each shop visit from ordered game log rows.

    Args:
        rows: List of (seq, ante, phase, action, hand_type, jokers, shop_state_exists)
              ordered by seq.

    Returns:
        Dict mapping seq → GameState at that shop visit.
    """
    state = GameState()
    shop_states: dict[int, GameState] = {}
    seen_jokers: set[str] = set()

    for seq, ante, phase, action, hand_type, jokers, has_shop in rows:
        # Track played hand types
        if hand_type:
            state.played_hands.add(hand_type)

        # Track owned jokers from the jokers column
        if jokers:
            current = set(j.strip() for j in jokers.split(',') if j.strip())
            for name in current:
                if name not in seen_jokers:
                    seen_jokers.add(name)
                    key = joker_name_to_key(name)
                    if key:
                        state.used_jokers[key] = True

        # Track voucher purchases from action column
        if action and '购买' in action:
            # Pattern: "购买 <name> ($N)"
            m = re.match(r'购买\s+(.+?)\s+\(\$\d+\)', action)
            if m:
                item_name = m.group(1)
                vkey = voucher_name_to_key(item_name)
                if vkey:
                    state.used_vouchers[vkey] = True

        # Snapshot state at shop visits
        if has_shop:
            # Deep copy the current state
            shop_states[seq] = GameState(
                used_jokers=dict(state.used_jokers),
                used_vouchers=dict(state.used_vouchers),
                played_hands=set(state.played_hands),
                enhancement_cards=set(state.enhancement_cards),
                pool_flags=dict(state.pool_flags),
            )

    return shop_states
