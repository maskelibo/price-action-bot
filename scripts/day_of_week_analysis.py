"""Day-of-Week ve Hour-of-Day Calendar Effects — Engulfing Continuation.

Tum engulfing trade'lerini toplar, entry_ts'den DOW ve HOD cikarir,
Bonferroni-corrected Fisher exact testi ile anlamlilik kontrol eder.

Kullanim:
    PYTHONPATH=src PYTHONIOENCODING=utf-8 python scripts/day_of_week_analysis.py

Cikti:
    1. Day-of-Week win rate tablosu (7 gun, p-value, Cohen's h)
    2. Hour-of-Day win rate tablosu (anlamli saatler — 1d bar kısıtı ile)
    3. Bonferroni-corrected ozet
    4. VERDICT: DEFER / REJECT
"""
from __future__ import annotations

import io
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))

# ─── Sabitler ────────────────────────────────────────────────────────────────
DOW_NAMES = ["Pazartesi", "Sali", "Carsamba", "Persembe", "Cuma", "Cumartesi", "Pazar"]
ALPHA_GLOBAL = 0.05
BONFERRONI_DOW = ALPHA_GLOBAL / 7   # 0.00714
BONFERRONI_HOD = ALPHA_GLOBAL / 24  # 0.00208

SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
]


# ─── Istatistik Yardimcilari ─────────────────────────────────────────────────

class GroupStats(NamedTuple):
    label: str
    n_total: int
    n_win: int
    win_rate: float
    p_value: float          # Fisher exact (two-tailed)
    cohens_h: float         # Effect size
    significant: bool       # p < bonferroni_alpha


def _fisher_exact_p(n_win_grp: int, n_total_grp: int,
                    n_win_rest: int, n_total_rest: int) -> float:
    """Fisher exact testi (iki kuyruk) — scipy olmadan saf Python.

    2x2 contingency table:
         Win   Loss
    grp   a     b
    rest  c     d
    """
    a = n_win_grp
    b = n_total_grp - n_win_grp
    c = n_win_rest
    d = n_total_rest - n_win_rest

    def _log_comb(n: int, k: int) -> float:
        """log C(n, k) — log-gamma ile hassas hesaplama."""
        if k < 0 or k > n:
            return -math.inf
        return (math.lgamma(n + 1)
                - math.lgamma(k + 1)
                - math.lgamma(n - k + 1))

    R = a + b   # row1 total
    S = c + d   # row2 total
    N = R + S
    K = a + c   # col1 total

    # Gozlenen olasilik (log scale)
    def _log_p_table(x: int) -> float:
        """2x2 tablosunun log-probabilitesi (x = sol ust kose)."""
        return (
            _log_comb(R, x)
            + _log_comb(S, K - x)
            - _log_comb(N, K)
        )

    obs_log_p = _log_p_table(a)

    # Tum olasi x degerleri
    x_min = max(0, K - S)
    x_max = min(R, K)

    # Two-tailed: obs kadar kucuk ya da kucuk log-p olan tum tablolarin toplami
    total_p = 0.0
    for x in range(x_min, x_max + 1):
        lp = _log_p_table(x)
        if lp <= obs_log_p + 1e-10:   # kucuk ya da esit (numerik tolerans)
            total_p += math.exp(lp)

    return min(total_p, 1.0)


def _cohens_h(p1: float, p2: float) -> float:
    """Cohen's h effect size iki oran arasinda.

    h = 2 * arcsin(sqrt(p1)) - 2 * arcsin(sqrt(p2))
    |h| < 0.2 kucuk, 0.2-0.5 orta, >0.5 buyuk
    """
    phi1 = 2.0 * math.asin(math.sqrt(max(0.0, min(1.0, p1))))
    phi2 = 2.0 * math.asin(math.sqrt(max(0.0, min(1.0, p2))))
    return abs(phi1 - phi2)


def compute_group_stats(
    group_wins: dict[int | str, int],
    group_totals: dict[int | str, int],
    bonferroni_alpha: float,
    label_map: dict[int | str, str] | None = None,
) -> list[GroupStats]:
    """Her grup icin win rate + Fisher exact + Cohen's h hesapla."""
    total_wins = sum(group_wins.values())
    total_n = sum(group_totals.values())

    results = []
    for key in sorted(group_totals.keys()):
        n_grp = group_totals[key]
        w_grp = group_wins.get(key, 0)
        if n_grp == 0:
            continue

        n_rest = total_n - n_grp
        w_rest = total_wins - w_grp

        wr_grp = w_grp / n_grp if n_grp > 0 else 0.0
        wr_rest = w_rest / n_rest if n_rest > 0 else 0.0

        p = _fisher_exact_p(w_grp, n_grp, w_rest, n_rest)
        h = _cohens_h(wr_grp, wr_rest)

        lbl = label_map[key] if label_map else str(key)
        results.append(GroupStats(
            label=lbl,
            n_total=n_grp,
            n_win=w_grp,
            win_rate=wr_grp,
            p_value=p,
            cohens_h=h,
            significant=(p < bonferroni_alpha),
        ))
    return results


# ─── Trade toplama ────────────────────────────────────────────────────────────

def collect_all_trades() -> list[dict]:
    """10 sembol uzerinde engulfing backtest'i calistirip tum trade'leri toplar."""
    try:
        from price_action.backtest.engine import BacktestEngine
        from price_action.strategies.engulfing_continuation import (
            EngulfingContinuationStrategy,
            _default_manifest,
        )
        from scripts.run_real_backtest import _load_symbol_ohlcv
    except ImportError as e:
        print(f"[HATA] Import basarisiz: {e}")
        print("Lutfen: PYTHONPATH=src python scripts/day_of_week_analysis.py")
        sys.exit(1)

    manifest = _default_manifest()
    all_trades: list[dict] = []

    for sym in SYMBOLS:
        print(f"  [{sym}] yukleniyor...", end="", flush=True)
        try:
            df = _load_symbol_ohlcv(sym, tf="1d")
            if df.empty:
                print(" bos veri, atlaniyor.")
                continue

            strategy = EngulfingContinuationStrategy(manifest)
            df_feats = strategy.prepare_features(df)

            def prov(*_a, **_k):
                return df_feats.copy()

            engine = BacktestEngine(risk_officer=None, store_load=None)
            result = engine.run(
                strategy,
                [sym],
                start=df["ts"].iloc[0].to_pydatetime(),
                end=df["ts"].iloc[-1].to_pydatetime(),
                timeframe="1d",
                initial_capital=10_000.0,
                fees={"taker": 0.00075, "maker": -0.00010},
                slippage_bps=5.0,
                ohlcv_provider=prov,
            )

            if result.trades is None or result.trades.empty:
                print(f" 0 trade.")
                continue

            for _, row in result.trades.iterrows():
                try:
                    entry_ts = row["entry_ts"]
                    # pandas Timestamp -> Python datetime
                    if hasattr(entry_ts, "to_pydatetime"):
                        entry_ts = entry_ts.to_pydatetime()
                    if entry_ts.tzinfo is None:
                        entry_ts = entry_ts.replace(tzinfo=timezone.utc)

                    r_mult = float(row.get("realized_r_multiple", 0.0))
                    all_trades.append({
                        "symbol": sym,
                        "entry_ts": entry_ts,
                        "dow": entry_ts.weekday(),          # 0=Mon, 6=Sun
                        "hod": entry_ts.hour,               # 0-23 UTC
                        "r_multiple": r_mult,
                        "win": r_mult > 0,
                    })
                except Exception as row_err:
                    print(f"\n  [UYARI] Satir hatasi {sym}: {row_err}")

            n_t = len(result.trades)
            print(f" {n_t} trade.")

        except Exception as sym_err:
            print(f" HATA: {sym_err}")

    return all_trades


# ─── Tablo yazici ─────────────────────────────────────────────────────────────

def _print_table(
    title: str,
    stats: list[GroupStats],
    bonferroni_alpha: float,
    overall_wr: float,
) -> None:
    print(f"\n{'=' * 74}")
    print(f"  {title}")
    print(f"  Bonferroni alpha = {bonferroni_alpha:.5f} | Genel win rate = {overall_wr:.1%}")
    print(f"{'=' * 74}")
    header = f"{'Grup':<16} {'N':>5} {'Win':>5} {'WR%':>7} {'vs.avg':>8} {'p-val':>9} {'h':>6} {'Anlamli?':>10}"
    print(header)
    print("-" * 74)
    for s in stats:
        diff = s.win_rate - overall_wr
        sig_str = "*** ANLAMLI ***" if s.significant else "-"
        print(
            f"{s.label:<16} {s.n_total:>5} {s.n_win:>5} {s.win_rate:>6.1%} "
            f"{diff:>+8.1%} {s.p_value:>9.5f} {s.cohens_h:>6.3f} {sig_str:>10}"
        )
    print("-" * 74)
    sig_count = sum(1 for s in stats if s.significant)
    print(f"  Anlamli grup sayisi: {sig_count} / {len(stats)}")


# ─── Ana analiz ───────────────────────────────────────────────────────────────

def run_analysis(trades: list[dict]) -> str:
    """Trade listesinden analiz yap, VERDICT donduR."""

    if not trades:
        print("\n[HATA] Hic trade yok — analiz yapilamiyor.")
        return "REJECT"

    n_total = len(trades)
    n_win = sum(1 for t in trades if t["win"])
    overall_wr = n_win / n_total if n_total > 0 else 0.0

    print(f"\n{'#' * 74}")
    print(f"  ENGULFING CONTINUATION — CALENDAR EFFECT ANALIZI")
    print(f"{'#' * 74}")
    print(f"  Toplam trade : {n_total}")
    print(f"  Toplam kazanan: {n_win}")
    print(f"  Genel win rate: {overall_wr:.1%}")
    print(f"  Semboller    : {', '.join(SYMBOLS)}")

    # ─── DOW istatistikleri ─────────────────────────────────────────────────
    dow_wins: dict[int, int] = defaultdict(int)
    dow_totals: dict[int, int] = defaultdict(int)
    for t in trades:
        dow = t["dow"]
        dow_totals[dow] += 1
        if t["win"]:
            dow_wins[dow] += 1

    dow_stats = compute_group_stats(
        group_wins=dict(dow_wins),
        group_totals=dict(dow_totals),
        bonferroni_alpha=BONFERRONI_DOW,
        label_map={i: DOW_NAMES[i] for i in range(7)},
    )

    _print_table(
        title="DAY-OF-WEEK WIN RATE (Bonferroni alpha = 0.05/7 = 0.00714)",
        stats=dow_stats,
        bonferroni_alpha=BONFERRONI_DOW,
        overall_wr=overall_wr,
    )

    # ─── HOD istatistikleri ─────────────────────────────────────────────────
    hod_wins: dict[int, int] = defaultdict(int)
    hod_totals: dict[int, int] = defaultdict(int)
    for t in trades:
        hod = t["hod"]
        hod_totals[hod] += 1
        if t["win"]:
            hod_wins[hod] += 1

    hod_stats = compute_group_stats(
        group_wins=dict(hod_wins),
        group_totals=dict(hod_totals),
        bonferroni_alpha=BONFERRONI_HOD,
        label_map={h: f"{h:02d}:00 UTC" for h in range(24)},
    )

    # Sadece trade olan saatleri goster (1d bar => buyuk olasilikla tum 00:00)
    active_hod = [s for s in hod_stats if s.n_total > 0]
    _print_table(
        title="HOUR-OF-DAY WIN RATE (Bonferroni alpha = 0.05/24 = 0.00208)",
        stats=active_hod,
        bonferroni_alpha=BONFERRONI_HOD,
        overall_wr=overall_wr,
    )

    # ─── Ozet ──────────────────────────────────────────────────────────────
    dow_sig = [s for s in dow_stats if s.significant]
    hod_sig = [s for s in active_hod if s.significant]

    print(f"\n{'=' * 74}")
    print(f"  OZET")
    print(f"{'=' * 74}")
    print(f"  DOW: {len(dow_sig)} / {len(dow_stats)} gün Bonferroni-anlamlı")
    print(f"  HOD: {len(hod_sig)} / {len(active_hod)} saat Bonferroni-anlamlı")

    # DOW gunluk dagilim
    print(f"\n  DOW dagilimi (trade sayilari):")
    for s in dow_stats:
        bar = "█" * min(s.n_total, 40)
        print(f"    {s.label:<12}: {s.n_total:>3} trade  {bar}")

    # HOD dagilimi ozet
    unique_hods = {t["hod"] for t in trades}
    print(f"\n  HOD: {len(unique_hods)} farkli saat degeri var.")
    if len(unique_hods) <= 3:
        print(f"  Tum barlar benzer HOD'da — 1d bar kısıtı nedeniyle HOD analizi trivially null.")

    # ─── Sample-size uyarisi ────────────────────────────────────────────────
    avg_per_day = n_total / 7.0
    print(f"\n  ORNEKLEM UYARISI:")
    print(f"    Gun basina ortalama trade: {avg_per_day:.1f}")
    print(f"    Power hesabi (yaklasik):")
    for grp_n in [10, 20, 30, 50]:
        # Tespit edilebilir fark icin yaklasik hesap
        # Two-proportion z-test, power=0.8, alpha=0.0071
        # Gerekli n icin: z_alpha/2 = 2.69, z_beta = 0.84
        # n = (z_alpha/2 + z_beta)^2 * (p(1-p)*2) / delta^2
        # delta: %10 fark, p=0.5 (en kotu durum)
        z = 2.69 + 0.84  # alpha=0.0071 + power=0.8
        base = 0.5
        delta = 0.10
        n_req = (z**2 * 2 * base * (1 - base)) / (delta**2)
        feasible = "OK" if grp_n >= n_req else f"yetersiz (gerekli ~{n_req:.0f})"
        print(f"      n={grp_n:>3}: %10 fark icin {feasible}")

    # ─── Retail tradeability degerlendirmesi ───────────────────────────────
    print(f"\n  RETAIL TRADEABILITY:")
    print(f"    1D barlarinda entry_ts genellikle 00:00 UTC => HOD filtresi uygulanamaz.")
    print(f"    DOW filtresi uygulanabilir ANCAK: her gun N~{avg_per_day:.0f} trade beklentisi")
    print(f"    cok kucuk => false discovery riski yuksek (Bonferroni'e ragmen).")
    print(f"    Harris uyarisi: Dusuk likidite saatlerindeki trade'ler gercek hayatta")
    print(f"    3-5x slippage odeyebilir — takvim efekti gerçekten trade edilebilir mi?")

    # ─── VERDICT ───────────────────────────────────────────────────────────
    print(f"\n{'#' * 74}")
    if dow_sig or hod_sig:
        verdict = "DEFER"
        print(f"  VERDICT: *** DEFER ***")
        print(f"")
        print(f"  Gerekce: {len(dow_sig)} gün / {len(hod_sig)} saat Bonferroni-anlamlı çıktı.")
        print(f"  ANCAK gun basina N~{avg_per_day:.0f} ile test gucu cok dusuk.")
        print(f"  Sinyal gercek mi, lucky pattern mi belirsiz.")
        print(f"")
        print(f"  EYLEM:")
        print(f"    - Calendar filter OLARAK UYGULAMA (overfit riski)")
        print(f"    - 6+ ay daha veri topla, N'i 50+'ya cikarmaya calis")
        print(f"    - Yeniden test et (pre-registered alpha: 0.0071)")
        print(f"    - Anlamlı gün(ler): {[s.label for s in dow_sig]}")
    else:
        verdict = "REJECT"
        print(f"  VERDICT: *** REJECT ***")
        print(f"")
        print(f"  Gerekce: Hicbir gün/saat Bonferroni-corrected alpha'yi gecemedi.")
        print(f"  Mevcut engulfing trade'lerinde istatistiksel anlamli DOW/HOD etkisi yok.")
        print(f"")
        print(f"  EYLEM:")
        print(f"    - Engulfing continuation stratejisi rejimde sabit kalir.")
        print(f"    - DOW/HOD filtresi ekleme — hicbir degisiklik yapma.")
        print(f"    - Bu hipotez arsivlenir (kanitlanamadi).")
    print(f"{'#' * 74}")

    return verdict


# ─── Ozet yazici ─────────────────────────────────────────────────────────────

def print_sample_size_warning(n_trades: int) -> None:
    """Power analizi ozeti."""
    avg = n_trades / 7.0
    print(f"\n  [ISTATISTIK] Gun basina ~{avg:.1f} trade | Bonferroni alpha=0.0071")
    print(f"  %10 fark tespit icin gereken n (power=0.8): ~{(3.53**2 * 0.5 * 0.5 * 2) / 0.01:.0f}")
    print(f"  Mevcut n ({avg:.0f}) << gerekli n => power < 0.5")
    print(f"  Bu analiz KESFEDICI (exploratory) niteligindedir, onaylayici degil.")


# ─── Entry point ─────────────────────────────────────────────────────────────

def main() -> None:
    # Windows terminali utf-8 ile cikti (sadece dogrudan calistirildignda)
    if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        except Exception:
            pass

    print("Engulfing trade'leri toplanıyor (10 sembol × 1d × 3y)...")
    trades = collect_all_trades()
    print(f"\nToplam {len(trades)} trade toplandi.\n")

    if trades:
        print_sample_size_warning(len(trades))

    verdict = run_analysis(trades)

    # Hipotez dosyasini guncelle
    hyp_path = ROOT / "memory" / "researcher" / "hypotheses" / "2026-05-09-day-of-week-effects.md"
    if hyp_path.exists():
        print(f"\nHipotez dosyasi: {hyp_path}")
        print(f"Lutfen 'Sonuclar' bolumunu manuel olarak guncelleyin: VERDICT = {verdict}")


if __name__ == "__main__":
    main()
