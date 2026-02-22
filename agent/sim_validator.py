"""Simulator Validator — compare simulator output against real game logs.

Validates:
1. Boss Blind sequence (per ante)
2. Shop joker availability (purchased jokers should appear in simulated shop)
3. Scoring accuracy (simulated score vs actual game score)

Usage:
  python3 sim_validator.py --seed H554B4BG
  python3 sim_validator.py --batch-id 57
  python3 sim_validator.py --batch-id 57 --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field

import psycopg2

# Add simulator to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "simulator"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".openclaw", "workspace", "projects", "balatro-simulator"))

from balatro_sim.rng import RNGState
from balatro_sim.shop import generate_shop


def get_conn():
    return psycopg2.connect(os.environ.get("DATABASE_URL", ""))


@dataclass
class ValidationResult:
    seed: str
    checks: list[dict] = field(default_factory=list)
    passed: int = 0
    failed: int = 0
    warnings: int = 0

    def add(self, category: str, ante: int, expected: str, actual: str, match: bool, detail: str = ""):
        status = "PASS" if match else "FAIL"
        if not match:
            self.failed += 1
        else:
            self.passed += 1
        self.checks.append({
            "category": category,
            "ante": ante,
            "expected": expected,
            "actual": actual,
            "status": status,
            "detail": detail,
        })

    def add_warning(self, category: str, ante: int, detail: str):
        self.warnings += 1
        self.checks.append({
            "category": category,
            "ante": ante,
            "status": "WARN",
            "detail": detail,
        })

    @property
    def score(self) -> str:
        total = self.passed + self.failed
        if total == 0:
            return "N/A"
        return f"{self.passed}/{total} ({round(self.passed/total*100)}%)"

    def summary(self) -> str:
        lines = [f"Seed {self.seed}: {self.score} passed, {self.warnings} warnings"]
        for c in self.checks:
            if c["status"] == "FAIL":
                lines.append(f"  ❌ [{c['category']}] Ante {c['ante']}: expected={c['expected']} actual={c['actual']} {c.get('detail','')}")
            elif c["status"] == "WARN":
                lines.append(f"  ⚠️  [{c['category']}] Ante {c['ante']}: {c['detail']}")
        return "\n".join(lines)


def validate_seed(seed: str, run_id: int = None) -> ValidationResult:
    """Validate simulator against real game logs for a given seed."""
    result = ValidationResult(seed=seed)
    conn = get_conn()
    cur = conn.cursor()

    # Find the run
    if run_id:
        cur.execute("SELECT id, seed FROM balatro_runs WHERE id = %s", (run_id,))
    else:
        cur.execute("SELECT id, seed FROM balatro_runs WHERE seed = %s ORDER BY id DESC LIMIT 1", (seed,))
    run = cur.fetchone()
    if not run:
        result.add_warning("setup", 0, f"No run found for seed {seed}")
        conn.close()
        return result

    rid = run[0]

    # ── 1. Boss Blind Validation ──
    cur.execute("""
        SELECT DISTINCT ante, boss_blind
        FROM balatro_game_log
        WHERE run_id = %s AND boss_blind IS NOT NULL AND boss_blind != ''
        ORDER BY ante
    """, (rid,))
    boss_rows = cur.fetchall()

    # Simulate boss blinds
    # Note: boss blind generation depends on RNG state which is affected by all prior decisions
    # For now, we just record what the game had — full boss validation needs the complete game flow
    if boss_rows:
        for ante, boss in boss_rows:
            result.add_warning("boss_blind", ante, f"Real boss: {boss} (full validation needs complete game flow simulation)")

    # ── 2. Shop Joker Validation ──
    # Get all purchased jokers per ante
    cur.execute("""
        SELECT ante, action
        FROM balatro_game_log
        WHERE run_id = %s AND phase = 'shop' AND action LIKE '购买 %%'
        ORDER BY ante, seq
    """, (rid,))
    shop_purchases = {}
    for ante, action in cur.fetchall():
        # Parse "购买 Hologram ($7)" -> "Hologram"
        name = action.replace("购买 ", "").split(" (")[0].strip()
        # Skip packs and vouchers
        if any(kw in name for kw in ["Pack", "Voucher", "Overstock", "Seed Money",
                                      "Crystal Ball", "Hone", "Grabber", "Wasteful",
                                      "Reroll", "Telescope", "Money Tree", "Glow Up"]):
            continue
        if ante not in shop_purchases:
            shop_purchases[ante] = []
        shop_purchases[ante].append(name)

    # Simulate shops for each ante and check if purchased jokers appear
    rng = RNGState(seed)
    for ante in range(1, max(shop_purchases.keys(), default=0) + 1):
        sim_jokers_this_ante = set()
        for blind_idx in range(3):  # small, big, boss
            shop = generate_shop(rng, ante=ante, owned_joker_keys=set(), owned_vouchers=set())
            for item in shop.card_slots:
                if hasattr(item, "joker_def"):
                    sim_jokers_this_ante.add(item.joker_def.name)

        purchased = shop_purchases.get(ante, [])
        for joker_name in purchased:
            found = joker_name in sim_jokers_this_ante
            result.add(
                "shop_joker", ante,
                expected=joker_name,
                actual="found" if found else f"NOT in sim ({', '.join(sorted(sim_jokers_this_ante))})",
                match=found,
                detail=f"Purchased {joker_name}" + ("" if found else " — sim shop didn't have it"),
            )

    # ── 3. Scoring Validation ──
    cur.execute("""
        SELECT ante, hand_type, estimated_score, actual_score, hand_cards, jokers
        FROM balatro_game_log
        WHERE run_id = %s AND phase = 'play'
        AND actual_score IS NOT NULL AND actual_score > 0
        ORDER BY ante, seq
    """, (rid,))
    score_rows = cur.fetchall()

    for ante, hand_type, est, actual, hand_cards, jokers in score_rows:
        if est and actual and actual > 0:
            error_pct = abs(est - actual) / actual * 100
            match = error_pct < 5  # 5% tolerance
            result.add(
                "scoring", ante,
                expected=f"{actual} (game)",
                actual=f"{est} (engine, {error_pct:.1f}% error)",
                match=match,
                detail=f"{hand_type} with {jokers[:50] if jokers else 'no jokers'}",
            )

    conn.close()
    return result


def validate_batch(batch_id: int) -> list[ValidationResult]:
    """Validate all seeds in a batch."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT r.id, r.seed FROM balatro_runs r
        JOIN balatro_batch_runs br ON r.batch_run_id = br.id
        WHERE br.batch_id = %s AND r.seed IS NOT NULL
        ORDER BY r.seed
    """, (batch_id,))
    runs = cur.fetchall()
    conn.close()

    results = []
    for rid, seed in runs:
        r = validate_seed(seed, run_id=rid)
        results.append(r)
    return results


def print_report(results: list[ValidationResult], as_json: bool = False):
    if as_json:
        data = []
        for r in results:
            data.append({
                "seed": r.seed,
                "passed": r.passed,
                "failed": r.failed,
                "warnings": r.warnings,
                "score": r.score,
                "checks": r.checks,
            })
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        total_pass = sum(r.passed for r in results)
        total_fail = sum(r.failed for r in results)
        total_warn = sum(r.warnings for r in results)
        total = total_pass + total_fail

        print(f"\n{'='*60}")
        print(f"Simulator Validation Report")
        print(f"Seeds: {len(results)} | Checks: {total} | Pass: {total_pass} | Fail: {total_fail} | Warn: {total_warn}")
        if total > 0:
            print(f"Accuracy: {round(total_pass/total*100)}%")
        print(f"{'='*60}\n")

        for r in results:
            print(r.summary())
            print()

        # Summary of failures by category
        if total_fail > 0:
            print("--- Failure Summary ---")
            cats = {}
            for r in results:
                for c in r.checks:
                    if c["status"] == "FAIL":
                        cat = c["category"]
                        cats[cat] = cats.get(cat, 0) + 1
            for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
                print(f"  {cat}: {count} failures")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate simulator against real game logs")
    parser.add_argument("--seed", help="Validate a specific seed")
    parser.add_argument("--batch-id", type=int, help="Validate all seeds in a batch")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if args.seed:
        results = [validate_seed(args.seed)]
    elif args.batch_id:
        results = validate_batch(args.batch_id)
    else:
        parser.print_help()
        sys.exit(1)

    print_report(results, as_json=args.json)
