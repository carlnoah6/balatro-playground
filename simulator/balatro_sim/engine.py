"""Game engine — state machine that drives a Balatro game.

Accepts Actions, validates them, and returns new GameState.
Immutable: step() returns a new state, never modifies the input.
"""

from __future__ import annotations

from itertools import combinations
from typing import Optional

from .enums import Phase, HandType, Enhancement, BLIND_BASE_CHIPS
from .cards import Card, Deck
from .rng import RNGState
from .state import GameState
from .hands import evaluate_hand
from .scoring import calculate_score, HandLevels, ScoreResult
from .blinds import (
    BossBlind, BOSS_BLINDS, select_boss_blind,
    select_skip_tag, SkipTag,
)
from .actions import (
    Action, SelectBlind, SkipBlind, PlayHand, DiscardHand,
    BuyShopItem, SellJoker, SellConsumable, UseConsumable,
    RerollShop, LeaveShop,
)
from .shop import (
    ShopState, ShopJoker, ShopConsumable, ShopVoucher, ShopPack,
    ShopConfig, generate_shop, reroll_shop,
)


class GameEngine:
    """Drives the Balatro game state machine."""

    # --- Game Creation ---

    def new_game(self, seed: str, deck_type: str = "Red Deck", stake: int = 1) -> GameState:
        """Create a new game with the given seed."""
        rng = RNGState(seed)
        state = GameState(
            seed=seed,
            deck_type=deck_type,
            stake=stake,
            rng=rng,
            phase=Phase.BLIND_SELECT,
            ante=1,
            round_num=0,
            blind_type="Small",
            dollars=4,
            hand_levels=HandLevels(),
        )

        # Build starting deck
        deck = Deck()
        state.full_deck = list(deck.cards)

        # Apply deck-specific modifiers
        state = self._apply_deck_type(state)

        # Select boss blind for ante 1
        state = self._select_boss_blind(state)

        # Set blind target
        state.blind_chips = state.get_blind_target()

        return state

    # --- Core Interface ---

    def step(self, state: GameState, action: Action) -> GameState:
        """Execute an action and return the new state. Does not modify input."""
        s = state.copy()

        if s.phase == Phase.BLIND_SELECT:
            return self._step_blind_select(s, action)
        elif s.phase == Phase.PLAY_HAND:
            return self._step_play_hand(s, action)
        elif s.phase == Phase.SHOP:
            return self._step_shop(s, action)
        elif s.phase == Phase.GAME_OVER:
            return s  # No actions in terminal state
        else:
            raise ValueError(f"Unknown phase: {s.phase}")

    def get_legal_actions(self, state: GameState) -> list[Action]:
        """Get all legal actions for the current state."""
        if state.phase == Phase.BLIND_SELECT:
            return self._legal_blind_select(state)
        elif state.phase == Phase.PLAY_HAND:
            return self._legal_play_hand(state)
        elif state.phase == Phase.SHOP:
            return self._legal_shop(state)
        else:
            return []

    def is_terminal(self, state: GameState) -> bool:
        return state.phase == Phase.GAME_OVER

    def get_reward(self, state: GameState) -> float:
        """Terminal reward. 1.0 for win, 0.0 for loss, ante-based for intermediate."""
        if state.won is True:
            return 1.0
        elif state.won is False:
            return state.ante / 8.0 * 0.5  # Partial credit based on ante reached
        return 0.0

    # --- Blind Select Phase ---

    def _step_blind_select(self, s: GameState, action: Action) -> GameState:
        if isinstance(action, SelectBlind):
            # Start the round: shuffle deck, deal hand
            s = self._start_round(s)
            s.phase = Phase.PLAY_HAND

            # Apply boss blind effects at round start (if Boss blind)
            if s.round_num == 2 and s.boss_blind_key:
                boss = BOSS_BLINDS.get(s.boss_blind_key)
                if boss:
                    s = boss.apply_round_start(s)
                    s = boss.apply_debuffs(s)

            return s
        elif isinstance(action, SkipBlind):
            if s.round_num >= 2:
                raise ValueError("Cannot skip Boss blind")
            # Award skip tag
            tag = select_skip_tag(s.rng, s.ante)
            s.skip_tags.append(tag.value)
            # Apply immediate tag effects
            s = self._apply_skip_tag(s, tag)
            # Skip: advance to next blind
            s = self._advance_blind(s)
            return s
        else:
            raise ValueError(f"Invalid action for BLIND_SELECT: {type(action)}")

    def _legal_blind_select(self, state: GameState) -> list[Action]:
        actions: list[Action] = [SelectBlind()]
        if state.round_num < 2:  # Can skip Small and Big
            actions.append(SkipBlind())
        return actions

    # --- Play Hand Phase ---

    def _step_play_hand(self, s: GameState, action: Action) -> GameState:
        if isinstance(action, PlayHand):
            return self._do_play_hand(s, action.card_indices)
        elif isinstance(action, DiscardHand):
            return self._do_discard(s, action.card_indices)
        else:
            raise ValueError(f"Invalid action for PLAY_HAND: {type(action)}")

    def _legal_play_hand(self, state: GameState) -> list[Action]:
        actions: list[Action] = []
        n = len(state.hand)
        boss = self._get_active_boss(state)

        # Play actions: 1-5 cards from hand
        max_play = min(5, n)
        for size in range(1, max_play + 1):
            for combo in combinations(range(n), size):
                action = PlayHand(card_indices=tuple(combo))
                # Filter by boss restrictions
                if boss:
                    error = boss.validate_play(state, tuple(combo))
                    if error:
                        continue
                actions.append(action)

        # Discard actions (if discards remaining)
        if state.discards_left > 0 and n > 0:
            max_discard = min(5, n)
            for size in range(1, max_discard + 1):
                for combo in combinations(range(n), size):
                    actions.append(DiscardHand(card_indices=tuple(combo)))

        return actions

    def _do_play_hand(self, s: GameState, indices: tuple[int, ...]) -> GameState:
        """Play selected cards, evaluate hand, score, check win/loss."""
        if not indices:
            raise ValueError("Must play at least 1 card")
        if len(indices) > 5:
            raise ValueError("Cannot play more than 5 cards")

        # Boss blind play validation
        boss = self._get_active_boss(s)
        if boss:
            error = boss.validate_play(s, indices)
            if error:
                raise ValueError(error)

        # Extract played cards
        played = [s.hand[i] for i in sorted(indices)]

        # Evaluate hand type
        hand_type, scoring_indices = evaluate_hand(played)

        # Track hand types for Eye/Mouth bosses
        s.hands_played_this_round.append(hand_type.value)
        if not s.first_hand_type:
            s.first_hand_type = hand_type.value

        # Calculate held cards (remaining in hand)
        played_set = set(indices)
        held = [s.hand[i] for i in range(len(s.hand)) if i not in played_set]

        # Update joker extra state for scoring context
        for j in s.jokers:
            j.extra["discards_left"] = s.discards_left
            j.extra["remaining_deck"] = len(s.draw_pile)
            j.extra["is_last_hand"] = (s.hands_left == 1)

        # Build game_state dict for scoring context
        _game_state = {
            "discards_left": s.discards_left,
            "remaining_deck": len(s.draw_pile),
            "dollars": s.dollars,
            "hands_played_counts": {},  # TODO: track per-hand-type play counts
            "stone_cards_in_deck": sum(1 for c in s.full_deck if c.enhancement == Enhancement.STONE),
            "steel_cards_in_deck": sum(1 for c in s.full_deck if c.enhancement == Enhancement.STEEL),
            "glass_cards_in_deck": sum(1 for c in s.full_deck if c.enhancement == Enhancement.GLASS),
            "deck_size": len(s.full_deck),
        }

        # Score — boss may modify base chips/mult
        result = calculate_score(
            played_cards=played,
            hand_type=hand_type,
            scoring_indices=scoring_indices,
            hand_levels=s.hand_levels,
            held_cards=held,
            jokers=s.jokers,
            game_state=_game_state,
        )

        # Boss: Flint halves the final score
        if boss and boss.key == "bl_flint":
            result = ScoreResult(
                hand_type=result.hand_type,
                chips=result.chips / 2,
                mult=result.mult / 2,
                final_score=max(0, int((result.chips / 2) * (result.mult / 2))),
                scoring_indices=result.scoring_indices,
            )

        # Update state
        s.round_chips += int(result.final_score)
        s.hands_left -= 1
        s.hands_played_total += 1

        # Move played cards to discard pile
        for i in sorted(indices, reverse=True):
            card = s.hand.pop(i)
            s.discard_pile.append(card)

        # Boss post-play effects (Hook discards, Ox money, Arm level-down)
        if boss:
            s = boss.on_post_play(s)
            # Ox: playing the target hand sets money to $0
            if boss.key == "bl_ox" and hand_type.value == s.ox_target_hand:
                s.dollars = 0
            # Arm: decrease level of played hand type
            if boss.key == "bl_arm":
                current_level = s.hand_levels.levels.get(hand_type.value, 1)
                if current_level > 1:
                    s.hand_levels.levels[hand_type.value] = current_level - 1

        # Check if blind is beaten
        if s.round_chips >= s.blind_chips:
            return self._win_round(s)

        # Check if out of hands
        if s.hands_left <= 0:
            return self._lose_game(s)

        # Draw back up to hand_size
        s = self._draw_to_hand_size(s)

        # Boss: apply debuffs to newly drawn cards
        if boss:
            s = boss.apply_debuffs(s)

        return s

    def _do_discard(self, s: GameState, indices: tuple[int, ...]) -> GameState:
        """Discard selected cards and draw replacements."""
        if s.discards_left <= 0:
            raise ValueError("No discards remaining")
        if not indices:
            raise ValueError("Must discard at least 1 card")
        if len(indices) > 5:
            raise ValueError("Cannot discard more than 5 cards")

        s.discards_left -= 1

        # Move discarded cards
        for i in sorted(indices, reverse=True):
            card = s.hand.pop(i)
            s.discard_pile.append(card)

        # Draw replacements
        s = self._draw_to_hand_size(s)

        # Boss post-discard effects
        boss = self._get_active_boss(s)
        if boss:
            s = boss.on_post_discard(s)
            s = boss.apply_debuffs(s)

        return s

    # --- Shop Phase ---

    def _step_shop(self, s: GameState, action: Action) -> GameState:
        if isinstance(action, LeaveShop):
            return self._leave_shop(s)
        elif isinstance(action, BuyShopItem):
            return self._buy_item(s, action.item_index)
        elif isinstance(action, SellJoker):
            return self._sell_joker(s, action.joker_index)
        elif isinstance(action, RerollShop):
            return self._reroll_shop(s)
        else:
            raise ValueError(f"Invalid action for SHOP: {type(action)}")

    def _legal_shop(self, state: GameState) -> list[Action]:
        actions: list[Action] = [LeaveShop()]

        # Buy items from shop state
        if hasattr(state, '_shop_state') and state._shop_state:
            shop = state._shop_state
            for i, item in enumerate(shop.card_slots):
                cost = self._get_shop_item_cost(item)
                if state.dollars >= cost:
                    # Check capacity
                    if isinstance(item, ShopJoker) and len(state.jokers) < state.joker_slots:
                        actions.append(BuyShopItem(item_index=i))
                    elif isinstance(item, ShopConsumable) and len(state.consumables) < state.consumable_slots:
                        actions.append(BuyShopItem(item_index=i))
            # Voucher
            if shop.voucher and state.dollars >= shop.voucher.cost:
                actions.append(BuyShopItem(item_index=len(shop.card_slots)))
            # Packs (index after card_slots + voucher)
            offset = len(shop.card_slots) + (1 if shop.voucher else 0)
            for i, pack in enumerate(shop.packs):
                if state.dollars >= pack.cost:
                    actions.append(BuyShopItem(item_index=offset + i))
        else:
            # Fallback for legacy dict-based shop_items
            for i, item in enumerate(state.shop_items):
                if isinstance(item, dict) and state.dollars >= item.get("cost", 999):
                    actions.append(BuyShopItem(item_index=i))

        # Sell jokers
        for i in range(len(state.jokers)):
            if not state.jokers[i].eternal:
                actions.append(SellJoker(joker_index=i))

        # Reroll
        cost = state.reroll_cost if state.free_rerolls <= 0 else 0
        if state.dollars >= cost:
            actions.append(RerollShop())

        return actions

    # --- Round Management ---

    def _start_round(self, s: GameState) -> GameState:
        """Shuffle deck and deal initial hand for a new round."""
        s.round_chips = 0
        s.hands_left = 4  # Base hands
        s.discards_left = 3  # Base discards
        s.hands_played_this_round = []
        s.first_hand_type = ""
        s.face_down_indices = set()

        # Apply deck type bonuses
        if s.deck_type == "Red Deck":
            s.discards_left += 1
        elif s.deck_type == "Blue Deck":
            s.hands_left += 1

        # Boss blind modifications to hands/discards
        boss = self._get_active_boss(s)
        if boss:
            if boss.key == "bl_water":
                s.discards_left = 0
            elif boss.key == "bl_needle":
                s.hands_left = 1
            # Manacle hand_size reduction is handled in boss.apply_round_start

        # Combine all cards back into draw pile
        all_cards = list(s.full_deck)  # Use full deck template
        s.discard_pile.clear()
        s.played_this_round = []

        # Shuffle — Immolate key: "nr" + ante (no round_num)
        from balatro_sim.rng import node_key, RType
        shuffle_key = node_key(RType.ShuffleNewRound, ante=s.ante)
        if s.rng:
            s.draw_pile = s.rng.shuffle(shuffle_key, all_cards)
        else:
            import random
            s.draw_pile = list(all_cards)
            random.shuffle(s.draw_pile)

        # Deal hand
        s.hand = []
        s = self._draw_to_hand_size(s)

        return s

    def _draw_to_hand_size(self, s: GameState) -> GameState:
        """Draw cards until hand is at hand_size (or draw pile empty)."""
        while len(s.hand) < s.hand_size and s.draw_pile:
            s.hand.append(s.draw_pile.pop(0))
        return s

    def _win_round(self, s: GameState) -> GameState:
        """Handle winning a round (beating the blind)."""
        s.rounds_won += 1

        # Cash-out economy (matches real Balatro):
        # 1. Base blind reward
        blind_money = {0: 3, 1: 4, 2: 5}  # Small/Big/Boss
        s.dollars += blind_money.get(s.round_num, 3)

        # 2. Bonus for remaining hands ($1 per unused hand)
        s.dollars += s.hands_left

        # 3. Interest: $1 per $5, max $5 (25 cap)
        interest = min(s.dollars // 5, 5)
        s.dollars += interest

        # Clear boss round tracking
        s.hands_played_this_round = []
        s.first_hand_type = ""
        s.face_down_indices = set()
        # Clear debuffs from all cards
        for card in s.full_deck:
            card.debuffed = False
        for card in s.hand:
            card.debuffed = False

        # Restore hand size if Manacle reduced it
        boss = self._get_active_boss(s)
        if boss and boss.key == "bl_manacle":
            s.hand_size += 1  # Undo the -1 from _start_round

        # Transition to shop
        s.phase = Phase.SHOP
        s.shop_items = self._generate_shop(s)

        return s

    def _lose_game(self, s: GameState) -> GameState:
        """Handle losing (ran out of hands without beating blind)."""
        s.phase = Phase.GAME_OVER
        s.won = False
        return s

    def _leave_shop(self, s: GameState) -> GameState:
        """Leave shop and advance to next blind."""
        s.shop_items = []
        s = self._advance_blind(s)
        return s

    def _advance_blind(self, s: GameState) -> GameState:
        """Move to the next blind (or next ante)."""
        if s.round_num < 2:
            s.round_num += 1
            s.blind_type = {0: "Small", 1: "Big", 2: "Boss"}[s.round_num]
        else:
            # Completed Boss blind — advance ante
            s.ante += 1
            s.round_num = 0
            s.blind_type = "Small"
            s.boss_blind_key = ""

            if s.ante > 8:
                s.phase = Phase.GAME_OVER
                s.won = True
                return s

            # Select boss blind for the new ante
            s = self._select_boss_blind(s)

        # Apply boss chip modifier for Boss blinds
        base_chips = s.get_blind_target()
        if s.round_num == 2 and s.boss_blind_key:
            boss = BOSS_BLINDS.get(s.boss_blind_key)
            if boss:
                base_chips = boss.modify_blind_chips(base_chips)
        s.blind_chips = base_chips

        s.phase = Phase.BLIND_SELECT
        return s

    # --- Boss Blind Helpers ---

    def _get_active_boss(self, s: GameState) -> Optional[BossBlind]:
        """Get the active boss blind if we're in a Boss round."""
        if s.round_num == 2 and s.boss_blind_key:
            return BOSS_BLINDS.get(s.boss_blind_key)
        return None

    def _select_boss_blind(self, s: GameState) -> GameState:
        """Select a boss blind for the current ante using RNG."""
        boss = select_boss_blind(s.ante, s.rng)
        s.boss_blind_key = boss.key
        s.blind_name = boss.name

        # Ox: pick a random hand type as the target
        if boss.key == "bl_ox":
            common_hands = [
                HandType.HIGH_CARD, HandType.PAIR, HandType.TWO_PAIR,
                HandType.THREE_OF_A_KIND, HandType.STRAIGHT, HandType.FLUSH,
                HandType.FULL_HOUSE,
            ]
            if s.rng:
                s.ox_target_hand = s.rng.random_element(
                    f"ox_target_{s.ante}", common_hands
                ).value
            else:
                import random
                s.ox_target_hand = random.choice(common_hands).value

        return s

    def _apply_skip_tag(self, s: GameState, tag: SkipTag) -> GameState:
        """Apply immediate effects of a skip tag."""
        if tag == SkipTag.HANDY:
            s.dollars += s.hands_played_total
        elif tag == SkipTag.GARBAGE:
            # +$1 per unused discard this run (approximate: current discards_left)
            s.dollars += s.discards_left
        elif tag == SkipTag.ECONOMY:
            # Max interest cap +$5 — tracked via state, simplified here
            s.dollars += 5
        elif tag == SkipTag.D6:
            s.free_rerolls += 4
        elif tag == SkipTag.JUGGLE:
            s.hand_size += 3  # Temporary, but we simplify to permanent for now
        elif tag == SkipTag.INVESTMENT:
            s.dollars += 25
        elif tag == SkipTag.COUPON:
            # All shop items free next shop — simplified: give $20
            s.dollars += 20
        elif tag == SkipTag.BOSS:
            # Reroll boss blind
            s = self._select_boss_blind(s)
        # Other tags: effect deferred to shop/pack opening (not yet implemented)
        return s

    # --- Shop Generation ---

    def _build_shop_config(self, s: GameState) -> ShopConfig:
        """Build ShopConfig from current game state."""
        used_jokers = {j.key: True for j in s.jokers}
        used_vouchers = {v: True for v in s.vouchers}
        has_showman = any(j.key == "j_ring_master" for j in s.jokers)

        # Voucher effects on rates
        joker_max = 2
        if used_vouchers.get("v_overstock_plus"):
            joker_max = 4
        elif used_vouchers.get("v_overstock_norm"):
            joker_max = 3

        edition_rate = 1.0
        if used_vouchers.get("v_glow_up"):
            edition_rate = 4.0
        elif used_vouchers.get("v_hone"):
            edition_rate = 2.0

        spectral_rate = 0.0
        if used_vouchers.get("v_omen_globe"):
            spectral_rate = 4.0
        elif used_vouchers.get("v_crystal_ball"):
            spectral_rate = 2.0

        tarot_rate = 4.0
        if used_vouchers.get("v_tarot_tycoon"):
            tarot_rate = 8.0
        elif used_vouchers.get("v_tarot_merchant"):
            tarot_rate = 6.0

        planet_rate = 4.0
        if used_vouchers.get("v_planet_tycoon"):
            planet_rate = 8.0
        elif used_vouchers.get("v_planet_merchant"):
            planet_rate = 6.0

        # Ghost Deck: spectral_rate = 2
        if s.deck_type == "Ghost Deck":
            spectral_rate = max(spectral_rate, 2.0)

        # Stake modifiers for eternal/perishable/rental
        enable_eternals = s.stake >= 3
        enable_perishables = s.stake >= 5
        enable_rentals = s.stake >= 7

        return ShopConfig(
            joker_rate=20.0,
            tarot_rate=tarot_rate,
            planet_rate=planet_rate,
            spectral_rate=spectral_rate,
            edition_rate=edition_rate,
            joker_max=joker_max,
            enable_eternals_in_shop=enable_eternals,
            enable_perishables_in_shop=enable_perishables,
            enable_rentals_in_shop=enable_rentals,
            has_illusion=bool(used_vouchers.get("v_illusion")),
            first_shop_buffoon=getattr(s, '_first_shop_buffoon', False),
            used_jokers=used_jokers,
            used_vouchers=used_vouchers,
            has_showman=has_showman,
        )

    def _generate_shop(self, s: GameState) -> list[dict]:
        """Generate shop using the full shop.py system.

        Returns legacy dict list for shop_items (backward compat),
        but also sets s._shop_state for the real ShopState.
        """
        config = self._build_shop_config(s)
        shop_state = generate_shop(s.rng, config, s.ante)
        s._shop_state = shop_state
        s._shop_config = config
        s.reroll_cost = shop_state.reroll_cost
        s.free_rerolls = shop_state.free_rerolls

        # Build legacy dict list for backward compat / serialization
        items = []
        for item in shop_state.card_slots:
            if isinstance(item, ShopJoker):
                items.append({"type": "joker", "key": item.key, "name": item.name, "cost": item.cost})
            elif isinstance(item, ShopConsumable):
                items.append({"type": "consumable", "key": item.key, "name": item.name, "cost": item.cost})
        if shop_state.voucher:
            items.append({"type": "voucher", "key": shop_state.voucher.key, "name": shop_state.voucher.name, "cost": shop_state.voucher.cost})
        for pack in shop_state.packs:
            items.append({"type": "pack", "key": pack.key, "name": pack.name, "cost": pack.cost})
        return items

    def _get_shop_item_cost(self, item) -> int:
        """Get cost of a shop item."""
        if isinstance(item, ShopJoker):
            return item.cost
        elif isinstance(item, ShopConsumable):
            return item.cost
        elif isinstance(item, ShopVoucher):
            return item.cost
        elif isinstance(item, ShopPack):
            return item.cost
        return 999

    def _buy_item(self, s: GameState, idx: int) -> GameState:
        """Buy a shop item and add it to inventory."""
        shop = getattr(s, '_shop_state', None)
        if not shop:
            # Legacy fallback
            if idx >= len(s.shop_items):
                raise ValueError(f"Invalid shop item index: {idx}")
            item = s.shop_items[idx]
            cost = item.get("cost", 0)
            if s.dollars < cost:
                raise ValueError(f"Not enough money: have ${s.dollars}, need ${cost}")
            s.dollars -= cost
            s.shop_items.pop(idx)
            return s

        # Determine which item is being bought
        n_slots = len(shop.card_slots)
        has_voucher = shop.voucher is not None
        voucher_idx = n_slots
        pack_offset = n_slots + (1 if has_voucher else 0)

        if idx < n_slots:
            # Buying a card slot item (joker or consumable)
            item = shop.card_slots[idx]
            cost = self._get_shop_item_cost(item)
            if s.dollars < cost:
                raise ValueError(f"Not enough money: have ${s.dollars}, need ${cost}")

            if isinstance(item, ShopJoker):
                if len(s.jokers) >= s.joker_slots:
                    raise ValueError("Joker slots full")
                from .cards import JokerCard
                joker = JokerCard(
                    key=item.key,
                    name=item.name,
                    edition=item.edition,
                    eternal=item.eternal,
                    perishable=item.perishable,
                    rental=item.rental,
                    sell_value=max(1, cost // 2),
                )
                s.jokers.append(joker)
            elif isinstance(item, ShopConsumable):
                if len(s.consumables) >= s.consumable_slots:
                    raise ValueError("Consumable slots full")
                from .cards import ConsumableCard
                consumable = ConsumableCard(
                    key=item.key,
                    name=item.name,
                    card_type=item.card_type,
                )
                s.consumables.append(consumable)

            s.dollars -= cost
            shop.card_slots.pop(idx)

        elif has_voucher and idx == voucher_idx:
            # Buying voucher
            v = shop.voucher
            if s.dollars < v.cost:
                raise ValueError(f"Not enough money for voucher: have ${s.dollars}, need ${v.cost}")
            s.dollars -= v.cost
            s.vouchers.append(v.key)
            shop.voucher = None

        else:
            # Buying a pack
            pack_idx = idx - pack_offset
            if pack_idx < 0 or pack_idx >= len(shop.packs):
                raise ValueError(f"Invalid pack index: {idx}")
            pack = shop.packs[pack_idx]
            if s.dollars < pack.cost:
                raise ValueError(f"Not enough money for pack: have ${s.dollars}, need ${pack.cost}")
            s.dollars -= pack.cost
            # Simplified: pack opening gives a random planet card (level up)
            if pack.pack_type in ("Celestial",):
                from .enums import HandType
                import random
                ht = random.choice(list(HandType))
                s.hand_levels.level_up(ht)
            shop.packs.pop(pack_idx)

        # Sync legacy shop_items
        s.shop_items = self._rebuild_shop_items(shop)
        return s

    def _rebuild_shop_items(self, shop: ShopState) -> list[dict]:
        """Rebuild legacy shop_items list from ShopState."""
        items = []
        for item in shop.card_slots:
            if isinstance(item, ShopJoker):
                items.append({"type": "joker", "key": item.key, "name": item.name, "cost": item.cost})
            elif isinstance(item, ShopConsumable):
                items.append({"type": "consumable", "key": item.key, "name": item.name, "cost": item.cost})
        if shop.voucher:
            items.append({"type": "voucher", "key": shop.voucher.key, "name": shop.voucher.name, "cost": shop.voucher.cost})
        for pack in shop.packs:
            items.append({"type": "pack", "key": pack.key, "name": pack.name, "cost": pack.cost})
        return items

    def _sell_joker(self, s: GameState, idx: int) -> GameState:
        """Sell a joker for its sell value."""
        if idx >= len(s.jokers):
            raise ValueError(f"Invalid joker index: {idx}")
        joker = s.jokers[idx]
        if joker.eternal:
            raise ValueError("Cannot sell Eternal joker")
        s.dollars += joker.sell_value
        s.jokers.pop(idx)
        return s

    def _reroll_shop(self, s: GameState) -> GameState:
        """Reroll shop items using real shop system."""
        shop = getattr(s, '_shop_state', None)
        config = getattr(s, '_shop_config', None)
        if shop and config and s.rng:
            new_shop, cost = reroll_shop(s.rng, shop, config, s.ante, s.dollars)
            s.dollars -= cost
            s._shop_state = new_shop
            s.shop_items = self._rebuild_shop_items(new_shop)
        else:
            # Legacy fallback
            if s.free_rerolls > 0:
                s.free_rerolls -= 1
            else:
                if s.dollars < s.reroll_cost:
                    raise ValueError("Not enough money to reroll")
                s.dollars -= s.reroll_cost
            s.shop_items = self._generate_shop(s)
        return s

    # --- Deck Type Modifiers ---

    def _apply_deck_type(self, s: GameState) -> GameState:
        """Apply starting deck modifications."""
        if s.deck_type == "Red Deck":
            pass  # +1 discard (applied in _start_round)
        elif s.deck_type == "Blue Deck":
            pass  # +1 hand (applied in _start_round)
        elif s.deck_type == "Yellow Deck":
            s.dollars += 10  # Start with extra money
        elif s.deck_type == "Green Deck":
            pass  # No interest cap (handled in _win_round)
        elif s.deck_type == "Abandoned Deck":
            # Remove face cards
            s.full_deck = [c for c in s.full_deck if not c.is_face]
        elif s.deck_type == "Checkered Deck":
            # All Spades and Hearts
            from .enums import Suit
            new_deck = []
            for c in s.full_deck:
                if c.suit in (Suit.CLUBS, Suit.DIAMONDS):
                    new_suit = Suit.SPADES if c.suit == Suit.CLUBS else Suit.HEARTS
                    new_deck.append(Card(c.rank, new_suit, c.edition, c.enhancement, c.seal))
                else:
                    new_deck.append(c)
            s.full_deck = new_deck
        # More deck types can be added
        return s

    # --- Utility ---

    def evaluate_possible_hands(
        self, state: GameState, top_n: int = 5
    ) -> list[tuple[tuple[int, ...], ScoreResult]]:
        """Evaluate all possible hands and return top N by score.

        Returns list of (card_indices, ScoreResult) sorted by score descending.
        Useful for AI decision making.
        """
        results = []
        n = len(state.hand)
        max_play = min(5, n)

        for size in range(1, max_play + 1):
            for combo in combinations(range(n), size):
                played = [state.hand[i] for i in combo]
                hand_type, scoring_idx = evaluate_hand(played)
                held = [state.hand[i] for i in range(n) if i not in combo]
                result = calculate_score(
                    played_cards=played,
                    hand_type=hand_type,
                    scoring_indices=scoring_idx,
                    hand_levels=state.hand_levels,
                    held_cards=held,
                    jokers=state.jokers,
                )
                results.append((combo, result))

        results.sort(key=lambda x: x[1].final_score, reverse=True)
        return results[:top_n]
