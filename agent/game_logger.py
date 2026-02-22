"""Game Logger — records every decision as a text replay entry.

Usage:
    logger = GameLogger(run_id)
    logger.log_play(state, cards_played, hand_type, estimated, actual, decision_type, reasoning)
    logger.log_discard(state, cards_discarded, decision_type, reasoning)
    logger.log_shop(state, action, item, price, decision_type, reasoning)
    logger.log_blind_select(state, blind_choice)
    logger.log_cashout(state, reward)
"""

from __future__ import annotations
from typing import Optional

SUIT_SYMBOLS = {"Spades": "♠", "Hearts": "♥", "Diamonds": "♦", "Clubs": "♣"}
RANK_SHORT = {"Jack": "J", "Queen": "Q", "King": "K", "Ace": "A"}


def format_card(card) -> str:
    """Format a Card object or dict as '10♠' or 'K♥'."""
    if isinstance(card, dict):
        rank = card.get("value", card.get("rank", "?"))
        suit = card.get("suit", "?")
        rank = RANK_SHORT.get(rank, rank)
        suit_sym = SUIT_SYMBOLS.get(suit, suit[0] if suit else "?")
        enh = card.get("enhancement", "")
        if enh and enh not in ("Default Base", "Base", ""):
            return f"{rank}{suit_sym}[{enh}]"
        return f"{rank}{suit_sym}"
    # Card object
    rank = RANK_SHORT.get(card.rank, card.rank)
    suit_sym = SUIT_SYMBOLS.get(card.suit, card.suit[0] if card.suit else "?")
    extra = ""
    if hasattr(card, 'enhancement') and card.enhancement:
        extra += f"[{card.enhancement}]"
    if hasattr(card, 'edition') and card.edition:
        extra += f"({card.edition})"
    return f"{rank}{suit_sym}{extra}"


def format_cards(cards) -> str:
    """Format a list of Card objects as 'K♠ Q♠ J♠ 10♠'."""
    return " ".join(format_card(c) for c in cards)


def format_jokers(jokers) -> str:
    """Format joker list from state dict."""
    if isinstance(jokers, dict):
        jokers = list(jokers.values())
    if not jokers:
        return ""
    return ", ".join(j.get("name", "?") if isinstance(j, dict) else str(j) for j in jokers)


def format_joker_state(jokers) -> list[dict] | None:
    """Extract full joker runtime state for validation."""
    if isinstance(jokers, dict):
        jokers = list(jokers.values())
    if not jokers:
        return None
    result = []
    for j in jokers:
        if isinstance(j, dict):
            result.append({
                "name": j.get("name", "?"),
                "x_mult": j.get("x_mult", 0),
                "mult": j.get("mult", 0),
                "t_mult": j.get("t_mult", 0),
                "t_chips": j.get("t_chips", 0),
                "extra": j.get("extra"),
                "edition": j.get("edition", ""),
                "rarity": j.get("rarity", ""),
            })
    return result if result else None


def format_consumables(consumables) -> str:
    """Format consumables from state dict."""
    if isinstance(consumables, dict):
        consumables = list(consumables.values())
    if not consumables:
        return ""
    return ", ".join(c.get("name", "?") if isinstance(c, dict) else str(c) for c in consumables)


class GameLogger:
    """Records game decisions to balatro_game_log table."""

    def __init__(self, run_id: int, enabled: bool = True):
        self.run_id = run_id
        self.enabled = enabled
        self._seq = 0
        self._current_boss = ""  # Track current boss blind name

    def set_boss_blind(self, boss_name: str):
        """Set the current boss blind name (called when entering boss blind)."""
        self._current_boss = boss_name or ""

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _write(self, phase: str, ante: int, blind: str,
               hand_cards: str, jokers: str, consumables: str,
               dollars: int, hands_left: int, discards_left: int,
               chips: int, target: int,
               action: str, decision_type: str = None, reasoning: str = None,
               hand_type: str = None, estimated_score: int = None, actual_score: int = None,
               joker_state: list = None):
        if not self.enabled or not self.run_id:
            return
        try:
            from run_db import add_game_log
            add_game_log(
                self.run_id, self._next_seq(), phase, ante, blind,
                hand_cards, jokers, consumables,
                dollars, hands_left, discards_left, chips, target,
                action, decision_type, reasoning,
                hand_type, estimated_score, actual_score,
                boss_blind=self._current_boss,
                joker_state=joker_state
            )
        except Exception as e:
            print(f"[log] write failed: {e}")

    def _state_fields(self, st: dict):
        """Extract common fields from game state dict."""
        raw_jokers = st.get("jokers", {})
        jokers = format_jokers(raw_jokers)
        joker_state = format_joker_state(raw_jokers)
        consumables = format_consumables(st.get("consumables", {}))
        return {
            "jokers": jokers,
            "joker_state": joker_state,
            "consumables": consumables,
            "dollars": st.get("dollars", 0),
            "hands_left": st.get("hands_left", 0),
            "discards_left": st.get("discards_left", 0),
            "chips": st.get("chips", 0),
            "target": st.get("blind_chips", 0),
        }

    def log_play(self, st: dict, hand_cards, cards_played, cards_indices: list[int],
                 hand_type: str, estimated: int, actual: int,
                 decision_type: str, reasoning: str):
        """Log a play (出牌) action."""
        sf = self._state_fields(st)
        hand_str = format_cards(hand_cards) if hand_cards else ""
        played_str = format_cards(cards_played) if cards_played else ""
        action = f"出牌 [{played_str}]"
        self._write("play", st.get("ante", 0), st.get("blind_on_deck", ""),
                     hand_str, sf["jokers"], sf["consumables"],
                     sf["dollars"], sf["hands_left"], sf["discards_left"],
                     sf["chips"], sf["target"],
                     action, decision_type, reasoning,
                     hand_type, estimated, actual,
                     joker_state=sf.get("joker_state"))

    def log_discard(self, st: dict, hand_cards, cards_discarded,
                    decision_type: str, reasoning: str):
        """Log a discard (弃牌) action."""
        sf = self._state_fields(st)
        hand_str = format_cards(hand_cards) if hand_cards else ""
        discarded_str = format_cards(cards_discarded) if cards_discarded else ""
        action = f"弃牌 [{discarded_str}]"
        self._write("discard", st.get("ante", 0), st.get("blind_on_deck", ""),
                     hand_str, sf["jokers"], sf["consumables"],
                     sf["dollars"], sf["hands_left"], sf["discards_left"],
                     sf["chips"], sf["target"],
                     action, decision_type, reasoning)

    def log_shop_buy(self, st: dict, item_name: str, price: int,
                     decision_type: str, reasoning: str):
        """Log a shop purchase."""
        sf = self._state_fields(st)
        action = f"购买 {item_name} (${price})"
        self._write("shop", st.get("ante", 0), "",
                     "", sf["jokers"], sf["consumables"],
                     sf["dollars"], 0, 0, 0, 0,
                     action, decision_type, reasoning)

    def log_shop_skip(self, st: dict):
        """Log skipping remaining shop items."""
        sf = self._state_fields(st)
        self._write("shop", st.get("ante", 0), "",
                     "", sf["jokers"], sf["consumables"],
                     sf["dollars"], 0, 0, 0, 0,
                     "跳过商店")

    def log_blind_select(self, st: dict, blind: str, boss_name: str = ""):
        """Log blind selection."""
        sf = self._state_fields(st)
        boss_info = f" ({boss_name})" if boss_name else ""
        action = f"进入 {blind}{boss_info}"
        self._write("blind_select", st.get("ante", 0), blind,
                     "", sf["jokers"], sf["consumables"],
                     sf["dollars"], sf["hands_left"], sf["discards_left"],
                     0, sf["target"],
                     action)

    def log_cashout(self, st: dict, dollars_before: int = 0, dollars_after: int = 0, earned=0):
        """Log round cashout with dollar amounts."""
        sf = self._state_fields(st)
        try:
            earned_int = int(earned)
        except (ValueError, TypeError):
            earned_int = 0
        action = f"结算 ${dollars_before} → ${dollars_after} (+${earned_int})"
        self._write("cashout", st.get("ante", 0), "",
                     "", sf["jokers"], sf["consumables"],
                     dollars_after, 0, 0, sf["chips"], sf["target"],
                     action)

    def log_game_over(self, st: dict, reason: str = "game_over"):
        """Log game end."""
        sf = self._state_fields(st)
        action = f"游戏结束: {reason}"
        self._write("game_over", st.get("ante", 0), "",
                     "", sf["jokers"], sf["consumables"],
                     sf["dollars"], 0, 0, sf["chips"], 0,
                     action)
