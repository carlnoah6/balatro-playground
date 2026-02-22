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
            d_left = joker.get_extra("discards_left", 0)
            mult += d_left * 2  # needs state
        elif key == "j_mystic_summit":
            d_left = joker.get_extra("d_remaining", 0) if isinstance(extra, dict) else (joker.get_extra("discards_left", 0))
            if d_left == 0:
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

        # ---- Scaling jokers (use runtime state from game) ----
        elif key == "j_supernova":
            # Lua: mult_mod = G.GAME.hands[scoring_name].played
            # extra is plain int (times played), or use joker.mult
            if isinstance(extra, (int, float)) and extra > 0:
                mult += extra
            elif joker.mult > 0:
                mult += joker.mult
        elif key == "j_ride_the_bus":
            # Lua: mult_mod = self.ability.mult (cumulative)
            val = joker.mult
            if val > 0:
                mult += val
        elif key == "j_green_joker":
            # Lua: mult_mod = self.ability.mult (cumulative, +hand_add per hand, -discard_sub per discard)
            val = joker.mult
            if val > 0:
                mult += val
        elif key == "j_red_card":
            # Lua: mult_mod = self.ability.mult (cumulative, +extra per skip)
            val = joker.mult
            if val > 0:
                mult += val
        elif key == "j_blue_joker":
            # Lua: chip_mod = self.ability.extra * #G.deck.cards
            # extra is plain int (chips per remaining card, usually 2)
            extra_val = extra if isinstance(extra, (int, float)) else 2
            remaining = joker.get_extra("remaining_deck", 0) if isinstance(extra, dict) else 0
            # If we have game_state with deck_remaining, use it
            if remaining > 0:
                chips += int(extra_val * remaining)
            else:
                # Fallback: assume ~30 cards remaining
                chips += 60
        elif key == "j_runner":
            # Lua: chip_mod = self.ability.extra.chips (cumulative, +chip_mod per Straight)
            val = joker.get_extra("chips", 0)
            if val > 0:
                chips += val
        elif key == "j_ice_cream":
            # Lua: chip_mod = self.ability.extra.chips (starts 100, -chip_mod per hand)
            val = joker.get_extra("chips", 100)
            if val > 0:
                chips += val
        elif key == "j_square":
            # Lua: chip_mod = self.ability.extra.chips (cumulative, +chip_mod per 4-card hand)
            val = joker.get_extra("chips", 0)
            if val > 0:
                chips += val
        elif key == "j_popcorn":
            # Lua: mult_mod = self.ability.mult (starts 20, -extra per round)
            val = joker.mult
            if val > 0:
                mult += val
        elif key == "j_castle":
            # Lua: chip_mod = self.ability.extra.chips (cumulative)
            val = joker.get_extra("chips", 0) if isinstance(extra, dict) else (joker.t_chips if joker.t_chips > 0 else 0)
            if val > 0:
                chips += val
        elif key == "j_wee":
            # Lua: chip_mod = self.ability.extra.chips (cumulative, +chip_mod per 2 scored)
            val = joker.get_extra("chips", 0) if isinstance(extra, dict) else (joker.t_chips if joker.t_chips > 0 else 0)
            if val > 0:
                chips += val
        elif key == "j_hiker":
            # Hiker: per-card trigger adds +5 permanent chips to each scored card
            # In independent phase, no direct effect (per-card is handled separately)
            pass

        # ---- Newly implemented jokers ----
        elif key == "j_trousers":
            # Spare Trousers: Lua mult_mod = self.ability.mult (cumulative, +extra per Two Pair)
            val = joker.mult
            if val > 0:
                mult += val
        elif key == "j_flash":
            # Flash Card: Lua mult_mod = self.ability.mult (cumulative, +extra per reroll)
            val = joker.mult
            if val > 0:
                mult += val
        elif key == "j_raised_fist":
            # Raised Fist: +2x mult of lowest-rank held card
            # This is a held-in-hand trigger, not independent. Skip here.
            pass
        elif key == "j_misprint":
            # Misprint: random mult between min and max (extra.min, extra.max)
            # Use expected value for deterministic scoring
            min_val = joker.get_extra("min", 0) if isinstance(extra, dict) else 0
            max_val = joker.get_extra("max", 23) if isinstance(extra, dict) else 23
            mult += (min_val + max_val) / 2  # EV = 11.5
        elif key == "j_loyalty_card":
            # Loyalty Card: xMult every N hands (extra.every, extra.remaining)
            # extra.Xmult is the multiplier, extra.remaining tracks countdown
            x = joker.get_extra("Xmult", 4) if isinstance(extra, dict) else 4
            remaining = joker.get_extra("remaining", "")
            # Triggers when remaining shows "0 remaining" or similar
            if remaining and "0 remaining" in str(remaining):
                mult *= x
        elif key == "j_gros_michel":
            # Gros Michel: +15 mult (extra.mult)
            val = joker.get_extra("mult", 15) if isinstance(extra, dict) else 15
            if val > 0:
                mult += val
        elif key == "j_abstract":
            # Abstract Joker: +3 mult per joker owned
            joker_count = len(jokers)
            mult += 3 * joker_count
        elif key == "j_erosion":
            # Erosion: +extra per card below starting deck size
            extra_per = joker.get_extra("value", 4) if isinstance(extra, dict) else (extra if isinstance(extra, (int, float)) else 4)
            # Need game_state for deck sizes — skip if not available
            pass
        elif key == "j_stone":
            # Stone Joker: +25 chips per Stone Card in full deck
            pass  # Needs deck info
        elif key == "j_stuntman":
            # Stuntman: +250 chips
            chips += 250
        elif key == "j_bootstraps":
            # Bootstraps: +2 mult per $5 (extra.mult per extra.dollars)
            m = joker.get_extra("mult", 2) if isinstance(extra, dict) else 2
            # Need dollars info — skip
            pass

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
            # Lua: Xmult_mod = self.ability.extra.Xmult (grows per hand played this round)
            x = joker.get_extra("Xmult", 0) if isinstance(extra, dict) else 0
            if x <= 0:
                x = joker.x_mult if joker.x_mult > 1 else 1.0
            if x > 1:
                mult *= x
        elif key == "j_blackboard":
            # x3 if all held cards are Spades or Clubs
            if held_cards and all(c.suit in (Suit.SPADES, Suit.CLUBS) for c in held_cards):
                mult *= 3
        elif key == "j_vampire":
            # Lua: Xmult_mod = self.ability.x_mult (grows by absorbing enhancements)
            x = joker.x_mult if joker.x_mult > 1 else joker.get_extra("x_mult", 1.0)
            if x > 1:
                mult *= x
        elif key == "j_obelisk":
            x = joker.x_mult if joker.x_mult > 1 else joker.get_extra("x_mult", 1.0)
            if x > 1:
                mult *= x
        elif key == "j_hologram":
            x = joker.x_mult if joker.x_mult > 1 else joker.get_extra("x_mult", 1.0)
            if x > 1:
                mult *= x
        elif key == "j_lucky_cat":
            x = joker.x_mult if joker.x_mult > 1 else joker.get_extra("x_mult", 1.0)
            if x > 1:
                mult *= x
        elif key == "j_campfire":
            x = joker.x_mult if joker.x_mult > 1 else joker.get_extra("x_mult", 1.0)
            if x > 1:
                mult *= x
        elif key == "j_acrobat":
            if joker.get_extra("is_last_hand", False):
                mult *= 3
        elif key == "j_steel_joker":
            steel_count = sum(1 for c in held_cards if c.enhancement == Enhancement.STEEL)
            if steel_count > 0:
                mult *= (1 + 0.2 * steel_count)
        elif key == "j_glass":
            glass_count = joker.get_extra("glass_destroyed", 0)
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
                      "j_turtle_bean",
                      "j_swashbuckler",
                      "j_dna", "j_perkeo",
                      "j_canio", "j_triboulet", "j_yorick", "j_chicot",
                      "j_idol",
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
