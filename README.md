# HackerStation AI Workstation

Local AI-powered cybersecurity research & penetration testing environment.
Apple M3 · 8GB · Metal 4 · Fully offline · Zero cloud dependencies.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   YOUR MACHINE                       │
│                  Apple M3 / 8GB                      │
│                                                      │
│  ┌──────────┐    ┌──────────────┐   ┌────────────┐  │
│  │  Warp /  │───▶│  AI Router   │──▶│  Ollama    │  │
│  │  VSCode  │    │  :8080       │   │  :11434    │  │
│  └──────────┘    └──────┬───────┘   │            │  │
│                         │           │ ┌────────┐ │  │
│                   classify()        │ │qwen3:8b│ │  │
│                         │           │ └────────┘ │  │
│              ┌──────────┴────┐      │ ┌────────┐ │  │
│              │               │      │ │deepseek│ │  │
│          coding          reasoning  │ │  r1:8b │ │  │
│              │               │      │ └────────┘ │  │
│              └──────┬────────┘      └────────────┘  │
│                     │                                │
│  ┌──────────────────┴────────────────────────┐      │
│  │         Docker Network: hacklab            │      │
│  │         172.30.0.0/24 (isolated)           │      │
│  │                                            │      │
│  │  ┌───────────┐ ┌──────┐ ┌───────────────┐ │      │
│  │  │Juice Shop │ │ DVWA │ │  Metasploit   │ │      │
│  │  │  :3000    │ │:4280 │ │  (exec only)  │ │      │
│  │  └───────────┘ └──────┘ └───────────────┘ │      │
│  │  ┌───────────┐                             │      │
│  │  │ WebGoat   │                             │      │
│  │  │  :8888    │                             │      │
│  │  └───────────┘                             │      │
│  └────────────────────────────────────────────┘      │
│                                                      │
│  Native Tools: nmap, sqlmap, hashcat, john,          │
│  wireshark, gobuster, ffuf, nikto, nuclei, radare2   │
└─────────────────────────────────────────────────────┘
```

## AI Model Routing Map

| Task Type | Model | Use Case |
|-----------|-------|----------|
| **Coding** | `qwen3:8b` | Script writing, exploit development, payload generation, tool building |
| **Reasoning** | `deepseek-r1:8b` | Attack chain planning, threat modeling, analysis, strategy |

The router auto-classifies prompts via keyword analysis. You can also force a model:

```bash
# Auto-route (recommended)
curl -X POST http://localhost:8080/generate \
  -d '{"prompt": "Write a Python port scanner"}'

# Force coding model
curl -X POST http://localhost:8080/generate/coding \
  -d '{"prompt": "your prompt here"}'

# Force reasoning model
curl -X POST http://localhost:8080/generate/reasoning \
  -d '{"prompt": "your prompt here"}'

# Chat endpoint
curl -X POST http://localhost:8080/chat \
  -d '{"messages": [{"role": "user", "content": "Explain SQL injection attack chains"}]}'
```

## Installed Tools & Versions

### Security Tools (Native)
| Tool | Version | Purpose |
|------|---------|---------|
| nmap | 7.99 | Network scanning & discovery |
| sqlmap | 1.10.4 | SQL injection automation |
| hashcat | 7.1.2 | GPU-accelerated password cracking (Metal) |
| john | jumbo | Password cracking (CPU) |
| wireshark/tshark | 4.6.4 | Packet capture & analysis |
| gobuster | latest | Directory/DNS brute-forcing |
| ffuf | 2.1.0-dev | Web fuzzing |
| nikto | latest | Web server scanning |
| nuclei | 3.7.1 | Vulnerability scanning |
| radare2 | 6.1.4 | Reverse engineering |

### AI Infrastructure
| Component | Version | Port |
|-----------|---------|------|
| Ollama | 0.20.7 | 11434 |
| AI Router | 1.0.0 | 8080 |
| qwen3:8b | 4.9 GB | via Ollama |
| deepseek-r1:8b | 4.9 GB | via Ollama |

### Docker Lab Targets
| Target | Port | Credentials |
|--------|------|-------------|
| OWASP Juice Shop | 3000 | (self-register) |
| DVWA | 4280 | admin / password |
| WebGoat | 8888 | (self-register) |
| Metasploit | exec only | `docker exec -it hacklab-msf msfconsole` |

### Infrastructure
| Tool | Version |
|------|---------|
| Docker | 28.5.2 |
| Docker Compose | 2.40.3 |
| Git | 2.50.1 |
| GitHub CLI | 2.86.0 |
| Python | 3.14.4 |
| Node.js | 25.4.0 |

## Quick Start

### 1. Start Everything (AI only — lightweight)
```bash
./start.sh
```
This starts Ollama + AI Router. Lab containers are NOT started by default (RAM-heavy).

### 2. Start the Security Lab
```bash
./start.sh lab
```

### 3. Check Status
```bash
./start.sh status
```

### 4. Use the AI Router
```bash
# Ask a coding question (routes to qwen3)
curl -s -X POST http://localhost:8080/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Write a Python nmap wrapper"}' | python3 -m json.tool

# Ask an analysis question (routes to deepseek-r1)
curl -s -X POST http://localhost:8080/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Analyze the OWASP Top 10 attack chain for a banking app"}' | python3 -m json.tool
```

### 5. Use Native Tools
```bash
# Network scan
nmap -sV -sC localhost

# SQL injection test against DVWA
sqlmap -u "http://localhost:4280/vulnerabilities/sqli/?id=1&Submit=Submit" --cookie="PHPSESSID=xxx;security=low"

# Web fuzzing
ffuf -u http://localhost:3000/FUZZ -w /usr/share/wordlists/dirb/common.txt

# Vulnerability scan
nuclei -u http://localhost:3000

# Password cracking (Metal GPU)
hashcat -m 0 -a 0 hashes.txt wordlist.txt

# Metasploit
docker exec -it hacklab-msf msfconsole
```

## Performance Optimization Notes

- **8GB RAM constraint**: Only one AI model is loaded at a time. Ollama auto-unloads the inactive model.
- **Metal 4 GPU**: Ollama uses Apple Metal for inference acceleration automatically.
- **Flash Attention**: Enabled via `OLLAMA_FLASH_ATTENTION=1` in the Ollama service config.
- **KV Cache Quantization**: Set `OLLAMA_KV_CACHE_TYPE=q8_0` for reduced memory usage.
- **hashcat**: Uses Metal backend for GPU-accelerated cracking on M3.
- **Docker memory limits**: Each container has a `mem_limit` to prevent OOM on 8GB.

## File Structure
```
hackerstation/
├── README.md              # This file
├── router.py              # AI routing server
├── router.log             # Router logs
├── docker-compose.yml     # Security lab containers
└── start.sh               # One-command launcher
```
