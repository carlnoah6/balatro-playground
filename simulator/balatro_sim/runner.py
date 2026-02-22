"""Game runner — plays complete Balatro games with pluggable strategies.

Provides:
- run_game(): single game with a strategy callback
- RandomStrategy: baseline random play
- GreedyStrategy: always plays highest-scoring hand, skips shop
- GameResult: structured result with stats
"""

from __future__ import annotations

import random as _random
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

from .engine import GameEngine
from .state import GameState
from .actions import (
    Action, SelectBlind, SkipBlind, PlayHand, DiscardHand,
    BuyShopItem, SellJoker, RerollShop, LeaveShop,
)
from .enums import Phase


class Strategy(Protocol):
    """Protocol for game-playing strategies."""
    def choose_action(self, state: GameState, legal_actions: list[Action]) -> Action:
        ...


@dataclass
class GameResult:
    """Result of a completed game."""
    seed: str
    won: bool
    ante_reached: int
    rounds_won: int
    total_steps: int
    final_dollars: int
    jokers_collected: int
    hands_played: int
    deck_type: str = "Red Deck"

    @property
    def score(self) -> float:
        """Normalized score: 1.0 = beat ante 8, partial credit for progress."""
        if self.won:
            return 1.0
        return self.ante_reached / 8.0 * 0.5


class RandomStrategy:
    """Plays random legal actions."""

    def __init__(self, seed: int = 42):
        self._rng = _random.Random(seed)

    def choose_action(self, state: GameState, legal_actions: list[Action]) -> Action:
        return self._rng.choice(legal_actions)


class GreedyStrategy:
    """Greedy strategy: plays highest-scoring hand, discards weak cards, buys affordable jokers."""

    def __init__(self):
        self._engine = GameEngine()

    def choose_action(self, state: GameState, legal_actions: list[Action]) -> Action:
        if state.phase == Phase.BLIND_SELECT:
            return SelectBlind()

        if state.phase == Phase.PLAY_HAND:
            play_actions = [a for a in legal_actions if isinstance(a, PlayHand)]
            discard_actions = [a for a in legal_actions if isinstance(a, DiscardHand)]

            # Find best play
            best_play = None
            best_score = -1
            for action in play_actions:
                from .hands import evaluate_hand
                from .scoring import calculate_score
                played = [state.hand[i] for i in action.card_indices]
                ht, si = evaluate_hand(played)
                held = [state.hand[i] for i in range(len(state.hand)) if i not in set(action.card_indices)]
                result = calculate_score(played, ht, si, state.hand_levels, held, state.jokers)
                if result.final_score > best_score:
                    best_score = result.final_score
                    best_play = action

            # If best play is weak and we have discards, discard low cards
            chips_needed = state.blind_chips - state.round_chips
            avg_needed = chips_needed / max(state.hands_left, 1)
            if best_score < avg_needed * 0.8 and discard_actions and state.discards_left > 0:
                # Discard the lowest-value cards (up to 5)
                card_values = [(i, state.hand[i].rank.value) for i in range(len(state.hand))]
                card_values.sort(key=lambda x: x[1])
                discard_indices = tuple(cv[0] for cv in card_values[:min(5, len(card_values))])
                return DiscardHand(card_indices=discard_indices)

            if best_play:
                return best_play
            return play_actions[0] if play_actions else legal_actions[0]

        if state.phase == Phase.SHOP:
            buy_actions = [a for a in legal_actions if isinstance(a, BuyShopItem)]
            if buy_actions:
                return buy_actions[0]
            return LeaveShop()

        return legal_actions[0]


def run_game(
    seed: str,
    strategy: Strategy,
    deck_type: str = "Red Deck",
    stake: int = 1,
    max_steps: int = 2000,
    on_step: Optional[Callable[[GameState, Action, int], None]] = None,
) -> GameResult:
    """Run a complete game with the given strategy.

    Args:
        seed: Game seed for deterministic RNG.
        strategy: Strategy that picks actions.
        deck_type: Starting deck type.
        stake: Difficulty stake level.
        max_steps: Safety limit to prevent infinite loops.
        on_step: Optional callback(state, action, step_num) for logging.

    Returns:
        GameResult with final stats.
    """
    engine = GameEngine()
    state = engine.new_game(seed, deck_type=deck_type, stake=stake)

    steps = 0
    while not engine.is_terminal(state) and steps < max_steps:
        actions = engine.get_legal_actions(state)
        if not actions:
            break

        action = strategy.choose_action(state, actions)

        if on_step:
            on_step(state, action, steps)

        state = engine.step(state, action)
        steps += 1

    return GameResult(
        seed=seed,
        won=state.won is True,
        ante_reached=state.ante,
        rounds_won=state.rounds_won,
        total_steps=steps,
        final_dollars=state.dollars,
        jokers_collected=len(state.jokers),
        hands_played=state.hands_played_total,
        deck_type=deck_type,
    )


def run_batch(
    seeds: list[str],
    strategy: Strategy,
    deck_type: str = "Red Deck",
    stake: int = 1,
    max_steps: int = 2000,
) -> list[GameResult]:
    """Run multiple games and return results."""
    return [
        run_game(seed, strategy, deck_type, stake, max_steps)
        for seed in seeds
    ]
