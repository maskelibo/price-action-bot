---
doc_id: researcher-20260624T080000-time-of-day-session-bias-ny-bo
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-24T08:00:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, time_of_day, session_bias, brooks_bo, crypto_perp, weak_rag_support, high_curvefit_risk]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-06-24-TOD-NY-BO

- Tarih: 2026-06-24
- Versiyon: 0.1
- Seed konu: Time-of-day session bias

## 1. İddia (pre-registered, tek cümle, ölçülebilir)

> Binance USDT-perpetual evreninde (top-20 by 90d ADV, survivorship düzeltmeli), 15m timeframe'de, **NY overlap penceresi (13:00–17:00 UTC)** içinde tetiklenen Brooks-tarzı failed-breakout (FBO) **trend-continuation long+short sinyalleri**, 2023-01-01 → 2025-12-31 (3y) periyodunda, fee 7.5bps taker + 5bps slippage altında, sabit %0.5/trade risk + 1R BE + 2R TP konfigürasyonuyla:
>
> - **Net trade expectancy (R-multiple cinsinden ortalama):** μ_NY ≥ μ_other + **0.10R** (mutlak fark)
> - **Per-trade Sharpe (R-bazlı, anüalize-değil):** Sharpe_NY ≥ 1.25 × Sharpe_other
> - **Bootstrap p-value (10k resample, Welch + permutation):** p < 0.005 (Bonferroni-sonrası, k=6 session bucket için 0.05/6 ≈ 0.0083 eşiğine karşı)
> - **Min trade sayısı NY bucket:** N ≥ 400 (yoksa istatistik anlamsız → red)
>
> üretir.

## 2. Null hipotez

H0: μ_NY − μ_other = 0 (session bucket'lar arasında expectancy farkı yok; herhangi bir gözlemlenen fark çoklu test gürültüsü).

H0 reddedilemezse → hipotez tamamen reddedilir.

## 3. Gerekçe (RAG referansları — ZAYIF, dürüst açıklama)

| Kaynak | Alıntı / Bağlam | Bu hipoteze katkı |
|---|---|---|
| [#4 book_extra_dailypriceaction_candlestick_patterns] | "Intraday: Not recommended for beginners; pattern reliability drops significantly" | Negatif kanıt — intraday bucket'larda pattern güvenilirliği DÜŞÜK; bu hipotezi destekleyen değil, **çürütmesi muhtemel** kaynak |
| [#5 Beamish 2026 Hyperliquid] | Long bias gradual rebuild Q2-2026, NY hours dominant | Çok dolaylı; institutional flow NY saatinde yoğun olabilir → mikroyapısal trend-continuation hipotezini *zayıf* destek |
| [#6 Glassnode CME OI] | Institutional rebuild, CME futures activity NY-centric | Aynı şekilde dolaylı, mikroyapı argümanı |

**Dürüst not:** Klasik price-action literatürü (Brooks, Volman, Bennett, Grimes) doğrudan kripto session bias kaydetmedi. Equity FX literatüründen "London/NY overlap = en yüksek likidite/volatilite" bulgusu var ama kripto 24/7 mikroyapısı farklı. Bu hipotez **literatür-zayıf** — özgün bir iddia olabilir veya null bir iddia olabilir. RAG bulgusu yetersiz → SOP-5 uyarınca hipotezi terk etmeyi düşünmem gerekti; tek-koşum keşif (exploratory) olarak işaretliyorum, gate'i geçse bile Lab'e taşımadan ÖNCE 2. bağımsız hipotez tasarımı isteyeceğim.

## 4. Bağımlı Değişkenler (önceden listelendi, ek metrik eklenemez)

1. `mean_R` — trade başı ortalama R-multiple
2. `sharpe_per_trade` — R-bazlı per-trade Sharpe
3. `n_trades` — bucket başı sample size
4. `win_rate` — bilgi amaçlı (anlamlılık testi için değil)
5. `bootstrap_p_value` — Welch + permutation hibrit

**Ek metrik eklenmez.** Sharpe sonradan annualize edilmez (CT-RES-01 anti-pattern, audit_research seed control).

## 5. Bağımsız Değişkenler (önceden donduruldu)

- **Session bucket'lar (k=6, sabit, optimize edilmeyecek):**
  1. `asia_early`: 00:00–04:00 UTC
  2. `asia_late`: 04:00–08:00 UTC
  3. `london_open`: 08:00–12:00 UTC
  4. `ny_overlap`: 12:00–16:00 UTC (NOT: hipotezdeki 13–17 yerine **12–16 UTC sabit** — DST esnekliği TANIMLI sayılır → curve-fit önleme)
  5. `ny_close`: 16:00–20:00 UTC
  6. `asia_handoff`: 20:00–24:00 UTC

  **DİKKAT — Curve-fit kırmızı bayrağı:** İddia metninde "13:00–17:00" yazdım ama pre-registration için bucket'ları **4-saatlik sabit grid'e** sabitliyorum. Eğer bucket boundary'leri kayan pencerelerle optimize edersem (örn 13:00–17:00 vs 12:30–16:30 vs ...), her saatlik kaydırma yeni hipotez = devasa multiple testing inflation. **Sabit grid, no fine-tuning.**

- **Pattern parametreleri (Brooks FBO):** standart kütüphane (signal_chief detector v3.2), parametre değişikliği YOK
- **Risk:** %0.5/trade fixed-fraction (compounding off — backtest compounding inflation lesson)
- **TP/SL:** 2R TP, 1R BE-shift, ATR(14)×1.5 başlangıç SL
- **Sembol evreni:** Top-20 ADV 90d, delisting dahil (survivorship düzeltmeli)
- **Veri periyodu:** 2023-01-01 → 2025-12-31 (3y); OOS: 2026-01-01 → 2026-06-23 (~6m)
- **Fee/slip:** taker 7.5bps, slippage 5bps (konservatif)

## 6. Beklenen p-value ve Çoklu Test Düzeltmesi

- Raw α = 0.05
- k=6 bucket karşılaştırması (NY vs 5 diğer) → **Bonferroni α* = 0.05/6 ≈ 0.0083**
- Hedef: p < 0.005 (Bonferroni'den daha sıkı → güvenlik tamponu)
- Ek: Benjamini-Hochberg FDR @ q=0.10 (yumuşak kontrol)
- Eğer Optuna/grid sweep yapılırsa N_trial × bucket sayısına göre tekrar düzeltilir

## 7. Stop Criteria (önceden taahhüt)

Hipotez **derhal** terkedilir eğer:

1. **In-sample mean_R farkı < 0.05R** (effect size çok küçük, gürültü-eşdeğer)
2. **N_NY < 400** (yetersiz örneklem)
3. **Bonferroni-sonrası p > 0.0083** (anlamlılık yok)
4. **OOS (2026 H1) mean_R farkı, in-sample'ın < %30'u** (overfit kanıtı)
5. **Symbol-out CV'de NY üstünlüğü < 3/5 sembol** (tek sembol baskınlığı)
6. **Bucket boundary perturbation (±1h shift):** 4-saatlik bucket'ı ±1h kaydırdığımda effect %50'den fazla bozuluyorsa → curve-fit
7. **Shuffle baseline:** Returns'leri timestamp'ten ayırıp shuffle ettiğim null modeli p<0.05 ile yenemezsem → red

## 8. Curve-fit Şüphesi (kendi kendine red-team)

Bu hipotezin doğal olarak overfit-eğilimli olduğu noktalar:

1. **Bucket boundary serbestliği:** 24 saatlik continuous bir uzayı bucketlere ayırmak sonsuz freedom verir. Sabit 4h grid ile bunu kapatıyorum ama yine de boundary "şanslı" olabilir.
2. **Multiple testing inflation:** k=6 bucket × {long, short, combined} × {expectancy, Sharpe, win_rate} = 54 olası test. Sıkı Bonferroni şart.
3. **Crypto rejim bağımlılığı:** Asia bias 2024 boğa'da bir, 2022 ayı'da başka olabilir. Regime split (bull/bear/range) zorunlu — en az 2 rejimde NY üstünlüğü tekrarlanmalı.
4. **Survivorship:** Top-20 ADV "bugün" liştesi seçilirse 2023'te listede olmayan semboller dahil edilemez → konservatif: 2023-01-01'de top-20 olanlarla başla, delisting'leri dahil et.
5. **Stress periyod:** 2024-08 Yen carry günü NY saatinde — single-day outlier bütün edge'i taşıyabilir. Bu günü dışlayan robustness koşusu zorunlu.
6. **"Mantıklı hikâye" tuzağı:** "NY = institutional money = trend continuation" anlatısı seksi ama anti-narrative bias kuralı uyarınca sayı kazanır. Hikâyeyi reddediyorum, sadece istatistik.

## 9. Beklenen Sonuç (kişisel prior)

Confidence: **low**. Beklentim:
- ~%60 olasılıkla H0 reddedilemez (NY etkisi gürültü)
- ~%25 olasılıkla in-sample p<0.005 ama OOS düşer → overfit kararı
- ~%10 olasılıkla gerçek küçük edge (<0.10R) → effect-size gate'i geçemez, red
- ~%5 olasılıkla anlamlı + OOS-stabil → Lab tournament adayı

Yani **bu hipotezin %95 olasılıkla reddedileceğini** beklemek sağlıklı. Bu Researcher kültürü: hipotezlerin %80+ reddedilir, sağlıklıdır.

## 10. SOP-4b Iterate Politikası (önceden taahhüt)

Eğer aylık ROI > 0 AMA DD yıkıcı çıkarsa → reddetmek YASAK. v2 iterate patikaları (önceden çizilmiş):
- v2-risk: risk_pct 0.5% → 0.25%
- v3-bucket-tighten: NY bucket'ı 12–16 yerine 12–14 (yarıya indir, daha keskin pencere — AMA pre-registered alternatif)
- v4-symbol-subset: edge negatif sembolleri çıkar
- v5-regime-filter: sadece trend-up rejimi (ADX>25)

Iterate budget: maks 5 versiyon (persona hard limit).

## 11. Reproducibility

- git_hash: (backtest çalıştırılınca doldurulur)
- config_hash: SHA256(backtest_config.yaml) (çalıştırma anında)
- data_hash: data/parquet/ snapshot SHA256
- seed: 42 (bootstrap için sabit)

## 12. Karar Sonrası Çıktı

Backtest tamamlandığında `memory/researcher/backtest_results/2026-06-24-time-of-day-session-bias-ny-bo.json` yazılacak, sonra rapor `reports/research/HYP-2026-06-24-TOD-NY-BO.html`.

Karar matrisi:
- Tüm gate ✓ + tüm robustness ✓ → Lab tournament adayı (ama önce 2. bağımsız hipotez tasarımı şart, literatür zayıf)
- Pozitif edge + bir gate fail → SOP-4b iterate v2
- mean_R < 0.05R veya p > 0.0083 → kesin red, gerekçeli arşiv

---

**Bu hipotez kod yazılmadan önce commit edilecek. Hash dondurulur. Sonraki adım: pre-registration commit → backtest config türetme → engine run.**
