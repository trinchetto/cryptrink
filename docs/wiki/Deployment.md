# Deployment Guide

This guide covers deployment options for Cryptrink. The recommended target is
**Hugging Face Spaces** — the Gradio UI, the live trading loop, and
(eventually) the LLM-agent strategy all run inside a single Space.

The cloud-VM and Docker sections at the bottom of this document are
preserved for operators who prefer to run cryptrink on their own
infrastructure, but they are not the primary deployment path.

## Deployment Options Comparison

| Option | Pros | Cons | Best For |
|--------|------|------|----------|
| **Hugging Face Space — free CPU** | Free, zero ops, three-tab UI | Sleeps when idle, ephemeral DB | Demo, backtests, suggestions |
| **Hugging Face Space — paid CPU + Storage Bucket** | Always on, persistent `/data`, secrets management | ~$22/mo for CPU Upgrade | Live paper or live trading |
| **Hugging Face Space — ZeroGPU (PRO account)** | Free GPU per request (25 min/day) | Per-call duration cap | LLM-agent strategy (Phase 9c) |
| **Local (PC)** | Full control, no latency | Must keep running, power costs | Development, backtesting |
| **Docker / Cloud VM** | Self-hosted, reliable | Manual ops | Operators avoiding HF |

## Hugging Face Spaces Deployment

### 9a — Free CPU Space (demo, backtests, suggestions)

1. Create a Space at <https://huggingface.co/new-space>:
   - Owner: your HF username
   - SDK: **Gradio**
   - Hardware: **CPU basic - free**
   - Visibility: Private (recommended).

2. Get a write-scoped HF access token:
   <https://huggingface.co/settings/tokens> → New token → role **Write**.

3. Push the cryptrink branch as the Space's `main`:
   ```bash
   git remote add space https://huggingface.co/spaces/<owner>/<space-name>
   git push space <branch>:main
   # If the Space already has the auto-init commit, force the first push:
   #   git push space <branch>:main --force
   ```

4. Watch **Logs** until the Space switches to **Running**. The
   front-matter at the top of `README.md` (`sdk: gradio`,
   `app_file: app.py`, `sdk_version: 6.x`) tells HF how to build it.
   `requirements.txt` is consumed verbatim — regenerate it whenever
   `pyproject.toml` changes via:
   ```bash
   poetry export --without-hashes --extras web -f requirements.txt -o requirements.txt
   ```

5. Walk the three tabs in the browser. The DB is ephemeral container
   disk on this tier — backtests, suggestions, and the live tab fall
   back to "no historical data" until you populate the DB. That's the
   expected demo path.

### 9b — Paid CPU Space with persistent storage and live trading

The Live tab needs the process to keep running between requests, and
SQLite needs to survive Space restarts. Both are satisfied by a paid
hardware tier plus an attached Storage Bucket.

1. **Upgrade hardware**: Space settings → Hardware → **CPU Upgrade**
   ($0.03/hr ≈ $22/mo). Paid hardware never sleeps.

2. **Attach a Storage Bucket**:
   ```bash
   hf buckets create /<owner>/<space-name>-data
   ```
   Then in the Space settings → **Storage Buckets** → attach the bucket
   at mount path `/data`. The Space gets a persistent read-write `/data`
   directory; restarts no longer erase the SQLite file.

3. **Set Space variables and secrets** (Space settings → **Variables and
   secrets**):

   | Name | Type | Required for | Notes |
   |------|------|--------------|-------|
   | `DB_URL` | Variable | Override the default | Optional. When `/data` is mounted at boot, cryptrink auto-defaults to `sqlite+aiosqlite:////data/cryptrink.db`. Set this only if you want a different path or driver. |
   | `REVOLUTX_API_KEY` | Secret | Live mode | From your Revolut X API console |
   | `REVOLUTX_PRIVATE_KEY` | Secret | Live mode | Base64-encoded raw 32-byte Ed25519 seed |
   | `REVOLUTX_PRIVATE_KEY_PATH` | Variable | Live mode (alt) | Use this *or* `REVOLUTX_PRIVATE_KEY`. Path to a PEM file checked into the Space repo. |
   | `NOTIFY_DISCORD_ENABLED` | Variable | Discord alerts | Set to `true` to enable |
   | `NOTIFY_DISCORD_WEBHOOK_URL` | Secret | Discord alerts | Discord channel webhook URL |
   | `CRYPTRINK_DEFAULT_STRATEGY` | Variable | Defaults | e.g. `sma_crossover` |
   | `CRYPTRINK_SYMBOLS` | Variable | Defaults | JSON list, e.g. `["BTC-EUR"]` |

   Without `REVOLUTX_API_KEY` and a private key, the Live tab still
   starts but silently falls back to paper mode — the status pane
   surfaces the fallback so you can confirm the operator's intent.

4. **Restart the Space** (Settings → Factory rebuild) so the new
   variables are picked up.

5. **Verify**:
   - Open the Live tab. The strategy dropdown shows the three built-ins.
   - Pick `paper` mode, click **Start**. The status pane reports
     "🟢 Running" and increments the iteration counter at your chosen
     interval. Click **Stop**; status flips to "⏹ Stopped" with a
     non-null `stopped_at`.
   - Pick `live` mode (when credentials are configured) and start a
     loop with a small interval. The status pane shows
     `Mode: live`. Trade alerts fire to Discord when an order is
     filled and `NOTIFY_DISCORD_ENABLED=true`.

### Security checklist for live mode

- Never commit `REVOLUTX_PRIVATE_KEY` to the repo. Use HF Secrets.
- Lock the Space repo: settings → Visibility → **Private**, and
  restrict collaborators.
- Set conservative `RISK_*` limits via env vars (e.g.
  `RISK_MAX_POSITION_SIZE_PCT=0.02`, `RISK_MAX_DAILY_LOSS_PCT=0.01`)
  before flipping the Mode radio to `live` for the first time.
- Watch the Status tab and Discord channel for the first few
  iterations; **Stop** the loop if anything looks wrong.

## Local Development

### Prerequisites

```bash
# Python 3.13+
python --version

# Poetry
curl -sSL https://install.python-poetry.org | python3 -

# Clone and install
git clone https://github.com/trinchetto/cryptrink.git
cd cryptrink
poetry install
```

### Running Locally

```bash
# Activate virtual environment
poetry shell

# Run in paper mode
cryptrink run --mode paper --strategy sma_crossover

# Run backtest
cryptrink backtest sma_crossover BTC-EUR --start 2024-01-01
```

### Environment Variables

Create a `.env` file (never commit this!):

```bash
# .env
REVOLUTX_API_KEY=your-api-key-here
REVOLUTX_PRIVATE_KEY=your-ed25519-private-key
CRYPTRINK_EXECUTION_MODE=paper
CRYPTRINK_LOG_LEVEL=INFO
```

---

## Docker Deployment

### Building the Image

```bash
# Build
docker build -t cryptrink:latest .

# Verify
docker images | grep cryptrink
```

### Running with Docker

```bash
# Paper trading
docker run -d \
  --name cryptrink \
  -e REVOLUTX_API_KEY=xxx \
  -e REVOLUTX_PRIVATE_KEY=xxx \
  -e CRYPTRINK_EXECUTION_MODE=paper \
  cryptrink:latest run --strategy sma_crossover

# With config file
docker run -d \
  --name cryptrink \
  -v $(pwd)/config.yaml:/app/config.yaml:ro \
  -e REVOLUTX_API_KEY=xxx \
  -e REVOLUTX_PRIVATE_KEY=xxx \
  cryptrink:latest run --config /app/config.yaml

# View logs
docker logs -f cryptrink

# Stop
docker stop cryptrink && docker rm cryptrink
```

### Docker Compose

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  cryptrink:
    build: .
    container_name: cryptrink
    restart: unless-stopped
    environment:
      - REVOLUTX_API_KEY=${REVOLUTX_API_KEY}
      - REVOLUTX_PRIVATE_KEY=${REVOLUTX_PRIVATE_KEY}
      - CRYPTRINK_EXECUTION_MODE=paper
      - CRYPTRINK_LOG_LEVEL=INFO
    volumes:
      - ./config.yaml:/app/config.yaml:ro
      - cryptrink-data:/app/data
    command: run --config /app/config.yaml

volumes:
  cryptrink-data:
```

Run with:
```bash
docker-compose up -d
docker-compose logs -f
```

---

## Google Cloud VM (GCE)

Best for production trading with persistent state.

### Setup

1. **Create VM**:
   - Go to GCE console
   - Create e2-micro (free tier) or e2-small
   - Select Ubuntu 22.04 LTS
   - Allow HTTP/HTTPS traffic (optional)

2. **SSH and Install Dependencies**:
```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python 3.13
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt install python3.13 python3.13-venv -y

# Install Poetry
curl -sSL https://install.python-poetry.org | python3.13 -

# Clone repo
git clone https://github.com/trinchetto/cryptrink.git
cd cryptrink
poetry install
```

3. **Configure Secrets**:
```bash
# Create environment file
sudo mkdir -p /etc/cryptrink
sudo nano /etc/cryptrink/env

# Add:
REVOLUTX_API_KEY=your-key
REVOLUTX_PRIVATE_KEY=your-private-key
CRYPTRINK_EXECUTION_MODE=paper
```

4. **Create Systemd Service**:
```bash
sudo nano /etc/systemd/system/cryptrink.service
```

```ini
[Unit]
Description=Cryptrink Trading Agent
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/cryptrink
EnvironmentFile=/etc/cryptrink/env
ExecStart=/home/ubuntu/.local/bin/poetry run cryptrink run --config config.yaml
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

5. **Enable and Start**:
```bash
sudo systemctl daemon-reload
sudo systemctl enable cryptrink
sudo systemctl start cryptrink
sudo systemctl status cryptrink

# View logs
sudo journalctl -u cryptrink -f
```

---

## Google Cloud Run

Serverless option, good for scheduled trading or suggestion mode.

### Limitations
- Stateless (use Cloud SQL for persistence)
- Cold starts (5-30 seconds)
- Max execution time: 60 minutes
- Not ideal for continuous trading

### Setup

1. **Enable APIs**:
```bash
gcloud services enable run.googleapis.com
gcloud services enable cloudbuild.googleapis.com
```

2. **Build and Push**:
```bash
# Configure Docker for GCR
gcloud auth configure-docker

# Build and push
docker build -t gcr.io/YOUR_PROJECT/cryptrink:latest .
docker push gcr.io/YOUR_PROJECT/cryptrink:latest
```

3. **Deploy**:
```bash
gcloud run deploy cryptrink \
  --image gcr.io/YOUR_PROJECT/cryptrink:latest \
  --platform managed \
  --region us-central1 \
  --set-env-vars="REVOLUTX_API_KEY=xxx,CRYPTRINK_EXECUTION_MODE=suggest" \
  --set-secrets="REVOLUTX_PRIVATE_KEY=cryptrink-private-key:latest" \
  --command="cryptrink" \
  --args="suggest,sma_crossover,BTC-EUR"
```

4. **Schedule with Cloud Scheduler**:
```bash
gcloud scheduler jobs create http cryptrink-hourly \
  --schedule="0 * * * *" \
  --uri="https://cryptrink-xxx.run.app" \
  --http-method=POST
```

---

## Fly.io

Alternative to Cloud Run with persistent volumes.

### Setup

1. **Install flyctl**:
```bash
curl -L https://fly.io/install.sh | sh
fly auth login
```

2. **Create fly.toml**:
```toml
app = "cryptrink"
primary_region = "ams"

[build]
  dockerfile = "Dockerfile"

[env]
  CRYPTRINK_EXECUTION_MODE = "paper"
  CRYPTRINK_LOG_LEVEL = "INFO"

[mounts]
  source = "cryptrink_data"
  destination = "/app/data"

[[services]]
  internal_port = 8080
  protocol = "tcp"

  [[services.ports]]
    port = 443
    handlers = ["tls", "http"]
```

3. **Set Secrets and Deploy**:
```bash
fly secrets set REVOLUTX_API_KEY=xxx
fly secrets set REVOLUTX_PRIVATE_KEY=xxx
fly deploy
```

---

## Monitoring

### Health Checks

Add a health endpoint (future enhancement):
```python
@app.command()
def health():
    """Health check endpoint."""
    print("OK")
```

### Logging

Configure JSON logging for cloud environments:
```yaml
# config.yaml
log_level: INFO
log_format: json  # Enable JSON logging
```

### Alerts

Configure Discord notifications:
```yaml
notifications:
  discord_enabled: true
  discord_webhook_url: "https://discord.com/api/webhooks/your-webhook-url"
```

---

## Security Checklist

Before deploying to production:

- [ ] API keys stored securely (environment variables, secrets manager)
- [ ] Private key never committed to git
- [ ] Paper trading mode tested first
- [ ] Risk limits configured appropriately
- [ ] Logging enabled for audit trail
- [ ] Monitoring and alerts configured
- [ ] Regular backups of trade history
- [ ] Network security (firewall rules)
