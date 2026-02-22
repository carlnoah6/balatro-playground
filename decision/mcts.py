"""MCTS-based discard search for Balatro.

Replaces brute-force enumeration with Monte Carlo Tree Search that can:
- Plan multi-step discard sequences (discard -> draw -> discard again)
- Allocate simulation budget to promising branches via UCB1
- Handle stochastic draws naturally through sampling

Tree structure:
  DecisionNode (player chooses: PLAY or DISCARD subset)
    -> ChanceNode (nature draws replacement cards)
         -> DecisionNode (next decision with new hand)

Terminal conditions:
  - Player chooses PLAY -> evaluate hand score
  - No discards remaining -> forced PLAY
  - No hands remaining -> forced PLAY
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from itertools import combinations
from typing import Optional

from .scoring import Card, Joker, HandLevel, find_best_hands


# ============================================================
# Configuration
# ============================================================

DEFAULT_ITERATIONS = 800
UCB_C = 1.414
MAX_DISCARD_SIZE = 5
MAX_CHILDREN = 20
ROLLOUT_SAMPLES = 5
TIME_LIMIT_MS = 2000


@dataclass
class GameState:
    """Snapshot of game state for MCTS."""
    hand: list[Card]
    draw_pile: list[Card]
    jokers: list[Joker]
    hand_levels: HandLevel
    chips_needed: float
    hands_left: int
    discards_left: int
    boss_blind: str = ""

    def copy(self) -> GameState:
        return GameState(
            hand=list(self.hand),
            draw_pile=list(self.draw_pile),
            jokers=self.jokers,
            hand_levels=self.hand_levels,
            chips_needed=self.chips_needed,
            hands_left=self.hands_left,
            discards_left=self.discards_left,
            boss_blind=self.boss_blind,
        )


@dataclass(frozen=True)
class PlayAction:
    """Terminal action: play the best hand."""
    pass


@dataclass(frozen=True)
class DiscardAction:
    """Discard specific card indices from hand."""
    indices: tuple[int, ...]

    def __hash__(self):
        return hash(self.indices)


Action = PlayAction | DiscardAction


# ============================================================
# Tree nodes
# ============================================================

class DecisionNode:
    """Player decision node."""

    __slots__ = (
        "state", "parent", "visits", "total_value",
        "children", "untried_actions", "_best_score",
    )

    def __init__(self, state: GameState, parent: Optional[ChanceNode] = None):
        self.state = state
        self.parent = parent
        self.visits = 0
        self.total_value = 0.0
        self.children: dict[Action, ChanceNode] = {}
        self.untried_actions: list[Action] | None = None
        self._best_score: float | None = None

    def best_play_score(self) -> float:
        if self._best_score is None:
            hands = find_best_hands(
                self.state.hand, self.state.jokers,
                self.state.hand_levels, top_n=1,
                boss_blind=self.state.boss_blind,
            )
            self._best_score = hands[0].final_score if hands else 0.0
        return self._best_score

    def get_actions(self) -> list[Action]:
        if self.untried_actions is not None:
            return self.untried_actions

        actions: list[Action] = [PlayAction()]
        s = self.state

        if s.discards_left <= 0 or s.hands_left <= 1 or not s.draw_pile:
            self.untried_actions = actions
            return actions

        if self.best_play_score() >= s.chips_needed > 0:
            self.untried_actions = actions
            return actions

        hands = find_best_hands(
            s.hand, s.jokers, s.hand_levels, top_n=1,
            boss_blind=s.boss_blind,
        )
        scoring_set = set(hands[0].all_cards) if hands else set()
        non_scoring = [i for i in range(len(s.hand)) if i not in scoring_set]

        if not non_scoring:
            non_scoring = list(range(len(s.hand)))

        max_d = min(s.discards_left, len(non_scoring), MAX_DISCARD_SIZE)
        combos: list[DiscardAction] = []
        for n in range(1, max_d + 1):
            for combo in combinations(non_scoring, n):
                combos.append(DiscardAction(indices=combo))
                if len(combos) >= MAX_CHILDREN:
                    break
            if len(combos) >= MAX_CHILDREN:
                break

        actions.extend(combos)
        self.untried_actions = actions
        return actions

    def is_fully_expanded(self) -> bool:
        return len(self.children) >= len(self.get_actions())

    def ucb1_select(self) -> tuple[Action, ChanceNode]:
        log_parent = math.log(self.visits) if self.visits > 0 else 0
        best_val = -float("inf")
        best_action = None
        best_child = None

        for action, chance in self.children.items():
            if chance.visits == 0:
                return action, chance
            exploit = chance.total_value / chance.visits
            explore = UCB_C * math.sqrt(log_parent / chance.visits)
            val = exploit + explore
            if val > best_val:
                best_val = val
                best_action = action
                best_child = chance

        return best_action, best_child


class ChanceNode:
    """Nature node -- stochastic card draw after discard."""

    __slots__ = ("action", "parent", "visits", "total_value", "children")

    def __init__(self, action: Action, parent: DecisionNode):
        self.action = action
        self.parent = parent
        self.visits = 0
        self.total_value = 0.0
        self.children: list[DecisionNode] = []

    def sample_child(self) -> DecisionNode:
        """Sample a draw outcome and return/create the resulting DecisionNode."""
        parent_state = self.parent.state

        if isinstance(self.action, PlayAction):
            # Terminal -- create leaf with same state
            child_state = parent_state.copy()
            child_state.hands_left -= 1
            child = DecisionNode(child_state, parent=self)
            self.children.append(child)
            return child

        # DiscardAction: remove discarded cards, draw replacements
        disc = self.action
        remaining = [parent_state.hand[i] for i in range(len(parent_state.hand))
                      if i not in disc.indices]
        draw_count = min(len(disc.indices), len(parent_state.draw_pile))

        if draw_count == 0:
            child_state = parent_state.copy()
            child_state.hand = remaining
            child_state.discards_left -= 1
            child = DecisionNode(child_state, parent=self)
            self.children.append(child)
            return child

        drawn = random.sample(parent_state.draw_pile, draw_count)
        new_hand = remaining + drawn
        new_pile = [c for c in parent_state.draw_pile if c not in drawn]

        child_state = GameState(
            hand=new_hand,
            draw_pile=new_pile,
            jokers=parent_state.jokers,
            hand_levels=parent_state.hand_levels,
            chips_needed=parent_state.chips_needed,
            hands_left=parent_state.hands_left,
            discards_left=parent_state.discards_left - 1,
            boss_blind=parent_state.boss_blind,
        )
        child = DecisionNode(child_state, parent=self)
        self.children.append(child)
        return child


# ============================================================
# Evaluation & Rollout
# ============================================================

def _evaluate_terminal(state: GameState) -> float:
    """Score a terminal state (player chose PLAY). Returns normalized value."""
    hands = find_best_hands(
        state.hand, state.jokers, state.hand_levels,
        top_n=1, boss_blind=state.boss_blind,
    )
    if not hands:
        return 0.0

    score = hands[0].final_score
    if state.chips_needed <= 0:
        return score  # No target, raw score is value

    # Normalize: 1.0 = exactly meets target, >1 = exceeds, <1 = falls short
    ratio = score / state.chips_needed
    if ratio >= 1.0:
        return 1.0 + min(ratio - 1.0, 1.0) * 0.5  # Cap bonus at 1.5
    return ratio


def _rollout(state: GameState) -> float:
    """Random rollout from a state. Returns average value over samples."""
    if state.discards_left <= 0 or not state.draw_pile:
        return _evaluate_terminal(state)

    total = 0.0
    for _ in range(ROLLOUT_SAMPLES):
        total += _single_rollout(state)
    return total / ROLLOUT_SAMPLES


def _single_rollout(state: GameState) -> float:
    """Single random rollout: randomly discard or play until terminal."""
    s = state.copy()

    # Greedy rollout: if current hand clears, play immediately
    hands = find_best_hands(
        s.hand, s.jokers, s.hand_levels, top_n=1, boss_blind=s.boss_blind,
    )
    if hands and hands[0].final_score >= s.chips_needed > 0:
        return _evaluate_terminal(s)

    # Random discard of 1-3 non-scoring cards if discards available
    if s.discards_left > 0 and s.draw_pile and s.hands_left > 1:
        scoring_set = set(hands[0].all_cards) if hands else set()
        non_scoring = [i for i in range(len(s.hand)) if i not in scoring_set]

        if non_scoring:
            n_disc = min(random.randint(1, 3), len(non_scoring), len(s.draw_pile))
            to_discard = set(random.sample(non_scoring, n_disc))
            remaining = [s.hand[i] for i in range(len(s.hand)) if i not in to_discard]
            drawn = random.sample(s.draw_pile, n_disc)
            s.hand = remaining + drawn
            s.draw_pile = [c for c in s.draw_pile if c not in drawn]
            s.discards_left -= 1

    return _evaluate_terminal(s)


# ============================================================
# Backpropagation
# ============================================================

def _backpropagate(node: DecisionNode | ChanceNode, value: float):
    """Propagate value up the tree."""
    current = node
    while current is not None:
        current.visits += 1
        current.total_value += value
        if isinstance(current, DecisionNode):
            current = current.parent
        else:
            current = current.parent


# ============================================================
# Main MCTS search
# ============================================================

@dataclass
class MCTSResult:
    """Result of MCTS search."""
    action: str           # "play" or "discard"
    card_indices: list[int]
    expected_score: float
    reasoning: str
    iterations: int
    time_ms: float
    # For multi-step plans
    plan: list[str] = field(default_factory=list)


def mcts_search(
    hand_cards: list[Card],
    jokers: list[Joker],
    hand_levels: HandLevel,
    draw_pile: list[Card],
    chips_needed: float,
    hands_left: int,
    discards_left: int,
    boss_blind: str = "",
    iterations: int = DEFAULT_ITERATIONS,
    time_limit_ms: int = TIME_LIMIT_MS,
) -> MCTSResult:
    """Run MCTS to find the best discard/play decision.

    Returns MCTSResult with the recommended action.
    """
    start = time.monotonic()

    root_state = GameState(
        hand=list(hand_cards),
        draw_pile=list(draw_pile),
        jokers=jokers,
        hand_levels=hand_levels,
        chips_needed=chips_needed,
        hands_left=hands_left,
        discards_left=discards_left,
        boss_blind=boss_blind,
    )
    root = DecisionNode(root_state)

    # Quick check: if we can already clear, just play
    play_score = root.best_play_score()
    if play_score >= chips_needed > 0:
        hands = find_best_hands(hand_cards, jokers, hand_levels, top_n=1,
                                boss_blind=boss_blind)
        indices = hands[0].all_cards if hands else list(range(min(5, len(hand_cards))))
        elapsed = (time.monotonic() - start) * 1000
        return MCTSResult(
            action="play",
            card_indices=indices,
            expected_score=play_score,
            reasoning=f"Already clears ({play_score:.0f} >= {chips_needed:.0f})",
            iterations=0,
            time_ms=elapsed,
        )

    # If no discards possible, just play
    actions = root.get_actions()
    if len(actions) <= 1:
        hands = find_best_hands(hand_cards, jokers, hand_levels, top_n=1,
                                boss_blind=boss_blind)
        indices = hands[0].all_cards if hands else list(range(min(5, len(hand_cards))))
        elapsed = (time.monotonic() - start) * 1000
        return MCTSResult(
            action="play",
            card_indices=indices,
            expected_score=play_score,
            reasoning="No discard options available",
            iterations=0,
            time_ms=elapsed,
        )

    # Main MCTS loop
    deadline = start + time_limit_ms / 1000.0
    iters = 0

    for iters in range(1, iterations + 1):
        if time.monotonic() > deadline:
            break

        # 1. SELECT: walk down tree using UCB1
        node = root
        while node.is_fully_expanded() and node.children:
            action, chance = node.ucb1_select()
            if chance is None:
                break
            # Sample a draw outcome from the chance node
            node = chance.sample_child()

        # 2. EXPAND: add a new child if not fully expanded
        if not node.is_fully_expanded():
            actions = node.get_actions()
            tried = set(node.children.keys())
            untried = [a for a in actions if a not in tried]
            if untried:
                action = random.choice(untried)
                chance = ChanceNode(action, node)
                node.children[action] = chance
                # Sample one outcome
                child = chance.sample_child()
                node = child

        # 3. ROLLOUT: simulate from this node
        value = _rollout(node.state)

        # 4. BACKPROPAGATE
        _backpropagate(node, value)

    elapsed = (time.monotonic() - start) * 1000

    # Extract best action from root (most visited)
    if not root.children:
        hands = find_best_hands(hand_cards, jokers, hand_levels, top_n=1,
                                boss_blind=boss_blind)
        indices = hands[0].all_cards if hands else list(range(min(5, len(hand_cards))))
        return MCTSResult(
            action="play",
            card_indices=indices,
            expected_score=play_score,
            reasoning="MCTS produced no children",
            iterations=iters,
            time_ms=elapsed,
        )

    best_action = max(root.children.keys(),
                      key=lambda a: root.children[a].visits)
    best_chance = root.children[best_action]
    avg_value = best_chance.total_value / best_chance.visits if best_chance.visits else 0

    if isinstance(best_action, PlayAction):
        hands = find_best_hands(hand_cards, jokers, hand_levels, top_n=1,
                                boss_blind=boss_blind)
        indices = hands[0].all_cards if hands else list(range(min(5, len(hand_cards))))
        hand_type = hands[0].hand_type if hands else "?"

        # Build stats string
        stats = _format_stats(root)
        return MCTSResult(
            action="play",
            card_indices=indices,
            expected_score=play_score,
            reasoning=f"[mcts] Play {hand_type} ({play_score:.0f}) "
                      f"v={avg_value:.3f} {stats}",
            iterations=iters,
            time_ms=elapsed,
        )
    else:
        disc = best_action
        card_names = " ".join(
            f"{hand_cards[i].rank}{hand_cards[i].suit[0]}" for i in disc.indices
        )
        stats = _format_stats(root)
        return MCTSResult(
            action="discard",
            card_indices=list(disc.indices),
            expected_score=avg_value * chips_needed if chips_needed > 0 else avg_value,
            reasoning=f"[mcts] Discard [{card_names}] "
                      f"v={avg_value:.3f} {stats}",
            iterations=iters,
            time_ms=elapsed,
        )


def _format_stats(root: DecisionNode) -> str:
    """Format root child visit stats for logging."""
    parts = []
    # Sort by visits descending, show top 5
    sorted_children = sorted(
        root.children.items(),
        key=lambda kv: kv[1].visits,
        reverse=True,
    )
    for action, chance in sorted_children[:5]:
        avg = chance.total_value / chance.visits if chance.visits else 0
        if isinstance(action, PlayAction):
            parts.append(f"PLAY:{chance.visits}({avg:.2f})")
        else:
            n = len(action.indices)
            parts.append(f"D{n}:{chance.visits}({avg:.2f})")
    return f"[{root.visits}it " + " ".join(parts) + "]"


# ============================================================
# Drop-in replacement for evaluate_discard_options
# ============================================================

def mcts_evaluate_discard(
    hand_cards: list[Card],
    jokers: list[Joker],
    hand_levels: HandLevel,
    draw_pile: list[Card],
    chips_needed: float,
    hands_left: int,
    discards_left: int,
    boss_blind: str = "",
    iterations: int = DEFAULT_ITERATIONS,
    time_limit_ms: int = TIME_LIMIT_MS,
) -> tuple[str, list[int], float, str]:
    """Drop-in replacement for search.evaluate_discard_options.

    Returns: (action, card_indices, expected_score, reasoning)
    Same signature as the original for easy integration.
    """
    result = mcts_search(
        hand_cards=hand_cards,
        jokers=jokers,
        hand_levels=hand_levels,
        draw_pile=draw_pile,
        chips_needed=chips_needed,
        hands_left=hands_left,
        discards_left=discards_left,
        boss_blind=boss_blind,
        iterations=iterations,
        time_limit_ms=time_limit_ms,
    )
    return (result.action, result.card_indices, result.expected_score, result.reasoning)
