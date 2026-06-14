# Hipotez: HYP-2026-06-02-smc-trend-continuation

## Bağlam (neden bu hipotez)
SMC investigation'da ÜÇ konsept honest `p_gross<0.05` gross-edge gate'inde DÜŞTÜ
(crypto 15m/1h): SFP reversal (iter1+iter2) ve mean-reversion (range+Camarilla).
Ortak neden: (1) crypto OHLCV REVERSAL yönü ≈ random, (2) tight stop + 55bps taker
fee = fee ölümü. Şimdi YAPISAL OLARAK FARKLI, henüz test edilmemiş bir mekanizma:
TREND-CONTINUATION (kurumsal akış mekanizması, reversal'dan farklı prior) + tek
fee-uygun rejim (4h, stop ≥~%2, fee_R<0.1).

## İddia (falsifiable, ölçülebilir)
"Crypto OHLCV'de, close-bazlı bir BOS (break of structure) + displacement
(impulse range ≥ k·ATR) sonrası, impulse'ı doğuran Order Block VEYA FVG'ye İLK
pullback'te trend yönünde girilen pozisyon, **shuffle null'ı yener** (p_gross<0.05).
EN AZ 4h timeframe'inde gross edge tespit edilir."

İki konsept:
1. MSB/displacement continuation (OB+FVG, "Dragon Fruit" + FTR/FTB family)
2. FTR/FTB (Fail-to-Return / First-Time-Back): impulse'ın bıraktığı supply/demand
   zone'a ilk revisit'te with-trend giriş.

## Null hipotez (Popper — bu doğruysa şu OLMAMALI)
H0: Trend-continuation entry yönü, shuffle (random-direction) baseline'dan
istatistiksel olarak ayırt edilemez. Yani gerçek mean R_gross, 50-seed shuffle
dağılımının içinde (p_gross >= 0.05). Eğer H0 reddedilemezse → continuation da
reversal gibi ~0 gross edge → TÜM SMC kursunun crypto OHLCV'de deploy edilebilir
edge'i yok (clean negative = teslimat).

## Bağımlı değişkenler (pre-registered metrikler)
- DECISIVE: shuffle `p_gross` (fee-bağımsız directional edge testi)
- mean_R_gross (0bps), mean_R_net (55bps), win%, n
- fee_R (medyan) — 4h'de <0.1 beklenir
- walk-forward: pozitif-ay oranı
- per-symbol: kaç sembol pozitif

## Bağımsız değişkenler (param uzayı — KASITLI KÜÇÜK, anti-curve-fit)
- TF: {15m, 1h, 4h}
- concept: {OB-continuation, FVG-continuation, FTR}
- k_atr (displacement eşiği + stop floor): {1.5, 2.5}
- R (fixed TP): {2, 3}
- entry zone: OB veya FVG (ilk pullback)
Toplam grid kasıtlı dar; her TF×concept için 2-3 varyant. Multiple-testing:
denenen config sayısına göre p eşiği raporlanır.

## Beklenen sonuç + predictive interval (Tetlock — calibration)
Prior: reversal 3/3 düştü; continuation farklı mekanizma ama crypto OHLCV
mean-reverting/noisy. Tahminim:
- P(herhangi TF'de p_gross<0.05) ≈ %35
- P(4h'de p_gross<0.05) ≈ %30
- P(herhangi config 55bps net-pozitif) ≈ %15
- En olası sonuç: clean negative (continuation da ~0 gross edge) ≈ %55

## Stop criteria
- Tüm TF×concept'te p_gross >= 0.05 → continuation da edge'siz → SMC clean negative,
  iterasyon YOK (pozitif edge yoksa SOP-4b geçerli değil).
- Bir config p_gross<0.05 + net-pozitif → tek survivor; exact config + walk-forward
  + adversary review öner.

## Reproducibility
git_hash: (rapor anında), driver: scripts/research/smc_continuation_backtest.py
data: market.duckdb (4h/1h: 10 sym 2023-05..2026-05; 15m: 19 sym)
fees: 55bps + 0bps, seeds: 50
