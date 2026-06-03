# Meme Coin Watchlist Scanner

A local Streamlit dashboard that scans public DEX Screener endpoints for Solana meme coin candidates, filters low-quality pairs, scores the remaining candidates, and exports a CSV watchlist.

This is a **screening tool only**. It does not place trades, does not guarantee profit, and should not be treated as financial advice.

## What it pulls

The app uses public DEX Screener endpoints:

- Latest token profiles
- Latest boosted tokens
- Top boosted tokens
- Search endpoint using configurable terms
- Token pair details by chain/token address

## Metrics shown

- Token / symbol
- Chain and DEX
- Price
- Market cap
- FDV
- Liquidity
- Market cap / liquidity ratio
- 24h volume
- 1h / 6h / 24h price change
- 24h buys and sells
- 24h transactions
- Automated risk notes
- DEX Screener link

## How to run

1. Install Python 3.10+.
2. Open a terminal in this folder.
3. Run:

```bash
pip install -r requirements.txt
streamlit run app.py
```

## How to use

1. Keep `Chain` set to `solana` to start.
2. Start with these filters:
   - Minimum liquidity: `$25,000`
   - Minimum 24h volume: `$25,000`
   - Maximum MC/Liquidity ratio: `60`
   - Maximum market cap: `$25,000,000`
3. Click **Run Scanner**.
4. Review candidates marked **Watch Closely** or **Review**.
5. Manually verify:
   - Largest wallet percentage
   - Top 10 / Top 20 holders
   - Liquidity lock/burn status
   - Whether volume looks botted
   - Whether the chart has already pumped and dumped

## Scoring model

The MVP scores each candidate from 0 to 100 using:

- Liquidity strength
- Market-cap upside range
- Market cap / liquidity ratio
- 24h volume
- Transaction participation
- Buy/sell balance
- Momentum sanity

This is intentionally conservative and should be tuned after you paper-trade results for at least 2-4 weeks.

## Important limitations

DEX Screener does not provide every risk metric needed to trade safely. In particular, this app does not currently pull:

- Largest holder percentage
- Top 10 / Top 20 holder percentage
- Liquidity lock/burn verification
- Developer wallet behavior
- Full holder growth history

Those can be added later using Solana RPC, Birdeye, Helius, Moralis, Solscan, or Bitquery APIs.
