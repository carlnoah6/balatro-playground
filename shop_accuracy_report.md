# Shop 预测准确率报告

## 数据概览

- 总记录数：191
- 覆盖 runs：39
- 覆盖 antes：[1, 2, 3]

## 准确率（按 ante 分组）

### Ante 1

- 记录数：80
- 总物品数：395
- 物品名称匹配率：25.3%
- 物品顺序匹配率：20.3%

**典型案例：**

案例 1 (seed: BEM6WEEH, run: 7):
- 实际：['DNA', 'Smiley Face', 'Hone', 'Jumbo Standard Pack', 'Jumbo Standard Pack']
- 预测：['Mars', 'Planet X', 'Magic Trick', 'Buffoon Pack', 'Jumbo Standard Pack']

案例 2 (seed: BEM6WEEH, run: 7):
- 实际：['Gros Michel', 'Sixth Sense', 'Hone', 'Buffoon Pack', 'Jumbo Standard Pack']
- 预测：['Mars', 'Planet X', 'Magic Trick', 'Buffoon Pack', 'Jumbo Standard Pack']

### Ante 2

- 记录数：82
- 总物品数：402
- 物品名称匹配率：15.2%
- 物品顺序匹配率：11.9%

**典型案例：**

案例 1 (seed: XVX3JUBA, run: 8):
- 实际：['Droll Joker', 'Clever Joker', 'Hieroglyph', 'Jumbo Arcana Pack', 'Celestial Pack']
- 预测：['Droll Joker', 'Clever Joker', 'Telescope', 'Buffoon Pack', 'Celestial Pack']

案例 2 (seed: HAHJQACK, run: 9):
- 实际：['Scholar', 'Crazy Joker', 'Overstock', 'Jumbo Standard Pack', 'Mega Buffoon Pack']
- 预测：['Scholar', 'The Moon', 'Planet Merchant', 'Buffoon Pack', 'Jumbo Arcana Pack']

### Ante 3

- 记录数：29
- 总物品数：141
- 物品名称匹配率：11.3%
- 物品顺序匹配率：5.0%

**典型案例：**

案例 1 (seed: F8PAUK1B, run: 13):
- 实际：['Odd Todd', 'The Devil', 'Overstock', 'Standard Pack', 'Standard Pack']
- 预测：['Odd Todd', '8 Ball', 'Hieroglyph', 'Buffoon Pack', 'Arcana Pack']

案例 2 (seed: FNNGIJNW, run: 15):
- 实际：['The Emperor', 'Fortune Teller', 'Overstock', 'Jumbo Celestial Pack', 'Mega Buffoon Pack']
- 预测：['Egg', 'Wily Joker', 'Reroll Surplus', 'Jumbo Standard Pack', 'Buffoon Pack']

## 总体统计

- 总物品数：938
- 总体名称匹配率：18.9%
- 总体顺序匹配率：14.4%
