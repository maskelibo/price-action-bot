"""v14 SERTLEŞTİRİLMİŞ yeniden-backtest — adversary + execution denetim cevabı.

Adversary KILL/MAJOR bulgularının her birine yapısal cevap:
  KILL-1  (compounding)   → fixed_notional_sizing=True (canlı v13/v14 wrapper
                            zaten başlangıç-equity sizing); aylık ROI = aylık
                            PnL$ / BAŞLANGIÇ sermayesi. Compound başlık YOK.
  KILL-2  (negatif havuz) → ÇÜRÜDÜ: replay'in gördüğü küme (sl>=0.025 &
                            conf>=0.25) meanR +0.88; adversary tüm havuzu ölçtü.
  KILL-3  (pyramid fill)  → leg ancak peak_R >= trig+0.15 ise sayılır (wick-fill
                            tamponu), leg boyutu x0.85 (fill olasılığı), leg
                            slippage 0.06R -> 0.20R.
  MAJOR-4 (reblend TP)    → reblend TAMAMEN KALDIRILDI. Havuz R'si engine'in
                            kendi 30/30/40 exit'i — v13/v14 wrapper'ın canlıda
                            birebir uyguladığı yapı (place_protection_orders
                            patch'i 30/30/40 + %1.5 trail). Sentez katmanı yok.
  MAJOR-5 (funding)       → +2bp (ölçülen: ort hold 15.6h ~2 funding penceresi,
                            notional 1bp/pencere) → toplam 57bps honest cost.
  MAJOR-7 (intra-ay DD)   → intra-month worst DD ayrıca raporlanır.
  MINOR-9 (multi-test)    → SADECE önceden seçilmiş 2 config koşulur (r0.62
                            d04/w08 ana + r0.55 d03/w06 yedek). Grid YOK,
                            yeniden seçim YOK.

Reproduce: ./.venv/bin/python scripts/research/hardened_rebacktest_v14.py
"""
from __future__ import annotations
import json, os, pickle, sys
from datetime import datetime, timezone
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")
import logging

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "research"))
logging.getLogger("price_action").setLevel(logging.ERROR)

from frontier_20pct_sweep import sl_pct_of, to_utc
from frontier_v2_pyr_expansion_regime import apply_filters, btc_daily_features
from price_action.backtest.lab import ProductionConfig, production_replay

POOL19 = ROOT / "data" / "pool_19sym_20260610.pkl"
YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_v14_frontier.yaml"
OUT = ROOT / "reports" / "research" / "2026-06-10_hardened_rebacktest_v14.json"
CLIP = datetime(2021, 5, 16, tzinfo=timezone.utc)
OOS_START = datetime(2024, 12, 1, tzinfo=timezone.utc)

HONEST_BPS = 57.0          # 55 taker+slip + 2 funding (ölçülen)
PYR_TRIG = (1.0, 1.5)
PYR_SIZE = (0.50, 0.30)
PYR_TRIG_BUFFER = 0.15     # wick-fill tamponu: değdi != doldu
PYR_FILL_PROB = 0.85       # leg fill olasılığı haircut'ı
PYR_SLIP_R = 0.20          # 0.06 -> 0.20 (market-fallback + spread gerçeği)
INITIAL = 10_000.0


def build_pool_hardened(pool, extra_bps):
    """Reblend YOK (engine-native 30/30/40 R). Pyramid: tamponlu/haircut'lı."""
    out = []
    for t in pool:
        t2 = dict(t)
        pk = t["peak_R"]
        slp = sl_pct_of(t)
        R = t["R"]  # native engine exit — sentez yok
        extra_R = (extra_bps / (slp * 10000.0)) if slp > 0 else 0.0
        radj = R
        for trig, sz in zip(PYR_TRIG, PYR_SIZE):
            if pk >= trig + PYR_TRIG_BUFFER:           # KILL-3a: tampon
                eff_sz = sz * PYR_FILL_PROB            # KILL-3b: fill olasılığı
                radj += eff_sz * max(0.0, R - trig)    # BE-protect katkısı
                radj -= PYR_SLIP_R * eff_sz            # KILL-3c: sert slippage
                radj -= extra_R * eff_sz               # leg fee
        radj -= extra_R
        t2["R"] = radj
        out.append(t2)
    return out


def monthly_fixed_base(entry_ts, equity, initial):
    """Non-compounding aylık ROI: (ay-sonu eq − önceki ay-sonu eq) / BAŞLANGIÇ."""
    if len(equity) == len(entry_ts) + 1:
        equity = equity[1:]
    month_last = {}
    for ts, eq in zip(entry_ts, equity):
        ts = to_utc(ts)
        month_last[(ts.year, ts.month)] = eq
    keys = sorted(month_last)
    rets, prev = [], initial
    for k in keys:
        rets.append((month_last[k] - prev) / initial * 100)
        prev = month_last[k]
    return keys, rets


def intra_month_worst_dd(entry_ts, equity):
    """Her ay içindeki en derin peak-to-trough DD (% — o anki equity'ye göre)."""
    if len(equity) == len(entry_ts) + 1:
        equity = equity[1:]
    worst = 0.0
    cur_month, peak = None, None
    for ts, eq in zip(entry_ts, equity):
        m = (to_utc(ts).year, to_utc(ts).month)
        if m != cur_month:
            cur_month, peak = m, eq
        peak = max(peak, eq)
        dd = (eq - peak) / peak * 100 if peak > 0 else 0.0
        worst = min(worst, dd)
    return worst


def run_one(label, sub, cfg):
    sub = sorted(sub, key=lambda x: to_utc(x["entry_ts"]))
    r = production_replay(sub, cfg)
    if r is None:
        print("  %s: replay bos" % label, flush=True)
        return None
    keys, rets = monthly_fixed_base(r.entry_ts_list, r.equity_curve, INITIAL)
    oos = [ret for k, ret in zip(keys, rets)
           if datetime(k[0], k[1], 1, tzinfo=timezone.utc) >= OOS_START]
    n = len(rets)
    res = {
        "n_trades": r.trades,
        "monthly_mean": sum(rets) / n,
        "monthly_median": sorted(rets)[n // 2],
        "neg_months": sum(1 for x in rets if x < 0),
        "n_months": n,
        "worst_month": min(rets),
        "best_month": max(rets),
        "continuous_dd": r.max_drawdown * 100,
        "intra_month_worst_dd": intra_month_worst_dd(r.entry_ts_list, r.equity_curve),
        "oos_mean": sum(oos) / len(oos) if oos else None,
        "oos_neg": sum(1 for x in oos if x < 0),
        "final_equity": r.final_equity,
        "total_pnl_pct_of_initial": (r.final_equity - INITIAL) / INITIAL * 100,
    }
    print(("  %-34s n=%5d  ay%%=%+6.2f med=%+6.2f  contDD=%+6.1f intraDD=%+6.1f  "
           "neg=%d/%d worst=%+6.2f  OOS=%+6.2f oneg=%d") % (
        label, res["n_trades"], res["monthly_mean"], res["monthly_median"],
        res["continuous_dd"], res["intra_month_worst_dd"], res["neg_months"],
        res["n_months"], res["worst_month"], res["oos_mean"], res["oos_neg"]), flush=True)
    return res


def main():
    with POOL19.open("rb") as f:
        raw = pickle.load(f)
    raw = [t for t in raw if to_utc(t["entry_ts"]) >= CLIP]
    feats = btc_daily_features()
    base = ProductionConfig.from_yaml(str(YAML))

    pool = build_pool_hardened(raw, HONEST_BPS)
    sub, dropped = apply_filters(pool, feats, use_f2=True, use_f4=True)
    print("[hardened] pool=%d  F2/F4 drop=%s  bps=%.0f  pyr(buf=%.2f,p=%.2f,slip=%.2f)"
          % (len(sub), dropped, HONEST_BPS, PYR_TRIG_BUFFER, PYR_FILL_PROB, PYR_SLIP_R),
          flush=True)

    results = {}
    configs = [
        ("ANA r0.62 d04/w08", dict(risk_pct=0.0062, daily_dd=0.04, weekly_dd=0.08)),
        ("YEDEK r0.55 d03/w06", dict(risk_pct=0.0055, daily_dd=0.03, weekly_dd=0.06)),
    ]
    print("\nNON-COMPOUNDING (sabit-notional, canlı sizing paritesi):", flush=True)
    for label, kw in configs:
        cfg = base.with_overrides(
            fee_bps_per_trade=0.0, pyramid_enabled=False,
            pyramid_triggers=(), pyramid_sizes=(),
            sl_pct_min=0.025, conf_min=0.25,
            fixed_notional_sizing=True, **kw,
        )
        results["fixed_" + label] = run_one(label, sub, cfg)

    print("\nREFERANS — compounding (eski metodoloji, kıyas için):", flush=True)
    for label, kw in configs:
        cfg = base.with_overrides(
            fee_bps_per_trade=0.0, pyramid_enabled=False,
            pyramid_triggers=(), pyramid_sizes=(),
            sl_pct_min=0.025, conf_min=0.25,
            fixed_notional_sizing=False, **kw,
        )
        sub_sorted = sorted(sub, key=lambda x: to_utc(x["entry_ts"]))
        r = production_replay(sub_sorted, cfg)
        if r is None:
            continue
        # compounding ay%: ay-üstü-ay oransal
        if len(r.equity_curve) == len(r.entry_ts_list) + 1:
            eqs = r.equity_curve[1:]
        else:
            eqs = r.equity_curve
        ml = {}
        for ts, eq in zip(r.entry_ts_list, eqs):
            ts = to_utc(ts)
            ml[(ts.year, ts.month)] = eq
        ks = sorted(ml)
        prev, crets = INITIAL, []
        for k in ks:
            crets.append((ml[k] / prev - 1) * 100)
            prev = ml[k]
        print("  %-34s ay%%=%+6.2f  contDD=%+6.1f" % (
            label, sum(crets) / len(crets), r.max_drawdown * 100), flush=True)
        results["comp_" + label] = {"monthly_mean": sum(crets) / len(crets),
                                    "continuous_dd": r.max_drawdown * 100}

    # ===== AY-BAĞIMSIZ taze-$10k replay (repo'nun yerleşik dürüst ROI metriği) =====
    # Non-compounding kurguda breaker'lar büyüyen equity ile etkisizleşiyor —
    # parite için her ay bağımsız $10k + sabit-notional + kendi breaker'ları.
    print("\nAY-BAĞIMSIZ taze-$10k replay (dürüst ROI başlığı):", flush=True)

    def per_month_independent(sub, cfg):
        sub = sorted(sub, key=lambda x: to_utc(x["entry_ts"]))
        start, end = to_utc(sub[0]["entry_ts"]), to_utc(sub[-1]["entry_ts"])
        cy, cm = start.year, start.month
        rets, keys = [], []
        while True:
            ms = datetime(cy, cm, 1, tzinfo=timezone.utc)
            me = datetime(cy + (cm == 12), (cm % 12) + 1, 1, tzinfo=timezone.utc)
            if ms > end:
                break
            m_tr = [t for t in sub if ms <= to_utc(t["entry_ts"]) < me]
            if len(m_tr) >= 10:
                r = production_replay(m_tr, cfg)
                if r is not None:
                    rets.append((r.final_equity - INITIAL) / INITIAL * 100)
                    keys.append((cy, cm))
            cm = (cm % 12) + 1
            if cm == 1:
                cy += 1
        return keys, rets

    for label, kw in configs:
        cfg = base.with_overrides(
            fee_bps_per_trade=0.0, pyramid_enabled=False,
            pyramid_triggers=(), pyramid_sizes=(),
            sl_pct_min=0.025, conf_min=0.25,
            fixed_notional_sizing=True, **kw,
        )
        keys, rets = per_month_independent(sub, cfg)
        n = len(rets)
        oos = [ret for k, ret in zip(keys, rets)
               if datetime(k[0], k[1], 1, tzinfo=timezone.utc) >= OOS_START]
        print("  %-34s ay%%=%+6.2f med=%+6.2f  neg=%d/%d worst=%+6.2f  OOS=%+6.2f oneg=%d" % (
            label, sum(rets) / n, sorted(rets)[n // 2],
            sum(1 for x in rets if x < 0), n, min(rets),
            sum(oos) / len(oos), sum(1 for x in oos if x < 0)), flush=True)
        results["permonth_" + label] = {
            "monthly_mean": sum(rets) / n, "neg_months": sum(1 for x in rets if x < 0),
            "n_months": n, "worst": min(rets), "oos_mean": sum(oos) / len(oos),
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "params": {"bps": HONEST_BPS, "pyr_buffer": PYR_TRIG_BUFFER,
                   "pyr_fill_prob": PYR_FILL_PROB, "pyr_slip_R": PYR_SLIP_R,
                   "reblend": "YOK (engine-native 30/30/40)"},
        "results": results,
    }, indent=2, default=str))
    print("\n[saved] %s" % OUT, flush=True)


if __name__ == "__main__":
    main()
