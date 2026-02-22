"""Build Path system — Bayesian build planning for Balatro.

Instead of greedy per-hand optimization, this module maintains a probability
distribution over possible "endgame blueprints" (build paths) and guides
shop/discard/blind decisions toward the most feasible path.

Each BuildPath represents a proven winning strategy from the community
knowledge base, with specific core jokers, target hands, and scaling ceiling.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# ============================================================
# Build Path Definitions
# ============================================================

@dataclass
class BuildPath:
    """A proven endgame blueprint."""
    name: str
    # Core jokers — need at least min_core of these to make the build work
    core_jokers: list[str]
    min_core: int = 2  # minimum core jokers needed
    # Flex jokers — nice to have, strengthen the build
    flex_jokers: list[str] = field(default_factory=list)
    # Target hand types (in priority order)
    target_hands: list[str] = field(default_factory=list)
    # Planet cards to prioritize
    target_planets: list[str] = field(default_factory=list)
    # Deck modifications needed (suit conversion, enhancement, etc.)
    deck_mods: list[str] = field(default_factory=list)
    # Scaling ceiling: max ante this build can realistically reach
    ceiling: int = 8
    # How hard is this build to assemble? 0=easy, 1=very hard
    difficulty: float = 0.5
    # Tags for categorization
    tags: list[str] = field(default_factory=list)


# 11 community-proven build paths
BUILD_PATHS: list[BuildPath] = [
    BuildPath(
        name="Flush + Tribe",
        core_jokers=["The Tribe", "Smeared Joker"],
        min_core=1,
        flex_jokers=["Splash", "Four Fingers", "Lusty Joker", "Greedy Joker",
                     "Gluttonous Joker", "Wrathful Joker", "Ancient Joker"],
        target_hands=["Flush", "Flush Five", "Flush House"],
        target_planets=["Jupiter"],
        deck_mods=["suit_convert"],
        ceiling=8,
        difficulty=0.3,
        tags=["flush", "xmult"],
    ),
    BuildPath(
        name="Flush + Bloodstone",
        core_jokers=["Bloodstone", "Smeared Joker", "Oops! All 6s"],
        min_core=2,
        flex_jokers=["The Tribe", "Lusty Joker", "Lucky Cat", "Four Fingers"],
        target_hands=["Flush", "Flush Five", "Flush House"],
        target_planets=["Jupiter"],
        deck_mods=["suit_convert_hearts"],
        ceiling=9,
        difficulty=0.5,
        tags=["flush", "lucky", "xmult"],
    ),
    BuildPath(
        name="Pairs + Duo",
        core_jokers=["The Duo", "Spare Trousers"],
        min_core=1,
        flex_jokers=["Half Joker", "Card Sharp", "Jolly Joker", "Smiley Face",
                     "Mime", "Photograph"],
        target_hands=["Pair", "Two Pair", "Full House"],
        target_planets=["Mercury", "Uranus", "Earth"],
        deck_mods=[],
        ceiling=7,
        difficulty=0.2,
        tags=["pairs", "xmult"],
    ),
    BuildPath(
        name="Pairs + Blueprint",
        core_jokers=["The Duo", "Blueprint"],
        min_core=2,
        flex_jokers=["Brainstorm", "Spare Trousers", "Card Sharp", "Half Joker"],
        target_hands=["Pair", "Two Pair", "Full House"],
        target_planets=["Mercury", "Uranus"],
        deck_mods=[],
        ceiling=9,
        difficulty=0.6,
        tags=["pairs", "copy", "xmult"],
    ),
    BuildPath(
        name="Straight + Shortcut",
        core_jokers=["Shortcut", "The Order"],
        min_core=1,
        flex_jokers=["Four Fingers", "Runner", "Wee Joker", "Hack"],
        target_hands=["Straight", "Straight Flush"],
        target_planets=["Saturn"],
        deck_mods=[],
        ceiling=8,
        difficulty=0.4,
        tags=["straight", "xmult"],
    ),
    BuildPath(
        name="Face Cards + Baron",
        core_jokers=["Baron", "Sock and Buskin"],
        min_core=1,
        flex_jokers=["Photograph", "Scary Face", "Smiley Face", "Pareidolia",
                     "Triboulet", "Blueprint"],
        target_hands=["Pair", "Two Pair", "Full House"],
        target_planets=["Mercury", "Earth"],
        deck_mods=["face_heavy"],
        ceiling=8,
        difficulty=0.4,
        tags=["face", "xmult", "held"],
    ),
    BuildPath(
        name="Steel Build",
        core_jokers=["Steel Joker", "Driver's License"],
        min_core=1,
        flex_jokers=["Baron", "Mime", "Blueprint", "Hack"],
        target_hands=["Pair", "High Card"],
        target_planets=["Mercury"],
        deck_mods=["steel_enhance"],
        ceiling=9,
        difficulty=0.5,
        tags=["steel", "xmult", "held"],
    ),
    BuildPath(
        name="Hologram + DNA",
        core_jokers=["Hologram", "DNA"],
        min_core=2,
        flex_jokers=["Blueprint", "Brainstorm", "Constellation", "Campfire"],
        target_hands=["Pair", "Flush"],
        target_planets=["Mercury", "Jupiter"],
        deck_mods=[],
        ceiling=9,
        difficulty=0.6,
        tags=["scaling", "xmult"],
    ),
    BuildPath(
        name="Blueprint Chain",
        core_jokers=["Blueprint", "Brainstorm"],
        min_core=2,
        flex_jokers=["The Duo", "The Trio", "The Family", "The Order",
                     "The Tribe", "Baron", "Steel Joker"],
        target_hands=[],  # any hand works
        target_planets=[],
        deck_mods=[],
        ceiling=10,  # infinite potential
        difficulty=0.7,
        tags=["copy", "xmult"],
    ),
    BuildPath(
        name="xMult Stack",
        # This is a flexible path — any 3 xMult jokers work
        core_jokers=["The Duo", "The Trio", "The Family", "The Order",
                     "The Tribe", "Card Sharp", "Bloodstone", "Cavendish"],
        min_core=3,  # need 3 of these
        flex_jokers=["Blueprint", "Brainstorm", "Hologram", "Campfire",
                     "Glass Joker", "Lucky Cat", "Obelisk"],
        target_hands=[],
        target_planets=[],
        deck_mods=[],
        ceiling=9,
        difficulty=0.4,
        tags=["xmult", "flexible"],
    ),
    BuildPath(
        name="Lucky Build",
        core_jokers=["Oops! All 6s", "Bloodstone", "Lucky Cat"],
        min_core=2,
        flex_jokers=["Lusty Joker", "Smeared Joker", "The Tribe"],
        target_hands=["Flush"],
        target_planets=["Jupiter"],
        deck_mods=["lucky_enhance"],
        ceiling=9,
        difficulty=0.5,
        tags=["lucky", "xmult"],
    ),
]


# ============================================================
# Build Path State Tracking
# ============================================================

@dataclass
class BuildPathState:
    """Tracks feasibility of a single build path during a run."""
    path: BuildPath
    # What we own
    owned_core: list[str] = field(default_factory=list)
    owned_flex: list[str] = field(default_factory=list)
    # Deck modification progress (0-1)
    deck_ready: float = 0.0
    # Hand level bonus from planet cards (0-1)
    hand_level_bonus: float = 0.0

    @property
    def missing_core(self) -> list[str]:
        return [j for j in self.path.core_jokers if j not in self.owned_core]

    @property
    def progress(self) -> float:
        """How complete is this build? 0-1."""
        needed = self.path.min_core
        owned = len(self.owned_core)
        core_pct = min(owned / needed, 1.0) if needed > 0 else 0.0

        flex_pct = min(len(self.owned_flex) / 2.0, 1.0)

        return (core_pct * 0.6
                + flex_pct * 0.2
                + self.deck_ready * 0.1
                + self.hand_level_bonus * 0.1)

    def feasibility(self, ante: int) -> float:
        """Current feasibility score (0-1), accounting for time pressure."""
        prog = self.progress

        # Time factor: builds that aren't progressing by ante 3 become less viable
        if ante <= 2:
            time_f = 1.0
        elif prog >= 0.5:
            time_f = 1.0
        else:
            # Linear decay: at ante 3 with 0 progress = 0.6, ante 5 = 0.2
            time_f = max(0.1, 1.0 - (ante - 2) * 0.2 * (1.0 - prog))

        # Ceiling factor: low-ceiling builds are less attractive
        ceil = self.path.ceiling
        if ceil >= 8:
            ceil_f = 1.0
        elif ceil == 7:
            ceil_f = 0.7
        else:
            ceil_f = 0.4

        return prog * time_f * ceil_f


@dataclass
class BuildPlanner:
    """Maintains Bayesian build path state across the entire run."""
    paths: list[BuildPathState] = field(default_factory=list)
    _committed: Optional[str] = None  # locked-in path name after commitment
    _commit_ante: int = 0

    def __post_init__(self):
        if not self.paths:
            self.paths = [BuildPathState(path=p) for p in BUILD_PATHS]

    # ----------------------------------------------------------
    # Queries
    # ----------------------------------------------------------

    def best_path(self, ante: int = 1) -> BuildPathState:
        """Return the most feasible build path."""
        if self._committed:
            for ps in self.paths:
                if ps.path.name == self._committed:
                    return ps
        return max(self.paths, key=lambda ps: ps.feasibility(ante))

    def top_paths(self, ante: int = 1, n: int = 3) -> list[tuple[BuildPathState, float]]:
        """Return top N paths with their feasibility scores."""
        scored = [(ps, ps.feasibility(ante)) for ps in self.paths]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:n]

    def is_committed(self) -> bool:
        return self._committed is not None

    # ----------------------------------------------------------
    # Updates (Bayesian signals)
    # ----------------------------------------------------------

    def on_joker_acquired(self, joker_name: str):
        """Update all paths when a joker is bought/obtained."""
        for ps in self.paths:
            if joker_name in ps.path.core_jokers and joker_name not in ps.owned_core:
                ps.owned_core.append(joker_name)
            elif joker_name in ps.path.flex_jokers and joker_name not in ps.owned_flex:
                ps.owned_flex.append(joker_name)

    def on_joker_sold(self, joker_name: str):
        """Update when a joker is sold."""
        for ps in self.paths:
            if joker_name in ps.owned_core:
                ps.owned_core.remove(joker_name)
            if joker_name in ps.owned_flex:
                ps.owned_flex.remove(joker_name)

    def on_planet_used(self, hand_type: str):
        """Update when a planet card levels up a hand type."""
        for ps in self.paths:
            if hand_type in ps.path.target_planets or hand_type in ps.path.target_hands:
                ps.hand_level_bonus = min(ps.hand_level_bonus + 0.15, 1.0)

    def on_tarot_used(self, tarot_name: str):
        """Update deck modification progress based on tarot usage."""
        # Suit-changing tarots help flush builds
        suit_tarots = {"Lovers", "Empress", "Emperor", "Hierophant"}
        enhance_tarots = {"Magician", "High Priestess", "Chariot", "Justice",
                          "Hermit", "Wheel of Fortune", "Strength"}
        for ps in self.paths:
            if "suit_convert" in ps.path.deck_mods and tarot_name in suit_tarots:
                ps.deck_ready = min(ps.deck_ready + 0.15, 1.0)
            if "steel_enhance" in ps.path.deck_mods and tarot_name in {"Chariot"}:
                ps.deck_ready = min(ps.deck_ready + 0.2, 1.0)
            if "lucky_enhance" in ps.path.deck_mods and tarot_name in {"Justice"}:
                ps.deck_ready = min(ps.deck_ready + 0.2, 1.0)

    def sync_jokers(self, joker_names: list[str]):
        """Full sync of owned jokers (call at start of each phase)."""
        for ps in self.paths:
            ps.owned_core = [j for j in joker_names if j in ps.path.core_jokers]
            ps.owned_flex = [j for j in joker_names if j in ps.path.flex_jokers]

    # ----------------------------------------------------------
    # Commitment & Pivot
    # ----------------------------------------------------------

    def try_commit(self, ante: int) -> Optional[str]:
        """Try to commit to a build path.

        Commits when:
        - ante >= 2 and best path has feasibility >= 0.4
        - OR ante >= 3 (forced commitment to best available)

        Returns path name if newly committed, None otherwise.
        """
        if self._committed:
            return None

        best = self.best_path(ante)
        feas = best.feasibility(ante)

        if ante >= 2 and feas >= 0.4:
            self._committed = best.path.name
            self._commit_ante = ante
            return best.path.name

        if ante >= 3:
            self._committed = best.path.name
            self._commit_ante = ante
            return best.path.name

        return None

    def check_pivot(self, ante: int) -> Optional[str]:
        """Check if we should pivot to a different build path.

        Pivot conditions:
        1. Current best feasibility < 0.2
        2. Another path has feasibility > 2x current best
        3. The alternative has higher ceiling

        Returns new path name if pivoting, None otherwise.
        """
        if not self._committed:
            return None
        if ante < 3:
            return None

        current = self.best_path(ante)
        current_feas = current.feasibility(ante)

        if current_feas >= 0.2:
            return None  # current path still viable

        # Find best alternative
        alternatives = [(ps, ps.feasibility(ante)) for ps in self.paths
                        if ps.path.name != self._committed]
        if not alternatives:
            return None

        best_alt, alt_feas = max(alternatives, key=lambda x: x[1])

        if alt_feas > current_feas * 2 and best_alt.path.ceiling > current.path.ceiling:
            self._committed = best_alt.path.name
            self._commit_ante = ante
            return best_alt.path.name

        return None

    # ----------------------------------------------------------
    # Decision Support
    # ----------------------------------------------------------

    def joker_build_bonus(self, joker_name: str, ante: int) -> tuple[float, str]:
        """Score bonus for buying a joker based on build path alignment.

        Returns (bonus, reason).
        """
        best = self.best_path(ante)
        best_feas = best.feasibility(ante)

        # Core joker for best path — must buy
        if joker_name in best.missing_core:
            return 5.0, f"core for {best.path.name}"

        # Flex joker for best path
        if joker_name in best.path.flex_jokers and joker_name not in best.owned_flex:
            return 2.0, f"flex for {best.path.name}"

        # Core joker for a competitive alternative path
        for ps in self.paths:
            if ps.path.name == best.path.name:
                continue
            alt_feas = ps.feasibility(ante)
            if joker_name in ps.missing_core:
                # More generous threshold before commitment
                threshold = 0.5 if not self._committed else 0.8
                if alt_feas > best_feas * threshold:
                    return 1.5, f"core for alt {ps.path.name} (feas={alt_feas:.2f})"

        return 0.0, ""

    def planet_build_bonus(self, hand_type: str, ante: int) -> tuple[float, str]:
        """Score bonus for using/buying a planet card."""
        best = self.best_path(ante)
        if hand_type in best.path.target_hands or hand_type in best.path.target_planets:
            return 3.0, f"levels {best.path.name} target"
        return 0.0, ""

    def tarot_build_bonus(self, tarot_name: str, ante: int) -> tuple[float, str]:
        """Score bonus for a tarot card based on deck modification needs."""
        best = self.best_path(ante)
        suit_tarots = {"Lovers", "Empress", "Emperor", "Hierophant"}
        if "suit_convert" in best.path.deck_mods and tarot_name in suit_tarots:
            return 2.0, f"suit convert for {best.path.name}"
        if "steel_enhance" in best.path.deck_mods and tarot_name == "Chariot":
            return 2.0, f"steel enhance for {best.path.name}"
        if "lucky_enhance" in best.path.deck_mods and tarot_name == "Justice":
            return 2.0, f"lucky enhance for {best.path.name}"
        return 0.0, ""

    def discard_guidance(self, ante: int) -> dict:
        """Get discard guidance based on current build path.

        Returns dict with:
        - prefer_suits: list of suits to keep (for flush builds)
        - prefer_ranks: list of ranks to keep (for pairs/face builds)
        - prefer_hand_type: target hand type name
        """
        best = self.best_path(ante)
        guidance = {
            "prefer_suits": [],
            "prefer_ranks": [],
            "prefer_hand_type": "",
            "path_name": best.path.name,
        }

        tags = best.path.tags

        if "flush" in tags:
            # For flush builds, prefer keeping cards of the dominant suit
            guidance["prefer_hand_type"] = "Flush"
            # Actual suit preference determined at runtime from hand composition

        if "face" in tags:
            guidance["prefer_ranks"] = ["J", "Q", "K"]
            guidance["prefer_hand_type"] = "Pair"

        if "pairs" in tags:
            guidance["prefer_hand_type"] = "Pair"

        if "straight" in tags:
            guidance["prefer_hand_type"] = "Straight"

        if best.path.target_hands:
            guidance["prefer_hand_type"] = best.path.target_hands[0]

        return guidance

    def summary(self, ante: int) -> str:
        """Human-readable build status for logging."""
        top = self.top_paths(ante, n=3)
        lines = []
        if self._committed:
            lines.append(f"Committed: {self._committed} (ante {self._commit_ante})")
        for ps, feas in top:
            core_str = f"{len(ps.owned_core)}/{ps.path.min_core} core"
            flex_str = f"{len(ps.owned_flex)} flex"
            lines.append(f"  {ps.path.name}: {feas:.2f} ({core_str}, {flex_str})")
        return "\n".join(lines)
