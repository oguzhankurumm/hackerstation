#!/usr/bin/env python3
"""
HackerStation Supervisor — out-of-process self-healing.

Watches:
  - the router HTTP process (port 8080)
  - the Ollama backend (port 11434)
  - host memory pressure

Restarts the router if it stops responding, with crash-loop protection.
This is the safety net for failures the in-process watchdog cannot recover from
(segfault, OOM-kill, deadlock).

Usage:
  python3 supervisor.py            # supervise router on default port 8080
  python3 supervisor.py 8080       # explicit port
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import memory_probe

ROOT = Path(__file__).resolve().parent
LOGS = ROOT / "logs"
LOGS.mkdir(exist_ok=True)

SELF_HEAL_LOG = LOGS / "self-heal.log"
ROUTER_LOG = ROOT / "router.log"

ROUTER_SCRIPT = ROOT / "router.py"
ROUTER_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
ROUTER_HEALTH_URL = f"http://localhost:{ROUTER_PORT}/health"

CHECK_INTERVAL_SEC = 10
HEALTH_TIMEOUT_SEC = 5
CONSECUTIVE_FAILURES_BEFORE_RESTART = 3
RESTART_WINDOW_SEC = 120
MAX_RESTARTS_IN_WINDOW = 5
BACKOFF_BASE_SEC = 5
BACKOFF_MAX_SEC = 300
OLLAMA_RETRY_ATTEMPTS = 3
OLLAMA_RETRY_DELAY_SEC = 4


def log(event: str, **fields) -> None:
    """Append a structured line to self-heal.log and stderr."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = " ".join(f"{k}={v}" for k, v in fields.items())
    line = f"[{ts}] event={event} {payload}".rstrip() + "\n"
    try:
        with SELF_HEAL_LOG.open("a") as f:
            f.write(line)
    except OSError as e:
        print(f"[supervisor] log write failed: {e}", file=sys.stderr)
    print(line, end="", file=sys.stderr)


def router_alive() -> bool:
    try:
        with urlopen(ROUTER_HEALTH_URL, timeout=HEALTH_TIMEOUT_SEC) as r:
            return r.status == 200
    except (URLError, TimeoutError, OSError):
        return False


def wait_for_ollama() -> bool:
    """Try OLLAMA_RETRY_ATTEMPTS times to confirm Ollama is reachable."""
    for attempt in range(1, OLLAMA_RETRY_ATTEMPTS + 1):
        if memory_probe.ollama_running():
            if attempt > 1:
                log("ollama_recovered", attempts=attempt)
            return True
        log("ollama_unreachable", attempt=attempt)
        time.sleep(OLLAMA_RETRY_DELAY_SEC)
    return False


def kill_stuck_router() -> None:
    """Best-effort cleanup of orphaned router processes on our port."""
    try:
        out = subprocess.check_output(
            ["lsof", "-ti", f"tcp:{ROUTER_PORT}"], timeout=4
        ).decode().strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError):
        return
    for pid_str in out.splitlines():
        try:
            pid = int(pid_str)
            os.kill(pid, signal.SIGTERM)
            log("killed_stuck_pid", pid=pid)
        except (ValueError, ProcessLookupError, PermissionError):
            continue
    time.sleep(1)
    # Force-kill anything still alive on the port
    try:
        out = subprocess.check_output(
            ["lsof", "-ti", f"tcp:{ROUTER_PORT}"], timeout=4
        ).decode().strip()
        for pid_str in out.splitlines():
            try:
                os.kill(int(pid_str), signal.SIGKILL)
                log("force_killed_pid", pid=pid_str)
            except (ValueError, ProcessLookupError, PermissionError):
                continue
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError):
        pass


def spawn_router() -> subprocess.Popen | None:
    """Launch the router as a child process; stdout/stderr → router.log."""
    if not wait_for_ollama():
        log("router_start_blocked", reason="ollama_down")
        return None
    f = None
    try:
        f = ROUTER_LOG.open("a")
        proc = subprocess.Popen(
            [sys.executable, str(ROUTER_SCRIPT), str(ROUTER_PORT)],
            stdout=f, stderr=subprocess.STDOUT,
            cwd=str(ROOT),
            start_new_session=True,
        )
        f.close()  # parent no longer needs the fd; child has its own copy
        f = None
        log("router_spawned", pid=proc.pid, port=ROUTER_PORT)
        return proc
    except OSError as e:
        log("router_spawn_failed", error=str(e))
        return None
    finally:
        if f is not None:
            f.close()


def memory_pressure_label() -> str:
    snap = memory_probe.snapshot()
    if snap is None:
        return "unknown"
    if snap.percent_used >= 95:
        return "critical"
    if snap.percent_used >= 88:
        return "high"
    if snap.percent_used >= 75:
        return "elevated"
    return "ok"


def main() -> None:
    log("supervisor_start", port=ROUTER_PORT, pid=os.getpid())

    proc: subprocess.Popen | None = None
    consecutive_failures = 0
    restart_times: list[float] = []

    # Initial spawn
    if not router_alive():
        kill_stuck_router()
        proc = spawn_router()
        time.sleep(3)

    try:
        while True:
            time.sleep(CHECK_INTERVAL_SEC)

            mem = memory_probe.snapshot()
            pressure = memory_pressure_label()
            if mem is not None and pressure in ("high", "critical"):
                log("memory_pressure",
                    percent=mem.percent_used,
                    available_gb=round(mem.available_gb, 2),
                    label=pressure)

            if router_alive():
                consecutive_failures = 0
                continue

            consecutive_failures += 1
            log("router_health_fail",
                consecutive=consecutive_failures,
                threshold=CONSECUTIVE_FAILURES_BEFORE_RESTART)

            if consecutive_failures < CONSECUTIVE_FAILURES_BEFORE_RESTART:
                continue

            # Crash-loop protection
            now = time.time()
            restart_times = [t for t in restart_times
                             if now - t < RESTART_WINDOW_SEC]
            if len(restart_times) >= MAX_RESTARTS_IN_WINDOW:
                backoff = min(
                    BACKOFF_BASE_SEC * (2 ** (len(restart_times)
                                              - MAX_RESTARTS_IN_WINDOW)),
                    BACKOFF_MAX_SEC,
                )
                log("crash_loop_backoff",
                    restarts_in_window=len(restart_times),
                    backoff_sec=backoff)
                time.sleep(backoff)

            kill_stuck_router()
            proc = spawn_router()
            restart_times.append(time.time())
            consecutive_failures = 0
            time.sleep(3)

    except KeyboardInterrupt:
        log("supervisor_shutdown", reason="sigint")
        if proc and proc.poll() is None:
            proc.terminate()


if __name__ == "__main__":
    main()
