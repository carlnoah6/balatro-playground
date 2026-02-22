# Balatro Datasets on Hugging Face

## Overview

There are **3 Balatro-related datasets** on Hugging Face, all focused on **computer vision / object detection** — not game strategy or replay data. They are designed for training YOLO models to visually parse the Balatro game screen.

There are **no** Balatro strategy datasets, game replay logs, or win-rate databases on Hugging Face as of Feb 2026.

---

## Dataset 1: proj-airi/games-balatro-2024-entities-detection

- **URL:** https://huggingface.co/datasets/proj-airi/games-balatro-2024-entities-detection
- **License:** CC BY-SA 4.0
- **Size:** < 1K images (~286 annotated screenshots)
- **Downloads:** 141
- **Format:** YOLO (imagefolder with txt labels)
- **Task:** Object detection — detecting card entities in Balatro screenshots
- **Part of:** [Project AIRI "Play Balatro" collection](https://huggingface.co/collections/proj-airi/play-balatro-68d24c74ef9568b287f3ce94)

### Classes (10 entity types)

| Class ID | Label | Description |
|----------|-------|-------------|
| 0 | `card_description` | Card description tooltip/popup |
| 1 | `card_pack` | Booster pack cards |
| 2 | `joker_card` | Joker cards |
| 3 | `planet_card` | Planet cards |
| 4 | `poker_card_back` | Face-down playing cards |
| 5 | `poker_card_description` | Playing card description |
| 6 | `poker_card_front` | Face-up playing cards |
| 7 | `poker_card_stack` | Stack/deck of cards |
| 8 | `spectral_card` | Spectral cards |
| 9 | `tarot_card` | Tarot cards |

### Label Format (YOLO)

Each `.txt` label file contains lines in YOLO format:
```
<class_id> <x_center> <y_center> <width> <height>
```
All values are normalized (0-1) relative to image dimensions.

Example:
```
6 0.5 0.4091737739192514 0.10222970130416485 0.2749582488749505
7 0.8271581359816653 0.8372406140572229 0.10122230710465999 0.27045618741120464
2 0.4101003900043334 0.13911960132890364 0.07755042307487621 0.22176079734219267
```

### File Structure
```
data/train/
├── metadata.jsonl
└── yolo/
    ├── classes.txt
    ├── images/
    │   ├── out_00001.jpg
    │   ├── out_00002.jpg
    │   └── ... (~286 images)
    └── labels/
        ├── out_00001.txt
        ├── out_00002.txt
        └── ...
```

---

## Dataset 2: proj-airi/games-balatro-2024-ui-detection

- **URL:** https://huggingface.co/datasets/proj-airi/games-balatro-2024-ui-detection
- **License:** CC BY-SA 4.0
- **Size:** 1K-10K images (~1,130 annotated screenshots)
- **Downloads:** 99
- **Format:** YOLO (text labels)
- **Task:** Object detection — detecting UI elements (buttons, score panels, data displays)

### Classes (33 UI element types)

| Class ID | Label | Description |
|----------|-------|-------------|
| 0 | `button_back` | Back button |
| 1 | `button_card_pack_skip` | Skip card pack button |
| 2 | `button_cash_out` | Cash out button |
| 3 | `button_discard` | Discard hand button |
| 4 | `button_level_select` | Level/ante select |
| 5 | `button_level_skip` | Skip level button |
| 6 | `button_main_menu` | Main menu button |
| 7 | `button_main_menu_play` | Play from main menu |
| 8 | `button_new_run` | New run button |
| 9 | `button_new_run_play` | Start new run play |
| 10 | `button_options` | Options button |
| 11 | `button_play` | Play hand button |
| 12 | `button_purchase` | Purchase button (shop) |
| 13 | `button_run_info` | Run info button |
| 14 | `button_sell` | Sell card button |
| 15 | `button_sort_hand_rank` | Sort by rank button |
| 16 | `button_sort_hand_suits` | Sort by suit button |
| 17 | `button_store_next_round` | Next round (from shop) |
| 18 | `button_store_reroll` | Reroll shop button |
| 19 | `button_use` | Use consumable button |
| 20 | `ui_card_value` | Card value display |
| 21 | `ui_data_cash` | Cash/money display |
| 22 | `ui_data_discards_left` | Remaining discards |
| 23 | `ui_data_hands_left` | Remaining hands |
| 24 | `ui_round_ante_current` | Current ante number |
| 25 | `ui_round_ante_left` | Ante progress indicator |
| 26 | `ui_round_round_current` | Current round number |
| 27 | `ui_round_round_left` | Round progress indicator |
| 28 | `ui_score_chips` | Chips component of score |
| 29 | `ui_score_current` | Current score |
| 30 | `ui_score_mult` | Multiplier component |
| 31 | `ui_score_round_score` | Round score display |
| 32 | `ui_score_target_score` | Target score to beat |

### File Structure
```
data/train/
├── metadata.jsonl
└── yolo/
    ├── classes.txt
    ├── images/
    │   ├── desktop_luoling8192_2025_09_17_23_02_out_00001.jpg
    │   ├── mobile_nekomeowww_2025_09_19_21_54_out_00001.jpg
    │   └── ... (~1,130 images, desktop + mobile)
    └── labels/
        └── ... (matching .txt files)
```

Note: This dataset includes both desktop and mobile screenshots, making the models more robust across platforms.

---

## Dataset 3: juleslagarde/balatro_bbox

- **URL:** https://huggingface.co/datasets/juleslagarde/balatro_bbox
- **License:** Not specified
- **Size:** 10 images (~892 KB total)
- **Downloads:** 11
- **Format:** COCO JSON + per-image JSON annotations
- **Task:** Object detection — card bounding boxes with rich metadata

### Annotation Schema (per-image JSON)

Each image has a companion `.json` file with detailed card annotations:

```json
{
  "image": null,
  "annotation": [
    {
      "type": "joker",
      "name": "JokerHallucination",
      "enhancement": "none",
      "seal": "none",
      "bbox": [135, 274, 128, 171]
    },
    {
      "type": "joker",
      "name": "JokerSlyJoker",
      "enhancement": "none",
      "seal": "none",
      "bbox": [429, 274, 128, 171]
    }
  ]
}
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | Card category: `joker`, `poker`, `tarot`, `planet`, `spectral` |
| `name` | string | Specific card name (e.g., `JokerHallucination`, `JokerSlyJoker`) |
| `enhancement` | string | Card enhancement: `none`, `bonus`, `mult`, `wild`, `glass`, `steel`, `stone`, `gold`, `lucky` |
| `seal` | string | Card seal: `none`, `gold`, `red`, `blue`, `purple` |
| `bbox` | [x, y, w, h] | Bounding box in pixels |

### COCO Annotations

Also includes `coco_annotations.json` with standard COCO format (categories with supercategories).

### Key Insight

This is the most semantically rich dataset — it identifies specific card names, enhancements, and seals. However, it's tiny (10 images) and more of a proof-of-concept.

---

## Related Models (Pre-trained YOLO)

The proj-airi team also published trained YOLO models:

| Model | Purpose | URL |
|-------|---------|-----|
| Entities Detection | Cards, card stacks | https://huggingface.co/proj-airi/games-balatro-2024-yolo-entities-detection |
| UI Detection | Buttons, scores, panels | https://huggingface.co/proj-airi/games-balatro-2024-yolo-ui-detection |

---

## Related Projects

### balatro-gym (Gymnasium Environment)
- **URL:** https://github.com/cassiusfive/balatro-gym
- Provides a standard Gymnasium RL environment for Balatro v1.0.0
- Includes `expert_agent.py` and `generate_trajectories.py` for creating training data
- Could be used to generate strategy datasets via self-play

### proj-airi/game-playing-ai-balatro
- **URL:** https://github.com/proj-airi/game-playing-ai-balatro
- CV + LLM approach to playing Balatro (YOLO + RapidOCR + LLM)
- The source of the two proj-airi datasets above
- Uses screen capture → YOLO detection → OCR → LLM decision pipeline

---

## Relevance to Our Balatro AI Agent

### What these datasets CAN help with

1. **Screen parsing / game state extraction** — If our agent uses screen capture (like proj-airi does), these YOLO datasets are directly useful for training object detection models to identify:
   - Which cards are in hand (poker_card_front)
   - Which jokers are active (joker_card)
   - Available consumables (tarot_card, planet_card, spectral_card)
   - Current game state (scores, hands left, discards left, cash)
   - Available actions (which buttons are visible/clickable)

2. **UI automation** — The UI detection dataset maps all interactive buttons, enabling automated clicking/interaction.

3. **Card identification** — The juleslagarde dataset's rich annotations (card names, enhancements, seals) could bootstrap a card recognition pipeline.

### What these datasets CANNOT help with

1. **Strategy / decision-making** — None of these datasets contain game logs, win rates, hand evaluations, or strategic decisions. They are purely visual.

2. **Joker synergy data** — No information about which joker combinations are effective.

3. **Scoring optimization** — No data about optimal hand selection given a set of cards.

4. **Run progression** — No data about shop decisions, card upgrades, or long-term strategy.

### Recommendations for Our Agent

1. **If using screen-capture approach:** Use the proj-airi YOLO models directly (pre-trained) or fine-tune on their datasets. This saves significant labeling effort.

2. **If using API/memory-reading approach:** These datasets have limited value since we'd read game state directly.

3. **For strategy data, consider:**
   - Using `balatro-gym` to generate trajectories via self-play with an expert agent
   - Scraping strategy guides from the Balatro wiki/subreddit
   - Building our own dataset by logging decisions during gameplay
   - Implementing the scoring rules directly (they're deterministic) rather than learning them

4. **Hybrid approach:** Use YOLO for screen reading + rule-based scoring engine + LLM for complex decisions (joker synergies, shop strategy).

---

## Code: Loading the Datasets

### Loading proj-airi entities dataset

```python
from datasets import load_dataset

# Load the entities detection dataset
entities_ds = load_dataset("proj-airi/games-balatro-2024-entities-detection")
print(entities_ds)
print(entities_ds['train'][0])
```

### Loading proj-airi UI dataset

```python
from datasets import load_dataset

# Load the UI detection dataset
ui_ds = load_dataset("proj-airi/games-balatro-2024-ui-detection")
print(ui_ds)
```

### Using the pre-trained YOLO models directly

```python
from ultralytics import YOLO
from huggingface_hub import hf_hub_download
import cv2

# Download entity detection model
model_path = hf_hub_download(
    repo_id="proj-airi/games-balatro-2024-yolo-entities-detection",
    filename="best.pt"  # or whatever the weight file is named
)

# Load and run inference
model = YOLO(model_path)
results = model("screenshot.png")

# Parse detections
for result in results:
    for box in result.boxes:
        cls_id = int(box.cls[0])
        conf = float(box.conf[0])
        x1, y1, x2, y2 = box.xyxy[0].tolist()
        print(f"Class: {cls_id}, Confidence: {conf:.2f}, Box: ({x1:.0f}, {y1:.0f}, {x2:.0f}, {y2:.0f})")
```

### Loading juleslagarde dataset manually

```python
import json
from huggingface_hub import hf_hub_download

# Download a sample annotation
json_path = hf_hub_download(
    repo_id="juleslagarde/balatro_bbox",
    filename="assets/unity_import/00000000.json",
    repo_type="dataset"
)

with open(json_path) as f:
    data = json.load(f)

for card in data["annotation"]:
    print(f"  {card['type']}: {card['name']} (enhancement={card['enhancement']}, seal={card['seal']})")
    print(f"    bbox: {card['bbox']}")
```

### Processing YOLO labels for analysis

```python
"""
Parse YOLO label files to understand class distribution in the entities dataset.
"""
from huggingface_hub import snapshot_download
from pathlib import Path
from collections import Counter

ENTITY_CLASSES = [
    "card_description", "card_pack", "joker_card", "planet_card",
    "poker_card_back", "poker_card_description", "poker_card_front",
    "poker_card_stack", "spectral_card", "tarot_card"
]

# Download the full dataset
dataset_path = snapshot_download(
    repo_id="proj-airi/games-balatro-2024-entities-detection",
    repo_type="dataset"
)

labels_dir = Path(dataset_path) / "data" / "train" / "yolo" / "labels"
class_counts = Counter()

for label_file in labels_dir.glob("*.txt"):
    with open(label_file) as f:
        for line in f:
            parts = line.strip().split()
            if parts:
                cls_id = int(parts[0])
                class_counts[cls_id] += 1

print("Class distribution:")
for cls_id, count in sorted(class_counts.items()):
    print(f"  {ENTITY_CLASSES[cls_id]:30s}: {count}")
```

---

## Summary

The Hugging Face Balatro ecosystem is focused on **computer vision** for screen parsing, not game strategy. The most valuable assets are:

1. **Pre-trained YOLO models** from proj-airi — ready to use for screen reading
2. **~1,400 annotated screenshots** across entities + UI datasets — useful for fine-tuning
3. **juleslagarde's rich card annotations** — useful schema for card identification (but tiny)

For strategy/decision-making, we need to build our own knowledge base from game rules, community guides, and self-play data (e.g., via balatro-gym).
