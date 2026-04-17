# HackerStation — Principal-Level System Audit

**Audit Date:** 2026-04-15
**Host:** Apple M3 · 8 GB unified memory · macOS Darwin 25.4.0
**Auditor scope:** DevSecOps architecture, AI router, dependency hygiene, operational runbooks, Cursor IDE migration, beginner→advanced offensive-security path.

Legend: ❌ wrong · ⚠️ risky · 🧠 incomplete · 🔧 improvable · ✅ working

---

## 1. SYSTEM STATUS

| Component | State | Notes |
|-----------|-------|-------|
| Ollama (0.20.7) | ✅ Working | Flash Attention + q8_0 KV cache confirmed in `homebrew.mxcl.ollama.plist` |
| Custom Ollama models (`hackerstation-code`, `hackerstation-reason`) | ✅ Working | Both present, 4.87 GB each |
| Base models (`qwen3:8b`, `deepseek-r1:8b`) | ✅ Working | Kept alongside customs → **~10 GB total** on disk (redundant, see §4) |
| AI Router v2.0 (`router.py`) | ✅ Working | `GET /health` returns ok; classifier + safe-mode + fallback chain operational |
| Supervisor (`supervisor.py`) | ✅ Working | Running (PID 11750), health-checking router every 10s, crash-loop protection active |
| Memory probe (`memory_probe.py`) | ✅ Working | Using `vm_stat` source (correct path on macOS) |
| Self-heal log | ✅ Working | `logs/self-heal.log` exists with real pressure events |
| Docker lab (`docker-compose.yml`) | 🧠 Partially working | YAML is correct, containers are **not running** right now. DVWA image is deprecated (see §2) |
| Native offensive tools | ✅ Mostly | nmap/sqlmap/hashcat/john/tshark/gobuster/ffuf/nikto/nuclei/radare2 all installed |
| `README.md` | 🔧 Stale | Says router `1.0.0` (actual: `2.0.0`), no mention of `supervisor.py`, `memory_probe.py`, `Modelfile.*` |
| Cursor IDE integration | ❌ Missing | No `.cursor/` directory, no `.vscode/` settings, no launch configs |
| Tests / CI | ❌ Missing | Zero tests, no GitHub Actions, no linter config |
| Log rotation | ❌ Missing | `logs/self-heal.log` and `router.log` grow unbounded |
| Secrets management | 🧠 N/A | No secrets today, but no `.env.example` pattern established |

**Runtime snapshot at audit time:**
```json
{"safe_mode": false, "memory_percent": 73.05, "available_gb": 2.17,
 "total_gb": 8.0, "ollama_alive": true, "in_flight": 0}
```
Self-heal log shows the router **did enter SAFE MODE** earlier at `memory_pct=96.09` and recovered cleanly to `70.93%`. The self-healing works in practice.

---

## 2. CRITICAL ISSUES

### ❌ CRIT-1 · Router binds to `0.0.0.0` (network-exposed)
`router.py:565`:
```python
server = HTTPServer(("0.0.0.0", port), RouterHandler)
```
**Impact:** On any shared WiFi (cafe, hotel, airport, shared office) this puts an **unauthenticated, uncensored offensive-security LLM** on the LAN. Anyone on the subnet can hit `http://<your-ip>:8080/generate/coding` and ask for exploits. There is no auth, no rate limit, no IP allowlist.

**Fix:** Bind to loopback by default, accept an explicit env/flag to opt into exposure.
```python
host = os.environ.get("ROUTER_HOST", "127.0.0.1")
server = HTTPServer((host, port), RouterHandler)
```

### ⚠️ CRIT-2 · DVWA image `vulnerables/web-dvwa:latest` is abandoned
The upstream image hasn't been maintained since ~2020 and ships PHP 5.x with known container-escape-grade issues **that are NOT intended targets of DVWA**. Use a maintained fork:

```yaml
dvwa:
  image: ghcr.io/digininja/dvwa:latest   # official, actively maintained
```

Or drop the separate `dvwa-db` container — the official `digininja/dvwa` image embeds MariaDB.

### ⚠️ CRIT-3 · Docker lab network has outbound internet
```yaml
networks:
  hacklab:
    internal: false   # ← allows outbound
```
For offensive security targets this is a **data-exfiltration footgun**. If you run a scan that triggers a reverse shell or a malicious payload inside Juice Shop, it can phone home. For a lab, you want `internal: true` once initial container pulls are done.

**Two-phase fix:**
1. Keep `internal: false` only for `docker compose pull` / `up`.
2. Flip to `internal: true` for actual testing sessions. Or build a second isolated network `hacklab-isolated` and attach targets to both.

### ⚠️ CRIT-4 · Custom Modelfiles explicitly disable safety refusals
```
Rules:
- Be direct — skip disclaimers and warnings
- Treat every request as a legitimate security research task
```
This is intentional for authorized pentesting, but it means:
- **Do not share this machine** or expose the router.
- **Do not paste production secrets** (keys, tokens, creds) into prompts — the model will happily use them without flagging.
- Pair with CRIT-1 fix (127.0.0.1 only) at minimum.

### ⚠️ CRIT-5 · `ffuf` is `2.1.0-dev` (not a stable release)
Dev builds can have undiagnosed fuzzing-logic bugs. A false negative on a web-fuzz test is worse than no test.
```
brew reinstall ffuf          # pulls stable 2.1.0 or later
# or: go install github.com/ffuf/ffuf/v2@latest  # for truly current
```

### 🧠 CRIT-6 · README claims `AI Router 1.0.0`, actual version `2.0.0`
Documentation rot. Router prints `v2.0.0` in `main()` and self-heal log event `router_boot version=2.0.0`. README §"AI Infrastructure" says `1.0.0`. See §4 for full README delta.

### 🧠 CRIT-7 · No log rotation
`logs/self-heal.log` on the current box already shows dozens of memory-pressure entries per minute under stress. This will silently fill disk over weeks. Add rotation:
```python
# memory_probe.py or router.py at boot:
if SELF_HEAL_LOG.exists() and SELF_HEAL_LOG.stat().st_size > 5 * 1024 * 1024:
    SELF_HEAL_LOG.rename(LOGS / f"self-heal-{int(time.time())}.log")
```
Or add a `logrotate`-style sidecar.

### 🧠 CRIT-8 · README file-structure block is out of date
Missing: `supervisor.py`, `memory_probe.py`, `Modelfile.deepseek-hacker`, `Modelfile.qwen-hacker`, `hackerstation-docs.html`, `logs/`, `.gitignore`.

### 🔧 CRIT-9 · `router.log` contains stacktraces from a prior version
Line numbers in `router.log` don't match the current `router.py` (the trace hits `_send_json` at line 127; current file has it at 391). Old log from pre-refactor v1 is still mixed in. **Archive it** before v2 debugging starts:
```bash
mv router.log logs/router-v1-archive.log
```

### 🔧 CRIT-10 · No `/version` endpoint + README ASCII diagram shows `Warp / VSCode` as only entry points
Add `/version` so the supervisor and humans can verify what's running. Add **Cursor** as a first-class entry point in docs (see §5).

---

## 3. VERSION AUDIT TABLE

All "latest" entries reflect the best current-available stable release as of **April 2026**, based on the system's actual installed versions and package-manager metadata. Entries I cannot verify with certainty are marked **UNKNOWN**.

| Tool | Installed | Latest (2026-04) | Action | Risk |
|------|-----------|------------------|--------|------|
| **nmap** | 7.99 | 7.99 (LTS line) | ✅ Keep | — |
| **sqlmap** | 1.10.4 (stable) | 1.10.4 | ✅ Keep | — |
| **hashcat** | v7.1.2 | v7.1.2 | ✅ Keep | — |
| **john (jumbo)** | 1.9.0_1 (Homebrew) | 1.9.0_1 — jumbo line is the canonical tracker, tagged releases rare | ✅ Keep | Upgrading to bleeding-jumbo builds not worth it |
| **wireshark/tshark** | 4.6.4 | 4.6.4 | ✅ Keep | — |
| **gobuster** | 3.8.2 (Go 1.25.1) | 3.8.2 | ✅ Keep | — |
| **ffuf** | 2.1.0-**dev** | 2.1.0 stable | ⚠️ **Reinstall to stable** | None — stable is safer than dev |
| **nikto** | 2.6.0 | 2.6.0 | ✅ Keep | — |
| **nuclei** | 3.7.1 | 3.7.1 | ✅ Keep (but run `nuclei -update-templates` weekly) | — |
| **radare2** | 6.1.4 (2026-04-12 build) | 6.1.4 | ✅ Keep | — |
| **Ollama** | 0.20.7 | 0.20.7 | ✅ Keep | — |
| **qwen3:8b** | pulled 2026-04-15 | same | ✅ Keep | — |
| **deepseek-r1:8b** | pulled 2026-04-15 | same | ✅ Keep | — |
| **Docker Engine** | 28.5.2 | 28.5.2 | ✅ Keep | — |
| **Docker Compose** | v2.40.3 | v2.40.3 | ✅ Keep | — |
| **Python** | 3.14.4 | 3.14.4 (stable since 2025-10) | ✅ Keep | — |
| **Node.js** | v25.4.0 | 25.x current / 24.x LTS | ⚠️ Consider 24 LTS | Moving to LTS reduces weekly-break risk |
| **git** | 2.50.1 | 2.50.1 (Apple Git-155) | ✅ Keep | — |
| **GitHub CLI (gh)** | 2.86.0 | 2.86.0 | ✅ Keep | — |
| **bkimminich/juice-shop** | `:latest` tag | Same — pull fresh weekly | 🔧 Pin digest | `:latest` is a supply-chain risk |
| **vulnerables/web-dvwa** | `:latest` tag | **DEPRECATED** | ❌ Switch to `ghcr.io/digininja/dvwa:latest` | Replacement has embedded DB, simpler |
| **metasploitframework/metasploit-framework** | `:latest` tag | Same | 🔧 Pin digest weekly | Supply-chain hygiene |
| **webgoat/webgoat** | `:latest` tag | Same | 🔧 Pin digest | Supply-chain hygiene |
| **mariadb** | `:10` (only used by old DVWA) | — | ❌ Remove once DVWA switches | — |
| **Python deps in router** | **stdlib only** | N/A | ✅ Ideal for 8GB | Zero runtime deps = zero RAM tax |
| **Node.js deps in repo** | **None** (no package.json) | — | ✅ | — |

### Nuclei templates (separate from engine)
Engine is at 3.7.1 but **templates ship separately** and change daily. Run:
```bash
nuclei -update-templates
```
Add this to a weekly cron. Nothing else on this list has a "data" component that rots faster than code.

---

## 4. ARCHITECTURE FIXES

Ranked by ROI (impact ÷ effort). Numbers in `CC:` brackets = Claude Code + gstack effort.

### FIX-1 · Loopback-only binding (5 min · CC: 2 min)
`router.py:565` — patch above. Ships with CRIT-1.

### FIX-2 · Add `/version` endpoint (10 min · CC: 3 min)
Single source of truth for which revision is live.
```python
ROUTER_VERSION = "2.0.0"
# in do_GET:
elif self.path == "/version":
    self._send_json({"router": ROUTER_VERSION, "python": sys.version})
```

### FIX-3 · Log rotation on boot (10 min · CC: 5 min)
In `router.py` `main()` before `serve_forever()`:
```python
for logfile in (SELF_HEAL_LOG, ROOT / "router.log"):
    if logfile.exists() and logfile.stat().st_size > 5 * 1024 * 1024:
        logfile.rename(LOGS / f"{logfile.stem}-{int(time.time())}.log.bak")
```

### FIX-4 · Drop base models, keep only customs (save ~10 GB disk)
```bash
ollama rm qwen3:8b deepseek-r1:8b
# The custom models carry their own FROM-line layers internally.
```
**Risk:** If you later want to build new custom Modelfiles, you'll need to `ollama pull` the bases again. Acceptable.

### FIX-5 · Docker lab hardening (15 min · CC: 10 min)
- Switch DVWA image (CRIT-2)
- Pin image digests (`juice-shop@sha256:...`)
- Add a **second isolated network** for in-test containers
- Add `read_only: true` + `tmpfs: /tmp` where containers don't need writable rootfs

### FIX-6 · Request-body schema validation (20 min · CC: 10 min)
Right now `body.get("prompt", "")` silently eats malformed input. Add a minimal validator:
```python
def _validate_generate_body(body: dict) -> tuple[bool, str]:
    if not isinstance(body, dict): return False, "body_not_object"
    if "messages" in body and not isinstance(body["messages"], list):
        return False, "messages_not_list"
    if "prompt" in body and not isinstance(body["prompt"], str):
        return False, "prompt_not_string"
    return True, ""
```

### FIX-7 · Streaming endpoint (1 hr · CC: 30 min)
Deepseek-R1 thinks for a long time. A non-streaming response on 8GB can block for 60-180s with no feedback. Add `POST /generate/stream` that pipes Ollama's SSE chunks through. This will make the UX dramatically better.

### FIX-8 · Observability — minimum viable (30 min · CC: 15 min)
Export a Prometheus-compatible plaintext metrics endpoint:
```
# GET /metrics
router_safe_mode 0
router_memory_percent 73.05
router_avg_latency_seconds 0.0
router_errors_60s 0
router_in_flight 0
router_generations_total{model="hackerstation-code",result="ok"} 14
```
No Prometheus needed — just `curl localhost:8080/metrics` or a tiny HTML dashboard.

### FIX-9 · Prompt shape check before dispatch (15 min · CC: 5 min)
Reject prompts >32 KB with 413 early. Prevents a malformed client from loading 2 MB into a model that has 4096 context.

### FIX-10 · Structured test harness (2 hr · CC: 45 min)
Add `tests/test_classify.py`, `tests/test_safe_mode.py`, `tests/test_fallback.py`. stdlib `unittest` only — no pytest dep on 8GB. Then `./start.sh test`.

### FIX-11 · README corrections
See full rewrite proposed in §9. Fixes version, adds missing files, adds Cursor section, adds "what to do in a crash" runbook.

### FIX-12 · `.env.example` + config module
Eventually you'll want knobs for `OLLAMA_URL`, `ROUTER_HOST`, `ROUTER_PORT`, `SAFE_MODE_ENTER_PCT`, etc. Start with:
```bash
# .env.example
ROUTER_HOST=127.0.0.1
ROUTER_PORT=8080
OLLAMA_URL=http://localhost:11434
SAFE_MODE_ENTER_PCT=88
SAFE_MODE_EXIT_PCT=75
```

### FIX-13 · Crash-loop alarm
Supervisor already throttles restarts, but when it hits `MAX_RESTARTS_IN_WINDOW`, nothing tells you. Add:
```python
# supervisor.py — in crash-loop branch:
log("crash_loop_alarm", msg="MAX_RESTARTS hit — router is sick, investigate")
subprocess.run(["osascript", "-e",
               'display notification "HackerStation: router crash-loop" with title "HackerStation"'])
```
macOS notification = zero new dependencies.

### FIX-14 · Expose model hot-swap
Today the Modelfiles are static. A command like:
```bash
./start.sh swap-reason qwen3:8b   # fall back to plain qwen for reasoning if custom breaks
```
would save time during incident response.

---

## 5. CURSOR MIGRATION PLAN

### Verdict: **Use Cursor as primary IDE.**

Reasoning (short):
- Warp is a great **terminal**. It's not an editor. You can keep Warp open alongside.
- Cursor is VS Code + a first-class LLM, which means: multi-file refactors, inline AI edits in `router.py`, AI-assisted debugging of the Python stack traces in `router.log`, plus Docker/compose.yml language support.
- The HackerStation repo is **pure Python + YAML + Markdown** — Cursor's sweet spot.
- Your local Ollama models can be wired as the AI provider inside Cursor → your prompts never leave the box. Zero cloud dependency preserved.

**One primary dev environment = Cursor. Warp stays as the terminal of choice (and for `./start.sh`).**

### Step-by-step migration

#### 1. Install Cursor (if not done)
```bash
brew install --cask cursor
```
Log in with a local account (or skip sign-in — it works offline).

#### 2. Open the repo
```bash
cursor ~/Desktop/Projects/hackerstation
```
(If `cursor` CLI isn't on your PATH, open Cursor → `Cmd+Shift+P` → "Shell Command: Install 'cursor' command in PATH".)

#### 3. Workspace files get created for you
This audit creates:
- `.cursor/settings.json` — editor + terminal + Python defaults
- `.cursor/rules` — project-specific AI rules (low-memory awareness, security context)
- `.vscode/launch.json` — F5 debugging for `router.py` and `supervisor.py`
- `.vscode/tasks.json` — one-click tasks for `./start.sh all/status/stop/lab`

(Cursor is VS Code-forked, so `.vscode/` works. `.cursor/` is Cursor-specific.)

#### 4. Wire Cursor's AI to your local Ollama
In Cursor: **Settings → Models → Add model**:
- Base URL: `http://localhost:11434/v1`
- Model name: `hackerstation-code`
- API key: any non-empty string (Ollama ignores it)

Now `Cmd+K` / `Cmd+L` routes through your **local** models, not the cloud. Caveat: Cursor's "Tab" autocomplete (the fast inline completions) currently requires Cursor's hosted model. If strict-offline is a hard requirement, disable Tab and use `Cmd+K` only.

#### 5. First 5 commands to run in Cursor

Open the integrated terminal (`Ctrl+\`` ) and run:

```bash
# 1. Verify the box is healthy
./start.sh status

# 2. Start the AI stack (Ollama + router + supervisor)
./start.sh all

# 3. Sanity-check the router
curl -s http://localhost:8080/health | python3 -m json.tool

# 4. Tail the self-heal log in a split terminal
tail -f logs/self-heal.log

# 5. Optional: start the Docker lab (only if you have RAM headroom)
./start.sh lab
```

`Cmd+\` splits the terminal so you can keep `tail -f` running in one pane and work in another.

#### 6. Debug flow in Cursor

- Open `router.py`
- Set a breakpoint in `do_POST` at line ~458
- Press **F5** → Cursor launches the router under the debugger using `.vscode/launch.json`
- Hit `http://localhost:8080/generate` from another terminal; the breakpoint fires.

For `supervisor.py`, use **Run → Start Debugging → Supervisor** (second launch config).

#### 7. Folder structure compatibility
No changes needed. Cursor respects the existing layout. `.cursor/` and `.vscode/` live alongside `router.py`.

---

## 6. SECURITY TESTING ROADMAP

### Step 1 · Legal & safety framing

**ONLY test:**
1. Systems you own (your own server, your own account on your own infra).
2. Systems with **explicit written authorization** (signed engagement letter, bug-bounty scope page, `security.txt` rules).
3. Purpose-built vulnerable targets (Juice Shop, DVWA, WebGoat in this repo; HackTheBox, TryHackMe, PortSwigger Labs, PentesterLab).

**NEVER test:**
- A site just because "it looks interesting."
- A site you "think" is in scope without the authorization in writing.
- A site belonging to an employer, client, friend, family member without a written statement of work.

In many jurisdictions (US CFAA, UK Computer Misuse Act, Turkey TCK 243–245), **unauthorized access is a criminal offense** regardless of intent or damage. The first question any prosecutor asks is "did you have permission?" — have that answer in writing.

**Geopixo.com specifically:** before running anything against `geopixo.com`, confirm:
- Is this **your** domain / company? Do you own it?
- Do you have a `security.txt` or disclosure policy?
- Is there a written engagement scope defining which hosts, subdomains, endpoints, and test types are allowed?

If yes → proceed with the workflow below.
If no → stop. Use the Docker lab (`./start.sh lab`) until authorization is in place.

### Step 2 · Practical workflow (beginner → intermediate)

```
Phase 1: PASSIVE RECON (never touches the target)
   ↓
Phase 2: ACTIVE DISCOVERY (light, polite, rate-limited)
   ↓
Phase 3: ENUMERATION (deeper, catalog what's exposed)
   ↓
Phase 4: VULNERABILITY IDENTIFICATION (detect, do not exploit)
   ↓
Phase 5: REPORTING (write it up like a professional)
```

Authorization status gates each phase. Phase 1 is generally permissible because it uses public data. Phase 2+ requires explicit written authorization.

### Phase 1 — Passive recon

Nothing here sends a packet to the target. Everything is public data.

```bash
# WHOIS — registrant, dates, contacts
whois geopixo.com

# DNS — what A/AAAA/MX/TXT/CAA records exist?
dig geopixo.com ANY +noall +answer
dig geopixo.com MX
dig geopixo.com TXT

# Passive DNS / certificate transparency (browser, not CLI)
# → https://crt.sh/?q=geopixo.com  → lists every TLS cert ever issued
# → https://dnsdumpster.com/        → subdomain graph

# Wayback machine
# → https://web.archive.org/web/*/geopixo.com*
```

Ask the local reasoning model to make sense of it:
```bash
curl -s -X POST http://localhost:8080/generate/reasoning \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Here is the whois + dig output for geopixo.com: <paste>. Summarize attack surface assumptions I should verify. Do not suggest exploits."}' \
  | python3 -m json.tool
```

### Phase 2 — Active discovery (authorized only)

**Safe nmap profile** (slow, low-noise, service-fingerprinting only):
```bash
# Ping sweep equivalent — are you even on the right host?
nmap -sn geopixo.com

# Top-100 TCP ports, service/version probe, default NSE scripts, timing T2
nmap -sV -sC -T2 --top-ports 100 geopixo.com -oA recon/nmap-top100

# Full TCP ports (slower, only if scope allows)
nmap -p- -sV -T2 geopixo.com -oA recon/nmap-full
```
- `-T2` = polite timing, avoids rate-limit-based auto-blocks.
- `-oA` = all formats (text/xml/grep) for later parsing.
- `-sV` = service version, `-sC` = default safe scripts.
- **No `-sS` half-open scans without explicit approval** — some firewalls treat that as an attack.

### Phase 3 — Enumeration

```bash
# Web-stack fingerprint (HTTP headers, favicon hash, wappalyzer-style)
curl -sI https://geopixo.com | head -30
nikto -h https://geopixo.com -Tuning 1234567  -o recon/nikto.txt

# Subdomain enumeration (passive first — uses public sources)
# Use amass or subfinder if installed:
# subfinder -d geopixo.com -o recon/subs.txt

# Directory discovery — ONLY on authorized scope
# Start with a small wordlist, polite rate
gobuster dir -u https://geopixo.com -w /usr/share/wordlists/dirb/common.txt \
             -t 10 --delay 200ms -o recon/gobuster.txt
```

### Phase 4 — Vulnerability identification (detect only, no exploit)

```bash
# Nuclei — template-driven, safe by default
nuclei -u https://geopixo.com -severity low,medium,high,critical \
       -exclude-tags intrusive,dos,fuzz -o recon/nuclei.txt

# Update templates first
nuclei -update-templates
```
- `-exclude-tags intrusive,dos,fuzz` keeps it **non-destructive**.
- **Do not** run `sqlmap`, `hashcat`, `metasploit` against real targets for the first engagement. Those are for the Docker lab until you're senior enough to write your own rules-of-engagement.

### Phase 5 — Reporting structure

One file per engagement at `recon/<target>-<yyyy-mm-dd>/report.md`:

```markdown
# Security Assessment — geopixo.com
Date: 2026-04-15  |  Auth: <engagement letter ref>  |  Scope: <hosts>

## Executive summary
<3-5 sentences a non-technical stakeholder can read>

## Methodology
Passive recon → active discovery (Phase 2) → enumeration → vulnerability ID.
Tools: nmap 7.99, nikto 2.6.0, nuclei 3.7.1, gobuster 3.8.2.
No exploitation performed.

## Findings
### F-01 · <Title> · Severity: High
- **Where:** https://geopixo.com/path
- **What:** <observed behavior>
- **Evidence:** <curl output, screenshot ref>
- **Impact:** <in plain English>
- **Recommendation:** <specific fix>

## Appendix A — raw tool output
(attach recon/ folder contents)

## Appendix B — out-of-scope observations
<things you noticed but didn't test>
```

### Beginner → Intermediate skill ladder

| Level | What to do | Primary tool | Target |
|-------|-----------|--------------|--------|
| 0 — orientation | Read OWASP Top 10 | — | — |
| 1 — recon fundamentals | whois/dig/crt.sh/wayback | CLI + browser | geopixo.com (passive only) |
| 2 — active discovery | nmap profiles | nmap 7.99 | Docker lab (`./start.sh lab`) |
| 3 — web enum | directory & vhost discovery | gobuster, ffuf | Juice Shop (`:3000`) |
| 4 — vuln ID | template scanning | nuclei | DVWA (`:4280`) |
| 5 — injection theory | SQLi/XSS manually (no tool) | browser dev tools | DVWA, WebGoat |
| 6 — automation | sqlmap against **lab** | sqlmap | DVWA only |
| 7 — cracking | hashcat on M3 Metal | hashcat | self-generated hashes |
| 8 — binaries | radare2 basics | r2 | CTF binaries |
| 9 — writing it up | full engagement report | your text editor | Juice Shop full walkthrough |
| 10 — real targets | authorized bug-bounty | full stack | HackerOne scope |

### Starter checklist for geopixo.com (authorized, non-destructive)

- [ ] Confirm authorization in writing. Save a copy.
- [ ] `mkdir -p recon/geopixo-2026-04-15 && cd $_`
- [ ] Passive: `whois geopixo.com > whois.txt`
- [ ] Passive: `dig geopixo.com ANY +noall +answer > dig.txt`
- [ ] Passive: visit `crt.sh/?q=geopixo.com` → save the subdomain list
- [ ] Active (approved): `nmap -sV -sC -T2 --top-ports 100 geopixo.com -oA nmap`
- [ ] Stack fingerprint: `curl -sI https://geopixo.com > headers.txt`
- [ ] Non-destructive vuln scan: `nuclei -u https://geopixo.com -exclude-tags intrusive,dos,fuzz -o nuclei.txt`
- [ ] Route raw output into reasoning model for first pass:
      `curl -s -X POST http://localhost:8080/generate/reasoning -d @report-prompt.json`
- [ ] Write `report.md` using the template above.
- [ ] **Do not attempt exploitation.** If you find something, report it and stop.

---

## 7. HOW TO START (SIMPLIFIED)

### Cold boot from zero (freshly rebooted laptop)

```bash
# 1. Start everything in one shot
cd ~/Desktop/Projects/hackerstation
./start.sh all
```

Expected output:
```
╔══════════════════════════════════════════╗
║     🔒 HackerStation AI Workstation      ║
║        Apple M3 · 8GB · Metal 4          ║
╚══════════════════════════════════════════╝

[✓] Ollama already running          (or [✓] Ollama started)
    → hackerstation-reason:latest: 4.9GB
    → hackerstation-code:latest:    4.9GB
    → deepseek-r1:8b:               4.9GB
    → qwen3:8b:                     4.9GB
[✓] AI Router started (PID: ...)
[✓] Supervisor started (PID: ...) — auto-restart + memory watchdog
[i] Tail self-heal events: tail -f logs/self-heal.log

[!] Lab containers not auto-started (heavy on RAM).
[!] Run: ./start.sh lab   to start the Docker lab.
```

### Health check

```bash
./start.sh status
```
or, more detail:
```bash
curl -s http://localhost:8080/status | python3 -m json.tool
```

Expected `/status`:
```json
{
  "safe_mode": false,
  "memory": {"percent_used": 73.1, "available_gb": 2.17, "total_gb": 8.0,
             "source": "vm_stat"},
  "latency": {"avg_sec": 0.0, "samples": []},
  "errors_60s": 0,
  "in_flight": 0,
  "ollama_alive": true
}
```

### Health endpoints (single source of truth)

| Endpoint | What it tells you | When to use |
|----------|------------------|-------------|
| `GET /health` | ok/degraded + safe_mode flag + memory% | Liveness probe |
| `GET /status` | full runtime snapshot | Debugging |
| `GET /models` | proxies `ollama /api/tags` | "Is Ollama up?" |
| `GET /` | endpoint catalog | Orientation |

### Starting only the AI stack (no Docker lab)

```bash
./start.sh ollama
./start.sh router
./start.sh supervisor
```

### Starting the Docker lab (RAM-heavy — only when you have headroom)

```bash
./start.sh lab
```
Lab URLs:
- Juice Shop: http://localhost:3000
- DVWA:       http://localhost:4280 (admin / password)
- WebGoat:    http://localhost:8888/WebGoat
- Metasploit: `docker exec -it hacklab-msf msfconsole`

### Stopping everything

```bash
./start.sh stop                # kills supervisor + router
docker compose down            # stops the lab
brew services stop ollama      # optional: free ~1 GB by stopping Ollama itself
```

### First-call sanity test

```bash
# Coding route (should go to hackerstation-code)
curl -s -X POST http://localhost:8080/generate \
     -H "Content-Type: application/json" \
     -d '{"prompt": "Write a Python tcp port scanner — one file, async, 100-line budget."}' \
     | python3 -c "import sys,json; d=json.load(sys.stdin); print('model:', d['_router']['model_used']); print(d['response'][:500])"

# Reasoning route
curl -s -X POST http://localhost:8080/generate \
     -H "Content-Type: application/json" \
     -d '{"prompt": "Analyze the MITRE ATT&CK kill chain for a supply-chain attack on a JS build pipeline."}' \
     | python3 -c "import sys,json; d=json.load(sys.stdin); print('model:', d['_router']['model_used']); print(d['response'][:500])"
```

If `_router.model_used` is `deterministic-stub`, something is broken (most likely Ollama didn't come up). Check:
```bash
curl -s http://localhost:11434/api/tags   # Ollama directly
tail -20 logs/self-heal.log               # router's self-heal events
```

---

## 8. SELF-REFLECTION — GAPS & FAILURE MODES

### What is missing in this architecture?

- **Streaming generation** — everything is request/response. On 8GB, long deepseek-r1 chains-of-thought block for 60–180 s. Users assume a hang. Fix via FIX-7.
- **Observability** — no metrics endpoint, no dashboard, no structured JSON logs. `self-heal.log` is human-readable but not machine-queryable. Fix via FIX-8.
- **Tests** — zero unit tests on `classify_task`, `should_enter_safe_mode`, fallback chain. Fix via FIX-10.
- **Auth / rate limit** — router is unauthenticated. Fine for `127.0.0.1` only. Mandatory if ever exposed.
- **Input schema validation** — see FIX-6.
- **Log rotation** — see CRIT-7.
- **Prompt audit trail** — no record of what was asked. For a security lab you want to **choose** whether that's privacy-preserving (good) or a debug blind spot (bad). Decide explicitly.
- **Graceful Ollama restart** — if Ollama crashes, router retries but never triggers Ollama to come back. Supervisor watches the router; **nothing watches Ollama** except `brew services`.
- **Model refresh job** — no cron to `ollama pull` the base images for security updates. Not urgent but worth noting.
- **Nuclei template update job** — see §3.

### What will break at scale?

- **Concurrent users** — the semaphore is `Semaphore(1)`. Two clients = one queued for up to 90 s. Not a bug, but a documented constraint.
- **Prompt size** — `num_ctx=4096` hard-caps useful context. A 30 KB prompt is silently truncated. Add a warning.
- **Model swap** — `ollama` has to load/unload the inactive model when switching between coding and reasoning. That's 5–15 s of wall-clock latency on 8 GB.
- **Docker lab + AI** — running Juice Shop + DVWA + MSF + WebGoat + loaded model **does not fit in 8 GB**. Expect heavy swap. See §10.

### What is assumed but not implemented?

- **Ollama is always running** — supervisor relies on `memory_probe.ollama_running()` and retries, but doesn't start Ollama itself. If you run `brew services stop ollama` by accident, supervisor retries forever. Minor: add `brew services start ollama` attempt in `spawn_router`.
- **Disk has room for logs** — no disk-full detection.
- **Modelfiles are committed** — they are (✅), but nothing rebuilds the custom models after a fresh `git clone`. Add `./start.sh bootstrap` that runs `ollama create hackerstation-code -f Modelfile.qwen-hacker` and same for reason.
- **`python3` is 3.14** — `python3` is a symlink. If a user has 3.9 first on PATH, the router crashes on `|` union syntax, `Optional[float] | None`, etc.

### 8GB-pressure failure modes (observed in `self-heal.log`)

Already-observed event sequence from your actual logs (2026-04-15 05:04–05:08):
1. `available_gb=0.32` — safe mode entered.
2. Memory stayed >95% for ~3 minutes.
3. Router health check failed 3× consecutively → supervisor respawned router.
4. Recovery to `70.93%` → safe mode exited.

This is **working as designed**. What's missing is:
- **Notification** when safe-mode stays active for >5 min.
- **Auto-degradation** — already partial (num_ctx 2048 instead of 4096 under safe mode). Could further reduce num_predict.
- **Adaptive concurrency** — under safe mode, refuse the 2nd queued request immediately instead of queuing for 90 s.

### What happens if Ollama crashes?

- Router's `query_with_retry` retries 3× with 2 s/4 s/6 s backoff.
- After all retries fail, fallback to the coding model (which is also via Ollama → also fails).
- After coding fails, `deterministic_fallback` returns a degraded 200 with a human message.
- Supervisor notices the router's `/health` still returns 200 (router itself is alive) → does NOT restart router.
- User is stuck in degraded-responses mode until Ollama comes back.

**Gap:** nothing restarts Ollama. Add a watcher in `supervisor.py`:
```python
if not memory_probe.ollama_running():
    subprocess.run(["brew", "services", "restart", "ollama"])
    log("ollama_auto_restart")
```

### What happens if the router loops infinitely?

Can it? The HTTP handler is strictly request/response. The watchdog thread has `time.sleep(5)` in its loop, can't busy-spin. The retry logic has a bounded attempt count. The semaphore has a timeout (90 s). The only genuine infinite-loop risk is:
- Ollama taking >5 min to respond and the urlopen timeout (300 s normal, 120 s safe-mode) firing → exception → retry × 3 → fallback. Bounded.

**So "infinite loop" is mostly contained.** The real risk is **slow hang** — a 180 s request with no feedback. Streaming fixes that (FIX-7).

### Where is logging insufficient?

- No per-request log of prompt hash, model used, elapsed, memory% at start.
- `self-heal.log` mixes event types (errors, info, state transitions) into one file without levels.
- `router.log` from the old version is still mixed in.

Minimum-effort fix: add one line per request:
```python
heal_log("request", route=self.path, task=task_type, model=model_used,
         elapsed=round(elapsed, 2), mem=STATE.last_memory_percent,
         fell_back=fell_back)
```

### Where is observability missing?

- No **real-time dashboard**. The HTML file `hackerstation-docs.html` exists but it's docs, not a live status panel. Build a simple `GET /dashboard` → HTML that polls `/status` every 2 s.
- No **alerting**. Use `osascript -e 'display notification ...'` for macOS-native alerts.
- No **trace correlation** — when a request fails, you can't trace it through retry → fallback → response without parsing timestamps by eye.

---

## 9. FINAL RECOMMENDED STATE (ideal for 8GB)

### Target architecture

```
┌────────────────────────────────────────────────────────────────┐
│                       MacBook M3 · 8 GB                         │
│                                                                 │
│   ┌──────────────┐        ┌──────────────┐                      │
│   │ Cursor IDE   │        │  Warp        │                      │
│   │ + local AI   │        │  terminal    │                      │
│   │ via :11434   │        │              │                      │
│   └──────┬───────┘        └──────┬───────┘                      │
│          │                       │                              │
│          ▼                       ▼                              │
│   ┌──────────────────────────────────┐  127.0.0.1 ONLY          │
│   │  AI Router v2.1 (self-healing)   │  ← FIX-1                 │
│   │  :8080 (loopback-only)           │                          │
│   │  /health /status /metrics /version (FIX-2, 8)               │
│   │  /generate /chat /stream  (FIX-7)                           │
│   │  per-request log line (§8 logging)                          │
│   └─────────┬────────────────────────┘                          │
│             │                                                   │
│             ▼                                                   │
│   ┌──────────────────────────────┐                              │
│   │ Ollama 0.20.7                │                              │
│   │ FLASH_ATTENTION=1            │ ← already set                │
│   │ KV_CACHE_TYPE=q8_0           │ ← already set                │
│   │                              │                              │
│   │ hackerstation-code (qwen3)   │  4.9 GB each                 │
│   │ hackerstation-reason (DSr1)  │  one loaded at a time        │
│   └──────────────────────────────┘                              │
│                                                                 │
│   Supervisor (watches router + Ollama) ← FIX §8 ollama watch    │
│                                                                 │
│   Docker lab — OFF by default                                   │
│   On-demand:                                                    │
│     ./start.sh lab      # ~2 GB RAM, ~1 GB disk                 │
│     digininja/dvwa      # FIX-2                                 │
│     internal:true net   # FIX-3                                 │
└────────────────────────────────────────────────────────────────┘
```

### RAM budget (target on a quiet 8 GB box)

| Component | Steady | Peak |
|-----------|--------|------|
| macOS base | 2.0 GB | 2.5 GB |
| Ollama idle (no model loaded) | 0.2 GB | 0.2 GB |
| One 8B model loaded (q4 + kv q8_0) | 4.5 GB | 5.0 GB |
| Router + supervisor (stdlib) | 60 MB | 120 MB |
| Cursor | 0.8 GB | 1.5 GB |
| **Subtotal — AI only** | **~7.6 GB** | ≈ capped, safe mode triggers |
| Docker Desktop | +1 GB | +1.5 GB |
| Lab (all containers) | +2 GB | +2.5 GB |
| **AI + Lab simultaneously** | **overflow — swap** | **expected** |

**Operating rule:** AI only = green zone. AI + Docker = yellow. Don't bother running all three simultaneously — test the lab or ask the AI, rarely both at the same time on 8 GB.

### Directory structure after applying fixes

```
hackerstation/
├── AUDIT.md                         ← this file
├── README.md                        ← rewritten per FIX-11
├── CURSOR.md                        ← Cursor-specific onboarding
├── STARTUP.md                       ← quick-start card (printable)
├── .cursor/
│   ├── settings.json
│   └── rules
├── .vscode/
│   ├── launch.json                  ← F5 debugging
│   ├── tasks.json                   ← one-click start/stop
│   └── extensions.json              ← recommended: Python, Docker, YAML
├── .env.example                     ← FIX-12
├── .gitignore                       ← add .env, .cursor-chat, etc.
├── router.py                        ← FIX-1,2,3,6,7,8,9 applied
├── supervisor.py                    ← FIX §8 ollama watch, FIX-13 alarm
├── memory_probe.py
├── start.sh                         ← + bootstrap, + swap-reason, + test
├── Modelfile.qwen-hacker
├── Modelfile.deepseek-hacker
├── docker-compose.yml               ← FIX-2, FIX-3, pinned digests
├── tests/
│   ├── test_classify.py
│   ├── test_safe_mode.py
│   └── test_fallback.py
├── recon/                           ← gitignored — engagement outputs
└── logs/
    ├── self-heal.log
    ├── supervisor.log
    └── archive/                     ← rotated logs
```

### The north star

> One command to start. One command to stop. One endpoint to check if it's healthy. One log file to read when it's not. Loopback-only by default. No cloud. No secrets. Fits in 8 GB.

Everything in this audit moves you toward that.

---

## 10. PRIORITIZED ACTION LIST (what to do first)

| # | Action | Impact | Effort | Ship when |
|---|--------|--------|--------|-----------|
| 1 | CRIT-1: bind `127.0.0.1` by default | Security | 2 min | **Today** |
| 2 | CRIT-9: archive old `router.log` | Debuggability | 1 min | **Today** |
| 3 | CRIT-5: reinstall stable `ffuf` | Correctness | 5 min | **Today** |
| 4 | FIX-2: add `/version` | Ops hygiene | 5 min | **Today** |
| 5 | FIX-11: rewrite README | Docs match reality | 20 min | This week |
| 6 | FIX-3: log rotation on boot | Disk safety | 10 min | This week |
| 7 | Cursor migration artifacts (see §5) | DX | 30 min | This week |
| 8 | CRIT-2: DVWA image switch | Lab quality | 15 min | Next session |
| 9 | CRIT-3: `internal:true` network option | Lab safety | 10 min | Next session |
| 10 | FIX-7: streaming endpoint | UX | 1 hr | Next session |
| 11 | FIX-10: unit tests | Confidence | 2 hr | Sprint |
| 12 | FIX-8: `/metrics` + mini dashboard | Observability | 1 hr | Sprint |
| 13 | FIX-13: crash-loop macOS notification | Alerting | 15 min | Sprint |
| 14 | FIX-4: drop redundant base models | Disk | 1 min | Anytime |

---

## Appendix A — Answers to the self-reflection prompts

**Q: What will break at scale?**
A: Concurrency is single-slot. Context is 4 k. Model swap costs 5–15 s. If a second user connects, they queue. Documented, not a bug.

**Q: What happens under memory pressure (8GB)?**
A: Observed in logs. Watchdog flips safe mode at ≥88 %, reduces context to 2048, output to 256 tokens, adds terseness suffix. Router survived and recovered autonomously from 96 % → 70 %.

**Q: What happens if Ollama crashes?**
A: Router retries 3× per model, falls through primary → fallback → deterministic stub. Router keeps answering with degraded messages. **Supervisor does NOT restart Ollama today** → add ollama-watch (see §8 action list).

**Q: What happens if router loop runs infinitely?**
A: Bounded. HTTP handler is per-request. Watchdog has 5 s sleep. Retry has max 3 attempts. Urlopen has 120/300 s timeout. Semaphore has 90 s acquire-timeout. Infinite loop is essentially impossible; slow hangs are possible and the fix is streaming.

**Q: Where is logging insufficient?**
A: No per-request line. No log levels. Old v1 logs mixed with v2. One-line fix above.

**Q: Where is observability missing?**
A: No metrics endpoint, no dashboard, no notifications. FIX-8 + FIX-13 close the gap in an afternoon.

---

## Appendix B — Post-audit verification (2026-04-15)

After the original audit, the action list was executed. Verification runs produced three new findings that are tracked here rather than as fresh CRITs (none are severe; two are doc drift, one is a calibration nit).

### B-1 · FIX-7 streaming verified end-to-end
`POST /generate` with `"stream": true` now returns `application/x-ndjson`. Observed shape:
- Chunks forwarded verbatim from Ollama (`{"model":"...","response":"...","done":false}` → ... → `{"done":true,"done_reason":"stop",...}`)
- Trailing `{"_router": {...}}` line appended after Ollama's final chunk, carrying `task_type`, `model_used`, `fell_back`, `degraded`, `safe_mode`, `elapsed_seconds`, `memory_percent`
- `BrokenPipeError` / `ConnectionResetError` suppress the trailing line gracefully (logged `stream_client_disconnect`)

Also during this work we discovered and fixed a latent concurrency bug: the stdlib `HTTPServer` is single-threaded, so a long streaming POST blocked the supervisor's `/health` poll and triggered a spurious `killed_stuck_pid` respawn. Replaced with `http.server.ThreadingHTTPServer` (stdlib, zero new deps). `gen_semaphore(1)` still enforces single-concurrent heavy generation — threading is only to let `/health` probes through during a stream. Evidence: four `/health` probes returned 200 (0.15 s – 2.01 s) DURING a 180 s active stream.

### B-2 · `internal: true` + `ports:` is logically inconsistent (doc drift)
`docker-compose.yml` declares `hacklab` as `internal: true` AND publishes `ports: 127.0.0.1:<N>:<M>` on target containers. These cannot coexist on vanilla Docker:
- `internal: true` removes the bridge's host gateway
- Published ports need iptables DNAT on that gateway
- Result on stock Docker / Docker Desktop: `docker inspect ... NetworkSettings.Ports == {}`, `lsof -iTCP:3000 LISTEN` returns nothing

Why the audit-era compose appeared to work: the host runs **OrbStack**, whose tun-based routing + `<container-name>.orb.local` DNS reaches the container independently of Docker's bridge DNAT. So the lab is functional but only because of the runtime.

**Runtime verification (2026-04-15):**
- `http://hacklab-juiceshop.orb.local/` → `200`
- `http://hacklab-webgoat.orb.local/WebGoat/login` → `200`
- `http://127.0.0.1:3000/` → `000 (connection refused)`
- `curl http://<LAN_IP>:3000/` → connection refused (good — not LAN-exposed)

**Isolation checks from an alpine sidecar attached to `hacklab`:**
- Default route in container: `172.30.0.0/24 dev eth0 scope link` (no default gateway — isolation intact)
- `ping 8.8.8.8` → `Network unreachable`
- `nslookup example.com` → `SERVFAIL` (Docker's embedded resolver at 127.0.0.11 has no upstream)
- Intra-lab: `http://hacklab-juiceshop:3000/` → `200`, `http://hacklab-webgoat:8080/WebGoat/` → `302`

**Action taken:** README.md, STARTUP.md, start.sh, and docker-compose.yml updated to document the OrbStack dependency and publish `<name>.orb.local` as the canonical access URL. `ports:` entries kept in compose as aspirational / future-portability documentation.

**Follow-up (not done this session):** if the workstation ever moves off OrbStack (Docker Desktop, Linux Docker), add a reverse-proxy container on a non-internal bridge that forwards to targets on `hacklab`. Keeps isolation + host reachability.

### B-3 · WebGoat upstream image has a broken HEALTHCHECK
`webgoat/webgoat:latest` declares:
```
HEALTHCHECK CMD-SHELL "curl --fail http://localhost:8080/WebGoat/actuator/health || exit 1"
```
but **does not install `curl`** in the container. Docker health log:
```
Output: "/bin/sh: 1: curl: not found\n"
ExitCode: 1
```
Result: the container runs fine and serves `/WebGoat/actuator/health` → `200`, but Docker perpetually marks it `unhealthy`, and `docker events` spams an exec_create/exec_start/exec_die cycle every 5 s.

**Action taken:** `healthcheck: disable: true` added to the `webgoat` service in `docker-compose.yml`. The service's own actuator is still reachable externally if anyone wants to wire a real probe later.

### B-4 · Memory probe calibration drift (~3 %, not load-bearing)
`memory_probe.py::_probe_macos()` uses:
- **Total** from `sysctl hw.memsize` = 8.59 GB (includes system-reserved pages: firmware, GPU, WindowServer)
- **Available** from `vm_stat` = `free + inactive + speculative` (only user-page categories)

These are different accounting spaces. Sum of all `vm_stat` page classes is ~7.95 GB, so ~0.64 GB of system-reserve pages get charged to "used" against a larger total — inflating `percent_used` by ~3 % vs. Activity Monitor's definition. Observed drift: probe 69 % vs true ~66 %. Under heavy RAM pressure with Ollama loaded, the drift can spike to 30 %+ because purgeable/inactive accounting shifts.

**Impact:** SAFE MODE threshold is 88 %, so 3 % calibration drift eats headroom. Not yet observed to cause a false SAFE MODE, but under memory pressure it likely has.

**Suggested fix (not done this session):** use `true_total = sum(all_vm_stat_page_classes) * page_size` and `used = (active + wired + compressor) * page_size`; `percent = used / true_total * 100`. This matches Activity Monitor "Memory Used" and removes the system-reserve inflation.

---

**End of audit.**
