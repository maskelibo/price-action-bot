---
doc_id: researcher-20260622T120000-mat-hold-continuation-4h
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-22T12:00:00Z
status: PROPOSED
confidence: med
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, cross-strategy, low-correlation, mat-hold, continuation, 4h, curve-fit-risk]
supersedes: null
---

# Hipotez: HYP-2026-06-22-mat-hold-continuation-4h

- **Seed:** Cross-strategy edge keşfi — aktif `vsa_climax_test` (volume reversal) ile **düşük korelasyonlu** bir aday (raftaki 66'dan)
- **Pre-registration:** KOD YAZILMADAN ÖNCE
- **Versiyon:** 0.1

## 1. İddia (ölçülebilir, sayısal)

4H timeframe, top-15 likit USDT perpetual evreni (delisting-aware), 2023-06-01 → 2026-06-01 (3y), Bulkowski "Mat Hold" 5-bar continuation pattern'i:
- Bar1: büyük yön-bar (body/range ≥ p1)
- Bar2-4: Bar1 body aralığında kalan küçük 3 bar (range ≤ p2 × Bar1.range)
- Bar5: Bar1 kapanışını yön doğrultusunda aşan büyük yön-bar
- Giriş: Bar5 kapanışında market
- SL: giriş − sign × p3 × ATR(14)
- TP: p4 × R (sabit hedef, trailing yok)
- Risk: %1 fixed-fraction, ücret 7.5bps taker, slippage 5bps

aşağıdaki sonuçları üretir:

| Metrik | Hedef | Önemi |
|---|---|---|
| Annualized net return (OOS) | > %25 | edge eşiği |
| Sharpe (OOS, walk-forward) | > 1.0 | risk-adj edge |
| MaxDD | < %20 | sermaye koruma |
| Profit factor | > 1.3 | distribution sağlığı |
| Trade sayısı (3y, 15 sembol) | ≥ 150 | istatistik tabanı |
| **\|ρ(PnL_daily, vsa_climax_test)\|** | **< 0.20** | **🎯 ana test** |

> Korelasyon eşiğini geçemezse strateji edge'i olsa bile **REDDEDİLİR** — seed cross-strategy diversifikasyon.

## 2. Gerekçe (RAG referansları)

- **[Bulkowski candlestick #10]** Mat Hold: %74 bullish continuation rate, ortalama hareket %6.1, performance rank **10/103** — Bulkowski katalogunun en güçlü 10 pattern'inden. "Flag pattern'ın mum versiyonu; konsolidasyon sonrası momentum korunur."
- **[Brooks deep catalog #3]** "n-bar high/low aşımı + geri dönüş mekanik, tamamen kodlanabilir. En iyi hipotez adaylarından biri." — Mat Hold de Bar1 range içinde konsolidasyon + Bar5 breakout: tam mekanik.
- **[Lopez de Prado #1]** DSR < 0.5, PBO > 0.5, IS Sharpe > 3×OOS, freedom/sample > 1/30 → red. **Bu kriterler pre-register ediliyor.**
- **[Kaufman #7] (kontrast)** Turtle 20/55-bar breakout: trend-following, %35 win, asimetrik R. Mat Hold da continuation; mekanizma aynı aileden ama 5-bar fine-grained — VSA climax (mean-reversion) ile **ortogonal aile**.
- **[VSA / Wyckoff teorisi]** VSA climax_test = hacim ekstremi + reversal. Mat Hold = saf fiyat + continuation. **Sinyal kaynağı ve yön mantığı zıt** → düşük korelasyon teorik beklenti, ama **ölçülmeden iddia edilemez**.

## 3. Null Hipotezleri (ne olursa hipotezim çürür)

- **H0-edge:** Mat Hold OOS Sharpe'ı 0'dan farksız (shuffle baseline yenmez, p ≥ 0.01).
- **H0-cor:** Günlük PnL serisi `vsa_climax_test` ile |ρ| ≥ 0.20 — cross-strategy edge yok, sadece korelasyonlu kopya.
- **H0-transfer:** Bulkowski US equity daily istatistikleri kripto 4H'a transfer olmuyor (IS<<OOS).

## 4. Dependent Variables

- annualized_net_return, Sharpe (OOS walk-forward), MaxDD, profit_factor, win_rate, trade_count
- **pearson_correlation_with_vsa_climax_test** (daily PnL, 3y örtüşen pencere)
- regime-split Sharpe (bull/bear/range)
- stress-period drawdown (LUNA 2022-05 yok, ama 2024-03 ATH, 2024-08 Yen carry, 2025-Q1)

## 5. Independent Variables (pre-registered, TIGHT GRID)

Curve-fit kaygısıyla **parametre uzayı kasıtlı olarak DAR** tutuldu:

| Param | Aday değerler | Adet |
|---|---|---|
| p1: Bar1 body/range min | {0.6, 0.7} | 2 |
| p2: Bar2-4 max range / Bar1 range | {0.5, 0.7} | 2 |
| p3: ATR çarpanı (SL) | {1.5, 2.0, 2.5} | 3 |
| p4: TP (R multiple) | {2.0, 3.0} | 2 |

**Toplam grid: 2 × 2 × 3 × 2 = 24 kombinasyon.** Optuna YOK — full grid (multiple-testing kontrol edilebilir). Timeframe sabit 4H. Trailing/BE yok (bu sürümde).

## 6. Beklenen p-value

- Shuffle baseline'a karşı: **p < 0.01** zorunlu.
- 24 kombinasyon → **Bonferroni eşiği p_adj = 0.05 / 24 = 0.00208**. Bunu geçemezse anlamlılık reddedilir.
- Best params seçilirken: en yüksek Sharpe DEĞİL; **medyan parametre seti** (sınır parametreler curve-fit). Symbol-out CV'de en stabil olan seçilir.

## 7. Stop Criteria — HERHANGİ BİRİ → ARAŞTIRMA TERK

1. **Medyan IS Sharpe < 0.5** → hipotez ölü, devam etme.
2. **IS / OOS Sharpe farkı > %50** → overfit kırmızı bayrağı (LdP #1).
3. **Bonferroni p > 0.00208** → şans.
4. **|ρ(vsa_climax_test)| ≥ 0.20** → cross-strategy değeri yok, ana red.
5. **Trade sayısı < 100** (3y, 15 sembol) → istatistik anlamsız.
6. **Best params grid sınırında** (örn. p3=2.5 her zaman) → grid yanlış tasarlanmış; **yeniden başla**, çözüm tweaking değil.
7. **Regime split:** bull/bear/range'in en az 2'sinde pozitif olmalı; yoksa rejim-bağımlı şans.
8. **freedom/sample oranı > 1/30** (LdP) → 4 param × ≥150 trade gerekir; trade<120 → RED.

## 8. ⚠ Curve-fit Risk Beyanı

**Kendime karşı dürüst:**
- 5-bar pattern doğası gereği **çok yüksek serbestlik derecesi**: her bar için body, range, position ilişkisi. Açıkça yazılmayan implicit param'lar (örn. "konsolidasyon body Bar1 içinde" — kaç % içinde?) sezgisel ayarlanırsa **curve-fit riski yüksek**. Bu nedenle p1, p2 net oran cinsinden pre-register edildi.
- Bulkowski istatistikleri **ABD hisse senedi günlük**; kripto 4H'a transfer olmama olasılığı yüksek. Asıl risk faktörü budur — pattern istatistiği teorik öncelik, kripto'da kanıtlanmamış.
- "Mantıklı hikâye" (continuation pattern, ortogonal mekanizma) **kabul gerekçesi DEĞİLDİR**. Sayılar konuşacak.
- 24-grid Bonferroni dahi optimistik olabilir — symbol-level çoklu sample bağımlı; **PBO testi** (Lopez) walk-forward sonrası eklenecek.

## 9. Veri & Backtest Setup

- Universe: top-15 USDT perpetual, **delisting-aware** (LUNA, FTT, OCEAN gibi sembolleri tarihçeden çıkarmıyoruz)
- Period: 2023-06-01 → 2026-06-01 (3y; 2022 LUNA shock'u OOS dışında — kasıtlı, transfer riskini görmek için 2024-08 stress periyodu kullanılacak)
- Walk-forward: 24m train / 6m test, step 6m → 4 OOS dilimi
- Fees: 7.5bps taker / -1bp maker (konservatif)
- Slippage: 5bps (4H bar entry için makul)
- Initial: 10k USDT
- Risk per trade: %1 fixed-fraction (compounding değil — `backtest-compounding-inflation` dersi)

## 10. Sonraki Adım

1. Bu doc commit edilir → hash dondurulur (`git_hash`).
2. `backtest/engine.py` config türet → 24-grid full run.
3. Robustness suite (SOP-3): walk-forward + param perturb + symbol-out CV + regime split + stress + shuffle + Bonferroni + **|ρ| ölçümü**.
4. Sonuç raporu → karar:
   - Tüm ✓ + |ρ|<0.20 → terfi adayı → Lab tournament
   - ROI > 0 ama gate fail → **SOP-4b iterate** (v2 risk-reduction / quality filter)
   - ROI ≤ 0 → gerekçeli arşiv (`learning.md`'ye 3 satır)

## 11. Reproducibility

- git_hash: <to be filled at commit>
- config_hash: <derived from this doc>
- data_manifest_hash: <ingest manifest 2026-06-22>
- runner: `backtest/engine.py` vectorbt
- seed: 42 (shuffle baseline 100 seed)

---

**Author:** researcher
**Status:** PROPOSED — review bekleniyor (lab_scientist, risk_officer)
**SLA:** 24h ack
