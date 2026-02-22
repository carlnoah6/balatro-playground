"""Batch evaluation metrics for Balatro strategy comparison.

Primary metric: Weighted Score (2^(ante-1)) — respects exponential difficulty curve.
Secondary: Scorecard with Floor/Ceiling/Consistency/Breakthrough dimensions.

Usage:
    python3 batch_metrics.py <batch_id>              # Single batch report
    python3 batch_metrics.py <batch_a> <batch_b>     # Compare two batches
    python3 batch_metrics.py --recent 5               # Last 5 batches
"""

import sys
import os
import psycopg2

def get_conn():
    with open('/home/ubuntu/.openclaw/workspace/.env') as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                os.environ[k] = v
    return psycopg2.connect(os.environ['DATABASE_URL'])


def weighted_score(ante: int) -> float:
    """Exponential weight: A1=1, A2=2, A3=4, A4=8, A5=16, A6=32, A7=64, A8=128."""
    return 2 ** (ante - 1)


def calc_metrics(conn, batch_id: int) -> dict:
    """Calculate all metrics for a batch."""
    cur = conn.cursor()
    cur.execute('SELECT final_ante FROM balatro_runs WHERE batch_run_id = %s AND final_ante IS NOT NULL ORDER BY final_ante', (batch_id,))
    antes = [r[0] for r in cur.fetchall()]

    if not antes:
        return {"batch_id": batch_id, "seeds": 0, "error": "no completed runs"}

    n = len(antes)
    ws = [weighted_score(a) for a in antes]

    return {
        "batch_id": batch_id,
        "seeds": n,
        # Primary metric
        "weighted_score": sum(ws) / n,
        # Scorecard
        "avg_ante": sum(antes) / n,
        "median_ante": sorted(antes)[n // 2],
        "max_ante": max(antes),
        "min_ante": min(antes),
        # Floor (survival)
        "floor_a1_pct": sum(1 for a in antes if a == 1) / n * 100,
        # Consistency
        "ge_a3_pct": sum(1 for a in antes if a >= 3) / n * 100,
        "ge_a4_pct": sum(1 for a in antes if a >= 4) / n * 100,
        # Breakthrough
        "ge_a5_pct": sum(1 for a in antes if a >= 5) / n * 100,
        "ge_a6_pct": sum(1 for a in antes if a >= 6) / n * 100,
        "ge_a8_pct": sum(1 for a in antes if a >= 8) / n * 100,
        # Distribution
        "ante_dist": {a: antes.count(a) for a in sorted(set(antes))},
    }


def format_metrics(m: dict) -> str:
    """Format metrics as a readable report."""
    if "error" in m:
        return f"Batch {m['batch_id']}: {m['error']}"

    lines = [
        f"Batch {m['batch_id']} ({m['seeds']} seeds)",
        f"  Weighted Score: {m['weighted_score']:.2f}",
        f"  Avg Ante: {m['avg_ante']:.2f} | Median: {m['median_ante']} | Max: {m['max_ante']}",
        f"  Floor (A1 death): {m['floor_a1_pct']:.0f}%",
        f"  Consistency (≥A3): {m['ge_a3_pct']:.0f}% | (≥A4): {m['ge_a4_pct']:.0f}%",
        f"  Breakthrough (≥A5): {m['ge_a5_pct']:.0f}% | (≥A6): {m['ge_a6_pct']:.0f}%",
        f"  Distribution: {' '.join(f'A{a}={c}' for a, c in m['ante_dist'].items())}",
    ]
    return "\n".join(lines)


def format_comparison(ma: dict, mb: dict) -> str:
    """Format side-by-side comparison."""
    def arrow(va, vb, higher_better=True):
        if va == vb: return "="
        if higher_better:
            return "📈" if vb > va else "📉"
        else:
            return "📈" if vb < va else "📉"

    lines = [
        f"{'Metric':<25} {'B' + str(ma['batch_id']):>10} {'B' + str(mb['batch_id']):>10} {'':>3}",
        f"{'-'*25} {'-'*10} {'-'*10} {'-'*3}",
        f"{'Weighted Score':<25} {ma['weighted_score']:>10.2f} {mb['weighted_score']:>10.2f} {arrow(ma['weighted_score'], mb['weighted_score'])}",
        f"{'Avg Ante':<25} {ma['avg_ante']:>10.2f} {mb['avg_ante']:>10.2f} {arrow(ma['avg_ante'], mb['avg_ante'])}",
        f"{'Median Ante':<25} {ma['median_ante']:>10} {mb['median_ante']:>10} {arrow(ma['median_ante'], mb['median_ante'])}",
        f"{'Max Ante':<25} {ma['max_ante']:>10} {mb['max_ante']:>10} {arrow(ma['max_ante'], mb['max_ante'])}",
        f"{'Floor (A1 death %)':<25} {ma['floor_a1_pct']:>9.0f}% {mb['floor_a1_pct']:>9.0f}% {arrow(ma['floor_a1_pct'], mb['floor_a1_pct'], False)}",
        f"{'Consistency (≥A3 %)':<25} {ma['ge_a3_pct']:>9.0f}% {mb['ge_a3_pct']:>9.0f}% {arrow(ma['ge_a3_pct'], mb['ge_a3_pct'])}",
        f"{'Consistency (≥A4 %)':<25} {ma['ge_a4_pct']:>9.0f}% {mb['ge_a4_pct']:>9.0f}% {arrow(ma['ge_a4_pct'], mb['ge_a4_pct'])}",
        f"{'Breakthrough (≥A5 %)':<25} {ma['ge_a5_pct']:>9.0f}% {mb['ge_a5_pct']:>9.0f}% {arrow(ma['ge_a5_pct'], mb['ge_a5_pct'])}",
        f"{'Breakthrough (≥A6 %)':<25} {ma['ge_a6_pct']:>9.0f}% {mb['ge_a6_pct']:>9.0f}% {arrow(ma['ge_a6_pct'], mb['ge_a6_pct'])}",
    ]

    # Per-seed comparison if same seeds
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT seed, final_ante FROM balatro_runs WHERE batch_run_id = %s ORDER BY seed', (ma['batch_id'],))
    sa = {r[0]: r[1] for r in cur.fetchall()}
    cur.execute('SELECT seed, final_ante FROM balatro_runs WHERE batch_run_id = %s ORDER BY seed', (mb['batch_id'],))
    sb = {r[0]: r[1] for r in cur.fetchall()}

    common = set(sa.keys()) & set(sb.keys())
    if common:
        improved = sum(1 for s in common if sb[s] > sa[s])
        same = sum(1 for s in common if sb[s] == sa[s])
        regressed = sum(1 for s in common if sb[s] < sa[s])
        lines.append(f"\nSame-seed comparison ({len(common)} seeds):")
        lines.append(f"  📈 Improved: {improved} | ➡️ Same: {same} | 📉 Regressed: {regressed}")

        # Show per-seed
        for seed in sorted(common):
            a, b = sa[seed], sb[seed]
            mark = "📈" if b > a else ("📉" if b < a else "➡️")
            ws_a, ws_b = weighted_score(a), weighted_score(b)
            lines.append(f"  {mark} {seed}: A{a}({ws_a:.0f}) → A{b}({ws_b:.0f})")

    return "\n".join(lines)


if __name__ == "__main__":
    conn = get_conn()

    if len(sys.argv) == 2 and sys.argv[1].startswith("--recent"):
        n = int(sys.argv[1].split("=")[1]) if "=" in sys.argv[1] else 5
        cur = conn.cursor()
        cur.execute('SELECT id FROM balatro_batch_runs ORDER BY id DESC LIMIT %s', (n,))
        for (bid,) in reversed(cur.fetchall()):
            print(format_metrics(calc_metrics(conn, bid)))
            print()
    elif len(sys.argv) == 2:
        print(format_metrics(calc_metrics(conn, int(sys.argv[1]))))
    elif len(sys.argv) == 3:
        ma = calc_metrics(conn, int(sys.argv[1]))
        mb = calc_metrics(conn, int(sys.argv[2]))
        print(format_metrics(ma))
        print()
        print(format_metrics(mb))
        print()
        print(format_comparison(ma, mb))
    else:
        print(__doc__)
