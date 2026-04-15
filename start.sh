#!/usr/bin/env bash
# HackerStation — One-command launcher
# Usage: ./start.sh [component]
# Components: all, ollama, router, supervisor, lab, status, stop
set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

DIR="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$DIR/logs"

log()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[✗]${NC} $*"; }
info() { echo -e "${CYAN}[i]${NC} $*"; }

header() {
  echo ""
  echo -e "${CYAN}╔══════════════════════════════════════════╗${NC}"
  echo -e "${CYAN}║     🔒 HackerStation AI Workstation      ║${NC}"
  echo -e "${CYAN}║        Apple M3 · 8GB · Metal 4          ║${NC}"
  echo -e "${CYAN}╚══════════════════════════════════════════╝${NC}"
  echo ""
}

start_ollama() {
  if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    log "Ollama already running"
  else
    info "Starting Ollama..."
    brew services start ollama 2>/dev/null || true
    sleep 3
    if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
      log "Ollama started"
    else
      err "Ollama failed to start"
      return 1
    fi
  fi
  # List models
  curl -s http://localhost:11434/api/tags | python3 -c "
import sys,json
d=json.load(sys.stdin)
for m in d.get('models',[]):
    print(f'    → {m[\"name\"]}: {m[\"size\"]/(1024**3):.1f}GB')
" 2>/dev/null || true
}

start_router() {
  if curl -s http://localhost:8080/health >/dev/null 2>&1; then
    log "AI Router already running on :8080"
  else
    info "Starting AI Router on :8080..."
    nohup python3 "$DIR/router.py" > "$DIR/router.log" 2>&1 &
    sleep 2
    if curl -s http://localhost:8080/health >/dev/null 2>&1; then
      log "AI Router started (PID: $!)"
    else
      err "AI Router failed to start — check router.log"
      return 1
    fi
  fi
}

start_supervisor() {
  if pgrep -f "python3 .*supervisor.py" >/dev/null 2>&1; then
    log "Supervisor already running"
    return 0
  fi
  info "Starting self-healing supervisor..."
  nohup python3 "$DIR/supervisor.py" > "$DIR/logs/supervisor.log" 2>&1 &
  sleep 1
  if pgrep -f "python3 .*supervisor.py" >/dev/null 2>&1; then
    log "Supervisor started (PID: $!) — auto-restart + memory watchdog"
    info "Tail self-heal events: tail -f $DIR/logs/self-heal.log"
  else
    err "Supervisor failed to start — check logs/supervisor.log"
    return 1
  fi
}

stop_all() {
  info "Stopping supervisor (so it stops respawning the router)..."
  pkill -f "python3 .*supervisor.py" 2>/dev/null && log "Supervisor stopped" \
    || warn "No supervisor running"
  info "Stopping router..."
  pkill -f "python3 .*router.py" 2>/dev/null && log "Router stopped" \
    || warn "No router running"
}

start_lab() {
  if ! docker info >/dev/null 2>&1; then
    err "Docker is not running. Start Docker Desktop first."
    return 1
  fi
  info "Starting security lab containers..."
  docker compose -f "$DIR/docker-compose.yml" up -d 2>&1
  log "Lab containers started"
  echo "    → Juice Shop:  http://localhost:3000"
  echo "    → DVWA:        http://localhost:4280  (admin/password)"
  echo "    → WebGoat:     http://localhost:8888/WebGoat"
  echo "    → Metasploit:  docker exec -it hacklab-msf msfconsole"
}

show_status() {
  echo ""
  info "=== Service Status ==="
  echo ""

  # Ollama
  if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    log "Ollama        → http://localhost:11434"
  else
    err "Ollama        → DOWN"
  fi

  # Router
  if curl -s http://localhost:8080/health >/dev/null 2>&1; then
    log "AI Router     → http://localhost:8080"
  else
    err "AI Router     → DOWN"
  fi

  # Docker containers
  for name in hacklab-juiceshop hacklab-dvwa hacklab-msf hacklab-webgoat; do
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "$name"; then
      log "$name → running"
    else
      warn "$name → stopped"
    fi
  done
  echo ""
}

case "${1:-all}" in
  ollama)      header; start_ollama ;;
  router)      header; start_router ;;
  supervisor)  header; start_supervisor ;;
  lab)         header; start_lab ;;
  status)      header; show_status ;;
  stop)        header; stop_all ;;
  all)
    header
    start_ollama
    start_router
    start_supervisor
    echo ""
    warn "Lab containers not auto-started (heavy on RAM)."
    warn "Run: ./start.sh lab   to start the Docker lab."
    echo ""
    show_status
    ;;
  *)
    echo "Usage: $0 {all|ollama|router|supervisor|lab|status|stop}"
    exit 1
    ;;
esac
