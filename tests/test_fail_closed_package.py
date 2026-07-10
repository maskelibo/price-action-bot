"""Fail-closed paketi — 8 karar-kaleminin kapanışı (2026-07-10, Principal onayı).

Ortak ilke: hata/eksik-config anında bot artık SESSİZCE RİSKLİ tarafa düşmez;
güvenli tarafa düşer + görünür log. Her fix'in parite kalkanı: mevcut canlı
config (anahtarlar TAM) altında davranış BYTE-AYNI.

#1 p1c: bozuk release_at → halt KORUNUR (eski: sessizce düşerdi = risk-halt fail-open)
#2 sl_pct_min: anahtar YOK → 1.0 hepsi-reddet (eski: 0.0 = fee-kalkanı kapanırdı)
#3 breaker: bozuk state → 24h süreli halt (eski: sıfırla = tripped halt kaybolurdu)
#4 DMS: init-fail → SystemExit (eski: switch'siz devam; DR9 alarmı haber verir)
#5 kaldıraç: _LEV_HARD_CAP tek mutlak tavan + yaml tutarlılık uyarısı
#6 breaker_monitor: arşivlendi (ikinci kill-switch yazarı / split-brain)
#7 pyramid: anahtar YOK/okunamaz → False (eski: True = sessiz pyramid açılışı)
#8 boş-dönüş deseni: tasarım mini-projesi — KALAN_ISLER defterinde (kapsam dışı)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


# ---------------------------------------------------------------------------
# #3 Breaker: bozuk state → 24h süreli halt
# ---------------------------------------------------------------------------


def test_breaker_corrupt_state_fails_closed(tmp_path):
    from price_action.risk.breaker import DDBreaker

    bad = tmp_path / "breaker_state.json"
    bad.write_text("{bozuk json!!", encoding="utf-8")
    br = DDBreaker({}, state_path=bad)
    # Eski davranış: tertemiz state (halt kaybı). Yeni: combined-halt 24h.
    assert br.state.triggered_daily is True
    assert br.state.blocked_combined_until != ""


def test_breaker_missing_state_still_fresh(tmp_path):
    """Parite: dosya YOKSA (ilk koşu) eskisi gibi temiz state — halt YOK."""
    from price_action.risk.breaker import DDBreaker

    br = DDBreaker({}, state_path=tmp_path / "yok.json")
    assert br.state.triggered_daily is False
    assert br.state.blocked_combined_until == ""


def test_breaker_valid_state_loads_normally(tmp_path):
    """Parite: geçerli state aynen yüklenir (fail-closed tetiklenmez)."""
    from price_action.risk.breaker import DDBreaker

    good = tmp_path / "s.json"
    good.write_text(json.dumps({"daily_pnl": -12.5, "consecutive_losses": 2}), encoding="utf-8")
    br = DDBreaker({}, state_path=good)
    assert br.state.daily_pnl == -12.5
    assert br.state.triggered_daily is False


# ---------------------------------------------------------------------------
# #1 p1c: bozuk release_at → halt KORUNUR
# ---------------------------------------------------------------------------


def _p1c_walker(tmp_path, monkeypatch, halts):
    import price_action.execution.p1c_walker as pw

    state_file = tmp_path / "p1c_state.json"
    monkeypatch.setattr(pw, "_STATE_FILE", state_file, raising=False)
    monkeypatch.setattr(pw, "_STATE_DIR", tmp_path, raising=False)
    state_file.write_text(json.dumps({"halts": halts}), encoding="utf-8")
    return pw


def test_p1c_corrupt_release_keeps_halt(tmp_path, monkeypatch):
    pw = _p1c_walker(
        tmp_path,
        monkeypatch,
        [
            {"reason": "3_loss_halt", "release_at": "BOZUK-TARİH", "added_at": "x"},
        ],
    )
    w = pw.P1cWalker.__new__(pw.P1cWalker)
    w.config = pw.P1cConfig()
    w._state = {
        "equity_usdt": 10_000.0,
        "halts": [{"reason": "3_loss_halt", "release_at": "BOZUK-TARİH"}],
    }
    # check_halts bozuk kaydı artık AKTİF sayar (eski: sessizce düşürürdü)
    monkeypatch.setattr(w, "_save_state", lambda *a, **k: None, raising=False)
    result = w.check_halts()
    assert len(w._state["halts"]) == 1  # halt DÜŞMEDİ
    # dönüş sözlüğünde halted işareti (API'ye göre esnek assert)
    assert result is not None


def test_p1c_valid_future_halt_still_active(tmp_path, monkeypatch):
    """Parite: geçerli gelecek-tarihli halt aynen aktif."""
    from datetime import UTC, datetime, timedelta

    pw = _p1c_walker(tmp_path, monkeypatch, [])
    w = pw.P1cWalker.__new__(pw.P1cWalker)
    w.config = pw.P1cConfig()
    future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    w._state = {"equity_usdt": 10_000.0, "halts": [{"reason": "t", "release_at": future}]}
    monkeypatch.setattr(w, "_save_state", lambda *a, **k: None, raising=False)
    w.check_halts()
    assert len(w._state["halts"]) == 1


def test_p1c_expired_halt_still_removed(tmp_path, monkeypatch):
    """Parite: geçerli GEÇMİŞ-tarihli halt eskisi gibi temizlenir."""
    from datetime import UTC, datetime, timedelta

    pw = _p1c_walker(tmp_path, monkeypatch, [])
    w = pw.P1cWalker.__new__(pw.P1cWalker)
    w.config = pw.P1cConfig()
    past = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    w._state = {"equity_usdt": 10_000.0, "halts": [{"reason": "t", "release_at": past}]}
    monkeypatch.setattr(w, "_save_state", lambda *a, **k: None, raising=False)
    w.check_halts()
    assert len(w._state["halts"]) == 0


# ---------------------------------------------------------------------------
# #4 DMS: init-fail → SystemExit (1d yolu çağrılabilir; 15m kaynak-pin)
# ---------------------------------------------------------------------------


def test_dms_init_fail_raises_system_exit(monkeypatch):
    import scripts.futures_daemon as fd

    class _Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("dms kurulamadı")

    import price_action.execution.dead_mans_switch as dmsmod

    monkeypatch.setattr(dmsmod, "DeadMansSwitch", _Boom)
    with pytest.raises(SystemExit):
        fd._init_dead_mans_switch(object())


# ---------------------------------------------------------------------------
# #5/#7/#2/#4-15m/#6: kaynak-pin + parite kanıtları
# ---------------------------------------------------------------------------


def test_source_pins_fail_closed_package():
    src = (ROOT / "scripts" / "futures_daemon.py").read_text(encoding="utf-8")
    # #7 pyramid fail-closed
    assert "PYRAMID_KEY_MISSING" in src
    assert "PYRAMID_CFG_FAIL" in src
    assert '_cfg.get("strategy_portfolio", {}).get("pyramid_enabled", True)' not in src
    # #2 sl anahtar-eksik fail-closed
    assert "15M_WIDESTOP_KEY_MISSING" in src
    assert '.get("sl_pct_min", 0.0)' not in src
    # #4 15m DMS fatal
    assert "15M_DMS_INIT_FATAL" in src
    assert "devam ediliyor (DMS devre dışı)" not in src  # 3 init-sitesi de fatal
    # #5 kaldıraç hard-cap sabiti + eski hardcode gitti
    assert "_LEV_HARD_CAP = 3" in src
    assert "LEV_CAP_MISMATCH" in src
    assert "min(3, int(round(_decision.leverage))" not in src


def test_live_config_parity_no_fail_closed_triggers():
    """PARİTE KALKANI: canlı v15p2 config'inde TÜM anahtarlar mevcut →
    hiçbir fail-closed yolu tetiklenmez, davranış deploy-öncesiyle aynı."""
    import yaml

    cfg = yaml.safe_load(
        (ROOT / "configs" / "risk_phoenix_scalp_15m_v15p2.yaml").read_text(encoding="utf-8")
    )
    assert cfg["execution"]["sl_pct_min"] == 0.025  # #2 anahtar VAR
    assert cfg["strategy_portfolio"]["pyramid_enabled"] is False  # #7 anahtar VAR
    assert int(cfg["leverage"]["max_leverage_per_symbol"]) == 3  # #5 yaml == hard-cap


def test_breaker_monitor_archived():
    """#6: ikinci kill-switch yazarı arşivde; canlı yolda import edilmiyor."""
    assert not (ROOT / "scripts" / "breaker_monitor.py").exists()
    assert (ROOT / "scripts" / "_archive" / "breaker_monitor_ARCHIVED_20260710.py").exists()


def test_p1c_source_pins():
    src = (ROOT / "src" / "price_action" / "execution" / "p1c_walker.py").read_text(
        encoding="utf-8"
    )
    assert "halt_release_parse_fail_KEPT" in src
    assert "3loss_halt_calc_fail" in src
    assert "state_bak_copy_fail" in src
