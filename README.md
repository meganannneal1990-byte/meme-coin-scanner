# Meme Coin Watchlist Scanner

A Streamlit screening dashboard for researching meme coin candidates. This is a decision-support tool only. It is **not financial advice**, not a trading bot, and not a guarantee of profit.

## Features

- DEX Screener data pull for fresh/trending pairs
- Solana-first scanner, with basic chain selector support
- Opportunity score and risk score
- Red-flag detection
- MC/liquidity ratio checks
- Volume and buy/sell pressure checks
- Historical snapshots and trend comparison
- Manual watchlist token checker
- Optional whale wallet tracker using Helius
- CSV exports

## Files

```text
app.py
requirements.txt
runtime.txt
README.md
```

## Deploy on Streamlit Community Cloud

1. Upload the files to your GitHub repo.
2. In Streamlit Community Cloud, create a new app from the repo.
3. Main file path: `app.py`
4. Python version: choose `3.11` in Advanced Settings if available.
5. Deploy.

## Optional: Helius API key for Whale Tracker

The Whale Tracker tab requires a Helius API key for Solana wallet transaction activity.

### Option A: Add it in Streamlit Secrets

In Streamlit Community Cloud:

1. Open the app settings.
2. Go to Secrets.
3. Add:

```toml
HELIUS_API_KEY = "your_api_key_here"
```

4. Save and reboot the app.

### Option B: Paste it in the app

You can paste the API key directly into the Whale Tracker tab. This is easier for testing, but Streamlit Secrets is cleaner.

## Important Limitations

- DEX Screener data does not provide full holder distribution or full wallet concentration.
- Whale tracking is informational only. Wallets may be wrong, paid, spoofing, or already exiting.
- Streamlit Community Cloud file storage can reset. Download your `scanner_history.csv` regularly.
- Always manually verify top holders, largest wallet, liquidity lock/burn, social activity, and chart structure before risking money.
