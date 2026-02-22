#!/usr/bin/env python3
"""Fly.io Batch Monitor — runs via cron every 2 minutes.

Checks all 'running' batch_runs:
1. Counts completed seeds in DB
2. Checks if Fly machines are still alive
3. If all seeds done OR all machines stopped → finalize batch, stop machines
4. Prints status summary (captured by cron for logging)

No long-running loops. Runs once and exits.
"""

import json
import os
import sys
import time

import psycopg2
import requests

NEON_CONFIG = "/home/ubuntu/.openclaw/workspace/data/neon-config.json"
FLY_TOKEN_FILE = "/home/ubuntu/.openclaw/workspace/data/fly-token.txt"
FLY_APP = "balatro-batch"
FLY_API = "https://api.machines.dev/v1"


def get_db_url():
    with open(NEON_CONFIG) as f:
        return json.load(f)["database_url"]


def get_db():
    return psycopg2.connect(get_db_url())


def fly_headers():
    with open(FLY_TOKEN_FILE) as f:
        token = f.read().strip()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def get_machine_state(machine_id: str) -> str:
    try:
        resp = requests.get(
            f"{FLY_API}/apps/{FLY_APP}/machines/{machine_id}",
            headers=fly_headers(), timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("state", "unknown")
    except Exception:
        return "unknown"


def stop_machine(machine_id: str):
    try:
        requests.post(
            f"{FLY_API}/apps/{FLY_APP}/machines/{machine_id}/stop",
            headers=fly_headers(), timeout=10,
        )
    except Exception:
        pass


def destroy_machine(machine_id: str):
    try:
        requests.delete(
            f"{FLY_API}/apps/{FLY_APP}/machines/{machine_id}?force=true",
            headers=fly_headers(), timeout=10,
        )
    except Exception:
        pass


def check_batch_run(cur, br):
    """Check a single running batch_run. Returns (is_done, summary_str)."""
    br_id = br["id"]
    batch_id = br["batch_id"]
    total = br["total_runs"]
    machine_ids = br.get("machine_ids") or []
    started_at = br["started_at"]

    # Count completed seeds (any status except 'running')
    cur.execute("""
        SELECT count(*) as total,
               count(*) FILTER (WHERE status IN ('completed', 'failed')) as finished,
               count(*) FILTER (WHERE status = 'running') as running
        FROM balatro_runs WHERE batch_run_id = %s
    """, (br_id,))
    row = cur.fetchone()
    db_total, db_finished, db_running = row

    # Get ante stats
    cur.execute("""
        SELECT final_ante FROM balatro_runs
        WHERE batch_run_id = %s AND final_ante IS NOT NULL
    """, (br_id,))
    antes = [r[0] for r in cur.fetchall()]
    avg_ante = sum(antes) / len(antes) if antes else 0
    max_ante = max(antes) if antes else 0

    # Check machine states
    alive_machines = 0
    for mid in machine_ids:
        state = get_machine_state(mid)
        if state in ("started", "starting"):
            alive_machines += 1

    elapsed = (time.time() - started_at.timestamp()) if started_at else 0
    elapsed_min = elapsed / 60

    summary = (f"Batch run {br_id} (batch {batch_id}): "
               f"{db_finished}/{total} done, {db_running} running, "
               f"avg_ante={avg_ante:.2f}, max_ante={max_ante}, "
               f"{alive_machines}/{len(machine_ids)} machines alive, "
               f"{elapsed_min:.0f}min elapsed")

    # Determine if batch is done
    all_seeds_done = db_finished >= total and db_running == 0
    all_machines_dead = alive_machines == 0 and elapsed_min > 2  # grace period
    timed_out = elapsed_min > 65  # 60min machine timeout + 5min grace
    # Orphaned: machines dead but DB still has "running" runs (stale)
    orphaned = all_machines_dead and db_running > 0 and elapsed_min > 5

    is_done = all_seeds_done or (all_machines_dead and db_running == 0) or timed_out or orphaned

    if orphaned:
        # Mark orphaned runs as failed
        cur.execute("""
            UPDATE balatro_runs SET status='failed'
            WHERE batch_run_id = %s AND status = 'running'
        """, (br_id,))
        db_finished += db_running
        db_running = 0
        summary += " [orphaned runs marked failed]"

    if is_done:
        # Finalize
        stats = {
            "total_seeds": total,
            "completed": db_finished,
            "avg_ante": round(avg_ante, 2),
            "max_ante": max_ante,
            "duration_seconds": round(elapsed),
            "platform": "fly.io",
            "machines": len(machine_ids),
        }
        status = "completed" if db_finished >= total else "failed"
        cur.execute(
            "UPDATE balatro_batch_runs SET status=%s, stats=%s, completed_at=NOW(), completed_runs=%s WHERE id=%s",
            (status, json.dumps(stats), db_finished, br_id)
        )

        # Stop any remaining machines
        for mid in machine_ids:
            stop_machine(mid)

        summary += f" → FINALIZED ({status})"
    else:
        # Update progress
        cur.execute(
            "UPDATE balatro_batch_runs SET completed_runs=%s WHERE id=%s",
            (db_finished, br_id)
        )

    return is_done, summary


def main():
    conn = get_db()
    cur = conn.cursor()

    # Find all running batch_runs
    cur.execute("""
        SELECT id, batch_id, total_runs, machine_ids, started_at, model, stop_ante
        FROM balatro_batch_runs WHERE status = 'running'
        ORDER BY id
    """)
    columns = [desc[0] for desc in cur.description]
    running = [dict(zip(columns, row)) for row in cur.fetchall()]

    if not running:
        # Nothing to monitor
        return

    print(f"[fly-monitor] {len(running)} running batch(es)", flush=True)

    for br in running:
        is_done, summary = check_batch_run(cur, br)
        print(f"  {summary}", flush=True)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
