"""Shop generation — item spawning, pricing, editions, packs.

Simulates Balatro's shop mechanics:
- 2 card slots (jokers/consumables) + 1 voucher + 2 booster packs
- Rarity-weighted joker selection
- Edition rolls (Foil/Holo/Polychrome)
- Reroll mechanics with cost tracking
- Booster pack types and contents
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .rng import RNGState
from .enums import Edition, Suit, Rank
from .data import (
    Rarity, RARITY_WEIGHTS, JokerDef,
    JOKER_CATALOG, JOKERS_BY_RARITY,
)


# ---------------------------------------------------------------------------
# Shop item types
# ---------------------------------------------------------------------------

@dataclass
class ShopJoker:
    """A joker available in the shop."""
    joker_def: JokerDef
    edition: Edition
    cost: int
    eternal: bool = False
    perishable: bool = False
    rental: bool = False

    @property
    def name(self) -> str:
        return self.joker_def.name

    @property
    def key(self) -> str:
        return self.joker_def.key


@dataclass
class ShopConsumable:
    """A tarot/planet/spectral card in the shop."""
    key: str
    name: str
    card_type: str  # 'Tarot', 'Planet', 'Spectral'
    cost: int


@dataclass
class ShopVoucher:
    """A voucher available in the shop."""
    key: str
    name: str
    cost: int = 10


@dataclass
class ShopPack:
    """A booster pack in the shop."""
    key: str
    name: str
    pack_type: str  # 'Arcana', 'Celestial', 'Buffoon', 'Standard', 'Spectral'
    size: str       # 'normal', 'jumbo', 'mega'
    cost: int


# ---------------------------------------------------------------------------
# Consumable catalogs
# ---------------------------------------------------------------------------

TAROT_CARDS = [
    ("c_fool", "The Fool", 3),
    ("c_magician", "The Magician", 3),
    ("c_high_priestess", "The High Priestess", 3),
    ("c_empress", "The Empress", 3),
    ("c_emperor", "The Emperor", 3),
    ("c_hierophant", "The Hierophant", 3),
    ("c_lovers", "The Lovers", 3),
    ("c_chariot", "The Chariot", 3),
    ("c_justice", "Justice", 3),
    ("c_hermit", "The Hermit", 3),
    ("c_wheel_of_fortune", "The Wheel of Fortune", 3),
    ("c_strength", "Strength", 3),
    ("c_hanged_man", "The Hanged Man", 3),
    ("c_death", "Death", 3),
    ("c_temperance", "Temperance", 3),
    ("c_devil", "The Devil", 3),
    ("c_tower", "The Tower", 3),
    ("c_star", "The Star", 3),
    ("c_moon", "The Moon", 3),
    ("c_sun", "The Sun", 3),
    ("c_judgement", "Judgement", 3),
    ("c_world", "The World", 3),
]

PLANET_CARDS = [
    ("c_mercury", "Mercury", 3),   # Pair
    ("c_venus", "Venus", 3),       # Three of a Kind
    ("c_earth", "Earth", 4),       # Full House
    ("c_mars", "Mars", 4),         # Four of a Kind
    ("c_jupiter", "Jupiter", 3),   # Flush
    ("c_saturn", "Saturn", 3),     # Straight
    ("c_uranus", "Uranus", 3),     # Two Pair
    ("c_neptune", "Neptune", 4),   # Straight Flush
    ("c_pluto", "Pluto", 3),       # High Card
]

SPECTRAL_CARDS = [
    ("c_familiar", "Familiar", 4),
    ("c_grim", "Grim", 4),
    ("c_incantation", "Incantation", 4),
    ("c_talisman", "Talisman", 4),
    ("c_aura", "Aura", 4),
    ("c_wraith", "Wraith", 4),
    ("c_sigil", "Sigil", 4),
    ("c_ouija", "Ouija", 4),
    ("c_ectoplasm", "Ectoplasm", 4),
    ("c_immolate", "Immolate", 4),
    ("c_ankh", "Ankh", 4),
    ("c_deja_vu", "Deja Vu", 4),
    ("c_hex", "Hex", 4),
    ("c_trance", "Trance", 4),
    ("c_medium", "Medium", 4),
    ("c_cryptid", "Cryptid", 4),
    ("c_soul", "The Soul", 4),
    ("c_black_hole", "Black Hole", 4),
]

# ---------------------------------------------------------------------------
# Voucher catalog
# ---------------------------------------------------------------------------

VOUCHERS = [
    # Tier 1
    ("v_overstock_norm", "Overstock", 10),
    ("v_clearance_sale", "Clearance Sale", 10),
    ("v_hone", "Hone", 10),
    ("v_reroll_surplus", "Reroll Surplus", 10),
    ("v_crystal_ball", "Crystal Ball", 10),
    ("v_telescope", "Telescope", 10),
    ("v_grabber", "Grabber", 10),
    ("v_wasteful", "Wasteful", 10),
    ("v_seed_money", "Seed Money", 10),
    ("v_blank", "Blank", 10),
    ("v_magic_trick", "Magic Trick", 10),
    ("v_hieroglyph", "Hieroglyph", 10),
    ("v_directors_cut", "Director's Cut", 10),
    ("v_paint_brush", "Paint Brush", 10),
    # Tier 2 (unlocked by tier 1)
    ("v_overstock_plus", "Overstock Plus", 10),
    ("v_liquidation", "Liquidation", 10),
    ("v_glow_up", "Glow Up", 10),
    ("v_reroll_glut", "Reroll Glut", 10),
    ("v_omen_globe", "Omen Globe", 10),
    ("v_observatory", "Observatory", 10),
    ("v_nacho_tong", "Nacho Tong", 10),
    ("v_recyclomancy", "Recyclomancy", 10),
    ("v_money_tree", "Money Tree", 10),
    ("v_antimatter", "Antimatter", 10),
    ("v_illusion", "Illusion", 10),
    ("v_petroglyph", "Petroglyph", 10),
    ("v_retcon", "Retcon", 10),
    ("v_palette", "Palette", 10),
]

# ---------------------------------------------------------------------------
# Booster pack catalog
# ---------------------------------------------------------------------------

BOOSTER_PACKS = [
    # Arcana (Tarot)
    ("p_arcana_normal", "Arcana Pack", "Arcana", "normal", 4),
    ("p_arcana_jumbo", "Jumbo Arcana Pack", "Arcana", "jumbo", 6),
    ("p_arcana_mega", "Mega Arcana Pack", "Arcana", "mega", 8),
    # Celestial (Planet)
    ("p_celestial_normal", "Celestial Pack", "Celestial", "normal", 4),
    ("p_celestial_jumbo", "Jumbo Celestial Pack", "Celestial", "jumbo", 6),
    ("p_celestial_mega", "Mega Celestial Pack", "Celestial", "mega", 8),
    # Buffoon (Joker)
    ("p_buffoon_normal", "Buffoon Pack", "Buffoon", "normal", 4),
    ("p_buffoon_jumbo", "Jumbo Buffoon Pack", "Buffoon", "jumbo", 6),
    ("p_buffoon_mega", "Mega Buffoon Pack", "Buffoon", "mega", 8),
    # Standard (Playing cards)
    ("p_standard_normal", "Standard Pack", "Standard", "normal", 4),
    ("p_standard_jumbo", "Jumbo Standard Pack", "Standard", "jumbo", 6),
    ("p_standard_mega", "Mega Standard Pack", "Standard", "mega", 8),
    # Spectral
    ("p_spectral_normal", "Spectral Pack", "Spectral", "normal", 4),
    ("p_spectral_jumbo", "Jumbo Spectral Pack", "Spectral", "jumbo", 6),
    ("p_spectral_mega", "Mega Spectral Pack", "Spectral", "mega", 8),
]

# Pack weights by ante (approximate — Spectral is rare early)
PACK_WEIGHTS = {
    "Arcana": 4,
    "Celestial": 4,
    "Buffoon": 2,
    "Standard": 3,
    "Spectral": 1,
}

# Size weights
PACK_SIZE_WEIGHTS = {
    "normal": 6,
    "jumbo": 3,
    "mega": 1,
}


# ---------------------------------------------------------------------------
# Edition probabilities
# ---------------------------------------------------------------------------

# Base edition chances (before vouchers)
EDITION_CHANCES = {
    Edition.FOIL: 0.04,        # +50 Chips
    Edition.HOLOGRAPHIC: 0.02,  # +10 Mult
    Edition.POLYCHROME: 0.006,  # x1.5 Mult
    # Edition.NEGATIVE: 0.003,  # Only from special sources
}


# ---------------------------------------------------------------------------
# Shop generator
# ---------------------------------------------------------------------------

@dataclass
class ShopState:
    """Current shop contents and state."""
    card_slots: list  # ShopJoker or ShopConsumable
    voucher: Optional[ShopVoucher]
    packs: list[ShopPack]
    reroll_cost: int = 5
    free_rerolls: int = 0

    @property
    def all_items(self) -> list:
        items = list(self.card_slots)
        if self.voucher:
            items.append(self.voucher)
        items.extend(self.packs)
        return items


def _roll_edition(rng: RNGState, key_suffix: str = "") -> Edition:
    """Roll for a card edition (Foil/Holo/Polychrome/None)."""
    roll = rng.pseudoseed(f"edition_generic{key_suffix}")
    cumulative = 0.0
    for edition, chance in EDITION_CHANCES.items():
        cumulative += chance
        if roll < cumulative:
            return edition
    return Edition.NONE


def _roll_rarity(rng: RNGState) -> Rarity:
    """Roll joker rarity based on standard weights."""
    roll = rng.pseudoseed("shop_joker_rarity")
    cumulative = 0.0
    for rarity, weight in RARITY_WEIGHTS.items():
        cumulative += weight
        if roll < cumulative:
            return rarity
    return Rarity.COMMON


def _generate_joker(rng: RNGState, owned_joker_keys: set[str],
                    ante: int) -> ShopJoker:
    """Generate a random joker for the shop."""
    rarity = _roll_rarity(rng)

    # Pick from available jokers of this rarity
    pool = [j for j in JOKERS_BY_RARITY.get(rarity, [])
            if j.key not in owned_joker_keys]
    if not pool:
        pool = JOKERS_BY_RARITY.get(rarity, JOKERS_BY_RARITY[Rarity.COMMON])

    joker_def = rng.random_element(f"Joker{rarity.value}", pool)

    # Edition roll
    edition = _roll_edition(rng, f"_shop_j")

    # Cost: base_cost * edition multiplier
    cost = joker_def.base_cost
    if edition == Edition.FOIL:
        cost += 2
    elif edition == Edition.HOLOGRAPHIC:
        cost += 3
    elif edition == Edition.POLYCHROME:
        cost += 5

    return ShopJoker(joker_def=joker_def, edition=edition, cost=cost)


def _generate_consumable(rng: RNGState, ante: int) -> ShopConsumable:
    """Generate a random tarot or planet card for the shop."""
    # 60% tarot, 40% planet (approximate)
    roll = rng.pseudoseed("shop_consumable_type")
    if roll < 0.6:
        key, name, cost = rng.random_element("Tarot", TAROT_CARDS)
        return ShopConsumable(key=key, name=name, card_type="Tarot", cost=cost)
    else:
        key, name, cost = rng.random_element("Planet", PLANET_CARDS)
        return ShopConsumable(key=key, name=name, card_type="Planet", cost=cost)


def _generate_voucher(rng: RNGState, owned_vouchers: set[str],
                      ante: int) -> Optional[ShopVoucher]:
    """Generate the voucher for this shop visit."""
    # Filter to unowned vouchers
    available = [(k, n, c) for k, n, c in VOUCHERS if k not in owned_vouchers]
    if not available:
        return None

    key, name, cost = rng.random_element("Voucher", available)
    return ShopVoucher(key=key, name=name, cost=cost)


def _generate_pack(rng: RNGState) -> ShopPack:
    """Generate a random booster pack."""
    # Pick pack type by weight
    types = list(PACK_WEIGHTS.keys())
    weights = [PACK_WEIGHTS[t] for t in types]
    total = sum(weights)

    roll = rng.pseudoseed("shop_pack") * total
    cumulative = 0.0
    pack_type = types[0]
    for t, w in zip(types, weights):
        cumulative += w
        if roll < cumulative:
            pack_type = t
            break

    # Pick size by weight
    sizes = list(PACK_SIZE_WEIGHTS.keys())
    size_weights = [PACK_SIZE_WEIGHTS[s] for s in sizes]
    total_s = sum(size_weights)

    roll_s = rng.pseudoseed("shop_pack_size") * total_s
    cumulative_s = 0.0
    size = sizes[0]
    for s, w in zip(sizes, size_weights):
        cumulative_s += w
        if roll_s < cumulative_s:
            size = s
            break

    # Find matching pack
    for pk, pn, pt, ps, pc in BOOSTER_PACKS:
        if pt == pack_type and ps == size:
            return ShopPack(key=pk, name=pn, pack_type=pack_type,
                            size=size, cost=pc)

    # Fallback
    return ShopPack(key="p_arcana_normal", name="Arcana Pack",
                    pack_type="Arcana", size="normal", cost=4)


def generate_shop(
    rng: RNGState,
    ante: int,
    owned_joker_keys: set[str],
    owned_vouchers: set[str],
    num_card_slots: int = 2,
    num_pack_slots: int = 2,
) -> ShopState:
    """Generate a complete shop for the current round.

    Args:
        rng: RNG state (will be advanced)
        ante: Current ante number
        owned_joker_keys: Keys of jokers already owned (for dedup)
        owned_vouchers: Keys of vouchers already purchased
        num_card_slots: Number of card slots (default 2, +1 with Overstock)
        num_pack_slots: Number of pack slots (default 2)

    Returns:
        ShopState with all generated items
    """
    card_slots = []
    for i in range(num_card_slots):
        # ~70% chance joker, ~30% chance consumable
        roll = rng.pseudoseed(f"shop_slot_{i}")
        if roll < 0.7:
            card_slots.append(_generate_joker(rng, owned_joker_keys, ante))
        else:
            card_slots.append(_generate_consumable(rng, ante))

    voucher = _generate_voucher(rng, owned_vouchers, ante)

    packs = [_generate_pack(rng) for _ in range(num_pack_slots)]

    return ShopState(
        card_slots=card_slots,
        voucher=voucher,
        packs=packs,
        reroll_cost=5,
        free_rerolls=0,
    )


def reroll_shop(
    rng: RNGState,
    shop: ShopState,
    ante: int,
    owned_joker_keys: set[str],
    dollars: int,
) -> tuple[ShopState, int]:
    """Reroll the shop card slots (not voucher/packs).

    Returns (new_shop_state, cost_paid).
    Raises ValueError if can't afford.
    """
    cost = max(0, shop.reroll_cost - shop.free_rerolls)
    if dollars < cost:
        raise ValueError(f"Can't afford reroll: need ${cost}, have ${dollars}")

    # Regenerate card slots only
    new_slots = []
    for i in range(len(shop.card_slots)):
        roll = rng.pseudoseed(f"reroll_slot_{i}")
        if roll < 0.7:
            new_slots.append(_generate_joker(rng, owned_joker_keys, ante))
        else:
            new_slots.append(_generate_consumable(rng, ante))

    new_shop = ShopState(
        card_slots=new_slots,
        voucher=shop.voucher,
        packs=shop.packs,
        reroll_cost=shop.reroll_cost,
        free_rerolls=max(0, shop.free_rerolls - 1),
    )
    return new_shop, cost
