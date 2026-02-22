"""Analyze a seed's shop content for Ante 1-3.

Usage: python3 analyze_seed_shops.py <SEED>
Output: JSON with shop items per ante/blind
"""
import json
import sys
import os

# Add simulator to path
sys.path.insert(0, os.path.dirname(__file__))

from balatro_sim.rng import RNGState
from balatro_sim.shop import generate_shop
from seed_analyzer import S_PLUS_JOKERS, S_TIER_JOKERS, A_TIER_JOKERS, XMULT_JOKERS, GOOD_VOUCHERS


def get_joker_tier(name: str) -> str:
    if name in S_PLUS_JOKERS:
        return "S+"
    if name in S_TIER_JOKERS:
        return "S"
    if name in A_TIER_JOKERS:
        return "A"
    return "B"


def analyze_seed_shops(seed: str) -> dict:
    rng = RNGState(seed)
    result = {"seed": seed, "antes": []}
    all_jokers = []

    for ante in range(1, 4):
        ante_data = {"ante": ante, "shops": []}
        for blind_idx, blind_name in enumerate(["Small", "Big", "Boss"]):
            shop = generate_shop(rng, ante=ante, owned_joker_keys=set(), owned_vouchers=set())
            shop_data = {"blind": blind_name, "items": [], "voucher": None, "packs": []}

            for item in shop.card_slots:
                if hasattr(item, 'joker_def'):
                    jd = item.joker_def
                    tier = get_joker_tier(jd.name)
                    is_xmult = jd.name in XMULT_JOKERS
                    entry = {
                        "type": "joker",
                        "name": jd.name,
                        "rarity": jd.rarity.name.lower(),
                        "cost": item.cost,
                        "edition": item.edition or "base",
                        "tier": tier,
                        "xmult": is_xmult,
                    }
                    shop_data["items"].append(entry)
                    all_jokers.append(entry)
                elif hasattr(item, 'name'):
                    shop_data["items"].append({
                        "type": "consumable",
                        "name": item.name,
                        "cost": getattr(item, 'cost', 0),
                    })

            if shop.voucher:
                is_good = shop.voucher.name in GOOD_VOUCHERS
                shop_data["voucher"] = {
                    "name": shop.voucher.name,
                    "valuable": is_good,
                }

            for pack in (shop.packs or []):
                shop_data["packs"].append({
                    "name": getattr(pack, 'name', str(pack)),
                })

            ante_data["shops"].append(shop_data)
        result["antes"].append(ante_data)

    # Summary
    xmult_jokers = [j for j in all_jokers if j["xmult"]]
    high_tier = [j for j in all_jokers if j["tier"] in ("S+", "S")]
    result["summary"] = {
        "total_jokers": len(all_jokers),
        "xmult_jokers": [j["name"] for j in xmult_jokers],
        "high_tier_jokers": [j["name"] for j in high_tier],
        "suggested_builds": _suggest_builds(all_jokers),
    }
    return result


def _suggest_builds(jokers: list[dict]) -> list[str]:
    """Suggest possible build paths based on available jokers."""
    names = {j["name"] for j in jokers}
    builds = []

    # xMult scaling
    if names & {"Hologram", "Steel Joker", "Glass Joker"}:
        builds.append("🔮 Steel/Glass xMult 路线")
    if names & {"Obelisk", "Lucky Cat", "Campfire"}:
        builds.append("📈 Scaling xMult 路线")

    # Specific combos
    if "Blueprint" in names or "Brainstorm" in names:
        builds.append("🧬 复制效果路线 (Blueprint/Brainstorm)")
    if names & {"Fibonacci", "Blackboard"}:
        builds.append("🎯 条件 xMult 路线")
    if names & {"Baron", "The Idol", "Photograph"}:
        builds.append("🃏 特定牌型 xMult 路线")

    # Retrigger
    if names & {"Hack", "Dusk", "Mime"}:
        builds.append("🔁 重触发路线")

    # Hand enablers
    if names & {"Smeared Joker", "Four Fingers", "Shortcut"}:
        builds.append("🖐️ 牌型扩展路线")

    # Economy
    if names & {"Vampire", "DNA"}:
        builds.append("💰 高价值稀有路线")

    if not builds:
        builds.append("🎲 无明显 combo 路线，需要灵活应对")

    return builds


if __name__ == "__main__":
    seed = sys.argv[1] if len(sys.argv) > 1 else "4662U3KL"
    result = analyze_seed_shops(seed)
    print(json.dumps(result, ensure_ascii=False, indent=2))
