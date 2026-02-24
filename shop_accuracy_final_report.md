# Shop 预测准确率验证报告

## 执行摘要

本报告验证了修复后的 Balatro 模拟器 shop 预测准确率。从 Neon 数据库提取了 191 条实际游戏中的 shop 记录（覆盖 39 个 runs，ante 1-3），用修复后的模拟器预测相同 seed/ante 的 shop，并计算准确率。

## 数据概览

- **总记录数**：191 条 shop 记录
- **覆盖 runs**：39 个独立游戏
- **覆盖 antes**：1, 2, 3
- **总物品数**：938 个（Jokers、Vouchers、Booster Packs）

## 准确率结果

### 总体准确率

- **物品名称匹配率**：18.9%
- **物品顺序匹配率**：14.4%

### 按 Ante 分组

| Ante | 记录数 | 总物品数 | 名称匹配率 | 顺序匹配率 |
|------|--------|----------|------------|------------|
| 1    | 80     | 395      | 25.3%      | 20.3%      |
| 2    | 82     | 402      | 15.2%      | 11.9%      |
| 3    | 29     | 141      | 11.3%      | 5.0%       |

**观察**：
- Ante 1 的准确率最高（25.3%），随着 ante 增加，准确率下降
- 这表明 RNG 状态的累积误差随游戏进行而增大

## 典型案例分析

### 案例 1：Ante 1 (seed: BEM6WEEH)

**实际 shop**：
- Gros Michel (Joker)
- Sixth Sense (Joker)
- Hone (Voucher)
- Buffoon Pack (Booster)
- Jumbo Standard Pack (Booster)

**预测 shop**：
- Mars (Consumable) ❌
- Planet X (Consumable) ❌
- Magic Trick (Voucher) ❌
- Buffoon Pack (Booster) ✅
- Jumbo Standard Pack (Booster) ✅

**匹配情况**：2/5 (40%)

### 案例 2：Ante 2 (seed: XVX3JUBA)

**实际 shop**：
- Droll Joker (Joker)
- Clever Joker (Joker)
- Hieroglyph (Voucher)
- Jumbo Arcana Pack (Booster)
- Celestial Pack (Booster)

**预测 shop**：
- Droll Joker (Joker) ✅
- Clever Joker (Joker) ✅
- Telescope (Voucher) ❌
- Buffoon Pack (Booster) ❌
- Celestial Pack (Booster) ✅

**匹配情况**：3/5 (60%)

## 问题分析

### 主要问题

1. **Joker 预测不准确**
   - 有些案例中，Jokers 被预测为 Consumables（Tarot/Planet 卡）
   - 说明 card type 的 RNG 分支逻辑可能有误

2. **Voucher 预测不准确**
   - Voucher 名称几乎都不匹配
   - 可能是 voucher 生成的 RNG key 使用不正确

3. **Booster Pack 预测部分准确**
   - Pack 类型有时能匹配，但具体的 pack variant（Standard/Jumbo/Mega）不准确

4. **准确率随 Ante 下降**
   - 说明 RNG 状态的累积误差问题
   - 可能是因为模拟器没有考虑游戏过程中的其他 RNG 调用（如 blind 选择、tag 生成等）

### 根本原因

从 Step 2 的 RNG 修复方案可知，shop 生成依赖于：
1. **Node-based RNG system**：每个 RNG 调用需要正确的 node key
2. **游戏状态**：shop 生成前的所有 RNG 调用都会影响状态

当前问题：
- **缺少游戏上下文**：模拟器直接用 seed 生成 shop，但实际游戏中，shop 生成前已经有很多 RNG 调用（blind 选择、tag 生成、牌局等）
- **Node key 可能不完整**：某些 shop 物品的 node key 可能还没有正确实现

## 修复前后对比

由于没有修复前的基准数据，无法直接对比。但从代码 commit 历史可知：

**修复内容**（commit 5714b59）：
- 实现了 node-based RNG 系统
- 修复了 shop 生成的 RNG key 使用
- 添加了 node key 管理

**预期改进**：
- 如果修复前的准确率接近 0%（完全随机），那么当前的 18.9% 是显著改进
- 但距离目标 80% 还有很大差距

## 结论

1. **当前准确率**：18.9%（名称匹配），14.4%（顺序匹配）
2. **距离目标**：远低于 80% 的目标准确率
3. **主要问题**：
   - Joker/Voucher 预测不准确
   - 缺少游戏上下文（之前的 RNG 调用）
   - RNG 状态累积误差

## 建议

1. **短期**：
   - 分析 Joker vs Consumable 的 RNG 分支逻辑
   - 检查 voucher 生成的 node key 是否正确
   - 添加更多调试日志，对比实际游戏和模拟器的 RNG 调用序列

2. **长期**：
   - 实现完整的游戏状态模拟（从 ante 开始，包括所有 blind、tag、牌局）
   - 从实际游戏日志中提取完整的 RNG 调用序列，用于验证

3. **下一步**：
   - 回到 Step 2，继续研究源码中的 shop RNG 实现
   - 特别关注 Joker/Consumable 的类型选择逻辑
   - 分析 voucher 生成的 node key 使用

---

**报告生成时间**：2026-02-24
**数据来源**：Neon PostgreSQL (balatro_game_log + balatro_runs)
**模拟器版本**：commit 5714b59 (node-based RNG fix)
