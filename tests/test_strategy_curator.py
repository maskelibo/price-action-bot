"""Strategy Curator Agent — Faz 8 tests.

Coverage:
- YAML parse → active strategies list
- src/price_action/strategies/ glob → library modules
- Alpha decay slope: negative (decaying) → retire signal
- Alpha decay slope: positive (growing) → no retire
- Marginal Sharpe: 2-strategy book + new strategy returns
- Diversity entropy: uncorrelated vs correlated strategies
- Retirement decision flow: alpha decay active + n ≥ min_sample → RETIRE
- Onboarding decision flow: gates pass → ONBOARD

No live LLM call — `PA_LLM_DRY_RUN=true`.
"""
from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from price_action.agents.strategy_curator import (
    StrategyCuratorAgent,
    _annualized_sharpe,
    _calc_alpha_decay_slope,
    _calc_diversity_entropy,
)
from price_action.memory import MemoryStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FAKE_ACTIVE_YAML = """\
defaults:
  preset_name: test_preset
strategy_portfolio:
  enabled: true
  strategies:
    - vsa_climax_test
    - brooks_failed_breakout
"""

_FAKE_ACTIVE_YAML_DISABLED = """\
defaults:
  preset_name: test_preset_off
strategy_portfolio:
  enabled: false
  strategies:
    - anchored_vwap_reversal
"""

_LIFECYCLE_YAML = """\
alpha_decay:
  rolling_window_days: 90
  sharpe_slope_threshold: -0.001
  min_sample_size: 30

retirement_criteria:
  rolling_sharpe_min: 0.5
  alpha_decay_active: true
  cooldown_weeks_after_retire: 12

onboarding_criteria:
  min_lab_tournament_pass: 1
  min_oos_trades: 30
  min_marginal_sharpe_pct: 0.05
  max_correlation_to_book: 0.7

probation_criteria:
  weeks_on_probation: 4
  min_trades_during_probation: 10
  exit_to_active_if: "marginal_sharpe_positive AND no_alpha_decay"
  exit_to_retire_if: "marginal_sharpe_negative OR alpha_decay_active"

diversity_targets:
  min_entropy_normalized: 0.6
  max_pairwise_correlation: 0.8

library_path: src/price_action/strategies/
active_configs:
  - configs/active_a.yaml
  - configs/active_b.yaml
"""


@pytest.fixture
def curator_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """İzole ROOT_DIR + minimal memory + configs + library dirs."""
    root = tmp_path
    (root / "reports" / "curator").mkdir(parents=True)
    (root / "memory" / "strategy_curator").mkdir(parents=True)
    (root / "memory" / "shared" / "facts").mkdir(parents=True)
    (root / "memory" / "shared" / "lessons").mkdir(parents=True)
    (root / "memory" / "protocol").mkdir(parents=True)
    (root / "configs").mkdir(parents=True)
    (root / "data").mkdir(parents=True)
    rules_dir = root / "agents"
    rules_dir.mkdir(parents=True)
    (rules_dir / "strategy_curator.md").write_text(
        "---\nname: strategy_curator\n---\n# Curator rules\n", encoding="utf-8"
    )
    (root / "memory" / "strategy_curator" / "identity.md").write_text("# id\n", encoding="utf-8")
    (root / "memory" / "strategy_curator" / "know_how.md").write_text("# kh\n", encoding="utf-8")
    (root / "memory" / "strategy_curator" / "learning.md").write_text("# l\n", encoding="utf-8")

    # Lifecycle config
    (root / "configs" / "strategy_lifecycle.yaml").write_text(_LIFECYCLE_YAML, encoding="utf-8")
    # Aktif config'ler (lifecycle yaml'da listelenen)
    (root / "configs" / "active_a.yaml").write_text(_FAKE_ACTIVE_YAML, encoding="utf-8")
    (root / "configs" / "active_b.yaml").write_text(_FAKE_ACTIVE_YAML_DISABLED, encoding="utf-8")

    # Sahte strategies library
    lib = root / "src" / "price_action" / "strategies"
    lib.mkdir(parents=True)
    (lib / "__init__.py").write_text("", encoding="utf-8")
    (lib / "base.py").write_text("# base\n", encoding="utf-8")
    (lib / "manifest_loader.py").write_text("# loader\n", encoding="utf-8")
    (lib / "vsa_climax_test.py").write_text("# strat\n", encoding="utf-8")
    (lib / "brooks_failed_breakout.py").write_text("# strat\n", encoding="utf-8")
    (lib / "anchored_vwap_reversal.py").write_text("# strat\n", encoding="utf-8")
    (lib / "engulfing_continuation.py").write_text("# strat\n", encoding="utf-8")

    monkeypatch.setenv("PA_LLM_DRY_RUN", "true")
    from price_action import settings as _settings_mod
    _settings_mod.get_settings.cache_clear()
    monkeypatch.setattr(_settings_mod, "ROOT_DIR", root)
    return {"root": root, "rules_dir": rules_dir}


@pytest.fixture
def agent(curator_env: dict[str, Any]) -> StrategyCuratorAgent:
    store = MemoryStore(base_dir=curator_env["root"] / "memory")
    return StrategyCuratorAgent(memory_store=store)


# ---------------------------------------------------------------------------
# Helpers — synthetic returns generators
# ---------------------------------------------------------------------------


def _decaying_returns(n: int = 200, start_mu: float = 0.005, end_mu: float = -0.005, seed: int = 7) -> list[float]:
    """Drift mu from start_mu to end_mu over n samples — alpha decay simülasyonu."""
    import numpy as np
    rng = np.random.default_rng(seed)
    mus = np.linspace(start_mu, end_mu, n)
    noise = rng.normal(0.0, 0.01, size=n)
    return (mus + noise).tolist()


def _growing_returns(n: int = 200, start_mu: float = -0.002, end_mu: float = 0.006, seed: int = 11) -> list[float]:
    """Drift mu from start_mu to end_mu (improving edge)."""
    import numpy as np
    rng = np.random.default_rng(seed)
    mus = np.linspace(start_mu, end_mu, n)
    noise = rng.normal(0.0, 0.01, size=n)
    return (mus + noise).tolist()


def _stable_returns(n: int = 200, mu: float = 0.003, sigma: float = 0.01, seed: int = 13) -> list[float]:
    import numpy as np
    rng = np.random.default_rng(seed)
    return rng.normal(mu, sigma, size=n).tolist()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_active_strategies_load(curator_env: dict[str, Any], agent: StrategyCuratorAgent) -> None:
    """YAML parse → aktif strateji listesi."""
    active_map = agent._load_active_strategies()
    # active_a.yaml enabled=true → vsa + brooks; active_b.yaml enabled=false → boş
    assert "configs/active_a.yaml" in active_map
    assert "configs/active_b.yaml" in active_map
    assert active_map["configs/active_a.yaml"] == ["vsa_climax_test", "brooks_failed_breakout"]
    assert active_map["configs/active_b.yaml"] == []
    # Flat unique
    flat = agent._flat_active_strategies()
    assert flat == ["vsa_climax_test", "brooks_failed_breakout"]


def test_library_scan(curator_env: dict[str, Any], agent: StrategyCuratorAgent) -> None:
    """strategies/ dizini → modül listesi, __init__/base/manifest_loader hariç."""
    lib = agent._list_library_strategies()
    assert "vsa_climax_test" in lib
    assert "brooks_failed_breakout" in lib
    assert "anchored_vwap_reversal" in lib
    assert "engulfing_continuation" in lib
    # Excludes
    assert "__init__" not in lib
    assert "base" not in lib
    assert "manifest_loader" not in lib
    assert len(lib) == 4


def test_alpha_decay_slope_negative() -> None:
    """Decaying returns (drift mu ↓) → slope < 0; retirement signal."""
    series = _decaying_returns(n=200, start_mu=0.005, end_mu=-0.005, seed=7)
    out = _calc_alpha_decay_slope(series, window_days=90)
    assert not math.isnan(out["slope"])
    assert out["n_obs"] == 200
    # Negative slope — rolling Sharpe shrinks over time
    assert out["slope"] < 0.0, f"expected negative slope, got {out['slope']}"
    # SE pozitif ve makul boyutta
    assert out["slope_se"] > 0.0


def test_alpha_decay_slope_positive() -> None:
    """Growing edge → slope > 0; no retire signal."""
    series = _growing_returns(n=200, start_mu=-0.002, end_mu=0.006, seed=11)
    out = _calc_alpha_decay_slope(series, window_days=90)
    assert not math.isnan(out["slope"])
    # Positive slope — growing edge
    assert out["slope"] > 0.0, f"expected positive slope, got {out['slope']}"


def test_alpha_decay_insufficient_data() -> None:
    """n < window + buffer → NaN slope, n_obs raporlanır."""
    short = _stable_returns(n=20, mu=0.001, sigma=0.005, seed=1)
    out = _calc_alpha_decay_slope(short, window_days=90)
    assert math.isnan(out["slope"])
    assert out["n_obs"] == 20


def test_diversity_entropy_uncorrelated_vs_correlated() -> None:
    """Uncorrelated → entropy high (~1.0); perfectly correlated → entropy ~0."""
    import numpy as np

    # Uncorrelated (identity)
    n = 4
    identity = np.eye(n)
    uncorr = _calc_diversity_entropy(identity)
    assert uncorr["n_strategies"] == n
    assert uncorr["entropy_normalized"] == pytest.approx(1.0, abs=1e-6)

    # Perfectly correlated (all 1.0) — degenerate, entropy ≈ 0
    ones = np.ones((n, n))
    perfect = _calc_diversity_entropy(ones)
    assert perfect["entropy_normalized"] < 0.05

    # Mixed: 2 clusters of perfectly correlated strategies → middle entropy
    C = np.array(
        [
            [1.0, 0.95, 0.0, 0.0],
            [0.95, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.95],
            [0.0, 0.0, 0.95, 1.0],
        ]
    )
    mixed = _calc_diversity_entropy(C)
    assert 0.3 < mixed["entropy_normalized"] < 0.95


def test_marginal_sharpe_calc(curator_env: dict[str, Any], agent: StrategyCuratorAgent) -> None:
    """Mock 2-strategy book + new → marginal Sharpe delta hesaplanır."""
    book = {
        "vsa_climax_test": _stable_returns(n=120, mu=0.002, sigma=0.012, seed=21),
        "brooks_failed_breakout": _stable_returns(n=120, mu=0.001, sigma=0.010, seed=22),
    }
    new_returns = _stable_returns(n=120, mu=0.004, sigma=0.011, seed=23)

    out = asyncio.run(
        agent.calc_marginal_sharpe(
            "new_engulfing_4h",
            new_strategy_returns=new_returns,
            book_returns=book,
        )
    )
    assert "existing_sharpe" in out
    assert "with_new_sharpe" in out
    assert "marginal_pct" in out
    assert "correlation_to_book" in out
    # Tutarlılık: with_new ≠ existing; her ikisi sonlu
    assert math.isfinite(out["existing_sharpe"])
    assert math.isfinite(out["with_new_sharpe"])
    # Correlation finite
    assert math.isfinite(out["correlation_to_book"])
    # New mu > book mu → with_new genelde ≥ existing (pozitif beklenir)
    assert out["with_new_sharpe"] >= out["existing_sharpe"] - 0.5  # ufak gürültü toleransı


def test_marginal_sharpe_empty_book(curator_env: dict[str, Any], agent: StrategyCuratorAgent) -> None:
    """Book boş + yeni returns → existing=0, with_new = yeni Sharpe."""
    new_returns = _stable_returns(n=120, mu=0.004, sigma=0.011, seed=31)
    out = asyncio.run(
        agent.calc_marginal_sharpe(
            "first_strategy",
            new_strategy_returns=new_returns,
            book_returns={},
        )
    )
    assert out["existing_sharpe"] == 0.0
    assert math.isfinite(out["with_new_sharpe"])
    assert out["with_new_sharpe"] > 0.0


def test_retirement_decision_flow(curator_env: dict[str, Any], agent: StrategyCuratorAgent) -> None:
    """Decay-active + n ≥ min_sample → RETIRE; growing edge → KEEP."""
    cfg = agent._load_lifecycle_config()

    # Decaying — slope < threshold, 3 hafta consecutive simüle
    decay_returns = _decaying_returns(n=200, start_mu=0.006, end_mu=-0.008, seed=41)
    decay = _calc_alpha_decay_slope(decay_returns, window_days=90)
    # consecutive_weeks = 3 (üst üste decay var varsayımı)
    verdict, reason = agent._retirement_verdict("decaying_strat", decay, 3, cfg)
    assert verdict == "RETIRE", f"expected RETIRE, got {verdict}: {reason}"

    # Growing — slope > 0 → KEEP
    grow_returns = _growing_returns(n=200, start_mu=-0.001, end_mu=0.006, seed=42)
    grow = _calc_alpha_decay_slope(grow_returns, window_days=90)
    verdict_g, reason_g = agent._retirement_verdict("growing_strat", grow, 0, cfg)
    assert verdict_g == "KEEP", f"expected KEEP, got {verdict_g}: {reason_g}"

    # Insufficient data — n < min_sample_size (30) yetersiz
    short = _stable_returns(n=15, mu=0.001, sigma=0.005, seed=43)
    short_decay = _calc_alpha_decay_slope(short, window_days=90)
    verdict_s, reason_s = agent._retirement_verdict("short_strat", short_decay, 0, cfg)
    assert verdict_s == "INSUFFICIENT_DATA"


def test_onboarding_decision_flow(curator_env: dict[str, Any], agent: StrategyCuratorAgent) -> None:
    """Yeni hypothesis → tüm gate'ler geçerse ONBOARD; gate fail → REJECT."""
    cfg = agent._load_lifecycle_config()

    # Geçen aday
    good_candidate = {
        "id": "good_cand",
        "lab_tournament_passes": 1,
        "oos_trades": 50,
    }
    good_marginal = {
        "existing_sharpe": 1.2,
        "with_new_sharpe": 1.4,
        "marginal_pct": 0.166,   # +16.6%
        "correlation_to_book": 0.35,
    }
    verdict, reason = agent._onboarding_verdict(good_candidate, good_marginal, cfg)
    assert verdict == "ONBOARD", f"expected ONBOARD, got {verdict}: {reason}"

    # Reject — marginal Sharpe çok düşük
    weak_cand = {
        "id": "weak_cand",
        "lab_tournament_passes": 1,
        "oos_trades": 50,
    }
    weak_marginal = {
        "existing_sharpe": 1.2,
        "with_new_sharpe": 1.21,
        "marginal_pct": 0.008,   # %0.8 → eşik altı (%5)
        "correlation_to_book": 0.4,
    }
    verdict_w, reason_w = agent._onboarding_verdict(weak_cand, weak_marginal, cfg)
    assert verdict_w == "REJECT"
    assert "marginal_pct" in reason_w

    # Reject — yüksek korelasyon
    correlated_cand = {
        "id": "corr_cand",
        "lab_tournament_passes": 1,
        "oos_trades": 50,
    }
    correlated_marginal = {
        "existing_sharpe": 1.2,
        "with_new_sharpe": 1.35,
        "marginal_pct": 0.125,
        "correlation_to_book": 0.85,   # > 0.7 cap
    }
    verdict_c, _reason_c = agent._onboarding_verdict(correlated_cand, correlated_marginal, cfg)
    assert verdict_c == "REJECT"

    # Reject — tournament_pass yok
    untested = {
        "id": "untested",
        "lab_tournament_passes": 0,
        "oos_trades": 50,
    }
    verdict_u, reason_u = agent._onboarding_verdict(untested, good_marginal, cfg)
    assert verdict_u == "REJECT"
    assert "tournament_pass" in reason_u


def test_daily_correlation_update_writes_doc(
    curator_env: dict[str, Any], agent: StrategyCuratorAgent
) -> None:
    """Smoke test: daily_correlation_update → doc yazılır, protokol frontmatter mevcut."""
    # Sahte journal seed et — DuckDB varsa
    duckdb = pytest.importorskip("duckdb")
    journal = curator_env["root"] / "data" / "futures_journal_test.duckdb"
    con = duckdb.connect(str(journal))
    try:
        con.execute(
            """
            CREATE TABLE futures_trades_closed (
                trade_id TEXT PRIMARY KEY,
                ts_open TIMESTAMP,
                ts_close TIMESTAMP,
                sym TEXT,
                side TEXT,
                strategy TEXT,
                entry_price DOUBLE,
                exit_price DOUBLE,
                qty DOUBLE,
                realized_pnl_usdt DOUBLE,
                realized_r DOUBLE,
                win BOOLEAN,
                close_reason TEXT
            )
            """
        )
        base = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=20)
        # 30 trade per active strategy
        strategies = ["vsa_climax_test", "brooks_failed_breakout"]
        rows = []
        for i, strat in enumerate(strategies):
            for j in range(30):
                rows.append(
                    [
                        f"{strat}-{j}",
                        base + timedelta(hours=j),
                        base + timedelta(hours=j + 1),
                        "BTCUSDT",
                        "long",
                        strat,
                        100.0,
                        100.5,
                        1.0,
                        1.0 + j * 0.1 + i * 0.05,
                        0.5,
                        True,
                        "tp",
                    ]
                )
        for r in rows:
            con.execute(
                "INSERT INTO futures_trades_closed VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", r
            )
        con.commit()
    finally:
        con.close()

    path = asyncio.run(agent.daily_correlation_update())
    assert path is not None and path.exists()
    content = path.read_text(encoding="utf-8")
    assert "Strategy Correlation Update" in content
    assert "vsa_climax_test" in content
    assert "doc_type: strategy_correlation" in content


def test_annualized_sharpe_helper() -> None:
    """Helper: stable returns → pozitif Sharpe; sabit seri → 0."""
    series = _stable_returns(n=200, mu=0.003, sigma=0.01, seed=99)
    sr = _annualized_sharpe(series)
    assert sr > 0
    # Sabit seri → sigma 0 → Sharpe 0
    flat = [0.001] * 50
    assert _annualized_sharpe(flat) == 0.0
    # Boş → 0
    assert _annualized_sharpe([]) == 0.0
