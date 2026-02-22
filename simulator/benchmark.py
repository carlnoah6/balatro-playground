#!/usr/bin/env python3
"""Benchmark: compare Random vs Greedy vs KnowledgeBase strategies.

Runs N games per strategy and reports:
- Win rate, avg ante reached, avg rounds won
- Avg hands played, avg steps, avg final dollars
- Per-ante survival curve
- Speed (games/sec)
"""

from __future__ import annotations

import sys
import os
import time
import json
from dataclasses import dataclass, field
from collections import Counter

# Ensure project root is on path
_PROJECT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _PROJECT)

from balatro_sim.runner import run_game, run_batch, RandomStrategy, GreedyStrategy, GameResult


def try_import_kb():
    """Try to import KnowledgeBaseStrategy (may fail if balatro-env missing)."""
    try:
        from balatro_sim.adapter import KnowledgeBaseStrategy
        return KnowledgeBaseStrategy
    except Exception as e:
        print(f"⚠️  KnowledgeBaseStrategy unavailable: {e}")
        return None


@dataclass
class BenchmarkResult:
    name: str
    results: list[GameResult]
    elapsed: float

    @property
    def n(self) -> int:
        return len(self.results)

    @property
    def wins(self) -> int:
        return sum(1 for r in self.results if r.won)

    @property
    def win_rate(self) -> float:
        return self.wins / max(1, self.n)

    @property
    def avg_ante(self) -> float:
        return sum(r.ante_reached for r in self.results) / max(1, self.n)

    @property
    def avg_rounds(self) -> float:
        return sum(r.rounds_won for r in self.results) / max(1, self.n)

    @property
    def avg_hands(self) -> float:
        return sum(r.hands_played for r in self.results) / max(1, self.n)

    @property
    def avg_steps(self) -> float:
        return sum(r.total_steps for r in self.results) / max(1, self.n)

    @property
    def avg_dollars(self) -> float:
        return sum(r.final_dollars for r in self.results) / max(1, self.n)

    @property
    def games_per_sec(self) -> float:
        return self.n / max(0.001, self.elapsed)

    def ante_distribution(self) -> dict[int, int]:
        """Count how many games reached each ante."""
        dist = Counter()
        for r in self.results:
            dist[r.ante_reached] += 1
        return dict(sorted(dist.items()))

    def survival_curve(self) -> dict[int, float]:
        """Fraction of games that reached at least ante N."""
        curve = {}
        for ante in range(1, 9):
            reached = sum(1 for r in self.results if r.ante_reached >= ante)
            curve[ante] = reached / max(1, self.n)
        return curve


def run_benchmark(
    strategy,
    name: str,
    n_games: int = 100,
    max_steps: int = 2000,
) -> BenchmarkResult:
    """Run benchmark for a single strategy."""
    seeds = [f"bench_{i:04d}" for i in range(n_games)]
    t0 = time.time()
    results = []
    for seed in seeds:
        try:
            r = run_game(seed, strategy, max_steps=max_steps)
            results.append(r)
        except Exception as e:
            # Record as loss at ante 1
            results.append(GameResult(
                seed=seed, won=False, ante_reached=1,
                rounds_won=0, total_steps=0, final_dollars=0,
                jokers_collected=0, hands_played=0,
            ))
    elapsed = time.time() - t0
    return BenchmarkResult(name=name, results=results, elapsed=elapsed)


def print_report(benchmarks: list[BenchmarkResult]):
    """Print comparison table."""
    print("\n" + "=" * 80)
    print("BALATRO SIMULATOR BENCHMARK")
    print("=" * 80)

    # Header
    names = [b.name for b in benchmarks]
    col_w = max(18, max(len(n) for n in names) + 2)
    header = f"{'Metric':<22}" + "".join(f"{n:>{col_w}}" for n in names)
    print(header)
    print("-" * len(header))

    # Metrics
    rows = [
        ("Games", [str(b.n) for b in benchmarks]),
        ("Wins", [str(b.wins) for b in benchmarks]),
        ("Win Rate", [f"{b.win_rate:.1%}" for b in benchmarks]),
        ("Avg Ante", [f"{b.avg_ante:.2f}" for b in benchmarks]),
        ("Avg Rounds Won", [f"{b.avg_rounds:.1f}" for b in benchmarks]),
        ("Avg Hands Played", [f"{b.avg_hands:.1f}" for b in benchmarks]),
        ("Avg Steps", [f"{b.avg_steps:.0f}" for b in benchmarks]),
        ("Avg Final $", [f"${b.avg_dollars:.0f}" for b in benchmarks]),
        ("Speed (games/s)", [f"{b.games_per_sec:.1f}" for b in benchmarks]),
        ("Time (s)", [f"{b.elapsed:.1f}" for b in benchmarks]),
    ]
    for label, vals in rows:
        print(f"{label:<22}" + "".join(f"{v:>{col_w}}" for v in vals))

    # Survival curve
    print("\n--- Survival Curve (% reaching ante N) ---")
    header2 = f"{'Ante':<10}" + "".join(f"{n:>{col_w}}" for n in names)
    print(header2)
    for ante in range(1, 9):
        vals = []
        for b in benchmarks:
            curve = b.survival_curve()
            vals.append(f"{curve.get(ante, 0):.0%}")
        print(f"  {ante:<8}" + "".join(f"{v:>{col_w}}" for v in vals))

    # Ante distribution
    print("\n--- Ante Distribution (games ending at each ante) ---")
    header3 = f"{'Ante':<10}" + "".join(f"{n:>{col_w}}" for n in names)
    print(header3)
    for ante in range(1, 9):
        vals = []
        for b in benchmarks:
            dist = b.ante_distribution()
            vals.append(str(dist.get(ante, 0)))
        print(f"  {ante:<8}" + "".join(f"{v:>{col_w}}" for v in vals))

    print("=" * 80)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Balatro Simulator Benchmark")
    parser.add_argument("-n", "--games", type=int, default=100, help="Games per strategy")
    parser.add_argument("--max-steps", type=int, default=2000, help="Max steps per game")
    parser.add_argument("--json", type=str, help="Output JSON results to file")
    parser.add_argument("--strategies", nargs="+", default=["random", "greedy", "kb"],
                        help="Strategies to benchmark: random, greedy, kb")
    args = parser.parse_args()

    benchmarks = []

    if "random" in args.strategies:
        print(f"Running Random strategy ({args.games} games)...")
        b = run_benchmark(RandomStrategy(seed=42), "Random", args.games, args.max_steps)
        benchmarks.append(b)
        print(f"  Done: avg ante {b.avg_ante:.2f}, {b.games_per_sec:.1f} games/s")

    if "greedy" in args.strategies:
        print(f"Running Greedy strategy ({args.games} games)...")
        b = run_benchmark(GreedyStrategy(), "Greedy", args.games, args.max_steps)
        benchmarks.append(b)
        print(f"  Done: avg ante {b.avg_ante:.2f}, {b.games_per_sec:.1f} games/s")

    if "kb" in args.strategies:
        KBClass = try_import_kb()
        if KBClass:
            print(f"Running KnowledgeBase strategy ({args.games} games)...")
            b = run_benchmark(KBClass(), "KnowledgeBase", args.games, args.max_steps)
            benchmarks.append(b)
            print(f"  Done: avg ante {b.avg_ante:.2f}, {b.games_per_sec:.1f} games/s")

    if benchmarks:
        print_report(benchmarks)

    # JSON output
    if args.json and benchmarks:
        data = {}
        for b in benchmarks:
            data[b.name] = {
                "n": b.n,
                "wins": b.wins,
                "win_rate": round(b.win_rate, 4),
                "avg_ante": round(b.avg_ante, 2),
                "avg_rounds": round(b.avg_rounds, 1),
                "avg_hands": round(b.avg_hands, 1),
                "avg_steps": round(b.avg_steps, 0),
                "avg_dollars": round(b.avg_dollars, 0),
                "games_per_sec": round(b.games_per_sec, 1),
                "elapsed": round(b.elapsed, 2),
                "survival_curve": b.survival_curve(),
                "ante_distribution": b.ante_distribution(),
            }
        with open(args.json, "w") as f:
            json.dump(data, f, indent=2)
        print(f"\nJSON results saved to {args.json}")


if __name__ == "__main__":
    main()
