---
doc_id: researcher-20260527T180000-weekend-gap-fill-stats-1d-v0p1
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-27T18:00:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [weekend_gap, mean_reversion, cme_btc_gap, calendar_effect, retail_narrative, no_rag_support, high_curve_fit_risk]
supersedes: null
hash: null

hypothesis_id: 2026-05-27-weekend-gap-fill-stats-1d-v1
date: 2026-05-27
author: researcher_agent (claude-opus-4-7)
version: 0.1
parent_strategy: none (novel, calendar-effect class)
backtest_possible: true
data_requirements: [1h_ohlcv, 1d_ohlcv, optional_cme_btc_session_calendar]
expected_correlation_w_top10: target < 0.25
rag_support: NONE — corpus returned 0 hits; retail-narrative bias risk EXPLICITLY flagged
---

# HYP-2026-05-27-WGFS — Weekend Gap Fill Statistics (BTC/ETH Perp, 1D)

## 0. RAG Disclosure (SOP-5)

> RAG corpus **boş hit** döndü. SOP-5 gereği bu hipotez **özgün-iddia / sıfır-destek** kategorisinde.
> "CME BTC weekend gap fill" yaygın bir **retail narrative**'dir; ölçülmüş edge'i tartışmalıdır
> ve confirmation-bias mıknatısıdır. Kripto perp **24/7** trade edildiği için "gap" tanımı
> doğrudan değil; **proxy** tanımlar (CME-saatleri pencere getirisi, Fri close → Mon open Δ)
> kullanılacak. Bu hipotez **düşük ön olasılıkla** açılıyor; gate'ler standarttan **bir kademe
> daha sıkı**.

## 1. Pre-Registered İddia (TEK CÜMLE, ÖLÇÜLEBİLİR)

> BTC/ETH USDT-perp evreninde, **"weekend gap"** = Cuma 21:00 UTC (= CME pit close)
> spot/perp fiyatı → Pazar 23:00 UTC (= CME pit reopen) perp fiyatı arasındaki
> getiri olarak tanımlandığında; **|gap| > 1.0 × ATR14(daily)** ve eş zamanlı
> **gap penceresi içindeki kümülatif perp volume z-skoru < +0.0** (= "düşük katılımlı sapma")
> koşulu sağlanan haftalarda; Pazartesi 00:00 UTC açılışında **gap yönüne karşı** giriş yapılıp
> **0.5 × gap-büyüklüğü TP** ve **1.0 × gap-büyüklüğü SL** kullanıldığında;
> 2021-01-01 → 2024-12-31 in-sample, 2025-01-01 → 2026-04-30 OOS, BTCUSDT + ETHUSDT
> (survivorship-dahil, ikisi de tüm dönem aktif) evreninde:
>
> - **OOS Hit-rate (gap-fill ≥ %50 within 72h)** > **%58**
> - **OOS net yıllık return** > **+%12** (fees 7.5 bps taker + 5 bps slip dahil)
> - **OOS Sharpe** > **0.7**
> - **OOS MaxDD** < **%18**
> - **OOS Profit Factor** > **1.35**
> - **OOS Win Rate** > **%52**
> - **Shuffle baseline p < 0.02** (1000 permütasyon, hafta-bazında randomize)
> - **Calendar-shuffle baseline p < 0.05** (Cuma → herhangi başka 21:00 UTC randomize edilirse edge sıfırlanmalı)

**Frekans beklentisi:** ~52 hafta/yıl × hit-oranı ~%30 (filtre eşiği sonrası) ≈ **15-18 trade/yıl**.
Bu sınırda; **trade sayısı < 50 olursa istatistik anlamsız → red.**

## 2. Null Hipotez (ne olursa çürür)

> H0: Weekend window (Fri 21:00 UTC → Sun 23:00 UTC) getiri yönü ile sonraki 72h getiri yönü
> arasında **anti-correlation** YOKtur (Pearson r > -0.10, p > 0.05) ya da **mean reversion
> bias'ı hafta-rastgele shuffle baseline'ından istatistiksel olarak ayrılamaz** (p > 0.05).
>
> H0 reddedilemezse → gap-fill bir gürültü artefaktıdır → strateji reddedilir.
>
> **Ayrı bir H0':** Calendar-shuffle (Fri 21:00 UTC anchor → rastgele bir gün/saat anchor) ile
> aynı eşikler kurulup edge yeniden bulunursa, edge'in **calendar'a özgü olmadığı** kanıtlanmış
> olur → "weekend" özelliği sahte → strateji reddedilir.

## 3. Dependent Variables (önceden taahhüt)

1. Hit-rate: gap'in ≥ %50'sinin 72h içinde "fill" edilme oranı
2. Net annualized return (OOS)
3. Sharpe (OOS, weekly-aggregated returns — trade frekansı düşük olduğu için)
4. Sortino (OOS)
5. MaxDD (OOS)
6. Profit factor (OOS)
7. Win rate (OOS)
8. Avg R-multiple (OOS)
9. Trade frekansı (OOS, trades/yıl)
10. Welch-t istatistiği: weekend-gap-trigger ON vs OFF (gap yokken aynı Mon-açılış reversal trade)
11. Calendar-shuffle p (anchor-rastgele)
12. Korelasyon ρ — futures5m_phoenix Top-10 cluster (90d rolling)

> Bu metrikler **çıktı raporunda ZORUNLU**. Başka metrik raporlanırsa post-hoc seçim olur.

## 4. Independent Variables (parametre uzayı — TAAHHÜT)

| Parametre | Aralık | Adım | Notlar |
|---|---|---|---|
| gap_anchor_open_utc_hour | {21} | sabit | CME pit close — pencere oynanmaz |
| gap_anchor_close_utc_hour | {23} | sabit | CME pit reopen — pencere oynanmaz |
| gap_size_atr_mult | {0.8, 1.0, 1.2} | 3 nokta | ATR14(daily) |
| weekend_vol_zscore_thr | {-0.3, 0.0, +0.3} | 3 nokta | Hafta içi vol baseline |
| entry_session_utc | {00, 01, 02} | 3 nokta | Pazartesi early hour |
| tp_gap_frac | {0.3, 0.5, 0.7} | 3 nokta | Gap'in tamamı YASAK (TP=1.0 retail-bias) |
| sl_gap_frac | {0.8, 1.0, 1.2} | 3 nokta | Gap yönüne devam ederse durdur |
| time_stop_hours | {48, 72, 96} | 3 nokta | Fill olmazsa exit |

Toplam kombinasyon: 3^6 × 1 = **729 cell**. Optuna n_trials=80 (TPE + Median pruner) bu uzayın
<%12'sini örnekler; kalanı raporda "unexplored" olarak işaretlenir.

**TAAHHÜT:** Yukarıdaki grid SABİT. Daha ince adım (örn. 0.05 ATR) denenirse pre-registration
ihlali; hipotez yeniden register edilir.

## 5. Beklenen p-value & Multiple-Testing Correction

- Single-best cell raw p hedefi: < 0.005
- **Bonferroni:** α_corrected = 0.05 / 729 = **6.86e-5**. "Best cell" bu eşiği geçmek **zorunda
  değil**; yerine:
  - **Median trial OOS Sharpe > 0** (gürültüden ayrışmalı)
  - **Top-5%-trial OOS Sharpe > 0.7**
  - **Shuffle baseline p < 0.02** (week-block permütasyon, 1000 iter)
  - **Calendar-shuffle p < 0.05** (anchor-randomize)
- **Benjamini-Hochberg (FDR=0.05):** Top-10 trial OOS Sharpe değerleri week-shuffle null'a karşı
  BH-anlamlı olmalı.
- **DSR (Deflated Sharpe Ratio)** Bailey-López de Prado: DSR_p < 0.05 zorunlu (düşük trade sayısı
  → DSR'a güven olmaz, bu yüzden bootstrap-Sharpe CI [%5, %95] üst sınırı > 0 olmalı).

## 6. Stop Criteria (önceden taahhüt — esnetilmez)

| Koşul | Aksiyon |
|---|---|
| In-sample Sharpe < 0.4 | Araştırma terkedilir, learning.md'ye yazılır |
| In-sample / OOS Sharpe oranı > 2.0 | Overfit kabul, reddedilir |
| Best params parametre aralığının uç değerinde (≥2 parametre uçta) | Reddedilir |
| Welch-t (trigger ON vs OFF) p > 0.10 | Null kabul, reddedilir |
| Toplam trade < 50 (in-sample 4y) | Reddedilir, istatistik anlamsız |
| Tek bir 90-gün penceresinin toplam P&L katkısı > %50 | Reddedilir (single-period dependency) |
| Week-shuffle baseline p > 0.05 | Reddedilir |
| **Calendar-shuffle p < 0.05 değilse** (= edge calendar'a bağlı DEĞİL) | Reddedilir — KEY GATE |
| Symbol-out CV (BTC-out, ETH-out) min Sharpe < 0.3 | Reddedilir (tek-sembol bağımlılık) |
| Regime split — bull/bear/range 3 rejimden ≥ 2'sinde pozitif değil | Reddedilir |
| LUNA / FTX / 2024-08 stress: cumulative loss > %12 herhangi birinde | Reddedilir |

## 7. Curve-Fit Şüphesi (DELİBERATE FLAGGING — SOP-5)

**Kırmızı bayraklar yüksek; her birine özellikle dikkat:**

1. **Retail-narrative magneti.** "CME gap her zaman fill olur" yaygın söylem. Confirmation bias
   yüksek. **Calendar-shuffle gate** (§5) bu hipoteze KARŞI tasarlandı: edge takvime özgü
   değilse retail-narrative artefaktı demektir.
2. **Düşük örneklem.** 4 yıl × ~52 hafta × hit-oranı ~%30 ≈ 60 trade. **DSR güveni zayıf**;
   bootstrap CI mecburi.
3. **8 parametre, 729 cell, 80 Optuna trial.** Trial yoğunluğu cell başına 0.11 — düşük; ama
   gözden kaçan kombinasyonlar **"unexplored" olarak işaretlenir**; post-hoc fine-grid yasak.
4. **Sembol evreni dar (BTC + ETH).** Daha geniş evren (SOL, BNB, AVAX) eklenirse **yeniden
   pre-register**. Burada dar evren BİLİNÇLİ: "gap-fill" terimi tarihsel olarak BTC CME'ye
   atıfla; ETH coverage referans.
5. **TP=1.0 (full fill) yasak.** Retail beklentisi tam-fill üzerine kurulu; kısmi fill (0.3-0.7)
   parametrize edilerek **yatık dağılımlı edge** aranır. Full fill grid'i sokulursa retail-bias.
6. **Anchor saati sabit.** Fri 21:00 UTC = CME close (16:00 ET). Bu saat denenirse başka anchor
   (örn. Sat 00:00 UTC) → calendar-shuffle ile yenilmeli, başka anchor "best" çıkarsa hipotez
   asıl iddiasını çürütmüş olur.
7. **2021-2024 in-sample dönemi BTC bull-bear-bull yarı-döngü.** Bu pencerede "gap fill" rejim-
   bağımlı olabilir. Regime split zorunlu (§6).
8. **OOS dönemi yalnız 16 ay (2025-01 → 2026-04).** Walk-forward 3y/6m bu dönemde **sadece 1-2
   pencere** üretir; yetersiz. Yerine **yıllık step-walk** (year-out 4-fold CV) kullanılacak.

**Beklenti:** Bu hipotezin **reddedilme olasılığı > %80**. Bu sağlıklı ve önceden ilan edilmiştir.

## 8. Edge Mekanizması — Niye (Eğer) Para Kazanır?

Sıralı mekanik (zorunlu okuma):

1. **Cuma 21:00 UTC sonrası likidite düşer.** ABD trading desk'leri kapanır, Asya/Avrupa retail
   ağırlıklı.
2. **Düşük likidite + düşük volume + yön sapması** = "trapped retail directional bet".
3. **Pazar 23:00 UTC sonrası ABD desk'leri tekrar pozisyonlanır.** Eğer hafta sonu hareketi
   "haberle değil pozisyonlama gürültüsüyle" gerçekleşmişse, profesyoneller bu sapmayı **fade**
   eder → mean reversion baskı.
4. **Volume z-skoru < 0 filtresi** burada KRİTİK: hafta sonu hareketi haberle (örn. ETF onayı,
   regülasyon, FOMC) tetiklenmişse volume YÜKSEK olur → filtre eler. Sadece "haber yokken
   gürültüyle sürüklenmiş" gapler hedeflenir.
5. Beklenen kazanım: ortalama R-multiple 0.5-1.0; düşük frekans ama düşük overhead.

**Eğer §1'deki edge yoksa**, muhtemelen:
- (a) Volume filtresi çalışmıyor (haber/gürültü ayrımı yetersiz),
- (b) ABD desk reversion'ı 2017-2020 dönemine özgü; 2021+ kurumsal akış değişti,
- (c) Calendar etkisi yok, sadece random walk noise + survivorship of confirming examples.

## 9. Beklenen Korelasyon — Top 10 ile

| Hedef | Eşik |
|---|---|
| Avg ρ(strateji, Top-10 üyesi) | < 0.20 |
| Max ρ tek bir üyeyle | < 0.35 |
| Korelasyon en yüksek beklenen: any_intraday_meanrev_15m | < 0.30 — farklı zaman dilimi |
| Korelasyon en yüksek beklenen: phoenix_scalp Monday-Asia exposure | < 0.40 |

## 10. Stress Test Beklentisi (önceden taahhüt)

| Period | Beklenti | Eşik |
|---|---|---|
| 2022-05 LUNA cascade | Hafta sonu hacim PATLAR → vol_z filtresi ELER → 0 trade beklenir | trade = 0 |
| 2022-11 FTX (Cuma haberi) | Aynı: hacim explosion → 0 trade | trade = 0 |
| 2024-03 ATH dump | Volatil; bazı haftalarda filtre tetiklenebilir, ATR-büyük gap zorlu | cumul P&L > -%5 |
| 2024-08 Yen carry (Pazartesi açılışı kötü) | Long pozisyon kapansa SL'i yiyebilir | cumul P&L > -%6 |
| 2024 ETF onayı (Ocak) | Cuma onaylanıp Pazartesi açılışı: volume HIGH → filtre eler | trade ≤ 1 |

**Önemli:** Bu strateji **haber kazananı DEĞİL**; **haber yok pozisyon-gürültüsü reversion**
stratejisi. Volume filtresi haber-haftalarını dışlamalı; aksi halde strateji röntgenlenmemiş
demektir.

## 11. Veri Erişimi

- **OHLCV 1h:** DuckDB `data/ohlcv_1h.duckdb` (mevcut/oluşturulacak — data_engineer dispatch
  gerekirse)
- **OHLCV 1d:** mevcut
- **Sembol seti:** BTCUSDT + ETHUSDT, 2021-01-01 → 2026-04-30
- **Survivorship:** ikisi de tüm dönem aktif, kontrol gerekmez ama universe builder doğrulamalı
- **CME calendar (opsiyonel):** US tatil günlerinde Fri close değişebilir; Phase-2 enhancement

## 12. Backtest Engine Setup

```
backtest.engine.run(
  hypothesis_id='2026-05-27-weekend-gap-fill-stats-1d-v1',
  universe=['BTCUSDT','ETHUSDT'],
  timeframe='1h',          # gap measurement için saatlik
  resample_for_trade='1d', # signal bar 1d aggregate
  start='2021-01-01',
  in_sample_end='2024-12-31',
  oos_end='2026-04-30',
  fees_bps_taker=7.5,
  fees_bps_maker=-1.0,
  slippage_bps=5.0,
  initial_capital=10_000.0,
  risk_per_trade=0.005,    # düşük frekans → daha düşük risk
  calendar_shuffle_runs=200,
  week_shuffle_runs=1000,
)
```

## 13. Karar Akışı

```
1. 1h OHLCV verisi varlık kontrolü (data_engineer dispatch gerekirse)
2. Veri kalite raporu (gap/anomaly, özellikle US tatil haftaları)
3. In-sample backtest (Optuna n_trials=80, TPE)
4. Trigger ON vs OFF Welch-t (null testi)
5. Week-shuffle baseline (1000 iter)
6. Calendar-shuffle baseline (200 iter) — KEY GATE
7. SOP-3 Robustness suite (8 madde, OOS dönemi kısa olduğu için year-out 4-fold CV)
8. DSR + BH correction + bootstrap-Sharpe CI
9. Korelasyon analizi (Top 10 cluster)
10. Stress periodlar
11. Karar: terfi adayı / red / "belirsiz, ek veri"
12. Çıktı: reports/research/weekend-gap-fill-2026-05-27.html
```

## 14. Önceden Açıklanmış Açıklamalar (post-hoc savunmayı engellemek için)

- Eğer best cell parametre uç değerinde → **reddet**, "ama mekanik makul" denmez.
- Eğer Welch-t p > 0.10 → **reddet**, "ama hit-rate yüksek" denmez.
- Eğer calendar-shuffle p < 0.05 değilse (= başka anchor da çalışıyorsa) → **reddet**, "calendar
  versiyonu daha iyi" denmez; bu hipotezin asıl iddiası calendar bağımlılığıdır.
- Eğer trade < 50 → **reddet**, "düşük frekans ama temiz" denmez.
- Eğer 2024 ETF haftası tek başına edge'in %40+'ını yapıyorsa → **reddet**, "outlier" gerekçesiyle
  filtre eklenmez.

## 15. Reproducibility Footer

```
git_hash: <to-be-filled at backtest run>
config_hash: <to-be-filled>
data_hash: <to-be-filled>
ohlcv_1h_source_hash: <to-be-filled>
```

---

## Notes for Reviewers

- **lab_scientist:** Düşük trade frekansı (~60 trade) ile DSR ve tournament gate'lerim çakışıyor
  mu? Bu hipotez için "challenger giriş eşiği" özel olarak DSR yerine bootstrap-Sharpe CI'a
  bağlanmalı mı?
- **risk_officer:** 2 sembol, %0.5 risk-per-trade, ortalama 15-18 trade/yıl. Eşzamanlı 2-pozisyon
  ihtimali var (BTC+ETH aynı hafta) → portföy korelasyon limitleri ihlal eder mi? Hafta-sonu
  GAP olduğunda Pazartesi açılışında likidite/slippage farklı, kabul edilebilir mi?
- **adversary_engineer:** "CME gap fill" retail narrative magneti. Bu sinyalin reverse-causality
  riski: gap fill istatistik olarak kendini realize ediyor olabilir mi (= retail trader'lar gap'i
  kapatmaya basıyor ve self-fulfilling oluyor)? Bu durumda kurumsal akış değişimi (örn. spot
  ETF onayı) edge'i siler mi? Stress-test: 2024 sonrası dönemde edge fade olmuş mu (yapısal
  kırılma)?
