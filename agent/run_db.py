"""Database helper for Balatro AI agent — writes run data to Neon PostgreSQL."""

import json
import os
import psycopg2
from datetime import datetime, timezone, timedelta

SGT = timezone(timedelta(hours=8))
NEON_CONFIG = "/home/ubuntu/.openclaw/workspace/data/neon-config.json"


def _get_conn():
    # Support DATABASE_URL env var for remote (Fly.io) workers
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        with open(NEON_CONFIG) as f:
            db_url = json.load(f)["database_url"]
    return psycopg2.connect(db_url)


def generate_run_code() -> str:
    """Generate run_code like 20260219-001 (auto-increment per day).
    Uses advisory lock to prevent race conditions in parallel batch runs."""
    conn = _get_conn()
    cur = conn.cursor()
    today = datetime.now(SGT).strftime("%Y%m%d")
    prefix = f"{today}-"

    # Advisory lock on a hash of the date to serialize run_code generation
    lock_id = int(today) % (2**31)
    cur.execute("SELECT pg_advisory_lock(%s)", (lock_id,))

    try:
        cur.execute(
            "SELECT run_code FROM balatro_runs WHERE run_code LIKE %s ORDER BY run_code DESC LIMIT 1",
            (prefix + "%",),
        )
        row = cur.fetchone()
        if row:
            last_num = int(row[0].split("-")[1])
            code = f"{today}-{last_num + 1:03d}"
        else:
            code = f"{today}-001"

        # Insert a placeholder immediately to reserve the code
        cur.execute(
            """INSERT INTO balatro_runs (run_code, status, played_at)
               VALUES (%s, 'pending', NOW()) RETURNING id""",
            (code,),
        )
        run_id = cur.fetchone()[0]
        conn.commit()
    finally:
        cur.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))
        conn.commit()
        conn.close()

    return code, run_id


def create_run(run_code: str, config: dict, llm_model: str, run_id: int = None) -> int:
    """Create or update a run record. If run_id is provided (from generate_run_code),
    update the placeholder. Otherwise insert a new row."""
    conn = _get_conn()
    cur = conn.cursor()
    if run_id:
        cur.execute(
            """UPDATE balatro_runs SET status='running', config=%s, llm_model=%s, played_at=NOW()
               WHERE id=%s RETURNING id""",
            (json.dumps(config), llm_model, run_id),
        )
    else:
        cur.execute(
            """INSERT INTO balatro_runs (run_code, status, config, llm_model, played_at)
               VALUES (%s, 'running', %s, %s, NOW())
               RETURNING id""",
            (run_code, json.dumps(config), llm_model),
        )
    run_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return run_id


def update_run(db_id: int, **kwargs):
    """Update run fields. Accepts any column name as kwarg."""
    if not kwargs:
        return
    conn = _get_conn()
    cur = conn.cursor()
    sets = []
    vals = []
    for k, v in kwargs.items():
        sets.append(f"{k} = %s")
        vals.append(json.dumps(v) if isinstance(v, dict) else v)
    vals.append(db_id)
    cur.execute(f"UPDATE balatro_runs SET {', '.join(sets)} WHERE id = %s", vals)
    conn.commit()
    conn.close()


def add_screenshot(db_id: int, seq: int, filename: str, caption: str,
                   event_type: str = "", source: str = "", detail: dict = None,
                   estimated_score: int = None, actual_score: int = None,
                   score_error: float = None, hand_type: str = None,
                   chips_before: int = None, chips_after: int = None):
    """Record a screenshot event with optional score tracking."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO balatro_screenshots 
           (run_id, seq, filename, caption, event_type, source, detail,
            estimated_score, actual_score, score_error, hand_type, chips_before, chips_after)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (db_id, seq, filename, caption, event_type, source,
         json.dumps(detail) if detail else None,
         estimated_score, actual_score, score_error, hand_type, chips_before, chips_after),
    )
    conn.commit()
    conn.close()


def add_round(db_id: int, ante: int, blind_type: str, target_score: int,
              best_hand_score: int = 0, hands_played: int = 0,
              discards_used: int = 0, money_after: int = 0, boss_name: str = None):
    """Record a round result."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO balatro_rounds (run_id, ante, blind_type, boss_name, target_score,
           best_hand_score, hands_played, discards_used, money_after)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (db_id, ante, blind_type, boss_name, target_score,
         best_hand_score, hands_played, discards_used, money_after),
    )
    conn.commit()
    conn.close()


def add_jokers(db_id: int, jokers: list[str]):
    """Record final joker lineup."""
    conn = _get_conn()
    cur = conn.cursor()
    for i, name in enumerate(jokers, 1):
        cur.execute(
            "INSERT INTO balatro_jokers (run_id, name, position) VALUES (%s, %s, %s)",
            (db_id, name, i),
        )
    conn.commit()
    conn.close()


def finalize_run(db_id: int, stats: dict, llm_stats: dict, report_text: str, strategy: str):
    """Write final stats when game ends."""
    llm_total_ms = llm_stats.get("total_ms", 0)
    input_tok = llm_stats.get("input_tokens", 0)
    output_tok = llm_stats.get("output_tokens", 0)
    cost = input_tok / 1_000_000 * 0.15 + output_tok / 1_000_000 * 0.60

    start = datetime.fromisoformat(stats["start_time"])
    end = datetime.fromisoformat(stats["end_time"])
    duration = int((end - start).total_seconds())

    # Determine status: completed if won (ante>=8) or passed stop_after_ante target
    stop_ante = stats.get("stop_after_ante", 0)
    max_ante = stats.get("max_ante", 0)
    won = max_ante >= 8
    completed = won or (stop_ante > 0 and max_ante >= stop_ante)

    update_run(
        db_id,
        status="completed" if completed else "failed",
        final_ante=stats.get("max_ante", 1),
        final_score=stats.get("final_score", 0),
        won=stats.get("max_ante", 0) >= 8,
        hands_played=stats.get("hands", 0),
        discards_used=stats.get("discards", 0),
        purchases=stats.get("purchases", 0),
        rule_decisions=stats.get("rule_decisions", 0),
        llm_decisions=stats.get("llm_decisions", 0),
        llm_calls=llm_stats.get("calls", 0),
        llm_failures=llm_stats.get("failures", 0),
        llm_tokens_in=input_tok,
        llm_tokens_out=output_tok,
        llm_cost_usd=round(cost, 6),
        llm_total_ms=round(llm_total_ms, 2),
        duration_seconds=duration,
        strategy=strategy,
        report_text=report_text,
        ended_at=end.isoformat(),
    )

    # Save jokers
    jokers = stats.get("jokers_at_end", [])
    if jokers:
        add_jokers(db_id, jokers)


def register_strategy(name: str, code_hash: str, model: str, params: dict = None,
                      description: str = None, source_code: str = None,
                      summary: str = None) -> int:
    """Register or get existing strategy. Auto-links parent (most recent different hash)."""
    conn = _get_conn()
    cur = conn.cursor()
    # Try to find existing (code_hash now includes params+model, so it's the sole key)
    cur.execute(
        "SELECT id FROM balatro_strategies WHERE code_hash = %s",
        (code_hash,)
    )
    row = cur.fetchone()
    if row:
        # Update source_code if provided and not yet stored
        if source_code:
            cur.execute("UPDATE balatro_strategies SET source_code = %s WHERE id = %s AND source_code IS NULL",
                        (source_code, row[0]))
            conn.commit()
        conn.close()
        return row[0]

    # Find parent: most recent strategy with same model but different hash
    cur.execute(
        "SELECT id FROM balatro_strategies WHERE model = %s AND code_hash != %s ORDER BY created_at DESC LIMIT 1",
        (model, code_hash)
    )
    parent_row = cur.fetchone()
    parent_id = parent_row[0] if parent_row else None

    # Insert new
    cur.execute(
        """INSERT INTO balatro_strategies (name, code_hash, model, params, description, source_code, summary, parent_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (name, code_hash, model, json.dumps(params) if params else None,
         description, source_code, summary, parent_id)
    )
    sid = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return sid


def link_run_strategy(run_id: int, strategy_id: int):
    """Link a run to a strategy."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE balatro_runs SET strategy_id = %s WHERE id = %s", (strategy_id, run_id))
    conn.commit()
    conn.close()


def add_game_log(run_id: int, seq: int, phase: str, ante: int, blind: str,
                 hand_cards: str, jokers: str, consumables: str,
                 dollars: int, hands_left: int, discards_left: int,
                 chips: int, target: int,
                 action: str, decision_type: str = None, reasoning: str = None,
                 hand_type: str = None, estimated_score: int = None, actual_score: int = None,
                 boss_blind: str = None):
    """Add a game log entry (one step in the text replay)."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO balatro_game_log
        (run_id, seq, phase, ante, blind, hand_cards, jokers, consumables,
         dollars, hands_left, discards_left, chips, target,
         action, decision_type, reasoning, hand_type, estimated_score, actual_score,
         boss_blind)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (run_id, seq, phase, ante, blind, hand_cards, jokers, consumables,
          dollars, hands_left, discards_left, chips, target,
          action, decision_type, reasoning, hand_type, estimated_score, actual_score,
          boss_blind))
    conn.commit()
    conn.close()
