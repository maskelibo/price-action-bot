"""BTC Dominance Altcoin Rotation Filter testleri — H22.

Test gruplari:
    T01: compute_btc_d_trend — lookahead-free (shift(1))
    T02: compute_btc_d_trend — falling BTC.D neg slope
    T03: compute_btc_d_trend — rising BTC.D pos slope
    T04: compute_btc_d_trend — empty input graceful
    T05: filter_alt_signals_by_btc_d — alt long blocked in BTC dominant regime
    T06: filter_alt_signals_by_btc_d — alt long passes in alt season
    T07: filter_alt_signals_by_btc_d — BTC sembol ALWAYS passes (exempt)
    T08: filter_alt_signals_by_btc_d — short signals always pass
    T09: filter_alt_signals_by_btc_d — empty btcd_df → all signals pass (conservative)
    T10: DominanceStore roundtrip
    T11: combined F&G + BTC.D filter
    T12: _mock_dominance schema + range
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import sys
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def falling_btcd_df() -> pd.DataFrame:
    """60 gunluk monoton dusen BTC.D (slope kesinlikle negatif)."""
    days = pd.date_range("2023-01-01", periods=60, freq="1D", tz="UTC")
    # 60 → 40: her gun ~0.33 pp dusuyor
    dom = np.linspace(60.0, 40.0, 60)
    return pd.DataFrame({"ts": days, "btc_dominance": dom})


@pytest.fixture
def rising_btcd_df() -> pd.DataFrame:
    """60 gunluk monoton yukselen BTC.D (slope kesinlikle pozitif)."""
    days = pd.date_range("2023-01-01", periods=60, freq="1D", tz="UTC")
    dom = np.linspace(40.0, 65.0, 60)
    return pd.DataFrame({"ts": days, "btc_dominance": dom})


@pytest.fixture
def sample_btcd_df() -> pd.DataFrame:
    """200 gunluk karısık BTC.D (test genel amacli)."""
    rng = np.random.default_rng(123)
    days = pd.date_range("2023-01-01", periods=200, freq="1D", tz="UTC")
    dom = np.clip(50 + np.cumsum(rng.normal(0, 0.3, 200)), 30, 70)
    return pd.DataFrame({"ts": days, "btc_dominance": dom.round(2)})


def _make_signal(
    date_str: str,
    symbol: str = "ETH/USDT",
    direction: str = "long",
) -> "Signal":
    from price_action.contracts import Signal
    ts = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if direction == "long":
        sl, tp = 1800.0, 2200.0
    else:
        sl, tp = 2200.0, 1800.0
    return Signal(
        ts=ts,
        venue="binance",
        symbol=symbol,
        timeframe="1d",
        direction=direction,
        pattern_id="test_engulf",
        confluence_score=1.5,
        sl_price=sl,
        tp_price=tp,
        suggested_size_atr=1.0,
    )


# ---------------------------------------------------------------------------
# T01: compute_btc_d_trend — lookahead-free: slope_lag = shift(1) of slope
# ---------------------------------------------------------------------------

def test_T01_lookahead_free(falling_btcd_df):
    """btcd_slope_lag, btcd_slope'un shift(1)'i olmali — lookahead yok."""
    from price_action.strategies.dominance_filter import compute_btc_d_trend

    result = compute_btc_d_trend(falling_btcd_df, lookback=10)
    assert "btcd_slope" in result.columns
    assert "btcd_slope_lag" in result.columns

    # Row i'nin slope_lag'i = row i-1'in slope'u
    for i in range(1, len(result)):
        lag = result["btcd_slope_lag"].iloc[i]
        prev_slope = result["btcd_slope"].iloc[i - 1]
        if pd.notna(lag) and pd.notna(prev_slope):
            assert abs(lag - prev_slope) < 1e-10, (
                f"Lookahead hatasi: row {i} slope_lag={lag:.6f} "
                f"row {i-1} slope={prev_slope:.6f}"
            )


# ---------------------------------------------------------------------------
# T02: compute_btc_d_trend — falling BTC.D yields negative slope
# ---------------------------------------------------------------------------

def test_T02_falling_btcd_negative_slope(falling_btcd_df):
    """Dusen BTC.D → btcd_slope_lag < 0 (lookback geceldiginde)."""
    from price_action.strategies.dominance_filter import compute_btc_d_trend

    result = compute_btc_d_trend(falling_btcd_df, lookback=5)
    valid = result.dropna(subset=["btcd_slope_lag"])

    assert not valid.empty, "slope_lag tamamen NaN olmamali"
    # Dusen seri → slope negatif olmali
    neg_count = (valid["btcd_slope_lag"] < 0).sum()
    assert neg_count > 0, (
        f"Dusen BTC.D negatif slope uretmeli. "
        f"Slope range: [{valid['btcd_slope_lag'].min():.4f}, {valid['btcd_slope_lag'].max():.4f}]"
    )
    # Cok buyuk kismi negatif olmali (monoton dusen seri)
    neg_pct = neg_count / len(valid)
    assert neg_pct > 0.8, f"Cok az negatif slope: {neg_pct:.1%}"


# ---------------------------------------------------------------------------
# T03: compute_btc_d_trend — rising BTC.D yields positive slope
# ---------------------------------------------------------------------------

def test_T03_rising_btcd_positive_slope(rising_btcd_df):
    """Yukselen BTC.D → btcd_slope_lag > 0 (lookback geceldiginde)."""
    from price_action.strategies.dominance_filter import compute_btc_d_trend

    result = compute_btc_d_trend(rising_btcd_df, lookback=5)
    valid = result.dropna(subset=["btcd_slope_lag"])

    assert not valid.empty
    pos_pct = (valid["btcd_slope_lag"] > 0).mean()
    assert pos_pct > 0.8, f"Yukselen BTC.D pozitif slope uretmeli: {pos_pct:.1%}"


# ---------------------------------------------------------------------------
# T04: compute_btc_d_trend — empty / None → graceful
# ---------------------------------------------------------------------------

def test_T04_empty_btcd_graceful():
    """Bos veya None btcd_df → crash yok, bos DataFrame doner."""
    from price_action.strategies.dominance_filter import compute_btc_d_trend

    result_empty = compute_btc_d_trend(pd.DataFrame(), lookback=30)
    assert isinstance(result_empty, pd.DataFrame)
    assert result_empty.empty

    result_none = compute_btc_d_trend(None, lookback=30)  # type: ignore[arg-type]
    assert isinstance(result_none, pd.DataFrame)
    assert result_none.empty


# ---------------------------------------------------------------------------
# T05: filter_alt_signals_by_btc_d — rising BTC.D blocks alt long
# ---------------------------------------------------------------------------

def test_T05_rising_btcd_blocks_alt_long(rising_btcd_df):
    """Yukselen BTC.D (positive slope) → alt long bloklanmali."""
    from price_action.strategies.dominance_filter import filter_alt_signals_by_btc_d

    # rising_btcd_df: 60 gun yukselen (2023-01-01 to 2023-03-01)
    # lookback=10 → bar 15 (2023-01-16) için yeterli; slope_lag bar 11'den itibaren var
    # Signal tarihi: 2023-02-15 (bar ~45, veri icinde ve yeterli lookback var)
    sig = _make_signal("2023-02-15", symbol="ETH/USDT", direction="long")

    filtered, stats = filter_alt_signals_by_btc_d(
        [sig], rising_btcd_df, btc_d_trend_max=0.0, lookback=10
    )

    # Slope pozitif → BLOKLANMALI
    assert stats.rejected_btcd == 1, (
        f"Yukselen BTC.D alt long'u bloklumali. "
        f"stats={stats.to_dict()}"
    )
    assert len(filtered) == 0


# ---------------------------------------------------------------------------
# T06: filter_alt_signals_by_btc_d — falling BTC.D passes alt long
# ---------------------------------------------------------------------------

def test_T06_falling_btcd_passes_alt_long(falling_btcd_df):
    """Dusen BTC.D (negative slope) → alt long GECER."""
    from price_action.strategies.dominance_filter import filter_alt_signals_by_btc_d

    sig = _make_signal("2023-03-15", symbol="ETH/USDT", direction="long")

    filtered, stats = filter_alt_signals_by_btc_d(
        [sig], falling_btcd_df, btc_d_trend_max=0.0, lookback=10
    )

    # Slope negatif → GECMELI
    assert len(filtered) == 1, (
        f"Dusen BTC.D alt long'u gecirmeli. stats={stats.to_dict()}"
    )
    assert stats.rejected_btcd == 0


# ---------------------------------------------------------------------------
# T07: filter_alt_signals_by_btc_d — BTC symbol ALWAYS passes
# ---------------------------------------------------------------------------

def test_T07_btc_symbol_always_passes(rising_btcd_df):
    """BTC/USDT sembolü BTC.D filtresinden MUAF — her zaman gecer."""
    from price_action.strategies.dominance_filter import filter_alt_signals_by_btc_d

    # Yukselen BTC.D → normalde alt long bloklardı ama BTC muaf
    btc_long = _make_signal("2023-03-15", symbol="BTC/USDT", direction="long")
    btc_short = _make_signal("2023-03-15", symbol="BTC/USDT", direction="short")
    # Alt variants for comparison
    btcusd = _make_signal("2023-03-15", symbol="BTCUSDT", direction="long")

    filtered, stats = filter_alt_signals_by_btc_d(
        [btc_long, btc_short, btcusd],
        rising_btcd_df,
        btc_d_trend_max=0.0,
        lookback=10,
    )

    assert len(filtered) == 3, (
        f"BTC sinyalleri tamamen gecmeli. filtered={len(filtered)}, "
        f"rejected={stats.rejected_btcd}, btc_exempt={stats.btc_exempt}"
    )
    assert stats.rejected_btcd == 0, "BTC sinyalleri HICBIR ZAMAN reddedilmemeli"
    assert stats.btc_exempt == 3, f"3 BTC muafiyeti bekleniyor, {stats.btc_exempt} var"


# ---------------------------------------------------------------------------
# T08: filter_alt_signals_by_btc_d — short signals always pass
# ---------------------------------------------------------------------------

def test_T08_short_signals_always_pass(rising_btcd_df):
    """Short sinyalleri BTC.D filtresinden MUAF — sadece alt long filtre uygulanir."""
    from price_action.strategies.dominance_filter import filter_alt_signals_by_btc_d

    eth_short = _make_signal("2023-03-15", symbol="ETH/USDT", direction="short")
    sol_short = _make_signal("2023-03-15", symbol="SOL/USDT", direction="short")

    filtered, stats = filter_alt_signals_by_btc_d(
        [eth_short, sol_short],
        rising_btcd_df,
        btc_d_trend_max=0.0,
        lookback=10,
    )

    assert len(filtered) == 2, (
        f"Short sinyaller her zaman gecmeli. filtered={len(filtered)}, "
        f"short_exempt={stats.short_exempt}"
    )
    assert stats.rejected_btcd == 0
    assert stats.short_exempt == 2


# ---------------------------------------------------------------------------
# T09: filter_alt_signals_by_btc_d — empty btcd_df → conservative pass
# ---------------------------------------------------------------------------

def test_T09_empty_btcd_conservative_pass():
    """Bos BTC.D verisi → konservatif: tum sinyaller gecer, crash yok."""
    from price_action.strategies.dominance_filter import filter_alt_signals_by_btc_d

    sigs = [
        _make_signal("2023-03-15", symbol="ETH/USDT", direction="long"),
        _make_signal("2023-03-15", symbol="SOL/USDT", direction="long"),
        _make_signal("2023-03-15", symbol="BTC/USDT", direction="long"),
    ]

    filtered_empty, stats_e = filter_alt_signals_by_btc_d(
        sigs, pd.DataFrame(), btc_d_trend_max=0.0
    )
    assert len(filtered_empty) == 3, "Bos BTC.D → tum sinyaller gecmeli"
    assert stats_e.rejected_btcd == 0

    filtered_none, stats_n = filter_alt_signals_by_btc_d(
        sigs, None, btc_d_trend_max=0.0  # type: ignore[arg-type]
    )
    assert len(filtered_none) == 3
    assert stats_n.rejected_btcd == 0


# ---------------------------------------------------------------------------
# T10: DominanceStore roundtrip
# ---------------------------------------------------------------------------

def test_T10_dominance_store_roundtrip(tmp_path, sample_btcd_df):
    """DominanceStore: upsert + read round-trip tutarli olmali."""
    from price_action.data.dominance_ingest import DominanceStore, reset_dominance_pool

    db = tmp_path / "test_dom.duckdb"
    reset_dominance_pool()
    store = DominanceStore(duckdb_path=db)

    written = store.upsert(sample_btcd_df)
    assert written == len(sample_btcd_df), f"Yazilan {written} != {len(sample_btcd_df)}"

    df_read = store.read()
    assert not df_read.empty
    assert len(df_read) == len(sample_btcd_df)
    assert set(df_read.columns) >= {"ts", "btc_dominance"}
    assert (df_read["btc_dominance"] > 0).all()
    assert (df_read["btc_dominance"] < 100).all()

    # Idempotent upsert (tekrar yazma)
    written2 = store.upsert(sample_btcd_df)
    df_read2 = store.read()
    assert len(df_read2) == len(df_read), "Upsert idempotent olmali — satir artmamali"

    reset_dominance_pool()


# ---------------------------------------------------------------------------
# T11: Combined F&G + BTC.D filter
# ---------------------------------------------------------------------------

def test_T11_combined_fng_btcd_filter(falling_btcd_df):
    """F&G + BTC.D bileşik filtre: her iki filtre dogru uygulanmali."""
    from price_action.strategies.dominance_filter import filter_engulfing_fng_and_btcd
    from price_action.contracts import Signal

    # F&G: yuksek greed (>= 60 long eşigi) → long blokla
    days = falling_btcd_df["ts"].dt.date.unique()
    fng_date = falling_btcd_df["ts"].iloc[40]  # bar 40 (yeterli lookback var)
    # Build F&G df with high greed on target date
    fng_dates = pd.date_range("2023-01-01", periods=60, freq="1D", tz="UTC")
    fng_values = [50] * 60
    fng_values[39] = 75  # bar 39 (t-1 of bar 40) = extreme greed
    fng_df = pd.DataFrame({
        "ts": fng_dates,
        "value": fng_values,
        "classification": ["Neutral"] * 60,
    })

    sig_long = _make_signal(str(fng_date.date()), symbol="ETH/USDT", direction="long")
    sig_btc = _make_signal(str(fng_date.date()), symbol="BTC/USDT", direction="long")
    sig_short = _make_signal(str(fng_date.date()), symbol="ETH/USDT", direction="short")

    # ETH long with high F&G → blocked by F&G
    # BTC long with high F&G → blocked by F&G (BTC exempt from BTC.D but NOT F&G)
    # ETH short → passes (short exempt from BTC.D, F&G check for short is different)
    filtered, stats = filter_engulfing_fng_and_btcd(
        [sig_long, sig_btc, sig_short],
        fng_df,
        falling_btcd_df,
        long_max_fng=60.0,
        short_min_fng=40.0,
        btc_d_trend_max=0.0,
        btcd_lookback=10,
    )

    assert isinstance(filtered, list)
    assert isinstance(stats, dict)
    assert "fng" in stats
    assert "btcd" in stats
    assert stats["total_input"] == 3
    # ETH long blocked by F&G (value 75 >= 60 threshold on bar 40)
    # Short passes F&G check (50 > 40 min for shorts)
    assert stats["fng"]["n_rejected"] >= 1, (
        f"Yuksek F&G long'u bloklumali. fng_stats={stats['fng']}"
    )


# ---------------------------------------------------------------------------
# T12: _mock_dominance schema + range check
# ---------------------------------------------------------------------------

def test_T12_mock_dominance_schema():
    """Mock BTC.D: schema dogru, degerler mantikli aralikta."""
    from price_action.data.dominance_ingest import _mock_dominance

    df = _mock_dominance(365)

    assert not df.empty, "Mock DataFrame bos olmamali"
    assert set(df.columns) >= {"ts", "btc_dominance"}, "Schema eksik"
    assert len(df) >= 360, f"Yeterli satir yok: {len(df)}"
    assert pd.api.types.is_datetime64_any_dtype(df["ts"]), "ts datetime olmali"
    assert df["ts"].dt.tz is not None, "ts timezone-aware olmali"

    # BTC.D range: gerçekci aralik
    assert (df["btc_dominance"] >= 20.0).all(), (
        f"BTC.D cok dusuk: min={df['btc_dominance'].min():.1f}%"
    )
    assert (df["btc_dominance"] <= 80.0).all(), (
        f"BTC.D cok yuksek: max={df['btc_dominance'].max():.1f}%"
    )

    # Monoton artis kontrolu — sinuzoidal oldugundan cok degil ama trend var mi?
    # (Sadece cokan bir seri olmadigini kontrol et)
    std_dom = df["btc_dominance"].std()
    assert std_dom > 1.0, f"BTC.D cok sabit (std={std_dom:.2f}) — gercekci degil"
