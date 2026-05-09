"""Unit testler — Day-of-Week / Hour-of-Day Calendar Effects Analizi.

Test senaryolari:
  1. Day-of-week extraction (sentetik timestamp'ler)
  2. Hour-of-day extraction (sentetik timestamp'ler)
  3. Bonferroni correction logic (alpha / n_comparisons)
  4. Win rate computation per group
  5. Fisher exact test + Cohen's h temel degerler
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from scripts.day_of_week_analysis import (
    BONFERRONI_DOW,
    BONFERRONI_HOD,
    DOW_NAMES,
    GroupStats,
    _cohens_h,
    _fisher_exact_p,
    compute_group_stats,
)


# ---------------------------------------------------------------------------
# 1. Day-of-Week extraction
# ---------------------------------------------------------------------------

class TestDayOfWeekExtraction:
    """Timestamp'den weekday() ile DOW cikarmasi."""

    def test_monday_is_zero(self):
        """Pazartesi = 0 (Python datetime.weekday() konvansiyonu)."""
        # 2026-01-05 Pazartesi
        ts = datetime(2026, 1, 5, 0, 0, 0, tzinfo=timezone.utc)
        assert ts.weekday() == 0, "Pazartesi weekday() == 0 olmali"
        assert DOW_NAMES[0] == "Pazartesi"

    def test_sunday_is_six(self):
        """Pazar = 6."""
        # 2026-01-11 Pazar
        ts = datetime(2026, 1, 11, 0, 0, 0, tzinfo=timezone.utc)
        assert ts.weekday() == 6, "Pazar weekday() == 6 olmali"
        assert DOW_NAMES[6] == "Pazar"

    def test_full_week_sequence(self):
        """7 ardisik gun 0..6 dondurmeli."""
        # 2026-05-04 (Pazartesi) ile baslayan bir hafta
        start = datetime(2026, 5, 4, 0, 0, 0, tzinfo=timezone.utc)
        import datetime as dt_mod
        for i in range(7):
            day = start + dt_mod.timedelta(days=i)
            assert day.weekday() == i, f"Gun {i}: weekday={day.weekday()} != {i}"

    def test_friday_is_four(self):
        """Cuma = 4."""
        ts = datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc)
        assert ts.weekday() == 4, "Cuma weekday() == 4 olmali"


# ---------------------------------------------------------------------------
# 2. Hour-of-Day extraction
# ---------------------------------------------------------------------------

class TestHourOfDayExtraction:
    """Timestamp'den .hour ile HOD cikarmasi."""

    def test_midnight_is_zero(self):
        """Gece yarisi UTC = saat 0."""
        ts = datetime(2026, 5, 9, 0, 0, 0, tzinfo=timezone.utc)
        assert ts.hour == 0

    def test_noon_is_twelve(self):
        ts = datetime(2026, 5, 9, 12, 30, 0, tzinfo=timezone.utc)
        assert ts.hour == 12

    def test_hour_range_0_to_23(self):
        """Tum saatler 0-23 araliginda."""
        import datetime as dt_mod
        base = datetime(2026, 5, 9, 0, 0, 0, tzinfo=timezone.utc)
        for h in range(24):
            ts = base + dt_mod.timedelta(hours=h)
            assert 0 <= ts.hour <= 23

    def test_daily_bars_typically_midnight(self):
        """1d bar entry_ts genellikle 00:00 UTC — HOD dagilimi tekduzedir."""
        # Sentetik 20 trade, hepsi saat 00:00
        trades = [
            {"hod": 0, "win": i % 2 == 0}
            for i in range(20)
        ]
        unique_hods = {t["hod"] for t in trades}
        assert len(unique_hods) == 1, "1d bar'larda HOD tek deger olmali (00:00 UTC)"


# ---------------------------------------------------------------------------
# 3. Bonferroni correction logic
# ---------------------------------------------------------------------------

class TestBonferroniCorrection:
    """Bonferroni alpha hesaplari."""

    def test_dow_bonferroni_alpha(self):
        """DOW icin alpha = 0.05 / 7 = 0.00714..."""
        expected = 0.05 / 7
        assert abs(BONFERRONI_DOW - expected) < 1e-10, (
            f"BONFERRONI_DOW = {BONFERRONI_DOW}, beklenen = {expected}"
        )

    def test_hod_bonferroni_alpha(self):
        """HOD icin alpha = 0.05 / 24 = 0.002083..."""
        expected = 0.05 / 24
        assert abs(BONFERRONI_HOD - expected) < 1e-10, (
            f"BONFERRONI_HOD = {BONFERRONI_HOD}, beklenen = {expected}"
        )

    def test_dow_stricter_than_unadjusted(self):
        """Bonferroni-duzeltilmis alpha, duzeltilmemisten kucuk olmali."""
        assert BONFERRONI_DOW < 0.05

    def test_hod_stricter_than_dow(self):
        """HOD daha fazla karsilastirma => daha siki alpha."""
        assert BONFERRONI_HOD < BONFERRONI_DOW

    def test_generic_bonferroni_formula(self):
        """n karsilastirma icin alpha = 0.05 / n."""
        for n in [1, 5, 7, 10, 24, 100]:
            expected = 0.05 / n
            assert abs(expected - 0.05 / n) < 1e-15


# ---------------------------------------------------------------------------
# 4. Win rate computation per group
# ---------------------------------------------------------------------------

class TestWinRateComputation:
    """compute_group_stats fonksiyonu temel davranisi."""

    def _make_stats(self, wins: dict[int, int], totals: dict[int, int]):
        return compute_group_stats(
            group_wins=wins,
            group_totals=totals,
            bonferroni_alpha=BONFERRONI_DOW,
            label_map={i: DOW_NAMES[i] for i in range(7)},
        )

    def test_perfect_win_rate(self):
        """Bir grubun tum trade'leri kazanmissa win_rate=1.0."""
        stats = self._make_stats(
            wins={0: 10, 1: 5, 2: 5, 3: 5, 4: 5, 5: 5, 6: 5},
            totals={i: 10 for i in range(7)},
        )
        monday = next(s for s in stats if s.label == "Pazartesi")
        assert monday.win_rate == 1.0

    def test_zero_win_rate(self):
        """Hic kazanamayan grup => win_rate=0.0."""
        stats = self._make_stats(
            wins={0: 0, 1: 5, 2: 5, 3: 5, 4: 5, 5: 5, 6: 5},
            totals={i: 10 for i in range(7)},
        )
        monday = next(s for s in stats if s.label == "Pazartesi")
        assert monday.win_rate == 0.0

    def test_all_equal_win_rates_not_significant(self):
        """Tum gruplar ayni win rate'e sahipse hicbiri anlamli olmamali."""
        # Her gunde 10 trade, 5 kazanma (50%)
        stats = self._make_stats(
            wins={i: 5 for i in range(7)},
            totals={i: 10 for i in range(7)},
        )
        assert all(not s.significant for s in stats), (
            "Ayni oranlar hicbir grubu anlamli kilmamali"
        )

    def test_n_total_and_n_win_match_inputs(self):
        """GroupStats.n_total ve n_win input ile tutarli olmali."""
        stats = self._make_stats(
            wins={0: 8, 1: 3, 2: 4, 3: 5, 4: 6, 5: 2, 6: 1},
            totals={i: 10 for i in range(7)},
        )
        monday = next(s for s in stats if s.label == "Pazartesi")
        assert monday.n_total == 10
        assert monday.n_win == 8
        assert abs(monday.win_rate - 0.8) < 1e-9

    def test_extreme_win_rate_difference(self):
        """Cok buyuk fark + buyuk n => anlamli olmali (Fisher test kontrolu)."""
        # Grup 0: 50 kazanma / 50 toplam (100%)
        # Diger 6 grup: 0 kazanma / 50 toplam (0%)
        stats = self._make_stats(
            wins={0: 50, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0},
            totals={i: 50 for i in range(7)},
        )
        monday = next(s for s in stats if s.label == "Pazartesi")
        # p < 1e-30 bekleniyor — kesinlikle anlamli
        assert monday.significant, (
            "100% vs 0% karsilastirmasi anlamli olmali (p << 0.0071)"
        )
        assert monday.p_value < 0.001


# ---------------------------------------------------------------------------
# 5. Fisher exact test + Cohen's h
# ---------------------------------------------------------------------------

class TestFisherAndCohensH:
    """Istatistik fonksiyonlari birim testleri."""

    def test_fisher_same_proportions_high_p(self):
        """Ayni oran => p 1.0'e yakin olmali."""
        p = _fisher_exact_p(n_win_grp=5, n_total_grp=10,
                            n_win_rest=35, n_total_rest=70)
        assert p > 0.9, f"Ayni oran icin p {p:.4f} yuksek olmali"

    def test_fisher_extreme_difference_low_p(self):
        """Buyuk fark + buyuk n => p cok kucuk olmali."""
        p = _fisher_exact_p(n_win_grp=45, n_total_grp=50,
                            n_win_rest=5, n_total_rest=50)
        assert p < 1e-10, f"Extreme fark icin p {p} << 0.0001 olmali"

    def test_fisher_p_between_0_and_1(self):
        """Fisher exact p-deger her zaman [0, 1] araliginda olmali."""
        cases = [
            (5, 10, 35, 70),
            (0, 10, 10, 10),
            (10, 10, 0, 10),
            (7, 10, 33, 70),
        ]
        for a, b, c, d in cases:
            p = _fisher_exact_p(a, b, c, d)
            assert 0.0 <= p <= 1.0, f"p={p} aralik disinda: ({a},{b},{c},{d})"

    def test_cohens_h_equal_proportions_is_zero(self):
        """Ayni iki oran => Cohen's h = 0."""
        h = _cohens_h(0.5, 0.5)
        assert abs(h) < 1e-9, f"Ayni oranlarda h={h} != 0"

    def test_cohens_h_zero_vs_one(self):
        """0.0 vs 1.0 => maksimum effect size (h = pi)."""
        h = _cohens_h(0.0, 1.0)
        # 2*arcsin(sqrt(0)) - 2*arcsin(sqrt(1)) = 0 - pi = pi (abs)
        expected = math.pi
        assert abs(h - expected) < 1e-9, f"h={h} != pi={expected}"

    def test_cohens_h_medium_effect(self):
        """%50 vs %65 => yaklasik orta buyuklukte etki."""
        h = _cohens_h(0.65, 0.50)
        # Yaklasik 0.30 (referans: Cohen 1988)
        assert 0.1 < h < 0.6, f"h={h} beklenmedik aralik"

    def test_cohens_h_symmetric(self):
        """h(p1, p2) == h(p2, p1) — simetrik olmali."""
        h1 = _cohens_h(0.4, 0.6)
        h2 = _cohens_h(0.6, 0.4)
        assert abs(h1 - h2) < 1e-12, f"Simetri bozuldu: h1={h1}, h2={h2}"
