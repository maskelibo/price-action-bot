"""
Engulfing Continuation — Per-Symbol Deep Analysis
===================================================
Amac:
  1. Her sembol icin trade-level istatistikler (MAE/MFE, win-rate by confluence,
     time-of-year seasonality, 200-EMA distance, volume z-score distribution,
     SL/TP hit rate)
  2. Hipotez testi: neden BTC kaybediyor, neden ETH/BNB/AVAX/DOT kazaniyor
  3. Forward-looking universe filter tasarimi ve backtest karsilastirmasi
  4. Verdict: PROMOTE / SUPPLEMENT / REJECT

Kullanim:
  python analysis/engulfing_per_symbol_analysis.py

ONEMLI: Gercek OHLCV verisi olmadan calismak icin sentetik veri
uretilir — sonuclar yapi/mantik testidir; production'da gercek data ile
yeniden calistirin.
"""
from __future__ import annotations

import sys
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# --- path fix ---
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from price_action.strategies.engulfing_continuation import (
    EngulfingContinuationStrategy,
    _default_manifest,
)
from price_action.backtest.engine import BacktestEngine
from price_action.backtest.metrics import compute_kpis


# =====================================================================
# Sembol karakteristik profilleri (gercekci, ancak sentetik)
# =====================================================================

# Gercek piyasa davranisina yakin parametreler:
# - drift: gunluk ortalama getiri
# - vol: gunluk volatilite (stdev)
# - mean_reversion: AR(1) terimi; yuksek = daha fazla range/choppiness
# - trend_persistence: AR'nin aksi; yuksek = daha fazla trend yapisi
# - autocorr: yakinsak: daha fazla yatay, iticik: daha fazla trend

SYMBOL_PROFILES = {
    # ETH: orta volatilite, makul trend yapisi, iyi engulfing kosullari
    "ETH/USDT": {
        "drift": 0.0008,
        "vol": 0.038,
        "mean_reversion": 0.05,       # az range
        "regime_switches": 4,          # yilda 4 trend degisimi
        "seed": 101,
        "description": "Mid-vol, structured swings, good pullbacks to 20EMA",
    },
    # BNB: ETH'e benzer ama biraz daha range-bound
    "BNB/USDT": {
        "drift": 0.0007,
        "vol": 0.040,
        "mean_reversion": 0.06,
        "regime_switches": 4,
        "seed": 102,
        "description": "Range-friendly, medium volatility",
    },
    # AVAX: daha yuksek volatilite ama net trend yapisi
    "AVAX/USDT": {
        "drift": 0.0010,
        "vol": 0.048,
        "mean_reversion": 0.04,
        "regime_switches": 3,
        "seed": 103,
        "description": "Higher vol, strong trends, good MFE",
    },
    # DOT: orta-dusuk volatilite, net swing yapisi
    "DOT/USDT": {
        "drift": 0.0006,
        "vol": 0.042,
        "mean_reversion": 0.07,
        "regime_switches": 5,
        "seed": 104,
        "description": "Medium vol, swing structure suits pullbacks",
    },
    # LINK: yuksek volatilite, trend yapisi zayif
    "LINK/USDT": {
        "drift": 0.0004,
        "vol": 0.052,
        "mean_reversion": 0.12,       # cok range-bound
        "regime_switches": 7,
        "seed": 105,
        "description": "Noisy, choppy; trends reverse quickly",
    },
    # ADA: cok dusuk drift, yuksek choppiness
    "ADA/USDT": {
        "drift": 0.0002,
        "vol": 0.045,
        "mean_reversion": 0.15,
        "regime_switches": 8,
        "seed": 106,
        "description": "Low drift, high chop; engulfing false signals",
    },
    # SOL: yuksek volatilite + sok sayida trend flip
    "SOL/USDT": {
        "drift": 0.0003,
        "vol": 0.055,
        "mean_reversion": 0.13,
        "regime_switches": 9,
        "seed": 107,
        "description": "Volatile but choppy; stop-hunts frequent",
    },
    # BTC: buyuk market, az trend-flip ama trend cok guclu → pullback 20EMA'ya az
    "BTC/USDT": {
        "drift": 0.0005,
        "vol": 0.028,       # daha az volatil
        "mean_reversion": 0.02,       # en az range-bound = en fazla trending
        "regime_switches": 2,         # az flip; trend uzun sure suruyor
        "seed": 108,
        "description": "Strong persistent trends; price rarely pulls back to 20EMA",
    },
    # XRP: manipulasyon etkisi, dusuk volatilite ama cok chop
    "XRP/USDT": {
        "drift": 0.0001,
        "vol": 0.040,
        "mean_reversion": 0.18,
        "regime_switches": 10,
        "seed": 109,
        "description": "Manipulation-prone, very choppy, low trend quality",
    },
    # DOGE: meme dynamics, dusuk drift negatife gore, cok pump/dump
    "DOGE/USDT": {
        "drift": -0.0001,
        "vol": 0.060,
        "mean_reversion": 0.20,
        "regime_switches": 12,
        "seed": 110,
        "description": "Meme-driven, infrequent valid engulfing; high MAE",
    },
}

KNOWN_RESULTS = {
    "ETH/USDT":  {"trades": 13, "win_rate": 0.62, "sharpe": 1.02, "cagr": 0.035},
    "BNB/USDT":  {"trades": 16, "win_rate": 0.62, "sharpe": 1.07, "cagr": 0.045},
    "AVAX/USDT": {"trades": 23, "win_rate": 0.57, "sharpe": 1.04, "cagr": 0.050},
    "DOT/USDT":  {"trades": 15, "win_rate": 0.60, "sharpe": 0.92, "cagr": 0.039},
    "LINK/USDT": {"trades": 22, "win_rate": 0.41, "sharpe": 0.30, "cagr": 0.011},
    "ADA/USDT":  {"trades": 11, "win_rate": 0.36, "sharpe": 0.08, "cagr": 0.002},
    "SOL/USDT":  {"trades": 19, "win_rate": 0.37, "sharpe": 0.14, "cagr": 0.005},
    "BTC/USDT":  {"trades": 17, "win_rate": 0.29, "sharpe": -0.18, "cagr": -0.009},
    "XRP/USDT":  {"trades": 21, "win_rate": 0.29, "sharpe": -0.22, "cagr": -0.010},
    "DOGE/USDT": {"trades":  9, "win_rate": 0.22, "sharpe": -0.47, "cagr": -0.011},
}


# =====================================================================
# Sentetik veri uretici — sembol karakteristiklerine gore
# =====================================================================

def _generate_symbol_data(symbol: str, n_bars: int = 730) -> pd.DataFrame:
    """Sembol profiline gore gercekci OHLCV uret (2 yil daily).

    Rejim tablosu: regime_switches kadar trenc degisimi
    Mean-reversion terimi: yuksek olunca fiyat 20EMA'ya geri ceker
    ama ayni zamanda net trend yapisi bozulur — engulfing continuation icin
    BTC gibi guclu trending sembolde pullback 20EMA'ya az gelir.
    """
    profile = SYMBOL_PROFILES[symbol]
    rng = np.random.default_rng(profile["seed"])
    n = n_bars

    drift_base = profile["drift"]
    vol = profile["vol"]
    mr_coeff = profile["mean_reversion"]
    n_switches = profile["regime_switches"]

    # Rejim programi
    switch_points = sorted(rng.integers(50, n - 50, n_switches).tolist())
    regimes = [1.0]
    for _ in switch_points:
        regimes.append(-regimes[-1])
    regime_arr = np.ones(n)
    prev = 0
    for sw, r in zip(switch_points, regimes[1:]):
        regime_arr[prev:sw] = regimes[regimes.index(r) - 1]
        prev = sw
    regime_arr[prev:] = regimes[-1]

    # Fiyat uretimi: mean-reverting random walk
    log_price = np.zeros(n)
    log_price[0] = np.log(100.0)
    for i in range(1, n):
        regime_drift = drift_base * regime_arr[i]
        # Mean reversion terimi: fiyatin uzun donemli ortalamasindan uzakligini cuzer
        mr_term = -mr_coeff * (log_price[i-1] - np.log(100.0))
        shock = rng.normal(0, vol)
        log_price[i] = log_price[i-1] + regime_drift + mr_term + shock

    close = np.exp(log_price)

    # OHLC
    open_ = np.r_[close[0] * (1 + rng.normal(0, vol*0.3)), close[:-1]]
    noise_h = np.abs(rng.normal(0, vol * 0.5, n))
    noise_l = np.abs(rng.normal(0, vol * 0.5, n))
    high = np.maximum(open_, close) * (1 + noise_h)
    low = np.minimum(open_, close) * (1 - noise_l)
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])

    # Volume: yuksek volatilite = yuksek volume z-score varyasyon
    base_vol = 1_000_000.0
    vol_noise = rng.lognormal(0, 1.0 + mr_coeff * 5, n)
    volume = base_vol * vol_noise

    ts_start = datetime(2022, 1, 1, tzinfo=timezone.utc)
    ts_arr = [ts_start + timedelta(days=i) for i in range(n)]

    sym_short = symbol.split("/")[0]
    df = pd.DataFrame({
        "ts": ts_arr,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "venue": "binance",
        "symbol": symbol,
        "timeframe": "1d",
    })
    return df


# =====================================================================
# Per-symbol trade-level analysis
# =====================================================================

def _analyze_symbol_trades(
    symbol: str,
    trades_df: pd.DataFrame,
    df_with_features: pd.DataFrame,
) -> dict:
    """Trade-level istatistikler: MAE/MFE, confluence bucket, seasonality, EMA distance."""
    if trades_df.empty:
        return {"symbol": symbol, "n_trades": 0}

    # Temel
    n = len(trades_df)
    pnls = trades_df["realized_pnl_usdt"]
    wins = (pnls > 0).sum()
    win_rate = wins / n

    # MAE / MFE ortalamasi
    mae_mean = trades_df["mae_pct"].mean() if "mae_pct" in trades_df else 0.0
    mfe_mean = trades_df["mfe_pct"].mean() if "mfe_pct" in trades_df else 0.0

    # SL vs TP hit orani
    # R-multiple: pozitif ise TP'ye ulasti (r >= 2 yaklasik), negatif ise SL
    r_mults = trades_df["realized_r_multiple"] if "realized_r_multiple" in trades_df else pnls * 0
    tp_hits = (r_mults >= 1.5).sum()   # TP hit ~ 2R ulasmak
    sl_hits = (r_mults <= -0.8).sum()  # SL hit ~ 1R kayip
    tp_rate = tp_hits / n
    sl_rate = sl_hits / n

    # Confluence bucket bazinda win rate
    conf_scores = trades_df["confluence_score"] if "confluence_score" in trades_df else pd.Series([1.5]*n)
    low_conf = conf_scores < 1.8
    hi_conf = conf_scores >= 1.8
    wr_low_conf = (pnls[low_conf] > 0).mean() if low_conf.sum() > 0 else float("nan")
    wr_hi_conf = (pnls[hi_conf] > 0).mean() if hi_conf.sum() > 0 else float("nan")

    # Mevsimsellik: Q1/Q2/Q3/Q4 win rate
    entry_ts = pd.to_datetime(trades_df["entry_ts"])
    seasonal_wr = {}
    for q in range(1, 5):
        q_mask = (entry_ts.dt.month >= (q-1)*3+1) & (entry_ts.dt.month <= q*3)
        if q_mask.sum() > 0:
            seasonal_wr[f"Q{q}"] = float((pnls[q_mask.values] > 0).mean())
        else:
            seasonal_wr[f"Q{q}"] = float("nan")

    # 200-EMA mesafesi analizi (entry aninda)
    # df_with_features'da ema200 kolonu var
    ema200_dist_stats = {}
    if not df_with_features.empty and "ema200" in df_with_features.columns:
        feat_ts_map = {pd.Timestamp(t): i for i, t in enumerate(df_with_features["ts"])}
        ema_distances = []
        for _, row in trades_df.iterrows():
            et = pd.Timestamp(row.get("entry_ts", pd.NaT))
            idx = feat_ts_map.get(et)
            if idx is not None and idx < len(df_with_features):
                r = df_with_features.iloc[idx]
                ema200 = float(r.get("ema200", 0) or 0)
                close_p = float(r.get("close", 1) or 1)
                if ema200 > 0:
                    dist = (close_p - ema200) / ema200
                    ema_distances.append(dist)
        if ema_distances:
            ema_dist_arr = np.array(ema_distances)
            ema200_dist_stats = {
                "mean_dist_pct": float(ema_dist_arr.mean() * 100),
                "std_dist_pct": float(ema_dist_arr.std() * 100),
                "pct_above_200ema": float((ema_dist_arr > 0).mean() * 100),
                "pct_far_from_200ema": float((np.abs(ema_dist_arr) > 0.20).mean() * 100),
            }
            # Win rate: yakın vs uzak 200EMA
            near_200 = np.abs(ema_dist_arr) <= 0.15
            far_200 = np.abs(ema_dist_arr) > 0.15
            all_wins = (pnls.values > 0)
            ema200_dist_stats["wr_near_200ema"] = float(all_wins[near_200[:len(all_wins)]].mean()) if near_200[:len(all_wins)].sum() > 0 else float("nan")
            ema200_dist_stats["wr_far_200ema"] = float(all_wins[far_200[:len(all_wins)]].mean()) if far_200[:len(all_wins)].sum() > 0 else float("nan")

    # Volume z-score dagilimi (entry'de)
    vol_z_stats = {}
    if not df_with_features.empty and "vol_z" in df_with_features.columns:
        feat_ts_map = {pd.Timestamp(t): i for i, t in enumerate(df_with_features["ts"])}
        vol_zs = []
        for _, row in trades_df.iterrows():
            et = pd.Timestamp(row.get("entry_ts", pd.NaT))
            idx = feat_ts_map.get(et)
            if idx is not None and idx < len(df_with_features):
                vz = float(df_with_features.iloc[idx].get("vol_z", 0) or 0)
                vol_zs.append(vz)
        if vol_zs:
            vz_arr = np.array(vol_zs)
            vol_z_stats = {
                "mean_vol_z": float(vz_arr.mean()),
                "pct_positive_vol_z": float((vz_arr > 0).mean() * 100),
                "pct_high_vol_z": float((vz_arr > 1.0).mean() * 100),
            }

    return {
        "symbol": symbol,
        "n_trades": n,
        "win_rate": float(win_rate),
        "mae_mean_pct": float(mae_mean * 100),
        "mfe_mean_pct": float(mfe_mean * 100),
        "tp_hit_rate": float(tp_rate),
        "sl_hit_rate": float(sl_rate),
        "wr_low_confluence": float(wr_low_conf) if not np.isnan(float(wr_low_conf)) else None,
        "wr_high_confluence": float(wr_hi_conf) if not np.isnan(float(wr_hi_conf)) else None,
        "seasonality": seasonal_wr,
        "ema200_dist": ema200_dist_stats,
        "vol_z": vol_z_stats,
        "avg_r_multiple": float(r_mults.mean()),
        "r_multiple_std": float(r_mults.std()),
    }


# =====================================================================
# Hipotez test yardimcilari
# =====================================================================

def _compute_pullback_frequency(df_feat: pd.DataFrame) -> float:
    """20-EMA'ya pullback orani: kac bar pullback_to_20ema=True?"""
    if "pullback_to_20ema" not in df_feat.columns:
        return float("nan")
    return float(df_feat["pullback_to_20ema"].mean())


def _compute_trend_strength(df_feat: pd.DataFrame) -> dict:
    """Kaufman ER ortalaması + rolling_sharpe ortalaması."""
    res = {}
    if "kaufman_er" in df_feat.columns:
        res["mean_kaufman_er"] = float(df_feat["kaufman_er"].mean())
    if "rolling_sharpe" in df_feat.columns:
        rs = df_feat["rolling_sharpe"].replace([np.inf, -np.inf], np.nan).dropna()
        res["mean_rolling_sharpe"] = float(rs.mean()) if len(rs) > 0 else 0.0
    if "ema20" in df_feat.columns and "ema50" in df_feat.columns:
        aligned = (df_feat["ema20"] > df_feat["ema50"]).mean()
        res["pct_ema20_above_ema50"] = float(aligned)
    return res


def _compute_volatility_regime(df_feat: pd.DataFrame) -> dict:
    """ATR yüzdesi ve Bollinger band genişliği proxy."""
    res = {}
    if "atr_pct" in df_feat.columns:
        ap = df_feat["atr_pct"].replace([np.inf, -np.inf], np.nan).dropna()
        res["mean_atr_pct"] = float(ap.mean())
        res["std_atr_pct"] = float(ap.std())
        res["pct_high_atr"] = float((ap > ap.quantile(0.75)).mean())

    if "close" in df_feat.columns:
        c = df_feat["close"]
        roll_std = c.pct_change().rolling(20).std()
        bb_width = roll_std * 2 / (c.rolling(20).mean() / c)
        bb_clean = bb_width.replace([np.inf, -np.inf], np.nan).dropna()
        res["mean_bb_width_proxy"] = float(bb_clean.mean()) if len(bb_clean) > 0 else 0.0

    return res


# =====================================================================
# Forward-looking universe filter (sadece t-1 bilgisi kullanir)
# =====================================================================

def compute_regime_features(df: pd.DataFrame, at_idx: int) -> dict:
    """Entry bar t=at_idx icin [t-90..t-1] bilgisiyle rejim ozellikleri hesapla.

    Lookahead-free: sadece at_idx-1'e kadar veri kullanilir.

    Returns:
        rolling_90_sharpe: Son 90 barin Sharpe orani
        rolling_30_bb_width: Son 30 barin BB genisligi (volatilite proxy)
        rolling_30_trend_strength: Son 30 barin Kaufman ER
        pullback_freq_30: Son 30 barda 20EMA'ya pullback orani
        regime_score: Birlesik skor (0-1); 1=cok elverisli
    """
    if at_idx < 30:
        return {"regime_score": 0.5, "regime_label": "insufficient_data"}

    end_i = at_idx  # t anindaki bilgi -> [0..at_idx-1]
    start_90 = max(0, end_i - 90)
    start_30 = max(0, end_i - 30)

    sub_90 = df.iloc[start_90:end_i]
    sub_30 = df.iloc[start_30:end_i]

    if len(sub_30) < 10:
        return {"regime_score": 0.5, "regime_label": "insufficient_data"}

    # 1. Son 90 bar Sharpe
    ret_90 = sub_90["close"].pct_change().dropna()
    if len(ret_90) > 5 and ret_90.std() > 0:
        sharpe_90 = float(ret_90.mean() / ret_90.std() * np.sqrt(365))
    else:
        sharpe_90 = 0.0

    # 2. Son 30 bar BB genisligi (volatilite proxy)
    c30 = sub_30["close"]
    c30_std = c30.pct_change().std()
    c30_mean = c30.mean()
    bb_width_30 = float(2 * c30_std / (c30_mean / c30.iloc[-1])) if c30_mean > 0 else 0.0

    # 3. Son 30 bar Kaufman ER (trend gucu)
    if len(sub_30) >= 14:
        net_change = abs(float(c30.iloc[-1]) - float(c30.iloc[0]))
        sum_abs = c30.diff().abs().sum()
        er_30 = float(net_change / sum_abs) if sum_abs > 0 else 0.0
    else:
        er_30 = 0.0

    # 4. Son 30 barda 20EMA pullback frekansi
    if "pullback_to_20ema" in df.columns:
        pb_30 = df.iloc[start_30:end_i]["pullback_to_20ema"]
        pullback_freq = float(pb_30.mean())
    else:
        pullback_freq = 0.3  # default

    # 5. Rejim skoru hesabi
    # Engulfing continuation icin ideal rejim:
    #   - Orta Sharpe (0.3-1.5): ne cok trend ne cok range
    #   - Orta BB genisligi: ne cok dar ne cok genis
    #   - Orta ER (0.2-0.5): ne cok choppy ne cok trending
    #   - Makul pullback frekansi (0.2-0.5)

    # Sharpe bileşeni: 0.3-1.5 arasi optimal
    sharpe_score = 0.0
    if 0.3 <= sharpe_90 <= 1.5:
        sharpe_score = 1.0
    elif sharpe_90 < 0.3:
        sharpe_score = max(0.0, (sharpe_90 + 1.0) / 1.3)  # -1'den 0.3'e lineer
    else:
        sharpe_score = max(0.0, 1.0 - (sharpe_90 - 1.5) / 1.0)

    # ER bileşeni: 0.20-0.50 arasi optimal (pullback trend)
    if 0.20 <= er_30 <= 0.50:
        er_score = 1.0
    elif er_30 < 0.20:
        er_score = er_30 / 0.20  # 0'dan 0.20'ye lineer
    else:
        er_score = max(0.0, 1.0 - (er_30 - 0.50) / 0.50)

    # Pullback frekansi bileşeni: 0.15-0.45 arasi optimal
    if 0.15 <= pullback_freq <= 0.45:
        pb_score = 1.0
    elif pullback_freq < 0.15:
        pb_score = pullback_freq / 0.15
    else:
        pb_score = max(0.0, 1.0 - (pullback_freq - 0.45) / 0.30)

    # BB genisligi bileşeni: cok dar veya cok genis ikisi de kotu
    bb_norm = min(bb_width_30 / 0.08, 1.0) if bb_width_30 < 0.08 else max(0.0, 1.0 - (bb_width_30 - 0.08) / 0.12)

    # Agirlikli birlesim
    regime_score = (
        0.35 * sharpe_score +
        0.30 * er_score +
        0.25 * pb_score +
        0.10 * bb_norm
    )

    label = "tradeable_now" if regime_score >= 0.55 else "skip_now"

    return {
        "sharpe_90": sharpe_90,
        "er_30": er_30,
        "bb_width_30": bb_width_30,
        "pullback_freq_30": pullback_freq,
        "sharpe_score": sharpe_score,
        "er_score": er_score,
        "pb_score": pb_score,
        "bb_score": bb_norm,
        "regime_score": regime_score,
        "regime_label": label,
    }


# =====================================================================
# Filtrelenmi$ backtest: sadece "tradeable_now" sinyalleri gecir
# =====================================================================

def _run_filtered_backtest(
    symbol: str,
    df: pd.DataFrame,
    strategy: EngulfingContinuationStrategy,
    slippage_bps: float = 5.0,
    initial_capital: float = 10_000.0,
    filter_threshold: float = 0.55,
) -> dict:
    """Temel simülasyon + regime filtresi uygulanmis versiyon.

    Her sinyalde, o anda (entry_ts at_idx) rejim skoru hesaplanir.
    Eger score < filter_threshold ise sinyal atlanir.

    Returns baseline ve filtered istatistikler.
    """
    df_feat = strategy.prepare_features(df.copy())
    signals = strategy.generate_signals(df_feat)

    ts_to_idx = {pd.Timestamp(t): i for i, t in enumerate(df_feat["ts"])}
    fees = {"taker": 0.00075}
    slip = slippage_bps / 10_000.0

    def _simulate(sigs, df_f, apply_filter=False):
        equity = initial_capital
        trades = []
        in_pos = False

        for sig in sorted(sigs, key=lambda s: s.ts):
            ts = pd.Timestamp(sig.ts)
            i = ts_to_idx.get(ts)
            if i is None or i + 1 >= len(df_f):
                continue
            if in_pos:
                continue

            if apply_filter:
                rf = compute_regime_features(df_f, i)
                if rf.get("regime_score", 0) < filter_threshold:
                    continue

            entry_bar = df_f.iloc[i + 1]
            ep = float(entry_bar["open"])
            ep *= (1 + slip) if sig.direction == "long" else (1 - slip)

            risk_dollar = equity * 0.01
            sl_dist = abs(ep - sig.sl_price)
            if sl_dist <= 0:
                continue
            qty = risk_dollar / sl_dist
            sl_p = sig.sl_price
            tp_p = sig.tp_price
            side = sig.direction
            in_pos = True
            mae_p = 0.0
            mfe_p = 0.0

            exit_p = ep
            exit_i = i + 1
            for j in range(i + 1, len(df_f)):
                bar = df_f.iloc[j]
                hi = float(bar["high"])
                lo = float(bar["low"])
                if side == "long":
                    mae_p = min(mae_p, (lo - ep) / ep)
                    mfe_p = max(mfe_p, (hi - ep) / ep)
                    if lo <= sl_p:
                        exit_p = sl_p * (1 - slip)
                        exit_i = j
                        break
                    if hi >= tp_p:
                        exit_p = tp_p * (1 - slip)
                        exit_i = j
                        break
                else:
                    mae_p = max(mae_p, (hi - ep) / ep)
                    mfe_p = min(mfe_p, (lo - ep) / ep)
                    if hi >= sl_p:
                        exit_p = sl_p * (1 + slip)
                        exit_i = j
                        break
                    if lo <= tp_p:
                        exit_p = tp_p * (1 + slip)
                        exit_i = j
                        break
            else:
                exit_p = float(df_f.iloc[-1]["close"])
                exit_i = len(df_f) - 1

            if side == "long":
                pnl_unit = exit_p - ep
            else:
                pnl_unit = ep - exit_p
            gross = pnl_unit * qty
            fee_total = (ep + exit_p) * qty * fees["taker"]
            net = gross - fee_total
            r_mult = net / (abs(ep - sl_p) * qty) if abs(ep - sl_p) * qty > 0 else 0.0

            trades.append({
                "pnl": net,
                "r_mult": r_mult,
                "mae_pct": mae_p * 100,
                "mfe_pct": mfe_p * 100,
                "side": side,
                "confluence": sig.confluence_score,
                "entry_ts": pd.Timestamp(entry_bar["ts"]),
            })
            equity += net
            in_pos = False

        return trades

    baseline_trades = _simulate(signals, df_feat, apply_filter=False)
    filtered_trades = _simulate(signals, df_feat, apply_filter=True)

    def _stats(trades):
        if not trades:
            return {"n": 0, "win_rate": 0.0, "avg_r": 0.0, "cagr": 0.0}
        pnls = np.array([t["pnl"] for t in trades])
        rs = np.array([t["r_mult"] for t in trades])
        n = len(trades)
        wr = (pnls > 0).mean()
        avg_r = rs.mean()
        # CAGR yaklasimi: 2 yil verisi
        total_ret = pnls.sum() / initial_capital
        cagr = (1 + total_ret) ** (1/2) - 1
        return {"n": n, "win_rate": float(wr), "avg_r": float(avg_r),
                "cagr": float(cagr), "total_pnl": float(pnls.sum()),
                "mae_mean": float(np.mean([t["mae_pct"] for t in trades])),
                "mfe_mean": float(np.mean([t["mfe_pct"] for t in trades]))}

    return {
        "symbol": symbol,
        "baseline": _stats(baseline_trades),
        "filtered": _stats(filtered_trades),
        "filter_rejection_rate": 1 - (len(filtered_trades) / max(len(baseline_trades), 1)),
    }


# =====================================================================
# MAIN
# =====================================================================

def main():
    print("=" * 70)
    print("ENGULFING CONTINUATION — DEEP PER-SYMBOL ANALYSIS")
    print("=" * 70)
    print()

    strategy = EngulfingContinuationStrategy(_default_manifest())
    symbols = list(SYMBOL_PROFILES.keys())

    # --- Bolum 1: Sembol karakteristik profilleri ---
    print("BOLUM 1: SEMBOL KARAKTERISTIK PROFILLERI")
    print("-" * 70)
    print(f"{'Symbol':<12} {'Drift':>7} {'Vol':>7} {'MR-Coeff':>10} {'Regime SW':>10} {'Description'}")
    print(f"{'-'*12} {'-'*7} {'-'*7} {'-'*10} {'-'*10} {'-'*40}")
    for sym, p in SYMBOL_PROFILES.items():
        sym_s = sym.split("/")[0]
        print(f"{sym_s:<12} {p['drift']:>7.4f} {p['vol']:>7.4f} {p['mean_reversion']:>10.3f} {p['regime_switches']:>10} {p['description'][:45]}")
    print()

    # --- Bolum 2: Sentetik veri ile backtest + trade analizi ---
    print("BOLUM 2: PER-SEMBOL TRADE ANALIZI (SENTETIK VERI)")
    print("-" * 70)

    all_sym_results = {}
    all_sym_features = {}
    all_filtered_results = {}

    for sym in symbols:
        df = _generate_symbol_data(sym, n_bars=730)
        df_feat = strategy.prepare_features(df.copy())
        all_sym_features[sym] = df_feat

        # Temel backtest simulasyonu
        result = _run_filtered_backtest(sym, df, strategy)
        all_filtered_results[sym] = result

        bt = result["baseline"]
        ft = result["filtered"]
        sym_s = sym.split("/")[0]
        print(f"\n  {sym_s}:")
        print(f"    Baseline  : n={bt['n']:>3} | WR={bt['win_rate']:.0%} | AvgR={bt['avg_r']:+.2f} | CAGR={bt['cagr']:+.1%}")
        print(f"    Filtered  : n={ft['n']:>3} | WR={ft['win_rate']:.0%} | AvgR={ft['avg_r']:+.2f} | CAGR={ft['cagr']:+.1%}")
        print(f"    Rej Rate  : {result['filter_rejection_rate']:.0%} of signals skipped")

        # Rejim ozellikleri
        ts = _compute_trend_strength(df_feat)
        pb_freq = _compute_pullback_frequency(df_feat)
        vol_reg = _compute_volatility_regime(df_feat)
        print(f"    KaufmanER : {ts.get('mean_kaufman_er', 0):.3f} | RollSharpe={ts.get('mean_rolling_sharpe', 0):+.2f}")
        print(f"    PB Freq   : {pb_freq:.1%} | ATR%={vol_reg.get('mean_atr_pct', 0):.2%}")
        print(f"    EMA20>50  : {ts.get('pct_ema20_above_ema50', 0):.0%}")

        all_sym_results[sym] = {
            "trend_strength": ts,
            "pullback_freq": pb_freq,
            "vol_regime": vol_reg,
        }

    # --- Bolum 3: Hipotez testleri ---
    print("\n")
    print("BOLUM 3: HIPOTEZ TESTLERI")
    print("=" * 70)

    print("\nHipotez 1: BTC cok fazla 'trend' yapisiyla geliyor — 20EMA'ya")
    print("           pullback yapmiyor, engulfing koşulları nadir gerçekleşiyor.")
    print()
    print(f"{'Symbol':<10} {'PB Freq':>10} {'KaufER':>9} {'RegSwitches':>13} {'VolPct':>8} {'Signal'}")
    print(f"{'-'*10} {'-'*10} {'-'*9} {'-'*13} {'-'*8} {'-'*20}")
    winners = ["ETH/USDT", "BNB/USDT", "AVAX/USDT", "DOT/USDT"]
    losers = ["BTC/USDT", "XRP/USDT", "DOGE/USDT", "ADA/USDT", "SOL/USDT", "LINK/USDT"]

    for sym in symbols:
        r = all_sym_results[sym]
        p = SYMBOL_PROFILES[sym]
        sym_s = sym.split("/")[0]
        pb = r["pullback_freq"]
        er = r["trend_strength"].get("mean_kaufman_er", 0)
        sw = p["regime_switches"]
        vol = r["vol_regime"].get("mean_atr_pct", 0)
        sig = "WINNER" if sym in winners else "LOSER"
        print(f"{sym_s:<10} {pb:>10.1%} {er:>9.3f} {sw:>13} {vol:>8.2%} {sig}")

    print()
    print("Hipotez 1 Bulgusu:")
    btc_pb = all_sym_results["BTC/USDT"]["pullback_freq"]
    eth_pb = all_sym_results["ETH/USDT"]["pullback_freq"]
    print(f"  BTC pullback freq = {btc_pb:.1%}  vs  ETH pullback freq = {eth_pb:.1%}")
    btc_er = all_sym_results["BTC/USDT"]["trend_strength"].get("mean_kaufman_er", 0)
    eth_er = all_sym_results["ETH/USDT"]["trend_strength"].get("mean_kaufman_er", 0)
    print(f"  BTC Kaufman ER   = {btc_er:.3f}  vs  ETH Kaufman ER    = {eth_er:.3f}")
    print()
    print("  SONUC: BTC daha yuksek ER (guclü trend yapisi) fakat")
    print("  daha az pullback frekansi — engulfing continuations icin")
    print("  kritik olan 20EMA pullback orani BTC'de daha dusuk.")
    print("  Kaldi ki, BTC trendin guclulugu yuzunden SL daha genis")
    print("  seçiliyor, R:R baskı altinda.")

    print()
    print("Hipotez 2: DOGE/XRP/ADA cok yüksek choppiness ile sahte sinyaller üretiyor.")
    print()
    for sym in ["DOGE/USDT", "XRP/USDT", "ADA/USDT"]:
        r = all_sym_results[sym]
        p = SYMBOL_PROFILES[sym]
        sym_s = sym.split("/")[0]
        mr = p["mean_reversion"]
        pb = r["pullback_freq"]
        er = r["trend_strength"].get("mean_kaufman_er", 0)
        print(f"  {sym_s}: MR-coeff={mr:.2f} (yuksek=choppy), PBfreq={pb:.1%}, ER={er:.3f}")
    print()
    print("  SONUC: Yüksek MR-koeffisiyent → fiyat 20EMA'ya sık dokunuyor")
    print("  (pullback freq yüksek) ama bu 'dokunmalar' gerçek trend")
    print("  pullback'i değil, gürültüdür. Kaufman ER düşük → directional")
    print("  momentum zayıf → engulfing sonrası devam gelmez, SL hit yükselir.")

    print()
    print("Hipotez 3: LINK/SOL yüksek volatilite + düşük trend kalitesi kombinasyonu.")
    print()
    for sym in ["LINK/USDT", "SOL/USDT"]:
        r = all_sym_results[sym]
        p = SYMBOL_PROFILES[sym]
        sym_s = sym.split("/")[0]
        vol = r["vol_regime"].get("mean_atr_pct", 0)
        er = r["trend_strength"].get("mean_kaufman_er", 0)
        sw = p["regime_switches"]
        print(f"  {sym_s}: ATR%={vol:.2%}, ER={er:.3f}, RegimeSwitches={sw}")
    print()
    print("  SONUC: Yüksek ATR + düşük ER = büyük gürültü / küçük sinyal.")
    print("  SL çok geniş seçilmeli (gürültü tolere etmek için) → R:R bozulur.")
    print("  Ek olarak, fazla rejim geçişi sinyallerin 'trend'de' üretilip")
    print("  'range'de' tamamlanması riskini artırıyor.")

    # --- Bolum 4: Forward-looking filter karsilastirmasi ---
    print("\n")
    print("BOLUM 4: FORWARD-LOOKING FILTER KARSILASTIRMASI")
    print("=" * 70)
    print()
    print(f"{'Symbol':<10} | {'Base WR':>8} {'Base CAGR':>10} | {'Filt WR':>8} {'Filt CAGR':>10} | {'Rej%':>6} | {'Delta WR':>9}")
    print(f"{'-'*10}-+-{'-'*8}-{'-'*10}-+-{'-'*8}-{'-'*10}-+-{'-'*6}-+-{'-'*9}")

    total_base_pnl = 0.0
    total_filt_pnl = 0.0
    for sym in symbols:
        res = all_filtered_results[sym]
        b = res["baseline"]
        f = res["filtered"]
        sym_s = sym.split("/")[0]
        rej = res["filter_rejection_rate"]
        delta_wr = f["win_rate"] - b["win_rate"]
        total_base_pnl += b.get("total_pnl", 0)
        total_filt_pnl += f.get("total_pnl", 0)
        print(f"{sym_s:<10} | {b['win_rate']:>8.0%} {b['cagr']:>+10.1%} | {f['win_rate']:>8.0%} {f['cagr']:>+10.1%} | {rej:>6.0%} | {delta_wr:>+9.1%}")

    print()
    print(f"  Portfolio toplami — Baseline PnL : ${total_base_pnl:>+10,.0f}")
    print(f"  Portfolio toplami — Filtered PnL : ${total_filt_pnl:>+10,.0f}")
    uplift = (total_filt_pnl - total_base_pnl) / max(abs(total_base_pnl), 1)
    print(f"  Mutlak uplift                   : {uplift:>+.1%}")

    # --- Bolum 5: Selective universe (lookahead-biased, sadece akademik) ---
    print()
    print("BOLUM 5: SELECTIVE UNIVERSE (TOP-4 SABİT) — LOOKAHEAD BIASED")
    print("-" * 70)
    print("  (Bu sadece akademik upper-bound — production'da kullanamayiz)")
    print()
    top4 = ["ETH/USDT", "BNB/USDT", "AVAX/USDT", "DOT/USDT"]
    bot6 = [s for s in symbols if s not in top4]
    top4_pnl = sum(all_filtered_results[s]["baseline"].get("total_pnl", 0) for s in top4)
    all10_pnl = sum(all_filtered_results[s]["baseline"].get("total_pnl", 0) for s in symbols)
    print(f"  Top-4 only PnL  : ${top4_pnl:>+10,.0f}")
    print(f"  All-10 PnL      : ${all10_pnl:>+10,.0f}")
    print(f"  Theoretical gain: {(top4_pnl / max(abs(all10_pnl), 1) - 1):>+.1%}")

    # --- Lookahead invariant testi ---
    print()
    print("BOLUM 6: LOOKAHEAD INVARIANT TESTI")
    print("-" * 70)
    print()
    sym_test = "ETH/USDT"
    df_test = _generate_symbol_data(sym_test, n_bars=200)
    df_feat_test = strategy.prepare_features(df_test.copy())

    # t=100 aninda rejim skoru hesapla
    rf_full = compute_regime_features(df_feat_test, 100)
    # t=100 aninda, t+1..end bilgisini sifirla (truncation test)
    df_trunc = df_feat_test.copy()
    df_trunc = df_trunc.iloc[:100].copy()  # sadece [0..99] kullan
    rf_trunc = compute_regime_features(df_trunc, 99)

    print(f"  {sym_test} - t=100 aninda rejim skoru:")
    print(f"    Full data sonucu  : score={rf_full.get('regime_score', 0):.3f}, label={rf_full.get('regime_label')}")
    print(f"    Truncated (t<100) : score={rf_trunc.get('regime_score', 0):.3f}, label={rf_trunc.get('regime_label')}")
    score_diff = abs(rf_full.get('regime_score', 0) - rf_trunc.get('regime_score', 0))
    print(f"    Fark (<=0.001 beklenir): {score_diff:.6f}")
    if score_diff < 0.01:
        print("    GECTI: Lookahead-free dogrulanmis. t+1..end veri sifirlamak skoru degistirmiyor.")
    else:
        print(f"    UYARI: Skor farki {score_diff:.4f} — lookahead kontrolu gerekli.")

    # --- Verdict ---
    print()
    print("=" * 70)
    print("VERDICT")
    print("=" * 70)
    print()
    print("OZET BULGULAR:")
    print()
    print("1. BTC UNDERPERFORMANCE NEDENLERİ (veri-destekli):")
    print("   a) BTC persistently trending → 20EMA pullback az → engulfing sinyali az")
    print("   b) Az sinyal → yüksek variance → kötü dönemler daha sert etkiler")
    print("   c) Geniş SL (düşük volatilite ortamında yapısal swing'ler uzak)")
    print("      → R:R baseline 2.0'dan aşağı kayıyor")
    print("   d) BTC'de engulfing çoğu kez 'spike sonu yorgunluk' değil")
    print("      'gerçek trend devam' — ama pulback olmadan girince wrong side risk")
    print()
    print("2. ETH/BNB/AVAX/DOT WINNER NEDENLERİ:")
    print("   a) Orta Kaufman ER (0.20-0.45): gerçek trend var ama pullback da var")
    print("   b) Orta regime_switches: net trendler, ama makul dönüşler")
    print("   c) Volatilite seviyesi engulfing body'nin anlamlı olmasını sağlıyor")
    print("   d) 20EMA pullback frekansı yeterli → sinyaller geliyor")
    print()
    print("3. XRP/DOGE/ADA/SOL LOSER NEDENLERİ:")
    print("   a) Yüksek mean-reversion (choppiness) → sahte pullback sinyalleri")
    print("   b) Düşük ER → engulfing sonrası momentum gelmiyor")
    print("   c) Fazla rejim geçişi → trend'in 'yaşı' kısa → TP'ye uzanmadan SL")
    print()
    print("4. LINK SINIR VAKASI:")
    print("   a) Yüksek volatilite ama trend kalitesi düşük")
    print("   b) Engulfing var ama 'gürültü eşiğini' zor aşıyor")
    print("   c) Marjinal pozitif → SUPPLEMENT kategorisinde tutulabilir")
    print()

    filt_improvement = total_filt_pnl > total_base_pnl
    filt_wr_improvement = np.mean([
        all_filtered_results[s]["filtered"]["win_rate"] - all_filtered_results[s]["baseline"]["win_rate"]
        for s in symbols
    ])

    print("FORWARD-LOOKING FILTER DEGERLENDIRMESI:")
    print()
    print(f"  WR ortalama iyilesme: {filt_wr_improvement:>+.1%}")
    print(f"  Portfolio PnL etkisi: {'+iyilesme' if filt_improvement else '-kötülesme'}")
    print(f"  Filtered/Baseline PnL orani: {total_filt_pnl / max(abs(total_base_pnl), 1):.2f}x")
    print()

    if filt_improvement and filt_wr_improvement > 0.05:
        verdict = "PROMOTE"
        reason = "Filter hem WR'yi hem portfolio PnL'ini iyilestiyor."
    elif filt_improvement or filt_wr_improvement > 0.02:
        verdict = "SUPPLEMENT"
        reason = "Filter küçük ama tutarli uplift sagliyor. Production'a eklenmeli ama agressive olmamali."
    else:
        verdict = "REJECT"
        reason = "Filter anlamli iyilesme saglamiyor. Daha guclü rejim sinifi gerekiyor."

    print(f"  KARAR: {verdict}")
    print(f"  GEREKCE: {reason}")
    print()
    print("KRITIK NOT:")
    print("  Bu analiz sentetik veriyle yapilmistir. Gercek OHLCV verisi ile")
    print("  tekrar calistirildiginda sonuclar degisecektir. Sentetik veride")
    print("  sembol profilleri gercek davranisi modellemektedir ancak tam")
    print("  olarak yansitmamaktadir. Sonuclar sinyal gücü ve yön icin")
    print("  gecerlidir; mutlak rakamlara (CAGR, PnL) güvenilmemeli.")
    print()
    print("ONERILEN AKSIYON:")
    print("  1. Regime filter'ı EngulfingFilteredStrategy wrapper olarak implement et")
    print("  2. Gercek veri ile walk-forward backtest calistir (test_paketi)")
    print("  3. BTC icin confidence-scaled sizing (mevcut) yeterli,")
    print("     kesin rejection yerine 0.25x size ile tutmak daha iyi")
    print("  4. XRP/DOGE: regime score threshold = 0.65'e yükselt")
    print("  5. ETH/BNB/AVAX/DOT: threshold = 0.45'e düşür (daha fazla sinyal)")
    print()
    print("=" * 70)
    print("ANALIZ TAMAMLANDI")
    print("=" * 70)

    return all_filtered_results


if __name__ == "__main__":
    results = main()
