import json
import math
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
import streamlit as st

DEX_BASE = "https://api.dexscreener.com"
HELIUS_BASE = "https://api.helius.xyz/v0"

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

WATCHLIST_FILE = "watchlist.csv"
HISTORY_FILE = "scanner_history.csv"


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


def fmt_money(v: Any) -> str:
    v = safe_float(v, 0)
    if v >= 1_000_000:
        return f"${v/1_000_000:.2f}M"
    if v >= 1_000:
        return f"${v/1_000:.1f}k"
    return f"${v:,.0f}"


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


@st.cache_data(ttl=300, show_spinner=False)
def get_json(url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    headers = {"Accept": "application/json", "User-Agent": "meme-coin-watchlist-scanner/2.0"}
    response = requests.get(url, params=params, headers=headers, timeout=25)
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
    buys_6h = safe_int((txns.get("h6") or {}).get("buys"))
    sells_6h = safe_int((txns.get("h6") or {}).get("sells"))
    buys_1h = safe_int((txns.get("h1") or {}).get("buys"))
    sells_1h = safe_int((txns.get("h1") or {}).get("sells"))
    total_txns_24h = buys_24h + sells_24h
    buy_sell_ratio = buys_24h / sells_24h if sells_24h else None

    liquidity_usd = safe_float(liquidity.get("usd"))
    market_cap = safe_float(pair.get("marketCap"))
    fdv = safe_float(pair.get("fdv"))
    mc = market_cap or fdv
    mc_liq_ratio = mc / liquidity_usd if liquidity_usd else None

    created_ms = safe_int(pair.get("pairCreatedAt"), 0)
    age_hours = None
    if created_ms:
        age_hours = max(0, (datetime.now(timezone.utc).timestamp() - created_ms / 1000) / 3600)

    return {
        "source": source,
        "chain": pair.get("chainId"),
        "dex": pair.get("dexId"),
        "pair_created_at": pair.get("pairCreatedAt"),
        "age_hours": age_hours,
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
        "buys_6h": buys_6h,
        "sells_6h": sells_6h,
        "buys_1h": buys_1h,
        "sells_1h": sells_1h,
        "txns_24h": total_txns_24h,
        "buy_sell_ratio": buy_sell_ratio,
        "url": pair.get("url"),
        "pair_address": pair.get("pairAddress"),
        "solscan_token_url": f"https://solscan.io/token/{base.get('address')}" if pair.get("chainId") == "solana" and base.get("address") else "",
    }


def score_row(row: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    opportunity = 0
    risk = 0
    notes: List[str] = []
    red_flags: List[str] = []

    liq = row.get("liquidity_usd") or 0
    mc = row.get("market_cap") or row.get("fdv") or 0
    vol = row.get("volume_24h") or 0
    vol_1h = row.get("volume_1h") or 0
    ratio = row.get("mc_liquidity_ratio")
    txns = row.get("txns_24h") or 0
    buys = row.get("buys_24h") or 0
    sells = row.get("sells_24h") or 0
    chg1 = row.get("price_change_1h_pct") or 0
    chg24 = row.get("price_change_24h_pct") or 0
    age = row.get("age_hours")

    # Opportunity score, 0-100
    if liq >= 250000:
        opportunity += 18
    elif liq >= 100000:
        opportunity += 16
    elif liq >= 50000:
        opportunity += 12
    elif liq >= 25000:
        opportunity += 8
    else:
        opportunity += 2
        risk += 25
        red_flags.append("Thin liquidity")

    if 50_000 <= mc <= 1_000_000:
        opportunity += 18
        notes.append("Early cap range")
    elif 1_000_000 < mc <= 5_000_000:
        opportunity += 15
    elif 5_000_000 < mc <= 15_000_000:
        opportunity += 9
    elif mc > 25_000_000:
        opportunity += 2
        risk += 10
        notes.append("May already be discovered")
    else:
        opportunity += 5
        risk += 20
        red_flags.append("Ultra-low cap / extreme risk")

    if ratio is None:
        risk += 10
        notes.append("No MC/liquidity ratio")
    elif ratio <= 10:
        opportunity += 18
    elif ratio <= 25:
        opportunity += 14
    elif ratio <= 50:
        opportunity += 8
        risk += 12
        notes.append("Fragile MC/liquidity ratio")
    else:
        opportunity += 2
        risk += 28
        red_flags.append("High MC/liquidity ratio")

    if vol >= 1_000_000:
        opportunity += 14
    elif vol >= 250_000:
        opportunity += 12
    elif vol >= 50_000:
        opportunity += 8
    elif vol >= 10_000:
        opportunity += 4
    else:
        risk += 10
        notes.append("Low 24h volume")

    if vol and vol_1h:
        hourly_run_rate = vol_1h * 24
        if hourly_run_rate > vol * 1.5:
            opportunity += 8
            notes.append("1h volume accelerating")
        elif hourly_run_rate < vol * 0.25:
            risk += 8
            notes.append("1h volume fading")

    if txns >= 2000:
        opportunity += 8
    elif txns >= 500:
        opportunity += 6
    elif txns >= 100:
        opportunity += 3
    else:
        risk += 10
        notes.append("Low transaction count")

    if sells == 0 and buys > 0:
        opportunity += 2
        risk += 18
        red_flags.append("No sells shown; verify sellability")
    elif buys and sells:
        bs = buys / sells
        if 0.85 <= bs <= 1.7:
            opportunity += 10
        elif 1.7 < bs <= 3:
            opportunity += 6
            risk += 7
            notes.append("Buy pressure may be overheated")
        elif bs < 0.85:
            opportunity += 3
            risk += 12
            notes.append("Sell pressure elevated")
        else:
            opportunity += 1
            risk += 20
            red_flags.append("Potentially botted/overheated buys")

    if -10 <= chg1 <= 50 and -30 <= chg24 <= 200:
        opportunity += 8
    elif chg24 > 500:
        opportunity += 1
        risk += 25
        red_flags.append("Already pumped hard")
    elif chg24 < -50:
        opportunity += 2
        risk += 15
        red_flags.append("Sharp drawdown")
    else:
        opportunity += 4
        risk += 6

    if age is not None:
        if age < 2:
            opportunity += 5
            risk += 25
            red_flags.append("Extremely new token")
        elif age < 24:
            opportunity += 8
            risk += 12
            notes.append("New token")
        elif age <= 14 * 24:
            opportunity += 7
        else:
            opportunity += 3
            notes.append("Older token; check if narrative is stale")

    risk = max(0, min(100, round(risk, 1)))
    opportunity = max(0, min(100, round(opportunity, 1)))
    combined = max(0, min(100, round(opportunity - (risk * 0.35), 1)))

    if red_flags:
        label = "Avoid / Verify First" if risk >= 45 else "High Risk / Review"
    elif combined >= 75:
        label = "Watch Closely"
    elif combined >= 60:
        label = "Review"
    elif combined >= 45:
        label = "High Risk / Early"
    else:
        label = "Avoid / Low Quality"

    return {
        "opportunity_score": opportunity,
        "risk_score": risk,
        "score": combined,
        "label": label,
        "red_flags": "; ".join(red_flags) if red_flags else "None",
        "risk_notes": "; ".join(notes) if notes else "No major automated flags",
    }


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
                    time.sleep(0.03)
                except Exception:
                    continue

    if cfg.get("include_latest_boosts"):
        for boost in latest_boosts(top=False):
            if boost.get("chainId") == chain and boost.get("tokenAddress"):
                try:
                    for p in token_pairs(chain, boost["tokenAddress"]):
                        add_pair(p, "latest_boost")
                    time.sleep(0.03)
                except Exception:
                    continue

    if cfg.get("include_top_boosts"):
        for boost in latest_boosts(top=True):
            if boost.get("chainId") == chain and boost.get("tokenAddress"):
                try:
                    for p in token_pairs(chain, boost["tokenAddress"]):
                        add_pair(p, "top_boost")
                    time.sleep(0.03)
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


def load_csv(path: str) -> pd.DataFrame:
    if os.path.exists(path):
        try:
            return pd.read_csv(path)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


def append_history(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return load_csv(HISTORY_FILE)
    snap = df.copy()
    snap.insert(0, "snapshot_utc", now_utc())
    keep_cols = [
        "snapshot_utc", "chain", "symbol", "token_name", "token_address", "price_usd", "market_cap", "fdv",
        "liquidity_usd", "mc_liquidity_ratio", "volume_24h", "volume_1h", "price_change_24h_pct",
        "buys_24h", "sells_24h", "txns_24h", "opportunity_score", "risk_score", "score", "label", "red_flags", "url"
    ]
    snap = snap[[c for c in keep_cols if c in snap.columns]]
    hist = load_csv(HISTORY_FILE)
    hist = pd.concat([hist, snap], ignore_index=True) if not hist.empty else snap
    try:
        hist.to_csv(HISTORY_FILE, index=False)
    except Exception:
        pass
    return hist


def trend_from_history(hist: pd.DataFrame) -> pd.DataFrame:
    if hist.empty or "token_address" not in hist.columns:
        return pd.DataFrame()
    hist = hist.copy()
    hist["snapshot_utc_dt"] = pd.to_datetime(hist["snapshot_utc"], errors="coerce")
    hist = hist.dropna(subset=["snapshot_utc_dt"])
    if hist.empty:
        return pd.DataFrame()
    latest_idx = hist.groupby("token_address")["snapshot_utc_dt"].idxmax()
    first_idx = hist.groupby("token_address")["snapshot_utc_dt"].idxmin()
    latest = hist.loc[latest_idx].set_index("token_address")
    first = hist.loc[first_idx].set_index("token_address")
    rows = []
    for addr in latest.index:
        l = latest.loc[addr]
        f = first.loc[addr]
        price_change = None
        vol_change = None
        liq_change = None
        if safe_float(f.get("price_usd")):
            price_change = (safe_float(l.get("price_usd")) / safe_float(f.get("price_usd")) - 1) * 100
        if safe_float(f.get("volume_24h")):
            vol_change = (safe_float(l.get("volume_24h")) / safe_float(f.get("volume_24h")) - 1) * 100
        if safe_float(f.get("liquidity_usd")):
            liq_change = (safe_float(l.get("liquidity_usd")) / safe_float(f.get("liquidity_usd")) - 1) * 100
        rows.append({
            "symbol": l.get("symbol"),
            "token_name": l.get("token_name"),
            "token_address": addr,
            "snapshots": int((hist["token_address"] == addr).sum()),
            "latest_score": l.get("score"),
            "price_change_since_first_pct": price_change,
            "volume_change_since_first_pct": vol_change,
            "liquidity_change_since_first_pct": liq_change,
            "latest_url": l.get("url"),
        })
    return pd.DataFrame(rows).sort_values(["latest_score", "snapshots"], ascending=[False, False])


def parse_wallet_lines(text: str) -> List[Tuple[str, str]]:
    wallets: List[Tuple[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "," in line:
            name, addr = line.split(",", 1)
            wallets.append((name.strip(), addr.strip()))
        else:
            wallets.append((line[:6] + "..." + line[-4:], line))
    return wallets


@st.cache_data(ttl=180, show_spinner=False)
def helius_wallet_transactions(wallet: str, api_key: str, limit: int = 20) -> List[Dict[str, Any]]:
    url = f"{HELIUS_BASE}/addresses/{wallet}/transactions"
    params = {"api-key": api_key, "limit": limit}
    data = get_json(url, params=params)
    return data if isinstance(data, list) else []


def extract_wallet_token_activity(name: str, wallet: str, txs: List[Dict[str, Any]]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for tx in txs:
        tx_type = tx.get("type")
        desc = tx.get("description") or ""
        timestamp = tx.get("timestamp")
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if timestamp else ""
        signature = tx.get("signature")
        token_transfers = tx.get("tokenTransfers") or []
        native_transfers = tx.get("nativeTransfers") or []
        fee_payer = tx.get("feePayer")

        # Keep swaps and transactions where the watched wallet sent/received token transfers.
        involved = wallet in json.dumps(token_transfers) or wallet in json.dumps(native_transfers) or fee_payer == wallet
        if not involved:
            continue

        token_mints = []
        token_amounts = []
        for t in token_transfers:
            mint = t.get("mint")
            if mint and mint not in token_mints:
                token_mints.append(mint)
            amount = t.get("tokenAmount")
            if amount is not None:
                token_amounts.append(str(amount))

        rows.append({
            "wallet_name": name,
            "wallet": wallet,
            "time_utc": dt,
            "type": tx_type,
            "token_mints_seen": ", ".join(token_mints[:5]),
            "token_amounts_seen": ", ".join(token_amounts[:5]),
            "description": desc[:240],
            "solscan_tx": f"https://solscan.io/tx/{signature}" if signature else "",
        })
    return pd.DataFrame(rows)


def enrich_mints_from_dex(mints: List[str]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    seen = set()
    for mint in mints:
        if not mint or mint in seen:
            continue
        seen.add(mint)
        try:
            pairs = token_pairs("solana", mint)
            if not pairs:
                rows.append({"token_address": mint, "note": "No DEX Screener pair found yet", "solscan_token_url": f"https://solscan.io/token/{mint}"})
                continue
            best = sorted(pairs, key=lambda p: safe_float((p.get("liquidity") or {}).get("usd")), reverse=True)[0]
            row = pair_to_row(best, "whale_wallet")
            score = score_row(row, DEFAULT_CONFIG)
            row.update(score)
            rows.append(row)
        except Exception as e:
            rows.append({"token_address": mint, "note": f"Lookup failed: {e}", "solscan_token_url": f"https://solscan.io/token/{mint}"})
    return pd.DataFrame(rows)


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

tab1, tab2, tab3, tab4, tab5 = st.tabs(["Scanner", "Trends", "Watchlist", "Whale Tracker", "Guide"])

with tab1:
    c1, c2 = st.columns([1, 3])
    with c1:
        run = st.button("Run Scanner", type="primary", use_container_width=True)
    with c2:
        st.write("Finds fresh/trending pairs, filters obvious junk, scores opportunity and risk, and saves a snapshot.")

    if run:
        with st.spinner("Pulling token data and scoring candidates..."):
            try:
                df = collect_candidates(cfg)
            except Exception as e:
                st.error(f"Scanner failed: {e}")
                st.stop()
        st.session_state["results"] = df
        st.session_state["last_run"] = now_utc()
        hist = append_history(df)
        st.session_state["history"] = hist

    if "results" in st.session_state:
        df = st.session_state["results"]
        st.subheader(f"Results — last run {st.session_state.get('last_run', '')}")
        if df.empty:
            st.warning("No candidates matched your filters. Lower minimum volume/liquidity or add different search terms.")
        else:
            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Candidates", len(df))
            k2.metric("Median Score", round(df["score"].median(), 1))
            k3.metric("Median Risk", round(df["risk_score"].median(), 1))
            k4.metric("Median Liquidity", fmt_money(df["liquidity_usd"].median()))
            k5.metric("Median MC/Liq", round(df["mc_liquidity_ratio"].dropna().median(), 1) if not df["mc_liquidity_ratio"].dropna().empty else "N/A")

            display_cols = [
                "label", "score", "opportunity_score", "risk_score", "symbol", "token_name", "price_usd",
                "market_cap", "fdv", "liquidity_usd", "mc_liquidity_ratio", "volume_24h", "volume_1h",
                "price_change_24h_pct", "buys_24h", "sells_24h", "txns_24h", "red_flags", "risk_notes", "url", "solscan_token_url"
            ]
            st.dataframe(df[[c for c in display_cols if c in df.columns]], use_container_width=True, hide_index=True)

            st.download_button(
                "Download CSV Watchlist",
                data=df.to_csv(index=False).encode("utf-8"),
                file_name=f"meme_coin_watchlist_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
            )
            st.info("Manual review still required: verify holders, top wallets, liquidity lock/burn, social activity, and chart structure before risking money.")
    else:
        st.info("Adjust settings in the sidebar, then click Run Scanner.")

with tab2:
    st.subheader("Historical Snapshots & Momentum")
    uploaded = st.file_uploader("Optional: upload an older scanner_history.csv to continue your history", type=["csv"], key="history_upload")
    if uploaded is not None:
        try:
            hist_uploaded = pd.read_csv(uploaded)
            hist_existing = load_csv(HISTORY_FILE)
            hist = pd.concat([hist_existing, hist_uploaded], ignore_index=True).drop_duplicates()
            hist.to_csv(HISTORY_FILE, index=False)
            st.success("History uploaded and merged for this session.")
        except Exception as e:
            st.error(f"Could not read uploaded history: {e}")

    hist = st.session_state.get("history", load_csv(HISTORY_FILE))
    if hist.empty:
        st.info("Run the scanner a few times to build trend history. Streamlit storage may reset, so download your history periodically.")
    else:
        st.metric("Stored Snapshots", len(hist))
        trend = trend_from_history(hist)
        if not trend.empty:
            st.dataframe(trend, use_container_width=True, hide_index=True)
        st.download_button("Download History CSV", data=hist.to_csv(index=False).encode("utf-8"), file_name="scanner_history.csv", mime="text/csv")

with tab3:
    st.subheader("Manual Watchlist")
    st.write("Paste token addresses you want to monitor. The app will pull their current best DEX pair and score them.")
    watch_text = st.text_area("Solana token addresses, one per line", height=140, placeholder="Example:\nTOKEN_MINT_ADDRESS_1\nTOKEN_MINT_ADDRESS_2")
    if st.button("Check Watchlist", use_container_width=True):
        addresses = [x.strip() for x in watch_text.splitlines() if x.strip()]
        with st.spinner("Checking watchlist tokens..."):
            wdf = enrich_mints_from_dex(addresses)
        st.session_state["watchlist_df"] = wdf
    if "watchlist_df" in st.session_state:
        wdf = st.session_state["watchlist_df"]
        if wdf.empty:
            st.warning("No watchlist tokens found.")
        else:
            cols = ["label", "score", "risk_score", "symbol", "token_name", "market_cap", "liquidity_usd", "volume_24h", "red_flags", "risk_notes", "url", "solscan_token_url", "token_address"]
            st.dataframe(wdf[[c for c in cols if c in wdf.columns]], use_container_width=True, hide_index=True)
            st.download_button("Download Watchlist Check", data=wdf.to_csv(index=False).encode("utf-8"), file_name="manual_watchlist_check.csv", mime="text/csv")

with tab4:
    st.subheader("Whale Tracker")
    st.warning("Beginner-friendly whale tracking is useful, but it is not a guarantee. Whales can be wrong, paid, spoofing activity, or exiting before you.")
    st.write("This feature uses the optional Helius API for Solana wallet activity. Add a free/paid Helius API key in Streamlit secrets as `HELIUS_API_KEY`, or paste it below for temporary use.")

    default_key = ""
    try:
        default_key = st.secrets.get("HELIUS_API_KEY", "")
    except Exception:
        default_key = ""
    api_key = st.text_input("Helius API key", value=default_key, type="password")
    wallet_lines = st.text_area(
        "Wallets to monitor — one per line. Format can be `Name,WalletAddress` or just `WalletAddress`.",
        height=140,
        placeholder="Example:\nWhale 1,AbCd...\nWhale 2,EfGh...",
    )
    limit = st.slider("Transactions per wallet", 5, 50, 20, step=5)
    if st.button("Run Whale Tracker", use_container_width=True):
        if not api_key:
            st.error("Add a Helius API key first. Without one, use the Solscan links manually for wallet research.")
        else:
            wallets = parse_wallet_lines(wallet_lines)
            if not wallets:
                st.error("Add at least one wallet address.")
            else:
                all_activity: List[pd.DataFrame] = []
                with st.spinner("Checking whale wallet transactions..."):
                    for name, wallet in wallets:
                        try:
                            txs = helius_wallet_transactions(wallet, api_key, limit=limit)
                            activity = extract_wallet_token_activity(name, wallet, txs)
                            if not activity.empty:
                                all_activity.append(activity)
                            time.sleep(0.05)
                        except Exception as e:
                            all_activity.append(pd.DataFrame([{"wallet_name": name, "wallet": wallet, "description": f"Lookup failed: {e}"}]))
                activity_df = pd.concat(all_activity, ignore_index=True) if all_activity else pd.DataFrame()
                st.session_state["whale_activity"] = activity_df

                mints: List[str] = []
                if not activity_df.empty and "token_mints_seen" in activity_df.columns:
                    for m in activity_df["token_mints_seen"].dropna().astype(str):
                        for part in m.split(","):
                            part = part.strip()
                            if len(part) >= 32 and part not in mints:
                                mints.append(part)
                st.session_state["whale_tokens"] = enrich_mints_from_dex(mints[:30]) if mints else pd.DataFrame()

    if "whale_activity" in st.session_state:
        st.markdown("### Recent Wallet Activity")
        adf = st.session_state["whale_activity"]
        if adf.empty:
            st.info("No recent activity found for those wallets.")
        else:
            st.dataframe(adf, use_container_width=True, hide_index=True)
            st.download_button("Download Whale Activity", data=adf.to_csv(index=False).encode("utf-8"), file_name="whale_activity.csv", mime="text/csv")

    if "whale_tokens" in st.session_state:
        st.markdown("### Tokens Seen in Whale Activity")
        tdf = st.session_state["whale_tokens"]
        if tdf.empty:
            st.info("No DEX-listed tokens found from the wallet activity yet.")
        else:
            cols = ["label", "score", "risk_score", "symbol", "token_name", "market_cap", "liquidity_usd", "volume_24h", "red_flags", "risk_notes", "url", "solscan_token_url", "token_address", "note"]
            st.dataframe(tdf[[c for c in cols if c in tdf.columns]], use_container_width=True, hide_index=True)
            st.download_button("Download Whale Tokens", data=tdf.to_csv(index=False).encode("utf-8"), file_name="whale_tokens.csv", mime="text/csv")

    st.markdown("### How to find wallets to monitor")
    st.write("Open a promising token on Solscan, review top holders and recent large buyers, then add wallet addresses here. Avoid blindly copying a wallet unless you understand whether it is buying, selling, distributing, or just moving tokens between wallets.")

with tab5:
    st.subheader("How to Use This App")
    st.markdown(
        """
1. **Run Scanner** each morning to create a ranked shortlist.
2. Prioritize coins labeled **Watch Closely** or **Review**, but read the red flags first.
3. Use the DEX Screener and Solscan links to manually verify holders, largest wallet, chart, social activity, and liquidity status.
4. Download your history CSV regularly so you can compare what worked over time.
5. Use Whale Tracker only as a research aid. Copying wallets blindly is still very risky.

**Important:** This app intentionally does not place trades, generate guaranteed buy/sell signals, or promise profits.
        """
    )
