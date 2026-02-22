"""Balatro Playground 🃏 - FastAPI backend."""

import json
import os
import uuid
from pathlib import Path

import asyncpg
import aiofiles
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, HTMLResponse
from contextlib import asynccontextmanager

# Config
NEON_CONFIG = Path(__file__).parent.parent.parent.parent / "data" / "neon-config.json"
SCREENSHOT_DIR = Path(os.environ.get("SCREENSHOT_DIR", "/home/ubuntu/balatro-screenshots"))
JOKER_DATA = Path(__file__).parent.parent / "data" / "jokers.json"
VOUCHER_DATA = Path(__file__).parent.parent / "data" / "vouchers.json"
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

_joker_catalog: list[dict] | None = None
_voucher_catalog: list[dict] | None = None


def _load_joker_catalog() -> list[dict]:
    global _joker_catalog
    if _joker_catalog is None:
        try:
            with open(JOKER_DATA) as f:
                _joker_catalog = json.load(f)
        except FileNotFoundError:
            _joker_catalog = []
    return _joker_catalog


def _load_voucher_catalog() -> list[dict]:
    global _voucher_catalog
    if _voucher_catalog is None:
        try:
            with open(VOUCHER_DATA) as f:
                _voucher_catalog = json.load(f)
        except FileNotFoundError:
            _voucher_catalog = []
    return _voucher_catalog


def _build_card_catalog_map() -> dict:
    """Build a combined lookup map for jokers + vouchers by lowercase name."""
    m = {}
    for j in _load_joker_catalog():
        m[j["name_en"].lower()] = j
    for v in _load_voucher_catalog():
        m[v["name_en"].lower()] = v
    return m

db_pool: asyncpg.Pool | None = None


def get_database_url() -> str:
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    with open(NEON_CONFIG) as f:
        return json.load(f)["database_url"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    db_pool = await asyncpg.create_pool(get_database_url(), min_size=2, max_size=10,
                                         statement_cache_size=0)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    yield
    if db_pool:
        await db_pool.close()


app = FastAPI(title="Balatro Playground 🃏", lifespan=lifespan)

# Serve screenshots as static files
app.mount("/screenshots", StaticFiles(directory=str(SCREENSHOT_DIR)), name="screenshots")


# ── Runs ──────────────────────────────────────────────────────────────

@app.get("/api/runs")
async def list_runs(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    deck: str | None = None,
    stake: str | None = None,
    won: bool | None = None,
    sort: str = Query("played_at", pattern="^(played_at|final_ante|final_score|created_at)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
):
    """List runs with pagination and filters."""
    conditions = []
    params = []
    idx = 1

    if deck:
        conditions.append(f"deck = ${idx}")
        params.append(deck)
        idx += 1
    if stake:
        conditions.append(f"stake = ${idx}")
        params.append(stake)
        idx += 1
    if won is not None:
        conditions.append(f"won = ${idx}")
        params.append(won)
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    # Count
    count_row = await db_pool.fetchrow(f"SELECT COUNT(*) FROM balatro_runs {where}", *params)
    total = count_row["count"]

    # Fetch
    offset = (page - 1) * per_page
    rows = await db_pool.fetch(
        f"""SELECT r.*, 
                   s.name AS strategy_name, s.id AS strategy_sid,
                   (SELECT COUNT(*) FROM balatro_screenshots sc WHERE sc.run_id = r.id) AS screenshot_count
            FROM balatro_runs r
            LEFT JOIN balatro_strategies s ON r.strategy_id = s.id
            {where}
            ORDER BY {sort} {order}
            LIMIT ${idx} OFFSET ${idx + 1}""",
        *params, per_page, offset,
    )

    return {
        "runs": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if total else 0,
    }


@app.get("/api/runs/by-code/{run_code}")
async def get_run_by_code(run_code: str):
    """Lookup a run by run_code and return full detail."""
    run = await db_pool.fetchrow("SELECT id FROM balatro_runs WHERE run_code = $1", run_code)
    if not run:
        raise HTTPException(404, "Run not found")
    return await get_run(run["id"])


@app.get("/api/runs/{run_id}")
async def get_run(run_id: int):
    """Get full run detail with jokers, rounds, screenshots, tags."""
    run = await db_pool.fetchrow("SELECT * FROM balatro_runs WHERE id = $1", run_id)
    if not run:
        raise HTTPException(404, "Run not found")

    jokers = await db_pool.fetch(
        "SELECT * FROM balatro_jokers WHERE run_id = $1 ORDER BY position", run_id
    )
    rounds = await db_pool.fetch(
        "SELECT * FROM balatro_rounds WHERE run_id = $1 ORDER BY ante, blind_type", run_id
    )
    screenshots = await db_pool.fetch(
        "SELECT * FROM balatro_screenshots WHERE run_id = $1 ORDER BY created_at", run_id
    )
    tags = await db_pool.fetch(
        "SELECT * FROM balatro_tags WHERE run_id = $1 ORDER BY ante", run_id
    )

    # Strategy info
    strategy = None
    if run.get("strategy_id"):
        srow = await db_pool.fetchrow("SELECT * FROM balatro_strategies WHERE id = $1", run["strategy_id"])
        if srow:
            strategy = dict(srow)

    return {
        "run": dict(run),
        "jokers": [dict(j) for j in jokers],
        "rounds": [dict(r) for r in rounds],
        "screenshots": [dict(s) for s in screenshots],
        "tags": [dict(t) for t in tags],
        "strategy": strategy,
    }


@app.post("/api/runs")
async def create_run(
    seed: str | None = Form(None),
    deck: str = Form("Red Deck"),
    stake: str = Form("White"),
    final_ante: int = Form(1),
    final_score: int | None = Form(None),
    won: bool = Form(False),
    endless_ante: int | None = Form(None),
    notes: str | None = Form(None),
    played_at: str | None = Form(None),
):
    """Create a new run."""
    row = await db_pool.fetchrow(
        """INSERT INTO balatro_runs (seed, deck, stake, final_ante, final_score, won, endless_ante, notes, played_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, COALESCE($9::timestamptz, NOW()))
           RETURNING *""",
        seed, deck, stake, final_ante, final_score, won, endless_ante, notes, played_at,
    )
    return {"run": dict(row)}


@app.put("/api/runs/{run_id}")
async def update_run(run_id: int):
    """Update a run (accepts JSON body)."""
    # We'll handle this via JSON since it's easier for updates
    raise HTTPException(501, "Use PATCH endpoint")


@app.patch("/api/runs/{run_id}")
async def patch_run(run_id: int, body: dict):
    """Patch run fields."""
    allowed = {"seed", "deck", "stake", "final_ante", "final_score", "won", "endless_ante", "notes", "played_at"}
    fields = {k: v for k, v in body.items() if k in allowed}
    if not fields:
        raise HTTPException(400, "No valid fields to update")

    sets = []
    params = []
    for i, (k, v) in enumerate(fields.items(), 1):
        sets.append(f"{k} = ${i}")
        params.append(v)
    params.append(run_id)

    row = await db_pool.fetchrow(
        f"UPDATE balatro_runs SET {', '.join(sets)} WHERE id = ${len(params)} RETURNING *",
        *params,
    )
    if not row:
        raise HTTPException(404, "Run not found")
    return {"run": dict(row)}


@app.delete("/api/runs/{run_id}")
async def delete_run(run_id: int):
    """Delete a run and its screenshots from disk."""
    run = await db_pool.fetchrow("SELECT id FROM balatro_runs WHERE id = $1", run_id)
    if not run:
        raise HTTPException(404, "Run not found")

    # Delete screenshot files
    screenshots = await db_pool.fetch(
        "SELECT filename FROM balatro_screenshots WHERE run_id = $1", run_id
    )
    for s in screenshots:
        fpath = SCREENSHOT_DIR / s["filename"]
        if fpath.exists():
            fpath.unlink()

    # Cascade delete handles DB rows
    await db_pool.execute("DELETE FROM balatro_runs WHERE id = $1", run_id)

    # Clean up empty run directory
    run_dir = SCREENSHOT_DIR / str(run_id)
    if run_dir.exists() and not any(run_dir.iterdir()):
        run_dir.rmdir()

    return {"deleted": True}


# ── Jokers ────────────────────────────────────────────────────────────

@app.post("/api/runs/{run_id}/jokers")
async def add_joker(
    run_id: int,
    name: str = Form(...),
    position: int = Form(...),
    edition: str | None = Form(None),
    eternal: bool = Form(False),
    perishable: bool = Form(False),
    rental: bool = Form(False),
):
    """Add a joker to a run."""
    row = await db_pool.fetchrow(
        """INSERT INTO balatro_jokers (run_id, name, position, edition, eternal, perishable, rental)
           VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *""",
        run_id, name, position, edition, eternal, perishable, rental,
    )
    # Update joker count
    await db_pool.execute(
        "UPDATE balatro_runs SET joker_count = (SELECT COUNT(*) FROM balatro_jokers WHERE run_id = $1) WHERE id = $1",
        run_id,
    )
    return {"joker": dict(row)}


@app.post("/api/runs/{run_id}/jokers/batch")
async def add_jokers_batch(run_id: int, jokers: list[dict]):
    """Add multiple jokers at once."""
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            results = []
            for j in jokers:
                row = await conn.fetchrow(
                    """INSERT INTO balatro_jokers (run_id, name, position, edition, eternal, perishable, rental)
                       VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *""",
                    run_id, j["name"], j["position"], j.get("edition"),
                    j.get("eternal", False), j.get("perishable", False), j.get("rental", False),
                )
                results.append(dict(row))
            await conn.execute(
                "UPDATE balatro_runs SET joker_count = (SELECT COUNT(*) FROM balatro_jokers WHERE run_id = $1) WHERE id = $1",
                run_id,
            )
    return {"jokers": results}


# ── Rounds ────────────────────────────────────────────────────────────

async def _sync_final_score(conn, run_id: int):
    """Update run's final_score to the max best_hand_score across all rounds."""
    await conn.execute(
        """UPDATE balatro_runs
           SET final_score = (SELECT MAX(best_hand_score) FROM balatro_rounds WHERE run_id = $1)
           WHERE id = $1""",
        run_id,
    )

@app.post("/api/runs/{run_id}/rounds")
async def add_round(
    run_id: int,
    ante: int = Form(...),
    blind_type: str = Form(...),
    boss_name: str | None = Form(None),
    target_score: int | None = Form(None),
    best_hand_score: int | None = Form(None),
    hands_played: int | None = Form(None),
    discards_used: int | None = Form(None),
    skipped: bool = Form(False),
    money_after: int | None = Form(None),
):
    """Add a round result."""
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """INSERT INTO balatro_rounds 
                   (run_id, ante, blind_type, boss_name, target_score, best_hand_score, hands_played, discards_used, skipped, money_after)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) RETURNING *""",
                run_id, ante, blind_type, boss_name, target_score, best_hand_score,
                hands_played, discards_used, skipped, money_after,
            )
            await _sync_final_score(conn, run_id)
    return {"round": dict(row)}


@app.post("/api/runs/{run_id}/rounds/batch")
async def add_rounds_batch(run_id: int, rounds: list[dict]):
    """Add multiple rounds at once."""
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            results = []
            for r in rounds:
                row = await conn.fetchrow(
                    """INSERT INTO balatro_rounds 
                       (run_id, ante, blind_type, boss_name, target_score, best_hand_score, hands_played, discards_used, skipped, money_after)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) RETURNING *""",
                    run_id, r["ante"], r["blind_type"], r.get("boss_name"),
                    r.get("target_score"), r.get("best_hand_score"),
                    r.get("hands_played"), r.get("discards_used"),
                    r.get("skipped", False), r.get("money_after"),
                )
                results.append(dict(row))
            await _sync_final_score(conn, run_id)
    return {"rounds": results}


# ── Tags ──────────────────────────────────────────────────────────────

@app.post("/api/runs/{run_id}/tags")
async def add_tag(run_id: int, ante: int = Form(...), name: str = Form(...)):
    """Add a tag."""
    row = await db_pool.fetchrow(
        "INSERT INTO balatro_tags (run_id, ante, name) VALUES ($1, $2, $3) RETURNING *",
        run_id, ante, name,
    )
    return {"tag": dict(row)}


# ── Screenshots ───────────────────────────────────────────────────────

@app.post("/api/runs/{run_id}/screenshots")
async def upload_screenshot(
    run_id: int,
    file: UploadFile = File(...),
    round_id: int | None = Form(None),
    caption: str | None = Form(None),
):
    """Upload a screenshot for a run."""
    # Validate run exists
    run = await db_pool.fetchrow("SELECT id FROM balatro_runs WHERE id = $1", run_id)
    if not run:
        raise HTTPException(404, "Run not found")

    # Validate extension
    ext = Path(file.filename).suffix.lower() if file.filename else ".png"
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"File type {ext} not allowed. Use: {ALLOWED_EXTENSIONS}")

    # Read and validate size
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(400, f"File too large. Max {MAX_UPLOAD_SIZE // 1024 // 1024}MB")

    # Save to disk
    run_dir = SCREENSHOT_DIR / str(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{run_id}/{uuid.uuid4().hex}{ext}"
    filepath = SCREENSHOT_DIR / filename

    async with aiofiles.open(filepath, "wb") as f:
        await f.write(content)

    # Try to get image dimensions
    width, height = None, None
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(content))
        width, height = img.size
    except Exception:
        pass

    # Save to DB
    row = await db_pool.fetchrow(
        """INSERT INTO balatro_screenshots (run_id, round_id, filename, original_name, caption, file_size, width, height)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING *""",
        run_id, round_id, filename, file.filename, caption, len(content), width, height,
    )
    return {"screenshot": dict(row)}


@app.delete("/api/screenshots/{screenshot_id}")
async def delete_screenshot(screenshot_id: int):
    """Delete a screenshot."""
    row = await db_pool.fetchrow(
        "SELECT * FROM balatro_screenshots WHERE id = $1", screenshot_id
    )
    if not row:
        raise HTTPException(404, "Screenshot not found")

    # Delete file
    fpath = SCREENSHOT_DIR / row["filename"]
    if fpath.exists():
        fpath.unlink()

    await db_pool.execute("DELETE FROM balatro_screenshots WHERE id = $1", screenshot_id)
    return {"deleted": True}


# ── Stats ─────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def get_stats():
    """Overall stats summary."""
    stats = await db_pool.fetchrow("""
        SELECT 
            COUNT(*) AS total_runs,
            COUNT(*) FILTER (WHERE won) AS wins,
            COUNT(*) FILTER (WHERE NOT won) AS losses,
            MAX(final_ante) AS highest_ante,
            MAX(final_score) AS highest_score,
            COUNT(DISTINCT deck) AS decks_used,
            COUNT(DISTINCT stake) AS stakes_played
        FROM balatro_runs
    """)
    return {"stats": dict(stats)}


# ── Joker Catalog ─────────────────────────────────────────────────────

@app.get("/api/jokers/catalog")
async def joker_catalog():
    """Return the full joker catalog with images and descriptions."""
    return {"jokers": _load_joker_catalog()}


@app.get("/api/jokers/lookup/{name}")
async def joker_lookup(name: str):
    """Lookup a joker by English name (case-insensitive)."""
    catalog = _load_joker_catalog()
    name_lower = name.lower().strip()
    for j in catalog:
        if j["name_en"].lower() == name_lower:
            return j
    raise HTTPException(404, f"Joker '{name}' not found in catalog")


# ── Health ────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    """Health check."""
    try:
        await db_pool.fetchval("SELECT 1")
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        return JSONResponse({"status": "error", "db": str(e)}, status_code=503)


# ── Server-rendered HTML pages ────────────────────────────────────────

STATIC_DIR = Path(__file__).parent.parent / "static"

def _base_css():
    """Shared CSS for all pages."""
    return """
:root{--bg:#1a1a2e;--surface:#16213e;--card:#0f3460;--accent:#e94560;--gold:#f5c518;--text:#eee;--muted:#aaa;--win:#4ade80;--loss:#f87171}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
a{color:var(--gold);text-decoration:none}a:hover{text-decoration:underline}
.container{max-width:1400px;margin:0 auto;padding:1rem}
header{background:var(--surface);padding:1rem 0;border-bottom:2px solid var(--accent);margin-bottom:1.5rem}
header .container{display:flex;align-items:center;justify-content:space-between}
header h1{font-size:1.5rem}header h1 span{color:var(--accent)}
.run-table{width:100%;border-collapse:collapse}
.run-table th{text-align:left;padding:.5rem .75rem;color:var(--muted);font-size:.8rem;text-transform:uppercase;border-bottom:1px solid #333}
.run-table td{padding:.6rem .75rem;border-bottom:1px solid #222}
.run-table tbody tr:hover{background:var(--surface);cursor:pointer}
.run-code{color:var(--gold);font-family:monospace;font-weight:bold}
.badge{display:inline-block;padding:.15rem .5rem;border-radius:4px;font-size:.75rem;font-weight:600}
.badge.win{background:#166534;color:var(--win)}.badge.loss{background:#7f1d1d;color:var(--loss)}
.badge.running{background:#1e3a5f;color:#60a5fa;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
.back-btn{display:inline-block;margin-bottom:1rem;padding:.4rem .8rem;background:var(--surface);border:1px solid #333;border-radius:6px;color:var(--text);font-size:.85rem}
.detail-header{background:var(--surface);padding:1.25rem;border-radius:12px;margin-bottom:1.5rem}
.detail-header h2{margin-bottom:.5rem;font-size:1.4rem}
.detail-stats{display:flex;gap:1rem;flex-wrap:wrap;margin-top:.75rem}
.detail-stats .stat{background:var(--card);padding:.5rem .75rem;border-radius:8px;text-align:center;min-width:80px}
.detail-stats .stat .val{font-size:1.2rem;font-weight:bold;color:var(--gold)}
.detail-stats .stat .lbl{font-size:.7rem;color:var(--muted)}
.joker-grid{display:flex;gap:1.25rem;flex-wrap:wrap;margin-bottom:1.5rem}
.joker-card{display:flex;gap:1rem;background:var(--surface);padding:1rem;border-radius:12px;min-width:320px;max-width:480px;flex:1}
.joker-card img{width:96px;height:96px;object-fit:contain;flex-shrink:0}
.joker-card .joker-info{flex:1}
.joker-card .name-en{font-size:1.1rem;font-weight:600}.joker-card .name-zh{font-size:1rem;color:var(--gold);margin-top:3px}
.joker-card .effect{font-size:.9rem;color:var(--muted);margin-top:6px;line-height:1.4}
.feed{display:flex;flex-direction:column;gap:1.5rem}
.feed-entry{background:var(--surface);border-radius:12px;overflow:hidden}
.feed-entry .caption{padding:.75rem 1.25rem;color:#fff;font-size:1.25rem;line-height:1.6;font-weight:500}
.feed-entry .caption .source-tag{font-size:.85rem;padding:.2rem .5rem;border-radius:4px;font-weight:600;margin-left:.5rem;vertical-align:middle}
.feed-entry .caption .source-tag.rule{background:#1e3a5f;color:#60a5fa}
.feed-entry .caption .source-tag.llm{background:#3b1f5e;color:#c084fc}
.feed-entry img.screenshot{width:100%;display:block}
.score-bar{display:flex;align-items:center;gap:.75rem;padding:.4rem 1.25rem .6rem;font-size:1rem;font-family:monospace}
.score-est{color:var(--muted)}.score-arrow{color:#555}.score-act{color:var(--text);font-weight:600}
.score-err{padding:.15rem .4rem;border-radius:4px;font-size:.85rem;font-weight:600}
.score-err.good{background:#166534;color:var(--win)}.score-err.ok{background:#854d0e;color:#fbbf24}.score-err.bad{background:#7f1d1d;color:var(--loss)}
.section{margin-bottom:1.5rem}.section h3{margin-bottom:.75rem;font-size:1.1rem}
.blind-divider{padding:.75rem 1rem;font-size:1.1rem;font-weight:700;color:var(--gold);border-bottom:1px solid #333}
.detail-layout{display:flex;gap:1.5rem;align-items:flex-start}
.detail-main{flex:1;min-width:0}
.toc{position:sticky;top:1rem;width:200px;flex-shrink:0;background:var(--surface);border-radius:12px;padding:.75rem;max-height:calc(100vh - 2rem);overflow-y:auto}
.toc-title{font-size:.85rem;font-weight:600;color:var(--muted);text-transform:uppercase;margin-bottom:.5rem;padding-bottom:.5rem;border-bottom:1px solid #333}
.toc-ante{font-size:.95rem;font-weight:700;color:var(--gold);padding:.5rem .5rem;margin-top:.75rem;cursor:pointer;border-radius:4px;transition:background .15s}
.toc-ante:first-child{margin-top:0}
.toc-ante:hover{background:var(--card)}
.toc-blind{font-size:.85rem;color:var(--muted);padding:.3rem .5rem .3rem 1.25rem;cursor:pointer;border-radius:4px;transition:all .15s}
.toc-blind:hover{color:var(--text);background:rgba(255,255,255,.05)}
.toc-ante.active,.toc-blind.active{color:#fff;background:var(--card);font-weight:700}
.toc-blind.active::before{content:'▸ ';color:var(--gold)}
@media(max-width:768px){.detail-layout{flex-direction:column}.toc{display:none}}
.tab-bar{display:flex;gap:0;margin-bottom:1.5rem;border-bottom:2px solid #333}
.tab-btn{padding:.6rem 1.2rem;background:none;border:none;color:var(--muted);font-size:.95rem;cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-2px;transition:all .15s}
.tab-btn:hover{color:var(--text)}
.tab-btn.active{color:var(--gold);border-bottom-color:var(--gold);font-weight:600}
.lightbox{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.92);z-index:100;justify-content:center;align-items:center}
.lightbox.active{display:flex}.lightbox img{max-width:95%;max-height:95%;object-fit:contain}
.lightbox .close{position:absolute;top:1rem;right:1.5rem;font-size:2rem;color:#fff;cursor:pointer}
.run-table.sortable th{cursor:pointer;user-select:none;position:relative}
.run-table.sortable th:hover{color:var(--text)}
.run-table.sortable th.sort-asc::after{content:' ▲';font-size:.65rem}
.run-table.sortable th.sort-desc::after{content:' ▼';font-size:.65rem}
th[data-tooltip]{position:relative}
th[data-tooltip]:hover::after{content:attr(data-tooltip);position:absolute;bottom:100%;left:50%;transform:translateX(-50%);background:#333;color:#fff;padding:4px 8px;border-radius:4px;font-size:.75rem;white-space:nowrap;z-index:10;font-weight:normal;text-transform:none}
.joker-chip{display:inline-flex;align-items:center;background:var(--surface);padding:2px 8px;border-radius:4px;font-size:.85rem;margin:2px;cursor:default}
.joker-chip:hover{background:var(--card)}
"""


def _header():
    return '<header><div class="container" style="display:flex;align-items:center;justify-content:space-between"><h1><a href="/balatro/" style="color:inherit;text-decoration:none">🃏 <span>Balatro</span> Playground</a></h1><nav style="display:flex;gap:1.5rem"><a href="/balatro/validation" style="color:var(--muted);text-decoration:none;font-size:.9rem">🔬 验证</a></nav></div></header>'


def _game_log_css():
    return """
.ante-block{margin-bottom:2rem}
.ante-header{font-size:1.2rem;font-weight:700;color:var(--gold);padding:.75rem 0;text-align:center;border-bottom:2px solid var(--gold);margin-bottom:1rem}
.blind-header{font-size:1rem;font-weight:600;color:var(--accent);padding:.5rem .75rem;background:rgba(233,69,96,.1);border-radius:8px;margin:.75rem 0 .5rem}
.log-entry{background:var(--surface);border-radius:8px;padding:.75rem 1rem;margin-bottom:.5rem;border-left:3px solid #333}
.log-entry.shop{border-left-color:#a78bfa}
.log-entry.blind-select{border-left-color:var(--gold)}
.log-entry.cashout{border-left-color:var(--win)}
.log-entry.game-over{border-left-color:var(--accent);background:rgba(233,69,96,.1)}
.log-state{font-size:.8rem;color:var(--muted);margin-bottom:.25rem;font-family:monospace}
.log-hand{font-size:.9rem;color:#ccc;margin-bottom:.25rem;font-family:monospace;word-break:break-all}
.log-action{font-size:.95rem;font-weight:500}
.log-reason{font-size:.8rem;color:var(--muted);margin-top:.25rem;font-style:italic}
.log-score{font-size:.85rem;font-family:monospace;margin-top:.25rem}
.log-score .hand-type{color:var(--gold);font-weight:600}
.log-score .est{color:var(--muted)}
.log-score .act{font-weight:600}
.log-score .act.good{color:var(--win)}
.log-score .act.ok{color:#fbbf24}
.log-score .act.bad{color:var(--loss)}
.log-jokers{font-size:.8rem;color:#8b9dc3;margin:.25rem 0;padding:.3rem .5rem;background:rgba(255,255,255,.03);border-radius:4px;font-family:monospace;word-break:break-all}
.dt-tag{display:inline-block;padding:.1rem .4rem;border-radius:3px;font-size:.75rem;font-weight:600;margin-right:.25rem;vertical-align:middle}
.dt-tag.rule{background:#1e3a5f;color:#60a5fa}
.dt-tag.llm{background:#3b1f5e;color:#c084fc}
"""


def _lightbox_html():
    return """<div class="lightbox" id="lb" onclick="this.classList.remove('active')"><span class="close">&times;</span><img id="lbi" src="" alt=""></div>
<script>function openLb(src){document.getElementById('lbi').src=src;document.getElementById('lb').classList.add('active')}
document.addEventListener('keydown',function(e){if(e.key==='Escape')document.getElementById('lb').classList.remove('active')})</script>"""


def _html_escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _joker_card_html(name: str, catalog_map: dict = None, compact: bool = False) -> str:
    """Render a joker card with image, name, and description.
    compact=True renders a small inline version."""
    cj = (catalog_map or {}).get(name.lower(), {})
    img = f'/balatro/joker-images/{cj["image"]}' if cj.get("image") else ""
    name_zh = cj.get("name_zh", "")
    effect = cj.get("effect", "")
    if compact:
        if img:
            return f'<span class="joker-chip" title="{_html_escape(effect)}"><img src="{img}" style="width:20px;height:20px;vertical-align:middle;margin-right:3px">{_html_escape(name)}</span>'
        return f'<span class="joker-chip" title="{_html_escape(effect)}">{_html_escape(name)}</span>'
    h = '<div class="joker-card">'
    if img:
        h += f'<img src="{img}" alt="{_html_escape(name)}">'
    h += f'<div class="joker-info"><div class="name-en">{_html_escape(name)}</div>'
    if name_zh:
        h += f'<div class="name-zh">{_html_escape(name_zh)}</div>'
    if effect:
        h += f'<div class="effect">{_html_escape(effect)}</div>'
    h += '</div></div>'
    return h

def _code_with_lines(code: str) -> str:
    """Wrap each line in a span for line numbering, escape HTML."""
    escaped = _html_escape(code)
    lines = escaped.split("\n")
    return "\n".join(f'<span class="line">{l}</span>' for l in lines)

BLIND_LABELS = {1: "小盲", 2: "大盲", 3: "Boss"}

def _format_progress(prog: str) -> str:
    """Format progress number: '301' → 'A3-小盲', '403' → 'A4-Boss'."""
    if not prog:
        return "-"
    try:
        n = int(prog)
        ante = n // 100
        blind = n % 100
        blind_name = BLIND_LABELS.get(blind, str(blind))
        return f"A{ante}-{blind_name}"
    except (ValueError, TypeError):
        return prog


def _progress_to_numeric(prog, final_ante=None) -> float | None:
    """Normalize progress to a single float: 3.0=A3小盲, 3.3=A3大盲, 3.6=A3Boss, 4.0=A4小盲.
    Accepts: int progress code (301), string ('301'), or None (falls back to final_ante)."""
    if prog:
        try:
            n = int(prog)
            ante = n // 100
            blind = n % 100
            # blind: 1=小盲(at), 2=大盲(passed小), 3=Boss(passed大)
            offset = {1: 0.0, 2: 0.3, 3: 0.6}.get(blind, 0.0)
            return round(ante + offset, 1)
        except (ValueError, TypeError):
            pass
    if final_ante:
        try:
            return float(final_ante)
        except (ValueError, TypeError):
            pass
    return None


def _format_progress_numeric(prog, final_ante=None) -> str:
    """Format progress as normalized number string like '3.0', '3.3', '3.6'."""
    v = _progress_to_numeric(prog, final_ante)
    return f"{v:.1f}" if v is not None else "-"


def _pagination_html(current_page: int, total_pages: int, param: str, tab_name: str) -> str:
    """Generate pagination controls HTML."""
    if total_pages <= 1:
        return ""
    h = '<div style="display:flex;justify-content:center;align-items:center;gap:.5rem;margin-top:1rem">'
    if current_page > 1:
        h += f'<a href="?{param}={current_page-1}#{tab_name}" onclick="setTimeout(function(){{switchTab(\'{tab_name}\')}},50)" style="color:var(--gold);text-decoration:none;padding:.3rem .8rem;border:1px solid #333;border-radius:4px">← 上一页</a>'
    h += f'<span style="color:var(--muted);padding:.3rem .8rem">{current_page} / {total_pages}</span>'
    if current_page < total_pages:
        h += f'<a href="?{param}={current_page+1}#{tab_name}" onclick="setTimeout(function(){{switchTab(\'{tab_name}\')}},50)" style="color:var(--gold);text-decoration:none;padding:.3rem .8rem;border:1px solid #333;border-radius:4px">下一页 →</a>'
    h += '</div>'
    return h


@app.get("/game/{run_code}", response_class=HTMLResponse)
async def page_game_detail(run_code: str):
    """Server-rendered game detail page."""
    row = await db_pool.fetchrow("SELECT id FROM balatro_runs WHERE run_code = $1", run_code)
    if not row:
        raise HTTPException(404, "Run not found")
    run_data = await get_run(row["id"])
    run = run_data["run"]
    jokers = run_data.get("jokers", [])
    screenshots = run_data.get("screenshots", [])
    catalog_map = _build_card_catalog_map()

    # Fetch strategy info
    strategy = None
    if run.get("strategy_id"):
        strategy = await db_pool.fetchrow("SELECT * FROM balatro_strategies WHERE id = $1", run["strategy_id"])

    # Score error stats
    score_err = await db_pool.fetchrow(
        """SELECT COUNT(*) as cnt, ROUND(AVG(ABS(score_error))::numeric * 100, 1) as avg_err,
           ROUND(MAX(ABS(score_error))::numeric * 100, 1) as max_err
           FROM balatro_screenshots WHERE run_id = $1
           AND estimated_score IS NOT NULL AND actual_score IS NOT NULL""", row["id"])

    # Fetch game log for text replay tab
    game_logs = await db_pool.fetch(
        """SELECT seq, phase, ante, blind, hand_cards, jokers, consumables,
                  dollars, hands_left, discards_left, chips, target,
                  action, decision_type, reasoning, hand_type, estimated_score, actual_score
           FROM balatro_game_log WHERE run_id = $1 ORDER BY seq""", row["id"])
    has_log = len(game_logs) > 0

    rc = run["run_code"]
    is_running = run["status"] == "running"
    dur = f'{round(run["duration_seconds"] / 60)}分钟' if run.get("duration_seconds") else "-"
    icon = "🔄" if is_running else ("🏆" if run.get("won") else "💀")
    status_badge = ' <span class="badge running">运行中</span>' if is_running else ""

    h = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{rc} - Balatro Playground 🃏</title><style>{_base_css()}{_game_log_css()}</style></head><body>
{_header()}<div class="container">
<a class="back-btn" href="/balatro/">← 返回列表</a>
<div class="detail-header"><h2>{icon} {rc}{status_badge}</h2>
<div style="font-family:monospace;font-size:.9rem;color:var(--muted);margin:.5rem 0">种子: {f'<a href="/balatro/seed/{run.get("seed")}" style="color:var(--gold)">{run.get("seed")}</a>' if run.get('seed') else '未知'} | 策略: {f'<a href="/balatro/strategy/{strategy["id"]}" style="color:var(--gold)">{_html_escape(strategy["name"])}</a>' if strategy else '未知'}</div>
<div class="detail-stats">"""

    # Score error display
    if score_err and score_err["cnt"] > 0:
        avg_e = float(score_err["avg_err"] or 0)
        max_e = float(score_err["max_err"] or 0)
        err_cls = "good" if avg_e < 20 else ("ok" if avg_e < 50 else "bad")
        err_val = f'<span class="score-err {err_cls}">均{avg_e:.0f}% 峰{max_e:.0f}%</span>'
    else:
        err_val = "-"

    # Weighted score for this run
    fa = run.get("final_ante") or 0
    ws = 2 ** (fa - 1) if fa > 0 else 0

    for v, lbl in [
        (f"Ante {run.get('final_ante', '?')}", "关卡"),
        (ws, "加权分"),
        (run.get("hands_played", 0), "出牌"),
        (run.get("discards_used", 0), "弃牌"),
        (run.get("purchases", 0), "购买"),
        (err_val, "估分误差"),
        (dur, "耗时"),
    ]:
        h += f'<div class="stat"><div class="val">{v}</div><div class="lbl">{lbl}</div></div>'
    h += "</div></div>"

    # Jokers
    if jokers:
        h += f'<div class="section"><h3>🃏 小丑牌 ({len(jokers)})</h3><div class="joker-grid">'
        for j in jokers:
            cj = catalog_map.get(j["name"].lower(), {})
            img = f'/balatro/joker-images/{cj["image"]}' if cj.get("image") else ""
            h += '<div class="joker-card">'
            if img:
                h += f'<img src="{img}" alt="{_html_escape(j["name"])}">'
            h += f'<div class="joker-info"><div class="name-en">{_html_escape(j["name"])}</div>'
            if cj.get("name_zh"):
                h += f'<div class="name-zh">{_html_escape(cj["name_zh"])}</div>'
            eff = cj.get("effect_zh") or cj.get("effect_en") or ""
            if eff:
                h += f'<div class="effect">{_html_escape(eff)}</div>'
            h += "</div></div>"
        h += "</div></div>"

    # Build TOC data first (need to scan screenshots)
    import re
    toc_items = []  # [(ante, blind, divider_id)]
    seen_keys = set()
    for i, s in enumerate(screenshots):
        cap = s.get("caption") or s.get("event_type") or ""
        ev = s.get("event_type") or ""
        ante_m = re.search(r"第(\d+)关", cap)
        ante_n = int(ante_m.group(1)) if ante_m else 0
        blind = ""
        for kw in ["商店", "小盲", "大盲", "Boss"]:
            if kw in cap:
                blind = kw
                break
        if not blind:
            if "游戏结束" in cap or ev == "game_over":
                blind = "结束"
            elif "开始" in cap or ev == "game_start":
                blind = "开始"
        key = f"a{ante_n}-{blind}"
        if key not in seen_keys and blind:
            seen_keys.add(key)
            toc_items.append((ante_n, blind, f"blind-{i}"))

    # Tabs: 文字棋谱 / 截图
    h += '<div class="tab-bar">'
    h += f'<button class="tab-btn{" active" if has_log else ""}" onclick="switchTab(\'log\')" id="tab-log">📜 文字棋谱{f" ({len(game_logs)}步)" if has_log else ""}</button>'
    h += f'<button class="tab-btn{" active" if not has_log else ""}" onclick="switchTab(\'screenshots\')" id="tab-screenshots">📷 截图 ({len(screenshots)}张)</button>'
    h += '</div>'

    # Tab: 文字棋谱
    h += f'<div class="tab-content" id="content-log" style="display:{"block" if has_log else "none"}">'
    if has_log:
        # Group by ante
        log_ante_groups = {}
        for log in game_logs:
            a = log["ante"] or 0
            if a not in log_ante_groups:
                log_ante_groups[a] = []
            log_ante_groups[a].append(log)

        current_ante = -1
        current_blind = ""
        for log in game_logs:
            ante = log["ante"] or 0
            blind = log["blind"] or ""
            phase = log["phase"]
            dt = log["decision_type"] or ""
            action = log["action"] or ""

            if ante != current_ante and ante > 0:
                if current_ante > 0:
                    h += '</div>'
                current_ante = ante
                current_blind = ""
                h += f'<div class="ante-block" id="log-ante-{ante}">'
                h += f'<div class="ante-header">═══ Ante {ante} ═══</div>'

            if blind and blind != current_blind:
                current_blind = blind
                target = log["target"] or 0
                target_str = f" (目标: {target:,})" if target else ""
                h += f'<div class="blind-header">{blind} Blind{target_str}</div>'

            jokers = log["jokers"] or ""
            dollars = log["dollars"] if log["dollars"] is not None else 0
            hl = log["hands_left"] if log["hands_left"] is not None else 0
            dl = log["discards_left"] if log["discards_left"] is not None else 0
            consumables = log["consumables"] or ""
            dt_tag = ""
            if dt == "rule":
                dt_tag = '<span class="dt-tag rule">Rule</span>'
            elif dt == "llm":
                dt_tag = '<span class="dt-tag llm">LLM</span>'

            # Joker bar — shown for play/discard/blind_select
            def _joker_bar():
                parts = []
                if jokers:
                    parts.append(f'🃏 {_html_escape(jokers)}')
                if consumables:
                    parts.append(f'🎴 {_html_escape(consumables)}')
                if parts:
                    return f'<div class="log-jokers">{" | ".join(parts)}</div>'
                return ''

            if phase in ("play", "discard"):
                hand = log["hand_cards"] or ""
                h += '<div class="log-entry">'
                h += f'<div class="log-state">💰${dollars} | 出牌:{hl} 弃牌:{dl}</div>'
                h += _joker_bar()
                if hand:
                    h += f'<div class="log-hand">手牌: {_html_escape(hand)}</div>'
                h += f'<div class="log-action">{dt_tag} {_html_escape(action)}</div>'
                if log["reasoning"]:
                    h += f'<div class="log-reason">{_html_escape(log["reasoning"])}</div>'
                if log["hand_type"]:
                    est = log["estimated_score"] or 0
                    act = log["actual_score"] or 0
                    err_cls = ""
                    if est > 0 and act > 0:
                        err = abs(act - est) / est
                        err_cls = "good" if err < 0.1 else ("ok" if err < 0.3 else "bad")
                        match_icon = "✅" if err < 0.1 else ("⚠️" if err < 0.3 else "❌")
                    else:
                        match_icon = ""
                    h += f'<div class="log-score"><span class="hand-type">{_html_escape(log["hand_type"])}</span>'
                    h += f' 估分=<span class="est">{est:,}</span>'
                    h += f' 实际=<span class="act {err_cls}">{act:,}</span> {match_icon}</div>'
                h += '</div>'
            elif phase == "shop":
                h += f'<div class="log-entry shop">'
                h += f'<div class="log-state">💰${dollars}</div>'
                h += f'<div class="log-action">{dt_tag} 🛒 {_html_escape(action)}</div>'
                if log["reasoning"]:
                    h += f'<div class="log-reason">{_html_escape(log["reasoning"])}</div>'
                h += _joker_bar()
                h += '</div>'
            elif phase == "blind_select":
                h += f'<div class="log-entry blind-select"><div class="log-action">🎯 {_html_escape(action)}</div>'
                h += f'<div class="log-state">💰${dollars}</div>'
                h += _joker_bar()
                h += '</div>'
            elif phase == "cashout":
                h += f'<div class="log-entry cashout"><div class="log-action">💰 {_html_escape(action)}</div>'
                h += _joker_bar()
                h += '</div>'
            elif phase == "game_over":
                chips = log["chips"] or 0
                h += f'<div class="log-entry game-over"><div class="log-action">💀 {_html_escape(action)}</div>'
                if chips:
                    h += f'<div class="log-state">最终筹码: {chips:,}</div>'
                h += '</div>'

        if current_ante > 0:
            h += '</div>'
    else:
        h += '<p style="color:var(--muted);padding:2rem;text-align:center">该局没有棋谱记录（仅 2026-02-20 之后的运行会记录棋谱）</p>'
    h += '</div>'

    # Tab: 截图
    h += f'<div class="tab-content" id="content-screenshots" style="display:{"none" if has_log else "block"}">'

    # Feed with detail-layout wrapper
    h += '<div class="detail-layout"><div class="detail-main">'
    h += f'<div class="section"><h3>📷 游戏过程 ({len(screenshots)} 张)'
    if is_running:
        h += ' <span class="badge running">实时更新中</span>'
    h += '</h3><div class="feed">'

    last_blind_key = ""
    for i, s in enumerate(screenshots):
        cap = s.get("caption") or s.get("event_type") or ""
        ev = s.get("event_type") or ""
        url = f"/balatro/screenshots/{rc}/screenshots/{s['filename']}"

        # Blind divider
        ante_m = re.search(r"第(\d+)关", cap)
        ante_n = int(ante_m.group(1)) if ante_m else 0
        blind = ""
        for kw in ["商店", "小盲", "大盲", "Boss"]:
            if kw in cap:
                blind = kw
                break
        if not blind:
            if "游戏结束" in cap or ev == "game_over":
                blind = "结束"
            elif "开始" in cap or ev == "game_start":
                blind = "开始"
        key = f"a{ante_n}-{blind}"
        if key != last_blind_key and blind:
            label = f"第{ante_n}关 {blind}" if ante_n > 0 else blind
            h += f'<div class="blind-divider" id="blind-{i}">{label}</div>'
            last_blind_key = key

        # Source tag
        src_tag = ""
        if "[Rule]" in cap:
            src_tag = ' <span class="source-tag rule">RULE</span>'
        elif "[LLM]" in cap:
            src_tag = ' <span class="source-tag llm">LLM</span>'

        h += '<div class="feed-entry">'
        if cap:
            h += f'<div class="caption">{_html_escape(cap)}{src_tag}</div>'

        # Score bar
        est = s.get("estimated_score")
        act = s.get("actual_score")
        if est and act is not None:
            err = s.get("score_error") or 0
            err_pct = round(err * 100)
            err_cls = "good" if abs(err) < 0.2 else ("ok" if abs(err) < 0.5 else "bad")
            sign = "+" if err >= 0 else ""
            h += f'<div class="score-bar"><span class="score-est">估分 {est}</span>'
            h += f'<span class="score-arrow">→</span><span class="score-act">实际 {act}</span>'
            h += f'<span class="score-err {err_cls}">{sign}{err_pct}%</span></div>'

        h += f'<img class="screenshot" src="{url}" alt="" onclick="openLb(this.src)" loading="lazy" onerror="this.style.display=\'none\'">'
        h += "</div>"

    h += "</div></div></div>"  # close feed, section, detail-main

    # TOC sidebar
    h += '<div class="toc"><div class="toc-title">目录</div>'
    last_toc_ante = -1
    for ante_n, blind, div_id in toc_items:
        if ante_n > 0 and ante_n != last_toc_ante:
            last_toc_ante = ante_n
            h += f'<div class="toc-ante" data-target="{div_id}" onclick="document.getElementById(\'{div_id}\').scrollIntoView({{behavior:\'smooth\'}})">第{ante_n}关</div>'
        if blind:
            h += f'<div class="toc-blind" data-target="{div_id}" onclick="document.getElementById(\'{div_id}\').scrollIntoView({{behavior:\'smooth\'}})">{blind}</div>'
    h += "</div></div>"  # close toc, detail-layout
    h += "</div>"  # close tab-content screenshots

    # Auto-refresh for running games
    if is_running:
        h += '<script>setTimeout(function(){location.reload()},5000)</script>'

    # Scroll spy for TOC
    h += """<script>
(function(){
  var dividers=document.querySelectorAll('.blind-divider[id]');
  var tocEls=document.querySelectorAll('.toc-ante,.toc-blind');
  if(!dividers.length||!tocEls.length)return;
  var obs=new IntersectionObserver(function(entries){
    entries.forEach(function(e){
      if(e.isIntersecting){
        var id=e.target.id;
        tocEls.forEach(function(t){
          var match=t.getAttribute('data-target')===id;
          t.classList.toggle('active',match);
          if(match)t.scrollIntoView({block:'nearest',behavior:'smooth'});
        });
      }
    });
  },{rootMargin:'-10% 0px -80% 0px'});
  dividers.forEach(function(d){obs.observe(d)});
})();
</script>"""

    h += f"""</div>{_lightbox_html()}
<script>
function switchTab(name){{
  document.querySelectorAll('.tab-content').forEach(function(el){{el.style.display='none'}});
  document.querySelectorAll('.tab-btn').forEach(function(el){{el.classList.remove('active')}});
  document.getElementById('content-'+name).style.display='block';
  document.getElementById('tab-'+name).classList.add('active');
}}
</script></body></html>"""
    return HTMLResponse(h)


@app.get("/game/{run_code}/log", response_class=HTMLResponse)
async def page_game_log(run_code: str):
    """Server-rendered game log (text replay) page."""
    row = await db_pool.fetchrow("SELECT id, strategy_id, seed, status, final_ante FROM balatro_runs WHERE run_code = $1", run_code)
    if not row:
        raise HTTPException(404, "Run not found")
    run_id = row["id"]

    logs = await db_pool.fetch(
        """SELECT seq, phase, ante, blind, hand_cards, jokers, consumables,
                  dollars, hands_left, discards_left, chips, target,
                  action, decision_type, reasoning, hand_type, estimated_score, actual_score,
                  boss_blind
           FROM balatro_game_log WHERE run_id = $1 ORDER BY seq""", run_id)

    if not logs:
        h = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{run_code} 棋谱 - Balatro 🃏</title><style>{_base_css()}</style></head><body>
{_header()}<div class="container">
<a class="back-btn" href="/balatro/game/{run_code}">← 返回详情</a>
<div class="detail-header"><h2>📜 {run_code} 文字棋谱</h2>
<p style="color:var(--muted);margin-top:.5rem">该局没有棋谱记录（仅 2026-02-20 之后的运行会记录棋谱）</p>
</div></div></body></html>"""
        return HTMLResponse(h)

    strategy_name = ""
    strategy_id = row["strategy_id"]
    if strategy_id:
        s = await db_pool.fetchrow("SELECT name FROM balatro_strategies WHERE id = $1", strategy_id)
        if s:
            strategy_name = s["name"]

    seed = row['seed'] or '未知'
    seed_link = f'<a href="/balatro/seed/{seed}" style="color:var(--gold)">{seed}</a>' if seed != '未知' else seed
    strategy_link = f'<a href="/balatro/strategy/{strategy_id}" style="color:var(--gold)">{_html_escape(strategy_name)}</a>' if strategy_id and strategy_name else '未知'

    h = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{run_code} 棋谱 - Balatro 🃏</title><style>{_base_css()}{_game_log_css()}</style></head><body>
{_header()}<div class="container">
<a class="back-btn" href="/balatro/game/{run_code}">← 返回详情</a>
<div class="detail-header"><h2>📜 {run_code} 文字棋谱</h2>
<div style="font-family:monospace;font-size:.9rem;color:var(--muted);margin:.5rem 0">种子: {seed_link} | 策略: {strategy_link} | 共 {len(logs)} 步</div>
</div>"""

    # Group by ante
    ante_groups = {}
    for log in logs:
        a = log["ante"] or 0
        if a not in ante_groups:
            ante_groups[a] = []
        ante_groups[a].append(log)

    # Build TOC HTML
    toc_html = '<div class="toc"><div class="toc-title">目录</div>'
    for ante in sorted(ante_groups.keys()):
        if ante == 0:
            continue
        blinds = []
        for log in ante_groups[ante]:
            if log["blind"] and log["blind"] not in blinds:
                blinds.append(log["blind"])
        toc_html += f'<div class="toc-ante" onclick="document.getElementById(\'ante-{ante}\').scrollIntoView({{behavior:\'smooth\'}})">Ante {ante}</div>'
        for b in ["Small", "Big", "Boss"]:
            if b in blinds:
                toc_html += f'<div class="toc-blind" onclick="document.getElementById(\'ante-{ante}-{b}\').scrollIntoView({{behavior:\'smooth\'}})">{b}</div>'
    toc_html += '</div>'

    # Main content (detail-main first, toc second — same as game detail page)
    h += '<div class="detail-layout"><div class="detail-main">'
    current_ante = -1
    current_blind = ""

    for log in logs:
        ante = log["ante"] or 0
        blind = log["blind"] or ""
        phase = log["phase"]
        dt = log["decision_type"] or ""
        action = log["action"] or ""

        # Ante divider
        if ante != current_ante and ante > 0:
            if current_ante > 0:
                h += '</div>'  # close prev ante-block
            current_ante = ante
            current_blind = ""
            h += f'<div class="ante-block" id="ante-{ante}">'
            h += f'<div class="ante-header">═══ Ante {ante} ═══</div>'

        # Blind divider
        if blind and blind != current_blind:
            current_blind = blind
            target = log["target"] or 0
            target_str = f" (目标: {target:,})" if target else ""
            boss_str = ""
            if blind == "Boss" and log.get("boss_blind"):
                boss_str = f' — 👹 {_html_escape(log["boss_blind"])}'
            h += f'<div class="blind-header" id="ante-{ante}-{blind}">{blind} Blind{target_str}{boss_str}</div>'

        # State bar
        jokers = log["jokers"] or ""
        dollars = log["dollars"] if log["dollars"] is not None else 0
        hl = log["hands_left"] if log["hands_left"] is not None else 0
        dl = log["discards_left"] if log["discards_left"] is not None else 0

        # Decision type tag
        dt_tag = ""
        if dt == "rule":
            dt_tag = '<span class="dt-tag rule">Rule</span>'
        elif dt == "llm":
            dt_tag = '<span class="dt-tag llm">LLM</span>'

        # Phase-specific rendering
        if phase in ("play", "discard"):
            hand = log["hand_cards"] or ""
            h += '<div class="log-entry">'
            h += f'<div class="log-state">💰${dollars} | 出牌:{hl} 弃牌:{dl}'
            if jokers:
                h += f' | 🃏 {_html_escape(jokers)}'
            h += '</div>'
            if hand:
                h += f'<div class="log-hand">手牌: {_html_escape(hand)}</div>'
            h += f'<div class="log-action">{dt_tag} {_html_escape(action)}</div>'
            if log["reasoning"]:
                h += f'<div class="log-reason">{_html_escape(log["reasoning"])}</div>'
            if log["hand_type"]:
                est = log["estimated_score"] or 0
                act = log["actual_score"] or 0
                err_cls = ""
                if est > 0 and act > 0:
                    err = abs(act - est) / est
                    err_cls = "good" if err < 0.1 else ("ok" if err < 0.3 else "bad")
                    match_icon = "✅" if err < 0.1 else ("⚠️" if err < 0.3 else "❌")
                else:
                    match_icon = ""
                h += f'<div class="log-score"><span class="hand-type">{_html_escape(log["hand_type"])}</span>'
                h += f' 估分=<span class="est">{est:,}</span>'
                h += f' 实际=<span class="act {err_cls}">{act:,}</span> {match_icon}</div>'
            h += '</div>'

        elif phase == "shop":
            h += '<div class="log-entry shop">'
            h += f'<div class="log-action">{dt_tag} 🛒 {_html_escape(action)}</div>'
            if log["reasoning"]:
                h += f'<div class="log-reason">{_html_escape(log["reasoning"])}</div>'
            h += '</div>'

        elif phase == "blind_select":
            h += f'<div class="log-entry blind-select"><div class="log-action">🎯 {_html_escape(action)}</div>'
            if jokers:
                h += f'<div class="log-state">🃏 {_html_escape(jokers)} | 💰${dollars}</div>'
            h += '</div>'

        elif phase == "cashout":
            h += f'<div class="log-entry cashout"><div class="log-action">💰 {_html_escape(action)}</div></div>'

        elif phase == "game_over":
            chips = log["chips"] or 0
            h += f'<div class="log-entry game-over"><div class="log-action">💀 {_html_escape(action)}</div>'
            if chips:
                h += f'<div class="log-state">最终筹码: {chips:,}</div>'
            h += '</div>'

    if current_ante > 0:
        h += '</div>'  # close last ante-block

    h += '</div>'  # close detail-main
    h += toc_html
    h += '</div>'  # close detail-layout

    # Stats summary
    play_count = sum(1 for l in logs if l["phase"] == "play")
    discard_count = sum(1 for l in logs if l["phase"] == "discard")
    shop_count = sum(1 for l in logs if l["phase"] == "shop")
    llm_count = sum(1 for l in logs if l["decision_type"] == "llm")
    rule_count = sum(1 for l in logs if l["decision_type"] == "rule")

    h += f"""<div class="detail-stats" style="margin-top:1.5rem">
<div class="stat"><div class="val">{play_count}</div><div class="lbl">出牌</div></div>
<div class="stat"><div class="val">{discard_count}</div><div class="lbl">弃牌</div></div>
<div class="stat"><div class="val">{shop_count}</div><div class="lbl">购买</div></div>
<div class="stat"><div class="val">{rule_count}</div><div class="lbl">Rule</div></div>
<div class="stat"><div class="val">{llm_count}</div><div class="lbl">LLM</div></div>
</div>"""

    h += "</div></body></html>"
    return HTMLResponse(h)

@app.get("/api/strategies")
async def list_strategies():
    """List all strategies with aggregated stats."""
    rows = await db_pool.fetch(
        """SELECT s.*,
           COUNT(r.id) AS total_runs,
           SUM(CASE WHEN r.won THEN 1 ELSE 0 END) AS total_wins,
           ROUND(AVG(r.final_ante), 1) AS calc_avg_ante,
           ROUND(AVG(r.llm_cost_usd)::numeric, 4) AS avg_cost,
           ROUND(AVG(r.duration_seconds)::numeric, 0) AS avg_duration
           FROM balatro_strategies s
           LEFT JOIN balatro_runs r ON r.strategy_id = s.id
           GROUP BY s.id ORDER BY s.created_at DESC"""
    )
    return [dict(r) for r in rows]


@app.get("/api/strategies/{strategy_id}")
async def get_strategy(strategy_id: int):
    """Get strategy detail with stats."""
    s = await db_pool.fetchrow("SELECT * FROM balatro_strategies WHERE id = $1", strategy_id)
    if not s:
        raise HTTPException(404, "Strategy not found")
    runs = await db_pool.fetch(
        """SELECT id, run_code, status, won, final_ante, seed, hands_played,
           discards_used, duration_seconds, llm_cost_usd, llm_model, played_at
           FROM balatro_runs WHERE strategy_id = $1 ORDER BY played_at DESC""",
        strategy_id
    )
    return {"strategy": dict(s), "runs": [dict(r) for r in runs]}

@app.get("/strategy/{strategy_id}", response_class=HTMLResponse)
async def page_strategy_detail(strategy_id: int):
    """Server-rendered strategy detail page with code, summary, tree."""
    s = await db_pool.fetchrow("SELECT * FROM balatro_strategies WHERE id = $1", strategy_id)
    if not s:
        raise HTTPException(404, "Strategy not found")

    runs = await db_pool.fetch(
        "SELECT * FROM balatro_runs WHERE strategy_id = $1 ORDER BY played_at DESC", strategy_id)
    total = len(runs)
    wins = sum(1 for r in runs if r.get("won"))
    win_rate = f"{round(wins / total * 100)}%" if total > 0 else "-"
    avg_ante = round(sum(r.get("final_ante") or 0 for r in runs) / total, 1) if total > 0 else "-"
    weighted_score = round(sum(2 ** ((r.get("final_ante") or 1) - 1) for r in runs if r.get("final_ante")) / max(total, 1), 1) if total > 0 else "-"

    # Strategy tree: ancestors + children
    ancestors = []
    pid = s.get("parent_id")
    while pid:
        anc = await db_pool.fetchrow("SELECT id, name, code_hash, created_at FROM balatro_strategies WHERE id = $1", pid)
        if not anc:
            break
        ancestors.insert(0, anc)
        pid = anc.get("parent_id")
    children = await db_pool.fetch(
        "SELECT id, name, code_hash, created_at FROM balatro_strategies WHERE parent_id = $1 ORDER BY created_at", strategy_id)

    import json as _json
    from datetime import timezone, timedelta
    sgt = timezone(timedelta(hours=8))

    name = s.get("name") or "未命名"
    code_hash = s.get("code_hash") or "-"
    model = s.get("model") or "-"
    params = s.get("params")
    if isinstance(params, str):
        params = _json.loads(params)
    source_code = s.get("source_code") or ""
    summary = s.get("summary") or s.get("description") or ""

    github_branch = s.get("github_branch") or ""
    github_url = f"https://github.com/carlnoah6/balatro-strategy/tree/{github_branch}" if github_branch else ""

    h = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>策略 {_html_escape(name)} - Balatro</title><style>{_base_css()}
pre.code{{background:#0d1117;padding:0;border-radius:8px;overflow-x:auto;font-size:.8rem;line-height:1.6;max-height:600px;overflow-y:auto;border:1px solid #333;position:relative}}
pre.code code{{display:block;padding:1rem 1rem 1rem 3.5rem;counter-reset:line}}
pre.code code .line{{display:block;position:relative}}
pre.code code .line::before{{counter-increment:line;content:counter(line);position:absolute;left:-3rem;width:2.5rem;text-align:right;color:#555;font-size:.75rem;user-select:none}}
.tree{{display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;margin:.75rem 0}}
.tree-node{{padding:.3rem .6rem;border-radius:6px;font-size:.85rem;font-family:monospace}}
.tree-node.current{{background:var(--accent);color:#fff;font-weight:700}}
.tree-node.ancestor{{background:var(--surface);color:var(--muted)}}
.tree-node.child{{background:var(--card);color:var(--gold)}}
.tree-arrow{{color:var(--muted);font-size:.8rem}}
</style>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/python.min.js"></script>
</head><body>
{_header()}<div class="container">
<a class="back-btn" href="/balatro/">← 返回列表</a>
<div class="detail-header">
<h2>🧠 {_html_escape(name)}</h2>
<div style="font-family:monospace;font-size:.9rem;color:var(--muted);margin:.5rem 0">
哈希: {code_hash} | 模型: {model}{f' | <a href="{github_url}" target="_blank" style="color:var(--gold)">📂 GitHub</a>' if github_url else ''}
</div>"""

    # Strategy tree
    if ancestors or children:
        h += '<div class="tree"><span style="color:var(--muted);font-size:.8rem">演进:</span>'
        for a in ancestors:
            atime = a["created_at"].astimezone(sgt).strftime("%m/%d %H:%M") if a.get("created_at") else ""
            h += f'<a href="/balatro/strategy/{a["id"]}" class="tree-node ancestor">{_html_escape(a["name"] or a["code_hash"][:8])}<br><span style="font-size:.7rem">{atime}</span></a><span class="tree-arrow">→</span>'
        cur_time = s["created_at"].astimezone(sgt).strftime("%m/%d %H:%M") if s.get("created_at") else ""
        h += f'<span class="tree-node current">{_html_escape(name)}<br><span style="font-size:.7rem">{cur_time}</span></span>'
        for c in children:
            ctime = c["created_at"].astimezone(sgt).strftime("%m/%d %H:%M") if c.get("created_at") else ""
            h += f'<span class="tree-arrow">→</span><a href="/balatro/strategy/{c["id"]}" class="tree-node child">{_html_escape(c["name"] or c["code_hash"][:8])}<br><span style="font-size:.7rem">{ctime}</span></a>'
        h += '</div>'

    # Stats
    h += '<div class="detail-stats">'
    for v, lbl in [(total, "总局数"), (wins, "胜场"), (win_rate, "胜率"), (avg_ante, "平均Ante"), (weighted_score, "加权分")]:
        h += f'<div class="stat"><div class="val">{v}</div><div class="lbl">{lbl}</div></div>'
    h += "</div></div>"

    # 1. Summary / Description
    if summary:
        h += f'<div class="section"><h3>📝 策略描述</h3><div style="background:var(--surface);padding:1rem;border-radius:8px;line-height:1.8;white-space:pre-wrap">{_html_escape(summary)}</div></div>'

    # 2. Source code - link to GitHub
    if source_code:
        if github_url:
            h += f'<div class="section"><h3>💻 策略代码</h3><div style="margin-bottom:.75rem"><a href="{github_url}" target="_blank" style="color:var(--gold);font-size:1rem">📂 在 GitHub 查看完整代码 →</a></div>'
        else:
            h += '<div class="section"><h3>💻 策略代码</h3>'
        h += f'<pre class="code"><code class="language-python">{_code_with_lines(source_code)}</code></pre></div>'

    # Params (filter out LLM-related params)
    llm_param_keys = {"model", "max_tokens", "llm_threshold"}
    if params:
        filtered_params = {k: v for k, v in params.items() if k not in llm_param_keys}
        if filtered_params:
            h += '<div class="section"><h3>⚙️ 策略参数</h3><div style="background:var(--surface);padding:1rem;border-radius:8px;font-family:monospace;font-size:.9rem">'
            for k, v in filtered_params.items():
                h += f'<div>{k}: <span style="color:var(--gold)">{v}</span></div>'
            h += "</div></div>"

    # Batch runs for this strategy
    batch_runs = await db_pool.fetch(
        """SELECT br.id, br.batch_id, br.status, br.completed_runs, br.total_runs, br.stats,
           b.name as batch_name, b.seed_count, b.stop_after_ante, b.created_at
           FROM balatro_batch_runs br
           JOIN balatro_batches b ON br.batch_id = b.id
           WHERE br.strategy_id = $1
           ORDER BY b.created_at DESC""", strategy_id)

    if batch_runs:
        h += f'<div class="section"><h3>📊 Batch 评估 ({len(batch_runs)})</h3>'
        h += '<table class="run-table sortable"><thead><tr><th>名称</th><th>种子数</th><th>状态</th><th data-tooltip="sum(2^(ante-1)) / N">加权分</th><th>最高Ante</th><th>时间</th></tr></thead><tbody>'
        for br in batch_runs:
            bname = br["batch_name"] or f"Batch #{br['batch_id']}"
            bstats = (json.loads(br["stats"]) if isinstance(br["stats"], str) else br["stats"]) if br["stats"] else {}
            bavg = bstats.get("avg_ante", "-")
            bws = bstats.get("weighted_score", bavg)  # fallback to avg_ante if no weighted_score
            bmax = bstats.get("max_ante", "-")
            bstatus = br["status"]
            if bstatus == "completed":
                bbadge = '<span class="badge win">完成</span>'
            elif bstatus == "running":
                bbadge = '<span class="badge running">运行中</span>'
            else:
                bbadge = f'<span class="badge loss">{bstatus}</span>'
            bcreated = br["created_at"].astimezone(sgt).strftime("%m/%d %H:%M") if br["created_at"] else ""
            h += f'<tr onclick="location.href=\'/balatro/batch/{br["batch_id"]}\'" style="cursor:pointer">'
            h += f'<td>{_html_escape(bname)}</td><td>{br["seed_count"]}</td><td>{bbadge}</td>'
            h += f'<td>{bws}</td><td>{bmax}</td><td>{bcreated}</td></tr>'
        h += '</tbody></table></div>'

    # Runs table
    if runs:
        h += f'<div class="section"><h3>🎮 关联运行 ({total} 局)</h3>'
        h += '<table class="run-table"><thead><tr><th>编号</th><th>进度</th><th>种子</th><th>出牌</th><th>弃牌</th><th>耗时</th><th>时间</th></tr></thead><tbody>'
        for r in runs:
            rc = r["run_code"] or str(r["id"])
            if r["status"] == "running":
                prog = '<span class="badge running">运行中</span>'
            elif r.get("won"):
                prog = '<span class="badge win">通关</span>'
            else:
                prog_text = _format_progress_numeric(r.get("progress"), r.get("final_ante"))
                prog = f'<span class="badge loss">{prog_text}</span>'
            seed = (r.get("seed") or "-")[:8]
            dur = f'{round(r["duration_seconds"] / 60)}m' if r.get("duration_seconds") else "-"
            t = r["played_at"].astimezone(sgt).strftime("%m/%d %H:%M") if r.get("played_at") else ""
            h += f'<tr onclick="location.href=\'/balatro/game/{rc}\'" style="cursor:pointer">'
            h += f'<td class="run-code">{rc}</td><td>{prog}</td><td style="font-family:monospace;font-size:.8rem;color:var(--muted)">{seed}</td>'
            h += f'<td>{r.get("hands_played", 0)}</td><td>{r.get("discards_used", 0)}</td><td>{dur}</td><td>{t}</td></tr>'
        h += "</tbody></table></div>"

    h += "</div><script>hljs.highlightAll();</script></body></html>"
    return HTMLResponse(h)




@app.get("/seed/{seed_val}", response_class=HTMLResponse)
async def page_seed_detail(seed_val: str):
    """Server-rendered seed detail page."""
    # Allow page to render even without runs (for seed analysis)
    runs = await db_pool.fetch(
        """SELECT r.*, s.name as strategy_name, s.id as sid
           FROM balatro_runs r LEFT JOIN balatro_strategies s ON r.strategy_id = s.id
           WHERE r.seed = $1 ORDER BY r.played_at DESC""", seed_val)

    # Validate seed format (8 chars, valid Balatro charset)
    import re
    if not re.match(r'^[1-9A-NP-Z]{3,8}$', seed_val):
        raise HTTPException(404, "Invalid seed format")

    from datetime import timezone, timedelta
    sgt = timezone(timedelta(hours=8))
    total = len(runs)
    wins = sum(1 for r in runs if r.get("won"))
    best_ante_values = []
    for r in runs:
        v = _progress_to_numeric(r.get("progress"), r.get("final_ante"))
        if v is not None:
            best_ante_values.append(v)
    best_ante = f'{max(best_ante_values):.1f}' if best_ante_values else "-"
    strategies_used = set(r.get("strategy_name") or "?" for r in runs if r.get("sid"))

    # Seed shop analysis via simulator
    shop_analysis = None
    try:
        import subprocess
        sim_dir = "/simulator"
        if not os.path.exists(sim_dir):
            sim_dir = "/home/ubuntu/.openclaw/workspace/projects/balatro-simulator"
        analyzer = os.path.join(sim_dir, "analyze_seed_shops.py")
        if os.path.exists(analyzer):
            proc = subprocess.run(
                ["python3", analyzer, seed_val],
                capture_output=True, text=True, timeout=10,
                cwd=sim_dir
            )
            if proc.returncode == 0:
                shop_analysis = json.loads(proc.stdout)
    except Exception:
        pass

    h = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>种子 {_html_escape(seed_val)} - Balatro</title><style>{_base_css()}</style></head><body>
{_header()}<div class="container">
<a class="back-btn" href="/balatro/">← 返回列表</a>
<div class="detail-header">
<h2>🌱 种子: <span style="font-family:monospace">{_html_escape(seed_val)}</span></h2>
<div class="detail-stats">"""
    for v, lbl in [(total, "运行次数"), (wins, "胜场"), (best_ante, "最佳Ante"), (len(strategies_used), "策略数")]:
        h += f'<div class="stat"><div class="val">{v}</div><div class="lbl">{lbl}</div></div>'
    h += "</div>"

    # Seed tier rating from seed sets
    seed_tier_info = None
    tier_rows = await db_pool.fetch("SELECT seed_tiers FROM balatro_seed_sets WHERE seed_tiers IS NOT NULL")
    for tr in tier_rows:
        raw = tr["seed_tiers"]
        tiers = json.loads(raw) if isinstance(raw, str) else (raw or {})
        if seed_val in tiers:
            seed_tier_info = tiers[seed_val]
            break

    if seed_tier_info and isinstance(seed_tier_info, dict):
        tier = seed_tier_info.get("tier", "?")
        tier_colors = {"S": "#e74c3c", "A": "#e67e22", "B": "#3498db", "C": "#95a5a6"}
        tc = tier_colors.get(tier, "#666")
        h += f'<div style="display:flex;gap:1rem;flex-wrap:wrap;margin-top:.75rem;align-items:center">'
        h += f'<div style="background:{tc};color:#fff;padding:.3rem .8rem;border-radius:6px;font-weight:700;font-size:1.2rem">{tier} 级</div>'
        for dim_val, dim_lbl in [
            (seed_tier_info.get("score"), "综合分"),
            (seed_tier_info.get("s_tier_count"), "S级Joker数"),
            (seed_tier_info.get("a_tier_count"), "A级Joker数"),
            (seed_tier_info.get("xmult_count"), "xMult Joker数"),
            (seed_tier_info.get("best_joker"), "最佳Joker"),
        ]:
            if dim_val is not None:
                h += f'<div style="background:var(--surface);padding:.3rem .6rem;border-radius:6px;font-size:.85rem"><span style="color:var(--muted)">{dim_lbl}:</span> <span style="color:var(--gold)">{dim_val}</span></div>'
        h += '</div>'

    h += "</div>"

    if strategies_used:
        # Build name->id map
        strat_id_map = {}
        for r in runs:
            if r.get("sid") and r.get("strategy_name"):
                strat_id_map[r["strategy_name"]] = r["sid"]
        h += '<div class="section"><h3>🧠 使用过的策略</h3><div style="display:flex;gap:.5rem;flex-wrap:wrap">'
        for sn in strategies_used:
            sid = strat_id_map.get(sn)
            if sid:
                h += f'<a href="/balatro/strategy/{sid}" style="background:var(--surface);padding:.3rem .6rem;border-radius:6px;font-size:.85rem;color:var(--gold)">{_html_escape(sn)}</a>'
            else:
                h += f'<span style="background:var(--surface);padding:.3rem .6rem;border-radius:6px;font-size:.85rem">{_html_escape(sn)}</span>'
        h += "</div></div>"

    # Shop analysis section
    if shop_analysis:
        catalog_map = _build_card_catalog_map()
        summary = shop_analysis.get("summary", {})
        builds = summary.get("suggested_builds", [])
        high_tier = summary.get("high_tier_jokers", [])
        xmult = summary.get("xmult_jokers", [])

        h += '<div class="section"><h3>🔍 种子分析 (Ante 1-3 商店预览)</h3>'

        # Summary cards
        if builds or high_tier:
            h += '<div style="display:flex;gap:1rem;margin:.5rem 0;flex-wrap:wrap">'
            if xmult:
                unique_xm = list(dict.fromkeys(xmult))
                h += f'<div class="card" style="flex:1;min-width:150px;padding:.8rem;border-left:4px solid #e74c3c"><div style="font-weight:600;color:#e74c3c">xMult Jokers ({len(unique_xm)})</div>'
                for j in unique_xm:
                    h += f'<div style="padding:2px 0">{_joker_card_html(j, catalog_map, compact=True)}</div>'
                h += '</div>'
            if high_tier:
                unique_ht = list(dict.fromkeys(high_tier))
                h += f'<div class="card" style="flex:1;min-width:150px;padding:.8rem;border-left:4px solid #e67e22"><div style="font-weight:600;color:#e67e22">高价值 Jokers ({len(unique_ht)})</div>'
                for j in unique_ht:
                    h += f'<div style="padding:2px 0">{_joker_card_html(j, catalog_map, compact=True)}</div>'
                h += '</div>'
            if builds:
                h += '<div class="card" style="flex:1;min-width:150px;padding:.8rem;border-left:4px solid #2ecc71"><div style="font-weight:600;color:#2ecc71">推荐路线</div>'
                for b in builds:
                    h += f'<div style="font-size:.85rem">{_html_escape(b)}</div>'
                h += '</div>'
            h += '</div>'

        # Per-ante shop details
        tier_colors_shop = {"S+": "#e74c3c", "S": "#e74c3c", "A": "#e67e22", "B": "#95a5a6"}
        for ante_data in shop_analysis.get("antes", []):
            ante_num = ante_data["ante"]
            h += f'<details style="margin:.5rem 0"><summary style="cursor:pointer;font-weight:600;padding:.3rem 0">Ante {ante_num} 商店详情</summary>'
            h += '<div style="display:flex;gap:.5rem;flex-wrap:wrap;margin:.5rem 0">'
            for shop_data in ante_data.get("shops", []):
                blind = shop_data["blind"]
                h += f'<div class="card" style="flex:1;min-width:200px;padding:.6rem">'
                h += f'<div style="font-weight:600;font-size:.9rem;margin-bottom:.3rem">{blind} Blind</div>'
                for item in shop_data.get("items", []):
                    if item["type"] == "joker":
                        tier = item.get("tier", "B")
                        tc = tier_colors_shop.get(tier, "#666")
                        xm_badge = ' <span style="background:#e74c3c;color:#fff;padding:1px 4px;border-radius:3px;font-size:.7rem">xMult</span>' if item.get("xmult") else ""
                        edition = f' ({item["edition"]})' if item.get("edition") and item["edition"] != "base" else ""
                        h += f'<div style="font-size:.85rem;padding:2px 0"><span style="color:{tc};font-weight:600">[{tier}]</span> {_joker_card_html(item["name"], catalog_map, compact=True)}{edition} <span style="color:var(--muted)">${item["cost"]}</span>{xm_badge}</div>'
                    else:
                        h += f'<div style="font-size:.85rem;padding:2px 0;color:var(--muted)">🃏 {_html_escape(item["name"])} <span>${item.get("cost", "?")}</span></div>'
                if shop_data.get("voucher"):
                    v = shop_data["voucher"]
                    v_style = "color:#2ecc71;font-weight:600" if v.get("valuable") else "color:var(--muted)"
                    h += f'<div style="font-size:.85rem;padding:2px 0;{v_style}">🎫 {_html_escape(v["name"])}</div>'
                h += '</div>'
            h += '</div></details>'
        h += '</div>'

    if runs:
        h += f'<div class="section"><h3>🎮 关联运行 ({total} 局)</h3>'
    h += '<table class="run-table"><thead><tr><th>编号</th><th>进度</th><th>策略</th><th>出牌</th><th>弃牌</th><th>耗时</th><th>时间</th></tr></thead><tbody>'
    for r in runs:
        rc = r["run_code"] or str(r["id"])
        if r["status"] == "running":
            prog = '<span class="badge running">运行中</span>'
        elif r.get("won"):
            prog = '<span class="badge win">通关</span>'
        else:
            prog_text = _format_progress_numeric(r.get("progress"), r.get("final_ante"))
            prog = f'<span class="badge loss">{prog_text}</span>'
        sn = r.get("strategy_name") or "-"
        sid = r.get("sid")
        scell = f'<a href="/balatro/strategy/{sid}" onclick="event.stopPropagation()" style="color:var(--gold);font-size:.8rem">{_html_escape(sn)}</a>' if sid else "-"
        dur = f'{round(r["duration_seconds"] / 60)}m' if r.get("duration_seconds") else "-"
        t = r["played_at"].astimezone(sgt).strftime("%m/%d %H:%M") if r.get("played_at") else ""
        h += f'<tr onclick="location.href=\'/balatro/game/{rc}\'" style="cursor:pointer">'
        h += f'<td class="run-code">{rc}</td><td>{prog}</td><td>{scell}</td>'
        h += f'<td>{r.get("hands_played", 0)}</td><td>{r.get("discards_used", 0)}</td><td>{dur}</td><td>{t}</td></tr>'
    if runs:
        h += "</tbody></table></div>"
    elif not shop_analysis:
        h += '<p style="color:var(--muted);padding:2rem;text-align:center">该种子暂无运行记录和分析数据。</p>'
    h += "</div></body></html>"
    return HTMLResponse(h)


# ── Batch Pages ─────────────────────────────────────────────────────────────

@app.get("/api/batches")
async def api_batches():
    rows = await db_pool.fetch(
        """SELECT b.*, br.id as batch_run_id, br.strategy_id, br.status as run_status,
           br.completed_runs, br.total_runs, br.stats,
           s.name as strategy_name
           FROM balatro_batches b
           LEFT JOIN balatro_batch_runs br ON br.batch_id = b.id
           LEFT JOIN balatro_strategies s ON br.strategy_id = s.id
           ORDER BY b.created_at DESC"""
    )
    return [dict(r) for r in rows]


@app.get("/batches", response_class=HTMLResponse)
async def page_batch_list():
    """Redirect to main page with batches tab active."""
    from starlette.responses import RedirectResponse
    return RedirectResponse("/balatro/#batches", status_code=302)


@app.get("/batch/{batch_id}", response_class=HTMLResponse)
async def page_batch_detail(batch_id: int):
    """Batch detail page with per-seed results."""
    from datetime import timezone, timedelta
    sgt = timezone(timedelta(hours=8))

    batch = await db_pool.fetchrow("SELECT * FROM balatro_batches WHERE id = $1", batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found")

    batch_run = await db_pool.fetchrow(
        """SELECT br.*, s.name as strategy_name
           FROM balatro_batch_runs br
           LEFT JOIN balatro_strategies s ON br.strategy_id = s.id
           WHERE br.batch_id = $1 ORDER BY br.id DESC LIMIT 1""", batch_id)

    # Get all runs for this batch
    runs = await db_pool.fetch(
        """SELECT r.id, r.run_code, r.seed, r.status, r.final_ante, r.won,
           r.hands_played, r.discards_used, r.duration_seconds,
           r.llm_cost_usd, r.rule_decisions, r.llm_decisions, r.progress,
           r.played_at
           FROM balatro_runs r
           WHERE r.batch_run_id = $1
           ORDER BY r.seed""",
        batch_run["id"] if batch_run else 0)

    name = batch["name"] or f"Batch #{batch_id}"
    seeds = batch["seed_count"]
    stop = batch["stop_after_ante"]
    status = batch_run["status"] if batch_run else "pending"
    strategy_name = batch_run["strategy_name"] if batch_run else "-"
    strategy_id = batch_run["strategy_id"] if batch_run else None
    stats = (json.loads(batch_run["stats"]) if isinstance(batch_run["stats"], str) else batch_run["stats"]) if batch_run and batch_run["stats"] else {}

    # Calculate stats from runs
    antes = [r["final_ante"] for r in runs if r["final_ante"]]
    avg_ante = round(sum(antes) / len(antes), 1) if antes else "-"
    max_ante = max(antes) if antes else "-"
    weighted_score = round(sum(2 ** (a - 1) for a in antes) / len(antes), 1) if antes else "-"
    wins = sum(1 for r in runs if r.get("won"))
    total_hands = sum(r["hands_played"] or 0 for r in runs)
    total_discards = sum(r["discards_used"] or 0 for r in runs)
    completed = len([r for r in runs if r["status"] in ("completed", "failed")])

    if status == "completed":
        badge = '<span class="badge win">完成</span>'
    elif status == "running":
        badge = '<span class="badge running">运行中</span>'
    else:
        badge = f'<span class="badge loss">{status}</span>'

    # Ante distribution using normalized progress
    ante_dist = {}
    for r in runs:
        v = _progress_to_numeric(r.get("progress"), r.get("final_ante"))
        if v is not None:
            ante_dist[v] = ante_dist.get(v, 0) + 1

    # Score error stats from game logs
    score_errors = await db_pool.fetch(
        """SELECT gl.estimated_score, gl.actual_score
           FROM balatro_game_log gl
           JOIN balatro_runs r ON gl.run_id = r.id
           WHERE r.batch_run_id = $1
           AND gl.estimated_score IS NOT NULL AND gl.actual_score IS NOT NULL
           AND gl.actual_score > 0""",
        batch_run["id"] if batch_run else 0)
    err_pcts = []
    for se in score_errors:
        err = abs(se["estimated_score"] - se["actual_score"]) / se["actual_score"] * 100
        err_pcts.append(err)
    avg_err = round(sum(err_pcts) / len(err_pcts), 1) if err_pcts else None
    max_err = round(max(err_pcts), 1) if err_pcts else None
    # Error distribution buckets: 0-5%, 5-10%, 10-20%, 20-50%, 50%+
    err_buckets = {"0-5%": 0, "5-10%": 0, "10-20%": 0, "20-50%": 0, "50%+": 0}
    for e in err_pcts:
        if e <= 5: err_buckets["0-5%"] += 1
        elif e <= 10: err_buckets["5-10%"] += 1
        elif e <= 20: err_buckets["10-20%"] += 1
        elif e <= 50: err_buckets["20-50%"] += 1
        else: err_buckets["50%+"] += 1

    strategy_link = f'<a href="/balatro/strategy/{strategy_id}" style="color:var(--gold)">{_html_escape(strategy_name)}</a>' if strategy_id else strategy_name

    h = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name} - Batch 详情 🃏</title><style>{_base_css()}
.detail-layout{{display:grid;grid-template-columns:280px 1fr;gap:1.5rem}}
.detail-stats{{display:flex;flex-direction:column;gap:.8rem}}
.stat-card{{background:var(--card-bg);border:1px solid #333;border-radius:8px;padding:1rem}}
.stat-card .label{{font-size:.75rem;color:var(--muted);margin-bottom:.3rem}}
.stat-card .value{{font-size:1.4rem;font-weight:700}}
.ante-bar{{display:flex;align-items:flex-end;gap:4px;height:120px;margin-top:.5rem}}
.ante-col{{flex:1;background:var(--gold);border-radius:3px 3px 0 0;min-width:20px;position:relative;transition:opacity .15s}}
.ante-col:hover{{opacity:.8}}
.ante-col .ante-label{{position:absolute;bottom:-18px;left:50%;transform:translateX(-50%);font-size:.7rem;color:var(--muted)}}
.ante-col .ante-count{{position:absolute;top:-18px;left:50%;transform:translateX(-50%);font-size:.75rem;font-weight:600}}
.err-bar{{display:flex;align-items:flex-end;gap:4px;height:80px;margin-top:.5rem}}
.err-col{{flex:1;border-radius:3px 3px 0 0;min-width:30px;position:relative;transition:opacity .15s}}
.err-col:hover{{opacity:.8}}
.err-col .err-label{{position:absolute;bottom:-18px;left:50%;transform:translateX(-50%);font-size:.65rem;color:var(--muted);white-space:nowrap}}
.err-col .err-count{{position:absolute;top:-18px;left:50%;transform:translateX(-50%);font-size:.75rem;font-weight:600}}
</style></head><body>
{_header()}<div class="container">
<div style="display:flex;align-items:center;gap:1rem;margin-bottom:1.5rem">
<a href="/balatro/batches" style="color:var(--muted);text-decoration:none;font-size:.9rem">← 返回列表</a>
<h2 style="margin:0">{_html_escape(name)}</h2>{badge}
</div>

<div class="detail-layout">
<div class="detail-stats">
<div class="stat-card"><div class="label">策略</div><div class="value" style="font-size:1rem">{strategy_link}</div></div>
<div class="stat-card"><div class="label">已完成</div><div class="value">{completed} <span style="font-size:.8rem;color:var(--muted)">/ {seeds} seeds</span></div></div>
<div class="stat-card"><div class="label">目标关卡</div><div class="value">{stop}</div></div>
<div class="stat-card"><div class="label">加权分</div><div class="value">{weighted_score}</div></div>
<div class="stat-card"><div class="label">平均 Ante</div><div class="value">{avg_ante}</div></div>
<div class="stat-card"><div class="label">最高 Ante</div><div class="value">{max_ante}</div></div>
<div class="stat-card"><div class="label">胜率</div><div class="value">{wins}/{len(runs)}</div></div>
<div class="stat-card"><div class="label">总出牌 / 弃牌</div><div class="value">{total_hands} / {total_discards}</div></div>"""

    if avg_err is not None:
        h += f'<div class="stat-card"><div class="label">估分误差</div><div class="value">{avg_err}%<span style="font-size:.8rem;color:var(--muted)"> avg / {max_err}% max</span></div></div>'

    h += """</div>
<div>"""

    # Ante distribution chart
    if ante_dist:
        max_count = max(ante_dist.values())
        h += '<div class="stat-card"><div class="label">Ante 分布</div><div class="ante-bar">'
        for ante in sorted(ante_dist.keys()):
            count = ante_dist[ante]
            pct = round(count / max_count * 100)
            label = f'{ante:.1f}' if ante != int(ante) else f'{int(ante)}.0'
            h += f'<div class="ante-col" style="height:{pct}%"><span class="ante-count">{count}</span><span class="ante-label">{label}</span></div>'
        h += '</div></div>'

    # Score error distribution chart
    if err_pcts:
        err_max_count = max(err_buckets.values()) if max(err_buckets.values()) > 0 else 1
        colors = ["#4ade80", "#a3e635", "#facc15", "#fb923c", "#f87171"]
        h += '<div class="stat-card" style="margin-top:1rem"><div class="label">估分误差分布</div><div class="err-bar">'
        for i, (label, count) in enumerate(err_buckets.items()):
            pct = round(count / err_max_count * 100) if count > 0 else 2
            h += f'<div class="err-col" style="height:{pct}%;background:{colors[i]}"><span class="err-count">{count}</span><span class="err-label">{label}</span></div>'
        h += f'</div><div style="margin-top:1.5rem;font-size:.8rem;color:var(--muted)">共 {len(err_pcts)} 次估分 | 平均误差 {avg_err}% | 最大误差 {max_err}%</div></div>'

    # Runs table
    # Load seed tiers if batch has a seed set
    batch_seed_tiers = {}
    tier_colors_b = {"S": "#e74c3c", "A": "#e67e22", "B": "#3498db", "C": "#95a5a6"}
    if batch.get("seed_set_id"):
        ss_row = await db_pool.fetchrow("SELECT seed_tiers FROM balatro_seed_sets WHERE id = $1", batch["seed_set_id"])
        if ss_row and ss_row["seed_tiers"]:
            raw_tiers = ss_row["seed_tiers"]
            batch_seed_tiers = json.loads(raw_tiers) if isinstance(raw_tiers, str) else raw_tiers

    # Tier-grouped stats
    if batch_seed_tiers and runs:
        tier_stats = {}
        for r in runs:
            sd = r["seed"]
            ti_info = batch_seed_tiers.get(sd, {})
            tier = ti_info.get("tier", "?") if isinstance(ti_info, dict) else "?"
            if tier not in tier_stats:
                tier_stats[tier] = {"antes": [], "weighted": []}
            fa = r["final_ante"]
            if fa:
                tier_stats[tier]["antes"].append(fa)
                tier_stats[tier]["weighted"].append(2 ** (fa - 1))
        h += '<div class="stat-card" style="margin-top:1rem"><div class="label" style="margin-bottom:.8rem">按评级统计</div>'
        h += '<div style="display:flex;gap:1rem;flex-wrap:wrap">'
        for t in ["S", "A", "B", "C"]:
            if t not in tier_stats:
                continue
            ts = tier_stats[t]
            tavg = round(sum(ts["antes"]) / len(ts["antes"]), 1) if ts["antes"] else "-"
            tws = round(sum(ts["weighted"]) / len(ts["weighted"]), 1) if ts["weighted"] else "-"
            tmax = max(ts["antes"]) if ts["antes"] else "-"
            tcolor = tier_colors_b.get(t, "#666")
            h += f'<div class="card" style="flex:1;min-width:120px;padding:.8rem;border-left:4px solid {tcolor}">'
            h += f'<div style="font-weight:700;color:{tcolor};font-size:1.1rem">{t} 级 ({len(ts["antes"])})</div>'
            h += f'<div style="font-size:.85rem">平均 Ante: <b>{tavg}</b></div>'
            h += f'<div style="font-size:.85rem">最高 Ante: <b>{tmax}</b></div>'
            h += f'<div style="font-size:.85rem">加权分: <b>{tws}</b></div></div>'
        h += '</div></div>'

    has_tier_col = bool(batch_seed_tiers)
    tier_th = '<th>评级</th>' if has_tier_col else ''
    h += f"""<div class="stat-card" style="margin-top:1rem">
<div class="label" style="margin-bottom:.8rem">每局详情</div>
<table class="run-table sortable"><thead><tr>
<th>种子</th>{tier_th}<th>进度</th><th data-tooltip="sum(2^(ante-1))">加权分</th><th>耗时</th>
</tr></thead><tbody>"""

    for r in runs:
        rc = r["run_code"]
        seed = r["seed"] or "-"
        fa = r["final_ante"] or 0
        if r["status"] == "running":
            prog = '<span class="badge running">运行中</span>'
        elif r.get("won"):
            prog = '<span class="badge win">通关</span>'
        else:
            prog_text = _format_progress_numeric(r.get("progress"), r.get("final_ante"))
            prog = f'<span class="badge loss">{prog_text}</span>'

        run_ws = 2 ** (fa - 1) if fa > 0 else 0
        dur = f'{round(r["duration_seconds"])}s' if r.get("duration_seconds") else "-"

        h += f'<tr onclick="location.href=\'/balatro/game/{rc}\'" style="cursor:pointer">'
        h += f'<td class="run-code" style="font-family:monospace">{seed}</td>'
        if has_tier_col:
            ti_info = batch_seed_tiers.get(seed, {})
            tier = ti_info.get("tier", "-") if isinstance(ti_info, dict) else "-"
            tcolor = tier_colors_b.get(tier, "#666")
            h += f'<td><span style="background:{tcolor};color:#fff;padding:2px 6px;border-radius:4px;font-weight:700;font-size:.8rem">{tier}</span></td>'
        h += f'<td>{prog}</td>'
        h += f'<td>{run_ws}</td><td>{dur}</td></tr>'

    h += """</tbody></table></div>
</div></div></div></body></html>"""
    return HTMLResponse(h)


@app.get("/seedset/{seedset_id}", response_class=HTMLResponse)
async def page_seedset_detail(seedset_id: int):
    """Seed set detail page."""
    ss = await db_pool.fetchrow("SELECT * FROM balatro_seed_sets WHERE id = $1", seedset_id)
    if not ss:
        raise HTTPException(404, "Seed set not found")

    from datetime import timezone, timedelta
    sgt = timezone(timedelta(hours=8))

    seeds = json.loads(ss["seeds"]) if isinstance(ss["seeds"], str) else (ss["seeds"] or [])

    # Get batches using this seed set
    batches = await db_pool.fetch("""
        SELECT b.id, b.name, b.created_at,
               br.status, br.stats, s.name as strategy_name
        FROM balatro_batches b
        LEFT JOIN balatro_batch_runs br ON br.batch_id = b.id
        LEFT JOIN balatro_strategies s ON br.strategy_id = s.id
        WHERE b.seed_set_id = $1
        ORDER BY b.created_at DESC
    """, seedset_id)

    # Get per-seed stats across all runs
    seed_stats = {}
    if seeds:
        placeholders = ", ".join(f"${i+1}" for i in range(len(seeds)))
        rows = await db_pool.fetch(f"""
            SELECT seed, COUNT(*) as runs,
                   array_agg(progress) as progresses,
                   array_agg(final_ante) as antes
            FROM balatro_runs WHERE seed IN ({placeholders})
            GROUP BY seed
        """, *seeds)
        for r in rows:
            progresses = r["progresses"] or []
            antes = r["antes"] or []
            norm_values = []
            for i, p in enumerate(progresses):
                fa = antes[i] if i < len(antes) else None
                v = _progress_to_numeric(p, fa)
                if v is not None:
                    norm_values.append(v)
            if not norm_values and antes:
                norm_values = [float(a) for a in antes if a]
            best = max(norm_values) if norm_values else None
            avg = round(sum(norm_values) / len(norm_values), 1) if norm_values else None
            seed_stats[r["seed"]] = {"runs": r["runs"], "best": best, "avg": avg}

    h = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_html_escape(ss['name'])} - Balatro Playground 🃏</title><style>{_base_css()}</style></head><body>
{_header()}<div class="container">
<a href="/balatro/#seedsets" style="color:var(--muted);text-decoration:none;font-size:.9rem">← 返回种子集列表</a>
<h2 style="margin:.5rem 0">{_html_escape(ss['name'])}</h2>
<p style="color:var(--muted)">{_html_escape(ss.get('description') or '')}</p>
<div style="display:flex;gap:2rem;margin:1rem 0">
<div class="card" style="flex:1;padding:1rem"><div style="color:var(--muted);font-size:.8rem">种子数</div><div style="font-size:1.5rem;font-weight:700">{ss['seed_count']}</div></div>
<div class="card" style="flex:1;padding:1rem"><div style="color:var(--muted);font-size:.8rem">批量次数</div><div style="font-size:1.5rem;font-weight:700">{len(batches)}</div></div>
<div class="card" style="flex:1;padding:1rem"><div style="color:var(--muted);font-size:.8rem">创建时间</div><div style="font-size:1rem">{ss['created_at'].astimezone(sgt).strftime('%Y-%m-%d %H:%M') if ss.get('created_at') else '-'}</div></div>
</div>"""

    # Parse seed tiers
    seed_tiers_raw = ss.get("seed_tiers")
    seed_tiers = json.loads(seed_tiers_raw) if isinstance(seed_tiers_raw, str) else (seed_tiers_raw or {})
    tier_colors = {"S": "#e74c3c", "A": "#e67e22", "B": "#3498db", "C": "#95a5a6"}
    tier_labels = {"S": "S", "A": "A", "B": "B", "C": "C"}

    # Tier distribution card
    if seed_tiers:
        tier_counts = {}
        for _sd, _ti in seed_tiers.items():
            t = _ti.get("tier", "?") if isinstance(_ti, dict) else "?"
            tier_counts[t] = tier_counts.get(t, 0) + 1
        h += '<h3 style="margin-top:1.5rem">🏷️ 评级分布</h3>'
        h += '<div style="display:flex;gap:1rem;margin:.5rem 0;flex-wrap:wrap">'
        for t in ["S", "A", "B", "C"]:
            cnt = tier_counts.get(t, 0)
            pct = round(cnt / len(seeds) * 100) if seeds else 0
            color = tier_colors.get(t, "#666")
            h += f'<div class="card" style="flex:1;min-width:100px;padding:.8rem;border-left:4px solid {color}">'
            h += f'<div style="font-size:1.4rem;font-weight:700;color:{color}">{t}</div>'
            h += f'<div style="font-size:1.2rem;font-weight:600">{cnt} 个</div>'
            h += f'<div style="color:var(--muted);font-size:.8rem">{pct}%</div></div>'
        # Bar chart
        h += '</div><div style="display:flex;height:24px;border-radius:6px;overflow:hidden;margin:.5rem 0">'
        for t in ["S", "A", "B", "C"]:
            cnt = tier_counts.get(t, 0)
            pct = cnt / len(seeds) * 100 if seeds else 0
            color = tier_colors.get(t, "#666")
            if pct > 0:
                h += f'<div style="width:{pct}%;background:{color};display:flex;align-items:center;justify-content:center;color:#fff;font-size:.75rem;font-weight:600">{t}</div>'
        h += '</div>'

    # Seeds table with tier
    h += '<h3 style="margin-top:1.5rem">🌱 种子列表</h3>'
    has_tiers = bool(seed_tiers)
    tier_header = '<th>评级</th><th>评分</th><th>xMult</th><th>最佳Joker</th>' if has_tiers else ''
    h += f'<table class="run-table"><thead><tr><th>种子</th>{tier_header}<th>运行次数</th><th>最佳Ante</th><th>平均Ante</th></tr></thead><tbody>'
    for s in seeds:
        st = seed_stats.get(s, {})
        runs_count = st.get("runs", 0)
        best = st.get("best")
        avg = st.get("avg")
        best_str = f'{best:.1f}' if best is not None else "-"
        avg_str = f'{avg}' if avg is not None else "-"
        h += f'<tr onclick="location.href=\'/balatro/seed/{s}\'" style="cursor:pointer">'
        h += f'<td style="font-family:monospace">{s}</td>'
        if has_tiers:
            ti = seed_tiers.get(s, {})
            tier = ti.get("tier", "-") if isinstance(ti, dict) else "-"
            tscore = ti.get("score", "-") if isinstance(ti, dict) else "-"
            txmult = ti.get("xmult_count", 0) if isinstance(ti, dict) else 0
            tbest = ti.get("best_joker", "-") if isinstance(ti, dict) else "-"
            tcolor = tier_colors.get(tier, "#666")
            h += f'<td><span style="background:{tcolor};color:#fff;padding:2px 8px;border-radius:4px;font-weight:700;font-size:.85rem">{tier}</span></td>'
            h += f'<td>{tscore}</td><td>{txmult}</td><td style="font-size:.85rem">{_html_escape(str(tbest))}</td>'
        h += f'<td>{runs_count}</td><td>{best_str}</td><td>{avg_str}</td></tr>'
    h += '</tbody></table>'

    # Batches using this seed set
    if batches:
        h += '<h3 style="margin-top:1.5rem">📊 关联批量</h3>'
        h += '<table class="run-table sortable"><thead><tr><th>名称</th><th>策略</th><th>状态</th><th data-tooltip="sum(2^(ante-1)) / N">加权分</th><th>时间</th></tr></thead><tbody>'
        for b in batches:
            bstats = json.loads(b["stats"]) if isinstance(b["stats"], str) else (b["stats"] or {})
            bavg = bstats.get("weighted_score", bstats.get("avg_ante", "-"))
            bstatus = b["status"] or "pending"
            badge = '<span class="badge win">完成</span>' if bstatus == "completed" else f'<span class="badge loss">{bstatus}</span>'
            bt = b["created_at"].astimezone(sgt).strftime("%m/%d %H:%M") if b.get("created_at") else ""
            bid = b["id"]
            bname = b["name"] or f"Batch #{bid}"
            h += f'<tr onclick="location.href=\'/balatro/batch/{bid}\'" style="cursor:pointer">'
            h += f'<td>{bname}</td><td>{b["strategy_name"] or "-"}</td>'
            h += f'<td>{badge}</td><td>{bavg}</td><td>{bt}</td></tr>'
        h += '</tbody></table>'

    h += '</div></body></html>'
    return HTMLResponse(h)


# ============================================================
# Simulator Validation
# ============================================================

@app.get("/api/validation/{batch_id}")
async def api_validation(batch_id: int):
    """Get validation results for a batch."""
    rows = await db_pool.fetch(
        """SELECT seed, category, ante, status, expected, actual, detail
           FROM balatro_sim_validation
           WHERE batch_id = $1
           ORDER BY seed, ante, category""", batch_id)
    return [dict(r) for r in rows]


@app.get("/api/validation/summary/{batch_id}")
async def api_validation_summary(batch_id: int):
    """Get validation summary for a batch."""
    row = await db_pool.fetchrow("""
        SELECT
            COUNT(*) FILTER (WHERE status = 'PASS') as passed,
            COUNT(*) FILTER (WHERE status = 'FAIL') as failed,
            COUNT(*) FILTER (WHERE status = 'WARN') as warnings,
            COUNT(DISTINCT seed) as seeds_checked,
            COUNT(*) FILTER (WHERE status = 'FAIL' AND category = 'scoring') as scoring_fails,
            COUNT(*) FILTER (WHERE status = 'FAIL' AND category = 'shop_joker') as shop_fails,
            COUNT(*) FILTER (WHERE status = 'FAIL' AND category = 'shop_contents') as shop_contents_fails
        FROM balatro_sim_validation WHERE batch_id = $1
    """, batch_id)
    if not row or (row["passed"] == 0 and row["failed"] == 0):
        return {"has_data": False}
    total = row["passed"] + row["failed"]
    return {
        "has_data": True,
        "passed": row["passed"],
        "failed": row["failed"],
        "warnings": row["warnings"],
        "seeds_checked": row["seeds_checked"],
        "accuracy": round(row["passed"] / total * 100, 1) if total > 0 else 0,
        "scoring_fails": row["scoring_fails"],
        "shop_fails": row["shop_fails"] + row["shop_contents_fails"],
    }


@app.get("/validation", response_class=HTMLResponse)
async def page_validation(request: Request):
    """Simulator validation overview page."""
    from datetime import timezone, timedelta
    sgt = timezone(timedelta(hours=8))

    # Get all batches that have validation data
    batches = await db_pool.fetch("""
        SELECT b.id, b.name, b.created_at,
            COUNT(*) FILTER (WHERE v.status = 'PASS') as passed,
            COUNT(*) FILTER (WHERE v.status = 'FAIL') as failed,
            COUNT(*) FILTER (WHERE v.status = 'WARN') as warnings,
            COUNT(DISTINCT v.seed) as seeds_checked,
            COUNT(*) FILTER (WHERE v.status = 'FAIL' AND v.category = 'scoring') as scoring_fails,
            COUNT(*) FILTER (WHERE v.status = 'FAIL' AND v.category LIKE 'shop%') as shop_fails
        FROM balatro_batches b
        JOIN balatro_sim_validation v ON v.batch_id = b.id
        GROUP BY b.id, b.name, b.created_at
        ORDER BY b.created_at DESC
    """)

    # Also get batches without validation for "run validation" button
    unvalidated = await db_pool.fetch("""
        SELECT b.id, b.name, b.created_at, b.seed_count
        FROM balatro_batches b
        LEFT JOIN balatro_sim_validation v ON v.batch_id = b.id
        WHERE v.id IS NULL
        AND EXISTS (SELECT 1 FROM balatro_batch_runs br WHERE br.batch_id = b.id AND br.status = 'completed')
        ORDER BY b.created_at DESC LIMIT 10
    """)

    h = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>模拟器验证 | Balatro Playground</title><style>{_base_css()}
.val-card{{background:var(--surface);border-radius:12px;padding:1.5rem;margin-bottom:1rem}}
.val-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:1rem;margin:1rem 0}}
.val-stat{{text-align:center;padding:.75rem;background:#1a1a2e;border-radius:8px}}
.val-stat .num{{font-size:1.5rem;font-weight:700}}
.val-stat .label{{font-size:.75rem;color:var(--muted);margin-top:.25rem}}
.accuracy-bar{{height:8px;background:#333;border-radius:4px;overflow:hidden;margin:.5rem 0}}
.accuracy-fill{{height:100%;border-radius:4px;transition:width .3s}}
</style></head><body>
{_header()}<div class="container">
<h2 style="margin-bottom:1.5rem">🔬 模拟器验证</h2>
<p style="color:var(--muted);margin-bottom:2rem">对比模拟器输出与真实游戏日志，追踪 shop 生成和 scoring 引擎的准确率</p>
"""

    if batches:
        h += '<div class="val-card"><h3 style="margin-bottom:1rem">已验证的批次</h3>'
        h += '<table class="run-table"><thead><tr><th>批次</th><th>种子数</th><th>准确率</th><th>通过</th><th>失败</th><th>Shop 差异</th><th>Scoring 差异</th><th>时间</th></tr></thead><tbody>'
        for b in batches:
            total = b["passed"] + b["failed"]
            acc = round(b["passed"] / total * 100, 1) if total > 0 else 0
            acc_color = "#4ade80" if acc >= 80 else "#fbbf24" if acc >= 50 else "#ef4444"
            ct = b["created_at"].astimezone(sgt).strftime("%m/%d %H:%M") if b.get("created_at") else ""
            bname = b["name"] or f"Batch #{b['id']}"
            h += f'<tr onclick="location.href=\'/balatro/validation/{b["id"]}\'" style="cursor:pointer">'
            h += f'<td><a href="/balatro/validation/{b["id"]}" style="color:var(--gold)">{_html_escape(bname)}</a></td>'
            h += f'<td>{b["seeds_checked"]}</td>'
            h += f'<td><span style="color:{acc_color};font-weight:700">{acc}%</span>'
            h += f'<div class="accuracy-bar"><div class="accuracy-fill" style="width:{acc}%;background:{acc_color}"></div></div></td>'
            h += f'<td style="color:#4ade80">{b["passed"]}</td>'
            h += f'<td style="color:#ef4444">{b["failed"]}</td>'
            h += f'<td>{b["shop_fails"]}</td><td>{b["scoring_fails"]}</td>'
            h += f'<td>{ct}</td></tr>'
        h += '</tbody></table></div>'

    if unvalidated:
        h += '<div class="val-card"><h3 style="margin-bottom:1rem">待验证的批次</h3>'
        h += '<p style="color:var(--muted);font-size:.85rem;margin-bottom:1rem">这些已完成的批次还没有运行模拟器验证</p>'
        h += '<table class="run-table"><thead><tr><th>批次</th><th>种子数</th><th>时间</th></tr></thead><tbody>'
        for b in unvalidated:
            ct = b["created_at"].astimezone(sgt).strftime("%m/%d %H:%M") if b.get("created_at") else ""
            bname = b["name"] or f"Batch #{b['id']}"
            h += f'<tr><td>{_html_escape(bname)}</td><td>{b["seed_count"]}</td><td>{ct}</td></tr>'
        h += '</tbody></table></div>'

    if not batches and not unvalidated:
        h += '<div class="val-card"><p style="color:var(--muted)">暂无验证数据。运行 <code>python3 sim_validator.py --batch-id N --save</code> 生成验证报告。</p></div>'

    h += '</div></body></html>'
    return HTMLResponse(h)


@app.get("/validation/{batch_id}", response_class=HTMLResponse)
async def page_validation_detail(batch_id: int):
    """Validation detail page for a specific batch."""
    from datetime import timezone, timedelta
    sgt = timezone(timedelta(hours=8))

    batch = await db_pool.fetchrow("SELECT * FROM balatro_batches WHERE id = $1", batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found")

    # Get validation results grouped by seed
    rows = await db_pool.fetch("""
        SELECT seed, category, ante, status, expected, actual, detail
        FROM balatro_sim_validation
        WHERE batch_id = $1
        ORDER BY seed, ante, category
    """, batch_id)

    # Summary stats
    summary = await db_pool.fetchrow("""
        SELECT
            COUNT(*) FILTER (WHERE status = 'PASS') as passed,
            COUNT(*) FILTER (WHERE status = 'FAIL') as failed,
            COUNT(*) FILTER (WHERE status = 'WARN') as warnings,
            COUNT(DISTINCT seed) as seeds_checked,
            COUNT(*) FILTER (WHERE status = 'FAIL' AND category = 'scoring') as scoring_fails,
            COUNT(*) FILTER (WHERE status = 'FAIL' AND category LIKE 'shop%') as shop_fails
        FROM balatro_sim_validation WHERE batch_id = $1
    """, batch_id)

    total = (summary["passed"] + summary["failed"]) if summary else 0
    acc = round(summary["passed"] / total * 100, 1) if total > 0 else 0
    acc_color = "#4ade80" if acc >= 80 else "#fbbf24" if acc >= 50 else "#ef4444"
    bname = batch["name"] or f"Batch #{batch_id}"

    h = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>验证: {_html_escape(bname)} | Balatro Playground</title><style>{_base_css()}
.val-card{{background:var(--surface);border-radius:12px;padding:1.5rem;margin-bottom:1rem}}
.val-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:1rem;margin:1rem 0}}
.val-stat{{text-align:center;padding:.75rem;background:#1a1a2e;border-radius:8px}}
.val-stat .num{{font-size:1.8rem;font-weight:700}}
.val-stat .label{{font-size:.75rem;color:var(--muted);margin-top:.25rem}}
.accuracy-bar{{height:10px;background:#333;border-radius:5px;overflow:hidden;margin:.5rem 0}}
.accuracy-fill{{height:100%;border-radius:5px}}
.seed-section{{margin-bottom:1.5rem}}
.seed-header{{font-weight:700;color:var(--gold);font-size:1rem;margin-bottom:.5rem;cursor:pointer}}
.check-row{{display:flex;align-items:center;gap:.75rem;padding:.4rem .75rem;font-size:.85rem;border-left:3px solid #333;margin-bottom:.25rem;background:#1a1a2e;border-radius:0 6px 6px 0}}
.check-row.pass{{border-left-color:#4ade80}}
.check-row.fail{{border-left-color:#ef4444}}
.check-row.warn{{border-left-color:#fbbf24}}
.check-badge{{font-size:.7rem;font-weight:700;padding:2px 6px;border-radius:4px;min-width:36px;text-align:center}}
.check-badge.pass{{background:#4ade8033;color:#4ade80}}
.check-badge.fail{{background:#ef444433;color:#ef4444}}
.check-badge.warn{{background:#fbbf2433;color:#fbbf24}}
</style></head><body>
{_header()}<div class="container">
<div style="margin-bottom:1rem"><a href="/balatro/validation" style="color:var(--gold);text-decoration:none">← 验证列表</a></div>
<h2 style="margin-bottom:.5rem">🔬 {_html_escape(bname)}</h2>

<div class="val-card">
<div class="val-grid">
<div class="val-stat"><div class="num" style="color:{acc_color}">{acc}%</div><div class="label">准确率</div></div>
<div class="val-stat"><div class="num">{summary["seeds_checked"] if summary else 0}</div><div class="label">种子数</div></div>
<div class="val-stat"><div class="num" style="color:#4ade80">{summary["passed"] if summary else 0}</div><div class="label">通过</div></div>
<div class="val-stat"><div class="num" style="color:#ef4444">{summary["failed"] if summary else 0}</div><div class="label">失败</div></div>
<div class="val-stat"><div class="num">{summary["shop_fails"] if summary else 0}</div><div class="label">Shop 差异</div></div>
<div class="val-stat"><div class="num">{summary["scoring_fails"] if summary else 0}</div><div class="label">Scoring 差异</div></div>
</div>
<div class="accuracy-bar"><div class="accuracy-fill" style="width:{acc}%;background:{acc_color}"></div></div>
</div>
"""

    # Group by seed
    seed_checks = {}
    for r in rows:
        s = r["seed"]
        if s not in seed_checks:
            seed_checks[s] = []
        seed_checks[s].append(r)

    for seed, checks in seed_checks.items():
        passed = sum(1 for c in checks if c["status"] == "PASS")
        failed = sum(1 for c in checks if c["status"] == "FAIL")
        total_s = passed + failed
        seed_acc = round(passed / total_s * 100) if total_s > 0 else 0
        seed_color = "#4ade80" if seed_acc >= 80 else "#fbbf24" if seed_acc >= 50 else "#ef4444"

        h += f'<div class="seed-section"><div class="seed-header">'
        h += f'<a href="/balatro/seed/{seed}" style="color:var(--gold)">{seed}</a>'
        h += f' <span style="color:{seed_color};font-size:.85rem;font-weight:400">{seed_acc}% ({passed}/{total_s})</span></div>'

        for c in checks:
            status = c["status"].lower()
            cat = c["category"]
            ante = c["ante"] or "-"
            detail = c["detail"] or ""
            if len(detail) > 120:
                detail = detail[:120] + "..."
            h += f'<div class="check-row {status}">'
            h += f'<span class="check-badge {status}">{c["status"]}</span>'
            h += f'<span style="color:var(--muted);min-width:80px">[{cat}] A{ante}</span>'
            h += f'<span>{_html_escape(detail)}</span></div>'

        h += '</div>'

    h += '</div></body></html>'
    return HTMLResponse(h)


@app.get("/", response_class=HTMLResponse)
async def page_list(request: Request):
    """Server-rendered run list page with tabs."""
    # Pagination params for all tabs
    per_page = 50
    games_page = int(request.query_params.get("gp", 1))
    strat_page = int(request.query_params.get("sp", 1))
    seeds_page = int(request.query_params.get("dp", 1))
    batch_page = int(request.query_params.get("bp", 1))
    seedset_page = int(request.query_params.get("ssp", 1))

    # Games tab
    games_total = await db_pool.fetchval("SELECT COUNT(*) FROM balatro_runs")
    games_offset = (games_page - 1) * per_page
    rows = await db_pool.fetch(
        """SELECT r.*, s.name as strategy_name, s.id as sid,
           br.batch_id as batch_id
           FROM balatro_runs r LEFT JOIN balatro_strategies s ON r.strategy_id = s.id
           LEFT JOIN balatro_batch_runs br ON r.batch_run_id = br.id
           ORDER BY r.played_at DESC NULLS LAST LIMIT $1 OFFSET $2""",
        per_page, games_offset
    )
    games_total_pages = max(1, (games_total + per_page - 1) // per_page)

    # Fetch score error stats per run
    score_stats = await db_pool.fetch(
        """SELECT run_id, COUNT(*) as cnt,
           AVG(ABS(score_error)) as avg_err,
           MAX(ABS(score_error)) as max_err
           FROM balatro_screenshots
           WHERE estimated_score IS NOT NULL AND actual_score IS NOT NULL
           GROUP BY run_id"""
    )
    score_map = {s["run_id"]: s for s in score_stats}

    # Fetch strategies for tab 2
    strat_total = await db_pool.fetchval("SELECT COUNT(*) FROM balatro_strategies")
    strat_offset = (strat_page - 1) * per_page
    strategies = await db_pool.fetch(
        """SELECT s.*,
           COUNT(r.id) as run_count,
           ROUND(AVG(r.final_ante)::numeric, 1) as avg_ante,
           CASE WHEN COUNT(r.id) > 0
                THEN ROUND((SUM(POWER(2, r.final_ante - 1)) / COUNT(r.id))::numeric, 1)
                ELSE NULL END as weighted_score,
           SUM(CASE WHEN r.won THEN 1 ELSE 0 END) as wins
           FROM balatro_strategies s
           LEFT JOIN balatro_runs r ON r.strategy_id = s.id
           GROUP BY s.id ORDER BY s.created_at DESC
           LIMIT $1 OFFSET $2""",
        per_page, strat_offset
    )
    strat_total_pages = max(1, (strat_total + per_page - 1) // per_page)

    # Fetch seeds for tab 3
    seeds_total = await db_pool.fetchval("SELECT COUNT(DISTINCT seed) FROM balatro_runs WHERE seed IS NOT NULL AND seed != ''")
    seeds_offset = (seeds_page - 1) * per_page
    seeds = await db_pool.fetch(
        """SELECT seed, COUNT(*) as run_count,
           array_agg(progress) as progresses,
           array_agg(final_ante) as antes,
           SUM(CASE WHEN won THEN 1 ELSE 0 END) as wins,
           COUNT(DISTINCT strategy_id) as strategy_count,
           MIN(played_at) as first_played
           FROM balatro_runs
           WHERE seed IS NOT NULL AND seed != ''
           GROUP BY seed ORDER BY run_count DESC
           LIMIT $1 OFFSET $2""",
        per_page, seeds_offset
    )
    seeds_total_pages = max(1, (seeds_total + per_page - 1) // per_page)

    # Fetch batches for tab 4 (with pagination)
    batch_total = await db_pool.fetchval("SELECT COUNT(*) FROM balatro_batches")
    batch_offset = (batch_page - 1) * per_page
    batch_rows = await db_pool.fetch(
        """SELECT b.id, b.name, b.seed_count, b.stop_after_ante, b.created_at,
           br.status as run_status, br.completed_runs, br.total_runs, br.stats,
           s.name as strategy_name, s.id as strategy_id,
           (SELECT ROUND(AVG(ABS(gl.estimated_score - gl.actual_score)::numeric / NULLIF(gl.actual_score, 0) * 100), 1)
            FROM balatro_game_log gl JOIN balatro_runs r3 ON gl.run_id = r3.id
            WHERE r3.batch_run_id = br.id AND gl.estimated_score IS NOT NULL AND gl.actual_score IS NOT NULL AND gl.actual_score > 0) as score_error,
           (SELECT array_agg(r4.progress) FROM balatro_runs r4 WHERE r4.batch_run_id = br.id AND r4.progress IS NOT NULL) as run_progresses,
           (SELECT array_agg(r5.final_ante) FROM balatro_runs r5 WHERE r5.batch_run_id = br.id AND r5.final_ante IS NOT NULL) as run_antes
           FROM balatro_batches b
           LEFT JOIN balatro_batch_runs br ON br.batch_id = b.id
           LEFT JOIN balatro_strategies s ON br.strategy_id = s.id
           ORDER BY b.created_at DESC LIMIT $1 OFFSET $2""",
        per_page, batch_offset
    )
    batch_total_pages = max(1, (batch_total + per_page - 1) // per_page)

    # Fetch seed sets for tab 5
    seedset_total = await db_pool.fetchval("SELECT COUNT(*) FROM balatro_seed_sets")
    seedset_offset = (seedset_page - 1) * per_page
    seed_sets = await db_pool.fetch(
        """SELECT ss.*,
           (SELECT COUNT(*) FROM balatro_batches b WHERE b.seed_set_id = ss.id) as batch_count
           FROM balatro_seed_sets ss
           ORDER BY ss.created_at DESC LIMIT $1 OFFSET $2""",
        per_page, seedset_offset
    )
    seedset_total_pages = max(1, (seedset_total + per_page - 1) // per_page)

    from datetime import timezone, timedelta
    sgt = timezone(timedelta(hours=8))

    h = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Balatro Playground 🃏</title><style>{_base_css()}
.tabs{{display:flex;gap:0;margin-bottom:1.5rem;border-bottom:2px solid #333}}
.tab{{padding:.6rem 1.5rem;cursor:pointer;font-size:1rem;font-weight:600;color:var(--muted);border-bottom:2px solid transparent;margin-bottom:-2px;transition:all .15s}}
.tab:hover{{color:var(--text)}}
.tab.active{{color:var(--gold);border-bottom-color:var(--gold)}}
.tab-content{{display:none}}.tab-content.active{{display:block}}
</style></head><body>
{_header()}<div class="container">
<div class="tabs">
<div class="tab active" onclick="switchTab('games')">🎮 运行 ({games_total})</div>
<div class="tab" onclick="switchTab('batches')">📊 批量 ({batch_total})</div>
<div class="tab" onclick="switchTab('seeds')">🌱 种子 ({seeds_total})</div>
<div class="tab" onclick="switchTab('seedsets')">📦 种子集 ({seedset_total})</div>
<div class="tab" onclick="switchTab('strategies')">🧠 策略 ({strat_total})</div>
</div>
<div id="tab-games" class="tab-content active">
<table class="run-table sortable"><thead><tr><th>编号</th><th>进度</th><th>策略</th><th>种子</th><th>Batch</th><th>出牌</th><th>弃牌</th><th>估分误差</th><th>耗时</th><th>时间</th></tr></thead><tbody>"""

    for r in rows:
        rc = r["run_code"] or str(r["id"])
        if r["status"] == "running":
            progress_cell = '<span class="badge running">运行中</span>'
        elif r.get("won"):
            progress_cell = '<span class="badge win">通关</span>'
        else:
            pn = _format_progress_numeric(r.get("progress"), r.get("final_ante"))
            cls = "win" if r["status"] == "completed" else "loss"
            progress_cell = f'<span class="badge {cls}">{pn}</span>'

        seed = r.get("seed") or "-"
        if len(seed) > 8:
            seed = seed[:8]
        dur = f'{round(r["duration_seconds"] / 60)}m' if r.get("duration_seconds") else "-"
        t = r["played_at"].astimezone(sgt).strftime("%m/%d %H:%M") if r.get("played_at") else ""

        ss = score_map.get(r["id"])
        if ss and ss["cnt"] > 0:
            avg_e = float(ss["avg_err"] or 0) * 100
            max_e = float(ss["max_err"] or 0) * 100
            err_cls = "good" if avg_e < 20 else ("ok" if avg_e < 50 else "bad")
            err_cell = f'<span class="score-err {err_cls}">均{avg_e:.0f}% 峰{max_e:.0f}% ({ss["cnt"]}手)</span>'
        else:
            err_cell = "-"

        sname = r.get("strategy_name") or "-"
        sid = r.get("sid")
        strategy_cell = f'<a href="/balatro/strategy/{sid}" onclick="event.stopPropagation()" style="color:var(--gold);font-size:.8rem">{_html_escape(sname)}</a>' if sid else "-"

        # Batch info
        batch_id = r.get("batch_id")
        batch_cell = f'<a href="/balatro/batch/{batch_id}" onclick="event.stopPropagation()" style="color:var(--gold);font-size:.8rem">B{batch_id}</a>' if batch_id else "-"

        # Clickable seed
        seed_cell = f'<a href="/balatro/seed/{seed}" onclick="event.stopPropagation()" style="font-family:monospace;font-size:.8rem;color:var(--muted)">{seed}</a>' if seed != "-" else "-"

        h += f'<tr onclick="location.href=\'/balatro/game/{rc}\'" style="cursor:pointer">'
        h += f'<td class="run-code">{rc}</td><td>{progress_cell}</td><td>{strategy_cell}</td><td>{seed_cell}</td>'
        h += f'<td>{batch_cell}</td>'
        h += f'<td>{r.get("hands_played", 0)}</td><td>{r.get("discards_used", 0)}</td>'
        h += f'<td>{err_cell}</td><td>{dur}</td><td>{t}</td></tr>'

    h += "</tbody></table>"
    h += _pagination_html(games_page, games_total_pages, "gp", "games")
    h += "</div>"

    # Batch tab (tab 2)
    h += '<div id="tab-batches" class="tab-content">'
    h += '<table class="run-table sortable"><thead><tr><th>编号</th><th>种子数</th><th>策略</th><th>状态</th><th data-tooltip="sum(2^(ante-1)) / N">加权分</th><th>平均Ante</th><th>最高Ante</th><th>估分误差</th><th>耗时</th><th>时间</th></tr></thead><tbody>'
    for b in batch_rows:
        bid = b["id"]
        bseeds = b["seed_count"]
        bstatus = b["run_status"] or "pending"
        bstats = json.loads(b["stats"]) if isinstance(b["stats"], str) else (b["stats"] or {})
        # Compute normalized avg/max from run progress data
        progresses = b.get("run_progresses") or []
        antes = b.get("run_antes") or []
        norm_values = []
        for i, p in enumerate(progresses):
            fa = antes[i] if i < len(antes) else None
            v = _progress_to_numeric(p, fa)
            if v is not None:
                norm_values.append(v)
        # Fallback: use antes directly if no progress data
        if not norm_values and antes:
            norm_values = [float(a) for a in antes if a]
        bavg = round(sum(norm_values) / len(norm_values), 1) if norm_values else "-"
        bws = round(sum(2 ** (v - 1) for v in norm_values) / len(norm_values), 1) if norm_values else "-"
        bmax = max(norm_values) if norm_values else "-"
        if isinstance(bmax, float):
            bmax = f'{bmax:.1f}' if bmax != int(bmax) else f'{int(bmax)}.0'
        bdur = bstats.get("duration_seconds")
        bdur_str = f"{round(bdur / 60, 1)}min" if bdur else "-"
        bcreated = b["created_at"].astimezone(sgt).strftime("%m/%d %H:%M") if b["created_at"] else ""
        if bstatus == "completed":
            bbadge = '<span class="badge win">完成</span>'
        elif bstatus == "running":
            bbadge = '<span class="badge running">运行中</span>'
        else:
            bbadge = f'<span class="badge loss">{bstatus}</span>'
        # Clickable strategy
        bsid = b.get("strategy_id")
        bsname = b.get("strategy_name") or "-"
        bstrat_cell = f'<a href="/balatro/strategy/{bsid}" onclick="event.stopPropagation()" style="color:var(--gold);font-size:.85rem">{_html_escape(bsname)}</a>' if bsid else "-"
        # Score error
        berr = f'{b["score_error"]}%' if b.get("score_error") is not None else "-"
        h += f'<tr onclick="location.href=\'/balatro/batch/{bid}\'" style="cursor:pointer">'
        h += f'<td class="run-code">batch-{bid}</td><td>{bseeds}</td><td>{bstrat_cell}</td><td>{bbadge}</td>'
        h += f'<td>{bws}</td><td>{bavg}</td><td>{bmax}</td><td>{berr}</td><td>{bdur_str}</td><td>{bcreated}</td></tr>'
    h += '</tbody></table>'
    h += _pagination_html(batch_page, batch_total_pages, "bp", "batches")
    h += '</div>'

    # Seeds tab (tab 3)
    h += """<div id="tab-seeds" class="tab-content">
<table class="run-table sortable"><thead><tr><th>种子</th><th>运行次数</th><th>策略数</th><th>最佳Ante</th><th data-tooltip="sum(2^(ante-1)) / N">加权分</th><th>胜率</th><th>首次使用</th></tr></thead><tbody>"""

    for sd in seeds:
        seed_val = sd["seed"] or "-"
        rc = sd["run_count"] or 0
        sc = sd["strategy_count"] or 0
        # Compute normalized best/avg from progress data
        sd_progresses = sd.get("progresses") or []
        sd_antes = sd.get("antes") or []
        sd_norm = []
        for i, p in enumerate(sd_progresses):
            fa = sd_antes[i] if i < len(sd_antes) else None
            v = _progress_to_numeric(p, fa)
            if v is not None:
                sd_norm.append(v)
        if not sd_norm and sd_antes:
            sd_norm = [float(a) for a in sd_antes if a]
        ba = f'{max(sd_norm):.1f}' if sd_norm else "-"
        sd_ws = f'{round(sum(2 ** (v - 1) for v in sd_norm) / len(sd_norm), 1)}' if sd_norm else "-"
        wins = sd["wins"] or 0
        wr = f"{round(wins / rc * 100)}%" if rc > 0 else "-"
        fp = sd["first_played"].astimezone(sgt).strftime("%m/%d %H:%M") if sd.get("first_played") else ""
        h += f'<tr onclick="location.href=\'/balatro/seed/{seed_val}\'" style="cursor:pointer">'
        h += f'<td class="run-code" style="font-family:monospace">{seed_val}</td>'
        h += f'<td>{rc}</td><td>{sc}</td><td>{ba}</td><td>{sd_ws}</td><td>{wr}</td><td>{fp}</td></tr>'

    h += "</tbody></table>"
    h += _pagination_html(seeds_page, seeds_total_pages, "dp", "seeds")
    h += "</div>"

    # Seed Sets tab (tab 4)
    h += '<div id="tab-seedsets" class="tab-content">'
    h += '<table class="run-table"><thead><tr><th>名称</th><th>种子数</th><th>评级分布</th><th>批量次数</th><th>描述</th><th>创建时间</th></tr></thead><tbody>'
    for ss in seed_sets:
        ssid = ss["id"]
        ssname = ss["name"] or f"种子集 #{ssid}"
        sscount = ss["seed_count"]
        ssbatches = ss["batch_count"] or 0
        ssdesc = (ss.get("description") or "-")[:60]
        sscreated = ss["created_at"].astimezone(sgt).strftime("%m/%d %H:%M") if ss.get("created_at") else ""
        # Tier distribution mini-bar
        ss_tiers_raw = ss.get("seed_tiers")
        ss_tiers = json.loads(ss_tiers_raw) if isinstance(ss_tiers_raw, str) else (ss_tiers_raw or {})
        tier_cell = "-"
        if ss_tiers:
            tc = {}
            for _sd, _ti in ss_tiers.items():
                t = _ti.get("tier", "?") if isinstance(_ti, dict) else "?"
                tc[t] = tc.get(t, 0) + 1
            _tc = {"S": "#e74c3c", "A": "#e67e22", "B": "#3498db", "C": "#95a5a6"}
            parts = []
            for t in ["S", "A", "B", "C"]:
                if tc.get(t, 0) > 0:
                    parts.append(f'<span style="color:{_tc[t]};font-weight:600">{t}:{tc[t]}</span>')
            tier_cell = " ".join(parts)
        h += f'<tr onclick="location.href=\'/balatro/seedset/{ssid}\'" style="cursor:pointer">'
        h += f'<td>{_html_escape(ssname)}</td><td>{sscount}</td><td style="font-size:.85rem">{tier_cell}</td><td>{ssbatches}</td>'
        h += f'<td style="color:var(--muted);font-size:.85rem">{_html_escape(ssdesc)}</td><td>{sscreated}</td></tr>'
    h += '</tbody></table>'
    if seedset_total == 0:
        h += '<p style="color:var(--muted);padding:2rem;text-align:center">还没有种子集。通过 API 或批量运行创建。</p>'
    h += _pagination_html(seedset_page, seedset_total_pages, "ssp", "seedsets")
    h += '</div>'

    # Strategies tab (tab 5)
    h += """<div id="tab-strategies" class="tab-content">
<table class="run-table sortable"><thead><tr><th>策略名</th><th>哈希</th><th>局数</th><th>胜率</th><th data-tooltip="sum(2^(ante-1)) / N">加权分</th><th>平均Ante</th><th>演进自</th><th>创建时间</th></tr></thead><tbody>"""

    for st in strategies:
        sname = st.get("name") or "未命名"
        chash = (st.get("code_hash") or "-")[:8]
        rc = st.get("run_count") or 0
        wins = st.get("wins") or 0
        wr = f"{round(wins / rc * 100)}%" if rc > 0 else "-"
        aa = st.get("avg_ante") or "-"
        # Weighted score from query
        sws = st.get("weighted_score") or "-"
        parent = ""
        if st.get("parent_id"):
            parent = f'<a href="/balatro/strategy/{st["parent_id"]}" style="color:var(--muted);font-size:.8rem">← 父策略</a>'
        ct = st["created_at"].astimezone(sgt).strftime("%m/%d %H:%M") if st.get("created_at") else ""
        h += f'<tr onclick="location.href=\'/balatro/strategy/{st["id"]}\'" style="cursor:pointer">'
        h += f'<td class="run-code">{_html_escape(sname)}</td><td style="font-family:monospace;font-size:.8rem;color:var(--muted)">{chash}</td>'
        h += f'<td>{rc}</td><td>{wr}</td><td>{sws}</td><td>{aa}</td><td>{parent}</td><td>{ct}</td></tr>'

    h += "</tbody></table>"
    h += _pagination_html(strat_page, strat_total_pages, "sp", "strategies")
    h += '</div>'

    h += """
<script>
var tabs=['games','batches','seeds','seedsets','strategies'];
function switchTab(name){
  document.querySelectorAll('.tab').forEach(function(t,i){t.classList.toggle('active',tabs[i]===name)});
  tabs.forEach(function(n){document.getElementById('tab-'+n).classList.toggle('active',n===name)});
}
var h=location.hash.replace('#','');if(tabs.indexOf(h)>=0)switchTab(h);

// Sortable tables
document.querySelectorAll('table.sortable').forEach(function(table){
  var headers=table.querySelectorAll('th');
  headers.forEach(function(th,colIdx){
    th.addEventListener('click',function(){
      var tbody=table.querySelector('tbody');
      var rows=Array.from(tbody.querySelectorAll('tr'));
      var asc=!th.classList.contains('sort-asc');
      headers.forEach(function(h){h.classList.remove('sort-asc','sort-desc')});
      th.classList.add(asc?'sort-asc':'sort-desc');
      rows.sort(function(a,b){
        var at=a.cells[colIdx].textContent.trim();
        var bt=b.cells[colIdx].textContent.trim();
        var an=parseFloat(at.replace(/[^0-9.\-]/g,''));
        var bn=parseFloat(bt.replace(/[^0-9.\-]/g,''));
        if(!isNaN(an)&&!isNaN(bn))return asc?an-bn:bn-an;
        return asc?at.localeCompare(bt):bt.localeCompare(at);
      });
      rows.forEach(function(r){tbody.appendChild(r)});
    });
  });
});
</script>
</div></body></html>"""
    return HTMLResponse(h)
