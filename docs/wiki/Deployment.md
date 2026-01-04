# Deployment Guide

This guide covers deployment options for Cryptrink, from local development to production cloud deployment.

## Deployment Options Comparison

| Option | Pros | Cons | Best For |
|--------|------|------|----------|
| **Local (PC)** | Full control, no latency | Must keep running, power costs | Development, backtesting |
| **Docker** | Portable, reproducible | Requires Docker knowledge | Any environment |
| **Cloud VM** | Always on, reliable | Monthly cost | Production trading |
| **Cloud Run** | Scales to zero, cheap | Cold starts, stateless | Scheduled trading |

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
- [ ] Sandbox mode tested first
- [ ] Risk limits configured appropriately
- [ ] Logging enabled for audit trail
- [ ] Monitoring and alerts configured
- [ ] Regular backups of trade history
- [ ] Network security (firewall rules)
