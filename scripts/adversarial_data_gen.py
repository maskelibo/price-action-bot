"""Synthetic adversarial OHLCV generator.

Faz 9 — Adversary Engineer red team toolkit.

Gerçek tarihsel crash periodları sınırlı sample (n=5). Tail behavior'i
zenginleştirmek için sentetik adversarial scenario'lar üretilir:

  - flash_crash: rastgele bara V-shaped drop (-%15 default), n bar içinde recovery
  - weekend_gap: hafta sonu sonrası open'da ±%5 gap
  - volume_spike: 3 bar boyunca 10x volume + range patlaması

CLI:
    .venv/bin/python scripts/adversarial_data_gen.py \\
        --symbol BTC/USDT --scenario flash_crash \\
        --output data/adversarial/flash_crash_btc.parquet

Test:
    pytest tests/test_adversary_engineer.py -k flash_crash_generator

Notes:
- Bu script DENEYSEL veri üretir. Pool'a injekt edilmeden önce Adversary
  Engineer evaluator'ı her synthetic scenario için ayrı verdict üretir.
- Input base_df YOKSA deterministik base series synthesize edilir
  (seed=42). Production'da gerçek pool subset verilmesi tercih.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Base series synthesizer (CLI standalone için)
# ---------------------------------------------------------------------------

def _synth_base(
    *,
    symbol: str = "BTC/USDT",
    timeframe: str = "5m",
    n: int = 500,
    start_price: float = 50000.0,
    seed: int = 42,
) -> pd.DataFrame:
    """Deterministik GBM-style OHLCV — base canvas for adversarial mutations."""
    rng = np.random.default_rng(seed)
    tf_minutes = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}.get(
        timeframe, 5
    )
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    ts = pd.date_range(
        start, periods=n, freq=f"{tf_minutes}min", tz="UTC"
    )
    rets = rng.normal(0.0, 0.005, size=n)
    close = start_price * np.exp(np.cumsum(rets))
    high = close * (1 + rng.uniform(0.0005, 0.005, size=n))
    low = close * (1 - rng.uniform(0.0005, 0.005, size=n))
    open_ = np.empty(n)
    open_[0] = close[0] * (1 + rng.uniform(-0.002, 0.002))
    open_[1:] = close[:-1] * (1 + rng.uniform(-0.002, 0.002, size=n - 1))
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    volume = rng.uniform(100, 1000, size=n)
    return pd.DataFrame(
        {
            "ts": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "venue": "synthetic",
            "symbol": symbol,
            "timeframe": timeframe,
            "scenario": "base",
        }
    )


# ---------------------------------------------------------------------------
# Scenario generators
# ---------------------------------------------------------------------------

def generate_flash_crash(
    base_df: pd.DataFrame,
    *,
    drop_pct: float = 0.15,
    recovery_bars: int = 20,
    crash_idx: int | None = None,
    seed: int = 7,
) -> pd.DataFrame:
    """Rastgele bara V-recovery flash crash enjekte et.

    Args:
        base_df: OHLCV pandas DF, ts ascending.
        drop_pct: kapanış düşüş yüzdesi (default 15%).
        recovery_bars: kaç bar içinde toparlasın (V-recovery).
        crash_idx: deterministik index; None ise random pick.
        seed: reproducibility.

    Returns:
        Yeni DataFrame (orijinali değiştirmez). `scenario` kolonu güncellenir.
    """
    if base_df.empty:
        return base_df.copy()
    rng = np.random.default_rng(seed)
    df = base_df.copy().reset_index(drop=True)
    n = len(df)
    if crash_idx is None:
        # Crash en az 50 bar baş, recovery_bars + 10 sonu için yer bırak
        lo, hi = max(50, 1), max(50, n - recovery_bars - 10)
        crash_idx = int(rng.integers(lo, max(lo + 1, hi)))
    crash_idx = max(1, min(crash_idx, n - 1))

    pre_close = float(df.loc[crash_idx - 1, "close"])
    crash_close = pre_close * (1 - drop_pct)

    # Crash bar: open near pre_close, plunge to crash_close
    df.loc[crash_idx, "open"] = pre_close * (1 - drop_pct * 0.1)
    df.loc[crash_idx, "high"] = pre_close * (1 + 0.001)
    df.loc[crash_idx, "low"] = crash_close * (1 - 0.01)  # wick aşağı
    df.loc[crash_idx, "close"] = crash_close
    df.loc[crash_idx, "volume"] = float(df.loc[crash_idx, "volume"]) * 5.0

    # V-recovery: recovery_bars boyunca lineer recovery
    end_idx = min(n - 1, crash_idx + recovery_bars)
    for i, j in enumerate(range(crash_idx + 1, end_idx + 1), start=1):
        frac = i / max(1, recovery_bars)
        target = crash_close + (pre_close - crash_close) * frac
        prev = float(df.loc[j - 1, "close"])
        df.loc[j, "open"] = prev
        df.loc[j, "close"] = target
        df.loc[j, "high"] = max(prev, target) * 1.002
        df.loc[j, "low"] = min(prev, target) * 0.998
        df.loc[j, "volume"] = float(df.loc[j, "volume"]) * (3.0 if i < 5 else 1.5)

    df.loc[crash_idx:end_idx, "scenario"] = (
        f"flash_crash_drop{int(drop_pct*100)}_rec{recovery_bars}"
    )
    return df


def generate_gap(
    base_df: pd.DataFrame,
    *,
    gap_pct: float = 0.05,
    when: str = "weekend_open",
    direction: str = "down",
    gap_idx: int | None = None,
    seed: int = 11,
) -> pd.DataFrame:
    """Open'da gap up/down (default: weekend open simülasyonu).

    Args:
        gap_pct: gap büyüklüğü (0.05 = %5).
        when: 'weekend_open' (Monday'i bul) ya da 'random'.
        direction: 'up' / 'down' / 'random'.
        gap_idx: manual override.
        seed: random pick için.
    """
    if base_df.empty:
        return base_df.copy()
    rng = np.random.default_rng(seed)
    df = base_df.copy().reset_index(drop=True)
    n = len(df)

    if gap_idx is None:
        if when == "weekend_open" and "ts" in df.columns:
            mondays = df.index[df["ts"].dt.dayofweek == 0].tolist()
            mondays = [m for m in mondays if m >= 10 and m < n - 5]
            if mondays:
                gap_idx = int(rng.choice(mondays))
            else:
                gap_idx = int(rng.integers(10, max(11, n - 5)))
        else:
            gap_idx = int(rng.integers(10, max(11, n - 5)))

    if direction == "random":
        direction = "up" if rng.random() > 0.5 else "down"
    sign = 1 if direction == "up" else -1

    prev_close = float(df.loc[gap_idx - 1, "close"])
    new_open = prev_close * (1 + sign * gap_pct)
    # Gap bar: open atlar, ama range bar normal width civarı
    cur_high = float(df.loc[gap_idx, "high"])
    cur_low = float(df.loc[gap_idx, "low"])
    cur_close = float(df.loc[gap_idx, "close"])

    width = max(1e-6, cur_high - cur_low)
    df.loc[gap_idx, "open"] = new_open
    df.loc[gap_idx, "high"] = new_open + width * 0.7
    df.loc[gap_idx, "low"] = new_open - width * 0.3
    df.loc[gap_idx, "close"] = new_open + (cur_close - (cur_high + cur_low) / 2)
    df.loc[gap_idx, "volume"] = float(df.loc[gap_idx, "volume"]) * 3.0
    df.loc[gap_idx, "scenario"] = (
        f"gap_{direction}_{int(gap_pct*100)}_{when}"
    )
    # Sanity
    df.loc[gap_idx, "high"] = max(
        float(df.loc[gap_idx, "high"]),
        float(df.loc[gap_idx, "open"]),
        float(df.loc[gap_idx, "close"]),
    )
    df.loc[gap_idx, "low"] = min(
        float(df.loc[gap_idx, "low"]),
        float(df.loc[gap_idx, "open"]),
        float(df.loc[gap_idx, "close"]),
    )
    return df


def generate_volume_spike(
    base_df: pd.DataFrame,
    *,
    vol_multiplier: float = 10.0,
    n_bars: int = 3,
    range_explosion_x: float = 3.0,
    spike_idx: int | None = None,
    seed: int = 23,
) -> pd.DataFrame:
    """n_bars boyunca vol_multiplier × volume + range patlaması.

    Args:
        vol_multiplier: volume çarpanı (10x).
        n_bars: kaç bar sürer (3 default).
        range_explosion_x: high-low range genişleme katsayısı (3x).
    """
    if base_df.empty:
        return base_df.copy()
    rng = np.random.default_rng(seed)
    df = base_df.copy().reset_index(drop=True)
    n = len(df)

    if spike_idx is None:
        lo, hi = max(20, 1), max(20, n - n_bars - 5)
        spike_idx = int(rng.integers(lo, max(lo + 1, hi)))
    spike_idx = max(1, min(spike_idx, n - n_bars - 1))

    for i in range(n_bars):
        j = spike_idx + i
        if j >= n:
            break
        cur_high = float(df.loc[j, "high"])
        cur_low = float(df.loc[j, "low"])
        mid = (cur_high + cur_low) / 2.0
        width = max(1e-6, cur_high - cur_low)
        new_width = width * range_explosion_x
        df.loc[j, "high"] = mid + new_width / 2
        df.loc[j, "low"] = mid - new_width / 2
        df.loc[j, "volume"] = float(df.loc[j, "volume"]) * vol_multiplier
        # Open/close range içinde tut
        cur_open = float(df.loc[j, "open"])
        cur_close = float(df.loc[j, "close"])
        df.loc[j, "open"] = min(
            max(cur_open, float(df.loc[j, "low"])),
            float(df.loc[j, "high"]),
        )
        df.loc[j, "close"] = min(
            max(cur_close, float(df.loc[j, "low"])),
            float(df.loc[j, "high"]),
        )
        df.loc[j, "scenario"] = (
            f"vol_spike_{int(vol_multiplier)}x_range{int(range_explosion_x)}x"
        )
    return df


SCENARIOS: dict[str, Any] = {
    "flash_crash": generate_flash_crash,
    "gap": generate_gap,
    "volume_spike": generate_volume_spike,
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generate synthetic adversarial OHLCV (Faz 9 red team).",
    )
    p.add_argument("--symbol", default="BTC/USDT")
    p.add_argument("--timeframe", default="5m")
    p.add_argument("--n", type=int, default=500, help="Base bar count")
    p.add_argument(
        "--scenario",
        required=True,
        choices=sorted(SCENARIOS.keys()),
        help="Hangi adversarial scenario uygulansın",
    )
    p.add_argument("--output", type=Path, required=True, help="Parquet output path")
    p.add_argument("--seed", type=int, default=42)
    # Scenario overrides
    p.add_argument("--drop-pct", type=float, default=0.15)
    p.add_argument("--recovery-bars", type=int, default=20)
    p.add_argument("--gap-pct", type=float, default=0.05)
    p.add_argument(
        "--gap-when", default="weekend_open", choices=["weekend_open", "random"]
    )
    p.add_argument(
        "--gap-direction", default="down", choices=["up", "down", "random"]
    )
    p.add_argument("--vol-multiplier", type=float, default=10.0)
    p.add_argument("--n-bars", type=int, default=3)
    p.add_argument("--range-explosion-x", type=float, default=3.0)
    p.add_argument(
        "--print-summary", action="store_true",
        help="Stdout'a kısa özet bas",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    base = _synth_base(
        symbol=args.symbol,
        timeframe=args.timeframe,
        n=args.n,
        seed=args.seed,
    )
    if args.scenario == "flash_crash":
        out = generate_flash_crash(
            base,
            drop_pct=args.drop_pct,
            recovery_bars=args.recovery_bars,
            seed=args.seed,
        )
    elif args.scenario == "gap":
        out = generate_gap(
            base,
            gap_pct=args.gap_pct,
            when=args.gap_when,
            direction=args.gap_direction,
            seed=args.seed,
        )
    elif args.scenario == "volume_spike":
        out = generate_volume_spike(
            base,
            vol_multiplier=args.vol_multiplier,
            n_bars=args.n_bars,
            range_explosion_x=args.range_explosion_x,
            seed=args.seed,
        )
    else:
        print(f"ERROR: unknown scenario {args.scenario}", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.output, index=False)

    if args.print_summary:
        scen_rows = out[out["scenario"] != "base"]
        print(
            f"scenario={args.scenario} symbol={args.symbol} tf={args.timeframe} "
            f"n_bars={len(out)} mutated={len(scen_rows)} "
            f"out={args.output}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
