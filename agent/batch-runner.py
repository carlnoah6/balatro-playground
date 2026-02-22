#!/usr/bin/env python3
"""Batch Runner — parallel strategy evaluation across multiple seeds.

Usage:
    # Create a batch and run it with 3 parallel workers
    python3 batch-runner.py --seeds 10 --workers 3 --strategy-id 8

    # Run a specific batch
    python3 batch-runner.py --batch-id 1 --workers 3

    # Use specific seeds
    python3 batch-runner.py --seed-list "ABC123,DEF456,GHI789" --workers 2
"""

import argparse
import asyncio
import json
import os
import random
import signal
import string
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta

import psycopg2

# ── Config ──────────────────────────────────────────────────────────────────

NEON_CONFIG = "/home/ubuntu/.openclaw/workspace/data/neon-config.json"
BASE_PORT = 12350          # Game containers use 12350, 12351, ...
AGENT_CTRL_BASE = 12390    # Agent ctrl ports: 12390, 12391, ...
DOCKER_IMAGE = "balatro-env-balatro"  # Built from docker-compose
GAME_DIR = "/home/ubuntu/balatro-env/game"
AGENT_DIR = "/home/ubuntu/balatro-env"
STOP_AFTER_ANTE = int(os.environ.get("STOP_AFTER_ANTE", "8"))
GAMESPEED = int(os.environ.get("GAMESPEED", "16"))
LLM_BASE_URL = "http://127.0.0.1:8180/v1"
LLM_API_KEY = "sk-admin-luna2026"
SGT = timezone(timedelta(hours=8))


def get_db():
    with open(NEON_CONFIG) as f:
        url = json.load(f)["database_url"]
    return psycopg2.connect(url)


def generate_seeds(n: int) -> list[str]:
    """Generate N random 8-char seeds matching Balatro's format.
    Characters: A-N, P-Z, 1-9 (skips O and 0 to avoid confusion)."""
    chars = "ABCDEFGHIJKLMNPQRSTUVWXYZ123456789"
    return ["".join(random.choices(chars, k=8)) for _ in range(n)]


# ── Batch DB Operations ────────────────────────────────────────────────────

def create_batch(name: str, seeds: list[str], stop_after_ante: int = 8) -> int:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO balatro_batches (name, seeds, seed_count, stop_after_ante) VALUES (%s, %s, %s, %s) RETURNING id",
        (name, seeds, len(seeds), stop_after_ante)
    )
    batch_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return batch_id


def create_batch_run(batch_id: int, strategy_id: int) -> int:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO balatro_batch_runs (batch_id, strategy_id, status, started_at) VALUES (%s, %s, 'running', NOW()) RETURNING id",
        (batch_id, strategy_id)
    )
    br_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return br_id


def get_batch(batch_id: int) -> dict:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name, seeds, seed_count, stop_after_ante FROM balatro_batches WHERE id = %s", (batch_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        raise ValueError(f"Batch {batch_id} not found")
    return {"id": row[0], "name": row[1], "seeds": row[2], "seed_count": row[3], "stop_after_ante": row[4]}


def update_batch_run(br_id: int, completed_runs: int, total_runs: int, status: str = "running", stats: dict = None):
    conn = get_db()
    cur = conn.cursor()
    if status in ("completed", "failed"):
        cur.execute(
            "UPDATE balatro_batch_runs SET completed_runs=%s, total_runs=%s, status=%s, stats=%s, completed_at=NOW() WHERE id=%s",
            (completed_runs, total_runs, status, json.dumps(stats or {}), br_id)
        )
    else:
        cur.execute(
            "UPDATE balatro_batch_runs SET completed_runs=%s, total_runs=%s, status=%s WHERE id=%s",
            (completed_runs, total_runs, status, br_id)
        )
    conn.commit()
    conn.close()


# ── Container Management ───────────────────────────────────────────────────

class GameWorker:
    """Manages a single game container + agent process."""

    def __init__(self, worker_id: int, port: int, ctrl_port: int):
        self.worker_id = worker_id
        self.port = port
        self.ctrl_port = ctrl_port
        self.container_name = f"balatro-batch-{worker_id}"
        self.agent_proc = None
        self.busy = False
        self.current_seed = None

    async def start_container(self):
        """Start the game container."""
        # Remove if exists
        await _run(f"docker rm -f {self.container_name} 2>/dev/null || true")

        cmd = (
            f"docker run -d --name {self.container_name} "
            f"--cpus=2.0 --memory=2g "
            f"-p {self.port}:12345 "
            f"-v {GAME_DIR}:/opt/balatro-game:ro "
            f"--add-host=host.docker.internal:host-gateway "
            f"-e DISPLAY=:99 "
            f"{DOCKER_IMAGE}"
        )
        await _run(cmd)
        print(f"[worker-{self.worker_id}] Container started on port {self.port}")

        # Wait for game to be ready
        for i in range(30):
            await asyncio.sleep(2)
            try:
                state = await self._get_state()
                if state.get("state") in ("MENU", "MAIN_MENU"):
                    print(f"[worker-{self.worker_id}] Game ready")
                    return True
            except:
                pass
        print(f"[worker-{self.worker_id}] Game failed to start")
        return False

    async def stop_container(self):
        """Stop and remove the container."""
        if self.agent_proc and self.agent_proc.returncode is None:
            self.agent_proc.terminate()
            try:
                await asyncio.wait_for(self.agent_proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.agent_proc.kill()
        await _run(f"docker rm -f {self.container_name} 2>/dev/null || true")

    async def run_seed(self, seed: str, strategy_id: int, batch_run_id: int,
                       stop_after_ante: int, model: str = "gemini-2.5-flash") -> dict:
        """Run a single seed and return results."""
        self.busy = True
        self.current_seed = seed
        print(f"[worker-{self.worker_id}] Starting seed {seed}")

        env = {
            **os.environ,
            "SEED": seed,
            "STOP_AFTER_ANTE": str(stop_after_ante),
            "GAMESPEED": str(GAMESPEED),
            "LARK_VERBOSE": "0",
            "NO_SCREENSHOTS": "1",
            "BALATRO_PORT": str(self.port),
            "CTRL_PORT": str(self.ctrl_port),
            "LLM_BASE_URL": LLM_BASE_URL,
            "LLM_API_KEY": LLM_API_KEY,
            "LLM_MODEL": model,
            "BATCH_RUN_ID": str(batch_run_id),
        }

        log_file = f"/tmp/batch_worker_{self.worker_id}.log"
        with open(log_file, "w") as f:
            self.agent_proc = await asyncio.create_subprocess_exec(
                sys.executable, os.path.join(AGENT_DIR, "ai-agent.py"),
                stdout=f, stderr=f,
                cwd=AGENT_DIR, env=env
            )

        try:
            await asyncio.wait_for(self.agent_proc.wait(), timeout=600)  # 10 min max
            rc = self.agent_proc.returncode
        except asyncio.TimeoutError:
            print(f"[worker-{self.worker_id}] Seed {seed} timed out")
            self.agent_proc.kill()
            rc = -1

        # Read result from log
        result = {"seed": seed, "exit_code": rc, "worker": self.worker_id}
        try:
            with open(log_file) as f:
                log_text = f.read()
            # Extract stats from log
            if '"max_ante"' in log_text:
                import re
                stats_match = re.search(r'\{[^}]*"max_ante"[^}]*\}', log_text)
                if stats_match:
                    result["stats"] = json.loads(stats_match.group())
        except:
            pass

        # Wait for game to return to menu, restart container if needed
        game_ready = False
        for attempt in range(15):
            try:
                state = await self._get_state()
                if state.get("state") in ("MENU", "MAIN_MENU", "SPLASH"):
                    game_ready = True
                    break
            except:
                pass
            await asyncio.sleep(2)

        if not game_ready:
            print(f"[worker-{self.worker_id}] Game not responding, restarting container...")
            await self.stop_container()
            await self.start_container()

        self.busy = False
        self.current_seed = None
        print(f"[worker-{self.worker_id}] Seed {seed} done (exit={rc})")
        return result

    async def _get_state(self) -> dict:
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write(b"state\n")
        await writer.drain()
        data = await asyncio.wait_for(reader.read(8192), timeout=3)
        writer.close()
        await writer.wait_closed()
        return json.loads(data)


async def _run(cmd: str) -> str:
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    return stdout.decode().strip()


# ── Main Orchestrator ──────────────────────────────────────────────────────

async def run_batch(batch_id: int, strategy_id: int, num_workers: int, model: str = "gemini-2.5-flash"):
    """Run all seeds in a batch with parallel workers."""
    batch = get_batch(batch_id)
    seeds = batch["seeds"]
    stop_ante = batch["stop_after_ante"]
    total = len(seeds)

    print(f"\n{'='*60}")
    print(f"Batch: {batch['name']} (id={batch_id})")
    print(f"Seeds: {total}, Workers: {num_workers}, Stop: Ante {stop_ante}")
    print(f"Strategy: {strategy_id}, Model: {model}")
    print(f"{'='*60}\n")

    # Create batch run record
    br_id = create_batch_run(batch_id, strategy_id)

    # Start workers
    workers = []
    for i in range(num_workers):
        w = GameWorker(i, BASE_PORT + i, AGENT_CTRL_BASE + i)
        workers.append(w)

    print(f"Starting {num_workers} game containers...")
    start_results = await asyncio.gather(*[w.start_container() for w in workers])
    active_workers = [w for w, ok in zip(workers, start_results) if ok]

    if not active_workers:
        print("ERROR: No workers started successfully")
        update_batch_run(br_id, 0, total, "failed")
        return

    print(f"{len(active_workers)} workers ready\n")

    # Seed queue
    seed_queue = asyncio.Queue()
    for s in seeds:
        await seed_queue.put(s)

    results = []
    completed = 0

    async def worker_loop(worker: GameWorker):
        nonlocal completed
        while not seed_queue.empty():
            try:
                seed = seed_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            result = await worker.run_seed(seed, strategy_id, br_id, stop_ante, model)
            results.append(result)
            completed += 1
            update_batch_run(br_id, completed, total)
            pct = completed / total * 100
            print(f"[progress] {completed}/{total} ({pct:.0f}%)")

    # Run all workers
    t_start = time.time()
    await asyncio.gather(*[worker_loop(w) for w in active_workers])
    elapsed = time.time() - t_start

    # Aggregate stats
    antes = [r.get("stats", {}).get("max_ante", 0) for r in results if r.get("stats")]
    avg_ante = sum(antes) / len(antes) if antes else 0
    max_ante = max(antes) if antes else 0

    agg_stats = {
        "total_seeds": total,
        "completed": completed,
        "avg_ante": round(avg_ante, 2),
        "max_ante": max_ante,
        "elapsed_seconds": round(elapsed),
        "seeds_per_minute": round(completed / (elapsed / 60), 1) if elapsed > 0 else 0,
    }

    update_batch_run(br_id, completed, total, "completed", agg_stats)

    # Cleanup
    print(f"\nStopping containers...")
    await asyncio.gather(*[w.stop_container() for w in workers])

    print(f"\n{'='*60}")
    print(f"Batch complete: {completed}/{total} seeds")
    print(f"Avg Ante: {avg_ante:.1f}, Max Ante: {max_ante}")
    print(f"Time: {elapsed:.0f}s ({agg_stats['seeds_per_minute']} seeds/min)")
    print(f"{'='*60}")


# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Batch evaluation runner")
    parser.add_argument("--batch-id", type=int, help="Run existing batch")
    parser.add_argument("--seeds", type=int, default=10, help="Number of random seeds")
    parser.add_argument("--seed-list", type=str, help="Comma-separated seed list")
    parser.add_argument("--workers", type=int, default=3, help="Parallel workers")
    parser.add_argument("--strategy-id", type=int, required=True, help="Strategy ID to evaluate")
    parser.add_argument("--model", type=str, default="gemini-2.5-flash", help="LLM model")
    parser.add_argument("--stop-ante", type=int, default=8, help="Stop after ante N")
    parser.add_argument("--name", type=str, help="Batch name")
    args = parser.parse_args()

    if args.batch_id:
        batch_id = args.batch_id
    else:
        # Create new batch
        if args.seed_list:
            seeds = [s.strip() for s in args.seed_list.split(",")]
        else:
            seeds = generate_seeds(args.seeds)

        name = args.name or f"batch-{datetime.now(SGT).strftime('%Y%m%d-%H%M')}"
        batch_id = create_batch(name, seeds, args.stop_ante)
        print(f"Created batch: {name} (id={batch_id}, {len(seeds)} seeds)")

    asyncio.run(run_batch(batch_id, args.strategy_id, args.workers, args.model))


if __name__ == "__main__":
    main()
