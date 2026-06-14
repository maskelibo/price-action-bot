# Hipotez: HYP-2026-06-02-v12-entry-quality-vsa-widestop

**Pre-registered BEFORE code.** git=a8f72539, data=market.duckdb (BTC 15m 2021-05..2026-06).

## Iddia
VSA `vsa_climax_test` + WIDESTOP (sl_pct>=0.025) 15m girisinin per-trade EDGE'i
(mean_R, base ~+0.84 @55bps / better @18bps true fee), ORTHOGONAL bir giris-kalite
filtresi ile OOS'ta artirilabilir; bu mean_R artisi stack getirisini AYNI -23% DD'de
~18-20% backtest'e (live ~15%) cekebilir.

## Test edilen kaldiraclar (her biri walk-forward + OOS hold-out + MTC zorunlu)
1. **Confluence threshold tuning** — strateji confluence_score'una bar koyma.
2. **Orthogonal filters:**
   - HTF trend bias (1d EMA200/EMA50 yonu ile hizali long/short)
   - climax intensity (SC/BC vol_sma_mult yuksek -> daha siddetli kapitulasyon)
   - bar spread/ATR intensity (test bar oncesi climax genisligi)
   - ADX floor (chop kacinma)
   - vol_z (giris barinin hacim z-skoru tabani)
3. **WIDESTOP threshold re-opt YUKARI** — sl_pct_min 0.025 -> 0.030 / 0.035 (siklasma izinli).

## Null hypothesis (Popper — once yazilir)
H0: Hicbir orthogonal filtre OOS mean_R'yi MTC-duzeltilmis anlamli sekilde artirmaz;
filtreler sadece sample'i kuculterek IS'te guzel gorunur ama OOS'ta cermez
(IS/OOS mean_R orani > 1.5 = overfit). Bu durumda giris zaten tavanda.
H0 yanlissa: en az 1 filtre IS'te SECILEN parametreyle OOS'ta mean_R'yi
+suficiently artirir (delta mean_R OOS > 0, BH-FDR alpha=0.05 gecer, IS/OOS ratio < 1.5).

## Dependent variables
per-trade mean_R (OOS), trade count (sample preservation), stack monthly return @ -23% DD,
sign-flip p_gross (shuffle), IS/OOS mean_R ratio.

## Independent variables
filter type + threshold (swept), sl_pct_min.

## Walk-forward protokol
- IS = [2021-05, 2024-01), OOS = [2024-01, 2026-06). Filtre esigi SADECE IS'te secilir,
  OOS'ta olculur. Tek split + ek olarak per-symbol-out sanity.
- MTC: tum filtre x esik kombinasyonlari icin Benjamini-Hochberg (FDR 0.05),
  shuffle-based p_gross her aday icin.

## Stop / overfit kriterleri (CRITICAL — overfit riski yuksek)
- IS mean_R < base IS mean_R -> filtre reddedilir (IS'te bile yardim etmiyor).
- IS/OOS mean_R ratio > 1.5 -> overfit red flag, REDDET.
- OOS delta mean_R <= 0 -> reddet.
- BH-FDR'da anlamli degil -> reddet.
- Sample OOS < ~150 trade'e dusuren filtre -> "noise shrink" suphesi, reddet.
- HICBIRI gecmezse: "giris tavanda, filtre curve-fit etme" de.

## Onceden taahhut (Tetlock adversarial collaboration)
Beklentim: confluence threshold OLU (confluence_score hardcoded 2.0 = sabit, varyans yok).
Filtrelerin %80'i overfit cikacak. En olasi GERCEK lever: WIDESTOP yukari (0.030)
fee-survival temiz + climax intensity (siddetli SC daha guvenilir test). Calibration:
%60 olasilik en az 1 lever OOS gecer; %40 hicbiri gecmez (giris tavanda).
