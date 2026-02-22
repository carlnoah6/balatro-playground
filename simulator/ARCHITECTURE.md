# Balatro 纯 Python 模拟器 — 架构设计

> Created: 2026-02-21
> Status: Step 1 完成 — 架构设计 + Seed 机制调研

## 1. 目标

构建一个纯 Python 的 Balatro 游戏模拟器，用于：
- **离线策略训练** — 不需要运行游戏客户端，纯数值模拟
- **MCTS 搜索** — 快速 rollout，每秒数千局模拟
- **策略评估** — 对比不同策略在相同 seed 下的表现
- **Seed 预计算** — 给定 seed，预测商店内容、Boss Blind 等

## 2. Balatro Seed/RNG 机制（源码分析）

### 2.1 核心 RNG 函数链

从 `game/functions/misc_functions.lua` 提取的完整 RNG 链：

```
seed (8字符字符串, 如 "7LB2WVPK")
  ↓
pseudohash(key + seed) → float [0, 1)
  ↓
pseudoseed(key) → 维护 per-key 状态，每次调用推进
  ↓
pseudorandom(seed, min, max) → math.randomseed(seed) + math.random()
```

### 2.2 pseudohash — 字符串到浮点数的哈希

```lua
function pseudohash(str)
    local num = 1
    for i = #str, 1, -1 do
        num = ((1.1239285023 / num) * string.byte(str, i) * math.pi + math.pi * i) % 1
    end
    return num
end
```

关键特性：
- 输入：任意字符串（通常是 `key + seed`）
- 输出：[0, 1) 的浮点数
- **从右到左**遍历字符串
- 使用 `1.1239285023 / num` 的递归除法 + `math.pi` 混合
- **已知 bug**：某些输入会产生 NaN（导致 "bug seed" 现象）

### 2.3 pseudoseed — 带状态的 per-key RNG

```lua
function pseudoseed(key, predict_seed)
    if key == 'seed' then return math.random() end

    -- predict 模式（不修改全局状态）
    if predict_seed then
        local _pseed = pseudohash(key .. (predict_seed or ''))
        _pseed = math.abs(tonumber(string.format("%.13f",
            (2.134453429141 + _pseed * 1.72431234) % 1)))
        return (_pseed + (pseudohash(predict_seed) or 0)) / 2
    end

    -- 正常模式：初始化或推进状态
    if not G.GAME.pseudorandom[key] then
        G.GAME.pseudorandom[key] = pseudohash(key .. (G.GAME.pseudorandom.seed or ''))
    end

    G.GAME.pseudorandom[key] = math.abs(tonumber(string.format("%.13f",
        (2.134453429141 + G.GAME.pseudorandom[key] * 1.72431234) % 1)))
    return (G.GAME.pseudorandom[key] + (G.GAME.pseudorandom.hashed_seed or 0)) / 2
end
```

关键特性：
- 每个 key（如 `'shop_joker'`, `'shuffle'`, `'edition_generic'`）有独立状态
- 首次调用：`pseudohash(key + master_seed)` 初始化
- 后续调用：线性同余推进 `(2.134453429141 + state * 1.72431234) % 1`
- 最终值 = `(推进后的 state + hashed_seed) / 2`
- `hashed_seed` = `pseudohash(master_seed)`

### 2.4 pseudorandom — 最终随机数生成

```lua
function pseudorandom(seed, min, max)
    if type(seed) == 'string' then seed = pseudoseed(seed) end
    math.randomseed(seed)
    if min and max then return math.random(min, max)
    else return math.random() end
end
```

关键特性：
- 用 pseudoseed 的输出作为 `math.randomseed` 的种子
- 然后调用 `math.random()` 获取最终值
- **LÖVE2D 的 math.randomseed 接受浮点数**（不同于标准 Lua 只接受整数）
- LÖVE2D 使用的 PRNG 不是标准 Lua 的，需要精确复现

### 2.5 RNG 使用场景（key 映射）

| 场景 | pseudoseed key | 说明 |
|------|---------------|------|
| 洗牌 | `'shuffle'`, `'nr' + ante` | 每轮开始洗牌 |
| 商店 Joker | `'Joker' + rarity` | 商店生成 Joker |
| 商店 Tarot | `'Tarot'` | 商店生成 Tarot 牌 |
| 商店 Planet | `'Planet'` | 商店生成 Planet 牌 |
| Booster Pack | `'shop_pack'` | 商店补充包类型 |
| Boss Blind | `'Boss'` | Boss Blind 选择 |
| Edition | `'edition_generic'` | 卡牌版本（foil/holo/polychrome） |
| Seal | `'certsl'` | Certificate 给的 seal 类型 |
| Lucky Card | `'lucky_mult'`, `'lucky_money'` | Lucky 卡触发 |
| 翻面牌 | `'flipped_card'` | 翻面牌概率 |
| Voucher | `'Voucher'` | 每轮 Voucher |
| Skip Tag | `'Tag'` | 跳过 Blind 的 Tag |

### 2.6 LÖVE2D PRNG 复现

Balatro 使用 LÖVE2D（基于 LuaJIT），其 `math.randomseed` / `math.random` 使用的是 **Xoshiro256** 算法（不是标准 Lua 的 LCG）。

关键差异：
- LÖVE2D 的 `math.randomseed(float)` 接受浮点数，内部转换为 64-bit state
- 标准 Lua 5.1 的 `math.randomseed` 只接受整数
- 必须精确复现 LÖVE2D 的 seed→state 转换逻辑

**复现策略**：
1. 方案 A（推荐）：用 Python 精确实现 LÖVE2D 的 Xoshiro256** 算法
2. 方案 B：用 LuaJIT FFI 调用 LÖVE2D 的 C 实现
3. 方案 C：近似实现，接受微小数值偏差（适合策略训练，不适合 seed 预测）

**对于 MCTS 训练场景，方案 C 足够** — 我们不需要精确复现每个 seed 的结果，只需要统计上正确的游戏机制。

## 3. 游戏状态机

### 3.1 核心状态（从 globals.lua 提取）

```
BLIND_SELECT → DRAW_TO_HAND → SELECTING_HAND → HAND_PLAYED → 
  ↓                                                    ↓
  ↓                                              (chips >= target?)
  ↓                                              YES → NEW_ROUND → ROUND_EVAL → SHOP → BLIND_SELECT
  ↓                                              NO  → DRAW_TO_HAND (继续出牌)
  ↓
  (跳过 blind → 获得 Tag)
```

简化为模拟器需要的 5 个核心阶段：

```python
class Phase(Enum):
    BLIND_SELECT = "blind_select"   # 选择/跳过 blind
    PLAY_HAND = "play_hand"         # 选牌出牌/弃牌
    SHOP = "shop"                   # 商店购买
    PACK_OPEN = "pack_open"         # 开补充包
    GAME_OVER = "game_over"         # 胜利或失败
```

### 3.2 一局游戏的完整流程

```
新游戏(seed, deck, stake)
  ↓
Ante 1:
  ├─ Small Blind (选择/跳过)
  │   ├─ 选择 → 打牌阶段 → 商店
  │   └─ 跳过 → 获得 Tag → 进入 Big Blind
  ├─ Big Blind (选择/跳过)
  │   ├─ 选择 → 打牌阶段 → 商店
  │   └─ 跳过 → 获得 Tag → 进入 Boss Blind
  └─ Boss Blind (必须打)
      └─ 打牌阶段 → 商店 → Ante 2
  ↓
Ante 2-8: 重复
  ↓
Ante 8 Boss 击败 → 胜利
任何时候 hands_left == 0 且 chips < target → 失败
```

### 3.3 打牌阶段详细流程

```
洗牌(deck, seed='nr'+ante)
  ↓
抽牌(hand_size 张)
  ↓
循环:
  ├─ 选择 1-5 张牌
  ├─ 动作: PLAY 或 DISCARD
  │   ├─ PLAY:
  │   │   ├─ evaluate_poker_hand(selected) → 牌型
  │   │   ├─ base_chips = hand_level.chips + Σ card.chips
  │   │   ├─ base_mult = hand_level.mult
  │   │   ├─ 触发 Joker 效果 (chips/mult/xmult)
  │   │   ├─ total = chips × mult
  │   │   ├─ game.chips += total
  │   │   ├─ hands_left -= 1
  │   │   └─ 如果 game.chips >= blind.chips → 过关
  │   └─ DISCARD:
  │       ├─ discards_left -= 1
  │       └─ 弃掉选中的牌
  ├─ 补牌到 hand_size
  └─ 如果 hands_left == 0 且 chips < target → 失败
```

## 4. 模拟器架构

### 4.1 模块划分

```
balatro_sim/
├── __init__.py
├── rng.py              # RNG 系统 (pseudohash, pseudoseed, pseudorandom)
├── enums.py            # 枚举 (Suit, Rank, HandType, Phase, Edition, Seal...)
├── cards.py            # Card, Deck 数据类
├── hands.py            # 牌型识别 (evaluate_poker_hand 的 Python 移植)
├── scoring.py          # 计分引擎 (chips, mult, joker 效果)
├── jokers.py           # Joker 效果实现 (150+ jokers)
├── blinds.py           # Blind 系统 (Boss Blind 效果)
├── shop.py             # 商店生成逻辑
├── state.py            # GameState — 完整游戏状态 (可序列化/可 copy)
├── engine.py           # GameEngine — 状态机驱动，接受 Action 返回新 State
├── actions.py          # Action 类型定义
└── mcts.py             # MCTS 搜索接口
```

### 4.2 核心数据结构

```python
@dataclass(frozen=True)
class Card:
    rank: Rank          # 2-10, J, Q, K, A
    suit: Suit          # Spades, Hearts, Clubs, Diamonds
    edition: Edition    # None, Foil, Holo, Polychrome
    enhancement: Enhancement  # None, Bonus, Mult, Wild, Glass, Steel, Stone, Gold, Lucky
    seal: Seal          # None, Gold, Red, Blue, Purple
    chips: int          # 该牌的 chip 值

@dataclass
class JokerCard:
    key: str            # 如 'j_joker', 'j_blueprint'
    edition: Edition
    eternal: bool
    perishable: bool
    rental: bool
    sell_value: int
    # Joker-specific state (如 Ride the Bus 的连续计数)
    extra: dict

@dataclass
class GameState:
    # 核心
    seed: str
    rng_state: dict[str, float]  # per-key RNG 状态
    phase: Phase
    ante: int
    round: int          # 当前 ante 内的 round (small/big/boss)
    blind_type: str     # 'Small', 'Big', 'Boss'
    blind_name: str     # Boss 名字
    blind_chips: int    # 需要达到的分数

    # 经济
    dollars: int
    
    # 牌组
    deck: list[Card]    # 牌组（未抽的牌）
    hand: list[Card]    # 手牌
    discard_pile: list[Card]  # 弃牌堆
    played_cards: list[Card]  # 已打出的牌（本轮）

    # 资源
    hands_left: int
    discards_left: int
    chips: int          # 本轮已累积的分数

    # 收藏
    jokers: list[JokerCard]
    consumables: list[ConsumableCard]
    vouchers: list[str]

    # 手牌等级
    hand_levels: dict[str, HandLevel]  # 每种牌型的等级

    # 配置
    hand_size: int
    joker_slots: int
    consumable_slots: int

    # 商店状态
    shop_items: list     # 当前商店物品
    reroll_cost: int
    free_rerolls: int
```

### 4.3 Action 类型

```python
@dataclass
class Action:
    pass

@dataclass
class SelectBlind(Action):
    """选择打当前 blind"""
    pass

@dataclass
class SkipBlind(Action):
    """跳过当前 blind（Small/Big only）"""
    pass

@dataclass
class PlayHand(Action):
    """出牌"""
    card_indices: list[int]  # 手牌中选中的牌的索引 (1-5张)

@dataclass
class DiscardHand(Action):
    """弃牌"""
    card_indices: list[int]  # 手牌中选中的牌的索引

@dataclass
class BuyShopItem(Action):
    """购买商店物品"""
    item_index: int

@dataclass
class SellJoker(Action):
    """卖掉 Joker"""
    joker_index: int

@dataclass
class UseConsumable(Action):
    """使用消耗品"""
    consumable_index: int
    target_cards: list[int]  # 目标牌索引

@dataclass
class RerollShop(Action):
    """重掷商店"""
    pass

@dataclass
class LeaveShop(Action):
    """离开商店"""
    pass
```

### 4.4 Engine 接口

```python
class GameEngine:
    def new_game(self, seed: str, deck: str = "Red Deck", stake: int = 1) -> GameState:
        """创建新游戏"""

    def get_legal_actions(self, state: GameState) -> list[Action]:
        """获取当前状态下的合法动作"""

    def step(self, state: GameState, action: Action) -> GameState:
        """执行动作，返回新状态（不修改原状态）"""

    def is_terminal(self, state: GameState) -> bool:
        """游戏是否结束"""

    def get_reward(self, state: GameState) -> float:
        """终局奖励（胜利=1.0, 失败=0.0, 或基于 ante 的中间值）"""
```

### 4.5 MCTS 接口

```python
class BalatroMCTS:
    def __init__(self, engine: GameEngine, policy_fn=None, value_fn=None,
                 n_simulations: int = 1000, c_puct: float = 1.4):
        ...

    def search(self, state: GameState) -> Action:
        """从当前状态搜索最佳动作"""

    def get_action_probs(self, state: GameState, temperature: float = 1.0) -> dict[Action, float]:
        """获取动作概率分布（用于训练）"""
```

## 5. 实现优先级

### Phase 1: 核心骨架（MVP）
1. `rng.py` — pseudohash + pseudoseed（近似实现，不精确复现 LÖVE2D）
2. `enums.py` + `cards.py` — 基础数据类型
3. `hands.py` — 牌型识别（从 Lua 移植 evaluate_poker_hand）
4. `scoring.py` — 基础计分（不含 Joker 效果）
5. `state.py` + `engine.py` — 最小状态机（只支持出牌阶段）
6. `actions.py` — Action 定义

### Phase 2: 完整游戏循环
7. `blinds.py` — Blind 系统 + Boss Blind 效果
8. `shop.py` — 商店生成
9. 完整 ante 循环（blind select → play → shop）

### Phase 3: Joker 系统
10. `jokers.py` — 按使用频率实现 Joker（先做 top 30 常用的）
11. Joker 触发时机（on_play, on_score, on_discard, on_round_end...）

### Phase 4: MCTS
12. `mcts.py` — UCT MCTS 实现
13. 策略网络接口（可选）

## 6. 性能目标

- **单局模拟**：< 10ms（不含 Joker 效果的简化版）
- **MCTS 1000 次 rollout**：< 5 秒
- **批量评估 1000 局**：< 30 秒
- 状态 copy 必须高效（用 `dataclass` + `copy.deepcopy` 或自定义 `__copy__`）

## 7. 与现有系统的关系

- **balatro-env/**：现有的 LLM agent + 游戏客户端方案，通过 TCP 控制真实游戏
- **balatro-sim/**：本项目，纯 Python 模拟器，不需要游戏客户端
- 两者共享策略知识（joker_knowledge.json），但执行方式完全不同
- 模拟器训练出的策略可以导出给 balatro-env 的 agent 使用

## 8. 关键风险

1. **LÖVE2D PRNG 精确复现**：如果需要精确 seed 预测，必须实现 Xoshiro256**。对于策略训练，近似实现足够。
2. **Joker 效果复杂度**：150+ Joker，每个有独特效果。建议分批实现，先覆盖 top 30。
3. **Boss Blind 效果**：部分 Boss 会改变游戏规则（如 The Hook 每次出牌随机弃 2 张），需要在状态机中特殊处理。
4. **状态空间大小**：Balatro 的状态空间非常大（手牌组合 × Joker 组合 × 经济状态），MCTS 需要好的剪枝策略。
