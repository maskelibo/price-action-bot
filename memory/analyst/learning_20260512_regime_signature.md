---
agent: analyst
type: learning
created: 2026-05-12
topic: regime_signature_best_vs_worst
related_script: scripts/v093_regime_analysis.py
related_output: reports/v093_regime_analysis.txt
windows:
  worst: 2022-05-10 -> 2025-05-10  (yillik +%13.8 backtest / +%14.5 benchmark)
  best:  2022-07-09 -> 2025-07-09  (yillik +%132.9 backtest / +%48.4 benchmark live-realistic)
---

# Regime Signature — Best vs Worst 3y Rolling Pencere

## Baglam

13 pencerelik 3y rolling stress (v0.9.2 production, risk %3, cap 0.30, conc 0.20):
- WORST: `2022-05-10 -> 2025-05-10` — yillik +%13.8
- BEST: `2022-07-09 -> 2025-07-09` — yillik +%132.87

Pencereler **60 gun** kayma ile uretiliyor; sadece pencerenin 60-gunluk uc dilimleri
farkli — IC kismi (2022-07-09 .. 2025-05-09 = 1035 gun) ortak. Yani tum
performans farki **iki uctaki 60 gunluk dilimden** geliyor.

## Bulgular (sayisal)

### 1) ROI farki tamamiyla "edge windows" kaynakli

| Dilim | n_trade | R_sum | BTC return |
|---|---|---|---|
| WORST'a OZGU: 2022-05/06 (giris) | 32 | **-2.71** | **-30.4%** |
| BEST'e OZGU: 2025-05/06/07 (cikis) | 201 | **+113.86** | **+3.9%** |
| **Diff (best - worst)** | | **+116.57 R** | |

Ortak 1035 gun ic kismi ayni 2153 sinyali iceriyor; BEST'in extra 78 sinyali
2025-05/06/07'de toplandi (en kazancli 3 ay). WORST'in extra 32 sinyali ise
2022-05/06'da ezici cogunluk SHORT (BTC -30%) — yalnizca +R 2.6 brutu.
**Yani 100 R'lik fark **iki ucta** uretiliyor.**

### 2) Giris rejimi imzasi (ilk 60 gun): WORST toksik, BEST sakin

| Metrik | WORST entry 2022-05/06 | BEST entry 2025-05/06/07 | Esik adayi |
|---|---|---|---|
| BTC net return | **-30.4%** | +3.9% | < -%15 RED |
| ATR% mean | **7.86** | 2.56 | > 6 RED |
| ATR% p90 | 10.01 | 2.81 | > 8 RED |
| 30d vol (annualized) | **85%** | 33% | > 75% RED |
| BTC > EMA200 gun % | **8%** | 68% | < %20 RED |
| 90d max-DD | -40.3% | -8.5% (90d max) | < -%30 RED |

WORST'in girisi: **vol 85% ann, ATR% ~8, EMA200 ustu sadece %8.** Bu klasik
bear capitulation rejimi (LUNA collapse + 3AC = Mayis-Haziran 2022).
BEST'in girisi: vol 33%, ATR% 2.56, EMA200 ustu %68 — saglikli bull tonu.

### 3) 3y butun pencere — toplam rejim farki (cok daha kucuk!)

| Metrik | WORST 3y | BEST 3y | Diff |
|---|---|---|---|
| BTC net | +232.0% | +404.5% | +172.5pp |
| ATR% mean | 4.04 | 3.71 | -0.32 |
| BTC > EMA200 gun % | 66.8% | 75.1% | +8.3pp |
| Bull gun % (close>EMA200 & slope>0) | 52.8% | 60.6% | +7.8pp |
| Bear gun % | **28.8%** | **22.0%** | -6.8pp |
| 30d vol mean ann | 50.0% | 47.7% | -2.3 |
| 90d median-DD | -9.3% | -7.9% | +1.4 |

3y ortalama farklari **kucuk** (ATR% sadece 0.3 puan); buyuk fark **edge 60 gun**.

### 4) Aylik kayip kumelenmesi (WORST'in en kotu 5 ayi)

| Ay | n | W/L | R_sum | BTC |
|---|---|---|---|---|
| 2023-11 | 48 | 14/34 | **-22.82** | +8.9% |
| 2022-12 | 48 | 16/32 | -9.80 | -3.6% |
| 2025-01 | 57 | 29/28 | -7.51 | +9.5% |
| 2024-07 | 80 | 35/45 | -7.55 | +3.0% |
| 2023-02 | 54 | 23/31 | -7.38 | +0.1% |

**Ilginc**: WORST'in kayipli aylari **BTC pozitif** olan aylar! Yani gercek
kayipa dilimi 2023-11 gibi "BTC up, system loses" rejim catismasi. ATR% bu
aylarda dustugu icin (sakin bull continuation), brooks_failed_breakout ve
brooks_h2_l2 short sinyalleri whipsaw oluyor.

### 5) Strateji asymmetry — kim hangi pencerede daha cok kazaniyor?

`brooks_failed_breakout` her iki pencerede de dominant kazandiran
(WORST: +234.5R / BEST: +246.3R). Strateji-bazli fark **kucuk** (+12 R).
`pin_bar_round_numbers`: WORST +25.7 vs BEST +5.5 — **WORST'in tek artisi**.
`equal_highs_sweep`: WORST +41 vs BEST +56 — BEST'te +15 R fazla.

**Sinyal sayisi farki kuckuk** (worst 2153, best 2230). Onemli olan
**hangi sinyalin hangi rejimde isleyip islemedigi**, sinyal sayisi degil.

## Cevap: "Filter olarak hangi makro degisken kullanilabilir?"

**BIR DEGISKEN HEPSINI YAKALIYOR: GIRIS REJIMI.**

Strateji 3y boyunca tutarli (orta sinyalleri ortak); fark **ne zaman trading'e
basladiginiz**. 2022-05'te (LUNA collapse anligi) baslamak ile 2022-07'de
(dip-recovery) baslamak ayni 3y boyunca **+33 pp yillik fark** yaratiyor.

Pratik karsiligi: **rejim filtresi = "girilebilir gun mu?"** — vakit sectiren
filter degil, **canli sistemde her gun yeniden uygulanan ON/OFF kapisi**.

## Onerilen Rejim Filtresi (somut threshold)

### `pa.regime_filter` (yeni RiskOfficer/Lab parametresi)

Asagidaki **3 kosulun en az 2'si** saglandiginda **trading ASKIYA ALINIR**
(yeni pozisyon acilmaz, mevcut pozisyonlara dokunulmaz):

```yaml
regime_filter:
  enabled: true
  measure_on: "BTC/USDT 1d"
  evaluation: "end-of-day"
  rules:
    # ZIYAFET MOD (capitulation/panic)
    - name: high_volatility_panic
      atr_pct_14: ">= 6.0"            # 1d ATR / close * 100 >= %6
      lookback: 1                      # son 1 gun
    - name: bear_dominance
      btc_below_ema200_streak_days: ">= 10"   # son 10 gun BTC < EMA200
    - name: deep_drawdown
      btc_90d_dd_pct: "<= -25"        # BTC son 90 gun icinde -%25+ DD
  trigger_logic: "ANY 2 of 3 -> halt trading"
  resume_logic: "ATR%<=4 AND BTC>EMA50 for 5 consec days -> resume"
```

**Beklenen impact (geriye donuk):**
- 2022-05-10 ile 2022-07-09 arasi WORST giris donemini KAPATIR
  (ATR%=7.86, EMA200 streak <8%, 90d-DD -40.3% — UC kural da tetiklenir).
- 2022-11/2023-01 LUNA/FTX kalintilarinda devam ederken **acilir** (ATR% 4 alti).
- 2025-02 BTC -%17 ay (WORST'in -3.08 R'lik orta-dilim kayip ayi) ATR% ~3.5,
  bear streak <10 — KAPATILMAZ. Bu da iyi: 2025-03 sonrasi system geri donuyor.

**Tahmin**: WORST pencerede ~32 sinyal (2022-05/06) atilir, **R_sum kaybi -2.71
elenir** AMA daha onemlisi sistem 2022-05 baslangic equity'sini koruyup
sonraki +R 117 dilimine eksisiz girer. Toplam ROI uplift'i: yillik
**+%14.5 -> +%30** dolayinda olur (capitulation start eliminasyonu).

### Alternatif (tek-degisken, daha basit)

`atr_pct_14_gt_6 -> halt` tek basina **WORST giris 60 gununu tum sekilde**
kapatir (60/60 gun ATR% > 6) ama 2023-08 ve 2024-04 gibi tek-gunluk
volatilite spike'lerinde gereksiz halt yapar. Bu yuzden **3 kuralin 2'si**
mantigi daha az false-positive verir.

## Sonraki Adimlar (Researcher'a oneri)

1. `scripts/v094_regime_filter_backtest.py` — onerilen filtre tum 13 pencerede
   simule edilsin. Beklenti: WORST pencere yillik %14.5 -> %30; BEST pencere
   yillik %48 -> %45 (kucuk dusus, halt sirasinda missed-opportunity); ortalama
   ROI artar, dispersiyon dusurur.
2. ATR%14 esigi 6.0 -> 5.0 / 6.5 / 7.0 grid sweep.
3. Resume kosulu icin lag testi (3 vs 5 vs 10 gun consec).
4. Sembol-bazli rejim ayrimi denenmeli mi? (BTC tek proxy yeterli mi yoksa
   ETH dominance dahil etmeli mi). Su an dominance proxy yok — BTC pe basit
   sinyal yeterli olabilir.

## Yanlis Yapilanlar / Sinirlar

- Sembol-bazli dominance proxy hesaplamadik (gerek yok — BTC kendisi yeterli sinyal verdi).
- 1w timeframe verisi okumadik (1d zaten yeterli ayrim verdi).
- Strateji-bazli rejim sensitivity sweep'i bu raporda **yok** — hep aggregate.

## Dosyalar

- Script: `scripts/v093_regime_analysis.py`
- Output: `reports/v093_regime_analysis.txt` (raw ciktilar, full table)
- Benchmark: `reports/PRODUCTION_BENCHMARK.md`
