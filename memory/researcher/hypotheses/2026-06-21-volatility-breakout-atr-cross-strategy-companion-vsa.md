---
doc_id: researcher-20260621T221059-volatility-breakout-atr-cross-strategy-companion-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-21T22:10:59Z
status: DRAFT
confidence: low
depends_on:
  - configs/strategies/vsa_climax_test.yaml
requested_review_from: [lab_scientist, risk_officer]
tags: [cross_strategy, low_corr_companion, volatility_breakout, kaufman, opening_range, atr, pre_registered]
supersedes: null
hash: null
---

# Hipotez: Volatility / Opening-Range ATR Breakout (1D) — vsa_climax_test ile Düşük Korelasyonlu Companion

- **Hipotez ID:** HYP-2026-06-21-vol-breakout-cross-corr-vsa
- **Tarih:** 2026-06-21
- **Versiyon:** 0.1
- **Pre-registered (kod öncesi):** ✓
- **Seed:** Cross-strategy edge keşfi — aktif `vsa_climax_test` ile düşük korelasyonlu (raftaki 66 adaydan birini seçmek yerine, mekanik temelden farklı yeni bir aday).
- **Mekanizma farkı (neden korelasyon düşük beklenir):**
  - `vsa_climax_test`: hacim-spike + wide-range exhaustion → **mean-revert / fade**, bar kapanışında karar.
  - Bu hipotez: **stop-emirli momentum breakout** (Kaufman volatility / opening-range, ref [#5 Kaufman]). Tetik bar **içinde** seviye kırılınca, hacme bakmadan.
  - Yön (continuation vs reversal), tetik mekaniği (close-trigger vs stop-emir) ve volatilite ortamı (her ikisinin de yüksek vol istemesi paralellik riski — ölç).

## 1. İddia (tek cümle, ölçülebilir)

> 2023-01-01 → 2025-12-31 dönemi, `all_liquid` USDT-perpetual evreni (delisting'ler dahil), 1D timeframe'de; her UTC günün açılışından itibaren fiyat **Open ± k·ATR(14)** seviyesini geçtiğinde stop-emirle giren, **1.5·ATR SL**, **2·ATR TP**, fee 7.5 bps taker + 5 bps slip kabulüyle simüle edilen "volatility breakout (Kaufman, ref [#5])" stratejisi aşağıdaki ölçütlerin **tümünü** sağlar:
>
> 1. **OOS yıllık net Sharpe ≥ 1.0** (fee+slip dahil),
> 2. **OOS MaxDD ≤ %25** (equity-base),
> 3. **OOS profit factor ≥ 1.30**,
> 4. **OOS trade count ≥ 200** (istatistik anlam için min örneklem),
> 5. **`vsa_climax_test` ile günlük getiri Pearson korelasyonu |ρ| ≤ 0.30** (companion kriteri — bu kırılırsa hipotez "cross-strategy" iddiasını kaybeder, gate'i geçse bile reddedilir).

## 2. Gerekçe (RAG referansları + neden anlamlı)

- **[#5 Kaufman summary]**: "Open ± k·ATR breakout, k∈[0.5,1.0], SL = giriş − 1.5·ATR, TP = bar/gün sonu kapanış veya 2·ATR. **Yüksek win rate (~%55) küçük R ile**, news-driven günlerde güçlü, düşük-vol günlerinde tetiklenmez."
  - Kripto bağlamına aktarım risklidir — Kaufman örnekleri eşit ağırlıklı equity index'leri ve futures üzerinde. **Bu hipotez bu aktarımın geçerli olup olmadığını test eder; geçersizse açıkça reddederiz.**
- **[#6 Market Structure / Order Flow]**: BOS close-tabanlı kırılım crypto 1D'de "yüksek mekanik çalışabilirlik" puanı (n=3); benim hipotezimde stop-emirli tetik, BOS'un kapanış-onay versiyonundan **daha hızlı ama daha gürültülü** — false-break riski yüksek. Bu yüzden ATR-orantılı tampon zorunlu.
- **[#1 Lopez de Prado kapı kriterleri]**: DSR<0.5, PBO>0.5, IS/OOS Sharpe oranı >3, parametre/sample >1/30 — bu hipotezi gate'lerken **mutlak şart**. Aşağıda numerik olarak bağlanmış.
- **vsa_climax_test ile fark hipotezi**: VSA climax exhaustion → karşı yöne fade; opening-range breakout → yön devamı. Aynı volatilite günlerinde tetiklenebilirler ama yönleri zıt → **korelasyon |ρ|≤0.30 makul beklenti, ama doğrulanmalı**. Aksi durum (yüksek korelasyon) red sebebi.

## 3. Null hipotez (ne olursa çürür)

- **H0a:** OOS yıllık net Sharpe ≤ 0.5 (sıfırdan ayırt edilemez kalite).
- **H0b:** Shuffle baseline (getirileri 1000× permüte ederek) ≥ stratejinin OOS Sharpe'ı, p ≥ 0.05.
- **H0c:** `vsa_climax_test` ile günlük getiri korelasyonu |ρ| > 0.30 (companion iddiası geçersiz; çift stratejik değer üretmez).
- **H0d:** Bonferroni / Benjamini-Hochberg sonrası p > 0.05.

H0a/b/c/d'den herhangi biri kırılırsa hipotez **REDDEDILIR** (gate'in numerik kısımlarını geçse bile).

## 4. Dependent Variables (önceden donduruldu)

| Metric | Birim | Eşik | Yön |
|---|---|---|---|
| OOS net annualized return | % | ≥ 30 | maksimize |
| OOS net Sharpe | unitless | ≥ 1.0 | maksimize |
| OOS MaxDD (equity-base) | % | ≤ 25 | minimize |
| OOS profit factor | ratio | ≥ 1.30 | maksimize |
| OOS trade count | int | ≥ 200 | constraint |
| Correlation w/ vsa_climax_test (daily ret) | ρ | \|ρ\| ≤ 0.30 | constraint (hard) |
| IS/OOS Sharpe ratio | ratio | ≤ 2.0 | overfit kontrol |
| DSR (Bailey/Lopez de Prado) | unitless | ≥ 0.5 | overfit kontrol |
| PBO | unitless | < 0.5 | overfit kontrol |
| Walk-forward dilim pozitif oranı | % | ≥ 60 | tutarlılık |
| Shuffle baseline p-value | unitless | < 0.05 | randomness vs edge |
| **Curve-fit red flags (auto)** | bool | hepsi false | gate |

## 5. Independent Variables (parametre grid — kasten kaba, dar)

| Param | Aralık | Adım | # değer | Not |
|---|---|---|---|---|
| `k` (ATR multiplier) | 0.5 – 1.0 | 0.25 | 3 | Kaufman önerisi orta-bant |
| `atr_window` | 14 | — | 1 | sabit (Kaufman default) |
| `sl_atr_mult` | 1.5 | — | 1 | sabit (overfit yüzeyini kapatmak için) |
| `tp_atr_mult` | 2.0 | — | 1 | sabit; alternatif "EoD close" ayrıca test edilir (kategorik, +1) |
| `exit_mode` | {fixed_R, eod_close} | — | 2 | tek tek değerlendirilir |
| `direction` | {long_only, both} | — | 2 | kripto 1D'de short edge ayrı bir soru |

**Toplam: 3 × 2 × 2 = 12 trial** (sabit metrik objektif: OOS Sharpe).

**Multiple-testing düzeltmesi:** N=12. **Bonferroni eşiği p < 0.05/12 = 0.00417**. Best trial bu eşiği geçmezse hipotez red.

> ⚠️ **Curve-fit suspicion (kasten not düşülmüştür):**
> - 5-bar pattern + birden fazla eşik (k, sl, tp, exit_mode, direction) → parametre uzayı küçük tutuldu ama hâlâ 12 kombinasyon var.
> - Bulkowski/Kaufman istatistikleri **equity/futures**'tan; **crypto 24/7 perpetual'a aktarım belirsiz** — Open tanımı keyfi (UTC 00:00 seçtim). Saat-of-day duyarlılığı varsa **bias**.
> - `k=0.5` ve `k=1.0` uçlarındaki best param → curve-fit kırmızı bayrak; aralık yeniden açılır ve hipotez askıya alınır (terk değil, "ek veri" durumu).
> - "Cross-strategy companion" iddiasının kendisi **post-hoc rationalization** riski — `vsa_climax_test` ile düşük korelasyon **gerçekten** mekanik mi yoksa sample-rastlantısı mı? Bunu walk-forward dilimlerinin **her birinde** korelasyon kontrolü ile ölç (12 dilim × |ρ|≤0.40, en az 10'unda).

## 6. Beklenen p-value

- Pre-registered: **p < 0.01** (Bonferroni öncesi); Bonferroni sonrası eşik **p < 0.00417**.
- "Çoğu hipotez red olmalı" prior'una göre **ön-tahmin: %30 ihtimalle gate'i geçer**, %70 ihtimalle aşağıdakilerden biri:
  - Net Sharpe < 1.0 (fee + slip eroze eder),
  - `vsa_climax_test` ile |ρ| > 0.30 (her ikisi de yüksek-vol günlerinde tetiklenir → korelasyon çıkar),
  - Crypto 24/7'de "open" tanımı keyfi olduğu için saat-of-day duyarlılığı varsa stres-dilimlerinde patlar.

## 7. Stop Criteria (terkleme koşulları)

- **In-sample (ilk 60 trial-equivalent dilimi):** Sharpe < 0.5 → araştırma terkedilir, "edge yok" notuyla `learning.md`'ye geçer.
- **OOS:** Yukarıdaki 5 numerik şarttan **herhangi biri** kırılırsa → red veya **iterate** (SOP-4b'ye gönder — pozitif aylık ROI ama DD yüksekse v2 patikası).
- **Correlation hard-fail:** |ρ| > 0.30 ise iterate denenmez; bu hipotezin "cross-strategy companion" iddiası geçersizdir, ayrı bir bağlamsız hipotez olarak değerlendirilebilir (yeni doc).
- **Curve-fit kırmızı bayrak (auto)**:
  - Best params parametre aralığının uç değerinde (k=0.5 veya k=1.0) → hipotez **askıda**, "ek veri / aralık genişletme" durumu.
  - IS/OOS Sharpe oranı > 3 → red (Lopez de Prado kriteri [#1]).
  - PBO ≥ 0.5 → red.
  - Walk-forward dilim varyansı > ortalama → red.

## 8. Backtest Setup (yürütme planı)

- **Evren:** `all_liquid` USDT-perpetual, **delisting'ler dahil** (survivorship'siz, bkz. [shared/lessons/survivorship_bias_crypto.md]).
- **Periyot:** 2022-01-01 → 2025-12-31 (4 yıl), train/test split walk-forward (3y train / 6m test, step 3m → 8 dilim).
- **Stress dilimleri (zorunlu, ayrı raporlanır):** 2022-05 (LUNA), 2022-11 (FTX), 2023-03 (USDC depeg), 2024-03 (BTC ATH), 2024-08 (Yen carry).
- **Fee:** 7.5 bps taker, **maker kullanılmaz** (stop emri olduğu için optimistik kabul etmem).
- **Slippage:** 5 bps (perpetual normal); stress dilimlerinde 15 bps ek (LUNA/FTX likidite çekilmesi).
- **Initial equity:** 10,000 USDT.
- **Risk per trade:** %1 (sabit-fraksiyon, compounding **kapalı** — bkz. [shared/lessons/backtest-compounding-inflation.md]).
- **Lookahead testleri:** `tests/test_lookahead.py` zorunlu PASS; karar bar `t` kapanışında, giriş `t+1` open'da değil — bu hipotez **intra-bar stop trigger** olduğu için giriş `t` günü içinde olur; bu durum **özellikle** lookahead testine tabi (`detector(df.iloc[:t+1])` semantiği için stop-fill simülasyonu).

## 9. Reproducibility

- `git_hash`: (doldurulacak — backtest çalıştırılınca)
- `config_hash`: (sabit grid; SHA-256 stamped)
- `data_hash`: (DuckDB snapshot id)
- Hipotez dosyası **commit edildikten sonra** backtest çalıştırılır (pre-registration).

## 10. Karar Şeması

```
1. Lookahead test PASS → devam, FAIL → ÖZÜR + signal_chief'e issue.
2. Backtest çalış, robustness suite tam koş.
3. Numerik gate (5 dependent variable) + correlation gate + curve-fit gate.
4. Hepsi ✓ → Lab tournament'e teslim (lab_scientist).
   Bazı ✓ + bazı ✗ (pozitif edge ama DD/risk):
       → SOP-4b iterate (v2 risk reduction, v3 confluence filter, ...).
   Hiçbiri ✓ → red, learning.md'ye 3 satır gerekçe.
5. Sonuç dosyası: reports/research/2026-06-XX-vol-breakout-atr-companion.html
```

## 11. Gelecek Adımlar

- [ ] Doc'u commit et (pre-registration mührü).
- [ ] `backtest/engine.py` config türet → `configs/research/2026-06-21-vol-breakout-atr.yaml` (taslak).
- [ ] Lookahead test çalıştır.
- [ ] Backtest + walk-forward + robustness suite.
- [ ] `vsa_climax_test` günlük getiri serisini çek, korelasyon hesapla.
- [ ] Karar raporu + bu doc'un status'unu güncelle (REVIEWED → APPROVED/REJECTED).

---

**Reviewer notu (`requested_review_from`):**
- `lab_scientist`: Tournament setup'a hazırlık — gate threshold'ları benim önerimle aynı mı, daha sıkı mı?
- `risk_officer`: 1.5·ATR SL kripto perpetual'da %50 margin-safety kuralını ihlal ediyor mu? (Beklemiyorum çünkü position sizing %1 risk-bound, ama doğrulasın.)
