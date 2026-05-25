"""Faz 7 — Parameter sweep tests."""
from __future__ import annotations

import json
import pickle
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Ensure scripts/ is importable.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from param_sweep_runner import (  # noqa: E402
    apply_cell,
    build_regime_series,
    iter_grid,
    load_pool,
    rank_top,
    run_sweep,
)


POOL_5M = _REPO_ROOT / "data" / "sec53_5m_pool_v11_vm20.pkl"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_pool_df() -> pd.DataFrame:
    """Synthetic pool — 100 trades, deterministic R distribution."""
    rng = np.random.default_rng(42)
    n = 100
    ts0 = pd.Timestamp("2024-01-01", tz="UTC")
    records = []
    for i in range(n):
        entry_price = 100.0 + rng.uniform(-5, 5)
        # 50% sl_pct ~ 0.04 (above base 0.030), 50% ~ 0.02 (below).
        sl_pct = 0.04 if i % 2 == 0 else 0.02
        initial_sl = entry_price * (1 + sl_pct) if i % 2 == 0 else entry_price * (1 - sl_pct)
        # 60% winners @ +1.5R peak, 40% losers @ -1.05R realized
        if i % 5 < 3:
            R = 1.5
            peak_R = 1.8
        else:
            R = -1.05
            peak_R = 0.3
        records.append({
            "entry_ts": ts0 + pd.Timedelta(minutes=5 * i),
            "exit_ts": ts0 + pd.Timedelta(minutes=5 * i + 30),
            "entry_price": entry_price,
            "initial_sl": initial_sl,
            "R": R,
            "peak_R": peak_R,
            "symbol": "BTC/USDT" if i % 2 == 0 else "ETH/USDT",
            "side": "long" if i % 3 == 0 else "short",
            "conf": 0.33,
            "strategy": "vsa_climax_test",
            "vol_z": 1.0,
        })
    df = pd.DataFrame(records)
    df["sl_pct"] = (df["initial_sl"] - df["entry_price"]).abs() / df["entry_price"]
    return df


@pytest.fixture
def simple_grid() -> dict[str, list[float]]:
    return {
        "sl_multiplier": [1.0, 1.25, 1.5, 1.75, 2.0],
        "tp_r": [1.0, 1.2, 1.5, 2.0],
        "risk_pct": [0.003, 0.005, 0.007, 0.010],
    }


@pytest.fixture
def small_grid() -> dict[str, list[float]]:
    return {
        "sl_multiplier": [1.0, 1.5],
        "tp_r": [1.0, 1.5],
        "risk_pct": [0.005],
    }


@pytest.fixture
def tmp_output(tmp_path: Path) -> Path:
    return tmp_path / "report.md"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not POOL_5M.exists(), reason="real pool not available")
def test_pool_load() -> None:
    """Pool yüklenir, schema beklenen kolonları içerir, sl_pct türetilir."""
    df = load_pool(POOL_5M)
    assert len(df) > 100_000
    required = {"entry_ts", "exit_ts", "entry_price", "initial_sl",
                "R", "peak_R", "symbol", "side", "conf", "strategy", "sl_pct"}
    assert required.issubset(set(df.columns))
    assert df["sl_pct"].min() >= 0
    assert df["sl_pct"].mean() < 0.5  # sanity


def test_grid_iter(simple_grid: dict) -> None:
    cells = iter_grid(simple_grid)
    assert len(cells) == 5 * 4 * 4  # 80
    # Tüm kombinasyonlar unique
    keys = [tuple(c.values()) for c in cells]
    assert len(set(keys)) == 80
    # İlk cell
    c0 = cells[0]
    assert set(c0.keys()) == {"sl_multiplier", "tp_r", "risk_pct"}


def test_per_cell_metrics(mock_pool_df: pd.DataFrame) -> None:
    """Mock 100 trade → win_rate, mean_R doğru."""
    # sl_multiplier=1.0 (base=0.030), so threshold=0.030; only sl_pct=0.04
    # trades (50 of them) qualify.
    m = apply_cell(
        mock_pool_df,
        sl_multiplier=1.0,
        tp_r=2.0,  # high, so peak_R never reaches → use realized R
        risk_pct=0.005,
        sl_pct_base=0.030,
    )
    assert m.n_trades == 50
    # i % 2 == 0 ile filtered (50 trade). i % 5 < 3 → winner (R=1.5).
    # i % 2 == 0 AND i % 5 < 3 → i ∈ {0,2,6,10,12,16,20,...}
    # Hızlı sayım:
    expected_winners = sum(1 for i in range(100) if i % 2 == 0 and i % 5 < 3)
    assert int(m.n_trades * m.win_rate) == expected_winners
    # mean_R: winners 1.5, losers -1.05
    expected_mean = (expected_winners * 1.5 + (50 - expected_winners) * -1.05) / 50
    assert abs(m.mean_R - expected_mean) < 1e-6
    # sum_R should equal mean * n
    assert abs(m.sum_R - m.mean_R * m.n_trades) < 1e-6


def test_per_cell_metrics_tp_override(mock_pool_df: pd.DataFrame) -> None:
    """tp_r=1.0 → peak_R>=1.0 olanlar (winners, peak_R=1.8) +1.0R'ye snap."""
    m = apply_cell(
        mock_pool_df,
        sl_multiplier=1.0,
        tp_r=1.0,
        risk_pct=0.005,
        sl_pct_base=0.030,
    )
    # Winners now realize +1.0R instead of +1.5R; losers unchanged.
    expected_winners = sum(1 for i in range(100) if i % 2 == 0 and i % 5 < 3)
    expected_mean = (expected_winners * 1.0 + (50 - expected_winners) * -1.05) / 50
    assert abs(m.mean_R - expected_mean) < 1e-6


def test_top_5_ranking(mock_pool_df: pd.DataFrame, small_grid: dict) -> None:
    """rank_top sıralaması Sharpe_like'a göre desc."""
    cells = iter_grid(small_grid)
    metrics = [
        apply_cell(
            mock_pool_df,
            sl_multiplier=p["sl_multiplier"],
            tp_r=p["tp_r"],
            risk_pct=p["risk_pct"],
            sl_pct_base=0.030,
        )
        for p in cells
    ]
    top = rank_top(metrics, n=5)
    assert len(top) <= 5
    # Sıralama doğru
    sharpes = [c.sharpe_like for c in top]
    assert sharpes == sorted(sharpes, reverse=True)
    # Tüm top eligible (n_trades >= 30)
    for c in top:
        assert c.n_trades >= 30


def test_regime_split_filter(mock_pool_df: pd.DataFrame) -> None:
    """Regime breakdown bull/bear bölünmesi üretir."""
    # Build a mock regime series spanning the trade dates.
    ts_min = mock_pool_df["entry_ts"].min()
    ts_max = mock_pool_df["entry_ts"].max()
    idx = pd.date_range(ts_min - pd.Timedelta(hours=1), ts_max + pd.Timedelta(hours=1),
                        freq="1h", tz="UTC")
    # First half bull, second half bear.
    half = len(idx) // 2
    labels = ["bull"] * half + ["bear"] * (len(idx) - half)
    regime_series = pd.Series(labels, index=idx, name="regime")

    m = apply_cell(
        mock_pool_df,
        sl_multiplier=1.0,
        tp_r=2.0,
        risk_pct=0.005,
        sl_pct_base=0.030,
        regime_series=regime_series,
    )
    assert "bull" in m.regime_breakdown
    assert "bear" in m.regime_breakdown
    # Toplam regime n_trades n_trades'i geçmemeli
    total_regime = sum(s["n"] for s in m.regime_breakdown.values())
    assert total_regime <= m.n_trades  # bazı trade'lar regime dışına düşebilir


def test_build_regime_series(mock_pool_df: pd.DataFrame) -> None:
    """build_regime_series BTC trade'lerinden günlük serisi üretir."""
    series = build_regime_series(mock_pool_df)
    # 100 trade, %50'si BTC → ~50 BTC trade, span 5*100=500dk → 1 gün
    # Çok az gün olduğu için EMA fallback olur ama bir şey döner.
    assert isinstance(series, pd.Series)
    if len(series) > 0:
        assert set(series.unique()).issubset({"bull", "bear"})


def test_run_sweep_writes_report(mock_pool_df: pd.DataFrame, tmp_path: Path,
                                  small_grid: dict, monkeypatch) -> None:
    """run_sweep end-to-end: mock pool .pkl → run → markdown çıkar."""
    pool_path = tmp_path / "mock_pool.pkl"
    # Save records (without sl_pct, will be re-derived in load_pool)
    records = mock_pool_df.drop(columns=["sl_pct"]).to_dict("records")
    with pool_path.open("wb") as f:
        pickle.dump(records, f)

    output = tmp_path / "report.md"
    result = run_sweep(
        strategy="vsa_climax_test",
        pool_path=pool_path,
        grids=small_grid,
        output_path=output,
        sl_pct_base=0.030,
        enable_regime=False,  # mock has no real BTC daily price → skip
    )
    assert output.exists()
    assert result["n_cells"] == 4  # 2 * 2 * 1
    content = output.read_text()
    assert "Param Sweep" in content
    assert "vsa_climax_test" in content
    assert "Top 5" in content


# ---------------------------------------------------------------------------
# Chunk processor tests
# ---------------------------------------------------------------------------

def test_chunk_state_advance(tmp_path: Path) -> None:
    """Chunk processor state machine — offset advance + rotation."""
    from param_sweep_chunk_processor import advance_state

    rotation = ["a", "b", "c"]
    # Mid-strategy
    s1 = advance_state({"strategy": "a", "cell_offset": 0}, rotation, 5, 80)
    assert s1["strategy"] == "a"
    assert s1["cell_offset"] == 5

    # End-of-strategy → rotate
    s2 = advance_state({"strategy": "a", "cell_offset": 75}, rotation, 5, 80)
    assert s2["strategy"] == "b"
    assert s2["cell_offset"] == 0

    # Last → wrap
    s3 = advance_state({"strategy": "c", "cell_offset": 75}, rotation, 5, 80)
    assert s3["strategy"] == "a"


def test_chunk_processor_smoke(tmp_path: Path, mock_pool_df: pd.DataFrame) -> None:
    """process_chunk runs end-to-end with mock pool + writes JSONL."""
    from param_sweep_chunk_processor import process_chunk

    pool_path = tmp_path / "mock.pkl"
    records = mock_pool_df.drop(columns=["sl_pct"]).to_dict("records")
    with pool_path.open("wb") as f:
        pickle.dump(records, f)

    chunks_cfg = {
        "chunk_size": 2,
        "strategies_in_rotation": ["vsa_climax_test"],
        "chunk_state_file": str(tmp_path / "state.json"),
    }
    grids_cfg = {
        "default_grid": {
            "sl_multiplier": [1.0, 1.5],
            "tp_r": [1.0, 1.5],
            "risk_pct": [0.005],
        },
        "per_strategy": {
            "vsa_climax_test": {
                "pool": str(pool_path),
                "sl_pct_min": 0.030,
            },
        },
        "regime_split": {"enabled": False},
    }
    chunks_dir = tmp_path / "chunks"
    result = process_chunk(chunks_cfg, grids_cfg, chunks_dir)

    assert result["n_results"] == 2
    assert result["total_cells"] == 4  # 2*2*1
    assert Path(result["output"]).exists()
    # JSONL parseable
    with open(result["output"]) as f:
        lines = [json.loads(l) for l in f if l.strip()]
    assert len(lines) == 2
    assert "sharpe_like" in lines[0]
    assert lines[0]["strategy"] == "vsa_climax_test"


def test_weekly_summary(tmp_path: Path) -> None:
    """summarize_weekly aggregates chunks → markdown."""
    from param_sweep_chunk_processor import summarize_weekly

    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()
    today = datetime.now(timezone.utc).date().isoformat()
    fp = chunks_dir / f"{today}-vsa_climax_test-offset000.jsonl"
    rows = [
        {"strategy": "vsa_climax_test", "sl_multiplier": 1.0, "tp_r": 1.0,
         "risk_pct": 0.005, "n_trades": 100, "win_rate": 0.55,
         "mean_R": 0.2, "sharpe_like": 0.8},
        {"strategy": "vsa_climax_test", "sl_multiplier": 1.5, "tp_r": 1.5,
         "risk_pct": 0.005, "n_trades": 80, "win_rate": 0.6,
         "mean_R": 0.3, "sharpe_like": 1.2},
    ]
    with fp.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    result = summarize_weekly(
        {"weekly_lookback_days": 7}, chunks_dir, tmp_path / "weekly", lookback_days=7,
    )
    assert result["n_rows"] == 2
    assert Path(result["output"]).exists()
    md = Path(result["output"]).read_text()
    assert "vsa_climax_test" in md
    assert "Weekly Summary" in md
