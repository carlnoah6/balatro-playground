"""Balatro AI decision layer — modular strategy, scoring, and LLM integration."""

from .scoring import (
    Card,
    Joker,
    HandLevel,
    ScoreBreakdown,
    find_best_hands,
    calculate_score,
    classify_hand,
)
from .strategy import (
    GameContext,
    Archetype,
    ArchetypeTracker,
    evaluate_shop_item,
    shop_decisions,
    should_reroll,
    get_boss_counter,
    build_context,
    JokerTier,
    JOKER_TIERS,
)
from .search import evaluate_discard_options
from .engine import DecisionEngine
from .llm_advisor import advise_shop, advise_discard, advise_boss

__all__ = [
    # Scoring
    "Card",
    "Joker",
    "HandLevel",
    "ScoreBreakdown",
    "find_best_hands",
    "calculate_score",
    "classify_hand",
    # Strategy
    "GameContext",
    "Archetype",
    "ArchetypeTracker",
    "evaluate_shop_item",
    "shop_decisions",
    "should_reroll",
    "get_boss_counter",
    "build_context",
    "JokerTier",
    "JOKER_TIERS",
    # Search
    "evaluate_discard_options",
    # Engine
    "DecisionEngine",
    # LLM
    "advise_shop",
    "advise_discard",
    "advise_boss",
]
