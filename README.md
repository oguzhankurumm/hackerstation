# HackerStation AI Workstation

Local AI-powered cybersecurity research & penetration testing lab.
Apple M3 · 8 GB unified memory · Metal 4 · **fully offline** · zero cloud dependencies.

> **Status (2026-04-15):** router v2.0 with self-healing, memory watchdog, and out-of-process supervisor. Bound to `127.0.0.1` by default. See `AUDIT.md` for the full system audit and `STARTUP.md` for a copy-paste startup card.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Apple M3 / 8 GB                          │
│                                                                 │
│   ┌──────────────┐     ┌──────────────┐                         │
│   │  Cursor IDE  │     │  Warp term   │                         │
│   │  (primary)   │     │  (runner)    │                         │
│   └──────┬───────┘     └──────┬───────┘                         │
│          │                    │                                 │
│          ▼                    ▼                                 │
│  ┌────────────────────────────────────┐ ROUTER_HOST=127.0.0.1   │
│  │  AI Router v2.0  (self-healing)    │  (default; env-override │
│  │  :8080                             │   to expose)            │
│  │  classify → primary → fallback     │                         │
│  │  → deterministic stub              │                         │
│  │  memory watchdog (5 s) + semaphore │                         │
│  └────────────────────────────────────┘                         │
│          │                    ▲                                 │
│          ▼                    │                                 │
│  ┌──────────────────┐    ┌────┴────────┐                        │
│  │  Ollama :11434   │    │ Supervisor  │                        │
│  │  FLASH_ATT=1     │    │ (out-of-    │                        │
│  │  KV_CACHE=q8_0   │    │  process    │                        │
│  │                  │    │  restart)   │                        │
│  │ hackerstation-   │    └─────────────┘                        │
│  │  code   (qwen3)  │                                           │
│  │ hackerstation-   │                                           │
│  │  reason (DSr1)   │                                           │
│  └──────────────────┘                                           │
│                                                                 │
│  ┌───────────────────────────────────────────────────┐          │
│  │  Docker lab (hacklab — internal:true)             │          │
│  │  172.30.0.0/24                                    │          │
│  │  Juice Shop :3000 · DVWA :4280 · WebGoat :8888    │          │
│  │  MSF (docker exec only) → hacklab-egress sidecar  │          │
│  └───────────────────────────────────────────────────┘          │
│                                                                 │
│  Native tools: nmap sqlmap hashcat john wireshark gobuster      │
│                ffuf nikto nuclei radare2                        │
└─────────────────────────────────────────────────────────────────┘
```

## Project layout

```
hackerstation/
├── README.md                      # This file
├── AUDIT.md                       # Full system audit (10 sections)
├── CURSOR.md                      # Cursor IDE onboarding + offline-Ollama wiring
├── STARTUP.md                     # Printable one-page cold-boot card
├── router.py                      # AI routing server (stdlib-only)
├── supervisor.py                  # Out-of-process self-healing watchdog
├── memory_probe.py                # Stdlib memory/CPU probe (vm_stat / /proc)
├── start.sh                       # One-command launcher (all/ollama/router/supervisor/lab/status/stop)
├── Modelfile.qwen-hacker          # → hackerstation-code  (coding/exploits/scripting)
├── Modelfile.deepseek-hacker      # → hackerstation-reason (analysis/kill-chains)
├── docker-compose.yml             # Isolated lab (targets on internal:true net)
├── .cursor/
│   ├── settings.json              # Editor defaults + local Ollama model
│   └── rules                      # Project AI guardrails (stdlib-only, 8GB, loopback)
├── .vscode/
│   ├── launch.json                # F5 debug configs (router, supervisor, compound)
│   ├── tasks.json                 # One-click start/stop/lab/tail-logs/rebuild-models
│   └── extensions.json            # Recommended: Python, Docker, YAML, Markdown
├── logs/
│   ├── self-heal.log              # Structured event stream (safe_mode, fallback, restart)
│   └── router-v1-archive-*.log    # Archived pre-v2 traces
└── recon/                         # Gitignored — per-engagement evidence folders
```

## AI routing map

| Task type | Model | Base | Use cases |
|-----------|-------|------|-----------|
| **Coding** | `hackerstation-code` | `qwen3:8b` | Scripting, exploit dev, payload gen, tool building |
| **Reasoning** | `hackerstation-reason` | `deepseek-r1:8b` | Attack-chain planning, threat modeling, analysis |

The router auto-classifies prompts via keyword analysis. Both models carry a shared **8GB-aware system prompt** that asks for concise, structured output. Under memory pressure the router adds a **SAFE MODE** suffix that reduces output to ≤120 tokens and skips chain-of-thought.

```bash
# Auto-route (recommended)
curl -X POST http://localhost:8080/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Write a Python port scanner"}'

# Force coding model
curl -X POST http://localhost:8080/generate/coding \
  -H "Content-Type: application/json" \
  -d '{"prompt": "..."}'

# Force reasoning model
curl -X POST http://localhost:8080/generate/reasoning \
  -H "Content-Type: application/json" \
  -d '{"prompt": "..."}'

# Chat endpoint (messages array)
curl -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Explain SQL injection attack chains"}]}'
```

Every response wraps the model output with a `_router` block:
```json
"_router": {"task_type":"coding","model_used":"hackerstation-code",
            "fell_back":false,"safe_mode":false,"elapsed_seconds":4.21,
            "memory_percent":73.1}
```

## Quick start

```bash
cd ~/Desktop/Projects/hackerstation
./start.sh all          # Ollama + router + supervisor
./start.sh status       # verify
./start.sh lab          # optional: Docker lab (2+ GB RAM, start only when needed)
```

Full command reference in [`STARTUP.md`](./STARTUP.md).

## Endpoints

| Method + path | Purpose |
|---------------|---------|
| `GET  /`          | Endpoint catalog |
| `GET  /health`    | Liveness (`ok`, `safe_mode`, `memory_percent`, `ollama_alive`) |
| `GET  /status`    | Full runtime snapshot (memory, latency samples, in-flight count) |
| `GET  /models`    | Proxies Ollama `GET /api/tags` |
| `GET  /version`   | Router + Ollama versions, PID, uptime, bind host |
| `POST /generate`  | Auto-routed generation |
| `POST /chat`      | Auto-routed chat (messages array) |
| `POST /generate/coding`    | Force coding model |
| `POST /generate/reasoning` | Force reasoning model |

## Installed tools & versions (2026-04-15)

### Security tools (native)
| Tool | Version | Purpose |
|------|---------|---------|
| nmap | 7.99 | Network scanning & discovery |
| sqlmap | 1.10.4 stable | SQL-injection automation |
| hashcat | 7.1.2 | GPU password cracking (Metal) |
| john (jumbo) | 1.9.0_1 | CPU password cracking |
| tshark | 4.6.4 | Packet capture & analysis |
| gobuster | 3.8.2 | Directory / DNS brute-forcing |
| ffuf | 2.1.0 (stable) | Web fuzzing |
| nikto | 2.6.0 | Web server scanning |
| nuclei | 3.7.1 | Template-driven vuln scanning |
| radare2 | 6.1.4 | Reverse engineering |

### AI infrastructure
| Component | Version | Port |
|-----------|---------|------|
| Ollama | 0.20.7 | 11434 |
| AI Router | **2.0.0** | 8080 (127.0.0.1) |
| hackerstation-code | 4.87 GB | via Ollama |
| hackerstation-reason | 4.87 GB | via Ollama |

### Docker lab targets
Reach targets via OrbStack's container-scoped DNS (`<name>.orb.local`). The compose file sets `ports: 127.0.0.1:…` for portability, but since `hacklab` is `internal: true` the Docker bridge has no host gateway, so those published ports do not work on vanilla Docker / Docker Desktop — only OrbStack's tun-based routing reaches the targets. If you move off OrbStack, add a reverse-proxy container on a non-internal network.

| Target | Image | URL | Credentials |
|--------|-------|-----|-------------|
| OWASP Juice Shop | `bkimminich/juice-shop:latest` | http://hacklab-juiceshop.orb.local/ | self-register |
| DVWA | `ghcr.io/digininja/dvwa:latest` | http://hacklab-dvwa.orb.local/ | admin / password |
| WebGoat | `webgoat/webgoat:latest` | http://hacklab-webgoat.orb.local/WebGoat/ | self-register |
| Metasploit | `metasploitframework/metasploit-framework:latest` | `docker exec -it hacklab-msf msfconsole` | — |

### Infrastructure
| Tool | Version |
|------|---------|
| Docker | 28.5.2 |
| Docker Compose | 2.40.3 |
| Git | 2.50.1 |
| GitHub CLI | 2.86.0 |
| Python | 3.14.4 |
| Node.js | 25.4.0 |

Weekly maintenance:
```bash
nuclei -update-templates          # template set changes daily
docker compose pull               # refresh lab images
ollama pull qwen3:8b              # only if you rebuild Modelfiles
```

## Network + security posture

- **Router binds `127.0.0.1:8080` by default.** Override with `ROUTER_HOST=0.0.0.0 ./start.sh router` only if you put an auth proxy in front.
- **Lab containers are reached over OrbStack's `.orb.local` DNS** — never exposed to the LAN or to published host ports (see "Docker lab targets" for why).
- **`hacklab` network is `internal: true`** — targets cannot reach the internet, so a compromised target cannot phone home. Side effect: it also disables the Docker bridge's host gateway, which is why `ports:` publishing is inert on non-OrbStack runtimes.
- **`hacklab-egress` sidecar network** exists for Metasploit (module updates via `msfupdate`). Only MSF is attached.
- **Modelfiles strip refusals** — appropriate for authorized offensive research; treat the AI output as powerful and private.

## Performance notes

- **8 GB RAM** — only one 8B model is resident at a time; Ollama unloads the inactive one. Expect 5–15 s swap latency when switching task types.
- **Flash Attention** — enabled via `OLLAMA_FLASH_ATTENTION=1` in the Ollama launchd plist.
- **KV-cache q8_0** — set via `OLLAMA_KV_CACHE_TYPE=q8_0`, cuts KV-cache memory ~50%.
- **Metal 4 GPU** — Ollama auto-detects and uses Apple Metal. `hashcat -b` reports Metal as well.
- **Docker mem limits** — every lab container has a `mem_limit` to prevent OOM on the host.

## Troubleshooting

```bash
# Memory pressure / safe mode?
curl -s http://localhost:8080/status | python3 -m json.tool

# Ollama alive?
curl -s http://localhost:11434/api/tags | head

# Recent self-heal events?
tail -30 logs/self-heal.log

# Is the router actually running?
pgrep -fa router.py

# Nuclear reset
./start.sh stop && ./start.sh all
```

If safe-mode stays on >5 min: close Cursor, stop the Docker lab (`docker compose down`), or temporarily quit Ollama (`brew services stop ollama`).

## Legal note

Every offensive tool here is for **authorized testing only**: the local Docker lab, your own infrastructure, or targets with **written engagement authorization**. Unauthorized access is a criminal offense in most jurisdictions. See `AUDIT.md` §6 for the authorization framework and the beginner→advanced skill ladder.
