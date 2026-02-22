# Balatro Auto-Play Projects on GitHub

Research conducted: 2026-02-20

---

## 1. Coder Ecosystem: BalatroBot + BalatroLLM + BalatroBench

### BalatroBot (API Layer)
- **URL:** https://github.com/coder/balatrobot
- **Stars:** ~45
- **Last Updated:** Active (1,038+ commits)
- **Language:** Lua (mod) + Python (client)

**Architecture:** A Balatro mod that exposes a JSON-RPC 2.0 HTTP API. External programs connect via HTTP POST to read game state and execute actions. This is the most mature bot API available — it's a fork of besteon/balatrobot but significantly evolved by Coder.

**Key API endpoints cover:**
- Card selection, playing, discarding
- Shop transactions (buy, sell, reroll)
- Blind selection/skipping
- Consumable usage
- Joker rearrangement
- Full game state serialization

**Worth borrowing:** Their JSON-RPC API design is clean and well-documented. If we ever need to interface with the actual game (vs. our simulation), this is the standard.

---

### BalatroLLM (LLM Player)
- **URL:** https://github.com/coder/balatrollm
- **Stars:** Active development
- **Last Updated:** Active (2026)
- **Language:** Python

**Architecture:** Pure LLM-driven player. Uses tool/function calling to execute game actions. The LLM receives structured game state and makes all decisions — hand selection, shop purchases, blind selection — through tool calls.

**Strategy System (Jinja2 templates):**
Each strategy is a directory with 5 files:
```
strategies/{name}/
├── manifest.json        # Metadata
├── STRATEGY.md.jinja    # Philosophy & approach guide for the LLM
├── GAMESTATE.md.jinja   # How game state is presented to the LLM
├── MEMORY.md.jinja      # Response history tracking
└── TOOLS.json           # Available function definitions
```

**Key design decisions:**
- Game state is rendered as structured markdown for the LLM
- Strategy templates use Jinja2 to dynamically include relevant context
- Memory template tracks recent decisions for consistency
- Tool definitions constrain the LLM to valid actions per game phase:
  - BLIND phase: `play_hand`, `discard_hand`, `rearrange`, `sell`, `use`
  - SHOP phase: `buy`, `reroll`, `next_round`, `sell`, `use`, `rearrange`
  - BLIND_SELECT phase: `select`, `skip`

**Performance (from BalatroBench):**
- Best model: **Gemini 3 Pro Preview** — cleared round 24 (final round / win) 9 out of 15 times
- Worst on leaderboard: **Mistral Large 2512** — lost in round 1 most attempts, best was round 7
- Key metric: "valid tool call rate" — many models fail by producing invalid actions
- Models are benchmarked on fixed seeds (AAAAA, BBBBB, CCCCC, DDDDD, EEEEE), 3 plays per seed

**Techniques worth borrowing:**
1. **Structured game state presentation** — their GAMESTATE.md.jinja template is a good reference for what info to feed an LLM
2. **Strategy-as-prompt-template** — separating strategy philosophy from game mechanics is elegant
3. **Phase-specific tool definitions** — constraining available actions per game phase reduces invalid moves
4. **Memory/history tracking** — feeding recent decisions back to the LLM for consistency

**Comparison with our approach:** They rely entirely on the LLM for all decisions (no rule-based engine). This means they pay the full LLM inference cost for every single action, including trivial ones. Our hybrid approach (rule-based engine + LLM advisor for complex decisions) should be significantly cheaper and faster while potentially more consistent for routine plays.

---

### BalatroBench (Benchmark)
- **URL:** https://github.com/coder/balatrobench
- **Website:** https://balatrobench.com
- **Stars:** Active
- **Language:** Python + JavaScript

**Purpose:** Standardized benchmark for comparing LLM Balatro performance. Processes BalatroLLM run artifacts and generates interactive leaderboards.

**Benchmark rules:**
- Red (initial) deck
- Initial difficulty (White Stake)
- Fixed seeds: AAAAA, BBBBB, CCCCC, DDDDD, EEEEE
- 3 plays per seed (15 total runs)
- Metrics: average round reached, valid tool call %, tokens, time, cost

**Worth borrowing:** Their seed-based reproducible benchmarking methodology. We should adopt fixed seeds for our own testing.

---

## 2. besteon/balatrobot (Original Bot Framework)
- **URL:** https://github.com/besteon/balatrobot
- **Stars:** ~200+
- **Last Updated:** 2024
- **Language:** Lua (mod) + Python (client)

**Architecture:** The original bot API that Coder forked. Uses UDP socket communication (vs Coder's HTTP). Provides a `Bot` base class with abstract methods:

```python
class Bot:
    def skip_or_select_blind(self): ...
    def select_cards_from_hand(self): ...
    def select_shop_action(self): ...
    def select_booster_action(self): ...
    def sell_jokers(self): ...
    def rearrange_jokers(self): ...
    def use_or_sell_consumables(self): ...
    def rearrange_consumables(self): ...
    def rearrange_hand(self): ...
```

**Game state enum (useful reference):**
```python
class State(Enum):
    SELECTING_HAND = 1
    HAND_PLAYED = 2
    DRAW_TO_HAND = 3
    GAME_OVER = 4
    SHOP = 5
    PLAY_TAROT = 6
    BLIND_SELECT = 7
    ROUND_EVAL = 8
    TAROT_PACK = 9
    PLANET_PACK = 10
    MENU = 11
    STANDARD_PACK = 17
    BUFFOON_PACK = 18
    NEW_ROUND = 19
```

**Worth borrowing:** The state machine design and action decomposition. Their `waitingFor` pattern (the game tells the bot what decision it needs) is a clean way to handle the game loop.

---

## 3. balatro-rs (Rust Engine + RL Attempt)
- **URL:** https://github.com/evanofslack/balatro-rs
- **Stars:** ~50+
- **Last Updated:** 2024-2025
- **Language:** Rust + Python (pyo3 bindings)

**Architecture:** A standalone game engine and **exhaustive move generator** for a simplified Balatro. Written in Rust for performance, with Python bindings via pyo3 for RL training.

**Key feature — Move Generation:**
```rust
// Get ALL valid actions at any game state
let actions: Vec<Action> = g.gen_moves().collect();
// Pick one and execute
g.handle_action(action);
```

**Implemented features:**
- ✅ Poker hand identification and scoring
- ✅ Playing/discarding/reordering cards
- ✅ Blind pass/fail and win/lose conditions
- ✅ Money/interest generation
- ✅ Ante progression (up to ante 8)
- ✅ Blind progression (small, big, boss)
- ✅ Stage transitions (pre-blind, blind, post-blind, shop)
- ✅ Buying/selling/using jokers (partial)
- ❌ Tarots, planets, spectrals
- ❌ Boss blind modifiers
- ❌ Card enhancements, foils, seals

**RL attempt (pylatro):** Author tried Gymnasium + pyo3 bindings for RL training but noted "nothing really works correctly" — the action/observation space is too complex for naive RL.

**Techniques worth borrowing:**
1. **Exhaustive move generation** — enumerating all valid actions is essential for search-based approaches
2. **Rust performance** — if we need Monte Carlo simulation, a Rust engine would be orders of magnitude faster than Python
3. **Simplified game model** — their subset of rules is a good reference for what's essential vs. nice-to-have

**Comparison with our approach:** They aimed for RL but the action space proved too large. Our rule-based + LLM hybrid avoids this problem entirely. However, their move generator concept could enhance our engine — we could enumerate candidate plays and score them rather than relying on heuristics alone.

---

## 4. balatro-gym (Gymnasium Environment)
- **URL:** https://github.com/cassiusfive/balatro-gym
- **Stars:** ~30+
- **Last Updated:** 2024-2025
- **Language:** Python

**Architecture:** OpenAI Gymnasium environment for Balatro RL training. Includes a scoring engine with hand evaluation.

**Scoring Engine (key code):**
```python
class HandType(IntEnum):
    HIGH_CARD       = 0
    ONE_PAIR        = 1
    TWO_PAIR        = 2
    THREE_KIND      = 3
    STRAIGHT        = 4
    FLUSH           = 5
    FULL_HOUSE      = 6
    FOUR_KIND       = 7
    STRAIGHT_FLUSH  = 8
    FIVE_KIND       = 9   # Balatro-specific
    FLUSH_HOUSE     = 10  # Balatro-specific
    FLUSH_FIVE      = 11  # Balatro-specific

BASE_HAND_VALUES = {
    HandType.HIGH_CARD:       (5, 1),
    HandType.ONE_PAIR:        (10, 2),
    HandType.TWO_PAIR:        (20, 2),
    HandType.THREE_KIND:      (30, 3),
    HandType.STRAIGHT:        (30, 4),
    HandType.FLUSH:           (35, 4),
    HandType.FULL_HOUSE:      (40, 4),
    HandType.FOUR_KIND:       (60, 7),
    HandType.STRAIGHT_FLUSH:  (100, 8),
    HandType.FIVE_KIND:       (120, 12),
    HandType.FLUSH_HOUSE:     (140, 14),
    HandType.FLUSH_FIVE:      (160, 16),
}
```

**Hand level system:**
```python
def get_hand_chips_mult(self, hand_type):
    base_chips, base_mult = BASE_HAND_VALUES[hand_type]
    level = self.get_hand_level(hand_type)
    level_bonus = level - 1
    final_chips = base_chips + (level_bonus * 10)
    final_mult = base_mult + level_bonus
    return final_chips, final_mult
```

**Planet card mapping:**
```python
PLANET_HAND_MAP = {
    'Mercury': HandType.ONE_PAIR,
    'Venus': HandType.TWO_PAIR,
    'Earth': HandType.THREE_KIND,
    'Mars': HandType.STRAIGHT,
    'Jupiter': HandType.FLUSH,
    'Saturn': HandType.FULL_HOUSE,
    'Uranus': HandType.FOUR_KIND,
    'Neptune': HandType.STRAIGHT_FLUSH,
    'Pluto': HandType.HIGH_CARD,
    'Planet X': HandType.FIVE_KIND,
    'Ceres': HandType.FLUSH_HOUSE,
    'Eris': HandType.FLUSH_FIVE,
}
```

**Modifier system for jokers:**
```python
def score_hand(self, cards, hand_type):
    base_chips, base_mult = self.get_hand_chips_mult(hand_type)
    # Add card chip values
    card_chips = sum(chip_value(card) for card in cards)
    total_chips = base_chips + card_chips
    score = total_chips * base_mult
    # Apply joker modifiers in order
    for modifier in self.modifiers:
        score = modifier(score, cards, self)
    return int(score)
```

**Techniques worth borrowing:**
1. **Base hand values table** — canonical reference for Balatro scoring
2. **Planet-to-hand mapping** — useful for planet card evaluation
3. **Modifier chain pattern** — clean way to apply joker effects in sequence
4. **Hand level progression formula** — each level adds +10 chips, +1 mult

**Comparison with our approach:** Their scoring engine is simpler than what we need (doesn't handle individual joker effects properly — Balatro applies chips/mult/xmult in specific order per joker). But the base values and structure are a solid reference.

---

## 5. proj-airi/game-playing-ai-balatro (Computer Vision + LLM)
- **URL:** https://github.com/proj-airi/game-playing-ai-balatro
- **Stars:** ~50+
- **Last Updated:** 2025
- **Language:** Python

**Architecture:** Completely different approach — uses **computer vision** to read the game screen, then LLM for decisions. No mod/API needed.

**CV Pipeline:**
- **YOLO11n models** trained on custom datasets (<1k labeled images):
  - `Entities model`: Detects cards and card stacks
  - `UI model`: Detects data panels, scores, buttons
  - `Unified model`: Combined detection
- **RapidOCR (PaddleOCR)**: Reads text from detected regions
- Training: Single NVIDIA 4080 Super, converged within 2000 epochs

**Models available on HuggingFace:**
- `proj-airi/games-balatro-2024-yolo-entities-detection`
- `proj-airi/games-balatro-2024-yolo-ui-detection`

**Techniques worth borrowing:**
1. **Screen reading as fallback** — if we ever need to work without a mod API, their YOLO approach is proven
2. **UI element detection** — could be useful for validation/debugging

**Comparison with our approach:** Fundamentally different — they solve the "how to read game state" problem with CV, while we use a simulation engine. CV approach is more fragile but works with the unmodified game. Not directly applicable to our architecture.

---

## 6. EFHIII/balatro-calculator (Score Calculator)
- **URL:** https://github.com/EFHIII/balatro-calculator
- **Website:** https://efhiii.github.io/balatro-calculator/
- **Stars:** ~100+
- **Last Updated:** Active
- **Language:** JavaScript

**Architecture:** Web-based score calculator that simulates Balatro's exact scoring pipeline. The most accurate scoring implementation available — handles all jokers, enhancements, editions, seals, and their interactions.

**Key value:** This is the gold standard for score calculation accuracy. Their JavaScript simulation (`balatro-sim.js`) replicates the game's Lua scoring logic faithfully, including:
- Exact joker trigger order
- Card enhancement effects (bonus, mult, wild, glass, steel, stone, gold, lucky)
- Edition effects (foil, holographic, polychrome)
- Seal effects (gold, red, blue, purple)
- Boss blind effects on scoring
- Retrigger mechanics

**Techniques worth borrowing:**
1. **Exact scoring replication** — if we need pixel-perfect score prediction, this is the reference
2. **Joker interaction order** — their code documents the exact order jokers apply effects
3. **Enhancement/edition/seal stacking** — complex interactions handled correctly

---

## 7. DivvyCr/Balatro-Preview (In-Game Score Preview)
- **URL:** https://github.com/DivvyCr/Balatro-Preview
- **Stars:** ~200+
- **Last Updated:** Active
- **Language:** Lua (Balatro mod)

**Architecture:** A Balatro mod that simulates scoring without side effects, showing a real-time preview of what score you'd get. Uses a separate simulation library (Balatro-Simulation).

**Key features:**
- Score and dollar preview without side-effects
- Real-time updates when changing card selection or joker order
- Can preview even with face-down cards
- Shows min/max possible scores when probabilities are involved

**Techniques worth borrowing:**
1. **Side-effect-free simulation** — their approach to simulating scoring without modifying game state is exactly what we need for our evaluation engine
2. **Min/max scoring for probabilistic jokers** — handling Lucky Card, probability-based jokers by computing expected value ranges

---

## 8. lahmann1/balatro_mc_scripts (Monte Carlo Probability)
- **URL:** https://github.com/lahmann1/balatro_mc_scripts
- **Stars:** Small
- **Last Updated:** 2024
- **Language:** Python

**Architecture:** Monte Carlo simulation scripts for testing hand draw probabilities in Balatro. Simulates drawing hands from a known deck to calculate probability of hitting specific hand types.

**Use case:** "What's the probability I draw a flush in the next 3 hands given my current deck composition?"

**Techniques worth borrowing:**
1. **Draw probability calculation** — useful for discard decisions ("should I break this pair to chase a flush?")
2. **Deck tracking** — knowing what's left in the deck to calculate odds

---

## 9. CzJLee/Balatro-AI (RL Attempt)
- **URL:** https://github.com/CzJLee/Balatro-AI
- **Stars:** Small
- **Last Updated:** 2024
- **Language:** Python

**Architecture:** Early-stage RL attempt using Stable Baselines3. Connects to the besteon/balatrobot API. Defines the full action space but appears incomplete.

**Action space defined:**
```
select_blind, skip_blind, play_hand, discard_hand, end_shop,
reroll_shop, buy_card, buy_voucher, buy_booster, select_booster_card,
skip_booster_pack, sell_joker, use_consumable, sell_consumable,
rearrange_jokers, rearrange_consumables, rearrange_hand, pass,
start_run, send_gamestate
```

**Comparison with our approach:** Abandoned early — confirms that naive RL on the full Balatro action space is intractable without significant state/action space engineering.

---

## Summary: Key Techniques to Borrow

### High Priority
1. **Exhaustive move generation** (balatro-rs) — enumerate all valid plays, score each, pick best
2. **Base scoring tables + hand level formulas** (balatro-gym) — canonical reference values
3. **Phase-specific action constraints** (BalatroLLM) — reduce invalid actions by constraining per game phase
4. **Structured game state for LLM** (BalatroLLM) — their Jinja2 template approach for presenting state to LLMs
5. **Fixed-seed benchmarking** (BalatroBench) — reproducible testing methodology

### Medium Priority
6. **Side-effect-free scoring simulation** (Balatro-Preview) — simulate without modifying state
7. **Monte Carlo draw probabilities** (balatro_mc_scripts) — inform discard decisions
8. **Modifier chain pattern** (balatro-gym) — clean joker effect application
9. **Planet card value mapping** (balatro-gym) — for planet purchase decisions

### Low Priority / Future Reference
10. **YOLO-based screen reading** (proj-airi) — fallback if no API available
11. **Exact joker interaction order** (EFHIII calculator) — for pixel-perfect scoring
12. **Min/max probabilistic scoring** (Balatro-Preview) — expected value for lucky cards

---

## Our Approach vs. The Field

| Aspect | BalatroLLM (Coder) | RL Projects | Our Approach |
|--------|-------------------|-------------|--------------|
| Decision engine | Pure LLM | Neural network | Rule-based + LLM advisor |
| Hand evaluation | LLM reasons about it | Learned | Algorithmic (fast, exact) |
| Shop decisions | LLM | Learned | LLM advisor (complex tradeoffs) |
| Speed | Slow (LLM per action) | Fast (inference) | Fast (rules) + slow only when needed |
| Cost | High (tokens per action) | Training cost | Low (LLM only for shop/complex) |
| Accuracy | Depends on model | Depends on training | Deterministic for scoring |
| Boss blinds | LLM adapts | Not implemented | Rule-based adaptation |
| Joker synergy | LLM reasons | Not implemented | Rule-based evaluation |

**Our key advantage:** By using a rule-based engine for the mechanical parts (hand evaluation, scoring, basic play decisions) and only invoking the LLM for genuinely complex strategic decisions (shop purchases, joker synergy evaluation, long-term deck building), we get the best of both worlds — speed and consistency for routine decisions, intelligence for complex ones.

**Key gap to address:** None of the existing projects have solved joker synergy evaluation well. The RL projects don't implement jokers at all, and the LLM projects just let the model reason about it (unreliably). This is our biggest opportunity for differentiation — building a proper joker synergy scoring system.
