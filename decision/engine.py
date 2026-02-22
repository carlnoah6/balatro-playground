"""Decision engine — orchestrates scoring, strategy, and LLM advisor.

This is the single entry point for ai-agent.py to make decisions.
It replaces the scattered decision logic in the original monolith.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from .scoring import (
    Card, Joker, HandLevel, ScoreBreakdown,
    find_best_hands, calculate_score,
)
from .search import evaluate_discard_options
from .strategy import (
    Archetype, ArchetypeTracker, GameContext,
    should_discard, choose_play, shop_decisions, evaluate_shop_item,
    build_context, get_boss_counter, should_reroll,
    JokerTier, JOKER_TIERS, TIER_SCORE_BONUS,
)
from .llm_advisor import (
    advise_discard, advise_shop, advise_boss,
    get_llm_stats,
)
from .build import BuildPlanner

USE_LLM = False  # All strategy knowledge is distilled into code

# When to escalate to LLM (thresholds)
LLM_HAND_RANK_THRESHOLD = 2   # Ask LLM only for very weak hands (High Card, Pair)
LLM_SCORE_MARGIN = 0.5        # Ask LLM only if best hand < 50% of target


@dataclass
class Decision:
    """A decision with action, parameters, and reasoning."""
    action: str          # "play", "discard", "buy", "skip", "select_blind"
    params: dict = field(default_factory=dict)
    reasoning: str = ""
    source: str = "rule"  # "rule" or "llm"
    score_estimate: float = 0.0
    hand_type: str = ""   # e.g. "Flush", "Two Pair"


class DecisionEngine:
    """Stateful decision engine that persists across the game."""

    def __init__(self):
        self.archetype = ArchetypeTracker()
        self.hand_levels = HandLevel()
        self.build_planner = BuildPlanner()
        self.game_count = 0
        self._last_ante = 0
        self._draw_pile: list[Card] = []  # Updated by agent via set_draw_pile()

    def set_draw_pile(self, draw_pile: list[Card]):
        """Update the draw pile (called by agent after deck_info command)."""
        self._draw_pile = draw_pile

    def new_game(self):
        """Reset for a new game run."""
        self.archetype = ArchetypeTracker()
        self.hand_levels = HandLevel()
        self.build_planner = BuildPlanner()
        self.game_count += 1
        self._last_ante = 0
        self._draw_pile = []

    def _build_context(self, state: dict) -> GameContext:
        """Build GameContext from raw game state."""
        ctx = build_context(state)
        ctx.archetype = self.archetype
        ctx.hand_levels = self.hand_levels
        ctx.draw_pile = self._draw_pile
        ctx.build_planner = self.build_planner

        # Sync build planner with current joker lineup
        joker_names = [j.name for j in ctx.jokers]
        self.build_planner.sync_jokers(joker_names)

        # Try commitment / check pivot at ante boundaries
        ante = ctx.ante
        if ante != self._last_ante:
            self._last_ante = ante
            committed = self.build_planner.try_commit(ante)
            if committed:
                print(f"[build] Committed to: {committed}")
            pivot = self.build_planner.check_pivot(ante)
            if pivot:
                print(f"[build] PIVOT to: {pivot}")

        return ctx

    def _should_use_llm(self, ctx: GameContext, best: Optional[ScoreBreakdown]) -> bool:
        """Decide whether this decision warrants an LLM call.
        
        Play/discard: only for truly desperate situations.
        Shop: handled separately (always uses LLM if enabled).
        """
        if not USE_LLM:
            return False
        if best is None:
            return True
        # Only escalate to LLM if hand is truly terrible AND score is way off
        if best.hand_rank <= 1 and ctx.chips_needed > 0 and best.final_score < ctx.chips_needed * 0.3:
            return True
        return False

    # ============================================================
    # Hand Phase
    # ============================================================

    def decide_hand(self, state: dict) -> Decision:
        """Decide what to do during SELECTING_HAND phase.

        Uses search-based evaluation when draw pile is available,
        falls back to heuristic rules otherwise.

        Returns a Decision with action="play" or action="discard".
        """
        ctx = self._build_context(state)

        # Track ante progression
        if ctx.ante > self._last_ante:
            self._last_ante = ctx.ante
            self.archetype.try_commit(ctx.ante)

        if not ctx.hand_cards:
            return Decision("play", {"cards": []}, "No cards in hand", "rule")

        boss_blind = ctx.boss_blind

        # === Search-based decision (primary path) ===
        if self._draw_pile:
            action, indices, expected, reason = evaluate_discard_options(
                hand_cards=ctx.hand_cards,
                jokers=ctx.jokers,
                hand_levels=ctx.hand_levels,
                draw_pile=self._draw_pile,
                chips_needed=ctx.chips_needed,
                hands_left=ctx.hands_left,
                discards_left=ctx.discards_left,
                boss_blind=boss_blind,
            )
            if action == "discard":
                self.archetype.signal_hand("", 0.5)
                return Decision("discard", {"cards": indices}, f"[search] {reason}", "rule")
            else:
                # Search says play — use its indices or find best hand
                best_hands = find_best_hands(ctx.hand_cards, ctx.jokers, ctx.hand_levels, top_n=1, boss_blind=boss_blind)
                if best_hands:
                    best = best_hands[0]
                    self.archetype.signal_hand(best.hand_type)
                    return Decision("play", {"cards": best.all_cards}, f"[search] {reason}", "rule",
                                    score_estimate=best.final_score,
                                    hand_type=best.hand_type)

        # === Fallback: heuristic path (no draw pile info) ===
        best_hands = find_best_hands(ctx.hand_cards, ctx.jokers, ctx.hand_levels, top_n=3, boss_blind=boss_blind)
        if not best_hands:
            indices = list(range(min(5, len(ctx.hand_cards))))
            return Decision("play", {"cards": indices}, "Fallback: play first cards", "rule")

        best = best_hands[0]

        # Rule-based discard check
        do_discard, disc_indices, disc_reason = should_discard(ctx)

        # LLM escalation for complex situations
        if self._should_use_llm(ctx, best) and ctx.discards_left > 0 and ctx.hands_left > 1:
            llm_result = advise_discard(ctx, best)
            if llm_result:
                action = llm_result.get("action", "play")
                reasoning = llm_result.get("reasoning", "LLM decision")

                if action == "discard":
                    cards = llm_result.get("params", {}).get("cards", [])
                    if cards and all(0 <= i < len(ctx.hand_cards) for i in cards):
                        self.archetype.signal_hand(best.hand_type, 0.5)
                        return Decision("discard", {"cards": cards}, reasoning, "llm")

                elif action == "play":
                    cards = llm_result.get("params", {}).get("cards", best.all_cards)
                    if cards and all(0 <= i < len(ctx.hand_cards) for i in cards):
                        self.archetype.signal_hand(best.hand_type)
                        return Decision("play", {"cards": cards}, reasoning, "llm",
                                        score_estimate=best.final_score,
                                        hand_type=best.hand_type)

        # Rule-based decision
        if do_discard:
            return Decision("discard", {"cards": disc_indices}, disc_reason, "rule")

        # Play best hand
        play_indices, play_reason = choose_play(ctx)
        self.archetype.signal_hand(best.hand_type)
        return Decision("play", {"cards": play_indices}, play_reason, "rule",
                        score_estimate=best.final_score,
                        hand_type=best.hand_type)

    # ============================================================
    # Shop Phase
    # ============================================================

    def decide_shop(self, state: dict) -> Decision:
        """Decide what to buy in the shop.

        Uses tier-aware scoring, economy management, and archetype synergy.
        LLM is consulted for nuanced decisions.

        Returns Decision with action="buy", "reroll", or "skip".
        """
        ctx = self._build_context(state)

        # Log build path status at shop entry
        print(f"[build] Shop entry:\n{self.build_planner.summary(ctx.ante)}", flush=True)

        if not ctx.shop_items:
            # Check if we should reroll
            do_reroll, reroll_reason = should_reroll(ctx)
            if do_reroll:
                return Decision("reroll", {}, reroll_reason, "rule")
            return Decision("skip", {}, "No items in shop", "rule")

        # Rule-based scoring (now with tier awareness + economy)
        item_scores = shop_decisions(ctx)

        # Lower threshold for high-tier items (S+/S get bought at 4.0+)
        buyable = []
        for idx, score, reason in item_scores:
            if idx >= len(ctx.shop_items):
                continue
            item = ctx.shop_items[idx]
            cost = item.get("cost", 0)
            if cost > ctx.dollars:
                continue
            name = item.get("name", "")
            tier = JOKER_TIERS.get(name)
            is_pack = "Pack" in name or item.get("type") == "Booster"
            # S+ tier: buy at any positive score
            if tier == JokerTier.S_PLUS and score >= 3.0:
                buyable.append((idx, score, reason))
            # S tier: lower threshold
            elif tier == JokerTier.S and score >= 4.0:
                buyable.append((idx, score, reason))
            # Packs: only buy if score >= 4.0 (Buffoon when needing jokers)
            elif is_pack and score >= 4.0:
                buyable.append((idx, score, reason))
            # Normal threshold for jokers/planets/tarots/vouchers
            elif not is_pack and score >= 5.0:
                buyable.append((idx, score, reason))

        # LLM for shop decisions — DISABLED: rule-based shop outperforms LLM
        # LLM tends to buy packs over jokers, leading to fewer scaling jokers
        # Re-enable after improving shop prompt with joker priority guidance
        if False and USE_LLM and ctx.shop_items:
            print(f"[engine] Calling LLM for shop decision (ante={ctx.ante}, ${ctx.dollars}, {len(ctx.shop_items)} items)", flush=True)
            llm_result = advise_shop(ctx, item_scores)
            if llm_result:
                print(f"[engine] LLM shop result: {llm_result.get('action', '?')}", flush=True)
                action = llm_result.get("action", "skip")
                reasoning = llm_result.get("reasoning", "LLM shop decision")

                if action == "buy":
                    idx = llm_result.get("params", {}).get("index", -1)
                    if 0 <= idx < len(ctx.shop_items):
                        item = ctx.shop_items[idx]
                        cost = item.get("cost", 0)
                        if cost <= ctx.dollars:
                            name = item.get("name", "?")
                            self.archetype.signal_joker(name)
                            return Decision("buy", {"index": idx}, reasoning, "llm")

                return Decision("skip", {}, reasoning, "llm")

        # Rule-based fallback
        if buyable:
            best_idx, best_score, best_reason = buyable[0]
            item = ctx.shop_items[best_idx]
            name = item.get("name", "?")
            self.archetype.signal_joker(name)
            return Decision("buy", {"index": best_idx},
                            f"Buy {name} (score {best_score:.1f}: {best_reason})", "rule")

        # Nothing to buy — consider reroll
        do_reroll, reroll_reason = should_reroll(ctx)
        if do_reroll:
            return Decision("reroll", {}, reroll_reason, "rule")

        return Decision("skip", {}, "Nothing worth buying", "rule")

    # ============================================================
    # Blind Select Phase
    # ============================================================

    def decide_blind(self, state: dict) -> Decision:
        """Decide on blind selection — play or skip.

        Skip logic (Small/Big only):
        - Valuable tags (Negative, Rare, Uncommon) worth skipping for
        - Only skip if confident we can beat Boss blind
        - Never skip Boss blind

        Returns Decision with action="select_blind" or "skip_blind".
        """
        ctx = self._build_context(state)
        blind_on_deck = state.get("blind_on_deck", "")
        boss_name = ctx.boss_blind

        # === Skip evaluation (Small/Big only) ===
        if blind_on_deck in ("Small", "Big"):
            skip_tags = state.get("skip_tags", {})
            tag = skip_tags.get(blind_on_deck, "")
            skip_reason = self._evaluate_skip_tag(tag, ctx)
            if skip_reason:
                return Decision("skip_blind", {"tag": tag},
                                f"Skip {blind_on_deck} for {tag}: {skip_reason}", "rule")

        # === Boss blind strategy ===
        if boss_name:
            # Get rule-based counter-strategy from knowledge base
            counter = get_boss_counter(boss_name, ctx)
            reasoning = (
                f"Boss: {boss_name} — {counter['effect']}. "
                f"Counter: {counter['counter']} "
                f"(danger {counter['danger_level']}/3"
                f"{', have counter joker' if counter.get('have_counter') else ''})"
            )

            # Only escalate to LLM for high-danger situations
            if USE_LLM and counter["danger_level"] >= 2:
                llm_result = advise_boss(ctx, boss_name)
                if llm_result:
                    llm_reasoning = llm_result.get("reasoning", "")
                    return Decision("select_blind", {"boss": boss_name},
                                    f"{reasoning} | LLM: {llm_reasoning}", "llm")

            return Decision("select_blind", {"boss": boss_name}, reasoning, "rule")

        return Decision("select_blind", {"boss": boss_name},
                        f"Entering blind (boss: {boss_name or 'none'})", "rule")

    # Tag values for skip evaluation
    VALUABLE_TAGS = {
        "tag_negative": "Negative Tag — free joker slot",
        "tag_rare": "Rare Tag — free rare joker",
        "tag_uncommon": "Uncommon Tag — free uncommon joker",
        "tag_investment": "Investment Tag — double money",
        "tag_ethereal": "Ethereal Tag — free spectral card",
        "tag_coupon": "Coupon Tag — free shop items",
        "tag_charm": "Charm Tag — free Mega Arcana Pack",
        "tag_meteor": "Meteor Tag — free Mega Celestial Pack",
        "tag_buffoon": "Buffoon Tag — free Mega Buffoon Pack",
    }

    def _evaluate_skip_tag(self, tag: str, ctx) -> str:
        """Evaluate whether a skip tag is worth skipping a blind for.

        Returns reason string if should skip, empty string if should play.
        """
        if not tag or tag not in self.VALUABLE_TAGS:
            return ""

        # Don't skip if we're struggling (low joker count early)
        if ctx.ante <= 1 and len(ctx.jokers) < 2:
            return ""  # Need the money from playing

        # Negative tag is always worth it (extra joker slot is huge)
        if tag == "tag_negative":
            return self.VALUABLE_TAGS[tag]

        # Rare/Uncommon joker tags: worth it if we have joker slots
        if tag in ("tag_rare", "tag_uncommon") and ctx.joker_space > 0:
            return self.VALUABLE_TAGS[tag]

        # Buffoon/Charm/Meteor packs: worth it mid-game
        if tag in ("tag_buffoon", "tag_charm", "tag_meteor") and ctx.ante >= 2:
            return self.VALUABLE_TAGS[tag]

        # Investment tag: worth it if we're building economy
        if tag == "tag_investment" and ctx.ante <= 4 and ctx.dollars >= 10:
            return self.VALUABLE_TAGS[tag]

        return ""

    # ============================================================
    # Utility
    # ============================================================

    def record_purchase(self, item_name: str):
        """Record a successful purchase for archetype + build tracking."""
        self.archetype.signal_joker(item_name)
        self.build_planner.on_joker_acquired(item_name)

    def record_planet(self, hand_type: str):
        """Record planet card usage."""
        self.archetype.signal_planet(hand_type)
        self.build_planner.on_planet_used(hand_type)
        level = self.hand_levels.levels.get(hand_type, 1)
        self.hand_levels.levels[hand_type] = level + 1

    def record_tarot(self, tarot_name: str):
        """Record tarot card usage for build tracking."""
        self.build_planner.on_tarot_used(tarot_name)

    def record_joker_sold(self, joker_name: str):
        """Record joker sale for build tracking."""
        self.build_planner.on_joker_sold(joker_name)

    def build_summary(self, ante: int) -> str:
        """Get build path status for logging."""
        return self.build_planner.summary(ante)

    def status_summary(self) -> str:
        """Get a human-readable status summary."""
        return (
            f"Build: {self.archetype.archetype_summary()} | "
            f"LLM: {get_llm_stats()}"
        )
