#!/usr/bin/env python3
"""Fly.io in-container batch worker — runs multiple game+agent processes in parallel.

Env vars (set by fly-batch.py):
    SEEDS           - comma-separated seed list
    WORKERS         - number of parallel workers (default: 4)
    STOP_AFTER_ANTE - stop after this ante
    BATCH_RUN_ID    - batch run ID for DB
    DATABASE_URL    - Neon connection string
    LLM_BASE_URL    - api-proxy URL
    LLM_API_KEY     - api-proxy key
    LLM_MODEL       - model name
    STRATEGY_ID     - strategy ID
"""

import asyncio
import json
import os
import signal
import subprocess
import sys
import time

WORKERS = int(os.environ.get("WORKERS", "4"))
SEEDS = os.environ.get("SEEDS", "").split(",")
STOP_AFTER_ANTE = os.environ.get("STOP_AFTER_ANTE", "8")
GAMESPEED = os.environ.get("GAMESPEED", "16")
BASE_DISPLAY = 99
BASE_GAME_PORT = 12345
BASE_CTRL_PORT = 12390


class GameWorker:
    """Manages one Xvfb + LÖVE + agent process set."""

    def __init__(self, wid: int):
        self.wid = wid
        self.display = f":{BASE_DISPLAY + wid}"
        self.game_port = BASE_GAME_PORT + wid
        self.ctrl_port = BASE_CTRL_PORT + wid
        self.xvfb_proc = None
        self.game_proc = None

    async def start_display(self):
        """Start Xvfb for this worker."""
        lock = f"/tmp/.X{BASE_DISPLAY + self.wid}-lock"
        sock = f"/tmp/.X11-unix/X{BASE_DISPLAY + self.wid}"
        for f in [lock, sock]:
            try:
                os.unlink(f)
            except FileNotFoundError:
                pass

        self.xvfb_proc = await asyncio.create_subprocess_exec(
            "Xvfb", self.display, "-screen", "0", "1280x720x24",
            "-ac", "+extension", "GLX", "+render", "-noreset",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.sleep(1)
        print(f"[w{self.wid}] Xvfb on {self.display}", flush=True)

    async def start_game(self):
        """Start LÖVE game process with lovely-injector."""
        env = {
            **os.environ,
            "DISPLAY": self.display,
            "LD_PRELOAD": "/usr/local/lib/liblovely.so",
            "BALATRO_PORT": str(self.game_port),
        }
        self.game_proc = await asyncio.create_subprocess_exec(
            "love", "/opt/balatro-game",
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        # Wait for game TCP port
        for i in range(60):
            try:
                r, w = await asyncio.open_connection("127.0.0.1", self.game_port)
                w.write(b"state\n")
                await w.drain()
                data = await asyncio.wait_for(r.read(4096), timeout=2)
                w.close()
                await w.wait_closed()
                if b"state" in data:
                    print(f"[w{self.wid}] Game ready on port {self.game_port}", flush=True)
                    return True
            except:
                pass
            await asyncio.sleep(2)
        print(f"[w{self.wid}] Game failed to start", flush=True)
        return False

    async def run_seed(self, seed: str) -> dict:
        """Run agent for one seed."""
        print(f"[w{self.wid}] Seed {seed} starting", flush=True)
        t0 = time.time()

        env = {
            **os.environ,
            "DISPLAY": self.display,
            "SEED": seed,
            "STOP_AFTER_ANTE": STOP_AFTER_ANTE,
            "GAMESPEED": GAMESPEED,
            "LARK_VERBOSE": "0",
            "NO_SCREENSHOTS": "1",
            "BALATRO_PORT": str(self.game_port),
            "CTRL_PORT": str(self.ctrl_port),
        }

        log_path = f"/tmp/agent_w{self.wid}.log"
        with open(log_path, "w") as lf:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "/opt/balatro-ai/ai-agent.py",
                stdout=lf, stderr=lf,
                cwd="/opt/balatro-ai", env=env,
            )
            try:
                await asyncio.wait_for(proc.wait(), timeout=1800)  # 30 min per seed (stop-ante 8 can take long)
                rc = proc.returncode
            except asyncio.TimeoutError:
                # Send SIGTERM first for graceful shutdown (finalize DB)
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=10)
                except asyncio.TimeoutError:
                    proc.kill()
                rc = -1

        elapsed = time.time() - t0
        print(f"[w{self.wid}] Seed {seed} done in {elapsed:.0f}s (exit={rc})", flush=True)

        # After seed: game needs restart (it crashes after quit_run)
        await self.restart_game()

        return {"seed": seed, "exit_code": rc, "elapsed": elapsed}

    async def restart_game(self):
        """Kill and restart the game process."""
        if self.game_proc:
            try:
                self.game_proc.kill()
                await self.game_proc.wait()
            except:
                pass
        await self.start_game()

    async def cleanup(self):
        for p in [self.game_proc, self.xvfb_proc]:
            if p:
                try:
                    p.kill()
                    await p.wait()
                except:
                    pass


async def main():
    seeds = [s.strip() for s in SEEDS if s.strip()]
    num_workers = min(WORKERS, len(seeds))

    print(f"[orchestrator] {len(seeds)} seeds, {num_workers} workers", flush=True)
    print(f"[orchestrator] Stop ante: {STOP_AFTER_ANTE}, Speed: {GAMESPEED}", flush=True)

    # Start all workers
    workers = []
    for i in range(num_workers):
        w = GameWorker(i)
        await w.start_display()
        workers.append(w)

    # Start games (parallel)
    results = await asyncio.gather(*[w.start_game() for w in workers])
    active = [(w, ok) for w, ok in zip(workers, results)]
    ready_workers = [w for w, ok in active if ok]

    if not ready_workers:
        print("[orchestrator] No workers ready, exiting", flush=True)
        sys.exit(1)

    print(f"[orchestrator] {len(ready_workers)} workers ready", flush=True)

    # Seed queue
    queue = asyncio.Queue()
    for s in seeds:
        await queue.put(s)

    completed = 0
    total = len(seeds)

    async def worker_loop(w: GameWorker):
        nonlocal completed
        while not queue.empty():
            try:
                seed = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            await w.run_seed(seed)
            completed += 1
            print(f"[progress] {completed}/{total}", flush=True)

    t_start = time.time()

    # Resource monitor — sample CPU and memory every 10s
    resource_samples = []
    monitor_stop = asyncio.Event()

    async def resource_monitor():
        while not monitor_stop.is_set():
            try:
                # Read /proc/stat for CPU
                with open("/proc/stat") as f:
                    cpu_line = f.readline().split()
                cpu_total = sum(int(x) for x in cpu_line[1:])
                cpu_idle = int(cpu_line[4])

                # Read /proc/meminfo
                mem = {}
                with open("/proc/meminfo") as f:
                    for line in f:
                        parts = line.split()
                        if parts[0] in ("MemTotal:", "MemAvailable:", "MemFree:", "Buffers:", "Cached:"):
                            mem[parts[0].rstrip(":")] = int(parts[1])

                mem_total = mem.get("MemTotal", 0)
                mem_avail = mem.get("MemAvailable", 0)
                mem_used_pct = round((1 - mem_avail / mem_total) * 100, 1) if mem_total else 0
                mem_used_mb = round((mem_total - mem_avail) / 1024)

                # Load average
                with open("/proc/loadavg") as f:
                    load1, load5, load15 = f.read().split()[:3]

                sample = {
                    "t": round(time.time() - t_start),
                    "cpu_total": cpu_total,
                    "cpu_idle": cpu_idle,
                    "mem_pct": mem_used_pct,
                    "mem_mb": mem_used_mb,
                    "load1": float(load1),
                    "load5": float(load5),
                }
                resource_samples.append(sample)
            except Exception as e:
                pass
            try:
                await asyncio.wait_for(monitor_stop.wait(), timeout=10)
                break
            except asyncio.TimeoutError:
                pass

    monitor_task = asyncio.create_task(resource_monitor())

    # Total orchestrator timeout: 55 min (leave 5 min for cleanup before 60 min machine kill)
    TOTAL_TIMEOUT = 55 * 60
    try:
        await asyncio.wait_for(
            asyncio.gather(*[worker_loop(w) for w in ready_workers]),
            timeout=TOTAL_TIMEOUT,
        )
    except asyncio.TimeoutError:
        print(f"[orchestrator] ⚠️ Total timeout ({TOTAL_TIMEOUT}s) reached, stopping", flush=True)

    monitor_stop.set()
    await monitor_task

    elapsed = time.time() - t_start

    # Print resource summary
    if len(resource_samples) >= 2:
        # Calculate CPU usage from deltas
        cpu_usages = []
        for i in range(1, len(resource_samples)):
            dt = resource_samples[i]["cpu_total"] - resource_samples[i-1]["cpu_total"]
            di = resource_samples[i]["cpu_idle"] - resource_samples[i-1]["cpu_idle"]
            if dt > 0:
                cpu_usages.append(round((1 - di / dt) * 100, 1))

        mem_pcts = [s["mem_pct"] for s in resource_samples]
        mem_mbs = [s["mem_mb"] for s in resource_samples]
        loads = [s["load1"] for s in resource_samples]

        print(f"[resources] Samples: {len(resource_samples)} over {elapsed:.0f}s", flush=True)
        print(f"[resources] CPU: avg={sum(cpu_usages)/len(cpu_usages):.1f}% peak={max(cpu_usages):.1f}% min={min(cpu_usages):.1f}%", flush=True)
        print(f"[resources] MEM: avg={sum(mem_pcts)/len(mem_pcts):.1f}% peak={max(mem_pcts):.1f}% (peak {max(mem_mbs)}MB used)", flush=True)
        print(f"[resources] LOAD: avg={sum(loads)/len(loads):.1f} peak={max(loads):.1f}", flush=True)

    print(f"[orchestrator] Done: {completed}/{total} in {elapsed:.0f}s", flush=True)

    # Cleanup
    for w in workers:
        await w.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
