#!/usr/bin/env python3
"""Extract complete EFHIII joker ID mapping and scoring logic."""

# EFHIII internal joker IDs (from balatro-sim.js case statements + cards.js order)
# The joker[JOKER] field in balatro-sim.js uses 0-indexed IDs
# cards.js uses 1-indexed "order" field
# Mapping: EFHIII_ID = order - 1

EFHIII_JOKER_MAP = {
    # order: (efhiii_id, name, scoring_category)
    # efhiii_id = order - 1
    0: "Joker",           # case 0 in triggerJoker: +4 mult
    1: "Greedy Joker",    # case 16 in triggerCard: +3 mult per Diamond
    2: "Lusty Joker",     # case 17: +3 mult per Heart
    3: "Wrathful Joker",  # case 18: +3 mult per Spade
    4: "Gluttonous Joker",# case 19: +3 mult per Club
    5: "Jolly Joker",     # case 2: +8 mult if Pair
    6: "Zany Joker",      # case 3: +12 mult if Three of a Kind
    7: "Mad Joker",       # case 4: +10 mult if Two Pair
    8: "Crazy Joker",     # case 5: +12 mult if Straight
    9: "Droll Joker",     # case 6: +10 mult if Flush
    10: "Sly Joker",      # compileCards case: +50 chips if Pair
    11: "Wily Joker",     # compileCards: +100 chips if Three of a Kind
    12: "Clever Joker",   # compileCards: +80 chips if Two Pair
    13: "Devious Joker",  # compileCards: +100 chips if Straight
    14: "Crafty Joker",   # compileCards: +80 chips if Flush
    15: "Half Joker",     # case 7: +20 mult if <=3 cards played
    16: "Joker Stencil",  # case 52: xMult from empty joker slots
    17: "Four Fingers",   # global: straights/flushes with 4 cards
    18: "Mime",           # case 13 in triggerCardInHand: retrigger held cards
    19: "Credit Card",    # no scoring effect
    20: "Ceremonial Dagger", # case 22: +mult from value
    21: "Banner",         # compileCards case 21: +30 chips per discard remaining
    22: "Mystic Summit",  # case 24: +15 mult if 0 discards remaining
    23: "Marble Joker",   # no scoring effect (adds Stone cards)
    24: "Loyalty Card",   # case 26: x4 every 5 hands
    25: "8 Ball",         # no scoring effect (spawns Tarot)
    26: "Misprint",       # case 27: random 0-23 mult
    27: "Dusk",           # retrigger on final hand
    28: "Raised Fist",    # held-in-hand: +2x lowest rank chips as mult
    29: "Chaos the Clown",# no scoring effect
    30: "Fibonacci",      # case 32 in triggerCard: +8 mult for Ace/2/3/5/8
    31: "Steel Joker",    # compileCards case: +chips from steel cards in deck
    32: "Scary Face",     # case 38 in triggerCard: +30 chips for face cards
    33: "Abstract Joker", # case 33: +3 mult per joker
    34: "Delayed Gratification", # no scoring effect
    35: "Hack",           # retrigger: cards rank 2-5
    36: "Pareidolia",     # global: all cards are face cards
    37: "Gros Michel",    # case 42: +15 mult
    38: "Even Steven",    # case 39 in triggerCard: +4 mult for even ranks
    39: "Odd Todd",       # case 40 in triggerCard: +31 chips for odd ranks
    40: "Scholar",        # case 51 in triggerCard: +20 chips +4 mult for Aces
    41: "Business Card",  # no scoring effect (money)
    42: "Supernova",      # case 44: +mult = times hand type played
    43: "Ride the Bus",   # case 45: +mult from consecutive non-face hands
    44: "Space Joker",    # no scoring effect (level up chance)
    # 45-59 gap in order (IDs 45-59 are other jokers)
    45: "Egg",            # no scoring effect
    46: "Burglar",        # no scoring effect
    47: "Blackboard",     # case 46: x3 if all held cards are Spades/Clubs
    48: "Runner",         # compileCards case 103: +chips from straights
    49: "Ice Cream",      # compileCards case 104: +100 chips minus 5 per hand
    50: "DNA",            # compileCards case 105: first hand = 1 card
    51: "Splash",         # global: all cards count in scoring
    52: "Blue Joker",     # case 47: +chips from remaining deck
    53: "Sixth Sense",    # no scoring effect
    54: "Constellation",  # case 48: xMult grows per Planet used
    55: "Hiker",          # case 55: +chips per card permanently
    56: "Faceless Jokers", # no scoring effect (money)
    57: "Green Joker",    # case 112: +mult per hand, -per discard
    58: "Superposition",  # no scoring effect
    59: "Swashbuckler",   # compileJokerOrder case 59: +mult = sum of sell values
    60: "Cavendish",      # case 49: x3 mult
    61: "Card Sharp",     # case 58: x3 if hand type played before this round
    62: "Red Card",       # case 57: +mult from value (grows per skip)
    63: "Madness",        # case 89: xMult grows per blind
    64: "Square Joker",   # compileCards case: +chips from 4-card hands
    65: "Seance",         # no scoring effect
    66: "Riff-raff",      # no scoring effect
    67: "Vampire",        # case 122 in compileJokers: consumes enhancements
    68: "Shortcut",       # global: straights can skip
    69: "Hologram",       # case 70: xMult grows per card added
    70: "Vagabond",       # no scoring effect
    71: "Baron",          # held-in-hand: x1.5 per King
    72: "Cloud 9",        # no scoring effect (money)
    73: "Rocket",         # no scoring effect (money)
    74: "Obelisk",        # case 75: xMult from consecutive non-most-played
    75: "Midas Mask",     # global: face cards become Gold
    76: "Luchador",       # no scoring effect
    77: "Photograph",     # case 76 in triggerCard: x2 for first face card
    78: "Gift Card",      # no scoring effect
    79: "Turtle Bean",    # no scoring effect
    80: "Erosion",        # case 81: +mult from missing deck cards
    81: "Reserved Parking",# case 82 in triggerCard: money chance for face
    82: "Mail-In Rebate", # no scoring effect (money)
    83: "To the Moon",    # no scoring effect (money)
    84: "Hallucination",  # no scoring effect
    85: "Fortune Teller", # case 83: +mult from Tarot cards used
    86: "Juggler",        # no scoring effect
    87: "Drunkard",       # no scoring effect
    88: "Stone Joker",    # compileCards case 9: +25 chips per Stone card
    89: "Golden Joker",   # no scoring effect (money)
    90: "Lucky Cat",      # case 85: xMult grows from Lucky triggers
    91: "Baseball Card",  # compileJokerOrder: x1.5 per Uncommon joker
    92: "Bull",           # case 12: +2 chips per dollar
    93: "Diet Cola",      # no scoring effect
    94: "Trading Card",   # no scoring effect
    95: "Flash Card",     # case 109: +mult from rerolls
    96: "Popcorn",        # case 115: +20 mult, decreasing
    97: "Spare Trousers", # case 116: +mult from two pair plays
    98: "Ancient Joker",  # case 84 in triggerCard: x1.5 for matching suit
    99: "Ramen",          # case 117: xMult decreasing per discard
    100: "Walkie Talkie",  # case 118 in triggerCard: +10 chips +4 mult for 10/4
    101: "Seltzer",        # retrigger all cards
    102: "Castle",         # case 129: +chips from discarded suit
    103: "Smiley Face",    # case 63 in triggerCard: +5 mult for face cards
    104: "Campfire",       # case 135: xMult grows per card sold
    105: "Golden Ticket",  # no scoring effect (money)
    106: "Mr. Bones",      # no scoring effect (survival)
    107: "Acrobat",        # case 145: x3 on final hand
    108: "Sock and Buskin", # retrigger face cards
    109: "Troubadour",     # no scoring effect
    110: "Certificate",    # no scoring effect
    111: "Smeared Joker",  # global: hearts=diamonds, clubs=spades
    112: "Throwback",      # case 147: xMult from blinds skipped
    113: "Hanging Chad",   # retrigger first scored card
    114: "Rough Gem",      # case 110 in triggerCard: money for Diamonds
    115: "Bloodstone",     # case 80 in triggerCard: x1.5 for Hearts (1 in 2)
    116: "Arrowhead",      # case 132 in triggerCard: +50 chips for Spades
    117: "Onyx Agate",     # case 156 in triggerCard: +7 mult for Clubs
    118: "Glass Joker",    # case 150: xMult grows per Glass destroyed
    119: "Showman",        # no scoring effect
    120: "Flower Pot",     # compileCards case 60: x3 if all 4 suits
    121: "Blueprint",      # compileJokerOrder: copies next joker
    122: "Wee Joker",      # case 151: +chips from 2s scored
    123: "Merry Andy",     # no scoring effect
    124: "Oops! All 6s",   # global: doubles probability
    125: "The Idol",       # case 152: x2 for specific rank+suit
    126: "Seeing Double",  # case 59: x2 if Club + other suit
    127: "Matador",        # no scoring effect (money)
    128: "Hit the Road",   # case 154: xMult from Jacks discarded
    129: "The Duo",        # case 155 variant: x2 if Pair
    130: "The Trio",       # case 155 variant: x2 if Three of a Kind
    131: "The Family",     # case 155 variant: x2 if Four of a Kind
    132: "The Order",      # case 155 variant: x2 if Straight
    133: "The Tribe",      # case 155 variant: x2 if Flush
    134: "Stuntman",       # compileCards case 68: +250 chips
    135: "Invisible Joker",# no scoring effect
    136: "Brainstorm",     # compileJokerOrder: copies first joker
    137: "Satellite",      # no scoring effect (money)
    138: "Shoot the Moon", # held-in-hand: +13 mult per Queen
    139: "Driver's License",# case 155 variant: x3 if 16+ enhanced
    140: "Cartomancer",    # no scoring effect
    141: "Astronomer",     # no scoring effect
    142: "Burnt Joker",    # no scoring effect
    143: "Bootstraps",     # case 150: +2 mult per $5
    144: "Canio",          # case 155 variant: xMult grows per face destroyed
    145: "Triboulet",      # case 157 in triggerCard: x2 for Kings, x2 for Queens
    146: "Yorick",         # case 155 variant: xMult after discards
    147: "Chicot",         # no scoring effect (negates boss)
    148: "Perkeo",         # no scoring effect
    149: "Photograph",     # duplicate? Actually this is the end
}

# Now let's extract the ACTUAL scoring logic from EFHIII for each joker
# organized by scoring phase

print("=== EFHIII Complete Joker Scoring Extraction ===")
print(f"Total jokers: {len(EFHIII_JOKER_MAP)}")
