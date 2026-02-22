"""Joker scoring effects — applies joker bonuses during score calculation.

Implements the most common joker effects for accurate simulation.
Jokers are processed left-to-right, matching real Balatro order.
"""

from __future__ import annotations

from collections import Counter
from typing import Optional

from .enums import HandType, Suit, Rank, Enhancement, Edition, HAND_CONTAINS
from .cards import Card, JokerCard


def apply_joker_scoring(
    jokers: list[JokerCard],
    played_cards: list[Card],
    scoring_indices: list[int],
    hand_type: HandType,
    held_cards: list[Card],
    chips: float,
    mult: float,
) -> tuple[float, float]:
    """Apply all joker scoring effects to chips/mult.

    Called after base scoring + card effects, before final multiplication.
    Returns updated (chips, mult).
    """
    scoring_cards = [played_cards[i] for i in scoring_indices]
    n_played = len(played_cards)
    n_scoring = len(scoring_cards)

    # Pre-compute stats for joker conditions
    suits_played = Counter(c.suit for c in played_cards)
    ranks_played = Counter(c.rank for c in played_cards)
    face_count = sum(1 for c in scoring_cards if c.is_face)
    hand_contains = HAND_CONTAINS.get(hand_type, {hand_type})

    for joker in jokers:
        if joker.edition == Edition.NEGATIVE:
            pass  # Negative just gives +1 joker slot, no scoring effect

        key = joker.key
        extra = joker.extra

        # ---- Flat mult jokers ----
        if key == "j_joker":
            mult += 4
        elif key == "j_jolly":
            if HandType.PAIR in hand_contains:
                mult += 8
        elif key == "j_zany":
            if HandType.THREE_OF_A_KIND in hand_contains:
                mult += 12
        elif key == "j_mad":
            if HandType.TWO_PAIR in hand_contains:
                mult += 10
        elif key == "j_crazy":
            if HandType.STRAIGHT in hand_contains:
                mult += 12
        elif key == "j_droll":
            if HandType.FLUSH in hand_contains:
                mult += 10

        # ---- Flat chip jokers ----
        elif key == "j_sly":
            if HandType.PAIR in hand_contains:
                chips += 50
        elif key == "j_wily":
            if HandType.THREE_OF_A_KIND in hand_contains:
                chips += 100
        elif key == "j_clever":
            if HandType.TWO_PAIR in hand_contains:
                chips += 80
        elif key == "j_devious":
            if HandType.STRAIGHT in hand_contains:
                chips += 100
        elif key == "j_crafty":
            if HandType.FLUSH in hand_contains:
                chips += 80

        # ---- Suit-based mult ----
        elif key == "j_greedy_joker":
            chips += 3 * sum(1 for c in scoring_cards if c.suit == Suit.DIAMONDS)
        elif key == "j_lusty_joker":
            mult += 3 * sum(1 for c in scoring_cards if c.suit == Suit.HEARTS)
        elif key == "j_wrathful_joker":
            mult += 3 * sum(1 for c in scoring_cards if c.suit == Suit.SPADES)
        elif key == "j_gluttenous_joker":
            chips += 3 * sum(1 for c in scoring_cards if c.suit == Suit.CLUBS)

        # ---- Conditional jokers ----
        elif key == "j_half":
            if n_played <= 3:
                mult += 20
        elif key == "j_banner":
            mult += extra.get("discards_left", 0) * 2  # needs state
        elif key == "j_mystic_summit":
            if extra.get("discards_left", 0) == 0:
                mult += 15
        elif key == "j_scholar":
            # +20 chips, +4 mult per Ace played
            ace_count = sum(1 for c in scoring_cards if c.rank == Rank.ACE)
            chips += 20 * ace_count
            mult += 4 * ace_count
        elif key == "j_walkie_talkie":
            # +10 chips, +4 mult per 10 or 4 played
            count = sum(1 for c in scoring_cards if c.rank in (Rank.TEN, Rank.FOUR))
            chips += 10 * count
            mult += 4 * count
        elif key == "j_even_steven":
            even_count = sum(1 for c in scoring_cards if c.rank.value % 2 == 0)
            mult += 4 * even_count
        elif key == "j_odd_todd":
            odd_count = sum(1 for c in scoring_cards if c.rank.value % 2 == 1)
            chips += 31 * odd_count
        elif key == "j_fibonacci":
            # 2, 3, 5, 8, Ace
            fib_ranks = {Rank.TWO, Rank.THREE, Rank.FIVE, Rank.EIGHT, Rank.ACE}
            fib_count = sum(1 for c in scoring_cards if c.rank in fib_ranks)
            mult += 8 * fib_count
        elif key == "j_scary_face":
            mult += 2 * face_count
        elif key == "j_smiley":
            mult += 5 * face_count
        elif key == "j_photograph":
            if face_count > 0:
                mult *= 2  # x2 if hand contains face card (first face card)

        # ---- Scaling jokers (use extra state) ----
        elif key == "j_supernova":
            mult += extra.get("times_played", 0)
        elif key == "j_ride_the_bus":
            mult += extra.get("consecutive_no_face", 0)
        elif key == "j_green_joker":
            mult += extra.get("mult_bonus", 0)
        elif key == "j_red_card":
            mult += extra.get("mult_bonus", 0)
        elif key == "j_blue_joker":
            chips += extra.get("remaining_deck", 0) * 2
        elif key == "j_runner":
            chips += extra.get("chip_bonus", 0)
        elif key == "j_ice_cream":
            chips += extra.get("chip_bonus", 100)
        elif key == "j_square":
            chips += extra.get("chip_bonus", 0)
        elif key == "j_popcorn":
            mult += extra.get("mult_bonus", 20)
        elif key == "j_castle":
            chips += extra.get("chip_bonus", 0)
        elif key == "j_wee":
            chips += extra.get("chip_bonus", 0)
        elif key == "j_hiker":
            # Hiker adds permanent +5 chips to each played card
            # In sim, we track via extra
            chips += extra.get("chip_bonus", 0)

        # ---- xMult jokers ----
        elif key == "j_duo":
            if HandType.PAIR in hand_contains:
                mult *= 2
        elif key == "j_trio":
            if HandType.THREE_OF_A_KIND in hand_contains:
                mult *= 3
        elif key == "j_family":
            if HandType.FOUR_OF_A_KIND in hand_contains:
                mult *= 4
        elif key == "j_order":
            if HandType.STRAIGHT in hand_contains:
                mult *= 3
        elif key == "j_tribe":
            if HandType.FLUSH in hand_contains:
                mult *= 2
        elif key == "j_cavendish":
            mult *= 3
        elif key == "j_card_sharp":
            mult *= extra.get("x_mult", 1.0)
        elif key == "j_blackboard":
            # x3 if all held cards are Spades or Clubs
            if held_cards and all(c.suit in (Suit.SPADES, Suit.CLUBS) for c in held_cards):
                mult *= 3
        elif key == "j_vampire":
            mult *= extra.get("x_mult", 1.0)
        elif key == "j_obelisk":
            mult *= extra.get("x_mult", 1.0)
        elif key == "j_hologram":
            mult *= extra.get("x_mult", 1.0)
        elif key == "j_lucky_cat":
            mult *= extra.get("x_mult", 1.0)
        elif key == "j_campfire":
            mult *= extra.get("x_mult", 1.0)
        elif key == "j_acrobat":
            if extra.get("is_last_hand", False):
                mult *= 3
        elif key == "j_steel_joker":
            steel_count = sum(1 for c in held_cards if c.enhancement == Enhancement.STEEL)
            if steel_count > 0:
                mult *= (1 + 0.2 * steel_count)
        elif key == "j_glass":
            glass_count = extra.get("glass_destroyed", 0)
            if glass_count > 0:
                mult *= (1 + 0.75 * glass_count)
        elif key == "j_baron":
            # x1.5 for each King held in hand
            king_held = sum(1 for c in held_cards if c.rank == Rank.KING)
            if king_held > 0:
                for _ in range(king_held):
                    mult *= 1.5

        # ---- Economy jokers (no scoring effect) ----
        elif key in ("j_credit_card", "j_delayed_grat", "j_egg", "j_golden",
                      "j_to_the_moon", "j_cloud_9", "j_rocket", "j_satellite",
                      "j_bull", "j_trading", "j_faceless", "j_rough_gem",
                      "j_ticket", "j_diet_cola", "j_ramen"):
            pass  # Economy effects handled elsewhere

        # ---- Utility jokers (no direct scoring) ----
        elif key in ("j_four_fingers", "j_splash", "j_shortcut", "j_smeared",
                      "j_pareidolia", "j_hack", "j_dusk", "j_mime",
                      "j_sock_and_buskin", "j_hanging_chad", "j_stencil",
                      "j_chaos", "j_burglar", "j_juggler", "j_drunkard",
                      "j_troubadour", "j_merry_andy", "j_marble",
                      "j_ceremonial", "j_madness", "j_riff_raff",
                      "j_luchador", "j_matador", "j_mr_bones",
                      "j_invisible", "j_brainstorm", "j_blueprint",
                      "j_showman", "j_cartomancer", "j_astronomer",
                      "j_burnt", "j_certificate", "j_vagabond",
                      "j_8_ball", "j_sixth_sense", "j_seance",
                      "j_superposition", "j_space", "j_hallucination",
                      "j_fortune_teller", "j_todo_list", "j_mail",
                      "j_reserved_parking", "j_business", "j_gift",
                      "j_turtle_bean", "j_erosion", "j_flash",
                      "j_swashbuckler", "j_bootstraps", "j_misprint",
                      "j_abstract", "j_raised_fist", "j_stone",
                      "j_stuntman", "j_dna", "j_perkeo",
                      "j_canio", "j_triboulet", "j_yorick", "j_chicot",
                      "j_gros_michel", "j_loyalty_card", "j_idol",
                      "j_seeing_double", "j_hit_the_road",
                      "j_shoot_the_moon", "j_flower_pot",
                      "j_oops", "j_throwback", "j_arrowhead",
                      "j_onyx_agate", "j_bloodstone"):
            pass  # Complex effects not yet simulated

        # Apply joker edition
        if joker.edition == Edition.FOIL:
            chips += 50
        elif joker.edition == Edition.HOLOGRAPHIC:
            mult += 10
        elif joker.edition == Edition.POLYCHROME:
            mult *= 1.5

    return chips, mult
