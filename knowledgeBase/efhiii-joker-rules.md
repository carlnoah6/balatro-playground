# EFHIII Joker Scoring Rules

Source: /tmp/balatro-calculator/balatro-sim.js
Independent jokers: 52
Per-card jokers: 27
Held-in-hand jokers: 3

## Independent Scoring (triggerJoker)

### Abstract Joker
Config: `{extra = 3}`
```js
this.mult = bigAdd(this.jokers.length * 3, this.mult);
```

### Acrobat
Config: `{extra = 3}`
```js
if(joker[VALUE] !== 0) {
          this.mult = bigTimes(3, this.mult);
        }
```

### Blackboard
Config: `?`
```js
if(this.compiledValues[j]) {
          this.mult = bigTimes(3, this.mult);
        }
```

### Bootstraps
Config: `{extra = {mult = 2, dollars = 5}`
```js
this.mult = bigAdd(joker[VALUE] * 2, this.mult);
```

### Bull
Config: `{extra = 2}`
```js
this.chips += 2 * joker[VALUE] + this.jokersExtraValue[j];
```

### Campfire
Config: `{extra = 0.25}`
```js
this.mult = bigTimes(1 + joker[VALUE] * 0.25, this.mult);
```

### Canio
Config: `{extra = 1}`
```js
this.mult = bigTimes(1 + joker[VALUE], this.mult);
```

### Card Sharp
Config: `{extra = {Xmult = 3}`
```js
if(this.hands[this.typeOfHand][PLAYED_THIS_ROUND]) {
          this.mult = bigTimes(3, this.mult);
        }
```

### Cavendish
Config: `{extra = {odds = 1000, Xmult = 3}`
```js
this.mult = bigTimes(3, this.mult);
```

### Ceremonial Dagger
Config: `{mult = 0}`
```js
this.mult = bigAdd(joker[VALUE], this.mult);
```

### Constellation
Config: `?`
```js
this.mult = bigTimes(1 + joker[VALUE] / 10, this.mult);
```

### Crazy Joker
Config: `{t_mult = 12, type = 'Straight'}`
```js
if(this.hasStraight) {
          this.mult = bigAdd(12, this.mult);
        }
```

### Driver's License
Config: `{extra = 3}`
```js
if(joker[VALUE] >= 16) {
          this.mult = bigTimes(3, this.mult);
        }
```

### Droll Joker
Config: `{t_mult = 10, type = 'Flush'}`
```js
if(this.hasFlush) {
          this.mult = bigAdd(10, this.mult);
        }
```

### Erosion
Config: `{extra = 4}`
```js
this.mult = bigAdd(joker[VALUE] * 4, this.mult);
```

### Flash Card
Config: `{extra = 2, mult = 0}`
```js
this.mult = bigAdd(joker[VALUE] * 2, this.mult);
```

### Flower Pot
Config: `{extra = 3}`
```js
if(this.compiledValues[j]) {
          this.mult = bigTimes(3, this.mult);
        }
```

### Fortune Teller
Config: `{extra = 1}`
```js
this.mult = bigAdd(joker[VALUE], this.mult);
```

### Glass Joker
Config: `{extra = 0.75, Xmult = 1}`
```js
this.mult = bigTimes(this.compiledValues[j], this.mult);
```

### Green Joker
Config: `?`
```js
this.mult = bigAdd(1 + joker[VALUE], this.mult);
```

### Gros Michel
Config: `{extra = {odds = 6, mult = 15}`
```js
this.mult = bigAdd(15, this.mult);
```

### Half Joker
Config: `{extra = {mult = 20, size = 3}`
```js
if(this.cards.length <= 3) {
          this.mult = bigAdd(20, this.mult);
        }
```

### Hit the Road
Config: `{extra = 0.5}`
```js
this.mult = bigTimes(1 + joker[VALUE] * 0.5, this.mult);
```

### Hologram
Config: `{extra = 0.25, Xmult = 1}`
```js
this.mult = bigTimes(1 + joker[VALUE] * 0.25, this.mult);
```

### Joker
Config: `{mult = 4}`
```js
this.mult = bigAdd(4, this.mult);
```

### Joker Stencil
Config: `{}`
```js
this.mult = bigTimes(1 + joker[VALUE], this.mult);
```

### Jolly Joker
Config: `{t_mult = 8, type = 'Pair'}`
```js
if(this.hasPair) {
          this.mult = bigAdd(8, this.mult);
        }
```

### Loyalty Card
Config: `{extra = {Xmult = 4, every = 5, remaining = "5 remaining"}`
```js
if(joker[VALUE] === 0) {
          this.mult = bigTimes(4, this.mult);
        }
```

### Lucky Cat
Config: `{Xmult = 1, extra = 0.25}`
```js
this.mult = bigTimes(1 + (joker[VALUE] + this.jokersExtraValue[j]) / 4, this.mult);
```

### Mad Joker
Config: `{t_mult = 10, type = 'Two Pair'}`
```js
if(this.hasTwoPair) {
          this.mult = bigAdd(10, this.mult);
        }
```

### Madness
Config: `{extra = 0.5}`
```js
this.mult = bigTimes(1 + joker[VALUE] * 0.5, this.mult);
```

### Misprint
Config: `{extra = {max = 23, min = 0}`
```js
switch(this.randomMode) {
          case 0:
            this.mult = bigAdd(23, this.mult);
```

### Mystic Summit
Config: `{extra = {mult = 15, d_remaining = 0}`
```js
if(joker[VALUE] !== 0) {
          this.mult = bigAdd(15, this.mult);
        }
```

### Obelisk
Config: `{extra = 0.2, Xmult = 1}`
```js
this.mult = bigTimes(this.compiledValues[j], this.mult);
```

### Popcorn
Config: `{mult = 20, extra = 4}`
```js
this.mult = bigAdd(20 - joker[VALUE] * 4, this.mult);
```

### Ramen
Config: `{Xmult = 2, extra = 0.01}`
```js
this.mult = bigTimes(2 - joker[VALUE] / 100, this.mult);
```

### Red Card
Config: `{extra = 3}`
```js
this.mult = bigAdd(joker[VALUE] * 3, this.mult);
```

### Ride the Bus
Config: `{extra = 1}`
```js
this.mult = bigAdd(this.compiledValues[j], this.mult);
```

### Seeing Double
Config: `{extra = 2}`
```js
if(this.compiledValues[j]) {
          this.mult = bigTimes(2, this.mult);
        }
```

### Spare Trousers
Config: `{extra = 2}`
```js
if(this.hasTwoPair) {
          this.compiledValues[j] = 1;
          this.mult = bigAdd(2 + joker[VALUE] * 2, this.mult);
        }
        else {
          this.mult = bigAdd(joker[VALUE] * 2, this.mult);
        }
```

### Steel Joker
Config: `{extra = 0.2}`
```js
this.mult = bigTimes(this.compiledValues[j], this.mult);
```

### Supernova
Config: `{extra = 1}`
```js
this.mult = bigAdd(this.hands[this.typeOfHand][PLAYED] + 1, this.mult);
```

### Swashbuckler
Config: `{mult = 1}`
```js
this.mult = bigAdd(this.compiledValues[j], this.mult);
```

### The Duo
Config: `{Xmult = 2, type = 'Pair'}`
```js
if(this.hasPair) {
          this.mult = bigTimes(2, this.mult);
        }
```

### The Family
Config: `{Xmult = 4, type = 'Four of a Kind'}`
```js
if(this.hasFourOfAKind) {
          this.mult = bigTimes(4, this.mult);
        }
```

### The Order
Config: `{Xmult = 3, type = 'Straight'}`
```js
if(this.hasStraight) {
          this.mult = bigTimes(3, this.mult);
        }
```

### The Tribe
Config: `{Xmult = 2, type = 'Flush'}`
```js
if(this.hasFlush) {
          this.mult = bigTimes(2, this.mult);
        }
```

### The Trio
Config: `{Xmult = 3, type = 'Three of a Kind'}`
```js
if(this.hasThreeOfAKind) {
          this.mult = bigTimes(3, this.mult);
        }
```

### Throwback
Config: `{extra = 0.25}`
```js
this.mult = bigTimes(1 + joker[VALUE] * 0.25, this.mult);
```

### Vampire
Config: `{extra = 0.1, Xmult = 1}`
```js
this.mult = bigTimes(1 + this.compiledValues[j] / 10, this.mult);
```

### Yorick
Config: `{extra = {xmult = 1, discards = 23}`
```js
this.mult = bigTimes(joker[VALUE], this.mult);
```

### Zany Joker
Config: `{t_mult = 12, type = 'Three of a Kind'}`
```js
if(this.hasThreeOfAKind) {
          this.mult = bigAdd(12, this.mult);
        }
```

## Per-Card Scoring (triggerCard)

### Ancient Joker
Config: `{extra = 1.5}`
```js
if(card[ENHANCEMENT] === WILD || (this.SmearedJoker ? card[SUIT] % 2 === Math.abs(joker[VALUE]) % 2 : card[SUIT] === Math.abs(joker[VALUE]) % 4)) {
              this.mult = bigTimes(1.5, this.mult);
            }
```

### Arrowhead
Config: `{extra = 50}`
```js
if(card[SUIT] === SPADES || (this.SmearedJoker && card[SUIT] === CLUBS)) {
              this.chips += 50;
            }
            else if(card[SUIT] === true) {
              this.chips += 50;
            }
```

### Bloodstone
Config: `{extra = {odds = 2, Xmult = 1.5}`
```js
if(card[SUIT] === HEARTS || (this.SmearedJoker && card[SUIT] === DIAMONDS)) {
              switch(this.randomMode) {
                case 0:
                  this.mult = bigTimes(1.5, this.mult);
```

### Bull
Config: `{extra = 2}`
```js
this.jokersExtraValue[j] += luckyMoney * 40;
```

### Dusk
Config: `{extra = 1}`
```js
if(joker[VALUE] !== 0) {
              this.triggerCard(card, true);
            }
```

### Even Steven
Config: `{extra = 4}`
```js
if(card[RANK] % 2 === 0 && card[RANK] <= _10) {
              this.mult = bigAdd(4, this.mult);
            }
```

### Fibonacci
Config: `{extra = 8}`
```js
if(card[RANK] === ACE || card[RANK] === _8 || card[RANK] === _5 || card[RANK] === _3 || card[RANK] === _2) {
              this.mult = bigAdd(8, this.mult);
            }
```

### Gluttonous Joker
Config: `{extra = {s_mult = 3, suit = 'Clubs'}`
```js
if(card[SUIT] === CLUBS || (this.SmearedJoker && card[SUIT] === SPADES)) {
              this.mult = bigAdd(3, this.mult);
            }
            else if(card[SUIT] === true) {
              this.mult = bigAdd(3, this.mult);
            }
```

### Greedy Joker
Config: `{extra = {s_mult = 3, suit = 'Diamonds'}`
```js
if(card[SUIT] === DIAMONDS || (this.SmearedJoker && card[SUIT] === HEARTS)) {
              this.mult = bigAdd(3, this.mult);
            }
            else if(card[SUIT] === true) {
              this.mult = bigAdd(3, this.mult);
            }
```

### Hack
Config: `{extra = 1}`
```js
if(card[RANK] <= _5) {
              this.triggerCard(card, true);
            }
```

### Hanging Chad
Config: `{extra = 2}`
```js
if(this.jokersExtraValue[j] === 0) {
              this.jokersExtraValue[j]++;
              this.triggerCard(card, true);
              this.triggerCard(card, true);
            }
```

### Hiker
Config: `?`
```js
card[EXTRA_EXTRA_CHIPS] += 4;
```

### Lucky Cat
Config: `{Xmult = 1, extra = 0.25}`
```js
this.jokersExtraValue[j] += luckyTriggers;
```

### Lusty Joker
Config: `{extra = {s_mult = 3, suit = 'Hearts'}`
```js
if(card[SUIT] === HEARTS || (this.SmearedJoker && card[SUIT] === DIAMONDS)) {
              this.mult = bigAdd(3, this.mult);
            }
            else if(card[SUIT] === true) {
              this.mult = bigAdd(3, this.mult);
            }
```

### Odd Todd
Config: `{extra = 31}`
```js
if((card[RANK] % 2 === 1 && card[RANK] <= _9) || card[RANK] === ACE) {
              this.chips += 31;
            }
```

### Onyx Agate
Config: `{extra = 7}`
```js
if(card[SUIT] === CLUBS || (this.SmearedJoker && card[SUIT] === SPADES)) {
              this.mult = bigAdd(7, this.mult);
            }
            else if(card[SUIT] === true) {
              this.mult = bigAdd(7, this.mult);
            }
```

### Photograph
Config: `{extra = 2}`
```js
if(this.jokersExtraValue[j] === card || this.jokersExtraValue[j] === 0) {
              this.jokersExtraValue[j] = card;
              this.mult = bigTimes(2, this.mult);
            }
```

### Scary Face
Config: `{extra = 30}`
```js
this.chips += 30;
```

### Scholar
Config: `{extra = {mult = 4, chips = 20}`
```js
if(card[RANK] === ACE) {
              this.chips += 20;
              this.mult = bigAdd(4, this.mult);
            }
```

### Seltzer
Config: `{extra = 10}`
```js
this.triggerCard(card, true);
```

### Smiley Face
Config: `{extra = 5}`
```js
this.mult = bigAdd(5, this.mult);
```

### Sock and Buskin
Config: `{extra = 1}`
```js
if(isFace) {
              this.triggerCard(card, true);
            }
```

### The Idol
Config: `{extra = 2}`
```js
if(card[SUIT] === Math.abs(joker[VALUE]) % 4 && card[RANK] === Math.floor(Math.abs(joker[VALUE]) / 4) % 13) {
              this.mult = bigTimes(2, this.mult);
            }
```

### Triboulet
Config: `{extra = 2}`
```js
if(card[RANK] === KING || card[RANK] === QUEEN) {
              this.mult = bigTimes(2, this.mult);
            }
```

### Walkie Talkie
Config: `{extra = {chips = 10, mult = 4}`
```js
if(card[RANK] === _4 || card[RANK] === _10) {
              this.chips += 10;
              this.mult = bigAdd(4, this.mult);
            }
```

### Wee Joker
Config: `{extra = {chips = 0, chip_mod = 8}`
```js
if(card[RANK] === _2) {
              this.chips += 8;
            }
```

### Wrathful Joker
Config: `{extra = {s_mult = 3, suit = 'Spades'}`
```js
if(card[SUIT] === SPADES || (this.SmearedJoker && card[SUIT] === CLUBS)) {
              this.mult = bigAdd(3, this.mult);
            }
            else if(card[SUIT] === true) {
              this.mult = bigAdd(3, this.mult);
            }
```

## Held-in-Hand Scoring (triggerCardInHand)

### Baron
Config: `{extra = 1.5}`
```js
if(card[RANK] === KING && card[ENHANCEMENT] !== STONE) {
            this.compiledInHandPlusMult = bigTimes(1.5, this.compiledInHandPlusMult);
            this.compiledInHandTimesMult = bigTimes(1.5, this.compiledInHandTimesMult);
          }
```

### Raised Fist
Config: `{}`
```js
if(card === this.compiledValues[j] && card[ENHANCEMENT] !== STONE) {
            this.compiledInHandPlusMult = bigAdd(2 * (card[RANK] === ACE ? 11 : Math.min(10, card[RANK] + 2)), this.compiledInHandPlusMult);
          }
```

### Shoot the Moon
Config: `{extra = 13}`
```js
if(card[RANK] === QUEEN && card[ENHANCEMENT] !== STONE) {
            this.compiledInHandPlusMult = bigAdd(13, this.compiledInHandPlusMult);
          }
```

