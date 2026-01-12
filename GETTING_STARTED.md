# Getting Started with Cryptrink

Complete guide to setting up and running integration tests with the Revolut X API.

## Prerequisites

- Python 3.13+
- Poetry installed
- OpenSSL (for generating Ed25519 keys)

## Quick Start

### Step 1: Generate Ed25519 Key Pair

Generate your Ed25519 private and public keys using OpenSSL:

```bash
# Generate private key
openssl genpkey -algorithm ed25519 -out private.pem

# Generate public key from private key
openssl pkey -in private.pem -pubout -out public.pem
```

Your files should now be:
- `private.pem` - Your Ed25519 private key (32 bytes)
- `public.pem` - Your Ed25519 public key (for Revolut X registration)

### Step 2: Create Revolut X API Key

1. Go to [Revolut X Web App](https://revx.revolut.com/) → Profile
2. Create a new API key
3. Paste the **full contents** of `public.pem` (including `-----BEGIN PUBLIC KEY-----` and `-----END PUBLIC KEY-----` lines)
4. Copy the generated API key (64-character alphanumeric string)

### Step 3: Run Setup Script

Run the automated setup script to configure everything:

```bash
poetry run python scripts/setup_secrets.py
```

This script will:
- ✅ Create the `secrets/` directory
- ✅ Move your PEM files to `secrets/`
- ✅ Set secure file permissions (Unix/Linux/macOS)
- ✅ Generate `.env.local` with all required configuration
- ✅ Provide the base64-encoded key for GitHub Actions

### Step 4: Add Your API Key

Edit `.env.local` and replace the placeholder with your actual API key:

```bash
REVOLUTX_API_KEY=your_actual_64_char_api_key_here
```

### Step 5: Run Integration Tests

```bash
# Run all integration tests
poetry run pytest tests/integration/ -v -m integration

# Run with verbose output
poetry run pytest tests/integration/ -v -s -m integration
```

## Understanding the Tests

### Safe Tests (Always Enabled)

#### 1. Connection Tests (`TestRevolutXConnection`)
- ✅ **100% Safe** - No modifications
- Tests authentication and symbol fetching

#### 2. Market Data Tests (`TestRevolutXMarketData`)
- ✅ **100% Safe** - Read-only operations
- Tests: ticker data, order book, recent trades

#### 3. Account Tests (`TestRevolutXAccount`)
- ✅ **100% Safe** - Read-only operations
- Tests: balance fetching for all currencies and specific currencies

#### 4. Order Tests - Read Only (`TestRevolutXOrdersReadOnly`)
- ✅ **100% Safe** - Read-only operations
- Tests: open orders, order history

### Write Tests (Disabled by Default)

#### 5. Order Creation Tests (`TestRevolutXOrdersWrite`)
- ⚠️ **CAUTION** - Creates real orders
- **DISABLED BY DEFAULT**
- Creates and immediately cancels test orders
- To enable: Set environment variable `SKIP_WRITE_TESTS=false`

## Expected Test Output

When running integration tests successfully, you'll see:

```
✓ Connected to Revolut X API
✓ Found 800+ trading symbols

✓ Ticker for BTC-USD:
  Last: $91,753.60

✓ Order book for BTC-USD:
  Best Bid: $91,767.00 (0.00217943 BTC)
  Best Ask: $92,200.00 (0.0010846 BTC)
  Spread: $433.00

✓ Recent trades: 10 trades fetched

✓ Account balances:
  MEW: 10722.63693333 (available: 10722.63693333)
  VET: 495.55552562 (available: 495.55552562)
  [...]

✓ Active orders: 0
✓ Order history: X orders

========================= 9 passed, 1 skipped =========================
```

## Running Specific Tests

### Run only connection tests:
```bash
poetry run pytest tests/integration/test_revolutx_live.py::TestRevolutXConnection -v
```

### Run only market data tests:
```bash
poetry run pytest tests/integration/test_revolutx_live.py::TestRevolutXMarketData -v
```

### Run only account tests:
```bash
poetry run pytest tests/integration/test_revolutx_live.py::TestRevolutXAccount -v
```

### Run specific test:
```bash
poetry run pytest tests/integration/test_revolutx_live.py::TestRevolutXMarketData::test_get_ticker -v
```

## Configuration Reference

After running `setup_secrets.py`, your `.env.local` will contain:

```ini
# Revolut X API Configuration
REVOLUTX_API_KEY=your_api_key_here
REVOLUTX_PRIVATE_KEY_PATH=./secrets/private.pem
REVOLUTX_BASE_URL=https://revx.revolut.com/api/1.0

# General Application Settings
CRYPTRINK_EXECUTION_MODE=paper
CRYPTRINK_LOG_LEVEL=INFO

# Risk Management
RISK_MAX_POSITION_SIZE_PCT=0.1
RISK_MAX_DAILY_LOSS_PCT=0.05
RISK_MAX_DRAWDOWN_PCT=0.15

# Database
DB_URL=sqlite+aiosqlite:///cryptrink.db

# Notifications (Optional)
NOTIFY_DISCORD_ENABLED=false
NOTIFY_DISCORD_WEBHOOK_URL=
```

### Environment Variables Explained

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `REVOLUTX_API_KEY` | **Yes** | Your 64-character Revolut X API key | - |
| `REVOLUTX_PRIVATE_KEY_PATH` | **Yes*** | Path to your `private.pem` file | `./secrets/private.pem` |
| `REVOLUTX_PRIVATE_KEY` | **Yes*** | Base64-encoded private key (for CI/CD) | - |
| `REVOLUTX_BASE_URL` | No | Revolut X API base URL | `https://revx.revolut.com/api/1.0` |
| `CRYPTRINK_EXECUTION_MODE` | No | Execution mode: `paper` or `live` | `paper` |
| `CRYPTRINK_LOG_LEVEL` | No | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR` | `INFO` |

\* Either `REVOLUTX_PRIVATE_KEY_PATH` (local) or `REVOLUTX_PRIVATE_KEY` (CI/CD) must be set.

## GitHub Actions / CI/CD Setup

The setup script generates a base64-encoded private key for CI/CD use.

### Add GitHub Secrets

1. Go to your repository → **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret**
3. Add these secrets:

| Secret Name | Value | Source |
|-------------|-------|--------|
| `REVOLUTX_API_KEY` | Your 64-char API key | From Revolut X dashboard |
| `REVOLUTX_PRIVATE_KEY` | Base64 key (44 chars) | From `setup_secrets.py` output |
| `REVOLUTX_BASE_URL` | `https://revx.revolut.com/api/1.0` | Fixed value |

The CI workflow will automatically use these secrets.

## Troubleshooting

### "private.pem not found"

**Solution:**
1. Ensure you generated keys with OpenSSL (Step 1)
2. Place `private.pem` in project root before running `setup_secrets.py`
3. The script will move it to `secrets/` automatically

### "Skipping integration test: REVOLUTX_API_KEY must be set"

**Solution:**
1. Verify `.env.local` exists in project root
2. Check that `REVOLUTX_API_KEY` is set in `.env.local`
3. Ensure python-dotenv is installed: `poetry install`

### Authentication Errors (401/403)

**Possible causes:**
- ❌ Incorrect API key
- ❌ Private key doesn't match the public key registered with Revolut X
- ❌ API key was regenerated but you're using the old one
- ❌ Wrong base URL

**Solution:**
1. Verify your API key is correct in `.env.local`
2. Ensure you uploaded the correct `public.pem` to Revolut X
3. Try regenerating keys and API credentials
4. Check that `REVOLUTX_BASE_URL=https://revx.revolut.com/api/1.0`

### "Private key file not found" During Tests

**Solution:**
1. Check that `secrets/private.pem` exists: `ls -la secrets/`
2. Verify `REVOLUTX_PRIVATE_KEY_PATH=./secrets/private.pem` in `.env.local`
3. Ensure path is relative to project root

### Connection Errors

**Possible causes:**
- ❌ No internet connection
- ❌ Firewall blocking requests
- ❌ Incorrect base URL

**Solution:**
1. Test internet connectivity: `ping revx.revolut.com`
2. Check firewall settings
3. Verify base URL is `https://revx.revolut.com/api/1.0`

### CI Tests Failing

**Solution:**
1. Verify all GitHub Secrets are set correctly
2. Check secret names match exactly (case-sensitive)
3. Ensure base64 key was copied correctly (no spaces, exactly 44 chars)
4. Re-run the setup script and update the `REVOLUTX_PRIVATE_KEY` secret

## Security Best Practices

### ✅ DO:
- Use the `setup_secrets.py` script for setup
- Store PEM files in the `secrets/` directory (gitignored)
- Use `.env.local` for local development (gitignored)
- Use GitHub Secrets for CI/CD
- Set restrictive file permissions (600) on keys
- Regularly rotate your API keys
- Use paper trading mode for development

### ❌ DON'T:
- Never commit `.env.local`, `*.pem`, or `*.key` files
- Never hardcode API keys in source code
- Never share private keys via email, chat, etc.
- Never commit files from the `secrets/` directory
- Never use production credentials for testing
- Never disable gitignore for sensitive files

## Important Notes

### Revolut X API

- **No Sandbox Environment**: Revolut X does not provide a separate sandbox/testnet environment
- **Real Money**: All API operations use real funds and execute real trades
- **Paper Trading Mode**: Use `CRYPTRINK_EXECUTION_MODE=paper` for testing strategies without executing real trades
- **Rate Limits**: Be aware of API rate limits when running tests

### File Structure

After setup, your project structure will be:

```
cryptrink/
├── secrets/                 # Gitignored
│   ├── private.pem         # Your Ed25519 private key
│   └── public.pem          # Your Ed25519 public key
├── .env.local              # Gitignored - Your local config
├── .env.example            # Removed (redundant)
├── scripts/
│   └── setup_secrets.py    # Setup automation
└── tests/
    └── integration/        # Integration tests
```

## Next Steps

After successful setup and test execution:

1. **Explore the codebase**
   - Review exchange implementation: `src/cryptrink/exchange/revolutx.py`
   - Study configuration: `src/cryptrink/core/config.py`

2. **Build trading strategies**
   - Check example strategies: `src/cryptrink/strategies/`
   - Implement your own strategy classes

3. **Run backtests**
   - Test strategies with historical data
   - Validate performance before live trading

4. **Paper trading**
   - Test strategies in paper trading mode (`CRYPTRINK_EXECUTION_MODE=paper`)
   - Monitor performance without risk

5. **Live trading** (when ready)
   - Switch to `CRYPTRINK_EXECUTION_MODE=live`
   - Start with small positions
   - Monitor carefully

## Additional Resources

- **Revolut X API Documentation**: [https://developer.revolut.com/docs/revolut-x](https://developer.revolut.com/docs/revolut-x)
- **Integration Status**: See `REVOLUTX_FINAL_STATUS.md` for API endpoint details
- **Configuration**: `src/cryptrink/core/config.py`
- **Tests**: `tests/integration/test_revolutx_live.py`

## Need Help?

1. Check logs with verbose output: `CRYPTRINK_LOG_LEVEL=DEBUG`
2. Run tests with verbose mode: `pytest -v -s`
3. Review this documentation thoroughly
4. Check the Revolut X API documentation
5. Review integration test source code for examples

---

**Generated by Cryptrink Setup Script** | Last Updated: 2026-01-12
