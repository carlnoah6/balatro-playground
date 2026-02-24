"""Shop generation — precise port of Balatro's shop RNG.

Mirrors the exact RNG call sequence from:
- create_card_for_shop()  (UI_definitions.lua:742)
- create_card()           (common_events.lua:2082)
- get_current_pool()      (common_events.lua:1963)
- poll_edition()          (common_events.lua:2055)
- get_pack()              (common_events.lua:1944)
- get_next_voucher_key()  (common_events.lua:1901)
- reroll_shop()           (button_callbacks.lua:2855)
- calculate_reroll_cost() (common_events.lua:2263)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .rng import RNGState
from .enums import Edition


# ---------------------------------------------------------------------------
# Rarity thresholds (from get_current_pool, line 1969)
# ---------------------------------------------------------------------------
# rarity = (rarity > 0.95 and 3) or (rarity > 0.7 and 2) or 1

RARITY_COMMON = 1
RARITY_UNCOMMON = 2
RARITY_RARE = 3
RARITY_LEGENDARY = 4


# ---------------------------------------------------------------------------
# Joker catalog — (key, name, rarity, cost, order)
# Extracted from game.lua, sorted by order (= sort_id for pool ordering)
# ---------------------------------------------------------------------------

_JOKER_RAW: list[tuple[str, str, int, int, int]] = [
    ("j_joker", "Joker", 1, 2, 1),
    ("j_greedy_joker", "Greedy Joker", 1, 5, 2),
    ("j_lusty_joker", "Lusty Joker", 1, 5, 3),
    ("j_wrathful_joker", "Wrathful Joker", 1, 5, 4),
    ("j_gluttenous_joker", "Gluttonous Joker", 1, 5, 5),
    ("j_jolly", "Jolly Joker", 1, 3, 6),
    ("j_zany", "Zany Joker", 1, 4, 7),
    ("j_mad", "Mad Joker", 1, 4, 8),
    ("j_crazy", "Crazy Joker", 1, 4, 9),
    ("j_droll", "Droll Joker", 1, 4, 10),
    ("j_sly", "Sly Joker", 1, 3, 11),
    ("j_wily", "Wily Joker", 1, 4, 12),
    ("j_clever", "Clever Joker", 1, 4, 13),
    ("j_devious", "Devious Joker", 1, 4, 14),
    ("j_crafty", "Crafty Joker", 1, 4, 15),
    ("j_half", "Half Joker", 1, 5, 16),
    ("j_stencil", "Joker Stencil", 2, 8, 17),
    ("j_four_fingers", "Four Fingers", 2, 7, 18),
    ("j_mime", "Mime", 2, 5, 19),
    ("j_credit_card", "Credit Card", 1, 1, 20),
    ("j_ceremonial", "Ceremonial Dagger", 2, 6, 21),
    ("j_banner", "Banner", 1, 5, 22),
    ("j_mystic_summit", "Mystic Summit", 1, 5, 23),
    ("j_marble", "Marble Joker", 2, 6, 24),
    ("j_loyalty_card", "Loyalty Card", 2, 5, 25),
    ("j_8_ball", "8 Ball", 1, 5, 26),
    ("j_misprint", "Misprint", 1, 4, 27),
    ("j_dusk", "Dusk", 2, 5, 28),
    ("j_raised_fist", "Raised Fist", 1, 5, 29),
    ("j_chaos", "Chaos the Clown", 1, 4, 30),
    ("j_fibonacci", "Fibonacci", 2, 8, 31),
    ("j_steel_joker", "Steel Joker", 2, 7, 32),
    ("j_scary_face", "Scary Face", 1, 4, 33),
    ("j_abstract", "Abstract Joker", 1, 4, 34),
    ("j_delayed_grat", "Delayed Gratification", 1, 4, 35),
    ("j_hack", "Hack", 2, 6, 36),
    ("j_pareidolia", "Pareidolia", 2, 5, 37),
    ("j_gros_michel", "Gros Michel", 1, 5, 38),
    ("j_even_steven", "Even Steven", 1, 4, 39),
    ("j_odd_todd", "Odd Todd", 1, 4, 40),
    ("j_scholar", "Scholar", 1, 4, 41),
    ("j_business", "Business Card", 1, 4, 42),
    ("j_supernova", "Supernova", 1, 5, 43),
    ("j_ride_the_bus", "Ride the Bus", 1, 6, 44),
    ("j_space", "Space Joker", 2, 5, 45),
    ("j_egg", "Egg", 1, 4, 46),
    ("j_burglar", "Burglar", 2, 6, 47),
    ("j_blackboard", "Blackboard", 2, 6, 48),
    ("j_runner", "Runner", 1, 5, 49),
    ("j_ice_cream", "Ice Cream", 1, 5, 50),
    ("j_dna", "DNA", 3, 8, 51),
    ("j_splash", "Splash", 1, 3, 52),
    ("j_blue_joker", "Blue Joker", 1, 5, 53),
    ("j_sixth_sense", "Sixth Sense", 2, 6, 54),
    ("j_constellation", "Constellation", 2, 6, 55),
    ("j_hiker", "Hiker", 2, 5, 56),
    ("j_faceless", "Faceless Joker", 1, 4, 57),
    ("j_green_joker", "Green Joker", 1, 4, 58),
    ("j_superposition", "Superposition", 1, 4, 59),
    ("j_todo_list", "To Do List", 1, 4, 60),
    ("j_cavendish", "Cavendish", 1, 4, 61),
    ("j_card_sharp", "Card Sharp", 2, 6, 62),
    ("j_red_card", "Red Card", 1, 5, 63),
    ("j_madness", "Madness", 2, 7, 64),
    ("j_square", "Square Joker", 1, 4, 65),
    ("j_seance", "Séance", 2, 6, 66),
    ("j_riff_raff", "Riff-raff", 1, 5, 67),
    ("j_vampire", "Vampire", 2, 7, 68),
    ("j_shortcut", "Shortcut", 2, 7, 69),
    ("j_hologram", "Hologram", 2, 7, 70),
    ("j_vagabond", "Vagabond", 3, 7, 71),
    ("j_baron", "Baron", 3, 8, 72),
    ("j_cloud_9", "Cloud 9", 2, 7, 73),
    ("j_rocket", "Rocket", 2, 6, 74),
    ("j_obelisk", "Obelisk", 3, 7, 75),
    ("j_midas_mask", "Midas Mask", 2, 7, 76),
    ("j_luchador", "Luchador", 2, 5, 77),
    ("j_photograph", "Photograph", 1, 5, 78),
    ("j_gift", "Gift Card", 2, 6, 79),
    ("j_turtle_bean", "Turtle Bean", 2, 6, 80),
    ("j_erosion", "Erosion", 2, 6, 81),
    ("j_reserved_parking", "Reserved Parking", 1, 6, 82),
    ("j_mail", "Mail-In Rebate", 1, 4, 83),
    ("j_to_the_moon", "To the Moon", 2, 5, 84),
    ("j_hallucination", "Hallucination", 1, 4, 85),
    ("j_fortune_teller", "Fortune Teller", 1, 6, 86),
    ("j_juggler", "Juggler", 1, 3, 87),
    ("j_drunkard", "Drunkard", 1, 4, 88),
    ("j_stone", "Stone Joker", 2, 6, 89),
    ("j_golden", "Golden Joker", 1, 6, 90),
    ("j_lucky_cat", "Lucky Cat", 2, 6, 91),
    ("j_baseball", "Baseball Card", 3, 8, 92),
    ("j_bull", "Bull", 2, 6, 93),
    ("j_diet_cola", "Diet Cola", 2, 6, 94),
    ("j_trading", "Trading Card", 2, 5, 95),
    ("j_flash", "Flash Card", 2, 4, 96),
    ("j_popcorn", "Popcorn", 1, 5, 97),
    ("j_trousers", "Spare Trousers", 2, 6, 98),
    ("j_ancient", "Ancient Joker", 3, 8, 99),
    ("j_ramen", "Ramen", 2, 5, 100),
    ("j_walkie_talkie", "Walkie Talkie", 1, 4, 101),
    ("j_selzer", "Seltzer", 2, 6, 102),
    ("j_castle", "Castle", 2, 6, 103),
    ("j_smiley", "Smiley Face", 1, 4, 104),
    ("j_campfire", "Campfire", 3, 9, 105),
    ("j_ticket", "Golden Ticket", 1, 5, 106),
    ("j_mr_bones", "Mr. Bones", 2, 5, 107),
    ("j_acrobat", "Acrobat", 2, 6, 108),
    ("j_sock_and_buskin", "Sock and Buskin", 2, 6, 109),
    ("j_swashbuckler", "Swashbuckler", 1, 4, 110),
    ("j_troubadour", "Troubadour", 2, 6, 111),
    ("j_certificate", "Certificate", 2, 6, 112),
    ("j_smeared", "Smeared Joker", 2, 7, 113),
    ("j_throwback", "Throwback", 2, 6, 114),
    ("j_hanging_chad", "Hanging Chad", 1, 4, 115),
    ("j_rough_gem", "Rough Gem", 2, 7, 116),
    ("j_bloodstone", "Bloodstone", 2, 7, 117),
    ("j_arrowhead", "Arrowhead", 2, 7, 118),
    ("j_onyx_agate", "Onyx Agate", 2, 7, 119),
    ("j_glass", "Glass Joker", 2, 6, 120),
    ("j_ring_master", "Showman", 2, 5, 121),
    ("j_flower_pot", "Flower Pot", 2, 6, 122),
    ("j_blueprint", "Blueprint", 3, 10, 123),
    ("j_wee", "Wee Joker", 3, 8, 124),
    ("j_merry_andy", "Merry Andy", 2, 7, 125),
    ("j_oops", "Oops! All 6s", 2, 4, 126),
    ("j_idol", "The Idol", 2, 6, 127),
    ("j_seeing_double", "Seeing Double", 2, 6, 128),
    ("j_matador", "Matador", 2, 7, 129),
    ("j_hit_the_road", "Hit the Road", 3, 8, 130),
    ("j_duo", "The Duo", 3, 8, 131),
    ("j_trio", "The Trio", 3, 8, 132),
    ("j_family", "The Family", 3, 8, 133),
    ("j_order", "The Order", 3, 8, 134),
    ("j_tribe", "The Tribe", 3, 8, 135),
    ("j_stuntman", "Stuntman", 3, 7, 136),
    ("j_invisible", "Invisible Joker", 3, 8, 137),
    ("j_brainstorm", "Brainstorm", 3, 10, 138),
    ("j_satellite", "Satellite", 2, 6, 139),
    ("j_shoot_the_moon", "Shoot the Moon", 1, 5, 140),
    ("j_drivers_license", "Driver's License", 3, 7, 141),
    ("j_cartomancer", "Cartomancer", 2, 6, 142),
    ("j_astronomer", "Astronomer", 2, 8, 143),
    ("j_burnt", "Burnt Joker", 3, 5, 144),
    ("j_bootstraps", "Bootstraps", 2, 7, 145),
    ("j_canio", "Canio", 4, 20, 146),
    ("j_triboulet", "Triboulet", 4, 20, 147),
    ("j_yorick", "Yorick", 4, 20, 148),
    ("j_chicot", "Chicot", 4, 20, 149),
    ("j_perkeo", "Perkeo", 4, 20, 150),
]

# Build lookup structures
JOKER_BY_KEY: dict[str, tuple[str, str, int, int, int]] = {
    j[0]: j for j in _JOKER_RAW
}

# Jokers locked by default in Balatro 1.0.1o (unlocked = false in game.lua).
# These are excluded from the shop pool unless the player has unlocked them.
LOCKED_JOKERS_DEFAULT: set[str] = {
    # Common (4)
    "j_ticket", "j_swashbuckler", "j_hanging_chad", "j_shoot_the_moon",
    # Uncommon (23)
    "j_mr_bones", "j_acrobat", "j_sock_and_buskin", "j_troubadour",
    "j_certificate", "j_smeared", "j_throwback", "j_rough_gem",
    "j_bloodstone", "j_arrowhead", "j_onyx_agate", "j_glass",
    "j_ring_master", "j_flower_pot", "j_merry_andy", "j_oops",
    "j_idol", "j_seeing_double", "j_matador", "j_satellite",
    "j_cartomancer", "j_astronomer", "j_bootstraps",
    # Rare (13)
    "j_blueprint", "j_wee", "j_hit_the_road", "j_duo", "j_trio",
    "j_family", "j_order", "j_tribe", "j_stuntman", "j_invisible",
    "j_brainstorm", "j_drivers_license", "j_burnt",
    # Legendary (5) — excluded from random rarity anyway, but listed for completeness
    "j_caino", "j_triboulet", "j_yorick", "j_chicot", "j_perkeo",
}

JOKERS_BY_RARITY: dict[int, list[tuple[str, str, int, int, int]]] = {}
for _j in _JOKER_RAW:
    JOKERS_BY_RARITY.setdefault(_j[2], []).append(_j)
# Already sorted by order within each rarity group
for _r in JOKERS_BY_RARITY:
    JOKERS_BY_RARITY[_r].sort(key=lambda x: x[4])


# ---------------------------------------------------------------------------
# Consumable catalogs — (key, name, cost, order)
# Sorted by order to match Lua's pool ordering
# ---------------------------------------------------------------------------

TAROT_CARDS: list[tuple[str, str, int, int]] = [
    ("c_fool", "The Fool", 3, 1),
    ("c_magician", "The Magician", 3, 2),
    ("c_high_priestess", "The High Priestess", 3, 3),
    ("c_empress", "The Empress", 3, 4),
    ("c_emperor", "The Emperor", 3, 5),
    ("c_hierophant", "The Hierophant", 3, 6),
    ("c_lovers", "The Lovers", 3, 7),
    ("c_chariot", "The Chariot", 3, 8),
    ("c_justice", "Justice", 3, 9),
    ("c_hermit", "The Hermit", 3, 10),
    ("c_wheel_of_fortune", "The Wheel of Fortune", 3, 11),
    ("c_strength", "Strength", 3, 12),
    ("c_hanged_man", "The Hanged Man", 3, 13),
    ("c_death", "Death", 3, 14),
    ("c_temperance", "Temperance", 3, 15),
    ("c_devil", "The Devil", 3, 16),
    ("c_tower", "The Tower", 3, 17),
    ("c_star", "The Star", 3, 18),
    ("c_moon", "The Moon", 3, 19),
    ("c_sun", "The Sun", 3, 20),
    ("c_judgement", "Judgement", 3, 21),
    ("c_world", "The World", 3, 22),
]

PLANET_CARDS: list[tuple[str, str, int, int]] = [
    ("c_mercury", "Mercury", 3, 1),
    ("c_venus", "Venus", 3, 2),
    ("c_earth", "Earth", 4, 3),
    ("c_mars", "Mars", 4, 4),
    ("c_jupiter", "Jupiter", 3, 5),
    ("c_saturn", "Saturn", 3, 6),
    ("c_uranus", "Uranus", 3, 7),
    ("c_neptune", "Neptune", 4, 8),
    ("c_pluto", "Pluto", 3, 9),
    ("c_ceres", "Ceres", 3, 10),
    ("c_planet_x", "Planet X", 3, 11),
    ("c_eris", "Eris", 3, 12),
]

# Softlocked planets — only available if the corresponding hand type has been played.
# In practice, Five of a Kind / Flush House / Flush Five are rarely played in early antes.
SOFTLOCKED_PLANETS: set[str] = {"c_ceres", "c_planet_x", "c_eris"}

SPECTRAL_CARDS: list[tuple[str, str, int, int]] = [
    ("c_familiar", "Familiar", 4, 1),
    ("c_grim", "Grim", 4, 2),
    ("c_incantation", "Incantation", 4, 3),
    ("c_talisman", "Talisman", 4, 4),
    ("c_aura", "Aura", 4, 5),
    ("c_wraith", "Wraith", 4, 6),
    ("c_sigil", "Sigil", 4, 7),
    ("c_ouija", "Ouija", 4, 8),
    ("c_ectoplasm", "Ectoplasm", 4, 9),
    ("c_immolate", "Immolate", 4, 10),
    ("c_ankh", "Ankh", 4, 11),
    ("c_deja_vu", "Deja Vu", 4, 12),
    ("c_hex", "Hex", 4, 13),
    ("c_trance", "Trance", 4, 14),
    ("c_medium", "Medium", 4, 15),
    ("c_cryptid", "Cryptid", 4, 16),
    ("c_soul", "The Soul", 4, 17),
    ("c_black_hole", "Black Hole", 4, 18),
]

# Pool lookup by type name (matches Lua's G.P_CENTER_POOLS keys)
CONSUMABLE_POOLS: dict[str, list[tuple[str, str, int, int]]] = {
    "Tarot": TAROT_CARDS,
    "Planet": PLANET_CARDS,
    "Spectral": SPECTRAL_CARDS,
}


# ---------------------------------------------------------------------------
# Voucher catalog — (key, name, cost, order, requires)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VoucherDef:
    key: str
    name: str
    cost: int
    order: int
    requires: Optional[str] = None  # key of prerequisite voucher


VOUCHER_DEFS: list[VoucherDef] = [
    VoucherDef("v_overstock_norm", "Overstock", 10, 1),
    VoucherDef("v_overstock_plus", "Overstock Plus", 10, 2, "v_overstock_norm"),
    VoucherDef("v_clearance_sale", "Clearance Sale", 10, 3),
    VoucherDef("v_liquidation", "Liquidation", 10, 4, "v_clearance_sale"),
    VoucherDef("v_hone", "Hone", 10, 5),
    VoucherDef("v_glow_up", "Glow Up", 10, 6, "v_hone"),
    VoucherDef("v_reroll_surplus", "Reroll Surplus", 10, 7),
    VoucherDef("v_reroll_glut", "Reroll Glut", 10, 8, "v_reroll_surplus"),
    VoucherDef("v_crystal_ball", "Crystal Ball", 10, 9),
    VoucherDef("v_omen_globe", "Omen Globe", 10, 10, "v_crystal_ball"),
    VoucherDef("v_telescope", "Telescope", 10, 11),
    VoucherDef("v_observatory", "Observatory", 10, 12, "v_telescope"),
    VoucherDef("v_grabber", "Grabber", 10, 13),
    VoucherDef("v_nacho_tong", "Nacho Tong", 10, 14, "v_grabber"),
    VoucherDef("v_wasteful", "Wasteful", 10, 15),
    VoucherDef("v_recyclomancy", "Recyclomancy", 10, 16, "v_wasteful"),
    VoucherDef("v_tarot_merchant", "Tarot Merchant", 10, 17),
    VoucherDef("v_tarot_tycoon", "Tarot Tycoon", 10, 18, "v_tarot_merchant"),
    VoucherDef("v_planet_merchant", "Planet Merchant", 10, 19),
    VoucherDef("v_planet_tycoon", "Planet Tycoon", 10, 20, "v_planet_merchant"),
    VoucherDef("v_seed_money", "Seed Money", 10, 21),
    VoucherDef("v_money_tree", "Money Tree", 10, 22, "v_seed_money"),
    VoucherDef("v_blank", "Blank", 10, 23),
    VoucherDef("v_antimatter", "Antimatter", 10, 24, "v_blank"),
    VoucherDef("v_magic_trick", "Magic Trick", 10, 25),
    VoucherDef("v_illusion", "Illusion", 10, 26, "v_magic_trick"),
    VoucherDef("v_hieroglyph", "Hieroglyph", 10, 27),
    VoucherDef("v_petroglyph", "Petroglyph", 10, 28, "v_hieroglyph"),
    VoucherDef("v_directors_cut", "Director's Cut", 10, 29),
    VoucherDef("v_retcon", "Retcon", 10, 30, "v_directors_cut"),
    VoucherDef("v_paint_brush", "Paint Brush", 10, 31),
    VoucherDef("v_palette", "Palette", 10, 32, "v_paint_brush"),
]

VOUCHER_BY_KEY: dict[str, VoucherDef] = {v.key: v for v in VOUCHER_DEFS}


# ---------------------------------------------------------------------------
# Booster pack catalog — (key, name, kind, cost, weight, order, extra, choose)
# From game.lua lines 665-697. Sorted by order.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PackDef:
    key: str
    name: str
    kind: str       # Arcana, Celestial, Spectral, Standard, Buffoon
    cost: int
    weight: float
    order: int
    extra: int      # cards shown
    choose: int     # cards to pick


PACK_DEFS: list[PackDef] = [
    PackDef("p_arcana_normal_1", "Arcana Pack", "Arcana", 4, 1, 1, 3, 1),
    PackDef("p_arcana_normal_2", "Arcana Pack", "Arcana", 4, 1, 2, 3, 1),
    PackDef("p_arcana_normal_3", "Arcana Pack", "Arcana", 4, 1, 3, 3, 1),
    PackDef("p_arcana_normal_4", "Arcana Pack", "Arcana", 4, 1, 4, 3, 1),
    PackDef("p_arcana_jumbo_1", "Jumbo Arcana Pack", "Arcana", 6, 1, 5, 5, 1),
    PackDef("p_arcana_jumbo_2", "Jumbo Arcana Pack", "Arcana", 6, 1, 6, 5, 1),
    PackDef("p_arcana_mega_1", "Mega Arcana Pack", "Arcana", 8, 0.25, 7, 5, 2),
    PackDef("p_arcana_mega_2", "Mega Arcana Pack", "Arcana", 8, 0.25, 8, 5, 2),
    PackDef("p_celestial_normal_1", "Celestial Pack", "Celestial", 4, 1, 9, 3, 1),
    PackDef("p_celestial_normal_2", "Celestial Pack", "Celestial", 4, 1, 10, 3, 1),
    PackDef("p_celestial_normal_3", "Celestial Pack", "Celestial", 4, 1, 11, 3, 1),
    PackDef("p_celestial_normal_4", "Celestial Pack", "Celestial", 4, 1, 12, 3, 1),
    PackDef("p_celestial_jumbo_1", "Jumbo Celestial Pack", "Celestial", 6, 1, 13, 5, 1),
    PackDef("p_celestial_jumbo_2", "Jumbo Celestial Pack", "Celestial", 6, 1, 14, 5, 1),
    PackDef("p_celestial_mega_1", "Mega Celestial Pack", "Celestial", 8, 0.25, 15, 5, 2),
    PackDef("p_celestial_mega_2", "Mega Celestial Pack", "Celestial", 8, 0.25, 16, 5, 2),
    PackDef("p_standard_normal_1", "Standard Pack", "Standard", 4, 1, 17, 3, 1),
    PackDef("p_standard_normal_2", "Standard Pack", "Standard", 4, 1, 18, 3, 1),
    PackDef("p_standard_normal_3", "Standard Pack", "Standard", 4, 1, 19, 3, 1),
    PackDef("p_standard_normal_4", "Standard Pack", "Standard", 4, 1, 20, 3, 1),
    PackDef("p_standard_jumbo_1", "Jumbo Standard Pack", "Standard", 6, 1, 21, 5, 1),
    PackDef("p_standard_jumbo_2", "Jumbo Standard Pack", "Standard", 6, 1, 22, 5, 1),
    PackDef("p_standard_mega_1", "Mega Standard Pack", "Standard", 8, 0.25, 23, 5, 2),
    PackDef("p_standard_mega_2", "Mega Standard Pack", "Standard", 8, 0.25, 24, 5, 2),
    PackDef("p_buffoon_normal_1", "Buffoon Pack", "Buffoon", 4, 0.6, 25, 2, 1),
    PackDef("p_buffoon_normal_2", "Buffoon Pack", "Buffoon", 4, 0.6, 26, 2, 1),
    PackDef("p_buffoon_jumbo_1", "Jumbo Buffoon Pack", "Buffoon", 6, 0.6, 27, 4, 1),
    PackDef("p_buffoon_mega_1", "Mega Buffoon Pack", "Buffoon", 8, 0.15, 28, 4, 2),
    PackDef("p_spectral_normal_1", "Spectral Pack", "Spectral", 4, 0.3, 29, 2, 1),
    PackDef("p_spectral_normal_2", "Spectral Pack", "Spectral", 4, 0.3, 30, 2, 1),
    PackDef("p_spectral_jumbo_1", "Jumbo Spectral Pack", "Spectral", 6, 0.3, 31, 4, 1),
    PackDef("p_spectral_mega_1", "Mega Spectral Pack", "Spectral", 8, 0.07, 32, 4, 2),
]

# Sorted by order for deterministic iteration
PACK_DEFS.sort(key=lambda p: p.order)


# ---------------------------------------------------------------------------
# Shop item types
# ---------------------------------------------------------------------------

@dataclass
class ShopJoker:
    key: str
    name: str
    rarity: int
    edition: Edition
    cost: int
    eternal: bool = False
    perishable: bool = False
    rental: bool = False


@dataclass
class ShopConsumable:
    key: str
    name: str
    card_type: str  # 'Tarot', 'Planet', 'Spectral'
    cost: int


@dataclass
class ShopVoucher:
    key: str
    name: str
    cost: int = 10


@dataclass
class ShopPack:
    key: str
    name: str
    kind: str
    cost: int
    extra: int = 3
    choose: int = 1


@dataclass
class ShopState:
    card_slots: list  # ShopJoker | ShopConsumable
    voucher: Optional[ShopVoucher]
    packs: list[ShopPack]
    reroll_cost: int = 5
    free_rerolls: int = 0
    reroll_cost_increase: int = 0

    @property
    def all_items(self) -> list:
        items = list(self.card_slots)
        if self.voucher:
            items.append(self.voucher)
        items.extend(self.packs)
        return items


# ---------------------------------------------------------------------------
# Game config — mirrors G.GAME defaults
# ---------------------------------------------------------------------------

@dataclass
class ShopConfig:
    """Game-level config that affects shop generation."""
    joker_rate: float = 20.0
    tarot_rate: float = 4.0
    planet_rate: float = 4.0
    playing_card_rate: float = 0.0
    spectral_rate: float = 0.0
    edition_rate: float = 1.0
    joker_max: int = 2
    # Modifiers
    enable_eternals_in_shop: bool = False
    enable_perishables_in_shop: bool = False
    enable_rentals_in_shop: bool = False
    all_eternal: bool = False
    # Voucher effects
    has_illusion: bool = False
    # Tracking
    first_shop_buffoon: bool = False
    # Banned keys
    banned_keys: set = field(default_factory=set)
    # Used jokers (for pool culling — keys of jokers ever owned)
    used_jokers: dict = field(default_factory=dict)
    # Used vouchers (redeemed)
    used_vouchers: dict = field(default_factory=dict)
    # Has Showman joker (allows duplicates)
    has_showman: bool = False
    # Pool flags
    pool_flags: dict = field(default_factory=dict)
    # Locked jokers — excluded from pool. Default = LOCKED_JOKERS_DEFAULT.
    locked_jokers: set = field(default_factory=lambda: set(LOCKED_JOKERS_DEFAULT))
    # Played hand types — planets with softlock only appear if hand was played.
    # Default empty = softlocked planets excluded.
    played_hands: set = field(default_factory=set)


# ---------------------------------------------------------------------------
# Pool construction — precise port of get_current_pool()
# ---------------------------------------------------------------------------

def _build_pool(
    pool_type: str,
    rarity: Optional[int],
    config: ShopConfig,
    ante: int,
    append: str = "",
    legendary: bool = False,
) -> tuple[list[str], str]:
    """Build the item pool, matching get_current_pool() exactly.

    Returns (pool, pool_key) where pool contains keys or 'UNAVAILABLE'.
    The UNAVAILABLE entries are critical for RNG determinism.
    """
    pool: list[str] = []
    pool_size = 0

    if pool_type == "Joker":
        # Rarity is already determined by caller
        r = rarity or RARITY_COMMON
        if legendary:
            r = RARITY_LEGENDARY
        starting_pool = JOKERS_BY_RARITY.get(r, [])
        pool_key = f"Joker{r}" + ((not legendary and append) or "")
    elif pool_type == "Voucher":
        starting_pool = VOUCHER_DEFS
        pool_key = "Voucher" + (append or "")
    elif pool_type in ("Tarot", "Planet", "Spectral"):
        starting_pool = CONSUMABLE_POOLS.get(pool_type, [])
        pool_key = pool_type + (append or "")
    elif pool_type == "Tarot_Planet":
        starting_pool = TAROT_CARDS + PLANET_CARDS
        pool_key = "Tarot_Planet" + (append or "")
    else:
        starting_pool = []
        pool_key = pool_type + (append or "")

    for item in starting_pool:
        add = False

        if pool_type == "Joker":
            # item is (key, name, rarity, cost, order)
            key = item[0]
            # Locked jokers excluded (unlocked ~= false), except Legendary (rarity 4)
            if key in config.locked_jokers and item[2] != RARITY_LEGENDARY:
                pass  # locked, don't add
            # Check used_jokers (no duplicates unless Showman)
            elif config.used_jokers.get(key) and not config.has_showman:
                pass  # don't add
            else:
                add = True
            # Soul and Black Hole are never in normal pool
            if key in ("c_soul", "c_black_hole"):
                add = False
        elif pool_type == "Voucher":
            # item is VoucherDef
            key = item.key
            if config.used_vouchers.get(key):
                pass  # already redeemed → UNAVAILABLE
            else:
                # Check requires (locked tier 2 → UNAVAILABLE, not excluded)
                include = True
                if item.requires:
                    if not config.used_vouchers.get(item.requires):
                        include = False
                if include:
                    add = True
        elif pool_type in ("Tarot", "Planet", "Spectral", "Tarot_Planet"):
            # item is (key, name, cost, order)
            key = item[0]
            # Soul and Black Hole excluded from normal pool
            if key in ("c_soul", "c_black_hole"):
                add = False
            # Softlocked planets: only if hand type has been played
            elif key in SOFTLOCKED_PLANETS and key not in config.played_hands:
                add = False
            elif config.used_jokers.get(key) and not config.has_showman:
                pass
            else:
                add = True
        else:
            key = item[0] if isinstance(item, (list, tuple)) else item.key
            add = True

        # Check banned keys
        if add and key in config.banned_keys:
            add = False

        if add:
            pool.append(key)
            pool_size += 1
        else:
            pool.append("UNAVAILABLE")

    # Empty pool fallback
    if pool_size == 0:
        pool = []
        if pool_type in ("Tarot", "Tarot_Planet"):
            pool.append("c_strength")
        elif pool_type == "Planet":
            pool.append("c_pluto")
        elif pool_type == "Spectral":
            pool.append("c_incantation")
        elif pool_type == "Joker":
            pool.append("j_joker")
        elif pool_type == "Voucher":
            pool.append("v_blank")
        else:
            pool.append("j_joker")

    if not legendary:
        pool_key = pool_key + str(ante)
    return pool, pool_key


# ---------------------------------------------------------------------------
# poll_edition — precise port
# ---------------------------------------------------------------------------

def poll_edition(
    rng: RNGState,
    key: str,
    edition_rate: float = 1.0,
    mod: float = 1.0,
    no_neg: bool = True,
    guaranteed: bool = False,
) -> Edition:
    """Port of poll_edition() from common_events.lua:2055.

    Lua: local edition_poll = pseudorandom(pseudoseed(_key))
    pseudorandom(seed) = math.randomseed(seed); math.random()
    Our rng.pseudorandom(key) does exactly this.
    """
    edition_poll = rng.pseudorandom(key)

    if guaranteed:
        if edition_poll > 1 - 0.003 * 25 and not no_neg:
            return Edition.NEGATIVE
        elif edition_poll > 1 - 0.006 * 25:
            return Edition.POLYCHROME
        elif edition_poll > 1 - 0.02 * 25:
            return Edition.HOLOGRAPHIC
        elif edition_poll > 1 - 0.04 * 25:
            return Edition.FOIL
    else:
        if edition_poll > 1 - 0.003 * mod and not no_neg:
            return Edition.NEGATIVE
        elif edition_poll > 1 - 0.006 * edition_rate * mod:
            return Edition.POLYCHROME
        elif edition_poll > 1 - 0.02 * edition_rate * mod:
            return Edition.HOLOGRAPHIC
        elif edition_poll > 1 - 0.04 * edition_rate * mod:
            return Edition.FOIL
    return Edition.NONE


# ---------------------------------------------------------------------------
# create_card — precise port of create_card() for shop context
# ---------------------------------------------------------------------------

def _select_joker_rarity(rng, ante: int, source) -> int:
    """Select Joker rarity using Immolate's next_joker_rarity logic.
    
    Immolate: random(inst, {N_Type, N_Ante, N_Source}, {R_Joker_Rarity, ante, itemSource}, 2)
    Key = "rarity" + str(ante) + source_str
    
    Returns:
        1 = Common, 2 = Uncommon, 3 = Rare, 4 = Legendary
    """
    from .rng import RType, NType, build_node_key
    
    # Build node key: {N_Type, N_Ante, N_Source}
    # Note: N_Ante comes BEFORE N_Source!
    rarity_key = build_node_key(
        (NType.Type, RType.JokerRarity),
        (NType.Ante, ante),
        (NType.Source, source),
    )
    
    rate = rng.raw_random(rarity_key)
    
    # Thresholds from Immolate functions.cl:201-207
    # Note: No Legendary from random! Legendary only from S_Soul source.
    # No ante check either.
    if rate > 0.95:
        return 3  # Rare
    elif rate > 0.7:
        return 2  # Uncommon
    else:
        return 1  # Common


def _create_card(
    rng: RNGState,
    card_type: str,
    config: ShopConfig,
    ante: int,
    rarity: Optional[float] = None,
    legendary: bool = False,
    soulable: bool = False,
    forced_key: Optional[str] = None,
    key_append: str = "",
    area: str = "shop_jokers",
) -> dict:
    """Port of create_card() — returns a dict describing the created card.

    Returns:
        {"key": str, "type": str, "edition": Edition,
         "eternal": bool, "perishable": bool, "rental": bool}
    """
    # Soul/Black Hole check (before pool)
    # Use node-based RNG matching Immolate: random(inst, {N_Type, N_Type, N_Ante}, {R_Soul, R_<CardType>, ante}, 3)
    from .rng import RType, NType, build_node_key
    
    if not forced_key and soulable and "c_soul" not in config.banned_keys:
        if card_type in ("Tarot", "Spectral", "Tarot_Planet"):
            if not (config.used_jokers.get("c_soul") and not config.has_showman):
                # Tarot: {R_Soul, R_Tarot, ante}
                soul_rtype = RType.Tarot if card_type == "Tarot" else RType.Spectral
                soul_key = build_node_key(
                    (NType.Type, RType.Soul),
                    (NType.Type, soul_rtype),
                    (NType.Ante, ante)
                )
                if rng.raw_random(soul_key) > 0.997:
                    forced_key = "c_soul"
        if card_type in ("Planet", "Spectral"):
            if not (config.used_jokers.get("c_black_hole") and not config.has_showman):
                # Planet/Spectral: {R_Soul, R_Planet/R_Spectral, ante}
                bh_rtype = RType.Planet if card_type == "Planet" else RType.Spectral
                bh_key = build_node_key(
                    (NType.Type, RType.Soul),
                    (NType.Type, bh_rtype),
                    (NType.Ante, ante)
                )
                if rng.raw_random(bh_key) > 0.997:
                    forced_key = "c_black_hole"

    if forced_key and forced_key not in config.banned_keys:
        return {
            "key": forced_key,
            "type": card_type,
            "edition": Edition.NONE,
            "eternal": False,
            "perishable": False,
            "rental": False,
        }

    # Build pool and select using node-based RNG
    from .rng import RType, RSource
    
    # Determine source from area
    source = RSource.Shop if "shop" in area else RSource.Buffoon
    
    # Joker-specific: rarity分流
    if card_type == "Joker":
        # Step 1: Select rarity using {N_Type, N_Ante, N_Source}
        joker_rarity = _select_joker_rarity(rng, ante, source)
        
        # Step 2: Get pool for this rarity (use _build_pool for proper filtering)
        pool, _pool_key = _build_pool("Joker", joker_rarity, config, ante, key_append)
        
        # Step 3: Select from rarity-specific pool using {N_Type, N_Source, N_Ante}
        # Note: N_Source comes BEFORE N_Ante in randchoice_common!
        rtype_map = {1: RType.Joker1, 2: RType.Joker2, 3: RType.Joker3, 4: RType.Joker4}
        rtype = rtype_map[joker_rarity]
        
        center_key = rng.node_element(rtype, pool, source, ante, resample=0)
    else:
        # Non-Joker: use original logic
        pool, pool_key = _build_pool(card_type, None, config, ante, key_append, legendary)
        
        rtype_map = {
            "Tarot": RType.Tarot,
            "Planet": RType.Planet,
            "Spectral": RType.Spectral,
        }
        rtype = rtype_map.get(card_type, RType.Tarot)
        
        center_key = rng.node_element(rtype, pool, source, ante, resample=0)

    # Resample if UNAVAILABLE
    resample_num = 1
    while center_key == "UNAVAILABLE":
        center_key = rng.node_element(rtype, pool, source, ante, resample=resample_num)
        resample_num += 1
        if resample_num > 100:  # Safety
            break

    # Joker-specific: edition, eternal, perishable, rental
    edition = Edition.NONE
    eternal = False
    perishable = False
    rental = False

    if card_type == "Joker":
        if config.all_eternal:
            eternal = True

        if area in ("shop_jokers", "pack_cards"):
            # Immolate: random(inst, {N_Type, N_Ante}, {R_Eternal_Perishable/Pack, ante}, 2)
            ep_rtype = RType.EternalPerishablePack if area == "pack_cards" else RType.EternalPerishable
            ep_key = build_node_key(
                (NType.Type, ep_rtype),
                (NType.Ante, ante)
            )
            ep_poll = rng.pseudorandom(ep_key)
            if config.enable_eternals_in_shop and ep_poll > 0.7:
                eternal = True
            elif config.enable_perishables_in_shop and 0.4 < ep_poll <= 0.7:
                perishable = True

            # Immolate: random(inst, {N_Type, N_Ante}, {R_Rental/Pack, ante}, 2)
            rental_rtype = RType.RentalPack if area == "pack_cards" else RType.Rental
            rental_key = build_node_key(
                (NType.Type, rental_rtype),
                (NType.Ante, ante)
            )
            if config.enable_rentals_in_shop:
                if rng.pseudorandom(rental_key) > 0.7:
                    rental = True

        # Joker edition: use node-based RNG
        # Immolate: random(inst, {N_Type, N_Source, N_Ante}, {R_Joker_Edition, itemSource, ante}, 3)
        # Immolate thresholds: >0.997→Negative, >0.994→Polychrome, >0.98→Holo, >0.96→Foil
        edition_key = build_node_key(
            (NType.Type, RType.JokerEdition),
            (NType.Source, source),
            (NType.Ante, ante)
        )
        edition_poll = rng.raw_random(edition_key)
        if edition_poll > 0.997:
            edition = Edition.NEGATIVE
        elif edition_poll > 0.994:
            edition = Edition.POLYCHROME
        elif edition_poll > 0.98:
            edition = Edition.HOLOGRAPHIC
        elif edition_poll > 0.96:
            edition = Edition.FOIL

    return {
        "key": center_key,
        "type": card_type,
        "edition": edition,
        "eternal": eternal,
        "perishable": perishable,
        "rental": rental,
    }


# ---------------------------------------------------------------------------
# create_card_for_shop — precise port of create_card_for_shop()
# ---------------------------------------------------------------------------

def create_card_for_shop(
    rng: RNGState,
    config: ShopConfig,
    ante: int,
) -> ShopJoker | ShopConsumable:
    """Port of create_card_for_shop() from UI_definitions.lua:742.

    Uses rate-based polling to determine card type, then calls _create_card.
    """
    from .rng import RType, RSource, NType, build_node_key
    
    total_rate = (
        config.joker_rate
        + config.tarot_rate
        + config.planet_rate
        + config.playing_card_rate
        + config.spectral_rate
    )

    # Immolate: random(inst, {N_Type, N_Ante}, {R_Card_Type, ante}, 2)
    # Key = "cdt" + str(ante)  (NO source!)
    card_type_key = build_node_key(
        (NType.Type, RType.CardType),
        (NType.Ante, ante),
    )
    polled_rate = rng.raw_random(card_type_key) * total_rate

    # Rate buckets — order matters (matches Lua ipairs order)
    rate_buckets = [
        ("Joker", config.joker_rate),
        ("Tarot", config.tarot_rate),
        ("Planet", config.planet_rate),
    ]

    # Playing card slot: Enhanced if has Illusion + roll > 0.6, else Base
    if config.has_illusion:
        illusion_roll = rng.pseudorandom("illusion")
        pc_type = "Enhanced" if illusion_roll > 0.6 else "Base"
    else:
        pc_type = "Base"
    rate_buckets.append((pc_type, config.playing_card_rate))
    rate_buckets.append(("Spectral", config.spectral_rate))

    check_rate = 0.0
    selected_type = "Joker"  # fallback
    for card_type, rate in rate_buckets:
        if polled_rate > check_rate and polled_rate <= check_rate + rate:
            selected_type = card_type
            break
        check_rate += rate

    card = _create_card(
        rng, selected_type, config, ante,
        soulable=False, key_append="sho",
        area="shop_jokers",
    )

    # Illusion edition for playing cards
    if selected_type in ("Base", "Enhanced") and config.has_illusion:
        if rng.pseudorandom("illusion") > 0.8:
            edition_poll = rng.pseudorandom("illusion")
            if edition_poll > 1 - 0.15:
                card["edition"] = Edition.POLYCHROME
            elif edition_poll > 0.5:
                card["edition"] = Edition.HOLOGRAPHIC
            else:
                card["edition"] = Edition.FOIL

    # Convert to typed shop item
    if selected_type == "Joker":
        jdef = JOKER_BY_KEY.get(card["key"])
        cost = jdef[3] if jdef else 4
        # Edition cost modifier
        if card["edition"] == Edition.FOIL:
            cost += 2
        elif card["edition"] == Edition.HOLOGRAPHIC:
            cost += 3
        elif card["edition"] == Edition.POLYCHROME:
            cost += 5
        elif card["edition"] == Edition.NEGATIVE:
            cost += 5
        return ShopJoker(
            key=card["key"],
            name=jdef[1] if jdef else card["key"],
            rarity=jdef[2] if jdef else 1,
            edition=card["edition"],
            cost=cost,
            eternal=card["eternal"],
            perishable=card["perishable"],
            rental=card["rental"],
        )
    else:
        # Consumable
        cost = 3
        if selected_type == "Spectral":
            cost = 4
        elif selected_type == "Planet":
            # Look up actual cost
            for p in PLANET_CARDS:
                if p[0] == card["key"]:
                    cost = p[2]
                    break
        elif selected_type == "Tarot":
            for t in TAROT_CARDS:
                if t[0] == card["key"]:
                    cost = t[2]
                    break
        name = card["key"]
        for pool in (TAROT_CARDS, PLANET_CARDS, SPECTRAL_CARDS):
            for item in pool:
                if item[0] == card["key"]:
                    name = item[1]
                    break
        return ShopConsumable(
            key=card["key"],
            name=name,
            card_type=selected_type,
            cost=cost,
        )


# ---------------------------------------------------------------------------
# get_pack — precise port of get_pack() from common_events.lua:1944
# ---------------------------------------------------------------------------

def get_pack(
    rng: RNGState,
    config: ShopConfig,
    ante: int,
    key: str = "shop_pack",
    pack_type: Optional[str] = None,
) -> PackDef:
    """Port of get_pack(). Ante 1-2: first pack is Buffoon Pack.

    Uses weighted selection over PACK_DEFS, matching Lua's iteration order.
    """
    from .rng import RType, NType, build_node_key
    
    # Ante 1-2: first pack is forced Buffoon Pack (Immolate behavior)
    if ante <= 2 and not config.first_shop_buffoon and "p_buffoon_normal_1" not in config.banned_keys:
        config.first_shop_buffoon = True
        for p in PACK_DEFS:
            if p.key == "p_buffoon_normal_1":
                return p

    # Weighted selection using node-based RNG
    cume = 0.0
    for p in PACK_DEFS:
        if (not pack_type or pack_type == p.kind) and p.key not in config.banned_keys:
            cume += p.weight

    # Use ShopPack RType + ante (no source, matching Immolate)
    node_key = build_node_key((NType.Type, RType.ShopPack), (NType.Ante, ante))
    poll = rng.raw_random(node_key) * cume
    it = 0.0
    for p in PACK_DEFS:
        if p.key in config.banned_keys:
            continue
        if not pack_type or pack_type == p.kind:
            it += p.weight
        if it >= poll and it - p.weight <= poll:
            return p

    # Fallback
    return PACK_DEFS[0]


# ---------------------------------------------------------------------------
# get_next_voucher_key — precise port
# ---------------------------------------------------------------------------

def get_next_voucher_key(
    rng: RNGState,
    config: ShopConfig,
    ante: int,
    from_tag: bool = False,
) -> Optional[str]:
    """Port of get_next_voucher_key() with resample mechanism.
    
    Matches Immolate's voucher generation: initial sample, then resample
    with N_Resample if locked/unavailable.
    
    Immolate source (functions.cl:527-532):
      randchoice(inst, {N_Type, N_Ante}, {R_Voucher, ante}, 2, VOUCHERS)
      resample: {N_Type, N_Ante, N_Resample}, {R_Voucher, ante, resampleNum}
    """
    from .rng import RType, NType, build_node_key
    
    pool, pool_key = _build_pool("Voucher", None, config, ante)
    
    # Initial sample: Type + Ante (no source)
    rtype = RType.VoucherTag if from_tag else RType.Voucher
    key = build_node_key((NType.Type, rtype), (NType.Ante, ante))
    center = rng.raw_element(key, pool)
    
    # Resample if unavailable (locked): Type + Ante + Resample
    resample_num = 1
    while center == "UNAVAILABLE":
        key = build_node_key((NType.Type, rtype), (NType.Ante, ante), (NType.Resample, resample_num))
        center = rng.raw_element(key, pool)
        resample_num += 1
        # Safety: prevent infinite loop
        if resample_num > 100:
            break

    return center


# ---------------------------------------------------------------------------
# generate_shop — full shop generation
# ---------------------------------------------------------------------------

def generate_shop(
    rng: RNGState,
    config: ShopConfig,
    ante: int,
) -> ShopState:
    """Generate a complete shop for the current round.

    Mirrors Game:update_shop() from game.lua:3072.
    """
    # Card slots
    card_slots = []
    for _ in range(config.joker_max):
        card_slots.append(create_card_for_shop(rng, config, ante))

    # Voucher
    voucher_key = get_next_voucher_key(rng, config, ante)
    voucher = None
    if voucher_key and voucher_key != "UNAVAILABLE":
        vdef = VOUCHER_BY_KEY.get(voucher_key)
        if vdef:
            cost = vdef.cost
            # Clearance Sale: 25% off, Liquidation: 50% off
            if config.used_vouchers.get("v_liquidation"):
                cost = max(1, int(cost * 0.5))
            elif config.used_vouchers.get("v_clearance_sale"):
                cost = max(1, int(cost * 0.75))
            voucher = ShopVoucher(key=vdef.key, name=vdef.name, cost=cost)

    # Booster packs (2 slots)
    packs = []
    for i in range(2):
        pack_def = get_pack(rng, config, ante)
        cost = pack_def.cost
        if config.used_vouchers.get("v_liquidation"):
            cost = max(1, int(cost * 0.5))
        elif config.used_vouchers.get("v_clearance_sale"):
            cost = max(1, int(cost * 0.75))
        packs.append(ShopPack(
            key=pack_def.key,
            name=pack_def.name,
            kind=pack_def.kind,
            cost=cost,
            extra=pack_def.extra,
            choose=pack_def.choose,
        ))

    # Reroll cost
    base_reroll = 5
    if config.used_vouchers.get("v_reroll_glut"):
        base_reroll = 0
    elif config.used_vouchers.get("v_reroll_surplus"):
        base_reroll = 3

    return ShopState(
        card_slots=card_slots,
        voucher=voucher,
        packs=packs,
        reroll_cost=base_reroll,
        free_rerolls=0,
        reroll_cost_increase=0,
    )


# ---------------------------------------------------------------------------
# reroll_shop — precise port of reroll_shop() + calculate_reroll_cost()
# ---------------------------------------------------------------------------

def calculate_reroll_cost(shop: ShopState, skip_increment: bool = False) -> None:
    """Port of calculate_reroll_cost() from common_events.lua:2263.

    Mutates shop in place.
    """
    if shop.free_rerolls < 0:
        shop.free_rerolls = 0
    if shop.free_rerolls > 0:
        shop.reroll_cost = 0
        return
    if not skip_increment:
        shop.reroll_cost_increase += 1
    shop.reroll_cost = shop.reroll_cost + shop.reroll_cost_increase


def reroll_shop(
    rng: RNGState,
    shop: ShopState,
    config: ShopConfig,
    ante: int,
    dollars: int,
) -> tuple[ShopState, int]:
    """Reroll the shop card slots (not voucher/packs).

    Returns (new_shop_state, cost_paid).
    Raises ValueError if can't afford.
    """
    cost = shop.reroll_cost
    if dollars < cost:
        raise ValueError(f"Can't afford reroll: need ${cost}, have ${dollars}")

    # Regenerate card slots
    new_slots = []
    for _ in range(config.joker_max):
        new_slots.append(create_card_for_shop(rng, config, ante))

    final_free = shop.free_rerolls > 0
    new_free = max(0, shop.free_rerolls - 1)

    new_shop = ShopState(
        card_slots=new_slots,
        voucher=shop.voucher,
        packs=shop.packs,
        reroll_cost=shop.reroll_cost,
        free_rerolls=new_free,
        reroll_cost_increase=shop.reroll_cost_increase,
    )
    calculate_reroll_cost(new_shop, skip_increment=final_free)

    return new_shop, cost
