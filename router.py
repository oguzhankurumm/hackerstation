#!/usr/bin/env python3
"""
HackerStation AI Router — self-healing, memory-aware, 8GB-optimized.

Routes requests to the optimal local model based on task classification.

Models:
  - hackerstation-code (qwen3:8b)     → coding, scripting, exploits, payloads
  - hackerstation-reason (deepseek-r1:8b) → reasoning, analysis, planning

Self-healing in-process features:
  - memory watchdog → SAFE MODE switching
  - concurrency lock → at most one heavy generation at a time (8GB constraint)
  - fallback chain  → reasoning fail → coding fail → deterministic stub
  - structured self-heal log at logs/self-heal.log

API: http://localhost:8080
"""

from __future__ import annotations

import json
import re
import signal
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

import memory_probe

ROOT = Path(__file__).resolve().parent
LOGS = ROOT / "logs"
LOGS.mkdir(exist_ok=True)
SELF_HEAL_LOG = LOGS / "self-heal.log"

OLLAMA_URL = "http://localhost:11434"

MODELS = {
    "coding": "hackerstation-code",
    "reasoning": "hackerstation-reason",
}

# ----------------------------------------------------------------------------
# 8GB-aware system prompt — always appended to the user's system prompt.
# ----------------------------------------------------------------------------
LOW_MEMORY_PROMPT = """
You are running on a low-memory environment (8GB RAM).

Rules:
- prioritize stability over performance
- minimize reasoning depth
- avoid long outputs unless requested
- reduce context usage aggressively
- degrade gracefully under load
- prefer structured short answers
- if overloaded: reduce output length immediately
""".strip()

SAFE_MODE_SUFFIX = (
    "\n\n[SAFE MODE ACTIVE] Memory pressure is high. "
    "Respond in <=120 tokens. Skip chain-of-thought. "
    "Use bullet points. No code blocks longer than 10 lines."
)

BASE_SYSTEM_PROMPT = (
    "You are HackerStation AI — a senior security researcher and software engineer. "
    "You provide direct, technical, working solutions. Be concise and precise."
)

# ----------------------------------------------------------------------------
# Routing classifier
# ----------------------------------------------------------------------------
CODING_PATTERNS = re.compile(
    r"(write|code|script|exploit|payload|generate|implement|function|class|"
    r"reverse.?shell|bind.?shell|encode|decode|obfuscat|compile|parse|regex|"
    r"http|request|api|sql|inject|xss|csrf|buffer|overflow|shellcode|"
    r"python|bash|javascript|go|rust|ruby|perl|php|powershell|c\+\+|"
    r"brute.?force|crack|hash|encrypt|decrypt|tool|scanner|fuzzer|"
    r"docker|kubernetes|yaml|json|config|setup|install)",
    re.IGNORECASE,
)
REASONING_PATTERNS = re.compile(
    r"(analyze|plan|strategy|think|reason|explain|compare|evaluate|"
    r"attack.?chain|kill.?chain|threat.?model|risk|assess|audit|"
    r"evasion|bypass|detection|forensic|incident|investigate|"
    r"architecture|design|approach|methodology|framework|"
    r"why|how.?does|what.?if|pros.?and.?cons|trade.?off|"
    r"report|document|summarize|review|prioritize|triage)",
    re.IGNORECASE,
)


def classify_task(prompt: str) -> str:
    coding_score = len(CODING_PATTERNS.findall(prompt))
    reasoning_score = len(REASONING_PATTERNS.findall(prompt))
    if coding_score > reasoning_score:
        return "coding"
    if reasoning_score > coding_score:
        return "reasoning"
    return "coding"  # default to faster model on tie


# ----------------------------------------------------------------------------
# Self-heal log
# ----------------------------------------------------------------------------
_log_lock = threading.Lock()


def heal_log(event: str, **fields) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = " ".join(f"{k}={v}" for k, v in fields.items())
    line = f"[{ts}] event={event} {payload}".rstrip() + "\n"
    with _log_lock:
        try:
            with SELF_HEAL_LOG.open("a") as f:
                f.write(line)
        except OSError:
            pass


# ----------------------------------------------------------------------------
# State: SAFE MODE, latency window, concurrency lock
# ----------------------------------------------------------------------------
class RouterState:
    def __init__(self) -> None:
        self.safe_mode = False
        self.safe_mode_entered_at: Optional[float] = None
        self.last_memory_percent: float = 0.0
        self.recent_latencies: deque[float] = deque(maxlen=20)
        self.recent_errors: deque[float] = deque(maxlen=20)
        # Only ONE heavy request in-flight at a time on an 8GB box.
        self.gen_semaphore = threading.Semaphore(1)
        self.in_flight: int = 0
        self._in_flight_lock = threading.Lock()

    def record_latency(self, seconds: float) -> None:
        self.recent_latencies.append(seconds)

    def record_error(self) -> None:
        self.recent_errors.append(time.time())

    def avg_latency(self) -> float:
        if not self.recent_latencies:
            return 0.0
        return sum(self.recent_latencies) / len(self.recent_latencies)

    def recent_error_count(self, window_sec: float = 60.0) -> int:
        cutoff = time.time() - window_sec
        return sum(1 for t in self.recent_errors if t >= cutoff)


STATE = RouterState()


# ============================================================================
# >>> POLICY DECISION POINT — TODO(user) <<<
# ============================================================================
# These two functions decide WHEN to enter and WHEN to exit SAFE MODE.
# They are intentionally separate so you can implement *hysteresis* — the
# difference between the entry threshold and exit threshold prevents the
# router from flapping in/out of SAFE MODE every few seconds when memory
# hovers near the boundary.
#
# Inputs you have to work with on `state`:
#   state.last_memory_percent   → 0–100, current host RAM usage
#   state.avg_latency()         → rolling avg seconds for the last 20 requests
#   state.recent_error_count()  → errors in the last 60s
#   state.safe_mode             → current mode (True/False)
#   state.safe_mode_entered_at  → unix ts of last entry (or None)
#
# Trade-offs to consider:
#   - tight thresholds (e.g. enter@80, exit@78) → responsive but flaps
#   - loose thresholds (e.g. enter@88, exit@70) → stable but slow to recover
#   - latency-only signal misses memory-bound stalls
#   - memory-only signal misses CPU thrash
#   - a minimum dwell time prevents instant flap-out
#
# Reference defaults below are CONSERVATIVE — tune for your workload.
# ============================================================================
def should_enter_safe_mode(state: "RouterState") -> bool:
    """Return True if SAFE MODE should be activated.

    Default: enter when RAM ≥ 88% OR avg latency ≥ 30s OR ≥3 errors in last 60s.
    """
    if state.safe_mode:
        return False
    if state.last_memory_percent >= 88.0:
        return True
    if state.avg_latency() >= 30.0 and len(state.recent_latencies) >= 3:
        return True
    if state.recent_error_count() >= 3:
        return True
    return False


def should_exit_safe_mode(state: "RouterState") -> bool:
    """Return True if SAFE MODE can be safely deactivated.

    Default: require RAM ≤ 75%, latency ≤ 20s, 0 recent errors,
    and at least 30s of dwell time to prevent flapping.
    """
    if not state.safe_mode:
        return False
    if state.last_memory_percent > 75.0:
        return False
    if state.avg_latency() > 20.0:
        return False
    if state.recent_error_count() > 0:
        return False
    if state.safe_mode_entered_at is None:
        return True
    return (time.time() - state.safe_mode_entered_at) >= 30.0
# ============================================================================
# <<< end policy block >>>
# ============================================================================


def watchdog_loop(interval: float = 5.0) -> None:
    """Background thread: refresh memory snapshot, toggle SAFE MODE."""
    while True:
        try:
            snap = memory_probe.snapshot()
            if snap is not None:
                STATE.last_memory_percent = snap.percent_used

            if should_enter_safe_mode(STATE):
                STATE.safe_mode = True
                STATE.safe_mode_entered_at = time.time()
                heal_log("safe_mode_entered",
                         memory_pct=STATE.last_memory_percent,
                         avg_latency=round(STATE.avg_latency(), 2),
                         errors_60s=STATE.recent_error_count())
            elif should_exit_safe_mode(STATE):
                STATE.safe_mode = False
                STATE.safe_mode_entered_at = None
                heal_log("safe_mode_exited",
                         memory_pct=STATE.last_memory_percent)
        except Exception as e:
            heal_log("watchdog_error", error=type(e).__name__, msg=str(e)[:120])
        time.sleep(interval)


# ----------------------------------------------------------------------------
# Ollama I/O with retry + fallback
# ----------------------------------------------------------------------------
OLLAMA_RETRY_ATTEMPTS = 3
OLLAMA_RETRY_DELAY = 2.0


def _ollama_request(path: str, payload: dict) -> dict:
    req = Request(
        f"{OLLAMA_URL}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    timeout = 120 if STATE.safe_mode else 300
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _gen_options(safe_mode: bool) -> dict:
    if safe_mode:
        return {
            "num_ctx": 2048,
            "num_predict": 256,
            "temperature": 0.5,
            "top_p": 0.85,
        }
    return {
        "num_ctx": 4096,
        "num_predict": 1024,
        "temperature": 0.7,
    }


def _build_system(system: str) -> str:
    parts = [system or BASE_SYSTEM_PROMPT, LOW_MEMORY_PROMPT]
    if STATE.safe_mode:
        parts.append(SAFE_MODE_SUFFIX)
    return "\n\n".join(parts)


def query_with_retry(model: str, prompt: str, system: str,
                     chat_messages: Optional[list] = None) -> dict:
    """Try up to OLLAMA_RETRY_ATTEMPTS times. Return error dict on full failure."""
    last_err: Optional[str] = None
    for attempt in range(1, OLLAMA_RETRY_ATTEMPTS + 1):
        try:
            if chat_messages is not None:
                payload = {
                    "model": model,
                    "messages": chat_messages,
                    "stream": False,
                    "options": _gen_options(STATE.safe_mode),
                }
                return _ollama_request("/api/chat", payload)
            payload = {
                "model": model,
                "prompt": prompt,
                "system": _build_system(system),
                "stream": False,
                "options": _gen_options(STATE.safe_mode),
            }
            return _ollama_request("/api/generate", payload)
        except (URLError, TimeoutError, OSError) as e:
            last_err = str(e)
            heal_log("ollama_retry", model=model, attempt=attempt, err=last_err[:120])
            time.sleep(OLLAMA_RETRY_DELAY * attempt)
        except json.JSONDecodeError as e:
            last_err = f"bad_json: {e}"
            heal_log("ollama_bad_json", model=model, attempt=attempt)
            time.sleep(OLLAMA_RETRY_DELAY * attempt)
    return {"error": last_err or "unknown", "model": model}


def deterministic_fallback(prompt: str) -> dict:
    """Last-resort response when both models are unreachable."""
    summary = (prompt or "").strip().splitlines()[0][:140]
    return {
        "response": (
            "[SERVICE DEGRADED] HackerStation router could not reach any model. "
            f"Received prompt: \"{summary}…\". "
            "Try: `./start.sh status` to inspect Ollama, then retry."
        ),
        "model": "deterministic-stub",
        "done": True,
        "_router": {"degraded": True},
    }


def routed_generate(task_type: str, prompt: str, system: str) -> tuple[dict, str, bool]:
    """Run with fallback chain. Returns (result, model_used, fell_back)."""
    primary = MODELS[task_type]
    fallback = MODELS["coding"]  # coding model is always the safety net

    result = query_with_retry(primary, prompt, system)
    if "error" not in result:
        return result, primary, False

    if primary != fallback:
        heal_log("fallback_to_coding", from_model=primary, reason=result["error"][:80])
        result = query_with_retry(fallback, prompt, system)
        if "error" not in result:
            return result, fallback, True

    heal_log("deterministic_fallback", reason=result.get("error", "")[:80])
    STATE.record_error()
    return deterministic_fallback(prompt), "deterministic-stub", True


def routed_chat(task_type: str, messages: list, system: str) -> tuple[dict, str, bool]:
    primary = MODELS[task_type]
    fallback = MODELS["coding"]
    sys_text = _build_system(system)
    msgs = list(messages)
    if not any(m.get("role") == "system" for m in msgs):
        msgs.insert(0, {"role": "system", "content": sys_text})

    result = query_with_retry(primary, "", "", chat_messages=msgs)
    if "error" not in result:
        return result, primary, False
    if primary != fallback:
        heal_log("fallback_to_coding_chat", from_model=primary,
                 reason=result["error"][:80])
        result = query_with_retry(fallback, "", "", chat_messages=msgs)
        if "error" not in result:
            return result, fallback, True
    heal_log("deterministic_fallback_chat", reason=result.get("error", "")[:80])
    STATE.record_error()
    last_user = next((m["content"] for m in reversed(msgs)
                     if m.get("role") == "user"), "")
    return deterministic_fallback(last_user), "deterministic-stub", True


# ----------------------------------------------------------------------------
# HTTP handler
# ----------------------------------------------------------------------------
SEMAPHORE_TIMEOUT_SEC = 90
MAX_BODY_SIZE = 1024 * 1024  # 1 MB — enough for any reasonable prompt on 8GB


class RouterHandler(BaseHTTPRequestHandler):
    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self._send_json({
                "status": "ok",
                "models": MODELS,
                "safe_mode": STATE.safe_mode,
                "memory_percent": STATE.last_memory_percent,
                "ollama_alive": memory_probe.ollama_running(),
                "avg_latency_sec": round(STATE.avg_latency(), 2),
                "errors_60s": STATE.recent_error_count(),
            })
        elif self.path == "/status":
            snap = memory_probe.snapshot()
            self._send_json({
                "safe_mode": STATE.safe_mode,
                "safe_mode_entered_at": STATE.safe_mode_entered_at,
                "memory": {
                    "percent_used": STATE.last_memory_percent,
                    "available_gb": round(snap.available_gb, 2) if snap else None,
                    "total_gb": round(snap.total_gb, 2) if snap else None,
                    "source": snap.source if snap else None,
                },
                "latency": {
                    "avg_sec": round(STATE.avg_latency(), 2),
                    "samples": list(STATE.recent_latencies),
                },
                "errors_60s": STATE.recent_error_count(),
                "in_flight": STATE.in_flight,
                "ollama_alive": memory_probe.ollama_running(),
            })
        elif self.path == "/models":
            try:
                with urlopen(f"{OLLAMA_URL}/api/tags", timeout=5) as resp:
                    self._send_json(json.loads(resp.read().decode()))
            except (URLError, TimeoutError, OSError) as e:
                self._send_json({"error": str(e)}, 502)
        else:
            self._send_json({
                "service": "HackerStation AI Router",
                "version": "2.0.0",
                "endpoints": {
                    "POST /generate": "auto-routed generation (with fallback)",
                    "POST /chat": "auto-routed chat (with fallback)",
                    "POST /generate/coding": "force coding model",
                    "POST /generate/reasoning": "force reasoning model",
                    "GET  /health": "health snapshot",
                    "GET  /status": "detailed runtime + memory state",
                    "GET  /models": "list Ollama models",
                },
                "safe_mode": STATE.safe_mode,
            })

    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > MAX_BODY_SIZE:
                self._send_json({"error": "body_too_large",
                                 "max_bytes": MAX_BODY_SIZE}, 413)
                return
            body = (json.loads(self.rfile.read(content_length).decode())
                    if content_length else {})
        except (ValueError, json.JSONDecodeError):
            self._send_json({"error": "invalid JSON body"}, 400)
            return

        if self.path == "/generate/coding":
            task_type = "coding"
        elif self.path == "/generate/reasoning":
            task_type = "reasoning"
        elif self.path in ("/generate", "/chat"):
            prompt_for_class = body.get("prompt", "") or ""
            if not prompt_for_class and "messages" in body:
                prompt_for_class = " ".join(
                    m.get("content", "") for m in body["messages"]
                )
            task_type = classify_task(prompt_for_class)
        else:
            self._send_json({"error": "Unknown endpoint"}, 404)
            return

        # Refuse new heavy work if memory is critical
        if STATE.last_memory_percent >= 95.0:
            heal_log("rejected_memory_critical",
                     memory_pct=STATE.last_memory_percent)
            self._send_json({
                "error": "memory_critical",
                "memory_percent": STATE.last_memory_percent,
                "hint": "Wait a few seconds and retry; SAFE MODE is active.",
            }, 503)
            return

        # Concurrency gate — only one heavy gen at a time on 8GB
        acquired = STATE.gen_semaphore.acquire(timeout=SEMAPHORE_TIMEOUT_SEC)
        if not acquired:
            heal_log("rejected_busy", task_type=task_type)
            self._send_json({
                "error": "router_busy",
                "hint": "another generation is in flight; retry shortly",
            }, 503)
            return

        with STATE._in_flight_lock:
            STATE.in_flight += 1
        start = time.time()
        try:
            system = body.get("system", BASE_SYSTEM_PROMPT)

            if self.path == "/chat" or "messages" in body:
                messages = body.get("messages", [])
                result, model_used, fell_back = routed_chat(
                    task_type, messages, system
                )
            else:
                prompt = body.get("prompt", "")
                result, model_used, fell_back = routed_generate(
                    task_type, prompt, system
                )

            elapsed = time.time() - start
            STATE.record_latency(elapsed)

            result["_router"] = {
                "task_type": task_type,
                "model_used": model_used,
                "fell_back": fell_back,
                "safe_mode": STATE.safe_mode,
                "elapsed_seconds": round(elapsed, 2),
                "memory_percent": STATE.last_memory_percent,
            }
            self._send_json(result)
        except Exception as e:
            STATE.record_error()
            heal_log("handler_exception",
                     err=type(e).__name__, msg=str(e)[:160])
            self._send_json({"error": "internal", "type": type(e).__name__}, 500)
        finally:
            with STATE._in_flight_lock:
                STATE.in_flight -= 1
            STATE.gen_semaphore.release()

    def log_message(self, fmt, *args):
        print(f"[Router] {self.address_string()} - {fmt % args}")


def _handle_sigterm(signum, frame):
    heal_log("router_shutdown", reason="sigterm")
    sys.exit(0)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    signal.signal(signal.SIGTERM, _handle_sigterm)

    # Boot watchdog thread
    t = threading.Thread(target=watchdog_loop, daemon=True, name="watchdog")
    t.start()

    heal_log("router_boot", port=port, version="2.0.0")

    server = HTTPServer(("0.0.0.0", port), RouterHandler)
    print(f"🚀 HackerStation AI Router v2.0 (self-healing) on http://localhost:{port}")
    print(f"   Coding model:    {MODELS['coding']}")
    print(f"   Reasoning model: {MODELS['reasoning']}")
    print(f"   Ollama backend:  {OLLAMA_URL}")
    print(f"   Self-heal log:   {SELF_HEAL_LOG}")
    print(f"   Watchdog:        memory + latency + error rate (5s tick)")
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        heal_log("router_shutdown", reason="sigint")
        print("\nShutting down router...")
        server.server_close()


if __name__ == "__main__":
    main()
