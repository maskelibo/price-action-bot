"""Adversary Engineer tests — Faz 9 red team.

Gerçek LLM çağrısı YOK — `PA_LLM_DRY_RUN=true`.

Coverage:
1. test_stress_period_load — yaml load + 5 period
2. test_replay_returns_metrics — mock pool + DD/recovery hesabı
3. test_kill_probe_in_oos_spread — IS Sharpe 2.0 OOS 0.8 → FAIL
4. test_kill_probe_extreme_params — grid ucundan param → FAIL
5. test_kill_probe_min_trades — n=50 fail, n=500 pass
6. test_flash_crash_generator — synthetic data shape check
7. test_readiness_score_pass — tüm period geçerse skor 100 civarı
8. test_readiness_score_concave_penalty — concave equity penalty uygulanır
"""
from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from price_action.agents.adversary_engineer import AdversaryEngineerAgent
from price_action.memory import MemoryStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """İzole memory + agent rules + configs."""
    # Rules dir + adversary_engineer.md stub (system prompt için)
    rules_dir = tmp_path / "agents"
    rules_dir.mkdir()
    (rules_dir / "adversary_engineer.md").write_text(
        "# Adversary Engineer rules stub\n", encoding="utf-8"
    )

    # Memory
    memdir = tmp_path / "memory"
    (memdir / "adversary_engineer").mkdir(parents=True)
    (memdir / "shared" / "facts").mkdir(parents=True)
    (memdir / "shared" / "lessons").mkdir(parents=True)
    (memdir / "protocol").mkdir(parents=True)

    # Configs — adversarial_periods.yaml
    cfg_dir = tmp_path / "configs"
    cfg_dir.mkdir()
    (cfg_dir / "adversarial_periods.yaml").write_text(
        """
stress_periods:
  covid_2020_03:
    name: "COVID Crash"
    start: "2020-03-08"
    end: "2020-03-23"
    description: "BTC -50%"
    severity: extreme
  luna_2022_05:
    name: "LUNA Collapse"
    start: "2022-05-07"
    end: "2022-05-15"
    description: "UST depeg"
    severity: extreme
  ftx_2022_11:
    name: "FTX Collapse"
    start: "2022-11-06"
    end: "2022-11-15"
    description: "Contagion"
    severity: extreme
  btc_ath_2024_03:
    name: "BTC ATH 2024"
    start: "2024-03-10"
    end: "2024-03-20"
    description: "Leverage flush"
    severity: high
  yen_carry_2024_08:
    name: "Yen Carry Unwind"
    start: "2024-08-04"
    end: "2024-08-08"
    description: "Yen +12%"
    severity: high

adversarial_thresholds:
  max_drawdown_pct_per_period: 0.20
  max_consecutive_losses: 5
  min_recovery_days_acceptable: 30
  min_n_trades_per_period: 3
  min_win_rate_per_period: 0.20

pre_deploy_kill_probes:
  in_oos_sharpe_spread_max_pct: 0.30
  min_unique_trades: 100
  max_param_extremeness_pct: 0.20
  min_regime_pass_count: 2
  max_param_count_per_trade: 0.10

readiness_scoring:
  per_period_pass_points: 20
  fast_recovery_bonus: 5
  kill_probe_baseline: 10
  concave_curve_penalty: -10
  critical_threshold: 60
  medium_threshold: 80
""",
        encoding="utf-8",
    )

    # Reports dir
    (tmp_path / "reports" / "adversary").mkdir(parents=True)

    # Override settings
    monkeypatch.setenv("PA_LLM_DRY_RUN", "true")
    from price_action import settings as _settings_mod
    _settings_mod.get_settings.cache_clear()
    monkeypatch.setattr(_settings_mod, "ROOT_DIR", tmp_path)

    return {"rules_dir": rules_dir, "memdir": memdir, "cfg_dir": cfg_dir, "root": tmp_path}


def _make_agent(env: dict) -> AdversaryEngineerAgent:
    store = MemoryStore(base_dir=env["memdir"])
    return AdversaryEngineerAgent(memory_store=store)


def _trade(ts_iso: str, pnl_pct: float) -> dict:
    return {"ts": ts_iso, "pnl_pct": pnl_pct}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_stress_period_load(env: dict) -> None:
    """configs/adversarial_periods.yaml yüklenir, 5 period var."""
    agent = _make_agent(env)
    cfg = agent._load_periods_config()
    assert "stress_periods" in cfg
    periods = cfg["stress_periods"]
    assert len(periods) == 5
    # Beklenen ID'ler
    assert "covid_2020_03" in periods
    assert "luna_2022_05" in periods
    assert "ftx_2022_11" in periods
    assert "btc_ath_2024_03" in periods
    assert "yen_carry_2024_08" in periods
    # Her period start/end alanına sahip
    for pid, pdata in periods.items():
        assert "start" in pdata, f"{pid} missing start"
        assert "end" in pdata, f"{pid} missing end"
        assert "severity" in pdata, f"{pid} missing severity"


def test_replay_returns_metrics(env: dict) -> None:
    """Mock pool ile replay — DD / recovery / win_rate hesabı kontrol."""
    agent = _make_agent(env)
    # LUNA period: 2022-05-07 → 2022-05-15
    # Simüle: 5 loss + 3 win, ardından recovery
    pool = [
        _trade("2022-05-08T01:00:00", -0.02),  # -2%
        _trade("2022-05-09T02:00:00", -0.03),  # -3%  (cum -5)
        _trade("2022-05-09T18:00:00", -0.04),  # -4%  (cum -9) ← worst
        _trade("2022-05-10T05:00:00", +0.02),  # +2%
        _trade("2022-05-11T05:00:00", +0.03),  # +3%
        _trade("2022-05-12T05:00:00", +0.05),  # +5%  (cum +1) — recovered
        _trade("2022-05-13T05:00:00", +0.01),  # +1%
    ]
    res = agent._replay_stress_period(
        strategy="phoenix_scalp_5m_p1c",
        period_dates=("2022-05-07", "2022-05-15"),
        params={},
        pool=pool,
    )
    assert res["status"] == "ok"
    assert res["n_trades"] == 7
    # 4 win (+2,+3,+5,+1) / 7 = ~0.5714
    assert abs(res["win_rate"] - 4 / 7) < 1e-4
    # Worst DD: peak 0, trough -0.09 → DD 0.09
    assert abs(res["worst_dd_pct"] - 0.09) < 1e-4
    # Recovery beklenir (positive recovery_days)
    assert res["recovery_days"] is not None
    assert res["recovery_days"] > 0
    # Final return cum sum: -2-3-4+2+3+5+1 = 0.02
    assert abs(res["final_return_pct"] - 0.02) < 1e-4


def test_replay_no_trades_window(env: dict) -> None:
    """Boş pool → status no_pool_data."""
    agent = _make_agent(env)
    res = agent._replay_stress_period(
        strategy="phoenix_scalp_5m_p1c",
        period_dates=("2022-05-07", "2022-05-15"),
        params={},
        pool=[],
    )
    assert res["status"] == "no_pool_data"
    assert res["n_trades"] == 0


def test_kill_probe_in_oos_spread(env: dict) -> None:
    """IS Sharpe 2.0 OOS 0.8 → spread = 0.6 > 0.30 → FAIL."""
    agent = _make_agent(env)
    metrics = {
        "is_sharpe": 2.0,
        "oos_sharpe": 0.8,
        "n_unique_trades": 500,
        "param_extremeness_pct": 0.10,
        "n_regimes_passed": 3,
        "n_params": 5,
    }
    res = agent.kill_probe(metrics=metrics)
    assert not res["passed"]
    assert any("overfit_is_oos_spread" in f for f in res["fails"])
    assert res["checks"]["in_oos_sharpe_spread"] is False
    # Diğer gate'ler geçmeli
    assert res["checks"]["min_unique_trades"] is True
    assert res["checks"]["param_extremeness"] is True


def test_kill_probe_extreme_params(env: dict) -> None:
    """Param grid ucundan (extremeness 0.30 > 0.20 threshold) → FAIL."""
    agent = _make_agent(env)
    metrics = {
        "is_sharpe": 1.5,
        "oos_sharpe": 1.4,           # spread küçük
        "n_unique_trades": 500,
        "param_extremeness_pct": 0.30,  # ← FAIL
        "n_regimes_passed": 3,
        "n_params": 5,
    }
    res = agent.kill_probe(metrics=metrics)
    assert not res["passed"]
    assert any("cherry_pick_grid_edge" in f for f in res["fails"])
    assert res["checks"]["param_extremeness"] is False


def test_kill_probe_min_trades(env: dict) -> None:
    """n=50 fail, n=500 pass."""
    agent = _make_agent(env)
    base_metrics = {
        "is_sharpe": 1.5,
        "oos_sharpe": 1.4,
        "param_extremeness_pct": 0.10,
        "n_regimes_passed": 3,
        "n_params": 5,
    }
    # n=50 → fail
    fail_res = agent.kill_probe(metrics={**base_metrics, "n_unique_trades": 50})
    assert not fail_res["passed"]
    assert any("sample_too_small" in f for f in fail_res["fails"])

    # n=500 → tüm gate'ler geçer
    pass_res = agent.kill_probe(metrics={**base_metrics, "n_unique_trades": 500})
    assert pass_res["passed"], f"expected pass, got fails={pass_res['fails']}"
    assert all(v is not False for v in pass_res["checks"].values() if v is not None)


def test_flash_crash_generator(env: dict) -> None:
    """generate_flash_crash deterministik shape check."""
    from scripts.adversarial_data_gen import _synth_base, generate_flash_crash

    base = _synth_base(symbol="BTC/USDT", timeframe="5m", n=300, seed=42)
    out = generate_flash_crash(
        base,
        drop_pct=0.15,
        recovery_bars=20,
        crash_idx=100,
        seed=7,
    )
    # Aynı bar sayısı, aynı kolonlar
    assert len(out) == len(base)
    for col in ["ts", "open", "high", "low", "close", "volume", "scenario"]:
        assert col in out.columns

    # Crash bar close pre_close'a göre ~%15 düşük olmalı
    pre_close = float(base.loc[99, "close"])
    crash_close = float(out.loc[100, "close"])
    actual_drop = (pre_close - crash_close) / pre_close
    assert abs(actual_drop - 0.15) < 0.02, (
        f"flash crash drop sapması: pre={pre_close} crash={crash_close} drop={actual_drop}"
    )

    # Recovery: crash + recovery_bars sonrasında pre_close'a yakın
    end_idx = 100 + 20
    recovered_close = float(out.loc[end_idx, "close"])
    recovery_gap = abs(recovered_close - pre_close) / pre_close
    assert recovery_gap < 0.02, (
        f"V-recovery yakınsamamış: pre={pre_close} recov={recovered_close} gap={recovery_gap}"
    )

    # Crash bar scenario etiketi güncellenmiş olmalı
    scen = str(out.loc[100, "scenario"])
    assert "flash_crash" in scen

    # OHLC sanity: high >= max(open, close), low <= min(open, close)
    for i in range(len(out)):
        h, l = float(out.loc[i, "high"]), float(out.loc[i, "low"])
        o, c = float(out.loc[i, "open"]), float(out.loc[i, "close"])
        assert h + 1e-6 >= max(o, c), f"bar {i} high {h} < max(o,c)"
        assert l - 1e-6 <= min(o, c), f"bar {i} low {l} > min(o,c)"


def test_readiness_score_pass(env: dict) -> None:
    """Tüm period passes_dd_gate + passes_recovery_gate → 100 (cap)."""
    agent = _make_agent(env)
    cfg = agent._load_periods_config()
    scoring = cfg.get("readiness_scoring", {})
    # 5 period × 20 = 100 + bonus 5 = 105 → cap 100
    results = [
        {
            "passes_dd_gate": True,
            "passes_recovery_gate": True,
            "recovery_days": 10,
            "concave": False,
        }
        for _ in range(5)
    ]
    score = agent._compute_readiness_score(
        results, kill_probe_passed=True, scoring=scoring
    )
    # 5*20 + 5*5 + 10 baseline = 135 → cap 100
    assert score == 100


def test_readiness_score_concave_penalty(env: dict) -> None:
    """Concave curve penalty -10 uygulanır."""
    agent = _make_agent(env)
    cfg = agent._load_periods_config()
    scoring = cfg.get("readiness_scoring", {})
    # 3 period pass, 2 concave fail
    results = [
        {"passes_dd_gate": True, "passes_recovery_gate": True,
         "recovery_days": 60, "concave": False},
        {"passes_dd_gate": True, "passes_recovery_gate": True,
         "recovery_days": 60, "concave": False},
        {"passes_dd_gate": True, "passes_recovery_gate": True,
         "recovery_days": 60, "concave": False},
        {"passes_dd_gate": False, "passes_recovery_gate": False,
         "recovery_days": 100, "concave": True},
        {"passes_dd_gate": False, "passes_recovery_gate": False,
         "recovery_days": 100, "concave": True},
    ]
    # 3*20 + 0 fast_rec (recovery > 30 hep) + 0 baseline (kill probe none)
    # - 2*10 concave = 60 - 20 = 40
    score = agent._compute_readiness_score(
        results, kill_probe_passed=False, scoring=scoring
    )
    assert score == 40
    # CRIT threshold 60 → label CRIT
    crit_thr = float(scoring["critical_threshold"])
    assert score < crit_thr


def test_extract_metrics_from_doc(env: dict) -> None:
    """Doc body regex parser çalışır."""
    agent = _make_agent(env)
    body = """
    # Tournament Candidate XYZ

    ## Metrics
    - in_sample sharpe: 2.4
    - oos sharpe = 0.9
    - n_unique_trades: 75
    - param_extremeness_pct: 0.35
    - regimes_passed: 1
    - n_params: 8
    """
    m = agent._extract_metrics_from_doc(body)
    assert m["is_sharpe"] == 2.4
    assert m["oos_sharpe"] == 0.9
    assert m["n_unique_trades"] == 75
    assert m["param_extremeness_pct"] == 0.35
    assert m["n_regimes_passed"] == 1
    assert m["n_params"] == 8

    # kill_probe = body verirse çoklu fail
    res = agent.kill_probe(candidate_doc_body=body)
    assert not res["passed"]
    # En az 3 fail beklenir (spread + min_trades + extremeness)
    assert len(res["fails"]) >= 3


def test_daily_stress_test_writes_doc(env: dict) -> None:
    """daily_stress_test path döner, dosya yazılır, frontmatter geçerli."""
    agent = _make_agent(env)
    pool = [
        _trade("2022-05-08T01:00:00", -0.01),
        _trade("2022-05-09T02:00:00", +0.02),
        _trade("2020-03-10T05:00:00", -0.05),  # COVID
        _trade("2020-03-12T05:00:00", -0.03),
        _trade("2020-03-18T05:00:00", +0.04),
    ]
    path = asyncio.run(agent.daily_stress_test("5m_p1c", pool=pool))
    assert path is not None
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    # Frontmatter mevcut
    assert content.startswith("---")
    assert "doc_type: adversarial_test" in content
    assert "agent_id: adversary_engineer" in content
    # Body içinde periodlar
    assert "covid_2020_03" in content
    assert "luna_2022_05" in content
    # Verdict bölümü
    assert "Red Team Verdict" in content
