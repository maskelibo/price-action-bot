"""Trail-PCT Champion-Challenger — 15m WIDESTOP VSA2 trail sıkılaştırma.

HIPOTEZ (2026-05-31):
  Mevcut daemon: _TRAIL_PCT=0.10, trail TP2(1.5R) sonrası başlıyor.
  Sorun: pozisyonlar kâra geçip geri zarara dönüyor (XLM vakası).
  Test: trail_pct grid (0.03/0.04/0.05) + trail_activate_stage=1 (TP1'den başla)
  vs CHAMPION (trail_pct=0.10, stage=2).

DÜRÜSTLÜK NOTU:
  Mevcut pool (sec53_15m_pool_v11.pkl) ATR-bazlı trail ile üretildi.
  Trail mekanizması değiştiği için POOL-REBLEND YETERSİZ.
  Full OHLCV re-sim: 15m OHLCV, pool'daki 4 strateji, 10 sembol, 2021-2026.

METRIKLER:
  mean_R_after_fees, MaxDD, monthly_mean_ROI, win%, ortalama holding bars.
  55bps baseline + 100bps stress, hem stage=1 hem stage=2 (CURRENT champion).

CHAMPION (current daemon davranışı):
  trail_pct=0.10, trail_activate_stage=2 (TP2 sonrası)
  NOT: engine'deki ATR trail ile parity için burada pct-bazlı simüle ediyoruz.

CHALLENGER grid:
  trail_pct ∈ {0.03, 0.04, 0.05}  x  trail_activate_stage=1 (TP1'den trail)

GATE:
  monthly_ROI >= champion ROI  AND  MaxDD <= champion DD -> SAFE (koy)
  yoksa: tradeoff sayısal raporla.

Çalıştır: .venv/bin/python scripts/trail_pct_champion_challenger.py
"""
from __future__ import annotations

import os
import pickle
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")
import logging
logging.getLogger("price_action").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.engine import BacktestEngine  # noqa: E402
from price_action.backtest.lab import ProductionConfig, production_replay  # noqa: E402
from scripts.run_real_backtest import _load_symbol_ohlcv  # noqa: E402

# ----- Sabitler -----
CHAMPION_YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_widestop_vsa2.yaml"
CACHE_DIR = ROOT / "data" / "_trail_pct_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Pool'daki 10 sembol (OHLCV 15m 2021-2026 mevcut)
SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
    "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
    "DOGE/USDT", "XRP/USDT",
]

# Pool'daki 4 strateji
STRATEGIES = [
    ("brooks_failed_breakout", "BrooksFailedBreakoutStrategy"),
    ("anchored_vwap_reversal", "AnchoredVWAPReversalStrategy"),
    ("vsa_climax_test", "VSAClimaxTestStrategy"),
    ("engulfing_continuation", "EngulfingContinuationStrategy"),
]

# Champion: %10 trail, stage=2 (TP2 sonrası)
CHAMPION_PCT = 0.10
CHAMPION_STAGE = 2

# Challenger grid: %3/4/5, stage=1 (TP1 sonrası)
CHALLENGER_PCTS = [0.03, 0.04, 0.05]
CHALLENGER_STAGE = 1

# Maliyet
TAKER_FEE = 0.00075   # %7.5bps
SLIP_BPS = 5.0
EXTRA_BPS_BASELINE = 55.0
EXTRA_BPS_STRESS = 100.0

TP1_R = 1.0
TP2_R = 1.5
TP1_CLOSE_PCT = 0.25   # live champion 25/25/50
TP2_CLOSE_PCT = 0.25


def load_strategy(module_name: str, class_name: str):
    """Strateji objesini yükle."""
    mod = __import__(
        f"price_action.strategies.{module_name}",
        fromlist=[class_name, "_default_manifest"],
    )
    cls = getattr(mod, class_name)
    manifest_fn = getattr(mod, "_default_manifest", None)
    if manifest_fn is None:
        return None
    return cls(manifest_fn())


def gather_trades(trail_pct: float, trail_stage: int) -> list[dict]:
    """Bir (trail_pct, trail_stage) hücresi için tüm trade'leri topla.

    Cache varsa diskten yükle; yoksa OHLCV'den full re-sim.
    """
    cache_key = f"pct{trail_pct:.3f}_stage{trail_stage}"
    cache_path = CACHE_DIR / f"trades_{cache_key}.pkl"

    if cache_path.exists():
        with cache_path.open("rb") as f:
            trades = pickle.load(f)
        print(f"  [cache] {cache_key}: n={len(trades)}")
        return trades

    print(f"  [sim]   {cache_key}: full OHLCV re-sim başlıyor...")
    t0 = time.time()
    all_trades: list[dict] = []

    for mod_name, cls_name in STRATEGIES:
        try:
            strategy = load_strategy(mod_name, cls_name)
        except Exception as e:
            print(f"    [skip] {mod_name}: {e}")
            continue
        if strategy is None:
            continue

        for sym in SYMBOLS:
            try:
                df = _load_symbol_ohlcv(sym, tf="15m")
                if df is None or df.empty:
                    continue
                df = df.sort_values("ts").reset_index(drop=True)
                df_feat = strategy.prepare_features(df)

                def _provider(s, tf, start, end, _df=df_feat):
                    return _df.copy()

                engine = BacktestEngine(
                    risk_officer=None,
                    store_load=None,
                    runner_trail_pct=trail_pct,
                    trail_activate_stage=trail_stage,
                    tp1_R=TP1_R,
                    tp2_R=TP2_R,
                    tp1_close_pct=TP1_CLOSE_PCT,
                    tp2_close_pct=TP2_CLOSE_PCT,
                    runner_force_exit_method="time",
                    runner_force_exit_bars=48,   # 15m x 48 = 12 saat
                )
                result = engine.run(
                    strategy,
                    [sym],
                    start=df["ts"].iloc[0].to_pydatetime(),
                    end=df["ts"].iloc[-1].to_pydatetime(),
                    timeframe="15m",
                    fees={"taker": TAKER_FEE, "maker": -0.000025},
                    slippage_bps=SLIP_BPS,
                    initial_capital=10_000.0,
                    ohlcv_provider=_provider,
                )

                if result.trades.empty:
                    continue

                for _, row in result.trades.iterrows():
                    entry_p = float(row.get("entry_price", 0))
                    initial_sl = float(row.get("initial_sl", 0))
                    sl_pct = abs(entry_p - initial_sl) / entry_p if entry_p > 0 else 0.025
                    conf_val = float(row.get("confluence_score", 0.0)) if "confluence_score" in row.index else 0.0
                    all_trades.append({
                        "entry_ts": row.get("entry_ts"),
                        "exit_ts": row.get("exit_ts"),
                        "entry_price": entry_p,
                        "initial_sl": initial_sl,
                        "R": float(row.get("realized_r_multiple", 0)),
                        "peak_R": float(row.get("peak_r_multiple", 0)) if "peak_r_multiple" in row.index else 0.0,
                        "symbol": sym,
                        "side": str(row.get("side", "long")),
                        "strategy": mod_name,
                        "sl_pct": sl_pct,
                        "conf": conf_val,   # production_replay icin zorunlu
                        "vol_z": 0.0,
                        "holding_bars": float(row.get("holding_bars", 0)) if "holding_bars" in row.index else 0.0,
                    })
            except Exception as e:
                print(f"    [fail] {mod_name}/{sym}: {e}")
                continue

    all_trades.sort(key=lambda x: x["entry_ts"] if x["entry_ts"] is not None else datetime.min)
    with cache_path.open("wb") as f:
        pickle.dump(all_trades, f)

    elapsed = time.time() - t0
    print(f"    -> n={len(all_trades)} ({elapsed:.0f}s) (cached)")
    return all_trades


def to_utc(ts):
    if ts is None:
        return datetime(2000, 1, 1, tzinfo=timezone.utc)
    if hasattr(ts, "tzinfo") and ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    if hasattr(ts, "to_pydatetime"):
        ts = ts.to_pydatetime()
    if hasattr(ts, "tzinfo") and ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def fee_adjusted_r(trades: list[dict], extra_bps: float) -> list[dict]:
    """R'ye fee cost ekle (R-space, konservatif).
    conf alanı yoksa 0.0 ekle — production_replay için zorunlu.
    """
    out = []
    for t in trades:
        sl_pct = t.get("sl_pct", 0.025)
        if sl_pct <= 0:
            ep = t.get("entry_price", 0)
            isl = t.get("initial_sl", 0)
            sl_pct = abs(ep - isl) / ep if ep > 0 else 0.025
        extra_r = (extra_bps / (sl_pct * 10_000.0)) if sl_pct > 0 else 0.0
        t2 = dict(t)
        t2["R"] = t["R"] - extra_r
        # production_replay zorunlu alanlar
        if "conf" not in t2:
            t2["conf"] = 0.0
        if "vol_z" not in t2:
            t2["vol_z"] = 0.0
        out.append(t2)
    return out


def monthly_metrics(trades: list[dict], cfg: ProductionConfig) -> dict | None:
    """Aylık ROI dağılımı + sürekli metrikler."""
    trades = sorted(trades, key=lambda x: to_utc(x["entry_ts"]))
    if len(trades) < 30:
        return None

    start = to_utc(trades[0]["entry_ts"])
    end = to_utc(trades[-1]["entry_ts"])

    # Aylık pencereler
    months = []
    cy, cm = start.year, start.month
    while True:
        ms = datetime(cy, cm, 1, tzinfo=timezone.utc)
        if ms > end:
            break
        me = datetime(cy + (cm == 12), (cm % 12) + 1, 1, tzinfo=timezone.utc)
        months.append((ms, me))
        cm = (cm % 12) + 1
        cy += (cm == 1)

    rets = []
    equity = cfg.initial_capital
    for ms, me in months:
        m_tr = [t for t in trades if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_tr) < 5:
            continue
        r = production_replay(m_tr, cfg.with_overrides(initial_capital=equity))
        if r is None:
            continue
        rets.append(r.total_return * 100)
        equity = r.final_equity if r.final_equity > 0 else equity

    if not rets:
        return None

    # Sürekli metrikler (tüm dönem)
    r_full = production_replay(trades, cfg)
    if r_full is None:
        return None

    win_r = [t["R"] for t in trades]
    winners = [r for r in win_r if r > 0]
    losers = [r for r in win_r if r <= 0]
    mean_r = mean(win_r) if win_r else 0.0
    win_pct = len(winners) / len(win_r) * 100 if win_r else 0.0
    avg_win = mean(winners) if winners else 0.0
    avg_loss = mean(losers) if losers else 0.0

    holding = [t.get("holding_bars", 0) for t in trades if t.get("holding_bars", 0) > 0]
    avg_hold = mean(holding) if holding else 0.0

    return {
        "n": len(trades),
        "n_months": len(rets),
        "monthly_mean_roi": mean(rets),
        "monthly_min_roi": min(rets),
        "monthly_neg": sum(1 for x in rets if x < 0),
        "max_dd": r_full.max_drawdown * 100,
        "total_return": r_full.total_return * 100,
        "mean_r": mean_r,
        "win_pct": win_pct,
        "avg_win_r": avg_win,
        "avg_loss_r": avg_loss,
        "avg_hold_bars": avg_hold,
    }


def run_cell(label: str, trades: list[dict], cfg: ProductionConfig, extra_bps: float) -> dict | None:
    """Bir hücre için hem 55bps hem 100bps metrikler."""
    adj = fee_adjusted_r(trades, extra_bps)
    m = monthly_metrics(adj, cfg)
    if m is None:
        return None
    m["label"] = label
    m["extra_bps"] = extra_bps
    return m


def print_row(m: dict, baseline: dict | None = None):
    tag = ""
    if baseline and m["label"] == baseline["label"]:
        tag = " <-- CHAMPION"
    elif baseline:
        roi_diff = m["monthly_mean_roi"] - baseline["monthly_mean_roi"]
        dd_diff = m["max_dd"] - baseline["max_dd"]   # negatif = daha iyi
        if roi_diff >= 0 and dd_diff <= 0:
            tag = " [SAFE]"
        elif roi_diff >= 0 and dd_diff <= 2.0:
            tag = " [ACCEPTABLE]"
        else:
            tag = " [TRADEOFF]"
    print(
        f"  {m['label']:<25} bps={m['extra_bps']:>3.0f} "
        f"n={m['n']:>6} "
        f"mon_roi={m['monthly_mean_roi']:>+6.2f}% "
        f"mon_min={m['monthly_min_roi']:>+6.1f}% "
        f"neg_mo={m['monthly_neg']:>2} "
        f"MaxDD={m['max_dd']:>+5.1f}% "
        f"total={m['total_return']:>+6.1f}% "
        f"meanR={m['mean_r']:>+5.3f} "
        f"win={m['win_pct']:>4.1f}% "
        f"hold={m['avg_hold_bars']:>4.0f}b"
        f"{tag}"
    )


def main():
    print("=" * 140)
    print("TRAIL-PCT CHAMPION-CHALLENGER — 15m WIDESTOP VSA2")
    print(f"Champion: trail_pct={CHAMPION_PCT:.2f} stage={CHAMPION_STAGE}")
    print(f"Challengers: pct={CHALLENGER_PCTS} stage={CHALLENGER_STAGE}")
    print(f"Semboller: {len(SYMBOLS)} | Stratejiler: {len(STRATEGIES)}")
    print(f"Fee: taker={TAKER_FEE*10000:.1f}bps slip={SLIP_BPS}bps + extra 55/100bps")
    print("=" * 140)

    # ProductionConfig (champion yaml'dan)
    base_cfg = ProductionConfig.from_yaml(str(CHAMPION_YAML)).with_overrides(
        pyramid_enabled=False,
        pyramid_triggers=(),
        pyramid_sizes=(),
        fee_bps_per_trade=0.0,
        sl_pct_min=0.0,
        conf_min=0.0,  # engine confluence_score mevcut strateji formatiyla 0.0 baseline
    )
    print(f"\n[config] risk_pct={base_cfg.risk_pct} initial_capital={base_cfg.initial_capital}")

    # --- Phase 1: Trade toplama ---
    print("\n[Phase 1] Trade pool toplama (cache yoksa full OHLCV re-sim)...")
    cells = []

    # Champion
    champ_trades = gather_trades(CHAMPION_PCT, CHAMPION_STAGE)
    cells.append((f"champion_pct{CHAMPION_PCT:.2f}_s{CHAMPION_STAGE}", champ_trades))

    # Challengers
    for pct in CHALLENGER_PCTS:
        trades = gather_trades(pct, CHALLENGER_STAGE)
        cells.append((f"chall_pct{pct:.2f}_s{CHALLENGER_STAGE}", trades))

    # --- Phase 2: Metrikler ---
    print("\n[Phase 2] Metrikleri hesaplıyor...")
    all_results = []
    champion_result = None

    for cost_label, extra_bps in [("55bps", EXTRA_BPS_BASELINE), ("100bps", EXTRA_BPS_STRESS)]:
        print(f"\n  --- Maliyet: {cost_label} ---")
        print(f"  {'Label':<25} {'bps':>4} {'n':>7} {'mon_roi':>8} {'mon_min':>8} "
              f"{'neg_mo':>6} {'MaxDD':>7} {'total':>7} {'meanR':>7} {'win%':>6} {'hold':>5}")
        print("  " + "-" * 130)

        for label, trades in cells:
            m = run_cell(label, trades, base_cfg, extra_bps)
            if m is None:
                print(f"  {label:<25} INSUFFICIENT DATA")
                continue

            key = (label, cost_label)
            all_results.append({**m, "cost_label": cost_label})

            # Champion referansı (55bps)
            if "champion" in label and extra_bps == EXTRA_BPS_BASELINE:
                champion_result = m

            print_row(m, baseline=(champion_result if "champion" not in label else None))

    # --- Phase 3: Özet karar ---
    print("\n" + "=" * 140)
    print("ÖZET KARAR (55bps baseline)")
    print("=" * 140)

    if champion_result is None:
        print("HATA: Champion metrikleri hesaplanamadı.")
        return

    print(f"\nCHAMPION (trail_pct={CHAMPION_PCT:.2f}, stage={CHAMPION_STAGE}):")
    print(f"  monthly_ROI={champion_result['monthly_mean_roi']:+.2f}%  "
          f"MaxDD={champion_result['max_dd']:+.1f}%  "
          f"meanR={champion_result['mean_r']:+.3f}  "
          f"win={champion_result['win_pct']:.1f}%  "
          f"hold={champion_result['avg_hold_bars']:.0f}bars")

    print("\nCHALLENGERS vs CHAMPION (55bps):")
    for m in all_results:
        if "champion" not in m["label"] and m["cost_label"] == "55bps":
            roi_diff = m["monthly_mean_roi"] - champion_result["monthly_mean_roi"]
            dd_diff = m["max_dd"] - champion_result["max_dd"]
            r_diff = m["mean_r"] - champion_result["mean_r"]
            win_diff = m["win_pct"] - champion_result["win_pct"]

            verdict = "SAFE" if roi_diff >= 0 and dd_diff <= 0 else (
                "ACCEPTABLE" if roi_diff >= -0.5 and dd_diff <= 2.0 else "RISKY"
            )
            print(f"\n  {m['label']}: [{verdict}]")
            print(f"    monthly_ROI: {m['monthly_mean_roi']:+.2f}% ({roi_diff:+.2f}pp vs champion)")
            print(f"    MaxDD: {m['max_dd']:+.1f}% ({dd_diff:+.1f}pp vs champion, neg=kötü)")
            print(f"    meanR: {m['mean_r']:+.3f} ({r_diff:+.3f} vs champion)")
            print(f"    win%: {m['win_pct']:.1f}% ({win_diff:+.1f}pp vs champion)")
            print(f"    hold: {m['avg_hold_bars']:.0f}bars "
                  f"(champion: {champion_result['avg_hold_bars']:.0f}bars)")

    # Best challenger
    challengers_55 = [m for m in all_results if "champion" not in m["label"] and m["cost_label"] == "55bps"]
    if challengers_55:
        best = max(challengers_55, key=lambda x: x["monthly_mean_roi"])
        print(f"\n>> EN IYI CHALLENGER (55bps ROI): {best['label']}")
        print(f"   monthly_ROI={best['monthly_mean_roi']:+.2f}%  MaxDD={best['max_dd']:+.1f}%  "
              f"meanR={best['mean_r']:+.3f}")

    print("\n[Done]")


if __name__ == "__main__":
    main()
