---
doc_id: researcher-20260612T120000-iii-marubozu-confluence-1d-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-12T12:00:00Z
status: DRAFT
confidence: low
depends_on:
  - researcher-20260610-volman-ii-iii-double-triple-inside-breakout-low-corr-to-vsa
  - researcher-20260607-marubozu-continuation-low-corr-to-vsa
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, low-corr-vsa, confluence, curve-fit-risk-high, null-strict]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-06-12-iii-marubozu-confluence-1d

- **Tarih:** 2026-06-12
- **Versiyon:** 0.1 (pre-registration, kod yazılmadı)
- **Status:** DRAFT — backtest öncesi dondurulacak

## Motivasyon ve Dürüst Bağlam (anti-narrative)

Son 14 günde 32 düşük-korelasyon hipotezi yazılmış; RAG'daki tek-bar/tek-pattern adaylar
(Mat Hold, Donchian, Kaufman vol-breakout, marubozu, BOS, equal-highs, Volman ii/iii,
golden-cross) **tüketilmiş**. Yeni tek-pattern hipotezi p-hacking riski. Bunun yerine **iki
ortogonal RAG kalıbının AND-konfluans** olarak test edilmesi: Volman iii (RAG #2 — 3 ardışık
inside bar, sıkışma) → kırılım yönüne **bullish marubozu** (RAG #8 — body ≥ %90 range, kapanış
high'a yapışık) ile teyit. Hipotez yalın versiyonları **yenmek zorunda**, aksi halde
confluence sadece trade sayısını düşürür.

## 1. İddia (measurable, single set — sweep YOK)

> 1D timeframe, USDT-perpetual evreninde (3y, delisting-aware, n≈19 sembol), **kombine setup**:
>
> 1. Bar `t-3, t-2, t-1`: her biri Bar `t-4`'ün gövdesinin içinde kapanır (iii pattern).
> 2. Bar `t`: **bullish marubozu** — body / range ≥ 0.90, close ≥ Bar `t-4` high (kırılım onayı).
> 3. Trend filtresi: Bar `t` kapanışı 50-EMA üzerinde (sadece long).
> 4. Giriş: `t+1` open.
> 5. SL: Bar `t-4` low (yapısal) veya 1.5×ATR(14), hangisi yakınsa.
> 6. TP: 2R fixed (alternatif TP varyantı YOK — sweep zinciri açmamak için).
> 7. Max hold: 10 bar; süre dolarsa close.
>
> **Pre-committed eşikler:**
> - Marubozu body/range ≥ 0.90 (Bulkowski tanımı, sweep yok)
> - iii: 3 ardışık inside (sweep yok)
> - 50-EMA tek trend filtresi (200-EMA YOK, ek filtre YOK)
> - Risk %1/trade sabit, fee 7.5 bps taker + 5 bps slippage
>
> **Hedef metrikler (3y net, fee+slip dahil):**
>
> | Metric | Hedef | Null (red) |
> |---|---|---|
> | Net annual return | > 25% | < 15% |
> | Sharpe (OOS, walk-forward ortalama) | > 0.80 | < 0.50 |
> | MaxDD | < 22% | > 30% |
> | Profit factor | > 1.40 | < 1.10 |
> | Trade count (3y) | ≥ 80 | < 50 |
> | **Spearman corr w/ vsa_climax_test daily returns** | **< 0.20** | **> 0.35** |
> | **Combined > max(iii_only, marubozu_only) Sharpe × 1.20** | **PASS** | FAIL → kombinasyon değersiz |

## 2. Gerekçe (RAG referansları)

- **RAG #2** (book_candlestick_statistics): Tekli inside bar zayıf (%54 win rate, rank 78/103);
  iii breakout daha güçlü — Volman'ın DD setup'ı bu temel üzerine.
- **RAG #8** (book_candlestick_statistics): Bullish marubozu continuation %64, rank 22/103,
  body/range tanımı net (%90 eşiği Bulkowski'den).
- **RAG #1** (Lopez de Prado): PBO > 0.5 → red, IS/OOS Sharpe > 3× → red, parametre/örnek
  > 1/30 → red. Bu hipotezde **0 sweep parametresi** var (eşikler önceden sabit), free-param
  sayısı = 0 → PBO testi en sert formda çalışacak.

**Curve-fit uyarısı (kendi kendime):** "İki kalıp birleşirse mutlaka daha iyi" bir
**narrative bias**. Bulkowski iki istatistik tek başına; AND-kombinasyonun crypto perp 1D'de
çalıştığı önceden gösterilmedi. **Beklenti: %60 ihtimalle red** (trade count yetersiz veya
combined gain marjinal).

## 3. Null Hipotez (ne olursa çürür)

H0: Kombine setup'ın 3y net Sharpe'ı yalın iii-only veya yalın marubozu-only'den **istatistiksel
olarak farklı değil** (Diebold-Mariano test, two-sided, α=0.05) — yani confluence sadece sample
size'ı düşürüyor, edge ekletmiyor.

## 4. Dependent Variables (önceden ilan — değişmez)

1. Net annual return (compounded, fee+slip dahil)
2. Walk-forward OOS Sharpe (12 dilim, 3y/6m/3m step)
3. MaxDD (account equity bazlı — cumulative PnL DEĞİL; ADR-002)
4. Profit factor
5. Trade count
6. Spearman corr (daily returns × vsa_climax_test daily returns)
7. DSR (Lopez de Prado, Bonferroni-adjusted)
8. Combined vs max(iii_only, marubozu_only) Sharpe ratio

## 5. Independent Variables (HİÇBİRİ optimize edilmiyor — locked)

- iii kuralı: 3 ardışık inside (locked)
- Marubozu eşiği: body/range ≥ 0.90 (locked, Bulkowski)
- Trend filter: 50-EMA only (locked)
- SL: max(Bar t-4 low, 1.5×ATR14) (locked)
- TP: 2R (locked)
- Max hold: 10 bar (locked)
- Risk per trade: %1 sabit (locked)

→ **Free parameters / sample size < 1/100** (PBO en sert form). Sweep YAPILIRSA hipotez
geçersiz, yeniden pre-reg gerekir.

## 6. Beklenen p-value

- Shuffle baseline (n=1000 resample): p < 0.01 (Bonferroni adjusted < 0.05)
- DM test (combined vs yalın): p < 0.05 single hypothesis (Bonferroni yok, tek karşılaştırma)

## 7. Robustness Suite (SOP-3 zorunlu — atlanamaz)

1. Walk-forward 12 dilim (3y/6m/3m step)
2. IS/OOS Sharpe oranı: > 2.0 → overfit, red
3. Symbol-out CV (19 sembol → her birini ayrı dışarıda bırak): min OOS Sharpe > 0.3
4. Regime split (bull/bear/range): en az 2'sinde pozitif net
5. Stress periods: 2022-05 (LUNA), 2022-11 (FTX), 2024-03 (BTC ATH), 2024-08 (Yen carry) →
   yıkıcı kayıp yok (max single-period DD < 15%)
6. Shuffle baseline: returns shuffle, n=1000 → mevcut Sharpe > shuffle 99-percentile
7. **Bonferroni:** çoklu hipotez sayısı = aynı seed'de 32 önceki hipotez × 6 dep var = 192 →
   α/192 ≈ 0.00026 → bu hipotezin shuffle p-değeri 0.0003'den küçük olmalı YOKSA RED.

## 8. Stop Criteria (her biri yeterli sebep — RED)

- ✋ In-sample Sharpe < 0.5 → terk (robustness'a geçme)
- ✋ Trade count (3y, 19 sym) < 50 → istatistik anlamsız, terk
- ✋ IS/OOS Sharpe ratio > 2.0 → overfit, terk
- ✋ Combined Sharpe < max(iii_only, marubozu_only) × 1.20 → confluence değersiz, terk
- ✋ Spearman corr vsa_climax_test > 0.35 → diversification amacı kaybedildi, terk
- ✋ Bonferroni-adjusted shuffle p > 0.001 → çoklu test sonrası anlamlılık yok, terk
- ✋ Regime split: 3 rejimden ≥ 2'sinde net negatif → red
- ✋ Stress period: tek periyotta DD > 20% → red

## 9. Curve-Fit Kırmızı Bayrak Self-Audit (önceden ilan)

| Bayrak | Bu hipotezde durum |
|---|---|
| Free param / sample < 1/30 | ✓ 0 sweep param |
| Best params parametre uzayı sınırında | N/A (sweep yok) |
| Çok ince parametre adım | N/A |
| Trade count < 100 | ⚠ RİSK — 19 sym × 3y, iii nadir kalıp; n ≥ 80 hedef, n < 50 terk |
| Tek periyot/sembol baskın | Robustness #5 + symbol-out CV ile yakalanır |
| WF dilimleri arası varyans yüksek | Robustness #1 + WF Sharpe std/mean < 0.5 |
| Hikaye iyi, sayı zayıf | **EN BÜYÜK RİSK** — anti-narrative §8 §3 stop criteria ile |

## 10. Reproducibility

- git_hash: çalıştırma anında yazılacak
- config_hash: yazılacak
- data_hash: USDT-perpetual evreni, 2023-06-12 → 2026-06-12, build_pool_19sym.py
- seed: 42 (shuffle baselines için), Optuna YOK (sweep yok)

## 11. Beklenen Sonuç (kendi tahminim — bias kontrolü)

%60 ihtimalle **RED** (trade count yetersiz veya combined marjinal).
%30 ihtimalle marjinal pozitif ama Spearman > 0.20 (vsa ile orta korelasyon, diversifier
sınırda).
%10 ihtimalle gerçek edge (kombine setup yalını yenecek).

Bu tahmini şimdi kaydediyorum; backtest sonrası sapma kendi calibration'ım için.

## 12. Sonraki Adım

1. Bu doc → status PROPOSED (lab_scientist, risk_officer review).
2. Onay sonra `backtest/engine.py` çalıştır (sweep YOK, tek config).
3. Robustness suite zorunlu (atlanırsa hipotez geçersiz).
4. Karar: terfi adayı / iterate (SOP-4b) / red — gerekçe ile.
