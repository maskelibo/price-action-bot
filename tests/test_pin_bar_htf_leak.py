"""pin_bar_htf_sr haftalık fraktal leak — kapanış sprinti 2026-07-08 (dalga-4 W4 HIGH).

_weekly_swing_sr_levels hafta i için window'u i'ye kadar (i hariç) alıyordu:
`df_w.iloc[start_i:i]`. Ama hafta j'nin fraktal swing'i j+fractal_n haftası
KAPANANA kadar kesinleşmez (fractal merkez bar + sonraki n barı görür). Hafta i,
henüz kesinleşmemiş (i-1..i-fractal_n) swing'lerini kullanıyordu → fractal_n
haftalık LOOKAHEAD. FAZ-2 köprüsünden sahte-GO basabilir.

Operasyonel lookahead tanımı: geçmiş S/R, GELECEK bar eklenince DEĞİŞMEMELİ.
Eski kod: gelecek hafta eklenince _fractal_swings geçmiş swing'leri yeniden
etiketler → geçmiş S/R değişir (leak). Fix sonrası: fractal_n marjini →
kesinleşmiş geçmiş sabit.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.strategies.pin_bar_htf_sr import _weekly_swing_sr_levels  # noqa: E402


def _weekly(n: int) -> pd.DataFrame:
    """n haftalık sentetik OHLCV — belirgin swing high/low'lar içerir."""
    ts = pd.date_range("2025-01-06", periods=n, freq="7D", tz="UTC")
    # zikzak: swing'ler net kesinleşsin
    highs = [100 + (10 if i % 3 == 0 else 0) + i * 0.5 for i in range(n)]
    lows = [90 - (10 if i % 3 == 1 else 0) + i * 0.5 for i in range(n)]
    return pd.DataFrame(
        {
            "ts": ts,
            "open": [95 + i * 0.5 for i in range(n)],
            "high": highs,
            "low": lows,
            "close": [95 + i * 0.5 for i in range(n)],
            "volume": [1000] * n,
        }
    )


def test_sr_immutable_once_computed():
    """LEAK TANIMI (operasyonel): bir haftanın S/R'ı İLK hesaplandığı değerde
    kalmalı — sonraki (daha uzun) prefikslerde DEĞİŞMEMELİ.

    _fractal_swings docstring'i: swing 'sadece bar t-n için kullanılabilir'
    (sağ taraf bilgisi). Eski _weekly_swing_sr_levels hafta i için i-1'e kadarki
    swing'leri kullanıyordu; i-1 swing'i i+1 haftası gelene dek False → prefiks
    büyüyünce True olur → hafta i'nin S/R'ı geçmişte değişir = lookahead.
    """
    full = _weekly(25)
    fractal_n = 2
    first_seen: dict[int, list[float]] = {}
    for k in range(fractal_n + 1, len(full) + 1):
        sr = _weekly_swing_sr_levels(full.iloc[:k], fractal_n=fractal_n)
        for i in range(len(sr)):
            val = sr.iloc[i]
            if i in first_seen:
                assert first_seen[i] == val, (
                    f"hafta {i} S/R prefiks k={k}'de DEĞİŞTİ (lookahead): "
                    f"ilk={first_seen[i]} → şimdi={val}"
                )
            else:
                first_seen[i] = val


def test_early_weeks_have_no_sr():
    """İlk fractal_n hafta S/R üretemez (yeterli teyit yok) — boş liste."""
    df = _weekly(10)
    sr = _weekly_swing_sr_levels(df, fractal_n=2)
    # İlk hafta hiçbir kesinleşmiş geçmiş swing'e sahip olamaz
    assert sr.iloc[0] == []


def test_sr_series_length_matches_input():
    df = _weekly(12)
    sr = _weekly_swing_sr_levels(df, fractal_n=2)
    assert len(sr) == len(df)


def test_empty_input_safe():
    sr = _weekly_swing_sr_levels(pd.DataFrame(), fractal_n=2)
    assert len(sr) == 0
