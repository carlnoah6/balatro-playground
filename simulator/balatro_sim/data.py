"""Game data catalog — Joker definitions, Vouchers, Booster Packs, Consumables.

All static game data for shop generation and game simulation.
Data sourced from Balatro wiki + source code analysis.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


# ---------------------------------------------------------------------------
# Rarity
# ---------------------------------------------------------------------------

class Rarity(IntEnum):
    COMMON = 1
    UNCOMMON = 2
    RARE = 3
    LEGENDARY = 4


# Rarity weights for random joker generation (Legendary only via The Soul)
RARITY_WEIGHTS: dict[Rarity, float] = {
    Rarity.COMMON: 0.70,
    Rarity.UNCOMMON: 0.25,
    Rarity.RARE: 0.05,
}


@dataclass(frozen=True)
class JokerDef:
    """Static definition of a Joker."""
    key: str
    name: str
    rarity: Rarity
    base_cost: int


# ---------------------------------------------------------------------------
# Joker catalog — compact (key, name, rarity_int, cost) tuples
# Rarity: 1=Common, 2=Uncommon, 3=Rare, 4=Legendary
# ---------------------------------------------------------------------------

_JOKER_RAW: list[tuple[str, str, int, int]] = [
    # ---- Common ($1-6) ----
    ("j_joker", "Joker", 1, 2),
    ("j_greedy_joker", "Greedy Joker", 1, 5),
    ("j_lusty_joker", "Lusty Joker", 1, 5),
    ("j_wrathful_joker", "Wrathful Joker", 1, 5),
    ("j_gluttenous_joker", "Gluttonous Joker", 1, 5),
    ("j_jolly", "Jolly Joker", 1, 3),
    ("j_zany", "Zany Joker", 1, 4),
    ("j_mad", "Mad Joker", 1, 4),
    ("j_crazy", "Crazy Joker", 1, 4),
    ("j_droll", "Droll Joker", 1, 4),
    ("j_sly", "Sly Joker", 1, 3),
    ("j_wily", "Wily Joker", 1, 4),
    ("j_clever", "Clever Joker", 1, 4),
    ("j_devious", "Devious Joker", 1, 4),
    ("j_crafty", "Crafty Joker", 1, 4),
    ("j_half", "Half Joker", 1, 5),
    ("j_stencil", "Joker Stencil", 1, 5),
    ("j_credit_card", "Credit Card", 1, 1),
    ("j_banner", "Banner", 1, 5),
    ("j_mystic_summit", "Mystic Summit", 1, 5),
    ("j_8_ball", "8 Ball", 1, 5),
    ("j_misprint", "Misprint", 1, 4),
    ("j_raised_fist", "Raised Fist", 1, 5),
    ("j_chaos", "Chaos the Clown", 1, 4),
    ("j_scary_face", "Scary Face", 1, 4),
    ("j_abstract", "Abstract Joker", 1, 4),
    ("j_delayed_grat", "Delayed Gratification", 1, 4),
    ("j_gros_michel", "Gros Michel", 1, 5),
    ("j_even_steven", "Even Steven", 1, 4),
    ("j_odd_todd", "Odd Todd", 1, 4),
    ("j_scholar", "Scholar", 1, 4),
    ("j_business", "Business Card", 1, 4),
    ("j_supernova", "Supernova", 1, 5),
    ("j_ride_the_bus", "Ride the Bus", 1, 6),
    ("j_egg", "Egg", 1, 5),
    ("j_runner", "Runner", 1, 5),
    ("j_ice_cream", "Ice Cream", 1, 5),
    ("j_splash", "Splash", 1, 3),
    ("j_blue_joker", "Blue Joker", 1, 5),
    ("j_faceless", "Faceless Joker", 1, 4),
    ("j_green_joker", "Green Joker", 1, 4),
    ("j_superposition", "Superposition", 1, 4),
    ("j_todo_list", "To Do List", 1, 4),
    ("j_cavendish", "Cavendish", 1, 4),
    ("j_red_card", "Red Card", 1, 5),
    ("j_square", "Square Joker", 1, 4),
    ("j_riff_raff", "Riff-Raff", 1, 6),
    ("j_photograph", "Photograph", 1, 5),
    ("j_mail", "Mail-In Rebate", 1, 4),
    ("j_hallucination", "Hallucination", 1, 4),
    ("j_fortune_teller", "Fortune Teller", 1, 6),
    ("j_juggler", "Juggler", 1, 4),
    ("j_drunkard", "Drunkard", 1, 4),
    ("j_golden", "Golden Joker", 1, 6),
    ("j_popcorn", "Popcorn", 1, 5),
    ("j_walkie_talkie", "Walkie Talkie", 1, 4),
    ("j_smiley", "Smiley Face", 1, 4),
    ("j_ticket", "Golden Ticket", 1, 5),
    ("j_swashbuckler", "Swashbuckler", 1, 4),
    ("j_hanging_chad", "Hanging Chad", 1, 4),
    ("j_shoot_the_moon", "Shoot the Moon", 1, 5),
    ("j_bootstraps", "Bootstraps", 1, 5),
]

_JOKER_RAW += [
    # ---- Uncommon ($4-8) ----
    ("j_four_fingers", "Four Fingers", 2, 7),
    ("j_mime", "Mime", 2, 5),
    ("j_ceremonial", "Ceremonial Dagger", 2, 6),
    ("j_marble", "Marble Joker", 2, 6),
    ("j_loyalty_card", "Loyalty Card", 2, 5),
    ("j_dusk", "Dusk", 2, 5),
    ("j_fibonacci", "Fibonacci", 2, 8),
    ("j_steel_joker", "Steel Joker", 2, 7),
    ("j_hack", "Hack", 2, 6),
    ("j_pareidolia", "Pareidolia", 2, 5),
    ("j_space", "Space Joker", 2, 5),
    ("j_burglar", "Burglar", 2, 6),
    ("j_blackboard", "Blackboard", 2, 6),
    ("j_sixth_sense", "Sixth Sense", 2, 6),
    ("j_constellation", "Constellation", 2, 6),
    ("j_hiker", "Hiker", 2, 5),
    ("j_card_sharp", "Card Sharp", 2, 6),
    ("j_madness", "Madness", 2, 7),
    ("j_seance", "Séance", 2, 6),
    ("j_vampire", "Vampire", 2, 7),
    ("j_shortcut", "Shortcut", 2, 7),
    ("j_hologram", "Hologram", 2, 7),
    ("j_vagabond", "Vagabond", 2, 7),
    ("j_baron", "Baron", 2, 8),
    ("j_cloud_9", "Cloud 9", 2, 7),
    ("j_rocket", "Rocket", 2, 6),
    ("j_obelisk", "Obelisk", 2, 8),
    ("j_midas_mask", "Midas Mask", 2, 7),
    ("j_luchador", "Luchador", 2, 5),
    ("j_gift", "Gift Card", 2, 6),
    ("j_turtle_bean", "Turtle Bean", 2, 6),
    ("j_erosion", "Erosion", 2, 6),
    ("j_reserved_parking", "Reserved Parking", 2, 6),
    ("j_to_the_moon", "To the Moon", 2, 5),
    ("j_stone", "Stone Joker", 2, 6),
    ("j_lucky_cat", "Lucky Cat", 2, 6),
    ("j_bull", "Bull", 2, 6),
    ("j_diet_cola", "Diet Cola", 2, 6),
    ("j_trading", "Trading Card", 2, 6),
    ("j_flash", "Flash Card", 2, 5),
    ("j_trousers", "Spare Trousers", 2, 6),
    ("j_ramen", "Ramen", 2, 5),
    ("j_selzer", "Seltzer", 2, 6),
    ("j_castle", "Castle", 2, 6),
    ("j_mr_bones", "Mr. Bones", 2, 5),
    ("j_acrobat", "Acrobat", 2, 6),
    ("j_sock_and_buskin", "Sock and Buskin", 2, 6),
    ("j_troubadour", "Troubadour", 2, 6),
    ("j_certificate", "Certificate", 2, 6),
    ("j_smeared", "Smeared Joker", 2, 7),
    ("j_throwback", "Throwback", 2, 6),
    ("j_rough_gem", "Rough Gem", 2, 7),
    ("j_bloodstone", "Bloodstone", 2, 7),
    ("j_arrowhead", "Arrowhead", 2, 7),
    ("j_onyx_agate", "Onyx Agate", 2, 7),
    ("j_glass", "Glass Joker", 2, 6),
    ("j_showman", "Showman", 2, 5),
    ("j_flower_pot", "Flower Pot", 2, 8),
    ("j_wee", "Wee Joker", 2, 8),
    ("j_merry_andy", "Merry Andy", 2, 7),
    ("j_oops", "Oops! All 6s", 2, 4),
    ("j_idol", "The Idol", 2, 6),
    ("j_seeing_double", "Seeing Double", 2, 6),
    ("j_matador", "Matador", 2, 7),
    ("j_hit_the_road", "Hit the Road", 2, 8),
    ("j_duo", "The Duo", 2, 8),
    ("j_trio", "The Trio", 2, 8),
    ("j_family", "The Family", 2, 8),
    ("j_order", "The Order", 2, 8),
    ("j_tribe", "The Tribe", 2, 8),
    ("j_stuntman", "Stuntman", 2, 8),
    ("j_invisible", "Invisible Joker", 2, 8),
    ("j_brainstorm", "Brainstorm", 2, 8),
    ("j_satellite", "Satellite", 2, 6),
    ("j_cartomancer", "Cartomancer", 2, 6),
    ("j_astronomer", "Astronomer", 2, 8),
    ("j_burnt", "Burnt Joker", 2, 5),
    # ---- Rare ($7-10) ----
    ("j_dna", "DNA", 3, 8),
    ("j_blueprint", "Blueprint", 3, 10),
    ("j_drivers_license", "Driver's License", 3, 7),
    ("j_glass_rare", "Glass Joker", 3, 7),  # some overlap in naming
    ("j_the_soul", "The Soul", 3, 8),  # spectral, not shop
    ("j_vagabond_r", "Vagabond", 3, 8),
    # ---- Legendary ($20) — only from The Soul ----
    ("j_canio", "Canio", 4, 20),
    ("j_triboulet", "Triboulet", 4, 20),
    ("j_yorick", "Yorick", 4, 20),
    ("j_chicot", "Chicot", 4, 20),
    ("j_perkeo", "Perkeo", 4, 20),
]

# ---------------------------------------------------------------------------
# Derived catalogs
# ---------------------------------------------------------------------------

JOKER_CATALOG: dict[str, JokerDef] = {
    key: JokerDef(key=key, name=name, rarity=Rarity(rarity), base_cost=cost)
    for key, name, rarity, cost in _JOKER_RAW
}

JOKERS_BY_RARITY: dict[Rarity, list[JokerDef]] = {}
for _jdef in JOKER_CATALOG.values():
    JOKERS_BY_RARITY.setdefault(_jdef.rarity, []).append(_jdef)
