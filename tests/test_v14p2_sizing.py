"""FAZ-2 (v14p2) sizing testleri — strateji risk ağırlığı + DD-throttle.

Backtest paritesi: lab.py `trade_risk_pct *= risk_weight` (cap öncesi) ve
dynamic_exposure_fn throttle deseni. Bu testler logic-mirror DEĞİL — gerçek
RiskOfficer kodunu çağırır (_dd_throttle_multiplier) ve kaynak doğrular.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from price_action.risk.regime_filter import _pattern_to_strategy


class TestPatternToStrategyForWeights:
    """Ağırlık anahtarları pattern_id eşlemesinden geçer — eşleme sağlam mı."""

    @pytest.mark.parametrize("pattern_id,expected", [
        ("vsa_climax_test_sc_long", "vsa_climax_test"),
        ("brooks_failed_breakout_bull_trap", "brooks_failed_breakout"),
        ("avwap_long_reversal", "anchored_vwap_reversal"),
        ("avwap_short_reversal", "anchored_vwap_reversal"),
        ("engulfing_bull", "engulfing_continuation"),
        ("bilinmeyen_pattern", None),
    ])
    def test_mapping(self, pattern_id, expected):
        assert _pattern_to_strategy(pattern_id) == expected


class _ThrottleHost:
    """_dd_throttle_multiplier'ı RiskOfficer'sız çağırmak için ince host."""

    def __init__(self):
        from price_action.risk.sizing import RiskOfficer
        self._fn = RiskOfficer._dd_throttle_multiplier

    def call(self, equity, cfg):
        return self._fn(self, equity, cfg)


class TestDDThrottle:
    def _cfg(self, tmp_path, thr=0.06, mult=0.5):
        return {
            "enabled": True,
            "dd_threshold": thr,
            "risk_mult": mult,
            "state_path": str(tmp_path / "peak.json"),
        }

    def test_no_drawdown_full_risk(self, tmp_path):
        h = _ThrottleHost()
        cfg = self._cfg(tmp_path)
        assert h.call(10_000.0, cfg) == 1.0

    def test_peak_ratchets_up_and_persists(self, tmp_path):
        h = _ThrottleHost()
        cfg = self._cfg(tmp_path)
        h.call(10_000.0, cfg)
        h.call(12_000.0, cfg)  # yeni peak
        state = json.loads(Path(cfg["state_path"]).read_text())
        assert state["peak"] == 12_000.0
        h.call(11_500.0, cfg)  # düşüş peak'i AŞAĞI çekmez
        assert json.loads(Path(cfg["state_path"]).read_text())["peak"] == 12_000.0

    def test_throttle_activates_at_threshold(self, tmp_path):
        h = _ThrottleHost()
        cfg = self._cfg(tmp_path, thr=0.06, mult=0.5)
        h.call(10_000.0, cfg)             # peak=10k
        assert h.call(9_500.0, cfg) == 1.0   # dd %5 < %6 → tam risk
        assert h.call(9_400.0, cfg) == 0.5   # dd %6 → kısıldı
        assert h.call(8_000.0, cfg) == 0.5   # daha derin → hâlâ kısık

    def test_recovery_restores_full_risk(self, tmp_path):
        h = _ThrottleHost()
        cfg = self._cfg(tmp_path)
        h.call(10_000.0, cfg)
        assert h.call(9_000.0, cfg) == 0.5
        assert h.call(9_800.0, cfg) == 1.0  # dd %2'ye toparladı

    def test_corrupt_state_fail_open(self, tmp_path):
        h = _ThrottleHost()
        cfg = self._cfg(tmp_path)
        Path(cfg["state_path"]).parent.mkdir(parents=True, exist_ok=True)
        Path(cfg["state_path"]).write_text("BOZUK{{{")
        assert h.call(10_000.0, cfg) == 1.0  # bozuk state → equity'den başla, no-op

    def test_zero_equity_noop(self, tmp_path):
        h = _ThrottleHost()
        assert h.call(0.0, self._cfg(tmp_path)) == 1.0


class TestSizingSourceWiring:
    """evaluate() yolunda ağırlık + throttle bloklarının varlığı (revert tespiti)."""

    def test_source_has_phase2_blocks(self):
        src = (Path(__file__).resolve().parents[1]
               / "src" / "price_action" / "risk" / "sizing.py").read_text(encoding="utf-8")
        assert "strategy_risk_weights" in src
        assert "_dd_throttle_multiplier" in src
        assert "dd_throttle" in src
        # ağırlık cap'lerden ÖNCE: risk_pct çarpımı method satırından önce gelmeli
        i_w = src.index("strategy_risk_weights")
        i_m = src.index('method = str(cfg.position_sizing.get("method"')
        assert i_w < i_m, "ağırlık bloğu sizing method'dan önce uygulanmalı (cap paritesi)"
