"""Balatro pure-Python simulator — core package."""

__version__ = "0.3.0"

from .engine import GameEngine
from .state import GameState
from .runner import run_game, run_batch, GameResult, RandomStrategy, GreedyStrategy
