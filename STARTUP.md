# HackerStation — Startup card

Copy-paste-ready. Printable. Print it, stick it next to the machine.

## Start everything

```bash
cd ~/Desktop/Projects/hackerstation
./start.sh all
```

## Verify it worked

```bash
./start.sh status
curl -s http://localhost:8080/health | python3 -m json.tool
```

Healthy response contains `"status": "ok"` and `"ollama_alive": true`.

## Use the AI

```bash
# Auto-routed (classifier picks coding vs reasoning model)
curl -s -X POST http://localhost:8080/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Write a Python TCP port scanner (async, single file, <100 lines)."}' \
  | python3 -m json.tool

# Force reasoning model
curl -s -X POST http://localhost:8080/generate/reasoning \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Analyze a typical supply-chain attack kill chain for a JS build pipeline."}' \
  | python3 -m json.tool
```

Response includes `_router.model_used` so you know which one answered.

## Start the Docker lab (only when you have RAM headroom)

```bash
./start.sh lab
```

Targets (use the `.orb.local` URLs — the `ports:` in compose are disabled because the `hacklab` network is `internal: true`, OrbStack routes via its own DNS):
- Juice Shop   http://hacklab-juiceshop.orb.local/
- DVWA         http://hacklab-dvwa.orb.local/            (admin / password → then "Create / Reset Database")
- WebGoat      http://hacklab-webgoat.orb.local/WebGoat/
- Metasploit   `docker exec -it hacklab-msf msfconsole`

## Stop everything

```bash
./start.sh stop          # router + supervisor
docker compose down      # lab containers
brew services stop ollama   # optional — frees ~1 GB
```

## When something is wrong

```bash
# 1. What does the router think?
curl -s http://localhost:8080/status | python3 -m json.tool

# 2. What events happened recently?
tail -30 logs/self-heal.log

# 3. Is Ollama even alive?
curl -s http://localhost:11434/api/tags | head -30

# 4. Is the router process alive?
pgrep -fa router.py

# 5. Nuclear option
./start.sh stop
./start.sh all
```

## Memory pressure (expected on 8 GB)

The router enters SAFE MODE automatically at ≥ 88 % memory and exits at ≤ 75 %. You'll see:
```
[timestamp] event=safe_mode_entered memory_pct=88.x ...
```
in `logs/self-heal.log`. This is normal. Responses get shorter, context drops from 4096 to 2048. No intervention needed.

If safe mode stays on for >5 min, close Cursor, close Docker Desktop, or stop the lab:
```bash
docker compose down
```

## Endpoint reference

| Verb + path | Purpose |
|-------------|---------|
| `GET  /`          | Endpoint catalog |
| `GET  /health`    | Liveness (ok + safe_mode + memory%) |
| `GET  /status`    | Full runtime snapshot |
| `GET  /models`    | Proxies Ollama `/api/tags` |
| `GET  /version`   | Router + Ollama versions, PID, uptime, bind host |
| `POST /generate`  | Auto-routed generation |
| `POST /chat`      | Auto-routed chat (messages array) |
| `POST /generate/coding`    | Force coding model |
| `POST /generate/reasoning` | Force reasoning model |
