# EFHIII Complete Joker Scoring Logic Extraction

Source: /tmp/balatro-calculator/balatro-sim.js (1838 lines)
Reference: /tmp/balatro-calculator/cards.js (joker definitions)

## ID Mapping

EFHIII uses internal IDs (joker[JOKER]) that differ from the "order" field in cards.js.
The grid position in jokerTexts is [row][col], and the internal ID = row * 10 + col.
But the actual case statements in balatro-sim.js use these internal IDs directly.

## Scoring Phases (execution order)

### Phase 0: Global Effects (compileJokers)
Set before any scoring. These modify how other things work.

| ID | Name | Effect |
|----|------|--------|
| 28 | Raised Fist | Flag: enables held-in-hand mult from lowest card |
| 36 | Pareidolia | Flag: all cards are face cards |
| 64 | Smeared Joker | Flag: Hearts=Diamonds, Clubs=Spades for suit checks |
| 65 | Oops! All 6s | chanceMultiplier *= 2 (doubles all probability-based effects) |
| 66 | Four Fingers | Flag: straights/flushes need only 4 cards |
| 106 | Splash | Flag: all played cards count as scoring |
| 122 | Vampire | Flag: hasVampire (consumes enhancements for xMult) |
| 123 | Shortcut | Flag: straights can skip 1 rank |
| 130 | Midas Mask | Flag: face cards become Gold when scored |

### Phase 1: Joker Order Resolution (compileJokerOrder)
Resolves Blueprint, Brainstorm, Swashbuckler, Baseball Card.

| ID | Name | Effect |
|----|------|--------|
| 30 | Blueprint | Copies ability of joker to the right |
| 59 | Swashbuckler | compiledValues[j] = sum of all other jokers' sell values |
| 77 | Brainstorm | Copies ability of leftmost joker |
| 146 | Baseball Card | BaseballCard++ (x1.5 per Uncommon joker, applied after all joker triggers) |

### Phase 2: Hand-Dependent Compilation (compileCards)
After hand type is determined. Sets compiledChips, compiledMult, compiledValues.

| ID | Name | Effect |
|----|------|--------|
| 9 | Stone Joker | compiledChips += value * 25 (Stone cards in full deck) |
| 21 | Banner | compiledChips += value * 30 (discards remaining) |
| 27 | Steel Joker | compiledValues[j] = 1 + value * 0.2 (Steel cards in deck → xMult) |
| 28 | Raised Fist | Find lowest rank card in hand → compiledValues[j] = that card |
| 31 | Glass Joker | compiledValues[j] = 1 + value * 0.75 (Glass cards destroyed → xMult) |
| 40 | Wee Joker | compiledChips += value * 8 (accumulated from scoring 2s) |
| 44 | Seeing Double | compiledValues[j] = true if Club + other suit in scoring cards |
| 60 | Flower Pot | compiledValues[j] = true if all 4 suits in scoring cards (Wild counts) |
| 61 | Ride the Bus | compiledValues[j] = value + 1 if no face cards scored (consecutive) |
| 68 | Stuntman | compiledChips += 250 |
| 102 | Blackboard | compiledValues[j] = true if ALL held cards are Spades/Clubs (Stone=skip, Wild=ok) |
| 103 | Runner | compiledChips += 15 * (value + hasStraight) |
| 104 | Ice Cream | compiledChips += 100 - 5 * value (decreases each hand) |
| 105 | DNA | If 1 card played, add copy to cardsInHand |
| 107 | Blue Joker | compiledChips += 104 + 2 * value (NOTE: value tracks deck remaining) |
| 119 | Square Joker | compiledChips += 4 * (value + (cards.length==4 ? 1 : 0)) |
| 122 | Vampire | compiledValues[j] = value + enhanced_cards_in_scoring (→ xMult) |
| 129 | Obelisk | compiledValues[j] = 1 or 1 + (value+1)/5 based on most-played hand |
| 140 | Sly Joker | compiledChips += 50 if hasPair |
| 141 | Wily Joker | compiledChips += 100 if hasThreeOfAKind |
| 142 | Clever Joker | compiledChips += 80 if hasTwoPair AND NOT hasFourOfAKind |
| 143 | Devious Joker | compiledChips += 100 if hasStraight |
| 144 | Crafty Joker | compiledChips += 80 if hasFlush |
| 159 | Castle | compiledChips += value * 3 (accumulated from discarding matching suit) |

### Phase 3: Card Scoring (triggerCard, per scoring card left-to-right)

#### 3a: Base card scoring
- Non-Stone: chips += cardValues[rank] + extra_chips + extra_extra_chips
- Stone: chips += 50 (only)
- Bonus Card: chips += 30
- Mult Card: mult += 4
- Glass Card: mult *= 2
- Lucky Card: mult += 20 (1/5 chance, or guaranteed in best-case mode)
- Card editions: Foil +50 chips, Holographic +10 mult, Polychrome x1.5 mult

#### 3b: Per-card joker triggers (inside triggerCard)

| ID | Name | Trigger Condition | Effect |
|----|------|-------------------|--------|
| 16 | Greedy Joker | Diamond suit (or Heart if Smeared) | +3 mult |
| 17 | Lusty Joker | Heart suit (or Diamond if Smeared) | +3 mult |
| 18 | Wrathful Joker | Spade suit (or Club if Smeared) | +3 mult |
| 19 | Gluttonous Joker | Club suit (or Spade if Smeared) | +3 mult |
| 32 | Scary Face | Face card (or Pareidolia) | +30 chips |
| 38 | Even Steven | Even rank (2,4,6,8,10) | +4 mult |
| 39 | Odd Todd | Odd rank (A,3,5,7,9) | +31 chips |
| 40 | Wee Joker | Rank = 2 | +8 chips (per trigger, accumulates to value) |
| 51 | Fibonacci | Ace, 2, 3, 5, or 8 | +8 mult |
| 63 | Scholar | Ace | +20 chips, +4 mult |
| 76 | The Idol | Specific rank+suit combo | x2 mult |
| 80 | Bloodstone | Heart suit (or Diamond if Smeared) | x1.5 mult (1/2 chance) |
| 81 | Arrowhead | Spade suit (or Club if Smeared) | +50 chips |
| 82 | Onyx Agate | Club suit (or Spade if Smeared) | +7 mult |
| 84 | Triboulet | King or Queen | x2 mult |
| 110 | Hiker | Any scored card | +5 chips permanently to card |
| 132 | Photograph | First face card only | x2 mult |
| 145 | Lucky Cat | (tracks lucky triggers) | jokersExtraValue[j] += luckyTriggers |
| 147 | Bull | (tracks lucky money) | jokersExtraValue[j] += luckyMoney * 40 |
| 156 | Smiley Face | Face card (or Pareidolia) | +5 mult |
| 157 | Ancient Joker | Matching suit (changes each round) | x1.5 mult |
| 158 | Walkie Talkie | Rank 4 or 10 | +10 chips, +4 mult |

#### 3c: Card retriggers (after all per-card joker effects)

| ID | Name | Condition | Retrigger Count |
|----|------|-----------|-----------------|
| Red Seal | (card seal) | Always | 1 retrigger |
| 13 | Sock and Buskin | Face card | 1 retrigger |
| 25 | Hack | Rank 2-5 | 1 retrigger |
| 69 | Hanging Chad | First scored card only | 2 retriggers |
| 74 | Dusk | Final hand of round (value != 0) | 1 retrigger |
| 153 | Seltzer | Always (for N hands) | 1 retrigger |

### Phase 4: Held-in-Hand Card Effects (triggerCardInHand)

#### 4a: Steel Card enhancement
- Steel Card: compiledInHandPlusMult *= 1.5, compiledInHandTimesMult *= 1.5

#### 4b: Per-held-card joker triggers

| ID | Name | Condition | Effect |
|----|------|-----------|--------|
| 28 | Raised Fist | Lowest rank card (non-Stone) | +2*rank_value to mult |
| 62 | Shoot the Moon | Queen (non-Stone) | +13 mult |
| 126 | Baron | King (non-Stone) | x1.5 mult (both plus and times) |

#### 4c: Held-card retriggers

| ID | Name | Effect |
|----|------|--------|
| Red Seal | (card seal) | 1 retrigger |
| 14 | Mime | 1 retrigger of all held-card effects |

### Phase 5: Independent Joker Effects (triggerJoker, left-to-right ORDER MATTERS)

| ID | Name | Condition | Effect |
|----|------|-----------|--------|
| 0 | Joker | Always | +4 mult |
| 2 | Jolly Joker | hasPair | +8 mult |
| 3 | Zany Joker | hasThreeOfAKind | +12 mult |
| 4 | Mad Joker | hasTwoPair | +10 mult |
| 5 | Crazy Joker | hasStraight | +12 mult |
| 6 | Droll Joker | hasFlush | +10 mult |
| 7 | Half Joker | cards.length <= 3 | +20 mult |
| 12 | Acrobat | value != 0 (final hand) | x3 mult |
| 22 | Mystic Summit | value != 0 (0 discards) | +15 mult |
| 24 | Loyalty Card | value == 0 (every 6th hand) | x4 mult |
| 26 | Misprint | Always | +0 to +23 mult (random) |
| 27 | Steel Joker | Always | xMult = compiledValues[j] (1 + N*0.2) |
| 31 | Glass Joker | Always | xMult = compiledValues[j] (1 + N*0.75) |
| 33 | Abstract Joker | Always | +3 mult per joker owned |
| 42 | Supernova | Always | +mult = times_hand_played + 1 |
| 44 | Seeing Double | compiledValues[j] true | x2 mult |
| 45 | The Duo | hasPair | x2 mult |
| 46 | The Trio | hasThreeOfAKind | x3 mult |
| 47 | The Family | hasFourOfAKind | x4 mult |
| 48 | The Order | hasStraight | x3 mult |
| 49 | The Tribe | hasFlush | x2 mult |
| 52 | Joker Stencil | Always | xMult = 1 + value (empty slots) |
| 55 | Ceremonial Dagger | Always | +mult = value (accumulated from destroyed jokers) |
| 57 | Fortune Teller | Always | +mult = value (Tarots used) |
| 58 | Hit the Road | Always | xMult = 1 + value * 0.5 (Jacks discarded this round) |
| 59 | Swashbuckler | Always | +mult = compiledValues[j] (sum of sell values) |
| 60 | Flower Pot | compiledValues[j] true | x3 mult |
| 61 | Ride the Bus | Always | +mult = compiledValues[j] (consecutive non-face hands) |
| 67 | Gros Michel | Always | +15 mult |
| 70 | Driver's License | value >= 16 | x3 mult |
| 75 | Throwback | Always | xMult = 1 + value * 0.25 (blinds skipped) |
| 83 | Canio | Always | xMult = 1 + value (face cards destroyed) |
| 85 | Yorick | Always | xMult = value (starts at 1, +1 per 23 discards) |
| 89 | Bootstraps | Always | +mult = value * 2 ($5 increments) |
| 102 | Blackboard | compiledValues[j] true | x3 mult |
| 109 | Constellation | Always | xMult = 1 + value/10 (Planets used) |
| 112 | Green Joker | Always | +mult = 1 + value (grows per hand, shrinks per discard) |
| 115 | Cavendish | Always | x3 mult |
| 116 | Card Sharp | hand played this round before | x3 mult |
| 117 | Red Card | Always | +mult = value * 3 (grows per skip) |
| 118 | Madness | Always | xMult = 1 + value * 0.5 (grows per blind) |
| 122 | Vampire | Always | xMult = 1 + compiledValues[j]/10 |
| 124 | Hologram | Always | xMult = 1 + value * 0.25 (cards added to deck) |
| 129 | Obelisk | Always | xMult = compiledValues[j] |
| 135 | Erosion | Always | +mult = value * 4 (cards below 52) |
| 145 | Lucky Cat | Always | xMult = 1 + (value + extraValue)/4 |
| 147 | Bull | Always | +chips = 2 * value + extraValue (dollars owned) |
| 150 | Flash Card | Always | +mult = value * 2 (rerolls) |
| 151 | Popcorn | Always | +mult = 20 - value * 4 (decreases per round) |
| 152 | Ramen | Always | xMult = 2 - value/100 (decreases per discard) |
| 154 | Spare Trousers | hasTwoPair: +2 + value*2 mult; else: +value*2 mult |
| 155 | Campfire | Always | xMult = 1 + value * 0.25 (cards sold) |

### Phase 5b: Joker Edition Effects (after each joker's own trigger)
- Foil: +50 chips (applied BEFORE joker effect in EFHIII! See triggerJoker line 299-303)
- Holographic: +10 mult (applied BEFORE joker effect)
- Polychrome: x1.5 mult (applied AFTER joker effect)

**IMPORTANT**: In EFHIII, Foil and Holographic are applied BEFORE the joker's own effect (lines 299-303), while Polychrome is applied AFTER (line 571). This differs from some implementations.

### Phase 5c: Baseball Card (after all joker triggers)
- For each Uncommon joker: x1.5 mult (applied BaseballCard times)

### Phase 6: Observatory (post-joker)
- If Observatory planet card: x1.5^(planets_used) mult

## Non-Scoring Jokers (no direct score impact)

These jokers have no effect in the scoring calculation:
- 19: Credit Card (debt limit)
- 23: Marble Joker (adds Stone cards)
- 25: 8 Ball (spawns Tarot)
- 29: Chaos the Clown (free reroll)
- 34: Delayed Gratification (money)
- 41: Business Card (money chance)
- 44b: Space Joker (level up chance)
- 45b: Egg (sell value grows)
- 46b: Burglar (hands/discards)
- 53: Sixth Sense (destroy 6)
- 56: Faceless Jokers (money)
- 58b: Superposition (Tarot chance)
- 65b: Seance (Spectral)
- 66b: Riff-raff (spawns Common jokers)
- 70b: Vagabond (Tarot if $4 or less)
- 72: Cloud 9 (money per 9)
- 73: Rocket (money)
- 76b: Luchador (disable boss)
- 78: Gift Card (sell value)
- 79: Turtle Bean (hand size, decreasing)
- 82b: Reserved Parking (money chance for face in hand)
- 82c: Mail-In Rebate (money)
- 83b: To the Moon (interest)
- 84b: Hallucination (Tarot chance)
- 86: Juggler (hand size)
- 87: Drunkard (discard)
- 89b: Golden Joker (money)
- 94: Diet Cola (Double Tag)
- 95: Trading Card (destroy + money)
- 100: Troubadour (hand size, -1 hand)
- 107b: Mr. Bones (prevent death)
- 108: Merry Andy (discards, -hand size)
- 111: Certificate (random card+seal)
- 121: Showman (allow duplicates)
- 125: Invisible Joker (duplicate joker)
- 137: Cartomancer (Tarot)
- 138: Astronomer (Planet)
- 139: Satellite (money per Planet)
- 142b: Burnt Joker (level up on discard)
- 149: Chicot (negate Boss Blind)
- 150b: Perkeo (duplicate consumable)

## Key Differences from Common Implementations

1. **Joker edition order**: Foil (+50 chips) and Holographic (+10 mult) apply BEFORE the joker's own effect. Polychrome (x1.5) applies AFTER.

2. **Clever Joker**: Only triggers if hasTwoPair AND NOT hasFourOfAKind (Four of a Kind contains Two Pair in Balatro's detection, but Clever shouldn't trigger).

3. **Seeing Double with Wild cards**: Wild cards are distributed optimally - first to Club if no Club, then to non-Club.

4. **Seeing Double with Smeared Joker**: Clubs AND Spades both count as "Club" side. Need club>0 AND (club>1 OR nonClub>0).

5. **Flower Pot with Wild cards**: Wild cards count toward missing suits. Disabled Wild cards are skipped.

6. **Blackboard**: Stone cards in hand are SKIPPED (not counted as black). Wild cards count as black.

7. **Ride the Bus**: Only J/Q/K are face cards for this check (not Ace). Pareidolia makes it never increment.

8. **Raised Fist**: Uses the LOWEST rank card in hand. If multiple same-rank, uses the last one. Adds 2 * rank_value to mult (Ace = 11).

9. **Vampire**: Consumes enhancements from scoring cards. Midas Mask interaction: Gold cards from Midas count as enhanced.

10. **Hanging Chad**: Retriggers the FIRST scored card 2 times (not 1). Also counts non-scoring cards for the "first" tracking.

11. **Supernova**: Adds times_played + 1 (includes current hand).

12. **Blue Joker**: compiledChips += 104 + 2*value. The value tracks remaining deck size differently.

13. **Lucky Cat**: xMult = 1 + (value + extraValue)/4, where extraValue accumulates lucky triggers during THIS hand's card scoring.

14. **Bull**: chips += 2*value + extraValue, where extraValue = luckyMoney * 40 from card scoring.

15. **Obelisk**: xMult = 1 + (value+1)/5 when NOT playing most-played hand. Resets to 1 when playing most-played.

16. **Spare Trousers**: When Two Pair is present, adds 2 + value*2 (the +2 is the current hand's contribution). Otherwise just value*2.
