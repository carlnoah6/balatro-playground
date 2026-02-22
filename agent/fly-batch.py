#!/usr/bin/env python3
"""Fly.io Remote Batch Runner — launch-only, non-blocking.

Creates Fly machines and exits immediately. Monitoring is done by fly-monitor.py (cron).

Usage:
    python3 fly-batch.py --seed-set-id 1 --strategy-id 10 --workers 4 --machines 3
    python3 fly-batch.py --seeds 10 --workers 4 --strategy-id 8 --stop-ante 8
"""

import argparse
import json
import math
import os
import random
import sys
import time
from datetime import datetime, timezone, timedelta

import psycopg2
import requests

# ── Config ──────────────────────────────────────────────────────────────────

NEON_CONFIG = "/home/ubuntu/.openclaw/workspace/data/neon-config.json"
FLY_TOKEN_FILE = "/home/ubuntu/.openclaw/workspace/data/fly-token.txt"
FLY_APP = "balatro-batch"
FLY_IMAGE = "registry.fly.io/balatro-batch:reroll-econ"
FLY_REGION = "sin"
FLY_API = "https://api.machines.dev/v1"

LLM_BASE_URL = "https://anz-luna.grolar-wage.ts.net/api/v1"
LLM_API_KEY = "sk-luna-2026-openclaw"

SGT = timezone(timedelta(hours=8))
SEED_CHARSET = "ABCDEFGHIJKLMNPQRSTUVWXYZ123456789"

# Machine presets: workers → (cpu_kind, cpus, memory_mb)
# Rule: shared-cpu-8x max 4 workers (benchmark verified 2026-02-20)
MACHINE_PRESETS = {
    1: ("shared", 2, 2048),
    2: ("shared", 4, 4096),
    3: ("shared", 8, 8192),
    4: ("shared", 8, 8192),
}


def get_db_url():
    with open(NEON_CONFIG) as f:
        return json.load(f)["database_url"]


def get_db():
    return psycopg2.connect(get_db_url())


def get_fly_token():
    with open(FLY_TOKEN_FILE) as f:
        return f.read().strip()


def fly_headers():
    return {
        "Authorization": f"Bearer {get_fly_token()}",
        "Content-Type": "application/json",
    }


def generate_seeds(n: int) -> list[str]:
    return ["".join(random.choices(SEED_CHARSET, k=8)) for _ in range(n)]


# ── DB Operations ──────────────────────────────────────────────────────────

def create_batch(name, seeds, stop_ante, seed_set_id=None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO balatro_batches (name, seeds, seed_count, stop_after_ante, seed_set_id) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (name, seeds, len(seeds), stop_ante, seed_set_id)
    )
    bid = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return bid


def create_batch_run(batch_id, strategy_id, total, machine_ids, model, stop_ante):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO balatro_batch_runs
           (batch_id, strategy_id, status, started_at, total_runs, machine_ids, model, stop_ante, fly_image)
           VALUES (%s, %s, 'running', NOW(), %s, %s, %s, %s, %s) RETURNING id""",
        (batch_id, strategy_id, total, json.dumps(machine_ids), model, stop_ante, FLY_IMAGE)
    )
    br_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return br_id


# ── Fly.io Machine Management ─────────────────────────────────────────────

def create_machine(seeds: list[str], workers: int, strategy_id: int,
                   batch_run_id: int, stop_ante: int, model: str) -> str:
    db_url = get_db_url()
    preset = MACHINE_PRESETS.get(workers, ("shared", 8, 8192))

    config = {
        "image": FLY_IMAGE,
        "guest": {
            "cpu_kind": preset[0],
            "cpus": preset[1],
            "memory_mb": preset[2],
        },
        "env": {
            "SEEDS": ",".join(seeds),
            "WORKERS": str(workers),
            "STOP_AFTER_ANTE": str(stop_ante),
            "GAMESPEED": "16",
            "TURBO_MODE": "1",
            "BATCH_RUN_ID": str(batch_run_id),
            "STRATEGY_ID": str(strategy_id),
            "DATABASE_URL": db_url,
            "LLM_BASE_URL": LLM_BASE_URL,
            "LLM_API_KEY": LLM_API_KEY,
            "LLM_MODEL": model,
        },
        "auto_destroy": True,
        "restart": {"policy": "no"},
        "stop": {"timeout": "60m"},
    }

    resp = requests.post(
        f"{FLY_API}/apps/{FLY_APP}/machines",
        headers=fly_headers(),
        json={
            "name": f"batch-{batch_run_id}-{len(seeds)}s-{random.randint(1000,9999)}",
            "region": FLY_REGION,
            "config": config,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["id"]


# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Fly.io remote batch runner (launch-only)")
    parser.add_argument("--seeds", type=int, default=10)
    parser.add_argument("--seed-list", type=str)
    parser.add_argument("--seed-set-id", type=int, help="Use seeds from a seed set in DB")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--machines", type=int, default=3, help="Number of parallel Fly machines")
    parser.add_argument("--strategy-id", type=int, required=True)
    parser.add_argument("--model", type=str, default="gemini-2.5-flash")
    parser.add_argument("--stop-ante", type=int, default=8)
    parser.add_argument("--name", type=str)
    parser.add_argument("--region", type=str, default="sin")
    args = parser.parse_args()

    global FLY_REGION
    FLY_REGION = args.region

    # Resolve seeds
    seed_set_id = None
    if args.seed_set_id:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT name, seeds FROM balatro_seed_sets WHERE id = %s", (args.seed_set_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            print(f"Seed set {args.seed_set_id} not found")
            sys.exit(1)
        ss_name, ss_seeds = row
        seeds = json.loads(ss_seeds) if isinstance(ss_seeds, str) else ss_seeds
        seed_set_id = args.seed_set_id
        print(f"Using seed set: {ss_name} ({len(seeds)} seeds)")
    elif args.seed_list:
        seeds = [s.strip() for s in args.seed_list.split(",")]
    else:
        seeds = generate_seeds(args.seeds)

    total = len(seeds)
    preset = MACHINE_PRESETS.get(args.workers, ("shared", 8, 8192))
    name = args.name or f"fly-{datetime.now(SGT).strftime('%m%d-%H%M')}"

    # Create batch
    batch_id = create_batch(name, seeds, args.stop_ante, seed_set_id=seed_set_id)
    print(f"Created batch: {name} (id={batch_id}, {total} seeds)")

    # Split seeds across machines
    seed_chunks = []
    chunk_size = math.ceil(total / args.machines)
    for i in range(args.machines):
        chunk = seeds[i * chunk_size : (i + 1) * chunk_size]
        if chunk:
            seed_chunks.append(chunk)

    # Create batch_run first (need ID for machines)
    # Use a placeholder, then update with machine IDs
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO balatro_batch_runs
           (batch_id, strategy_id, status, started_at, total_runs, machine_ids, model, stop_ante, fly_image)
           VALUES (%s, %s, 'launching', NOW(), %s, '[]', %s, %s, %s) RETURNING id""",
        (batch_id, args.strategy_id, total, args.model, args.stop_ante, FLY_IMAGE)
    )
    br_id = cur.fetchone()[0]
    conn.commit()
    conn.close()

    print(f"\n{'='*60}")
    print(f"Batch id={batch_id}, batch_run id={br_id}")
    print(f"Seeds: {total}, Machines: {len(seed_chunks)}, Workers/machine: {args.workers}")
    print(f"Strategy: {args.strategy_id}, Model: {args.model}, Stop: Ante {args.stop_ante}")
    print(f"Machine: {preset[0]}-cpu-{preset[1]}x / {preset[2]}MB")
    print(f"Image: {FLY_IMAGE}")
    print(f"Region: {FLY_REGION}")
    print(f"{'='*60}\n")

    # Create machines
    machine_ids = []
    for i, chunk in enumerate(seed_chunks):
        print(f"Creating machine {i+1}/{len(seed_chunks)} ({len(chunk)} seeds)...", flush=True)
        try:
            mid = create_machine(chunk, args.workers, args.strategy_id, br_id, args.stop_ante, args.model)
            machine_ids.append(mid)
            print(f"  ✅ Machine {mid[:12]} created ({len(chunk)} seeds: {chunk[0]}..{chunk[-1]})", flush=True)
        except Exception as e:
            print(f"  ❌ Failed to create machine: {e}", flush=True)

    # Update batch_run with machine IDs and set status to running
    conn = get_db()
    cur = conn.cursor()
    status = "running" if machine_ids else "failed"
    cur.execute(
        "UPDATE balatro_batch_runs SET machine_ids = %s, status = %s WHERE id = %s",
        (json.dumps(machine_ids), status, br_id)
    )
    conn.commit()
    conn.close()

    if not machine_ids:
        print("\n❌ No machines created. Batch failed.")
        sys.exit(1)

    print(f"\n✅ {len(machine_ids)}/{len(seed_chunks)} machines launched.")
    print(f"   fly-monitor.py will track progress and clean up.")
    print(f"   Check status: python3 fly-monitor.py --status")


if __name__ == "__main__":
    main()
