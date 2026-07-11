"""A1-04 korelasyon-gate körlüğü — kapanış sprinti 2026-07-10 (dalga-5 HIGH).

Daemon returns_df matrisini YALNIZ o barda sinyal üreten sembollerle kuruyordu;
açık pozisyon sembolü matriste yoksa eski correlation_gate fail-open dönüyordu =
yeni sinyal, mevcut pozisyonlarla korelasyonu HİÇ ölçülmeden geçiyordu. Güncel
gate bu savunma hattı kaçırılsa bile eksik sembolü fail-closed reddeder
(daemon-özel körlük; script yolu tüm-evrenle doğru çalışıyor).

Fix: _corr_matrix_syms saf fonksiyonu (evren ∪ sinyal) + döngü-içi
pozisyon-sembolü rebuild (UNI-cut emsali: evrenden çıkarılmış sembolde açık
pozisyon) + kalıcı KÖRLÜK logu.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import scripts.futures_daemon as fd  # noqa: E402


def test_open_position_symbol_included_without_signal():
    """ÇEKİRDEK VAKA: ETH sinyal üretmedi ama evren üyesi (açık pozisyon
    olabilir) → matriste OLMALI. Eski kod: yalnız BTC olurdu → gate ETH'ye kör."""
    signals = [{"symbol": "BTC/USDT"}]
    universe = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    result = fd._corr_matrix_syms(signals, universe)
    assert set(result) == {"BTC/USDT", "ETH/USDT", "SOL/USDT"}


def test_empty_signals_empty_list():
    """Sinyal yoksa döngü koşmaz — boşuna DB sorgusu yok."""
    assert fd._corr_matrix_syms([], ["BTC/USDT", "ETH/USDT"]) == []


def test_sorted_deterministic_for_cache_key():
    """build_returns_df TTL-cache anahtarı sorted-symbols — stabilite = cache hit."""
    sig = [{"symbol": "SOL/USDT"}, {"symbol": "BTC/USDT"}]
    r1 = fd._corr_matrix_syms(sig, ["ETH/USDT", "BTC/USDT"])
    r2 = fd._corr_matrix_syms(list(reversed(sig)), ["BTC/USDT", "ETH/USDT"])
    assert r1 == r2 == sorted(r1)


def test_scan_symbol_outside_universe_kept():
    """Savunmacı union: evren-dışı sinyal sembolü de matriste kalır."""
    result = fd._corr_matrix_syms([{"symbol": "XXX/USDT"}], ["BTC/USDT"])
    assert "XXX/USDT" in result and "BTC/USDT" in result


def test_gate_blind_regression_demo():
    """Eksik pozisyon sembolü fail-closed; tam matriste korelasyon ölçülür."""
    import numpy as np
    import pandas as pd

    from price_action.risk.gates import correlation_gate

    rng = np.random.default_rng(7)
    base = rng.normal(0, 0.02, 90)

    class _Pos:
        symbol = "ETH/USDT"

    index = pd.date_range(
        end=pd.Timestamp.now(tz="UTC").floor("D") - pd.Timedelta(days=1),
        periods=90,
        freq="D",
    )

    # (a) ETH matriste YOK → repaired gate fail-closed.
    df_blind = pd.DataFrame({"BTC/USDT": base}, index=index)
    ok, factor = correlation_gate(
        symbol="BTC/USDT",
        open_positions=[_Pos()],
        returns_df=df_blind,
        max_corr=0.7,
        hard_block_at=0.9,
    )
    assert (ok, factor) == (False, 0.0)

    # (b) ETH matriste VAR ve yüksek korele → gate gerçekten ölçer (blok/yarım)
    df_full = pd.DataFrame(
        {"BTC/USDT": base, "ETH/USDT": base + rng.normal(0, 0.001, 90)},
        index=index,
    )
    ok2, factor2 = correlation_gate(
        symbol="BTC/USDT",
        open_positions=[_Pos()],
        returns_df=df_full,
        max_corr=0.7,
        hard_block_at=0.9,
    )
    assert not (ok2 is True and factor2 == 1.0)  # artık kör değil


def test_daemon_source_wires_fix():
    """Kaynak-pin: daemon evren-union + pozisyon-rebuild + körlük logu içeriyor."""
    src = (ROOT / "scripts" / "futures_daemon.py").read_text(encoding="utf-8")
    assert src.count("_corr_matrix_syms(") >= 2  # def + çağrı
    assert "15M_CORR_GATE_BLIND" in src
    assert "_missing_pos_syms" in src
    # eski yalnız-sinyal kurulumu kalmadı
    assert '_all_scan_syms = list({s["symbol"] for s in signals}) if signals else []' not in src
