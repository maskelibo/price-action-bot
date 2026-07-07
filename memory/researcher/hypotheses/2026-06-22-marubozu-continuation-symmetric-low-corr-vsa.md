---
doc_id: researcher-20260622T093000-marubozu-continuation-symmetric-low-corr-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-22T09:30:00Z
status: DRAFT
confidence: low
depends_on:
  - researcher-20260621T140300-mat-hold-continuation-cross-strategy-companion
  - researcher-20260621T220300-volatility-breakout-atr-cross-strategy-companion
  - researcher-20260607T000000-donchian-20-1d-low-corr-to-vsa
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, cross-strategy, low-correlation, marubozu, single-bar-continuation, curve-fit-watch, recurring-seed-warning]
supersedes: null
---

# Hipotez: Bearish/Bullish Marubozu Continuation — Symmetric, Low-Correlation Companion to `vsa_climax_test`

- **Hipotez ID:** HYP-2026-06-22-marubozu-continuation-symmetric
- **Tarih:** 2026-06-22 (TR) / 09:30 UTC
- **Versiyon:** 0.1 (DRAFT, pre-registration — kod yazılmadı)
- **Reproducibility:** git=`<TBD on commit>`, config=`<TBD>`, data=`<TBD>` — bu hipotez **kod yazımından önce** donduruluyor.

---

## 0. ANTI-RECURRING / FISHING-EXPEDITION UYARISI (zorunlu okuma)

> Bu hipotez "Cross-strategy edge keşfi — `vsa_climax_test` ile düşük korelasyonlu strateji" seed'inin **27+'inci** denemesidir. Hafıza taraması:
>
> - Donchian / Turtle / Channel-breakout ekseninde **9 ayrı hipotez** dosyası mevcut (2026-05-08 → 2026-06-14), hiçbiri gate'i geçmedi.
> - Mat Hold (2026-06-21, dün) yazıldı — sonuç henüz tournament'a girmedi.
> - Volman III breakout (2026-06-21) ve ATR volatility breakout (2026-06-21) eşzamanlı denendi.
> - `learning.md` ve weekly-tag-snapshot'lar bu seed için **x26 recurring** uyarısı veriyor.
>
> Bu, **Lopez de Prado kriteri #2'ye (PBO > 0.5) doğrudan tehdittir**: aynı veride yeterince hipotez denersen, biri yanlışlıkla pozitif çıkar. Bonferroni / FDR düzeltmesi yalnızca **bu hipotez içindeki trial sayısı** için değil, **tüm seed-history aile boyutu (n_family ≥ 27)** için uygulanmalı. Stop criteria bu nedenle ek bir aile-düzeyi eşik içeriyor (bkz. §6).
>
> **Eğer bu hipotez de §7 stop criteria'yı tetiklerse, seed'in kendisi `seed_abort_log.jsonl`'a "exhausted — n_family ≥ 28 with zero promotion" notu ile kaydedilecek ve CEO'ya `directive` ile seed-değişimi önerisi sunulacak.** Bu, bu hipotezin tek başına başarısı kadar önemli bir çıktıdır.

---

## 1. İddia (pre-registered, ölçülebilir)

> "1D timeframe'de, USDT-perpetual evreninde (2022-01-01 → 2025-12-31, **survivorship-bias düzeltilmiş**, delisted semboller dahil), aşağıdaki sembol-ajnostik koşullarda:
>
> **Long leg (Bullish Marubozu continuation):**
> - Bar gövdesi (|close − open|) bar range'in (high − low) **≥ %90'ı**,
> - Kapanış bar high'a yakın (close ≥ high − 0.1×(high−low)),
> - **HTF trend filtresi:** 1W timeframe'de EMA50 > EMA200 **VE** son 1W bar bullish (close > open),
> - **Volatilite normalizasyonu:** Bar range ≥ 1.0× ATR14 **VE** ≤ 2.5× ATR14 (outlier rejection — climax/spike ile çakışmayı engelle),
> - **Anti-climax filtresi:** Son 5 barın volume z-score < 2.0 (`vsa_climax_test`'in pozitif örneklerini hipotezin kapsama alanından çıkar — yapısal anti-overlap),
> - Giriş: bar `t+1` açılışında market, slippage 5 bps,
> - SL: bar `t` low − 0.5×ATR14,
> - TP: 2R fixed.
>
> **Short leg (Bearish Marubozu continuation):** Yön simetrisi (RAG #8 Bulkowski %64 continuation rate'i tek-yönde verilmiş; long-side bullish marubozu için akademik destek daha zayıf — bu nedenle long+short paralel test, asimetri tespit edilirse leg'lerden biri elenir).
>
> 3-yıllık out-of-sample (2024-2025) penceresinde, fee 7.5 bps taker / −1 bp maker + 5 bps slip dahil:
>
> - **Annualized net return > %18** (yıllık),
> - **OOS Sharpe > 0.8** (Chan'in single-asset retail-realistic alt sınırı — RAG #9),
> - **MaxDD < %22** (live champion DD bandının iki katından az),
> - **Profit factor > 1.3** (Marubozu'nun düşük WR profiline uygun, asimetri R'de),
> - **Trade count (OOS) ≥ 200** (alt sınır; <200 ise istatistik anlamsız),
> - **30-day rolling Pearson correlation with `vsa_climax_test` daily PnL: |ρ̄| < 0.20** ve **|ρ_max| < 0.35** (cross-strategy edge'in asıl kriteri — Sharpe değil bu),
> - **Bonferroni-corrected p-value < 0.05**, **family-corrected p < 0.05 / n_family** (n_family ≥ 28, bkz. §0)."

**Tek cümle özet:** Marubozu single-bar continuation, sıkı HTF + anti-climax + volatility-normalization filtreleriyle, `vsa_climax_test`'e yapısal olarak ortogonal ve net-positive bir companion stratejidir.

---

## 2. Null Hipotez (H0)

> "Marubozu continuation'ın net annualized return'ü 0'a yakın (|μ_ann| < %5), Sharpe < 0.3, ve `vsa_climax_test` ile 30-day rolling |ρ̄| ≥ 0.20 olur — yani ne edge ne diversification sağlar."
>
> Shuffle baseline (entry tarihlerini shuffle eden null model) bu hipotezi p < 0.05 ile yenmek **zorunda**, aksi takdirde edge istatistiksel olarak şanstır.

---

## 3. Gerekçe — RAG Referansları

| # | Kaynak | Argüman |
|---|--------|---------|
| #8 | `book_candlestick_statistics` | Bearish Marubozu **bearish continuation rate %64**, average move %4.9, performance rank 22/103. Bulkowski klasik equity datası üzerinde; **kripto kalibrasyonu yok — curve-fit riski (§5).** |
| #1 | `book_lopez_summary` | Strategy production kriteri: DSR ≥ 0.5, PBO ≤ 0.5, IS Sharpe ≤ 3·OOS Sharpe. Bu hipotezin tüm gate'leri bu kriterlere bağlandı. |
| #9 | `book_chan_summary` | Single-asset Sharpe alt sınırı 0.8; regime-conditional ensemble yaklaşımı (cross-strategy edge ile uyumlu meta-yapı). |
| #2 | `book_candlestick_statistics` | Inside bar (Bulkowski rank 78/103) ile karşılaştırma — Marubozu'nun rank 22'si **akademik literatürde inside bar'dan ~3.5× daha güçlü**, ancak hâlâ rank top-20'nin altında değil. |
| (negatif) | shared/lessons/`smc-course-no-edge.md` | SMC mekanikleri (BOS/CHoCH) **3 ayrı testte RED** — bu nedenle BOS-tarzı struktural breakout adayı bilinçli olarak elendi; market-structure tabanlı düşük-korelasyon arayışı kapatıldı. |

**RAG'de bulunan ama bu hipotezde KULLANILMAYAN ve nedeni:**
- RAG #4 Golden Cross: zaman ölçeği uyumsuz (long-horizon, 1D-bazlı companion için trade frequency düşük).
- RAG #5 ATR Open-Range Breakout: intraday — bizim primary TF 1D, uymaz; ayrıca 2026-06-21'de denendi (`volatility-breakout-atr-...`).
- RAG #7 Donchian 20/55: **9 önceki denemede gate'i geçmedi** (§0).
- RAG #6 BOS/CHoCH: SMC lesson-learned (RED, 3×).
- RAG #10 Mat Hold: **dün denendi** (`2026-06-21-mat-hold-...`).

---

## 4. Bağımlı Değişkenler (pre-registered metrics, **DEĞİŞTİRİLEMEZ**)

1. Annualized net return (% / yıl, fee+slip sonrası)
2. OOS Sharpe (gün-bazlı, √252 annualize)
3. MaxDD (% of starting equity, daily mark-to-market)
4. Profit factor (gross_win / gross_loss)
5. Trade count (OOS, 2024-2025)
6. **Cross-strategy correlation:** 30-day rolling Pearson(daily_pnl_marubozu, daily_pnl_vsa_climax_test); raporlanan: μ(ρ), max(ρ), min(ρ).
7. Win rate (info only — Marubozu WR'i düşük beklentidir, gate değil)
8. Avg R-multiple per trade (target ≥ 0.15)
9. p-value vs shuffle baseline (bootstrap n=1000)
10. PBO (Lopez de Prado, k=10 partitions)
11. DSR (Lopez de Prado deflated Sharpe)

---

## 5. Bağımsız Değişkenler — Optimize Edilebilenler vs Dondurulanlar

### Dondurulan (curve-fit'i önlemek için pre-registration ile lock):
- Marubozu body/range eşiği: **%90** (literatürden, optimize edilmez).
- HTF EMA pair: **50/200 on 1W** (klasik, optimize edilmez).
- Volatilite penceresi: **ATR14** (klasik, optimize edilmez).
- Volume z-score window: **20 bars** (anti-climax filtre, optimize edilmez).
- Volume z-score eşiği: **< 2.0** (klasik 2σ, optimize edilmez).
- Risk per trade: **%0.5** (configs/risk live current).

### Optimize edilen (sıkı parametre uzayı, **maksimum 3 parametre × 8 değer = 24 grid noktası**):
- ATR-range alt sınır multiplier: ∈ {0.75, 1.0, 1.25} (3 değer)
- ATR-range üst sınır multiplier: ∈ {2.0, 2.25, 2.5, 2.75} (4 değer)
- SL ATR buffer: ∈ {0.25, 0.5, 0.75} (3 değer)
- TP R: **2.0 fixed** (optimize edilmez)

**Toplam trial:** 3 × 4 × 3 = 36 grid + 50 random perturbation seed = **n_trials = 86**.

**Bonferroni hedef:** raw p-value < 0.05 / 86 = **0.00058**.
**Family-level (n_family ≥ 28):** Bonferroni × 28 = **p < 0.0000207** — **bu eşik çok sert, gate'i geçmek son derece zor; bu kasten böyle** (§0 fishing-expedition tepkisi).

---

## 6. Robustness Suite Hedefleri (SOP-3, **zorunlu — atlatılamaz**)

| Test | Eşik | Karar etkisi |
|---|---|---|
| Walk-forward (3y/6m, step 3m) | OOS Sharpe pozitif dilim ≥ 8/12 | <8 ise REJECT |
| IS/OOS Sharpe farkı | ≤ %30 (Lopez kriter #4: IS ≤ 3·OOS) | aşılırsa REJECT |
| Param perturb (±%10, 50 seed) | Sharpe ortalama kayıp ≤ %25 | aşılırsa REJECT |
| Symbol-out CV | min OOS Sharpe ≥ 0 (her sembol leave-one-out) | <0 ise REJECT |
| Regime split (bull/bear/range) | En az 2 rejimde net pozitif | <2 ise REJECT |
| Stress: LUNA 2022-05 | Aylık DD ≤ %10 | aşılırsa REJECT |
| Stress: FTX 2022-11 | Aylık DD ≤ %10 | aşılırsa REJECT |
| Stress: 2024-08 Yen carry | Aylık DD ≤ %8 | aşılırsa REJECT |
| Shuffle baseline | p < 0.05 (bootstrap n=1000) | aşılırsa REJECT |
| PBO (Lopez) | ≤ 0.5 | aşılırsa REJECT |
| DSR (Lopez) | ≥ 0.5 | aşılırsa REJECT |
| **Cross-correlation gate** | μ(ρ_30d) < 0.20 ve max(ρ_30d) < 0.35 vs vsa_climax_test | aşılırsa **TERFI REDDEDİLİR** (edge varsa bile diversification yok → seed amacı başarısız) |
| Bonferroni (intra-hyp) | raw p < 0.00058 | aşılırsa REJECT |
| **Family Bonferroni (n=28)** | raw p < 0.0000207 | aşılırsa REJECT — fishing kanıtı |

---

## 7. Stop Criteria (erken iptal — **researcher zaman sermayesi koruması**)

Aşağıdaki koşullardan **herhangi biri** in-sample ilk pass'te tetiklenirse, walk-forward / robustness suite **çalıştırılmaz**, hipotez doğrudan red'e gider:

1. **In-sample Sharpe < 0.5** → terkedilir.
2. **In-sample trade count < 300** → istatistik için yetersiz, terkedilir.
3. **In-sample net annualized < %10** → fee/slip sonrası canlıda sıfırlanır, terkedilir.
4. **`vsa_climax_test` ile in-sample μ(ρ_30d) ≥ 0.30** → seed amacı (diversification) imkânsız, terkedilir; edge tek başına olsa bile cross-strategy değer yaratmaz.
5. **Long leg ve short leg arasında PnL asimetrisi > 5×** → yön-bağımlı, market-neutral değil; sadece güçlü leg ile yeniden başlat (v2 iterate, SOP-4b).

---

## 8. Beklenen Sonuç (önyargı kaydı için)

Researcher öznel beklentisi (yazıyorum ki sonradan kendimi kandırmayayım):

> "Bu hipotezin **gate'i geçme ihtimali öznel olarak < %20**. Gerekçe: (a) Bulkowski %64 continuation rate kripto'da fee+slip sonrası ~%55-58'e düşer, edge çok ince; (b) HTF+anti-climax+volatilite filtrelerinin birlikte trade count'u 300 altına çekme riski yüksek; (c) n_family = 28 ile family-Bonferroni eşiği son derece sert. Eğer gate geçilirse en muhtemel mekanizma: ATR-range filtresi 'spike olmayan ama momentum'lu' bar'ları izole ediyor olabilir — bu durumda SOP-4b iterate'e değer pozitif edge."

Bu beklenti sonradan accuracy denetimi için Lab'e iletilecek.

---

## 9. Karar Çerçevesi (sonuçlar geldiğinde)

```
1. RAG: Bulkowski rank 22/103 + Lopez gates + Chan Sharpe sınırı; net-edge için akademik destek orta.
2. Hipotez: Marubozu continuation symmetric, anti-climax filtered, cross-corr gated.
3. Null: edge=0 + ρ̄≥0.20.
4. Pre-registered metrics: §4 listesi DEĞİŞTİRİLEMEZ.
5. Backtest: <TBD>
6. Robustness: <TBD>
7. Karar:
   - terfi → tüm §6 ✓ AND cross-corr gate ✓ AND family-Bonferroni ✓ → Lab tournament
   - iterate (SOP-4b) → aylık ROI > 0 AMA DD/cross-corr fail → v2 risk-cut veya leg-prune
   - red → 1+ §6 hard-fail VEYA §7 stop tetiklendi → seed_abort_log.jsonl + family-exhaust note
8. Gerekçe: <TBD>
```

---

## 10. Curve-Fit ve Confirmation-Bias Kırmızı Bayrakları (kasıtlı self-flagging)

Aşağıdakilerden biri sonuçlarda görülürse, gate geçilse bile **şüphe ile terfi adayı işaretle** (Lab adversary'sine ek refute talebi):

1. Best param'lar grid'in **kenarında** (örn. ATR-range üst sınır = 2.75, en yüksek değer) → daha geniş aralık dene.
2. Toplam net P&L'in **%50'den fazlası** tek bir 3-aylık dilimden geliyor → regime-specific edge, generic değil.
3. Long leg ve short leg arasında **PnL > 3× asimetri** → yön-bağımlı, yapısal değil.
4. Cross-correlation gate'i geçen tek param noktası kalıyor (örn. 36 grid'in sadece 1'i) → unstable diversification.
5. Stress dilimlerinden 2026-08 (Yen carry) ya da 2022-11 (FTX) **sadece-marjin** geçiyor (DD %7-10 arası) → tail-risk gizli.
6. Marubozu pattern'inin firing oranı sembol bazında **çok dengesiz** (örn. trade'lerin %60'ı 2 sembolden) → konsantrasyon riski.

---

## 11. Pre-registration Locked Hash

> Bu doküman bu commit'te dondurulur:
> - `git_hash`: `<bu doc commit edildikten sonra doldurulacak>`
> - `data_hash`: USDT-perp universe @ 2026-06-22 snapshot
> - Backtest configurations bu §1–§7'den **birebir** türetilir; sapma olursa **yeni hipotez doc'u** açılır, eski supersede edilir.

---

## 12. Gelecek Adımlar (sırayla, atlatılamaz)

1. Pre-registration commit (bu dosya).
2. Family-history sentezi: 28 prior hipotezin abort gerekçeleri tek tablo (separate doc) — Researcher learning'e materyal.
3. Backtest config generate (`configs/strategies/_candidates/marubozu_cont_v1.yaml` taslak).
4. Veri kalite gate (Data dept onayı).
5. In-sample backtest → **§7 stop kontrolü**.
6. Geçerse robustness suite.
7. Karar yaz → ADR.
8. Lab'e teslim.

---

## 13. Imza

- **Author:** researcher (Head of Quantitative Research)
- **Confidence:** low (subjective; §8'de gerekçeli)
- **Status:** DRAFT — review için `lab_scientist`, `risk_officer`, `adversary_engineer`'a gönderilir (Protocol §1 `requested_review_from`).
- **Review SLA:** 24h (risk_officer 6h).
