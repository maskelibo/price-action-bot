# Postmortem — SEC26 Production Winner Forensic (2026-05-14)

## Sprint Tipi
**Pozitif kesif** — 10+ RED hipotez postmortem'i sonrasi, 1 PRODUCTION'in *NEDEN*'inin formal yazimi. Hard gate yok. RED hipotez sprint'i degil. PA mastery distillation amaçlı.

## 1-Cümle Sonuç
Production TOP_10+FVG pool'unun (n=6650) crypto'da kazanmasinin **9 yapisal kaynaği** ölçüldü ve kalıcı meta-memory'ye işlendi — gelecek researcher mental model edinebilir.

## Yapılanlar
1. Production envanteri çıkarıldı: 11 strateji × kanonik kaynak × pattern class × 1-2 cümle mekanik.
2. Cached PROD pool (sec13_4 pool_baseline_v1_3.pkl, n=6650) BTC OHLCV regime mask ile eşleştirildi.
3. Per-strategy + cross-strategy + 14 meta analiz (regime/side/sym/year/month/markov/jaccard).
4. 9 hipotez ölçüldü, hepsi sayıyla destekli.
5. Kalıcı meta-memory yazıldı: `memory/researcher/pattern_crypto_winner_anatomy.md`.

## En Büyük Sürprizler (Counter-Intuitive Bulgular)
1. **BTC<EMA50 mR > BTC>EMA50 mR** (+0.239 vs +0.172) — naive "trend with BTC" yanlış; bu sonuç short asymmetry'sinden geliyor.
2. **High-vol mR > Low-vol mR** (1.69x) — geleneksel risk mgmt'in tersine, high-vol edge'i besler (ama ekstrem high-vol toxic — capitulation halt).
3. **Right-tail %154 katki** — top 10% trade'ler total sumR'in 1.54x'ini uretiyor; mid 80% sadece -%3 net (≈noise). Bu kadar extreme power-law equity'de bile nadir.
4. **RANGE rejiminde SHORT/LONG = 4.62x** — counter-trend short edge'i range tepelerinde yoğunlaşmış (likidasyon havuzu mekanizmasi).
5. **Sequential dep delta_WR +13.9pp** — base WR %50.9, after-win %57.6 vs after-loss %43.7 → cool-down (3 loss → 5gun) matematiksel gerekçesi.

## Pool Edge Hierarchy (sumR)
1. brooks_failed_breakout: +370.4 (%27.3 katki)
2. fvg_fill_reversal: +267.3 (%19.7)
3. brooks_h2_l2: +194.4 (%14.3)
**Top 3 strateji pool sumR'in %61'ini taşıyor.** Diğer 8 strateji uncorrelated diversifikasyon sağlıyor.

## Mean-Rev Carrier Bulgusu
- mean_reversion class sumR'in **%69'u FVG'den** (267 / 388).
- Anchored VWAP + CVD spike fade + VSA climax ölçülebilir ama marjinal.
- **Kesin yapısal kural:** "Klasik mean-rev (RSI/Bollinger) crypto'da CONTINUATION. Microstructure gap-fill (FVG) tek skalable mean-rev edge."
- SEC22 zincir RED'leri (bb_extreme_reversal, htf_retest, three_push, rsi2 marginal) bunu defalarca dogruladi.

## Engine Settings Mathematical Justification (Forensik Sonrasi)
Tum production engine config kararları forensik tarafından destekleniyor:
- tp1_R=1.0 / tp2_R=1.5 → right-tail capture + Markov-1 lock-in
- runner_trail_mult=1.0 / time_exit=30 → fat-tail yakala + sermaye recycle
- consecutive_losses=3→5d → Markov-1 cluster reset
- mc=12 + per_sym=0.20 → alt-coin dispersion ama portfolyo konsantrasyonu yok
- monthly_dd_long=0.15 / short=0.05 → asymmetric short edge
- regime_filter (atr%≥6 + EMA200 streak + DD90≤-25) → ekstrem high-vol toxicity
- F&G ≤20 short-skip → losing-tail short engellenir

## Yapısal Bulgular (Generalizable)
1. **Crypto edge magnitude'ce gelir, sayıca değil** (right-tail dominance).
2. **Short bias structural** (1.66x; F&G + asymmetric DD koruması justifiable).
3. **Alt-coin'lerde edge 3-4x BTC** (DOT/ADA/SOL/AVAX/MATIC concentration cap critical).
4. **Pool yapisal orthogonal** (jaccard < 0.08) — slot fix (mc 8→12) ancak orthogonality var olunca yarar.
5. **Brooks trap + ICT FVG** crypto-spesifik amplified — leverage + 24/7 + funding cycle.

## Postmortem Sonuç
Hard gate sprint'i değil ama EN YUKSEK PA mastery EV iş. 10+ RED postmortem'in `pattern_crypto_mean_rev_continuation.md` + `learning_compound_pattern_bottleneck.md` + `learning_asset_class_transfer_bias.md` üçlüsünden sonra, **pozitif anatomik referans** elde edildi: `pattern_crypto_winner_anatomy.md`. Gelecek hipotez yazımında çift-yönlü pre-screen olur: "RED'lerin neden olduğunu biliyorum + PRODUCTION'in neden çalıştığını biliyorum."

## Sıradaki Sprint Backlog (Tetiklenen)
1. HYP-BACKLOG-001 — BTC>EMA50 hard filter test (beklenti: marjinal/negatif)
2. HYP-BACKLOG-002 — SHORT edge stress-period kaynak ayrıştırma
3. HYP-BACKLOG-003 — Alt-coin sub-portfolio özel manifest
4. HYP-BACKLOG-004 — Win-streak cap (3+ ardışık win → cool-down)
5. HYP-BACKLOG-005 — Structural class (Wyckoff+VSA) position-size bump

## Dosyalar
- `reports/researcher/2026-05-14_sec26_production_winner_forensic.md` (ana rapor)
- `memory/researcher/pattern_crypto_winner_anatomy.md` (kalıcı meta-memory)
- `reports/researcher/sec26_forensic_data.json` (ham veri)
- `reports/researcher/sec26_per_strategy_breakdown.csv`
- `reports/researcher/sec26_regime_breakdown.csv`
- `scripts/sec26_winner_forensic.py` (reproducibility)
