"""Seed quality analyzer — rate seeds by early-game potential.

Scans seeds and scores them based on:
- Shop joker quality (S/A tier, xMult availability)
- Boss blind difficulty
- Voucher quality
- Build path feasibility

Outputs tiered seed sets for benchmarking.
"""

from __future__ import annotations

import random
import sys
from dataclasses import dataclass

from balatro_sim.rng import RNGState
from balatro_sim.data import JOKER_CATALOG, JOKERS_BY_RARITY, Rarity, JokerDef
from balatro_sim.shop import generate_shop

# ---------------------------------------------------------------------------
# Joker quality tiers (from our knowledge base)
# ---------------------------------------------------------------------------

S_PLUS_JOKERS = {
    "Blueprint", "Brainstorm",  # Copy effects
}

S_TIER_JOKERS = {
    "Hologram", "Steel Joker", "Glass Joker",  # xMult
    "The Idol", "Photograph", "Baron",  # xMult conditional
    "Fibonacci", "Blackboard",  # xMult
    "DNA", "Vampire",  # Rare power
    "Obelisk", "Lucky Cat", "Campfire",  # Scaling xMult
}

A_TIER_JOKERS = {
    "Even Steven", "Odd Todd", "Scholar",  # Solid +Mult/+Chips
    "Supernova", "Green Joker", "Spare Trousers", "Flash Card",  # Scaling +Mult
    "Ride the Bus", "Runner", "Square Joker",  # Scaling
    "Hack", "Dusk", "Mime",  # Retrigger
    "Smeared Joker", "Four Fingers", "Shortcut",  # Hand enablers
    "Flower Pot", "The Duo", "The Trio", "The Family", "The Order", "The Tribe",
    "Stuntman", "Wee Joker", "Hit the Road",
    "Loyalty Card", "Card Sharp",
}

XMULT_JOKERS = {
    "Hologram", "Steel Joker", "Glass Joker", "The Idol", "Photograph",
    "Baron", "Fibonacci", "Blackboard", "Obelisk", "Lucky Cat", "Campfire",
    "Blueprint", "Brainstorm", "Acrobat", "Bloodstone",
}

# Boss blinds by difficulty
HARD_BOSSES = {
    "The Needle", "The Flint", "The Manacle", "The Serpent", "The Pillar",
}
EASY_BOSSES = {
    "The Hook", "The Tooth", "The Wall", "The House", "The Mark",
    "The Fish", "The Water", "The Window",
}

# Valuable vouchers
GOOD_VOUCHERS = {
    "Hone", "Grabber", "Wasteful", "Overstock", "Crystal Ball",
    "Reroll Surplus", "Seed Money",
}

# Balatro seed charset
SEED_CHARS = "123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"  # No O or 0


def random_seed(rng: random.Random = None) -> str:
    """Generate a random valid Balatro seed (8 chars)."""
    r = rng or random.Random()
    return "".join(r.choice(SEED_CHARS) for _ in range(8))


@dataclass
class SeedScore:
    seed: str
    total_score: float
    tier: str  # S, A, B, C
    details: dict

    def __repr__(self):
        return f"{self.seed} [{self.tier}] score={self.total_score:.1f}"


def analyze_seed(seed: str) -> SeedScore:
    """Analyze a seed's quality based on early-game shop content.

    Simulates shops for Ante 1-3 (Small + Big + Boss = 9 shops)
    and scores based on joker quality, xMult availability, etc.
    """
    rng = RNGState(seed)
    score = 0.0
    details = {
        "jokers_seen": [],
        "best_joker": None,
        "xmult_count": 0,
        "s_tier_count": 0,
        "a_tier_count": 0,
        "vouchers": [],
    }

    owned_jokers = set()
    owned_vouchers = set()

    # Simulate 9 shops (3 antes × 3 blinds)
    for ante in range(1, 4):
        for blind in range(3):  # small, big, boss
            shop = generate_shop(
                rng, ante=ante,
                owned_joker_keys=owned_jokers,
                owned_vouchers=owned_vouchers,
            )

            for item in shop.card_slots:
                if hasattr(item, 'joker_def'):
                    name = item.joker_def.name
                    details["jokers_seen"].append(name)

                    if name in S_PLUS_JOKERS:
                        score += 15
                        details["s_tier_count"] += 1
                    elif name in S_TIER_JOKERS:
                        score += 10
                        details["s_tier_count"] += 1
                    elif name in A_TIER_JOKERS:
                        score += 5
                        details["a_tier_count"] += 1
                    else:
                        score += 1

                    if name in XMULT_JOKERS:
                        details["xmult_count"] += 1

                    # Early xMult is extra valuable
                    if name in XMULT_JOKERS and ante <= 2:
                        score += 5

            if shop.voucher:
                details["vouchers"].append(shop.voucher.name)
                if shop.voucher.name in GOOD_VOUCHERS:
                    score += 3

    # Bonus for xMult diversity
    if details["xmult_count"] >= 2:
        score += 10
    elif details["xmult_count"] >= 1:
        score += 3

    # Bonus for S-tier density
    if details["s_tier_count"] >= 3:
        score += 10

    # Determine tier
    if score >= 60:
        tier = "S"
    elif score >= 40:
        tier = "A"
    elif score >= 25:
        tier = "B"
    else:
        tier = "C"

    details["best_joker"] = max(
        details["jokers_seen"],
        key=lambda j: (j in S_PLUS_JOKERS) * 3 + (j in S_TIER_JOKERS) * 2 + (j in A_TIER_JOKERS),
        default=None,
    )

    return SeedScore(seed=seed, total_score=score, tier=tier, details=details)


def build_seed_set(
    count: int = 12,
    target_tier: str = "A",
    scan_size: int = 2000,
    seed_rng_seed: int = 42,
) -> list[SeedScore]:
    """Scan many seeds and select the best ones matching target tier.

    Args:
        count: Number of seeds to select
        target_tier: Target quality tier (S, A, B, C)
        scan_size: How many seeds to scan
        seed_rng_seed: Random seed for reproducibility
    """
    rng = random.Random(seed_rng_seed)
    results = []

    for i in range(scan_size):
        seed = random_seed(rng)
        score = analyze_seed(seed)
        results.append(score)

    # Sort by score descending
    results.sort(key=lambda s: s.total_score, reverse=True)

    # Filter by target tier
    tier_seeds = [s for s in results if s.tier == target_tier]

    # If not enough in target tier, expand to adjacent
    if len(tier_seeds) < count:
        tier_seeds = results[:count * 2]

    # Select evenly from the tier (not just top — want diversity)
    step = max(1, len(tier_seeds) // count)
    selected = tier_seeds[::step][:count]

    return selected


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Balatro seed quality analyzer")
    parser.add_argument("--scan", type=int, default=2000, help="Seeds to scan")
    parser.add_argument("--select", type=int, default=12, help="Seeds to select")
    parser.add_argument("--tier", default="A", help="Target tier (S/A/B/C)")
    parser.add_argument("--rng-seed", type=int, default=42, help="RNG seed")
    parser.add_argument("--analyze", type=str, help="Analyze a single seed")
    args = parser.parse_args()

    if args.analyze:
        result = analyze_seed(args.analyze)
        print(f"\nSeed: {result.seed}")
        print(f"Tier: {result.tier} (score: {result.total_score:.1f})")
        print(f"xMult jokers seen: {result.details['xmult_count']}")
        print(f"S-tier jokers: {result.details['s_tier_count']}")
        print(f"A-tier jokers: {result.details['a_tier_count']}")
        print(f"Best joker: {result.details['best_joker']}")
        print(f"Vouchers: {', '.join(result.details['vouchers'])}")
        print(f"All jokers: {', '.join(result.details['jokers_seen'])}")
        sys.exit(0)

    print(f"Scanning {args.scan} seeds...")
    selected = build_seed_set(
        count=args.select,
        target_tier=args.tier,
        scan_size=args.scan,
        seed_rng_seed=args.rng_seed,
    )

    # Distribution stats
    all_results = []
    rng = random.Random(args.rng_seed)
    for _ in range(args.scan):
        seed = random_seed(rng)
        all_results.append(analyze_seed(seed))

    tiers = {"S": 0, "A": 0, "B": 0, "C": 0}
    for r in all_results:
        tiers[r.tier] += 1

    print(f"\nDistribution ({args.scan} seeds):")
    for t in ["S", "A", "B", "C"]:
        pct = tiers[t] / args.scan * 100
        print(f"  {t}: {tiers[t]} ({pct:.1f}%)")

    print(f"\nSelected {len(selected)} {args.tier}-tier seeds:")
    for s in selected:
        xm = s.details["xmult_count"]
        st = s.details["s_tier_count"]
        best = s.details["best_joker"]
        print(f"  {s.seed}  score={s.total_score:.0f}  xMult={xm}  S-tier={st}  best={best}")

    print(f"\nSeed list (copy-paste):")
    print(",".join(s.seed for s in selected))
