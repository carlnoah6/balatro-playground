"""Adapter: bridge balatro-env decision engine → balatro_sim Strategy protocol.

Converts balatro_sim.GameState into the dict/string-based format that
balatro-env/decision/ expects, then maps decisions back to typed Actions.
"""

from __future__ import annotations

import sys
import os
from typing import Optional

# Add balatro-env to path so we can import decision.*
_BALATRO_ENV = "/home/ubuntu/balatro-env"
if _BALATRO_ENV not in sys.path:
    sys.path.insert(0, _BALATRO_ENV)

from .state import GameState
from .enums import Phase, HandType
from .actions import (
    Action, SelectBlind, SkipBlind, PlayHand, DiscardHand,
    BuyShopItem, SellJoker, RerollShop, LeaveShop,
)
from .cards import Card as SimCard, JokerCard as SimJoker

# Import the existing decision engine
from decision.scoring import Card as DecCard, Joker as DecJoker, HandLevel
from decision.strategy import (
    GameContext, ArchetypeTracker, BuildPlanner,
    should_discard, choose_play, shop_decisions, should_reroll,
    evaluate_shop_item,
)


# ============================================================
# Type Converters
# ============================================================

_RANK_TO_STR = {
    2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8",
    9: "9", 10: "10", 11: "Jack", 12: "Queen", 13: "King", 14: "Ace",
}


def _sim_card_to_dec(card: SimCard, index: int = 0) -> DecCard:
    """Convert balatro_sim Card → decision.scoring Card."""
    return DecCard(
        rank=_RANK_TO_STR.get(card.rank.value, str(card.rank.value)),
        suit=card.suit.value,  # "Hearts", "Spades", etc.
        enhancement=card.enhancement.value if card.enhancement else "",
        edition=card.edition.value if card.edition else "",
        seal=card.seal.value if card.seal else "",
        index=index,
        debuffed=card.debuffed,
    )


def _sim_joker_to_dec(joker: SimJoker) -> DecJoker:
    """Convert balatro_sim JokerCard → decision.scoring Joker."""
    return DecJoker(
        name=joker.name,
        edition=joker.edition.value if joker.edition else "",
        rarity="Common",
        extra=dict(joker.extra) if joker.extra else {},
    )


def _sim_hand_levels_to_dec(hl) -> HandLevel:
    """Convert balatro_sim HandLevels → decision.scoring HandLevel."""
    dec_hl = HandLevel()
    for ht_str, level in hl.levels.items():
        dec_hl.levels[ht_str] = level
    return dec_hl


def _state_to_context(
    state: GameState,
    archetype: ArchetypeTracker,
    build_planner: Optional[BuildPlanner] = None,
) -> GameContext:
    """Convert full GameState → GameContext for the decision engine."""
    hand_cards = [_sim_card_to_dec(c, i) for i, c in enumerate(state.hand)]
    jokers = [_sim_joker_to_dec(j) for j in state.jokers]
    hand_levels = _sim_hand_levels_to_dec(state.hand_levels)

    # Build shop_items as list[dict] matching decision engine format
    shop_items = []
    for item in state.shop_items:
        d = {"name": getattr(item, "name", ""), "cost": getattr(item, "cost", 0)}
        # Determine type
        type_name = type(item).__name__
        if "Joker" in type_name:
            d["type"] = "Joker"
            d["edition"] = getattr(item, "edition", "")
        elif "Consumable" in type_name:
            d["type"] = "Consumable"
            d["subtype"] = getattr(item, "card_type", "")
        elif "Voucher" in type_name:
            d["type"] = "Voucher"
        elif "Pack" in type_name:
            d["type"] = "Booster"
        else:
            d["type"] = "Unknown"
        shop_items.append(d)

    # Boss blind name
    boss_blind = state.blind_name if state.round_num == 2 else ""

    ctx = GameContext(
        ante=state.ante,
        round_num=state.round_num,
        hands_left=state.hands_left,
        discards_left=state.discards_left,
        blind_chips=state.blind_chips,
        current_chips=state.round_chips,
        dollars=state.dollars,
        hand_cards=hand_cards,
        jokers=jokers,
        joker_slots=state.joker_slots,
        consumables=[],
        consumable_slots=state.consumable_slots,
        hand_levels=hand_levels,
        archetype=archetype,
        shop_items=shop_items,
        blind_info={"boss_name": boss_blind},
        boss_blind=boss_blind,
        build_planner=build_planner,
    )
    return ctx


# ============================================================
# Strategy Adapter
# ============================================================

class KnowledgeBaseStrategy:
    """Wraps the balatro-env decision engine as a balatro_sim Strategy.

    Uses the full rule-based strategy: archetype tracking, build planning,
    joker tier list, economy management, boss blind counters, etc.
    """

    def __init__(self):
        self.archetype = ArchetypeTracker()
        self.build_planner = BuildPlanner()
        self._last_ante = 0

    def choose_action(self, state: GameState, legal_actions: list[Action]) -> Action:
        """Pick the best action using the knowledge-base strategy."""

        # Reset archetype tracker on new game
        if state.ante == 1 and state.round_num == 0 and state.hands_played_total == 0:
            self.archetype = ArchetypeTracker()
            self.build_planner = BuildPlanner()
            self._last_ante = 0

        # Build context
        ctx = _state_to_context(state, self.archetype, self.build_planner)

        # --- BLIND SELECT ---
        if state.phase == Phase.BLIND_SELECT:
            # Always select (skip logic could be added later)
            for a in legal_actions:
                if isinstance(a, SelectBlind):
                    return a
            return legal_actions[0]

        # --- PLAY HAND ---
        if state.phase == Phase.PLAY_HAND:
            # First check if we should discard
            do_discard, discard_indices, _reason = should_discard(ctx)
            if do_discard and discard_indices:
                # Find matching DiscardHand action
                target = tuple(sorted(discard_indices))
                for a in legal_actions:
                    if isinstance(a, DiscardHand) and a.card_indices == target:
                        return a
                # If exact match not found, build one if valid
                if all(0 <= i < len(state.hand) for i in target):
                    da = DiscardHand(card_indices=target)
                    if da in legal_actions:
                        return da
                    # Fallback: just use the discard action with closest match
                    discard_actions = [a for a in legal_actions if isinstance(a, DiscardHand)]
                    if discard_actions:
                        return discard_actions[0]

            # Choose best play
            play_indices, _reason = choose_play(ctx)
            if play_indices:
                target = tuple(sorted(play_indices))
                for a in legal_actions:
                    if isinstance(a, PlayHand) and a.card_indices == target:
                        return a
                # Build it directly
                if all(0 <= i < len(state.hand) for i in target):
                    pa = PlayHand(card_indices=target)
                    if pa in legal_actions:
                        return pa

            # Fallback: play highest-scoring from legal actions
            play_actions = [a for a in legal_actions if isinstance(a, PlayHand)]
            if play_actions:
                return play_actions[0]
            return legal_actions[0]

        # --- SHOP ---
        if state.phase == Phase.SHOP:
            # Check if we should buy something
            buy_actions = [a for a in legal_actions if isinstance(a, BuyShopItem)]
            if buy_actions and ctx.shop_items:
                ranked = shop_decisions(ctx)
                for item_idx, score, _reason in ranked:
                    if score >= 5.0:  # Only buy if score is decent
                        for a in buy_actions:
                            if isinstance(a, BuyShopItem) and a.item_index == item_idx:
                                # Track purchase for archetype
                                item = ctx.shop_items[item_idx]
                                self.archetype.signal_joker(item.get("name", ""))
                                return a

            # Check reroll
            do_reroll, _reason = should_reroll(ctx)
            if do_reroll:
                for a in legal_actions:
                    if isinstance(a, RerollShop):
                        return a

            # Leave shop
            for a in legal_actions:
                if isinstance(a, LeaveShop):
                    return a
            return legal_actions[0]

        return legal_actions[0]
