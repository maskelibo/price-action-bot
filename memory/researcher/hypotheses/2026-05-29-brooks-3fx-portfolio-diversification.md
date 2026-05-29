# HYP-2026-05-29-brooks-3fx-portfolio-diversification

- **Iddia (pre-reg):** brooks_failed_breakout 4H, 3 FX sembolünde (EUR/USD, GBP/USD,
  USD/JPY) düşük korelasyonlu çalışırsa, sabit-DD altında portföy aylık-medyan
  getiriyi tek-sembole göre anlamlı (>+2pp) artırır. Null: semboller arası
  monthly-R korelasyonu yüksek (ρ>0.7) → portföy std'si sum-of-stds'e yakın →
  free lunch yok, sadece kaldıraç var.
- **Falsifier (Popper):** Eğer matched-DD'de portföy medyanı ≈ tek-sembol (Δ<+1pp)
  VEYA portföy std'si rho=1 bound'a yakınsa → diversifikasyon yok, hipotez çürür.
- **Reproducibility:** git=e7d0a90, seed=12345, data=forex_market.duckdb(histdata),
  engine=scripts/forex_4h_research.gather (bit-identical filtreler) +
  scripts/brooks_portfolio_3fx.py. cost: fee0/slip1.0bps/swap0.3bps Wed3x.
- **Pre-reg metrikler:** standalone net mR + shuffle p (BH-FDR); monthly-R corr;
  portföy compounded median/MaxDD; matched-DD free-lunch (pp); MC ruin.

## SONUÇ — CORROBORATED (null reddedildi)
- Standalone full net mR: EUR +0.427(p.0002), GBP +0.585(p.0002), JPY +0.430(p.0006).
  3/3 BH-FDR PASS. OOS hepsi pozitif (EUR+0.425/GBP+0.468/JPY+0.321).
- Monthly-R korelasyon: ortalama ρ=0.13 (EUR-GBP 0.36, EUR-JPY 0.08, GBP-JPY -0.05).
  Portföy monthly-R std=11.83, rho=0 bound=10.70, rho=1 bound=18.42 → bağımsız
  sınıra yakın = gerçek free lunch.
- Monthly-R Sharpe: tek 0.32-0.53 → portföy 0.61.
- Matched MC_medDD≈-25%: PORT eff_r=2.0% median +6.57% vs EUR eff_r=2.5% median
  +1.21% → **free lunch +5.36pp/ay aynı DD'de**.
- %10/ay: portföy eff_r=3% → median +10.13%, mean +16.07%, MC_medDD -41%, ruin 0.1%,
  half-Kelly altı(<4.5%). Tek-sembol bunu güvenle hiçbir riskte vermiyordu.

## UYARI (Feynman kandırılma kontrolü)
- "FULL@1%" modu sabit bütçe DEĞİL: max_concurrent=6 → eşzamanlı 6×1%=%6 riske kadar.
  contMaxDD -43.6% (tek-sembol 1% -27.9%). Bu "eşit riskte diversifikasyon" değil,
  ~3-6x kaldıraç. Dürüst eksen = realized MaxDD (matched-DD bloğu) ve SPLIT modu.
- OOS compounded median kırılgan (FULL@1% OOS median ~%0) — 2024 başı kötü küme
  sequencing artifact'i; R-uzayında OOS net pozitif. Compounded path riski var.
