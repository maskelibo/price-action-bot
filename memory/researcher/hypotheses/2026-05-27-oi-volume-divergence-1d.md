---
doc_id: researcher-20260527T140000-oi-volume-divergence-1d-v0p1
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-27T14:00:00Z
status: DRAFT
confidence: low
depends_on: [researcher-20260512T120000-funding-oi-divergence-reversal-v0p1]
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [open_interest, volume, divergence, wyckoff_effort_result, perp_microstructure, no_rag_support]
supersedes: null
hash: null

hypothesis_id: 2026-05-27-oi-volume-divergence-1d
date: 2026-05-27
author: researcher_agent (claude-opus-4-7)
version: 0.1
parent_strategy: none (novel; differentiated from 2026-05-12-funding-oi-divergence-reversal)
backtest_possible: true
data_requirements: [1d_ohlcv, daily_open_interest]
expected_correlation_w_top10: target < 0.20
rag_support: NONE — corpus returned 0 hits; novelty risk flagged
---

# HYP-2026-05-27-OIVD — OI/Volume Effort-vs-Participation Divergence (1D Perp)

## 0. RAG Disclosure (SOP-5)

> RAG corpus boş hit döndü. SOP-5 gereği bu hipotez **özgün-iddia / sıfır-destek** kategorisinde. Wyckoff "Effort vs Result" prensibi (volume = effort, price = result) yaygın bilgi olarak biliniyor; bu hipotez bu prensibe **OI'yi üçüncü eksen olarak ekler** (= participation). Ama hipoteze özgü bir referans gösterilemiyor. Sonuç: gate eşikleri standarttan **bir kademe daha sıkı** tutuldu; Bonferroni düzeltmesi sertleştirildi.

## 1. Pre-Registered İddia (TEK CÜMLE, ÖLÇÜLEBİLİR)

> 1D timeframe'de, son **5-bar** penceresinde **|Δprice| z-skor > +1.0 (yön=±1)** iken
> **OI 5-bar yüzde değişimi > +%8** ve **eş zamanlı volume 5-bar z-skor < -0.5**
> (= fiyat hareketi var, OI artıyor ama hacim onaylamıyor → "stacked, low-conviction")
> oluştuğunda; ardışık t veya t+1 barında **fiyat yönüne karşı rejection candle**
> (shooting star / hammer / bearish-bullish engulfing) ile teyit edildiğinde,
> 2021-01-01 → 2024-12-31 in-sample, 2025-01-01 → 2026-04-30 OOS, BTC+ETH+SOL+BNB+AVAX+LINK
> (6 perp, survivorship-dahil) evreninde:
>
> - **OOS net yıllık return > +%18** (fees 7.5bps taker + 5bps slip dahil)
> - **OOS Sharpe > 0.9**
> - **OOS MaxDD < %22**
> - **Profit Factor > 1.45**
> - **Win Rate > %55**
> - **Avg R-multiple > 1.4**
> - **Shuffle baseline p < 0.02**
> - **Walk-forward (3y/6m, step 3m) pencerelerin ≥ %70'i pozitif**

## 2. Null Hipotez (ne olursa çürür)

> H0: OI ve Volume "divergence" sinyali, sadece **5-bar |Δprice| z-skor > +1.0 + rejection candle**
> filtresinin başarısını **istatistiksel olarak iyileştirmez** (Δ Sharpe ≤ 0.10, Δ WR ≤ +%2,
> Welch-t p > 0.10).
>
> H0 reddedilemezse → divergence katmanı gürültüdür → strateji reddedilir.

## 3. Dependent Variables (önceden taahhüt)

1. Net annualized return (OOS)
2. Sharpe (OOS, daily-aggregated returns)
3. Sortino (OOS)
4. MaxDD (OOS)
5. Profit factor (OOS)
6. Win rate (OOS)
7. Avg R-multiple (OOS)
8. Trade frekansı (OOS, trades/yıl)
9. Korelasyon ρ — futures5m_phoenix Top-10 cluster (90d rolling)
10. Welch-t istatistiği: confluence-filter ON vs OFF

> Bu metrikler **çıktı raporunda ZORUNLU**. Başka metrik raporlanırsa post-hoc seçim olur.

## 4. Independent Variables (parametre uzayı — TAAHHÜT)

| Parametre | Aralık | Adım | Notlar |
|---|---|---|---|
| price_zscore_window | {5} | sabit | Pencere oynanmaz (curve-fit önleme) |
| price_zscore_thr | {+0.8, +1.0, +1.2} | 3 nokta | Daha ince grid YASAK |
| oi_pct_change_thr | {+0.06, +0.08, +0.10} | 3 nokta | |
| vol_zscore_thr | {-0.3, -0.5, -0.7} | 3 nokta | |
| sl_atr_mult | {1.5, 2.0, 2.5} | 3 nokta | ATR14 |
| tp_R | {1.5, 2.0, 2.5} | 3 nokta | |
| time_stop_bars | {5, 7, 10} | 3 nokta | |

Toplam kombinasyon: 3^6 × 1 = **729 cell**. Optuna n_trials=120 (TPE + Median pruner) bu uzayın <%20'sini örnekler; **kalanı raporda "unexplored" olarak işaretlenir.**

## 5. Beklenen p-value & Multiple-Testing Correction

- Single-best cell raw p hedefi: < 0.005
- **Bonferroni:** α_corrected = 0.05 / 729 = **6.86e-5** → "best cell" bu eşiği geçmek zorunda **değil**; bunun yerine **median trial Sharpe > 0** + **Top-5%-trial OOS Sharpe > 0.9** + **Shuffle baseline p < 0.02**.
- **Benjamini-Hochberg (FDR=0.05):** Top-10 trial OOS Sharpe değerleri shuffle-null'a karşı BH-anlamlı olmalı.
- **DSR (Deflated Sharpe Ratio)** Bailey-López de Prado: DSR_p < 0.05 → terfi adayı.

## 6. Stop Criteria (önceden taahhüt — esnetilmez)

| Koşul | Aksiyon |
|---|---|
| In-sample Sharpe < 0.5 | Araştırma terkedilir, learning.md'ye yazılır |
| In-sample / OOS Sharpe oranı > 2.0 | Overfit kabul, reddedilir |
| Best params parametre aralığının uç değerinde (ör. price_zscore_thr=+1.2 ve tüm grid içinde tek pozitif cell o) | Reddedilir |
| Confluence ON vs OFF Welch-t p > 0.10 | Null kabul, reddedilir |
| Tek sembolün toplam P&L katkısı > %50 | Reddedilir (single-name dependency) |
| Tek bir 30-gün penceresinin toplam P&L katkısı > %40 | Reddedilir (single-period dependency) |
| Shuffle baseline 1000 permütasyon p > 0.05 | Reddedilir |
| Symbol-out CV min Sharpe < 0.4 | Reddedilir |
| Regime split — 3 rejimden ≥ 2'sinde pozitif değil | Reddedilir |
| LUNA / FTX / 2024-08 stress: cumulative loss > %15 herhangi birinde | Reddedilir |

## 7. Curve-Fit Şüphesi (DELİBERATE FLAGGING — SOP-5)

Aşağıdaki kırmızı bayraklara **özellikle dikkat:**

1. **3-eksen confluence (price-z + OI-Δ + vol-z) = 3 serbestlik derecesi.** Her ekseninde 3-nokta grid var. Trial sayısı OOS pencere sayısına oranla yüksek olursa **multiple-testing yutması** kaçınılmaz.
2. **RAG-destek YOK.** Wyckoff effort-result genel prensip ama "OI participation axis" benim sentezim; literatür ackn'ı yok. **Confirmation bias riski yüksek.**
3. **OI verisi kripto-perp'e özgü** — adapter sembol setinden farklı borsa (Bybit, OKX) OI'sini gerektirebilir; **survivorship bias riski**.
4. **5-bar pencere kısa.** Daha uzun (10-15 bar) deneme de yapılmalı ama **ek pencere = ek deneme = ek correction**. Bu yüzden 5-bar **önceden taahhütlü**, başka pencere denenirse hipotez yeniden pre-register edilir.
5. **"Eş zamanlı" tanımı tek bar (t).** Kayma denemesi (örn. OI artışı t-1, volume düşüşü t) yapılırsa **post-hoc**. **Yasak.**
6. **Rejection candle 3 alt-tipi** — Bulkowski-tarzı patternler kabul edilirse curve-fit alanı genişler. Sadece **ön tanımlı 3 candle** (shooting star, hammer, engulfing) kullanılacak; başkası eklenirse pre-registration ihlali.

**Beklenti:** Bu hipotezin **reddedilme olasılığı > %70**. Bu sağlıklı.

## 8. Edge Mekanizması — Niye (Eğer) Para Kazanır?

- **Wyckoff Effort-Result:** Fiyat hareketi var (effort = price displacement) ama hacim yok (low participation) → hareketin sürdürülebilirliği zayıf.
- **OI artıyor + volume düşük:** Yeni pozisyonlar açılıyor (= stacking), ama spot/perp emirleri **agresif değil** (= passive limit fill, taker hacmi yok). Bu, **tetiklenmeye hazır birikim**.
- **Rejection candle:** Bu "stacked but unproven" yapının üstünde fiyatın geri çevrilmesi, stack'in **yanlış tarafta** olduğunun ilk işareti.
- Beklenen win mekanizması: Stack-tarafının likidasyonu → kısa-orta vadeli reversal.

## 9. Beklenen Korelasyon — Top 10 ile

| Hedef | Eşik |
|---|---|
| Avg ρ(strateji, Top-10 üyesi) | < 0.20 |
| Max ρ tek bir üyeyle | < 0.35 |
| Korelasyon en yüksek beklenen: cvd_spike_fade (volume-tabanlı) | < 0.40 |
| Korelasyon en yüksek beklenen: funding-oi-divergence (HYP-2026-05-12-005) | < 0.50 — **eğer > 0.50 ise bu hipotez gereksiz, reddedilir** |

## 10. Stress Test Beklentisi (önceden taahhüt)

| Period | Beklenti | Eşik |
|---|---|---|
| 2022-05 LUNA cascade | Strateji **tetiklenmemeli** (hacim patlaması → vol-z > -0.5 olmaz, filtre eler) | cumulative P&L > -%5 |
| 2022-11 FTX | Aynı: hacim explosion ⇒ filtre eler. | > -%5 |
| 2023 ranging | Az trade; nötr. | > -%5 |
| 2024-03 ATH dump | SHORT setup ideal: OI yüksek, hacim göreceli düşük (top'ta apati). | > +%3 |
| 2024-08 Yen carry | Cross-asset cascade; hacim explosion → filtre eler. | > -%5 |

**Önemli:** Bu strateji **flash-crash kazanan değil**; **slow-stacking reversal** stratejisi. Cascade'lerde nötr olması beklenir, kazanan değil.

## 11. Veri Erişimi

- **OHLCV 1D:** DuckDB `data/ohlcv_1d.duckdb` (mevcut)
- **OI günlük:** Binance `https://data.binance.vision/data/futures/um/daily/openInterestHist/` (5 dakikalık snapshot → günlük aggregate)
- **3y tarih:** 2021-01-01 → 2024-12-31 in-sample, 2025-01-01 → 2026-04-30 OOS
- **Sembol setinin SURVIVORSHIP DAHİL doğrulaması zorunlu** — delisting tarihinde pozisyon kapatma, evren tarihsel.

## 12. Backtest Engine Setup

```
backtest.engine.run(
  hypothesis_id='2026-05-27-oi-volume-divergence-1d',
  universe=['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','AVAXUSDT','LINKUSDT'],
  timeframe='1d',
  start='2021-01-01',
  in_sample_end='2024-12-31',
  oos_end='2026-04-30',
  fees_bps_taker=7.5,
  fees_bps_maker=-1.0,
  slippage_bps=5.0,
  initial_capital=10_000.0,
  risk_per_trade=0.01,
  extra_data={'open_interest': oi_loader(...)},
)
```

## 13. Karar Akışı

```
1. OI verisi indirme + DuckDB cache (data_engineer dispatch)
2. Veri kalite raporu (gap/anomaly)
3. In-sample backtest (Optuna n_trials=120, TPE)
4. Confluence-ON vs OFF Welch-t (null testi)
5. SOP-3 Robustness suite (8 madde)
6. DSR + BH correction
7. Korelasyon analizi (Top 10 cluster)
8. Stress periodlar
9. Karar: terfi adayı / red / "belirsiz, ek veri"
10. Çıktı: reports/research/oi-volume-divergence-2026-05-27.html
```

## 14. Önceden Açıklanmış Açıklamalar (post-hoc savunmayı engellemek için)

- Eğer best cell parametre uç değerinde → **reddet**, "ama mekanik makul" denmez.
- Eğer Welch-t p > 0.10 → **reddet**, "ama Sharpe yüksek" denmez.
- Eğer LUNA/FTX'te beklenenden iyi performans → **şüphelen**, "şanslı" varsayımıyla shuffle re-run.
- Eğer ρ(funding-oi-divergence) > 0.50 → **reddet**, "yine de portföye katar" denmez.

## 15. Reproducibility Footer

```
git_hash: <to-be-filled at backtest run>
config_hash: <to-be-filled>
data_hash: <to-be-filled>
oi_data_source_hash: <to-be-filled>
```

---

## Notes for Reviewers

- **lab_scientist:** Tournament gate'lerimle örtüşüyor mu? Özellikle DSR ve BH correction yeterli mi?
- **risk_officer:** 6-sembol evreni ve %1 risk-per-trade kombinasyonu portföy korelasyon limitlerini ihlal etmiyor mu (eğer terfi olursa)?
- **adversary_engineer:** "Stacking + low volume" sinyalinin hangi kötü-niyetli market-maker stratejisiyle karıştırılabileceğini stress-test et: spoofed OI? Wash trade volume suppression? Bu sinyali nasıl kandırırsın?
