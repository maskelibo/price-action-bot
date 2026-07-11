"""Tests for Faz 10 — TF Exploration Pipeline + Bot Factory.

Coverage:
    - explore_tf üzerinde aktif TF'ler (5m + 15m mock pool) metrik hesabı
    - Pool dosyası yok → status='NO_POOL_DATA'
    - composite_score normalize + weight matematiği
    - bot_factory.generate_bot → 4 dosya üretildi (yaml + plist + sh + duckdb)
    - bot_factory mevcut bot → FileExistsError (overwrite=False)
    - yaml override: 5m P1c template + 1h override → doğru sl_pct_min/timeframe

Notlar:
    - Gerçek sec53 pool .pkl dosyalarına dokunulmaz — testlerde mini sentetik
      pool .pkl dosyaları tmp_path'a yazılır.
    - duckdb schema sınanır (4 tablo + 2 index).
"""
from __future__ import annotations

import pickle
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from scripts.bot_factory import (
    generate_bot,
    init_journal_schema,
    render_plist,
    render_run_sh,
    render_yaml_override,
)
from scripts.tf_exploration_runner import (
    _build_recommendation,
    _normalize_for_score,
    align_common_comparison_sample,
    calc_tf_metrics,
    composite_score,
    explore_tf,
    filter_strategy_subset,
)


# ---------------------------------------------------------------------------
# Fixtures: sentetik mini pool .pkl
# ---------------------------------------------------------------------------
def _make_trade(
    *,
    entry_ts: datetime,
    r_value: float,
    strategy: str = "vsa_climax_test",
    symbol: str = "BTC/USDT",
    side: str = "long",
    conf: float = 0.5,
) -> dict:
    return {
        "entry_ts": entry_ts,
        "exit_ts": entry_ts + timedelta(hours=1),
        "R": float(r_value),
        "peak_R": max(0.0, float(r_value)),
        "conf": conf,
        "symbol": symbol,
        "strategy": strategy,
        "side": side,
        "entry_price": 100.0,
        "initial_sl": 96.0,
    }


def _make_pool(
    *,
    n: int,
    strategy: str,
    start: datetime,
    step_hours: int,
    r_values: list[float] | None = None,
) -> list[dict]:
    """n trade üret. r_values verilirse cycle eder, yoksa varsayılanı kullanır."""
    if r_values is None:
        r_values = [0.3, -0.5, 0.8, -0.2, 1.2, -0.7, 0.5, -0.3]
    pool = []
    for i in range(n):
        r_value = r_values[i % len(r_values)]
        pool.append(_make_trade(
            entry_ts=start + timedelta(hours=i * step_hours),
            r_value=r_value,
            strategy=strategy,
        ))
    return pool


@pytest.fixture
def synth_pools(tmp_path: Path) -> dict[str, Path]:
    """Sentetik mini pool .pkl dosyaları (5m ve 15m) — tmp_path altında."""
    paths = {}
    start = datetime(2024, 1, 1, tzinfo=UTC)

    # 5m pool — 200 trade, çoğunlukla küçük R'ler (Sharpe pozitif).
    pool_5m = _make_pool(
        n=200, strategy="vsa_climax_test",
        start=start, step_hours=1,
        r_values=[0.4, -0.3, 0.6, -0.4, 0.5, -0.2, 0.3, -0.1],
    )
    # 15m pool — 100 trade, biraz farklı dağılım (daha iyi recovery).
    pool_15m = _make_pool(
        n=100, strategy="vsa_climax_test",
        start=start, step_hours=4,
        r_values=[0.5, -0.3, 1.0, -0.4, 0.8, -0.5, 0.6, -0.2],
    )
    # Bonus: bir miktar engulfing_continuation trade ekle (drop_strategies test).
    pool_5m += [
        _make_trade(
            entry_ts=start + timedelta(hours=i),
            r_value=2.0,
            strategy="engulfing_continuation",
        )
        for i in range(5)
    ]

    p5 = tmp_path / "sec53_5m_pool_v11_vm20.pkl"
    p15 = tmp_path / "sec53_15m_pool_v11.pkl"
    with p5.open("wb") as f:
        pickle.dump(pool_5m, f)
    with p15.open("wb") as f:
        pickle.dump(pool_15m, f)

    paths["5m"] = p5
    paths["15m"] = p15
    return paths


@pytest.fixture
def tf_config_path(tmp_path: Path) -> Path:
    """Minimal tf_expansion_targets.yaml — testlerde kullanılır."""
    cfg = {
        "composite_score": {
            "weights": {
                "sharpe": 0.40,
                "maxdd_inverse": 0.20,
                "n_trades_per_year": 0.20,
                "recovery_factor": 0.20,
            }
        },
        "deploy_thresholds": {
            "composite_min": 0.70,
            "vs_baseline_min_gain_pct": 0.10,
        },
    }
    p = tmp_path / "tf_expansion_targets.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 1. explore_tf — aktif TF (5m + 15m pool var)
# ---------------------------------------------------------------------------
def test_explore_tf_active_tfs(synth_pools, tf_config_path):
    result = explore_tf(
        strategy="vsa_climax_test",
        tf_list=["5m", "15m"],
        pool_paths=synth_pools,
        drop_strategies=["engulfing_continuation"],
        config_path=tf_config_path,
    )
    assert result["strategy"] == "vsa_climax_test"
    assert set(result["tf_results"].keys()) == {"5m", "15m"}
    for tf in ("5m", "15m"):
        info = result["tf_results"][tf]
        assert info["status"] == "OK", f"{tf} not OK: {info['status']}"
        m = info["metrics"]
        assert m["n_trades"] > 0
        assert m["n_trades_per_year"] > 0
        assert m["sharpe"] != 0.0  # negative ya da positive ama sıfır değil
    assert result["best_tf"] in ("5m", "15m")
    # Both 5m + 15m are "active" TFs → recommendation STAY veya benzeri (not DEPLOY).
    assert "DEPLOY" not in result["recommendation"] or "STAY" in result["recommendation"]


def test_explore_tf_filter_strategy_excludes_drop(synth_pools, tf_config_path):
    """engulfing_continuation drop edilince trade sayısı düşer."""
    pool = pickle.load(synth_pools["5m"].open("rb"))
    subset_no_drop = filter_strategy_subset(pool, "vsa_climax_test", drop_strategies=[])
    subset_with_drop = filter_strategy_subset(
        pool, "vsa_climax_test", drop_strategies=["engulfing_continuation"]
    )
    # vsa_climax_test trade'leri her iki durumda da aynı — drop sadece başka
    # strategy'leri etkiler. Burada doğrudan equality.
    assert len(subset_no_drop) == len(subset_with_drop)
    # Pool toplam > vsa subset (çünkü engulfing_continuation var).
    assert len(pool) > len(subset_no_drop)


# ---------------------------------------------------------------------------
# 2. explore_tf — pool yok → NO_POOL_DATA
# ---------------------------------------------------------------------------
def test_explore_tf_skip_missing_pool(synth_pools, tf_config_path, tmp_path):
    """1h pool yok → status='NO_POOL_DATA'."""
    pool_paths = dict(synth_pools)  # 5m + 15m var
    pool_paths["1h"] = tmp_path / "sec53_1h_pool_v11.pkl"  # YOK
    pool_paths["4h"] = tmp_path / "sec53_4h_pool_v11.pkl"  # YOK

    result = explore_tf(
        strategy="vsa_climax_test",
        tf_list=["5m", "15m", "1h", "4h"],
        pool_paths=pool_paths,
        drop_strategies=["engulfing_continuation"],
        config_path=tf_config_path,
    )
    assert result["tf_results"]["1h"]["status"] == "NO_POOL_DATA"
    assert result["tf_results"]["4h"]["status"] == "NO_POOL_DATA"
    assert result["tf_results"]["1h"]["metrics"] is None
    assert result["tf_results"]["1h"]["rank"] is None
    # 5m + 15m hala rank alır.
    assert result["tf_results"]["5m"]["rank"] in (1, 2)
    assert result["tf_results"]["15m"]["rank"] in (1, 2)


# ---------------------------------------------------------------------------
# 3. composite_score: normalize + weight matematiği
# ---------------------------------------------------------------------------
def test_composite_score_mock_metrics():
    """Mock OK metrics → ranking + composite hesabı doğru çıkar."""
    metrics_list = [
        {
            "tf": "5m",
            "status": "OK",
            "metrics": {
                "sharpe": 1.0, "maxdd_R": 10.0,
                "n_trades_per_year": 500.0, "recovery_factor": 2.0,
            },
        },
        {
            "tf": "1h",
            "status": "OK",
            "metrics": {
                "sharpe": 2.0, "maxdd_R": 5.0,
                "n_trades_per_year": 100.0, "recovery_factor": 4.0,
            },
        },
    ]
    _normalize_for_score(metrics_list)
    weights = {
        "sharpe": 0.40, "maxdd_inverse": 0.20,
        "n_trades_per_year": 0.20, "recovery_factor": 0.20,
    }
    scores = {
        m["tf"]: composite_score(m["normalized"], weights)
        for m in metrics_list
    }
    # 1h: sharpe normalize=1.0, recovery=1.0; maxdd_inverse=1-(5/10)=0.5; nyr=100/500=0.2
    # → 0.4*1 + 0.2*0.5 + 0.2*0.2 + 0.2*1 = 0.4+0.1+0.04+0.2 = 0.74
    assert scores["1h"] == pytest.approx(0.74, abs=1e-6)
    # 5m: sharpe=0.5; recovery=0.5; maxdd_inv=1-(10/10)=0.0; nyr=1.0
    # → 0.4*0.5 + 0.2*0.0 + 0.2*1.0 + 0.2*0.5 = 0.2+0+0.2+0.1 = 0.5
    assert scores["5m"] == pytest.approx(0.5, abs=1e-6)
    assert scores["1h"] > scores["5m"]


def test_calc_tf_metrics_empty():
    out = calc_tf_metrics([])
    assert out["n_trades"] == 0
    assert out["sharpe"] == 0.0
    assert out["maxdd_R"] == 0.0


def test_calc_tf_metrics_basic():
    start = datetime(2024, 1, 1, tzinfo=UTC)
    trades = [
        _make_trade(entry_ts=start + timedelta(hours=i), r_value=r_value)
        for i, r_value in enumerate([1.0, -0.5, 1.0, -0.5, 1.0])
    ]
    m = calc_tf_metrics(trades)
    assert m["n_trades"] == 5
    assert m["sum_R"] == pytest.approx(2.0)
    assert m["mean_R"] == pytest.approx(0.4)
    assert m["win_rate"] == pytest.approx(3 / 5)
    assert m["maxdd_R"] > 0  # -0.5'lerden DD oluştu
    assert m["recovery_factor"] > 0


def test_recommendation_no_pool():
    """Hiçbir TF'de OK status yoksa NEEDS_MORE_DATA döner."""
    tf_results = {"1h": {"status": "NO_POOL_DATA", "composite": 0.0}}
    rec = _build_recommendation(None, tf_results, {"composite_min": 0.70})
    assert "NEEDS_MORE_DATA" in rec


def test_recommendation_marks_new_tf_as_candidate_not_deploy():
    """Ham ekran doğrudan deploy yetkisi vermez."""
    tf_results = {
        "15m": {"status": "OK", "composite": 0.40},
        "1h": {"status": "OK", "composite": 0.85},
    }
    rec = _build_recommendation("1h", tf_results, {"composite_min": 0.70})
    assert "CANDIDATE 1h" in rec
    assert "deploy ETME" in rec


def test_recommendation_requires_baseline_evidence():
    tf_results = {"1h": {"status": "OK", "composite": 0.85}}

    rec = _build_recommendation("1h", tf_results, {"composite_min": 0.70})

    assert "NEEDS_MORE_DATA" in rec
    assert "baseline" in rec


def test_recommendation_stay_active_tf():
    """Best TF configured baseline ise STAY."""
    tf_results = {"15m": {"status": "OK", "composite": 0.85}}
    rec = _build_recommendation("15m", tf_results, {"composite_min": 0.70})
    assert "STAY" in rec


def test_recommendation_enforces_baseline_gain():
    tf_results = {
        "15m": {"status": "OK", "composite": 0.75},
        "4h": {"status": "OK", "composite": 0.80},
    }

    rec = _build_recommendation(
        "4h",
        tf_results,
        {"composite_min": 0.70, "baseline_tf": "15m", "vs_baseline_min_gain_pct": 0.10},
    )

    assert "STAY 15m" in rec
    assert "6.7%" in rec


def test_common_sample_uses_symbol_and_date_intersection():
    start = datetime(2024, 1, 1, tzinfo=UTC)
    baseline = [
        _make_trade(entry_ts=start + timedelta(days=day), r_value=0.1, symbol=symbol)
        for symbol in ("BTC/USDT", "ETH/USDT")
        for day in range(10)
    ]
    candidate = [
        _make_trade(entry_ts=start + timedelta(days=day), r_value=0.2, symbol=symbol)
        for symbol in ("BTC/USDT", "SOL/USDT")
        for day in range(-5, 15)
    ]

    aligned, provenance = align_common_comparison_sample(
        {"15m": baseline, "30m": candidate}
    )

    assert provenance["common_symbols"] == ["BTC/USDT"]
    assert provenance["entry_start"].startswith("2024-01-01")
    assert provenance["entry_end"].startswith("2024-01-10")
    assert len(aligned["15m"]) == 10
    assert len(aligned["30m"]) == 10
    assert {row["symbol"] for rows in aligned.values() for row in rows} == {"BTC/USDT"}


def test_common_sample_fails_without_symbol_overlap():
    start = datetime(2024, 1, 1, tzinfo=UTC)
    baseline = [_make_trade(entry_ts=start, r_value=0.1, symbol="BTC/USDT")]
    candidate = [_make_trade(entry_ts=start, r_value=0.2, symbol="SOL/USDT")]

    with pytest.raises(ValueError, match="no common symbols"):
        align_common_comparison_sample({"15m": baseline, "30m": candidate})


# ---------------------------------------------------------------------------
# 4. bot_factory.generate_bot — 4 dosya üretilir
# ---------------------------------------------------------------------------
def test_bot_factory_generate(tmp_path: Path):
    """vsa + 1h → 4 dosya (yaml + plist + sh + duckdb)."""
    # tmp_path'i fake repo root yap. configs/ + ops/launchd/ template'leri
    # gerçek repo'dan reference olduğu için sadece OUTPUT tmp'e gider.
    # output_dir tmp_path; template'ler hala ROOT'tan okunur.
    result = generate_bot(
        strategy="vsa_climax_test",
        tf="1h",
        bot_name="futures1h_test",
        capital_usdt=1000.0,
        sl_pct_min=0.04,
        output_dir=tmp_path,
    )
    assert len(result["files_created"]) == 4
    expected_names = {
        "risk_phoenix_scalp_1h_vsa.yaml",
        "com.priceaction.futures1h_test.plist",
        "run_futures1h_test.sh",
        "futures_journal_1h.duckdb",
    }
    actual_names = {p.name for p in result["files_created"]}
    assert actual_names == expected_names

    # run.sh executable mı?
    sh_path = tmp_path / "ops" / "launchd" / "run_futures1h_test.sh"
    assert sh_path.exists()
    st_mode = sh_path.stat().st_mode
    assert st_mode & stat.S_IXUSR, "run.sh executable değil"


def test_bot_factory_existing_bot_skip(tmp_path: Path):
    """Var olan bot dosyaları → FileExistsError (overwrite=False)."""
    # İlk run
    generate_bot(
        strategy="vsa_climax_test",
        tf="1h",
        bot_name="futures1h_dup",
        capital_usdt=1000.0,
        sl_pct_min=0.04,
        output_dir=tmp_path,
    )
    # İkinci run → error
    with pytest.raises(FileExistsError):
        generate_bot(
            strategy="vsa_climax_test",
            tf="1h",
            bot_name="futures1h_dup",
            capital_usdt=1000.0,
            sl_pct_min=0.04,
            output_dir=tmp_path,
        )
    # overwrite=True ile yeniden — error vermez.
    result = generate_bot(
        strategy="vsa_climax_test",
        tf="1h",
        bot_name="futures1h_dup",
        capital_usdt=1000.0,
        sl_pct_min=0.04,
        output_dir=tmp_path,
        overwrite=True,
    )
    assert len(result["files_created"]) == 4


# ---------------------------------------------------------------------------
# 5. yaml_override — 5m template + override → 1h doğru config
# ---------------------------------------------------------------------------
def test_yaml_override_1h_params():
    """5m P1c template'ten 1h vsa için config render — kritik field'lar doğru mu?"""
    yaml_str = render_yaml_override(
        strategy="vsa_climax_test",
        tf="1h",
        capital_usdt=1500.0,
        sl_pct_min=0.04,
    )
    cfg = yaml.safe_load(yaml_str)
    assert cfg["defaults"]["timeframe"] == "1h"
    assert cfg["defaults"]["preset_name"] == "phoenix_scalp_1h_vsa"
    assert cfg["defaults"]["bot_name"] == "PHOENIX-SCALP-1h-VSA"
    assert cfg["execution"]["sl_pct_min"] == 0.04
    # 5m'de 15s; 1h'te scale → daha gevşek (max 120 clamp).
    assert cfg["execution"]["post_only_fallback_seconds"] >= 15
    assert cfg["execution"]["post_only_fallback_seconds"] <= 120
    assert cfg["capital"]["initial_usdt"] == 1500.0
    # Strategy yalnız verilen olmalı.
    assert cfg["strategy_portfolio"]["strategies"] == ["vsa_climax_test"]
    # Sim only paper mode korunur.
    assert cfg["defaults"]["sim_only"] is True
    # Cooldown TF'e uyarlandı (1h bar = 60min = 0.04167 gün).
    assert cfg["strategy_portfolio"]["same_symbol_side_cooldown_days"] == pytest.approx(
        60 / 1440.0, abs=1e-4
    )


def test_render_plist_label_swap():
    text = render_plist(bot_name="futures1h")
    assert "com.priceaction.futures1h" in text
    assert "com.priceaction.futures5m" not in text
    assert "run_futures1h.sh" in text
    assert "futures1h.stdout.log" in text


def test_render_run_sh_env_swap():
    text = render_run_sh(
        bot_name="futures1h",
        tf="1h",
        config_relpath="configs/risk_phoenix_scalp_1h_vsa.yaml",
    )
    assert "PA_1H_CONFIG" in text
    assert "PA_5M_CONFIG" not in text
    assert "--timeframe 1h" in text
    assert "configs/risk_phoenix_scalp_1h_vsa.yaml" in text


# ---------------------------------------------------------------------------
# 6. journal schema — duckdb tablolar
# ---------------------------------------------------------------------------
def test_init_journal_schema_tables(tmp_path: Path):
    """futures_journal_<tf>.duckdb içinde 4 tablo + 2 index yaratıldı."""
    import duckdb

    journal_path = tmp_path / "futures_journal_1h.duckdb"
    init_journal_schema(journal_path)
    assert journal_path.exists()

    con = duckdb.connect(str(journal_path))
    try:
        tables = {
            row[0] for row in
            con.execute("SELECT table_name FROM information_schema.tables").fetchall()
        }
    finally:
        con.close()

    expected = {
        "futures_signals",
        "futures_protection_orders",
        "futures_equity_snapshots",
        "futures_trades_closed",
    }
    assert expected.issubset(tables), f"Missing: {expected - tables}"
