"""OHLCV quality checks — gap, duplicate, OHLC sanity, volume z-score, stale.

Çıktı:
    QualityReport (dataclass)
    JSON: data/quality/YYYY-MM-DD.json (snapshot)
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from price_action.logging_config import logger
from price_action.settings import ROOT_DIR

# timeframe → pandas frequency
_TF_FREQ: dict[str, str] = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1D",
    "1w": "1W-MON",  # haftalık (Pazartesi başlangıçlı; Binance UTC için makul yaklaşım)
}

_TF_TIMEDELTA: dict[str, pd.Timedelta] = {
    "1m": pd.Timedelta(minutes=1),
    "5m": pd.Timedelta(minutes=5),
    "15m": pd.Timedelta(minutes=15),
    "1h": pd.Timedelta(hours=1),
    "4h": pd.Timedelta(hours=4),
    "1d": pd.Timedelta(days=1),
    "1w": pd.Timedelta(days=7),
}


@dataclass
class QualityReport:
    """OHLCV serisi için kalite raporu."""

    venue: str
    symbol: str
    timeframe: str
    rows: int
    start: str | None
    end: str | None
    gaps: int = 0
    gap_examples: list[str] = field(default_factory=list)
    duplicates: int = 0
    ohlc_violations: int = 0
    volume_outliers: int = 0
    price_jumps: int = 0
    stale: bool = False
    last_bar_age_seconds: float | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _expected_bars(start: pd.Timestamp, end: pd.Timestamp, tf: str) -> int:
    """Beklenen bar sayısı (start..end dahil)."""
    if tf not in _TF_TIMEDELTA:
        return 0
    delta = _TF_TIMEDELTA[tf]
    if delta.total_seconds() == 0:
        return 0
    return int((end - start) / delta) + 1


def detect_gaps(df: pd.DataFrame, tf: str) -> tuple[int, list[str]]:
    """Bar zincirinde eksikleri say. Örnek timestamp listesi (max 5)."""
    if df.empty or tf not in _TF_FREQ:
        return 0, []
    ts = pd.to_datetime(df["ts"], utc=True).sort_values()
    if len(ts) < 2:
        return 0, []
    full_range = pd.date_range(ts.iloc[0], ts.iloc[-1], freq=_TF_FREQ[tf], tz="UTC")
    missing = full_range.difference(ts)
    examples = [str(x) for x in missing[:5]]
    return int(len(missing)), examples


def detect_duplicates(df: pd.DataFrame) -> int:
    if df.empty or "ts" not in df.columns:
        return 0
    keys = ["ts"]
    for col in ("venue", "symbol", "timeframe"):
        if col in df.columns:
            keys.append(col)
    return int(df.duplicated(subset=keys, keep=False).sum())


def detect_ohlc_violations(df: pd.DataFrame) -> int:
    """high >= max(o,c) >= min(o,c) >= low; bunlardan birini ihlal eden sayısı."""
    if df.empty:
        return 0
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    upper = np.maximum(o, c)
    lower = np.minimum(o, c)
    bad = (h < upper) | (lower < l) | (h < l)
    return int(bad.sum())


def detect_volume_outliers(df: pd.DataFrame, z_threshold: float = 8.0) -> int:
    """Volume z-score > threshold sayısı."""
    if df.empty or "volume" not in df.columns or len(df) < 10:
        return 0
    v = pd.to_numeric(df["volume"], errors="coerce").astype(float)
    mean = v.mean()
    std = v.std(ddof=0)
    if not std or np.isnan(std):
        return 0
    z = (v - mean) / std
    return int((z.abs() > z_threshold).sum())


def detect_price_jumps(df: pd.DataFrame, max_pct: float = 0.30) -> int:
    if df.empty or len(df) < 2:
        return 0
    c = pd.to_numeric(df["close"], errors="coerce").astype(float)
    pct = c.pct_change().abs()
    return int((pct > max_pct).sum())


def detect_stale(df: pd.DataFrame, tf: str, *, now: datetime | None = None) -> tuple[bool, float | None]:
    """Son bar > 2 * timeframe önceyse stale=True."""
    if df.empty or tf not in _TF_TIMEDELTA:
        return False, None
    last_ts = pd.to_datetime(df["ts"], utc=True).max()
    now_dt = pd.Timestamp(now if now is not None else datetime.now(timezone.utc)).tz_convert("UTC")
    age = (now_dt - last_ts).total_seconds()
    return age > 2 * _TF_TIMEDELTA[tf].total_seconds(), float(age)


def run_quality_checks(
    df: pd.DataFrame,
    *,
    venue: str,
    symbol: str,
    timeframe: str,
    z_threshold: float = 8.0,
    price_jump_pct: float = 0.30,
    now: datetime | None = None,
) -> QualityReport:
    """Bir OHLCV serisine tüm checks'i çalıştır."""
    rep = QualityReport(
        venue=venue,
        symbol=symbol,
        timeframe=timeframe,
        rows=len(df),
        start=str(df["ts"].min()) if not df.empty and "ts" in df.columns else None,
        end=str(df["ts"].max()) if not df.empty and "ts" in df.columns else None,
    )
    if df.empty:
        rep.notes.append("empty_dataframe")
        return rep

    gaps, examples = detect_gaps(df, timeframe)
    rep.gaps = gaps
    rep.gap_examples = examples
    rep.duplicates = detect_duplicates(df)
    rep.ohlc_violations = detect_ohlc_violations(df)
    rep.volume_outliers = detect_volume_outliers(df, z_threshold=z_threshold)
    rep.price_jumps = detect_price_jumps(df, max_pct=price_jump_pct)
    stale, age = detect_stale(df, timeframe, now=now)
    rep.stale = stale
    rep.last_bar_age_seconds = age

    if rep.ohlc_violations:
        logger.bind(symbol=symbol, tf=timeframe, n=rep.ohlc_violations).warning(
            "quality.ohlc_violation"
        )
    if rep.duplicates:
        logger.bind(symbol=symbol, tf=timeframe, n=rep.duplicates).warning(
            "quality.duplicates"
        )
    if rep.gaps:
        logger.bind(symbol=symbol, tf=timeframe, n=rep.gaps).info("quality.gaps")
    return rep


def write_daily_manifest(
    reports: list[QualityReport],
    *,
    out_dir: Path | None = None,
    date: datetime | None = None,
) -> Path:
    """Günlük JSON manifest yaz: data/quality/YYYY-MM-DD.json."""
    out_dir = out_dir or (ROOT_DIR / "data" / "quality")
    out_dir.mkdir(parents=True, exist_ok=True)
    date = date or datetime.now(timezone.utc)
    fname = out_dir / f"{date.strftime('%Y-%m-%d')}.json"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report_count": len(reports),
        "reports": [r.to_dict() for r in reports],
    }
    fname.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    logger.bind(file=str(fname), n=len(reports)).info("quality.manifest_written")
    return fname
