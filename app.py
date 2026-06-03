import json
import math
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
import streamlit as st

DEX_BASE = "https://api.dexscreener.com"

DEFAULT_CONFIG = {
    "chain": "solana",
    "min_liquidity_usd": 25000,
    "max_market_cap_usd": 25000000,
    "min_volume_24h_usd": 25000,
    "max_mc_liquidity_ratio": 60,
    "min_txns_24h": 50,
    "max_results": 100,
    "search_terms": ["solana", "raydium", "pump"],
    "include_latest_profiles": True,
    "include_latest_boosts": True,
    "include_top_boosts": True,
}


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in [None, "", "null"]:
            return default
        return float(value)
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in [None, "", "null"]:
            return default
        return int(float(value))
    except Exception:
        return default


@st.cache_data(ttl=300, show_spinner=False)
def get_json(url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    headers = {"Accept": "application/json", "User-Agent": "meme-coin-watchlist-scanner/1.0"}
    response = requests.get(url, params=params, headers=headers, timeout=20)
    response.raise_for_status()
    return response.json()


def latest_profiles() -> List[Dict[str, Any]]:
    data = get_json(f"{DEX_BASE}/token-profiles/latest/v1")
    return data if isinstance(data, list) else []


def latest_boosts(top: bool = False) -> List[Dict[str, Any]]:
    path = "/token-boosts/top/v1" if top else "/token-boosts/latest/v1"
    data = get_json(f"{DEX_BASE}{path}")
    return data if isinstance(data, list) else []


def search_pairs(query: str) -> List[Dict[str, Any]]:
    data = get_json(f"{DEX_BASE}/latest/dex/search", params={"q": query})
    return data.get("pairs", []) if isinstance(data, dict) else []


def token_pairs(chain: str, token_address: str) -> List[Dict[str, Any]]:
    data = get_json(f"{DEX_BASE}/token-pairs/v1/{chain}/{token_address}")
    return data if isinstance(data, list) else []


def pair_to_row(pair: Dict[str, Any], source: str) -> Dict[str, Any]:
    liquidity = pair.get("liquidity") or {}
    txns = pair.get("txns") or {}
    volume = pair.get("volume") or {}
    price_change = pair.get("priceChange") or {}
    base = pair.get("baseToken") or {}
    quote = pair.get("quoteToken") or {}

    buys_24h = safe_int((txns.get("h24") or {}).get("buys"))
    sells_24h = safe_int((txns.get("h24") or {}).get("sells"))
    total_txns_24h = buys_24h + sells_24h
    buy_sell_ratio = buys_24h / sells_24h if sells_24h else None

    liquidity_usd = safe_float(liquidity.get("usd"))
    market_cap = safe_float(pair.get("marketCap"))
    fdv = safe_float(pair.get("fdv"))
    mc = market_cap or fdv
    mc_liq_ratio = mc / liquidity_usd if liquidity_usd else None

    return {
        "source": source,
        "chain": pair.get("chainId"),
        "dex": pair.get("dexId"),
        "pair_created_at": pair.get("pairCreatedAt"),
        "token_name": base.get("name"),
        "symbol": base.get("symbol"),
        "token_address": base.get("address"),
        "quote_symbol": quote.get("symbol"),
        "price_usd": safe_float(pair.get("priceUsd")),
        "market_cap": market_cap,
        "fdv": fdv,
        "liquidity_usd": liquidity_usd,
        "mc_liquidity_ratio": mc_liq_ratio,
        "volume_24h": safe_float(volume.get("h24")),
        "volume_6h": safe_float(volume.get("h6")),
        "volume_1h": safe_float(volume.get("h1")),
        "price_change_24h_pct": safe_float(price_change.get("h24")),
        "price_change_6h_pct": safe_float(price_change.get("h6")),
        "price_change_1h_pct": safe_float(price_change.get("h1")),
        "buys_24h": buys_24h,
        "sells_24h": sells_24h,
        "txns_24h": total_txns_24h,
        "buy_sell_ratio": buy_sell_ratio,
        "url": pair.get("url"),
        "pair_address": pair.get("pairAddress"),
    }


def score_row(row: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    score = 0
    notes = []

    liq = row.get("liquidity_usd") or 0
    mc = row.get("market_cap") or row.get("fdv") or 0
    vol = row.get("volume_24h") or 0
    ratio = row.get("mc_liquidity_ratio")
    txns = row.get("txns_24h") or 0
    buys = row.get("buys_24h") or 0
    sells = row.get("sells_24h") or 0
    chg1 = row.get("price_change_1h_pct") or 0
    chg24 = row.get("price_change_24h_pct") or 0

    # Liquidity strength, 0-20
    if liq >= 250000:
        score += 20
    elif liq >= 100000:
        score += 16
    elif liq >= 50000:
        score += 12
    elif liq >= 25000:
        score += 8
    else:
        score += 2
        notes.append("Thin liquidity")

    # Market-cap upside range, 0-15
    if 50000 <= mc <= 1000000:
        score += 15
        notes.append("Very early cap range")
    elif 1000000 < mc <= 5000000:
        score += 12
    elif 5000000 < mc <= 15000000:
        score += 8
    elif mc > 25000000:
        score += 2
        notes.append("May already be discovered")
    else:
        score += 4
        notes.append("Ultra-low cap / extreme risk")

    # MC/liquidity ratio, 0-20
    if ratio is None:
        notes.append("No MC/liquidity ratio")
    elif ratio <= 10:
        score += 20
    elif ratio <= 25:
        score += 15
    elif ratio <= 50:
        score += 8
        notes.append("Fragile liquidity ratio")
    else:
        score += 2
        notes.append("High MC/liquidity ratio")

    # Volume, 0-15
    if vol >= 1000000:
        score += 15
    elif vol >= 250000:
        score += 12
    elif vol >= 50000:
        score += 8
    elif vol >= 10000:
        score += 4
    else:
        notes.append("Low 24h volume")

    # Participation, 0-10
    if txns >= 2000:
        score += 10
    elif txns >= 500:
        score += 7
    elif txns >= 100:
        score += 4
    else:
        notes.append("Low transaction count")

    # Buy/sell balance, 0-10
    if sells == 0 and buys > 0:
        score += 4
        notes.append("No sells shown; verify sellability")
    elif buys and sells:
        bs = buys / sells
        if 0.8 <= bs <= 1.8:
            score += 10
        elif 1.8 < bs <= 3:
            score += 7
            notes.append("Buy pressure may be overheated")
        elif bs < 0.8:
            score += 4
            notes.append("Sell pressure elevated")
        else:
            score += 2
            notes.append("Potentially botted/overheated buys")

    # Momentum sanity, 0-10
    if -10 <= chg1 <= 50 and -30 <= chg24 <= 200:
        score += 10
    elif chg24 > 500:
        score += 2
        notes.append("Already pumped hard")
    elif chg24 < -50:
        score += 3
        notes.append("Sharp drawdown")
    else:
        score += 6

    score = max(0, min(100, round(score, 1)))
    if score >= 75:
        label = "Watch Closely"
    elif score >= 60:
        label = "Review"
    elif score >= 45:
        label = "High Risk / Early"
    else:
        label = "Avoid / Low Quality"

    return {"score": score, "label": label, "risk_notes": "; ".join(notes) if notes else "No major automated flags"}


def collect_candidates(cfg: Dict[str, Any]) -> pd.DataFrame:
    chain = cfg["chain"].lower().strip()
    pairs: List[Dict[str, Any]] = []
    seen_pair_addresses = set()

    def add_pair(p: Dict[str, Any], source: str):
        if not p or p.get("chainId") != chain:
            return
        pair_addr = p.get("pairAddress")
        if pair_addr and pair_addr in seen_pair_addresses:
            return
        if pair_addr:
            seen_pair_addresses.add(pair_addr)
        pairs.append(pair_to_row(p, source))

    if cfg.get("include_latest_profiles"):
        for profile in latest_profiles():
            if profile.get("chainId") == chain and profile.get("tokenAddress"):
                try:
                    for p in token_pairs(chain, profile["tokenAddress"]):
                        add_pair(p, "latest_profile")
                    time.sleep(0.05)
                except Exception:
                    continue

    if cfg.get("include_latest_boosts"):
        for boost in latest_boosts(top=False):
            if boost.get("chainId") == chain and boost.get("tokenAddress"):
                try:
                    for p in token_pairs(chain, boost["tokenAddress"]):
                        add_pair(p, "latest_boost")
                    time.sleep(0.05)
                except Exception:
                    continue

    if cfg.get("include_top_boosts"):
        for boost in latest_boosts(top=True):
            if boost.get("chainId") == chain and boost.get("tokenAddress"):
                try:
                    for p in token_pairs(chain, boost["tokenAddress"]):
                        add_pair(p, "top_boost")
                    time.sleep(0.05)
                except Exception:
                    continue

    for term in cfg.get("search_terms", []):
        try:
            for p in search_pairs(term):
                add_pair(p, f"search:{term}")
        except Exception:
            continue

    df = pd.DataFrame(pairs)
    if df.empty:
        return df

    # Filters
    df = df[df["liquidity_usd"].fillna(0) >= cfg["min_liquidity_usd"]]
    df = df[df["volume_24h"].fillna(0) >= cfg["min_volume_24h_usd"]]
    df = df[df["txns_24h"].fillna(0) >= cfg["min_txns_24h"]]
    df = df[(df["market_cap"].fillna(df["fdv"]).fillna(0) <= cfg["max_market_cap_usd"]) | (df["market_cap"].isna())]
    df = df[(df["mc_liquidity_ratio"].isna()) | (df["mc_liquidity_ratio"] <= cfg["max_mc_liquidity_ratio"])]

    if df.empty:
        return df

    scored = df.apply(lambda r: score_row(r.to_dict(), cfg), axis=1, result_type="expand")
    df = pd.concat([df.reset_index(drop=True), scored.reset_index(drop=True)], axis=1)
    df = df.sort_values(["score", "volume_24h", "liquidity_usd"], ascending=[False, False, False]).head(cfg["max_results"])
    return df


st.set_page_config(page_title="Meme Coin Watchlist Scanner", layout="wide")
st.title("Meme Coin Watchlist Scanner")
st.caption("Screening dashboard only — not financial advice, not automated trading, and not a guarantee of profit.")

with st.sidebar:
    st.header("Scanner Settings")
    chain = st.selectbox("Chain", ["solana", "ethereum", "base", "bsc"], index=0)
    min_liq = st.number_input("Minimum liquidity USD", min_value=0, value=DEFAULT_CONFIG["min_liquidity_usd"], step=5000)
    max_mc = st.number_input("Maximum market cap USD", min_value=0, value=DEFAULT_CONFIG["max_market_cap_usd"], step=1000000)
    min_vol = st.number_input("Minimum 24h volume USD", min_value=0, value=DEFAULT_CONFIG["min_volume_24h_usd"], step=5000)
    max_ratio = st.number_input("Maximum MC/Liquidity ratio", min_value=1, value=DEFAULT_CONFIG["max_mc_liquidity_ratio"], step=5)
    min_txns = st.number_input("Minimum 24h transactions", min_value=0, value=DEFAULT_CONFIG["min_txns_24h"], step=10)
    max_results = st.slider("Max results", min_value=10, max_value=200, value=DEFAULT_CONFIG["max_results"], step=10)
    terms = st.text_area("Search terms, one per line", value="\n".join(DEFAULT_CONFIG["search_terms"]))

    include_profiles = st.checkbox("Include latest token profiles", value=True)
    include_boosts = st.checkbox("Include latest boosts", value=True)
    include_top_boosts = st.checkbox("Include top boosts", value=True)

cfg = {
    "chain": chain,
    "min_liquidity_usd": min_liq,
    "max_market_cap_usd": max_mc,
    "min_volume_24h_usd": min_vol,
    "max_mc_liquidity_ratio": max_ratio,
    "min_txns_24h": min_txns,
    "max_results": max_results,
    "search_terms": [x.strip() for x in terms.splitlines() if x.strip()],
    "include_latest_profiles": include_profiles,
    "include_latest_boosts": include_boosts,
    "include_top_boosts": include_top_boosts,
}

if st.button("Run Scanner", type="primary"):
    with st.spinner("Pulling token data and scoring candidates..."):
        try:
            df = collect_candidates(cfg)
        except Exception as e:
            st.error(f"Scanner failed: {e}")
            st.stop()

    st.session_state["results"] = df
    st.session_state["last_run"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

if "results" in st.session_state:
    df = st.session_state["results"]
    st.subheader(f"Results — last run {st.session_state.get('last_run', '')}")

    if df.empty:
        st.warning("No candidates matched your filters. Lower minimum volume/liquidity or add different search terms.")
    else:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Candidates", len(df))
        k2.metric("Median Score", round(df["score"].median(), 1))
        k3.metric("Median Liquidity", f"${df['liquidity_usd'].median():,.0f}")
        k4.metric("Median MC/Liq", round(df["mc_liquidity_ratio"].dropna().median(), 1) if not df["mc_liquidity_ratio"].dropna().empty else "N/A")

        display_cols = [
            "label", "score", "symbol", "token_name", "price_usd", "market_cap", "fdv", "liquidity_usd",
            "mc_liquidity_ratio", "volume_24h", "price_change_24h_pct", "buys_24h", "sells_24h",
            "txns_24h", "risk_notes", "url"
        ]
        st.dataframe(df[display_cols], use_container_width=True, hide_index=True)

        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download CSV Watchlist",
            data=csv,
            file_name=f"meme_coin_watchlist_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
        )

        st.info("Manual review still required: verify holders, top wallets, liquidity lock/burn, social activity, and chart structure before risking money.")
else:
    st.info("Adjust settings in the sidebar, then click Run Scanner.")
