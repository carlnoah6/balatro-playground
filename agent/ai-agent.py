#!/usr/bin/env python3
"""Balatro AI Agent - LLM-assisted player via TCP ai-mod protocol.

Integrates with api-proxy for complex decisions (joker selection, shop purchases,
discard strategy). Sends key screenshots to Lark group as a visual timeline.
"""

import base64, json, os, signal, socket, subprocess, sys, time, traceback
import threading, queue
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone, timedelta

SGT = timezone(timedelta(hours=8))

def now_sgt():
    return datetime.now(SGT)

_stop_requested = False

def _exit_handler(signum, frame):
    global _stop_requested
    print(f"[agent] 收到信号 {signum}，标记退出", flush=True)
    _stop_requested = True

signal.signal(signal.SIGTERM, _exit_handler)
signal.signal(signal.SIGHUP, _exit_handler)
signal.signal(signal.SIGPIPE, signal.SIG_IGN)
from pathlib import Path

import requests

# Decision engine (v2)
from decision.engine import DecisionEngine, Decision
from decision.scoring import Card, Joker
from evaluation.live import LiveEvaluator

# --- Configuration ---
SCREENSHOT_DIR = os.environ.get("SCREENSHOT_DIR", "/home/ubuntu/balatro-env/screenshots")
HOST = os.environ.get("BALATRO_HOST", "127.0.0.1")
PORT = int(os.environ.get("BALATRO_PORT", "12345"))

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:8180/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "sk-luna-2026-openclaw")
LLM_MODEL = os.environ.get("LLM_MODEL", "gemini-2.5-flash")

LARK_APP_ID = os.environ.get("LARK_APP_ID", "cli_a90c3a6163785ed2")
LARK_APP_SECRET = os.environ.get("LARK_APP_SECRET", "IpWX3GqEgSDYfDVD8ICUedxjfbIanr7O")
LARK_TIMELINE_CHAT = os.environ.get("LARK_TIMELINE_CHAT", "oc_7f3ebd31a5cf2fec9170952b29eb2700")
LARK_BASE_URL = "https://open.larksuite.com/open-apis"

# LLM usage: only for complex decisions (shop, joker, boss blind)
USE_LLM = os.environ.get("USE_LLM", "1") == "1"

CTRL_PORT = int(os.environ.get("CTRL_PORT", "12380"))

# ============================================================
# Async Lark Send Queue
# ============================================================

_lark_queue: queue.Queue = queue.Queue()
_lark_thread: threading.Thread | None = None

def _lark_sender_loop():
    """Background thread that drains the send queue."""
    while True:
        try:
            task = _lark_queue.get(timeout=5)
        except queue.Empty:
            continue
        if task is None:  # poison pill
            break
        try:
            fn, args, kwargs = task
            fn(*args, **kwargs)
        except Exception as e:
            print(f"[lark-async] Error: {e}")
        finally:
            _lark_queue.task_done()

def start_lark_sender():
    global _lark_thread
    _lark_thread = threading.Thread(target=_lark_sender_loop, daemon=True, name="lark-sender")
    _lark_thread.start()

def lark_async(fn, *args, **kwargs):
    """Enqueue a Lark API call for async execution. Skipped in batch mode."""
    if os.environ.get("BATCH_RUN_ID"):
        return
    _lark_queue.put((fn, args, kwargs))


def lark_verbose(fn, *args, **kwargs):
    """Like lark_async but only sends if LARK_VERBOSE is on. Skipped in batch mode."""
    if os.environ.get("BATCH_RUN_ID"):
        return
    if LARK_VERBOSE:
        _lark_queue.put((fn, args, kwargs))

# ============================================================
# HTTP Control Server
# ============================================================

_ctrl_queue: queue.Queue = queue.Queue()

class CtrlHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8", errors="replace").strip() if length else ""
        path = self.path.rstrip("/")

        if path == "/stop":
            _ctrl_queue.put("stop")
            self._ok("stopping")
        elif path == "/pause":
            _ctrl_queue.put("pause")
            self._ok("pausing")
        elif path == "/resume":
            _ctrl_queue.put("resume")
            self._ok("resuming")
        elif path == "/msg":
            _ctrl_queue.put(f"msg:{body}")
            self._ok("message queued")
        elif path == "/status":
            self._ok("running")
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found")

    def do_GET(self):
        if self.path.rstrip("/") == "/status":
            self._ok("running")
        else:
            self.send_response(404)
            self.end_headers()

    def _ok(self, msg):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(msg.encode())

    def log_message(self, format, *args):
        pass  # suppress access logs

def start_ctrl_server():
    server = HTTPServer(("0.0.0.0", CTRL_PORT), CtrlHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True, name="ctrl-http")
    t.start()
    print(f"[ctrl] HTTP 控制端口: {CTRL_PORT} (POST /stop /pause /resume /msg)")
    return server

def check_control():
    """Check for control commands from HTTP or file."""
    # Check HTTP queue first
    try:
        cmd = _ctrl_queue.get_nowait()
        print(f"[ctrl] 收到控制命令: {cmd}")
        return cmd
    except queue.Empty:
        pass
    # Fall back to file control
    try:
        if os.path.exists(CTRL_FILE):
            with open(CTRL_FILE, "r") as f:
                cmd = f.read().strip()
            os.remove(CTRL_FILE)
            if cmd:
                print(f"[ctrl] 收到文件控制命令: {cmd}")
                return cmd
    except Exception:
        pass
    return None

class BalatroConnection:
    def __init__(self, host, port):
        self.host, self.port = host, port
        self.sock, self.buf = None, b""
        self._connected = False

    def connect(self, retries=30, delay=2.0):
        for i in range(1, retries + 1):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(10)
                s.connect((self.host, self.port))
                self.sock = s
                self.buf = b""
                self._connected = True
                print(f"[agent] 已连接到 {self.host}:{self.port}")
                return
            except OSError as e:
                print(f"[agent] Attempt {i}/{retries}: {e}")
                time.sleep(delay)
        raise ConnectionError(f"Cannot reach {self.host}:{self.port}")

    def reconnect(self, retries=60, delay=3.0):
        """Reconnect after connection loss. Waits longer for container restart."""
        print(f"[agent] 连接断开，尝试重连...")
        self._connected = False
        if self.sock:
            try: self.sock.close()
            except: pass
            self.sock = None
        self.buf = b""
        for i in range(1, retries + 1):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(10)
                s.connect((self.host, self.port))
                self.sock = s
                self._connected = True
                print(f"[agent] 重连成功 (第{i}次尝试)")
                return True
            except OSError as e:
                if i % 10 == 0:
                    print(f"[agent] 重连中... {i}/{retries}: {e}")
                time.sleep(delay)
        print(f"[agent] 重连失败，放弃")
        return False

    def send_cmd(self, cmd, timeout=15.0):
        if not self._connected:
            raise ConnectionError("Not connected")
        self.sock.settimeout(timeout)
        self.sock.sendall((cmd.strip() + "\n").encode())
        # Read until we get a complete line
        while b"\n" not in self.buf:
            chunk = self.sock.recv(16384)
            if not chunk:
                self._connected = False
                raise ConnectionError("Connection closed")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        try:
            return json.loads(line.decode())
        except json.JSONDecodeError as e:
            # Log but don't crash — return error dict so caller can retry
            print(f"[agent] JSON 解析失败: {e} (len={len(line)})")
            return {"ok": False, "error": "json_parse_error"}

    def close(self):
        if self.sock:
            self.sock.close()


# ============================================================
# Lark Integration (image upload + message)
# ============================================================

_lark_token_cache = {"token": None, "expires": 0}

def get_lark_token():
    """Get tenant access token, cached."""
    now = time.time()
    if _lark_token_cache["token"] and now < _lark_token_cache["expires"]:
        return _lark_token_cache["token"]
    if not LARK_APP_SECRET:
        print("[lark] No LARK_APP_SECRET, skipping Lark integration")
        return None
    try:
        r = requests.post(
            f"{LARK_BASE_URL}/auth/v3/tenant_access_token/internal",
            json={"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET},
            timeout=10,
        )
        data = r.json()
        token = data.get("tenant_access_token")
        if token:
            _lark_token_cache["token"] = token
            _lark_token_cache["expires"] = now + data.get("expire", 7000)
        return token
    except Exception as e:
        print(f"[lark] Token error: {e}")
        return None


def lark_upload_image(path: str) -> str | None:
    """Upload image to Lark, return image_key."""
    token = get_lark_token()
    if not token:
        return None
    try:
        with open(path, "rb") as f:
            r = requests.post(
                f"{LARK_BASE_URL}/im/v1/images",
                headers={"Authorization": f"Bearer {token}"},
                data={"image_type": "message"},
                files={"image": f},
                timeout=30,
            )
        data = r.json()
        if data.get("code") == 0:
            key = data["data"]["image_key"]
            print(f"[lark] Uploaded {path} -> {key}")
            return key
        print(f"[lark] Upload failed: {data}")
    except Exception as e:
        print(f"[lark] Upload error: {e}")
    return None


def lark_send_text(chat_id: str, text: str):
    """Send text message to Lark group. Skipped in batch mode."""
    if os.environ.get("BATCH_RUN_ID"):
        return
    token = get_lark_token()
    if not token:
        return
    try:
        requests.post(
            f"{LARK_BASE_URL}/im/v1/messages?receive_id_type=chat_id",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json={
                "receive_id": chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}),
            },
            timeout=10,
        )
    except Exception as e:
        print(f"[lark] Send text error: {e}")


def lark_send_image(chat_id: str, image_key: str, caption: str = ""):
    """Send image message to Lark group, with optional text caption sent first."""
    token = get_lark_token()
    if not token:
        return
    if caption:
        lark_send_text(chat_id, caption)
    try:
        requests.post(
            f"{LARK_BASE_URL}/im/v1/messages?receive_id_type=chat_id",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json={
                "receive_id": chat_id,
                "msg_type": "image",
                "content": json.dumps({"image_key": image_key}),
            },
            timeout=10,
        )
    except Exception as e:
        print(f"[lark] Send image error: {e}")


MAX_SCREENSHOTS = int(os.environ.get("MAX_SCREENSHOTS", "0"))  # 0 = unlimited
STOP_AFTER_ANTE = int(os.environ.get("STOP_AFTER_ANTE", "0"))  # 0 = don't stop; N = stop after completing ante N
FAST_MODE = os.environ.get("FAST_MODE", "0") == "1"
LARK_VERBOSE = os.environ.get("LARK_VERBOSE", "1") == "1"  # 0 = silent (only final link), 1 = full Lark output
_screenshot_count = 0
_conn_ref = None  # set in run()

# DB integration
_db_run_id = None  # Neon DB row id
_run_code = None   # e.g. "20260219-001"
_game_logger = None  # GameLogger instance
try:
    from run_db import generate_run_code, create_run, update_run, add_screenshot, add_round, finalize_run, register_strategy, link_run_strategy
    from game_logger import GameLogger, format_cards as fmt_cards, format_card
    DB_ENABLED = True
except ImportError:
    DB_ENABLED = False
    print("[agent] run_db not available, DB recording disabled")

# Async screenshot pipeline: game thread just fires screenshot command,
# background thread does docker cp + upload with delay
_screenshot_queue = queue.Queue()

def _screenshot_worker():
    """Background thread: pick up screenshot jobs, docker cp with delay, upload."""
    while True:
        job = _screenshot_queue.get()
        if job is None:
            break
        save_file, host_path, caption, count_str = job
        try:
            # Wait a bit for LÖVE to finish writing the file
            time.sleep(0.5)
            # Retry docker cp
            copied = False
            for attempt in range(5):
                try:
                    subprocess.run(
                        ["docker", "cp", f"balatro-dev:{save_file}", host_path],
                        timeout=10, check=True, capture_output=True,
                    )
                    copied = True
                    break
                except subprocess.CalledProcessError:
                    time.sleep(0.3)
            if not copied:
                print(f"[截图] cp失败: {os.path.basename(host_path)}")
                _screenshot_queue.task_done()
                continue
            # Copy to runs/{run_code}/ for web serving
            if _run_code:
                run_dir = os.path.join(os.path.dirname(host_path), "..", "runs", _run_code, "screenshots")
                os.makedirs(run_dir, exist_ok=True)
                import shutil
                try:
                    dest = os.path.join(run_dir, os.path.basename(host_path))
                    shutil.copy2(host_path, dest)
                    os.chmod(dest, 0o644)
                    # Ensure dirs are world-readable for nginx
                    for d in [run_dir, os.path.dirname(run_dir)]:
                        os.chmod(d, 0o755)
                except Exception:
                    pass
            # Upload to Lark
            if LARK_APP_SECRET and LARK_VERBOSE:
                ik = lark_upload_image(host_path)
                if ik:
                    lark_send_image(LARK_TIMELINE_CHAT, ik, caption)
        except Exception as e:
            print(f"[截图] 后台错误: {e}")
        _screenshot_queue.task_done()

_screenshot_thread = threading.Thread(target=_screenshot_worker, daemon=True)
_screenshot_thread.start()

def screenshot_and_post(label: str, caption: str = ""):
    """Take screenshot via LÖVE's captureScreenshot, queue async cp+upload."""
    # In batch/fast/turbo mode, skip screenshots entirely
    if os.environ.get("NO_SCREENSHOTS") == "1":
        return None
    if os.environ.get("TURBO_MODE") == "1":
        return None
    if os.environ.get("BATCH_RUN_ID"):
        return None
    if FAST_MODE:
        if caption and LARK_APP_SECRET:
            lark_verbose(lark_send_text, LARK_TIMELINE_CHAT, caption)
        return None
    global _screenshot_count
    if MAX_SCREENSHOTS > 0 and _screenshot_count >= MAX_SCREENSHOTS:
        return None
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    ts = now_sgt().strftime("%Y%m%d_%H%M%S")
    fname = f"{ts}_{_screenshot_count:03d}_{label}.png"
    host_path = os.path.join(SCREENSHOT_DIR, fname)
    try:
        if _conn_ref:
            resp = _conn_ref.send_cmd(f"screenshot {fname}")
            if not resp.get("ok"):
                print(f"[截图] mod 截图失败: {resp}")
                return None
            save_file = resp.get("file", "")
            _screenshot_count += 1
            # Record to DB
            if DB_ENABLED and _db_run_id:
                try:
                    add_screenshot(_db_run_id, _screenshot_count, fname, caption,
                                   event_type=label, source="", detail=None)
                except Exception as e:
                    print(f"[db] screenshot record failed: {e}")
            # Also copy to runs/{run_code}/ for web serving
            if _run_code:
                run_dir = os.path.join(SCREENSHOT_DIR, "..", "runs", _run_code, "screenshots")
                os.makedirs(run_dir, exist_ok=True)
            # Queue for async cp + upload (don't block game loop at all)
            _screenshot_queue.put((save_file, host_path, caption, f"{_screenshot_count}/{MAX_SCREENSHOTS or '∞'}"))
            return host_path
    except Exception as e:
        print(f"[截图] 失败: {e}")
        return None
    return None



# ============================================================
# Game Logic
# ============================================================

def wait_state(conn, targets, timeout=20):
    """Poll until game reaches one of target states."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = conn.send_cmd("state")
        if st.get("state") in targets:
            return st
        time.sleep(0.2)
    return conn.send_cmd("state")


BLIND_NAMES_CN = {"Small": "小盲", "Big": "大盲", "Boss": "Boss"}

def handle_selecting_hand(conn, state, stats, engine: DecisionEngine, evaluator: LiveEvaluator, blind_name: str = ""):
    """Handle the card playing phase using the decision engine."""
    t_step = time.time()
    blind_name = BLIND_NAMES_CN.get(blind_name, blind_name)
    hand = state.get("hand_cards", [])
    if isinstance(hand, dict):
        hand = list(hand.values()) if hand else []
    ante = state.get("ante", 1)

    if not hand:
        time.sleep(1)
        return

    # Fetch draw pile for search-based decisions
    try:
        deck_info = conn.send_cmd("deck_info")
        if isinstance(deck_info, dict) and deck_info.get("ok"):
            from decision.scoring import Card as SCard
            draw_pile = []
            for c in deck_info.get("draw_pile", []):
                draw_pile.append(SCard(
                    rank=c.get("value", "?"),
                    suit=c.get("suit", "?"),
                    enhancement=c.get("enhancement", "") if c.get("enhancement", "") not in ("Default Base", "Base", "") else "",
                    edition=c.get("edition", ""),
                    seal=c.get("seal", ""),
                ))
            engine.set_draw_pile(draw_pile)
            print(f"[agent] deck_info: {len(draw_pile)} cards in draw pile", flush=True)
        else:
            engine.set_draw_pile([])
            print(f"[agent] deck_info failed: {deck_info}", flush=True)
    except Exception as e:
        engine.set_draw_pile([])
        print(f"[agent] deck_info error: {e}", flush=True)

    t_decide = time.time()
    decision = engine.decide_hand(state)
    t_decide = time.time() - t_decide
    cards = decision.params.get("cards", [])

    if decision.action == "discard" and cards:
        # Validate indices
        if all(0 <= i < len(hand) for i in cards):
            sel = " ".join(str(x + 1) for x in cards)
            conn.send_cmd(f"select {sel}")
            time.sleep(0.1)
            resp = conn.send_cmd("discard")
            stats["discards"] += 1
            src = "LLM" if decision.source == "llm" else "Rule"; stats["llm_decisions" if decision.source == "llm" else "rule_decisions"] += 1
            t_total = time.time() - t_step
            print(f"[agent] [{src}] 弃牌 {cards}: {decision.reasoning} [decide={t_decide:.1f}s total={t_total:.1f}s]")
            if _game_logger:
                discarded = [hand[i] for i in cards if i < len(hand)]
                _game_logger.log_discard(state, hand, discarded, src.lower(), decision.reasoning)
            evaluator.record_discard(
                ante, cards,
                was_llm=(decision.source == "llm"),
                reasoning=decision.reasoning,
                hands_left=state.get("hands_left", 0),
                discards_left=state.get("discards_left", 0),
            )
            screenshot_and_post(
                f"discard_a{ante}",
                f"🃏 第{ante}关{blind_name} | 弃牌[{src}]: {decision.reasoning}"
            )
            time.sleep(0.3)
            wait_state(conn, ["SELECTING_HAND", "SHOP", "GAME_OVER"], timeout=15)
            return

    # Play hand
    if not cards:
        cards = list(range(min(5, len(hand))))

    if all(0 <= i < len(hand) for i in cards):
        chips_before = state.get("chips", 0)
        estimated = int(decision.score_estimate or 0)
        sel = " ".join(str(x + 1) for x in cards)
        conn.send_cmd(f"select {sel}")
        time.sleep(0.1)
        resp = conn.send_cmd("play")
        stats["hands"] += 1
        src = "LLM" if decision.source == "llm" else "Rule"; stats["llm_decisions" if decision.source == "llm" else "rule_decisions"] += 1

        t_total = time.time() - t_step
        hand_type_str = decision.hand_type or "Unknown"
        print(f"[agent] [{src}] 出牌 {cards}: {decision.reasoning} [decide={t_decide:.1f}s total={t_total:.1f}s]")

        evaluator.record_play(
            ante, hand_type_str,
            cards,
            score=decision.score_estimate,
            target=state.get("blind_chips", 0),
            hands_left=state.get("hands_left", 0),
            discards_left=state.get("discards_left", 0),
        )

        screenshot_and_post(
            f"play_a{ante}",
            f"🎴 第{ante}关{blind_name} | 出牌[{src}]: {decision.reasoning}",
        )
        time.sleep(0.3)
        wait_state(conn, ["SELECTING_HAND", "SHOP", "BLIND_SELECT", "GAME_OVER"], timeout=20)

        # Read actual chips AFTER scoring animation completes (state has changed)
        post_st = conn.send_cmd("state")
        chips_after = post_st.get("chips", 0) if post_st else 0
        actual_gained = chips_after - chips_before
        # Log play to game log
        if _game_logger:
            played = [hand[i] for i in cards if i < len(hand)]
            _game_logger.log_play(state, hand, played, cards,
                                  hand_type_str, estimated, actual_gained if actual_gained > 0 else estimated,
                                  src.lower(), decision.reasoning)
        if estimated > 0 and actual_gained > 0:
            error_ratio = (actual_gained / estimated - 1.0)
            print(f"[agent] 📊 估分={estimated} 实际={actual_gained} 误差={error_ratio:+.0%}")
            # Update the last screenshot record in DB with score data
            if DB_ENABLED and _db_run_id:
                try:
                    from run_db import _get_conn
                    _conn_db = _get_conn()
                    _cur = _conn_db.cursor()
                    _cur.execute(
                        """UPDATE balatro_screenshots SET estimated_score=%s, actual_score=%s,
                           score_error=%s, hand_type=%s, chips_before=%s, chips_after=%s
                           WHERE run_id=%s AND seq=(SELECT MAX(seq) FROM balatro_screenshots WHERE run_id=%s)""",
                        (estimated, actual_gained, round(error_ratio, 3), hand_type_str,
                         chips_before, chips_after, _db_run_id, _db_run_id))
                    _conn_db.commit()
                    _conn_db.close()
                except Exception as e:
                    print(f"[db] score update failed: {e}")


PLANET_TO_HAND = {
    "Mercury": "Pair", "Venus": "Three of a Kind", "Earth": "Full House",
    "Mars": "Four of a Kind", "Jupiter": "Flush", "Saturn": "Straight",
    "Uranus": "Two Pair", "Neptune": "Straight Flush", "Pluto": "High Card",
    "Planet X": "Five of a Kind", "Ceres": "Flush Five", "Eris": "Flush House",
}


def _use_consumables(conn, state, ante, engine):
    """Auto-use Planet and usable Tarot/Spectral cards from consumable slots."""
    try:
        new_st = conn.send_cmd("state")
        if not new_st:
            return
        consumables = new_st.get("consumables", [])
        if isinstance(consumables, dict):
            consumables = list(consumables.values())
        for i in range(len(consumables) - 1, -1, -1):  # reverse to avoid index shift
            c = consumables[i]
            ctype = c.get("type", "")
            cname = c.get("name", "")
            if ctype == "Planet":
                resp = conn.send_cmd(f"use {i}")
                if resp and resp.get("ok"):
                    print(f"[agent] 🪐 使用行星卡: {cname}")
                    hand_type = PLANET_TO_HAND.get(cname, cname)
                    engine.record_planet(hand_type)
                    time.sleep(0.3)
                else:
                    print(f"[agent] 行星卡使用失败: {cname} → {resp}")
            elif ctype in ("Tarot", "Spectral"):
                resp = conn.send_cmd(f"use {i}")
                if resp and resp.get("ok"):
                    print(f"[agent] 🔮 使用消耗品: {cname}")
                    time.sleep(0.3)
                else:
                    # Some tarots need selected cards — skip silently
                    pass
    except Exception as e:
        print(f"[agent] 使用消耗品出错: {e}")


def handle_shop(conn, state, stats, engine: DecisionEngine, evaluator: LiveEvaluator):
    """Handle shop phase using the decision engine."""
    t_shop_start = time.time()
    ante = state.get("ante", 1)
    dollars = state.get("dollars", 0)

    # Wait for shop items to load (at high game speed, shop may not be populated yet)
    shop_items = state.get("shop_items", [])
    if isinstance(shop_items, dict):
        shop_items = list(shop_items.values()) if shop_items else []
    shop_poll_delay = 0.1 if os.environ.get("BATCH_RUN_ID") else 0.3
    for _ in range(10):
        if shop_items:
            break
        time.sleep(shop_poll_delay)
        state = conn.send_cmd("state")
        shop_items = state.get("shop_items", [])
        if isinstance(shop_items, dict):
            shop_items = list(shop_items.values()) if shop_items else []
        dollars = state.get("dollars", 0)
    jokers = state.get("jokers", [])
    if isinstance(jokers, dict):
        jokers = list(jokers.values()) if jokers else []

    print(f"[agent] 商店 (ante={ante}, ${dollars}, {len(shop_items)} items) [load={time.time()-t_shop_start:.1f}s]")

    # Fetch deck info for search-based shop evaluation (sample hands from actual deck)
    try:
        deck_info = conn.send_cmd("deck_info")
        if isinstance(deck_info, dict) and deck_info.get("ok"):
            from decision.scoring import Card as SCard
            draw_pile = []
            for c in deck_info.get("draw_pile", []):
                draw_pile.append(SCard(
                    rank=c.get("value", "?"),
                    suit=c.get("suit", "?"),
                    enhancement=c.get("enhancement", "") if c.get("enhancement", "") not in ("Default Base", "Base", "") else "",
                    edition=c.get("edition", ""),
                    seal=c.get("seal", ""),
                ))
            engine.set_draw_pile(draw_pile)
        else:
            engine.set_draw_pile([])
    except Exception:
        engine.set_draw_pile([])

    screenshot_and_post(
        f"shop_a{ante}",
        f"🛒 第{ante}关 商店 | ${dollars} | {len(jokers)}个小丑 | {len(shop_items)}件商品"
    )
    evaluator.record_shop_visit(ante, dollars)

    purchases_this_shop = 0
    MAX_PURCHASES_PER_SHOP = 3

    while shop_items and dollars >= 2 and purchases_this_shop < MAX_PURCHASES_PER_SHOP:
        t_buy_decide = time.time()
        decision = engine.decide_shop(state)
        t_buy_decide = time.time() - t_buy_decide

        if decision.action == "buy":
            buy_idx = decision.params.get("index", -1)
            if 0 <= buy_idx < len(shop_items):
                item = shop_items[buy_idx]
                cost = item.get("cost", 0)
                if cost <= dollars:
                    src = "LLM" if decision.source == "llm" else "Rule"; stats["llm_decisions" if decision.source == "llm" else "rule_decisions"] += 1
                    print(f"[agent] [{src}] 购买 {item.get('name')} ${cost}: {decision.reasoning} [decide={t_buy_decide:.1f}s]")
                    resp = conn.send_cmd(f"buy {buy_idx}")
                    if resp.get("ok"):
                        time.sleep(0.3)
                        # Re-read state after purchase for accurate dollars/jokers
                        state_after_buy = conn.send_cmd("state")
                        if _game_logger:
                            _game_logger.log_shop_buy(state_after_buy if isinstance(state_after_buy, dict) and state_after_buy.get("dollars") is not None else state,
                                                      item.get('name', '?'), cost, src.lower(), decision.reasoning)
                        stats["purchases"] = stats.get("purchases", 0) + 1
                        purchases_this_shop += 1
                        engine.record_purchase(item.get("name", ""))
                        evaluator.record_purchase(
                            ante, item.get("name", "?"), cost, dollars,
                            item_type=item.get("type", ""),
                            joker_count=len(jokers),
                            was_llm=(decision.source == "llm"),
                        )
                        screenshot_and_post(
                            f"buy_{item.get('name','item').replace(' ','_')}_a{ante}",
                            f"💰 第{ante}关 | 购买[{src}]: {item.get('name')} (${cost})\n{decision.reasoning}"
                        )
                        # Auto-use Planet/Tarot cards immediately after buying
                        _use_consumables(conn, state, ante, engine)
                        # Refresh state
                        time.sleep(0.2)
                        new_st = conn.send_cmd("state")
                        if new_st and new_st.get("state") == "SHOP":
                            state = new_st
                            dollars = state.get("dollars", 0)
                            shop_items = state.get("shop_items", [])
                            if isinstance(shop_items, dict):
                                shop_items = list(shop_items.values()) if shop_items else []
                            jokers = state.get("jokers", [])
                            if isinstance(jokers, dict):
                                jokers = list(jokers.values()) if jokers else []
                        else:
                            break
                    else:
                        print(f"[agent] 购买失败: {resp}")
                        break
                else:
                    break
            else:
                break
        elif decision.action == "reroll":
            resp = conn.send_cmd("reroll")
            if resp.get("ok"):
                reroll_cost = resp.get("cost", 5)
                print(f"[agent] 🔄 Reroll shop (${reroll_cost}): {decision.reasoning}")
                if _game_logger:
                    _game_logger.log_shop_buy(state, "Reroll", reroll_cost, "rule", decision.reasoning)
                time.sleep(0.3)
                new_st = conn.send_cmd("state")
                if new_st and new_st.get("state") == "SHOP":
                    state = new_st
                    dollars = state.get("dollars", 0)
                    shop_items = state.get("shop_items", [])
                    if isinstance(shop_items, dict):
                        shop_items = list(shop_items.values()) if shop_items else []
                    jokers = state.get("jokers", [])
                    if isinstance(jokers, dict):
                        jokers = list(jokers.values()) if jokers else []
                    continue
                else:
                    break
            else:
                print(f"[agent] Reroll failed: {resp}")
                break
        else:
            break

    # Use any remaining consumables before leaving shop
    _use_consumables(conn, state, ante, engine)

    use_fast_shop = bool(os.environ.get("BATCH_RUN_ID"))
    shop_cmd = "fast_end_shop" if use_fast_shop else "end_shop"
    conn.send_cmd(shop_cmd)
    time.sleep(0.3)
    t_shop_total = time.time() - t_shop_start
    print(f"[perf] 商店总耗时: {t_shop_total:.1f}s (购买{purchases_this_shop}件)")
    wait_state(conn, ["BLIND_SELECT", "GAME_OVER"], timeout=30)


def handle_blind_select(conn, state, stats, engine: DecisionEngine, evaluator: LiveEvaluator):
    """Handle blind selection using the decision engine. Returns blind name."""
    t_blind = time.time()
    ante = state.get("ante", 1)
    # Boss blind name comes directly from G.GAME.blind.name (exported as boss_blind)
    boss_name = state.get("boss_blind", "")
    blind_on_deck = state.get("blind_on_deck", "?")

    print(f"[agent] 盲注选择: ante={ante}, blind={blind_on_deck}, boss={boss_name or 'none'}")
    if _game_logger:
        _game_logger.log_blind_select(state, blind_on_deck, boss_name or "")
        # Track boss blind name for all subsequent log entries in this ante
        if boss_name:
            _game_logger.set_boss_blind(boss_name)

    if boss_name:
        screenshot_and_post(
            f"boss_blind_a{ante}",
            f"👹 第{ante}关 | Boss盲注: {boss_name}"
        )

        decision = engine.decide_blind(state)
        if decision.reasoning:
            src = "LLM" if decision.source == "llm" else "Rule"; stats["llm_decisions" if decision.source == "llm" else "rule_decisions"] += 1
            print(f"[agent] [{src}] Boss策略: {decision.reasoning}")

    # Check if engine wants to skip (Small/Big blind only)
    if blind_on_deck in ("Small", "Big"):
        decision = engine.decide_blind(state)
        if decision.action == "skip_blind":
            print(f"[agent] ⏭️ Skip {blind_on_deck}: {decision.reasoning}")
            if _game_logger:
                _game_logger.log_action(state, "blind_select", f"跳过 {blind_on_deck} ({decision.reasoning})", phase="blind_select")
            conn.send_cmd("select_blind", {"blind_type": "skip"})
            time.sleep(0.5)
            wait_state(conn, ["BLIND_SELECT", "SELECTING_HAND", "GAME_OVER"], timeout=20)
            print(f"[perf] 盲注跳过: {time.time()-t_blind:.1f}s")
            return

    conn.send_cmd("select_blind")
    time.sleep(0.5)
    wait_state(conn, ["SELECTING_HAND", "GAME_OVER"], timeout=20)
    print(f"[perf] 盲注选择: {time.time()-t_blind:.1f}s")
    return blind_on_deck


def run():
    """Main game loop."""
    global _conn_ref

    # Start background services
    start_lark_sender()
    start_ctrl_server()

    conn = BalatroConnection(HOST, PORT)
    conn.connect()
    _conn_ref = conn

    # Initialize decision engine and evaluator
    engine = DecisionEngine()
    engine.new_game()
    evaluator = LiveEvaluator()

    stats = {
        "hands": 0, "discards": 0, "purchases": 0,
        "max_ante": 0, "final_score": 0,
        "jokers_at_end": [], "start_time": now_sgt().isoformat(),
        "rule_decisions": 0, "llm_decisions": 0,
        "stop_after_ante": STOP_AFTER_ANTE,
    }

    # Announce game start
    global _db_run_id, _run_code, _game_logger
    if DB_ENABLED:
        try:
            _run_code, _reserved_id = generate_run_code()
            run_config = {
                "GAMESPEED": os.environ.get("GAMESPEED", ""),
                "STOP_AFTER_ANTE": STOP_AFTER_ANTE,
                "USE_LLM": USE_LLM,
                "FAST_MODE": FAST_MODE,
                "LARK_VERBOSE": LARK_VERBOSE,
            }
            _db_run_id = create_run(_run_code, run_config, LLM_MODEL, run_id=_reserved_id)
            _game_logger = GameLogger(_db_run_id, enabled=DB_ENABLED)
            # Link to batch run if running as part of a batch
            _batch_run_id = os.environ.get("BATCH_RUN_ID")
            if _batch_run_id and DB_ENABLED:
                try:
                    from run_db import _get_conn
                    _bconn = _get_conn()
                    _bcur = _bconn.cursor()
                    _bcur.execute("UPDATE balatro_runs SET batch_run_id = %s WHERE id = %s", (int(_batch_run_id), _db_run_id))
                    _bconn.commit()
                    _bconn.close()
                except Exception as e:
                    print(f"[agent] batch link failed: {e}")
            print(f"[agent] DB run created: {_run_code} (id={_db_run_id})")

            # Register strategy
            import hashlib
            strategy_files = ["decision/engine.py", "decision/strategy.py", "decision/scoring.py"]
            code_parts = []
            for sf in strategy_files:
                try:
                    with open(sf) as f:
                        code_parts.append(f"# === {sf} ===\n" + f.read())
                except:
                    pass
            full_source = "\n\n".join(code_parts)
            # Also include llm_advisor.py in stored source (for display) but NOT in hash
            try:
                with open("decision/llm_advisor.py") as f:
                    full_source += f"\n\n# === decision/llm_advisor.py ===\n{f.read()}"
            except:
                pass
            # Strategy params — included in hash so param changes = new strategy
            strategy_params = {
                "model": LLM_MODEL,
                "llm_threshold": "hand_rank<=1 AND score<30%",
                "max_tokens": 1024,
            }
            # Hash = code + params JSON (sorted, deterministic)
            params_json = json.dumps(strategy_params, sort_keys=True)
            hash_input = "\n\n".join(code_parts) + "\n" + params_json
            code_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:16]
            strategy_name = f"v{code_hash[:8]}-{LLM_MODEL.split('/')[-1]}"
            try:
                sid = register_strategy(strategy_name, code_hash, LLM_MODEL,
                                        strategy_params, source_code=full_source)
                link_run_strategy(_db_run_id, sid)
                print(f"[agent] 策略: {strategy_name} (id={sid})")

                # Generate LLM summary for NEW strategies (check if summary is empty)
                try:
                    from run_db import _get_conn
                    _sc = _get_conn(); _scr = _sc.cursor()
                    _scr.execute("SELECT summary, parent_id FROM balatro_strategies WHERE id = %s", (sid,))
                    _srow = _scr.fetchone()
                    if _srow and not _srow[0] and USE_LLM:  # No summary yet = new strategy, need LLM
                        parent_source = None
                        if _srow[1]:
                            _scr.execute("SELECT source_code, name FROM balatro_strategies WHERE id = %s", (_srow[1],))
                            _prow = _scr.fetchone()
                            if _prow and _prow[0]:
                                parent_source = _prow[0]
                                parent_name = _prow[1]
                        # Build LLM prompt for summary
                        summary_prompt = "用中文写一段简洁的策略描述（100-200字），包括：\n1. 这个策略的核心思路\n2. 主要决策逻辑\n3. 关键参数\n"
                        if parent_source:
                            summary_prompt += f"\n4. 与上一版策略 ({parent_name}) 的主要差异\n"
                            summary_prompt += f"\n--- 上一版代码（摘要）---\n{parent_source[:2000]}\n"
                        summary_prompt += f"\n--- 当前策略代码 ---\n{full_source[:4000]}"

                        from decision.llm_advisor import _call_llm_raw
                        summary_text = _call_llm_raw(summary_prompt, max_tokens=512)
                        if summary_text:
                            _scr.execute("UPDATE balatro_strategies SET summary = %s WHERE id = %s",
                                         (summary_text, sid))
                            _sc.commit()
                            print(f"[agent] 策略描述已生成 ({len(summary_text)} chars)")
                    _sc.close()
                except Exception as se:
                    print(f"[agent] 策略描述生成失败 (non-fatal): {se}")

                # Auto-create git branch for new strategy
                branch_name = f"strategy/{strategy_name}"
                try:
                    import subprocess
                    repo_dir = "/tmp/balatro-strategy"
                    if not os.path.exists(repo_dir):
                        subprocess.run(["git", "clone", f"https://carlnoah6:{os.popen('gh auth token').read().strip()}@github.com/carlnoah6/balatro-strategy.git", repo_dir],
                                        capture_output=True, timeout=15)
                    else:
                        subprocess.run(["git", "fetch", "origin"], cwd=repo_dir, capture_output=True, timeout=10)
                        subprocess.run(["git", "checkout", "main"], cwd=repo_dir, capture_output=True, timeout=5)
                        subprocess.run(["git", "pull"], cwd=repo_dir, capture_output=True, timeout=10)

                    # Check if branch exists
                    r = subprocess.run(["git", "branch", "-r", "--list", f"origin/{branch_name}"],
                                       cwd=repo_dir, capture_output=True, text=True, timeout=5)
                    if branch_name not in (r.stdout or ""):
                        subprocess.run(["git", "checkout", "-b", branch_name], cwd=repo_dir, capture_output=True, timeout=5)
                        for sf in strategy_files:
                            import shutil
                            shutil.copy2(sf, os.path.join(repo_dir, os.path.basename(sf)))
                        # Copy LLM advisor too
                        shutil.copy2("decision/llm_advisor.py", os.path.join(repo_dir, "llm_advisor.py"))
                        # Write strategy.json
                        import json as _json
                        with open(os.path.join(repo_dir, "strategy.json"), "w") as sf:
                            _json.dump({"name": strategy_name, "code_hash": code_hash,
                                        "model": LLM_MODEL, "params": strategy_params}, sf, indent=2)
                        subprocess.run(["git", "add", "-A"], cwd=repo_dir, capture_output=True, timeout=5)
                        subprocess.run(["git", "commit", "-m", f"strategy: {strategy_name}"],
                                       cwd=repo_dir, capture_output=True, timeout=5)
                        subprocess.run(["git", "push", "origin", branch_name],
                                       cwd=repo_dir, capture_output=True, timeout=15)
                        # Update DB with branch name
                        from run_db import _get_conn
                        c = _get_conn(); cr = c.cursor()
                        cr.execute("UPDATE balatro_strategies SET github_branch=%s WHERE id=%s", (branch_name, sid))
                        c.commit(); c.close()
                        print(f"[agent] Git branch created: {branch_name}")
                    else:
                        print(f"[agent] Git branch exists: {branch_name}")
                except Exception as ge:
                    print(f"[agent] Git branch creation failed (non-fatal): {ge}")
            except Exception as e:
                print(f"[agent] strategy registration failed: {e}")
        except Exception as e:
            print(f"[agent] DB create_run failed: {e}")
            _db_run_id = None

    screenshot_and_post("game_start", "🎮 小丑牌 AI 开始新游戏！")
    lark_verbose(lark_send_text, LARK_TIMELINE_CHAT,
        f"🤖 AI 已连接\n"
        f"模型: {'✅ ' + LLM_MODEL if USE_LLM else '❌ 纯规则'}\n"
        f"控制端口: {CTRL_PORT}\n"
        f"时间: {now_sgt().strftime('%H:%M:%S')}"
    )

    prev_state = None
    prev_ante = 0
    same_state_count = 0
    MAX_SAME_STATE = 60 if os.environ.get("BATCH_RUN_ID") else 20  # More patient in batch mode
    MAX_ROUNDS_PER_ANTE = 15  # Max rounds before forcing progression
    rounds_this_ante = 0
    current_blind = "Small"  # Track current blind name
    MAX_RECONNECTS = 5  # Max reconnection attempts before giving up
    _game_seed = None  # Captured from first state
    _last_progress = ""  # "ante-blind" for DB tracking

    reconnect_count = 0
    try:
      while True:
        try:
            sys.stdout.flush()

            # Check for graceful shutdown signal
            if _stop_requested:
                print("[agent] 收到退出信号，优雅退出")
                lark_send_text(LARK_TIMELINE_CHAT, "⚠️ Agent 收到退出信号，正在保存并退出...")
                break

            # Check for external control commands
            ctrl = check_control()
            if ctrl == "stop":
                lark_send_text(LARK_TIMELINE_CHAT, "⏹️ Agent 收到停止指令，正在退出...")
                print("[agent] 收到 stop 指令，退出")
                break
            elif ctrl == "pause":
                lark_send_text(LARK_TIMELINE_CHAT, "⏸️ Agent 已暂停，写入 'resume' 到控制文件继续")
                print("[agent] 暂停中...")
                while True:
                    time.sleep(2)
                    c = check_control()
                    if c == "resume":
                        lark_send_text(LARK_TIMELINE_CHAT, "▶️ Agent 已恢复")
                        print("[agent] 恢复运行")
                        break
                    elif c == "stop":
                        lark_send_text(LARK_TIMELINE_CHAT, "⏹️ Agent 停止")
                        print("[agent] 停止")
                        return
            elif ctrl and ctrl.startswith("msg:"):
                # Forward message to Lark
                lark_send_text(LARK_TIMELINE_CHAT, f"📨 用户消息: {ctrl[4:]}")

            # Check screenshot limit
            if MAX_SCREENSHOTS > 0 and _screenshot_count >= MAX_SCREENSHOTS:
                lark_send_text(LARK_TIMELINE_CHAT, f"📸 已达到截图上限 ({MAX_SCREENSHOTS})，本轮测试结束")
                print(f"[agent] 截图上限 {MAX_SCREENSHOTS} 已达到，退出")
                break

            # === Get game state ===
            st = conn.send_cmd("state")
            if not st or st.get("ok") == False:
                time.sleep(1)
                continue

            cur = st.get("state", "")
            ante = st.get("ante", 0)

            # Capture seed on first state read
            if not _game_seed and st.get("seed") and st["seed"] != "unknown":
                _game_seed = st["seed"]
                print(f"[agent] 种子: {_game_seed}")
                if DB_ENABLED and _db_run_id:
                    try:
                        from run_db import _get_conn
                        c = _get_conn(); cr = c.cursor()
                        cr.execute("UPDATE balatro_runs SET seed=%s WHERE id=%s", (_game_seed, _db_run_id))
                        c.commit(); c.close()
                    except Exception as e:
                        print(f"[db] seed update failed: {e}")

            # Track progress as normalized number: ante*100 + blind_num
            # 小盲=01, 大盲=02, Boss=03. E.g. 301=Ante3小盲, 403=Ante4Boss
            BLIND_NUM = {"Small": 1, "Big": 2, "Boss": 3}
            blind_num = BLIND_NUM.get(current_blind, 0)
            if blind_num > 0:
                progress_num = ante * 100 + blind_num
                progress = str(progress_num)
                if progress != _last_progress:
                    _last_progress = progress
                    if DB_ENABLED and _db_run_id:
                        try:
                            from run_db import _get_conn
                            c = _get_conn(); cr = c.cursor()
                            cr.execute("UPDATE balatro_runs SET progress=%s WHERE id=%s", (progress, _db_run_id))
                            c.commit(); c.close()
                        except Exception as e:
                            print(f"[db] progress update failed: {e}")

            # Track ante progression
            if ante > prev_ante:
                prev_ante = ante
                stats["max_ante"] = ante
                rounds_this_ante = 0

                # Test mode: stop after completing an ante
                if STOP_AFTER_ANTE > 0 and ante > STOP_AFTER_ANTE:
                    msg = (
                        f"🧪 测试模式：第{STOP_AFTER_ANTE}关已完成，暂停复盘\n"
                        f"出牌 {stats['hands']} 手 | 弃牌 {stats['discards']} 次 | 购买 {stats.get('purchases', 0)} 件\n"
                        f"策略: {engine.status_summary()}"
                    )
                    print(f"[agent] {msg}")
                    LARK_VERBOSE and lark_send_text(LARK_TIMELINE_CHAT, msg)
                    screenshot_and_post(f"ante{STOP_AFTER_ANTE}_done", msg)
                    # Quit to menu so next run gets a fresh seed
                    try:
                        conn.send_cmd("quit_run")
                        print("[agent] quit_run sent, returning to menu")
                    except:
                        pass
                    break

                if ante > 1:
                    LARK_VERBOSE and lark_send_text(LARK_TIMELINE_CHAT,
                        f"📈 进入第{ante}关 | ${st.get('dollars', 0)} | "
                        f"已出 {stats['hands']} 手 | 弃 {stats['discards']} 次"
                    )

            # Stuck detection: same state too many times
            state_key = f"{cur}_{ante}_{st.get('hands_left', 0)}_{st.get('chips', 0)}"
            if state_key == prev_state:
                same_state_count += 1
                if same_state_count >= MAX_SAME_STATE:
                    msg = f"⚠️ 检测到卡住：{cur} 状态重复 {same_state_count} 次，停止"
                    print(f"[agent] {msg}")
                    LARK_VERBOSE and lark_send_text(LARK_TIMELINE_CHAT, msg)
                    break
            else:
                same_state_count = 0
                prev_state = state_key

            # Track jokers continuously (GAME_OVER state may not have them)
            cur_jokers = st.get("jokers", [])
            if isinstance(cur_jokers, dict):
                cur_jokers = list(cur_jokers.values()) if cur_jokers else []
            if cur_jokers:
                stats["jokers_at_end"] = [j.get("name", "?") for j in cur_jokers]

            if cur == "SELECTING_HAND":
                handle_selecting_hand(conn, st, stats, engine, evaluator, blind_name=current_blind)

            elif cur == "SHOP":
                handle_shop(conn, st, stats, engine, evaluator)

            elif cur == "BLIND_SELECT":
                handle_blind_select(conn, st, stats, engine, evaluator)
                current_blind = st.get("blind_on_deck", "Small")

            elif cur == "ROUND_EVAL":
                # Cash out after round evaluation
                rounds_this_ante += 1
                time.sleep(0.2)
                evaluator.record_round_clear(
                    ante,
                    blind_type=st.get("blind_info", {}).get("type", "unknown"),
                    score=st.get("chips", 0),
                    target=st.get("blind_chips", 0),
                )
                # Use fast_cash_out in batch mode (direct state manipulation, no animations)
                use_fast = bool(os.environ.get("BATCH_RUN_ID"))
                cash_cmd = "fast_cash_out" if use_fast else "cash_out"
                
                # Retry cash_out up to 5 times (G.round_eval UI may not be ready)
                cashout_ok = False
                dollars_before = st.get("dollars", 0)
                for _retry in range(5):
                    resp = conn.send_cmd(cash_cmd)
                    if resp.get("ok"):
                        cashout_ok = True
                        break
                    print(f"[agent] cash_out 失败 (retry {_retry+1}): {resp.get('error', '?')}")
                    time.sleep(2)
                
                if cashout_ok:
                    t_cashout = time.time()
                    earned = resp.get("earned", resp.get("dollars_earned", "?"))
                    print(f"[agent] 结算: (本关第{rounds_this_ante}轮) +${earned}")
                    time.sleep(0.5)
                    wait_state(conn, ["SHOP", "BLIND_SELECT", "GAME_OVER"], timeout=30)
                    # Get state after cashout to capture dollars_after
                    st_after = conn.send_cmd("state")
                    dollars_after = st_after.get("dollars", 0)
                    if _game_logger:
                        _game_logger.log_cashout(st, dollars_before=dollars_before, dollars_after=dollars_after, earned=earned)
                    print(f"[perf] 结算→商店: {time.time()-t_cashout:.1f}s")
                else:
                    print(f"[agent] ⚠️ cash_out 重试5次仍失败，等待状态变化...")
                    wait_state(conn, ["SHOP", "BLIND_SELECT", "GAME_OVER", "SELECTING_HAND"], timeout=30)

            elif cur == "GAME_OVER":
                stats["final_score"] = st.get("chips", 0)
                end_jokers = st.get("jokers", [])
                if isinstance(end_jokers, dict):
                    end_jokers = list(end_jokers.values()) if end_jokers else []
                stats["jokers_at_end"] = [j.get("name", "?") for j in end_jokers]
                stats["end_time"] = now_sgt().isoformat()
                if _game_logger:
                    _game_logger.log_game_over(st, "game_over")
                evaluator.record_game_over("game_over")
                screenshot_and_post("game_over", "")
                # Quit to menu so next run gets a fresh seed
                try:
                    conn.send_cmd("quit_run")
                except:
                    pass
                break

            elif cur == "MENU" or cur == "SPLASH":
                # Start a new run (optionally with seed)
                game_seed = os.environ.get("SEED", "")
                seed_msg = f" (种子: {game_seed})" if game_seed else ""
                print(f"[agent] 在主菜单，开始新游戏{seed_msg}...", flush=True)
                cmd = f"start_run {game_seed}" if game_seed else "start_run"
                resp = conn.send_cmd(cmd)
                print(f"[agent] start_run 返回: {resp}", flush=True)
                # Enable turbo mode in batch runs
                if os.environ.get("BATCH_RUN_ID"):
                    try:
                        turbo_resp = conn.send_cmd("turbo")
                        print(f"[agent] turbo 模式: {turbo_resp}", flush=True)
                    except:
                        pass
                time.sleep(3)
                print("[agent] 等待进入盲注选择...", flush=True)
                wait_state(conn, ["BLIND_SELECT", "SELECTING_HAND"], timeout=30)
                print("[agent] 已进入游戏", flush=True)

            elif cur in ("HAND_PLAYED", "DRAW_TO_HAND", "NEW_ROUND", "SCORING",
                         "TAROT_PACK", "PLANET_PACK", "SPECTRAL_PACK", "BUFFOON_PACK", "STANDARD_PACK"):
                # Transition states - just wait
                time.sleep(0.5)

            else:
                time.sleep(0.8)

        except (ConnectionError, BrokenPipeError, OSError, json.JSONDecodeError) as e:
            # Connection lost during gameplay — reconnect and restart game loop
            reconnect_count += 1
            print(f"[agent] 连接丢失 (第{reconnect_count}次): {e}", flush=True)
            if reconnect_count > MAX_RECONNECTS:
                lark_send_text(LARK_TIMELINE_CHAT, f"❌ 重连次数超限 ({MAX_RECONNECTS})，Agent 退出")
                break
            lark_async(lark_send_text, LARK_TIMELINE_CHAT,
                f"⚠️ 连接断开: {str(e)[:60]}\n正在重连 ({reconnect_count}/{MAX_RECONNECTS})...")
            if conn.reconnect(retries=60, delay=3.0):
                lark_async(lark_send_text, LARK_TIMELINE_CHAT, "✅ 重连成功，继续游戏")
                continue  # Back to while True — re-enter game loop
            else:
                lark_send_text(LARK_TIMELINE_CHAT, "❌ 重连失败，Agent 退出")
                break

    except KeyboardInterrupt:
        print("\n[agent] 已中断")
        lark_send_text(LARK_TIMELINE_CHAT, "⚠️ AI 被手动中断")
    except Exception as e:
        print(f"[agent] 错误: {e}", flush=True)
        traceback.print_exc()
        try:
            screenshot_and_post("error", f"❌ 出错: {str(e)[:100]}")
            lark_send_text(LARK_TIMELINE_CHAT, f"❌ AI 出错: {str(e)[:200]}")
        except Exception:
            pass
    finally:
        # === 等待截图队列排空 ===
        try:
            _screenshot_queue.join()  # wait for all pending screenshots
        except Exception:
            pass

        # === 无论如何退出，都生成报告 ===
        stats["end_time"] = stats.get("end_time", now_sgt().isoformat())

        # Attach LLM stats
        try:
            from decision.llm_advisor import get_llm_stats
            evaluator.result.llm_stats = get_llm_stats()
            llm_stats = get_llm_stats()
        except Exception:
            llm_stats = {}

        # Build report
        joker_list = ", ".join(stats.get("jokers_at_end", [])) or "无"
        eval_text = ""
        try:
            eval_text = evaluator.get_text_report()
        except Exception:
            pass

        # Token cost calculation
        input_tok = llm_stats.get("input_tokens", 0)
        output_tok = llm_stats.get("output_tokens", 0)
        llm_calls = llm_stats.get("calls", 0)
        llm_fails = llm_stats.get("failures", 0)
        llm_total_s = llm_stats.get("total_ms", 0) / 1000
        # gemini-2.5-flash: $0.15/1M input, $0.60/1M output
        cost_usd = input_tok / 1_000_000 * 0.15 + output_tok / 1_000_000 * 0.60

        # Decision source breakdown
        rule_d = stats.get("rule_decisions", 0)
        llm_d = stats.get("llm_decisions", 0)
        total_d = rule_d + llm_d
        rule_pct = f"{rule_d/total_d*100:.0f}%" if total_d > 0 else "N/A"
        llm_pct = f"{llm_d/total_d*100:.0f}%" if total_d > 0 else "N/A"

        report = (
            f"🏁 游戏结束\n\n"
            f"📊 成绩:\n"
            f"  关卡: Ante {stats['max_ante']}\n"
            f"  出牌: {stats['hands']} 手 | 弃牌: {stats['discards']} 次\n"
            f"  购买: {stats['purchases']} 件\n"
            f"  小丑牌: {joker_list}\n"
            f"  策略: {engine.status_summary()}\n\n"
            f"🧠 决策分布:\n"
            f"  Rule: {rule_d} 次 ({rule_pct}) | LLM: {llm_d} 次 ({llm_pct})\n\n"
            f"🤖 LLM 统计:\n"
            f"  模型: {LLM_MODEL}\n"
            f"  调用: {llm_calls} 次 (失败 {llm_fails})\n"
            f"  耗时: {llm_total_s:.1f}s (平均 {llm_total_s/max(llm_calls,1):.1f}s/次)\n"
            f"  Token: {input_tok} in + {output_tok} out = {input_tok+output_tok}\n"
            f"  成本: ${cost_usd:.4f}\n\n"
            f"{'🎉 胜利！' if stats['max_ante'] >= 8 else '💀 第' + str(stats['max_ante']) + '关'}"
        )

        # Finalize DB record
        web_url = ""
        if DB_ENABLED and _db_run_id:
            try:
                finalize_run(_db_run_id, stats, llm_stats, report, engine.status_summary())
                web_url = f"https://anz-luna.grolar-wage.ts.net/balatro/game/{_run_code}"
                print(f"[agent] DB finalized: {_run_code} → {web_url}")
            except Exception as e:
                print(f"[agent] DB finalize failed: {e}")

        # Send report to Lark (always, regardless of LARK_VERBOSE)
        if web_url:
            report += f"\n\n🔗 详情: {web_url}"
        try:
            lark_send_text(LARK_TIMELINE_CHAT, report)
            if not os.environ.get("BATCH_RUN_ID"):
                print("[agent] Lark 报告已发送")
        except Exception as e:
            print(f"[agent] Lark 报告发送失败: {e}")
        if eval_text and LARK_VERBOSE:
            lark_send_text(LARK_TIMELINE_CHAT, f"📈 评估报告:\n{eval_text[:2000]}")
        print(f"\n[agent] 报告:\n{report}")

        # Save evaluation
        try:
            eval_path = evaluator.save("/home/ubuntu/balatro-env/eval_results")
            print(f"[agent] Evaluation saved: {eval_path}")
        except Exception as e:
            print(f"[agent] Failed to save evaluation: {e}")

        print(f"\n[agent] Stats: {json.dumps(stats, indent=2)}")
        conn.close()
        # Wake Luna session (skip in batch mode)
        if not os.environ.get("BATCH_RUN_ID"):
            try:
                ante = stats.get("max_ante", "?")
                result = "胜利" if stats.get("max_ante", 0) >= 8 else "失败"
                requests.post(
                    "http://localhost:18789/api/wake",
                    json={"text": f"🎮 Balatro 游戏结束: Ante {ante} {result}，请查看评估报告并汇报给 Carl。", "mode": "now"},
                    timeout=5,
                )
                print("[agent] 已通知 Luna session")
            except Exception as e:
                print(f"[agent] 通知失败: {e}")


if __name__ == "__main__":
    run()
