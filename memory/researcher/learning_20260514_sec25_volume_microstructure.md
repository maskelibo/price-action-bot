# Learning — SEC25 Track D Volume Microstructure: 4/4 RED

**Tarih:** 2026-05-14
**Sprint:** SEC25 Researcher (Track D, hacim mikroyapısı + VSA/Wyckoff volume)
**Hipotezler:**
- [HYP-D1 VSA SOS Effort-to-Move-Up](hypotheses/2026-05-14-vol-d1-sos-effort-up.md)
- [HYP-D2 VSA SOW Effort-to-Move-Down](hypotheses/2026-05-14-vol-d2-sow-effort-down.md)
- [HYP-D3 VSA Bag Holding Absorpsiyon](hypotheses/2026-05-14-vol-d3-bag-holding-absorption.md)
- [HYP-D4 Weis Wave Volume Divergence](hypotheses/2026-05-14-vol-d4-weis-wave-divergence.md)

**Karar:** **4/4 HARD RED (pre-reg disiplini)** — D2 v2 ADAY işaretli.

---

## TL;DR

VSA/Wyckoff/Weis literatüründen 4 pre-registered hipotez (`vsa_sos_effort_up`,
`vsa_sow_effort_down`, `vsa_bag_holding`, `weis_wave_divergence`) crypto 1d × 11 sym
× 5y veride standalone test edildi. IS=2021-2023 / OOS=2024-2026 split.
**Tüm 4 hipotez pre-registered HARD gate'inde RED.**

| HYP | n_IS | mR_IS | mR_OOS | Verdict | Sebep |
|-----|-----:|------:|-------:|---------|-------|
| D1 SOS  | 123 | +0.273 | -0.047 | RED | IS→OOS sign-flip |
| D2 SOW  |  97 | +0.140 | +0.533 | RED-pre-reg / v2 ADAY | IS 5 gate fail |
| D3 Bag  |  10 | +0.556 | +0.889 | RED | n_min altı (15 trade total) |
| D4 Weis | 183 | +0.114 | -0.046 | RED | sign-flip + sym-out 48% dev |

Bonferroni-conservative (α=0.0125): hiçbir hipotez IS p<0.0125 geçmedi.
**Promote edilen production aday: YOK.**

---

## Asıl Bulgu — HYP-D2 SOW Asymmetry (Post-Hoc)

HYP-D2 IS gate FAIL (n=97, WR=44.3%, p=0.28, max_R=14.91 AVAX, sym-out 140%),
**AMA OOS dramatik:**
- n=59, mR=+0.533, WR=71.2%, p=0.0015 (Bonferroni geçer)
- AVAX hariç bile: n=53, mR=+0.502, bootstrap 95% CI=[+0.19, +0.82] CI low pozitif
- **OOS 11/11 sym pozitif** (sym-wide robust)
- IS no_AVAX: mR -0.056 (AVAX IS'ı kurtarmıştı)

**Açıklama hipotezi:** SEC14.1 short trade 1.66× karlılık bulgusu — short pattern'lar
bearish/range cycle'larda (2024-2026) güçlü, bull cycle'larda (2021-2023) zayıf.
IS bull-heavy → fail; OOS bear/range-heavy → pass.

**v2 önerisi:** Pre-registered sprint ile (a) 3y rolling walk-forward, (b) 20 sym
extension, (c) EMA200 trend filter (sadece downtrend), (d) BTC halving cycle
stratifikasyon.

---

## Doğrulanmış Bulgular

1. **RAG-first yaklaşımı**: WebSearch yapılmadı; `knowledge/books/vsa_volume_spread_analysis.md`
   ve `volume_price_divergence.md` zaten 10 test-edilebilir VSA pattern + 6 HYP
   taslağı içeriyor. Token tasarrufu + reproducibility.

2. **Lokal optimum hipotezi 5. teyit**: Mevcut envanter zaten 6 hacim stratejisi
   içeriyor (`obv_engulfing_confluence, cvd_spike_fade, vsa_climax_test,
   wyckoff_spring_vsa, volume_expansion, naked_poc_mr` — TOP_11'in %25'i). Yeni
   4 hipotezden 3'ünün RED + 1'inin post-hoc-only olması, crypto 1d hacim
   alpha'nın büyük ölçüde mevcut pool tarafından yakalanmış olduğunu doğrular.
   SEC4 (yeni strateji sınıfı survey) + SEC22 (mean-rev sprint) + SEC23 (RSI2 OOS) +
   SEC24 (turtle soup) + SEC25 = **5. lokal optimum teyit**.

3. **IS/OOS split selection bias çalıştı**: 4/4 hipotezden 2'si (D1, D4) IS→OOS
   sign-flip gösterdi. Full-sample ölçüm bunları "marjinal aday" olarak işaretlerdi.
   SEC23 paradigm doğrulandı.

4. **Honest clip + max_R gate çalıştı**: AVAX 14.91 outlier IS-period (2023-04-20),
   hold=48d (clip threshold 60d altında), gerçek MTM. Artifact gate (max_R<10) IS
   gate failure'a direkt katkı.

5. **Sample frekansı gerçekten kritik**: HYP-D3 pre-reg "sample riski yüksek" notu
   **gerçekleşti** (15 trade toplam, 5y × 11 sym). VSA narrow-spread + high-vol +
   small-body + down-bar + bullish-confirm kombinasyonu crypto 1d'de yapısal olarak
   çok ender.

6. **Single-bar / two-wave pattern'lar selection-bias-prone**: D1, D4 sign-flip.
   Multi-bar / multi-event pattern'lar (turtle_soup 4-bar ATR-defined, SEC24'te
   p=0.3 ama OOS hala +0.07) daha robust.

---

## Counter-Hypothesis Doğrulamaları

| Counter-hyp | Hipotez | Sonuç |
|-------------|---------|-------|
| D1 #2 | volume_expansion overlap | Mekanistik benzerlik var, OOS sign-flip overlap teorisini destekliyor |
| D1 #3 | Regime sensitivity (BC ön çağrısı olabilir) | 2022 IS mR -0.56, OOS 2026 -0.49 — regime-dependency doğrulandı |
| D2 #1 | Crypto bull-biased class | IS bull → fail, OOS bear/range → pass = **hipotez kanıtlandı** |
| D3 #4 | 2-bar gecikme edge azaltır | n=15, edge yön nötr — confirm |
| D4 #1 | OBV alt-örneklemesi | Direct correlation analizi sprint scope dışı; OOS sign-flip retail-arbitraj hipotezini destekliyor |

---

## Reproducibility Bilgileri

- `scripts/sec25_volume_standalone.py` — 4 strateji batch backtest
- `scripts/sec25_drill_d2_oos_forensic.py` — D2 OOS forensic
- `reports/researcher/sec25_volume_standalone.json` — full result dump
- `reports/researcher/sec25_volume_trades.pkl` — 4 strategy trade pickle
- Seed 42, n_perm 2000, 11 sym Binance spot 1d
- Honest clip: hold>60d → R≤1.0
- Fees: taker 0.075% / maker -0.010%, slippage 5 bps

---

## Sonraki Adımlar

1. v2 önerisi HYP-D2 SOW — sonraki sprint (SEC26+ scope), pre-reg ile dön
2. D3 4h timeframe pivot — düşük öncelik, opsiyonel
3. Hacim sınıfı **kapatıldı** lokal optimum hipotezi 5. teyit; sonraki sprint
   açıları:
   - data_engineer paralel sprint sonucu (funding/OI/onchain integration)
   - alternative timeframe (4h proper sprint with adjusted fee model)
   - cross-asset (forex sec8'den dönüş, FX-specific risk preset)
