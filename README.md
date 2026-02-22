# Balatro Playground 🃏

AI-powered Balatro strategy development platform.

## Structure

```
balatro-playground/
├── agent/          # Game orchestrator (ai-agent.py, batch system, Fly.io deployment)
├── decision/       # Decision engine (scoring, search, build paths, strategy)
├── simulator/      # Pure Python game simulator (RNG, shop, blinds, MCTS)
├── viewer/         # Web dashboard (FastAPI, Docker)
├── game/           # Lua game mod (ai-mod.lua)
├── knowledgeBase/  # Strategy knowledge base (joker tiers, boss guides)
└── data/           # Shared data files (joker catalog, etc.)
```

## Components

### Agent (`agent/`)
Game orchestrator that connects to Balatro via Lua mod, makes decisions using the decision engine, and logs results to PostgreSQL. Includes batch runner for parallel testing on Fly.io.

### Decision Engine (`decision/`)
Core strategy logic: hand scoring, discard search, shop evaluation, build path planning. No LLM dependency — all knowledge distilled into code.

### Simulator (`simulator/`)
Pure Python Balatro simulator with precise RNG (ported from Immolate's LFSR113 implementation). Enables offline strategy training, seed analysis, and MCTS search.

### Viewer (`viewer/`)
Web dashboard showing game runs, strategies, batches, seed analysis, and tier-based evaluation. FastAPI + server-rendered HTML.

### Game Mod (`game/`)
Lua mod that exposes game state to the AI agent via JSON files.

## Seed Tier System

Seeds are rated S/A/B/C based on Ante 1-3 shop quality (joker tiers, xMult availability, voucher value). Benchmark seed sets use a representative distribution for fair strategy evaluation.

## Key Metrics

- **Weighted Score**: 2^(ante-1) — respects exponential difficulty curve
- **Per-tier analysis**: Compare strategy performance within same seed quality tier
