---
doc_id: researcher-20260531T060000-donchian-adx-breakout-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-31T06:00:00Z
status: DRAFT
confidence: med
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, pre-registration, cross-strategy-diversification, trend-following, donchian, adx, low-corr-to-vsa-climax]
supersedes: null
hash: null
---

# Hypothesis HYP-2026-05-31-donchian-adx-breakout-low-corr-to-vsa

## 0. Seed & Pozisyon
- **Seed konu:** "Cross-strategy edge keşfi: aktif `vsa_climax_test` ile düşük korelasyonlu ek bir strateji (raftaki 66'dan adaylar)."
- **Yapısal argüman:** `vsa_climax_test` mean-reversion ailesinden (yüksek hacim + geniş range climax sonrası dönüş bekler). Donchian-N breakout *momentum / trend-continuation* ailesindendir — fiyat yeni N-bar high/low'a giderken sinyal verir. **İki strateji aynı barda zıt yönde sinyal üretebilir** → return-bazlı korelasyon yapısal olarak ≤ 0.20 beklenir. Bu beklenti dependent-variable olarak kaydediliyor; doğrulanmazsa hipotez red.
- **Daha önce var mı:** 2026-05-08 `donchian-bollinger-breakout` (kombo, ADX yok), 2026-05-14 `turtle-soup-20day-failed-breakout` (fade — bu hipotezin tersi). Bu hipotez ikisinin de duplicate'i değil: tek-kanal pure breakout + ADX(14)>25 regime gate + Turtle System 1 trail exit + active strategy ile portfolio risk-budget paylaşımı.

## 1. İddia (pre-registered, ölçülebilir)

> "USDT-perpetual evreninde, top-20 sembol (90-gün ADV'ye göre, survivorship-safe), 1D timeframe, 2022-01-01 → 2025-05-31 dönemi, taker fee 7.5 bps + 5 bps slippage, %0.5 risk/trade konfigürasyonunda; aşağıdaki Donchian + ADX kuralı:
> - **Entry-long:** `close[t] > max(high[t-20:t])` VE `ADX(14)[t] > 25` → `t+1` open'da long stop-market.
> - **Entry-short:** `close[t] < min(low[t-20:t])` VE `ADX(14)[t] > 25` → `t+1` open'da short stop-market.
> - **Stop:** entry ± `2.0 × ATR(20)[t]`.
> - **Exit (trailing):** Long için fiyat son 10-bar low'a değdiğinde; short için son 10-bar high'a değdiğinde (Turtle S1).
> - **Position cap:** Aktif `vsa_climax_test` ile aynı portföyde, sembol başına netting yok; iki strateji aynı sembolde aynı yönde açıkken yeni giriş engellenir.
>
> aşağıdaki **6 nokta hedefini** *aynı anda* karşılar (2.5-yıl IS + 1-yıl OOS, walk-forward 12 dilim):
>
> | # | Metrik | OOS hedef | Why |
> |---|---|---|---|
> | M1 | Net annualized return | ≥ **15%** (fee+slip dahil) | Mütevazi; "yıllık %50" iddiası curve-fit kırmızı bayrağı |
> | M2 | Sharpe (OOS, daily strategy returns) | ≥ **0.80** | Chan single-asset eşiği (RAG #9) |
> | M3 | MaxDD (OOS) | ≤ **30%** | Trend-following doğası gereği range'de DD beklenir; kabul edilebilir tavan |
> | M4 | Profit factor | ≥ **1.30** | Asimetrik R-multiple beklentisi |
> | M5 | Trade sayısı (3.5-yıl, 20 sembol) | ≥ **150** ve ≤ **600** | <150 istatistik yok; >600 ADX gate'in işe yaramadığını gösterir |
> | M6 | **Daily-return correlation (Pearson, OOS) `vsa_climax_test` ile** | **\|ρ\| ≤ 0.20** | Yapısal düşük-korelasyon iddiasının ölçülebilir tanımı |
>
> Bu 6 hedeften **herhangi biri** kaçırılırsa hipotez REDDEDİLİR (kısmi pas yok)."

## 2. Null Hipotez

H0: Donchian-20 breakout + ADX(14)>25 + ATR-trail kuralı, 2022-2025 USDT-perp evreninde, ya
(a) shuffle-baseline'ı yenmiyor (Sharpe p ≥ 0.05), ya
(b) M1..M5'ten en az birini kaçırıyor, ya
(c) `vsa_climax_test` ile daily-return |ρ| > 0.20 (yani diversifikasyon değeri yok),
yani edge gerçekten ortaya çıkmıyor veya çıksa bile portfolio'ya katkısı yapısal değil.

## 3. Gerekçe (RAG referansları)

| RAG | İçerik | Bu hipoteze etkisi |
|---|---|---|
| **#7** Kaufman — Donchian 20/55 breakout | "Asimetrik R-multiple; ~%35 win rate ile pozitif beklenti, çünkü winners 3-5R, losers 1R. Failure: Choppy/range-bound rejimde back-to-back whipsaw; %20-40 DD." | Mekanik tanım baz; range failure mode bilindiği için **ADX(14)>25 gate** zorunlu kılındı |
| **#6** Market structure — BOS/CHoCH | "BOS (close-based, n=3): Mekanik Çalışabilirlik **Yüksek**." | Donchian close-based breakout, BOS'un daha mekanik (n=20) varyantıdır |
| **#4** Kaufman — Golden/Death cross | "Long-horizon trend captures. Daily timeframe ideal; intraday'de gürültü baskın." | 1D timeframe seçimini destekler |
| **#1** López de Prado — overfit checklist | "DSR < 0.5, PBO > 0.5, T < MinBTL, IS Sharpe > 3·OOS Sharpe, free-params/N > 1/30, walk-forward Sharpe varyansı > ortalama → red." | **Stop criteria** ve robustness suite'in eksiksiz çalıştırılması bu listeyle bire bir eşlenir |
| **#9** Chan | "OOS Sharpe > 0.8 (single asset) eşiği." | M2 hedefi buradan |

## 4. Dependent Variables (ölçülecek, başka hiçbir şey değil)

1. `net_annualized_return_oos` (M1)
2. `sharpe_oos_daily` (M2)
3. `maxdd_oos_equity_based` (M3) — *zero-base PnL üzerinden DEĞİL, equity üzerinden* (CT-RSK-01 bug class — bkz. audit_risk seed control)
4. `profit_factor_oos` (M4)
5. `trade_count_total` (M5)
6. `pearson_corr_daily_returns_vs_vsa_climax_test_oos` (M6)
7. `walk_forward_dilim_pozitif_orani` (12 dilimden kaçı net-pozitif)
8. `is_oos_sharpe_ratio` (López #4 — > 3.0 ise overfit)
9. `bonferroni_adjusted_p_value` (n_trial = 27 → eşik 0.05/27 ≈ 0.00185)
10. `deflated_sharpe_p_value` (DSR — López #1)
11. `pbo_estimate` (López #2 — combinatorially symmetric backtest)
12. `shuffle_baseline_p_value` (returns shuffle, n=1000)

## 5. Independent Variables (optimize edilebilir, sınırlı uzay)

| Param | Aralık | Adım | Trial sayısı |
|---|---|---|---|
| `donchian_lookback` | {10, 20, 55} | discrete | 3 |
| `adx_threshold` | {20, 25, 30} | 5 | 3 |
| `atr_stop_mult` | {1.5, 2.0, 2.5} | 0.5 | 3 |
| `trail_lookback` | {10, 20} | discrete | 2 |
| **Toplam grid** | | | **3·3·3·2 = 54 kombinasyon** |

**Curve-fit guards:**
- Toplam free parameter = 4. N = 150-600 trade → free_params / N ≤ 4/150 ≈ 0.027 < 1/30 = 0.033 — López #5 PASS marjı dar; trade sayısı 150'nin altına düşerse hipotez derhal red.
- Adım büyüklükleri **kasıtlı kaba** (ince grid ≠ daha iyi; over-fit riskini büyütür). 0.1 ADX adımı veya 0.05 ATR adımı *yasak*.
- Best params kombinasyon uzayının sınırına otururca (örn. lookback=10 VE adx=20 VE atr=2.5) hipotez **otomatik red**: optimum kafesin dışındadır.
- Bonferroni eşiği 0.00185; shuffle p-value bunun altında değilse → red.

## 6. Beklenen p-value

- Pre-registered single-best-config p-value (shuffle baseline) hedefi: **< 0.005**.
- Bonferroni-corrected (54 trial): hedef **p < 0.00185**.
- DSR (López): hedef **DSR > 0.95**.
- Eğer 3 kriterden herhangi biri sağlanmazsa: red.

## 7. Stop Criteria (hipotezi terketme kuralları)

Aşağıdakilerden **herhangi biri** tetiklenirse araştırma terkedilir, sonuç `RED — gerekçeli arşiv` olarak yazılır:

1. **In-sample (3y 2022-2024) tek-best-config Sharpe < 0.5** → daha sonraki OOS'a anlam yok.
2. **Trade sayısı < 150** (3.5 yıl × 20 sembol → ortalama < 4 trade/sembol/yıl) → istatistik anlamsız.
3. **IS Sharpe / OOS Sharpe > 3.0** → López #4, klasik overfit.
4. **Walk-forward 12 dilimin < 7'si pozitif** → Sharpe varyansı ortalama üzerinde, López #6.
5. **Symbol-out CV: en kötü sembol bırakıldığında OOS Sharpe %40+ düşüyor** → tek sembole bağımlılık.
6. **Stress periods (2022-05 LUNA, 2022-11 FTX, 2023-03 USDC depeg, 2024-08 Yen) içinden herhangi birinde -%20'den derin DD** → tail-fragility.
7. **PBO > 0.5** (López #2) → backtest overfit olasılığı kabul edilemez.
8. **Bonferroni-corrected p ≥ 0.00185** → çoklu test düzeltmesi sonrası anlamlılık kalmıyor.
9. **`vsa_climax_test` ile \|ρ\| > 0.20** → düşük-korelasyon iddiası (hipotezin ana motivasyonu) çürür; saf-Sharpe iyi olsa bile bu hipotez bu seed için red (gerekirse bağımsız yeni hipotez olarak yeniden açılır).
10. **Lookahead test (`detector(df.iloc[:t+1])[t] == detector(df)[t]`) fail** → hata; hipotez kapsam dışı.

## 8. Curve-fit Şüphesi (kendine karşı paranoya — kayıt)

Bu hipotez için kendime sorduğum kırmızı-bayrak listesi (RAG #1 + iç learning):

| # | Bayrak | Bu hipotezde durumu | Mitigasyon |
|---|---|---|---|
| a | "Hikâye çok mantıklı, sayı bekleyeceğim" — narrative bias | Var: "VSA mean-rev, Donchian momentum → korelasyon düşük" hoşa giden hikâye | M6 sayısal olarak ölçülecek; hikâye dışlanır |
| b | İnce parametre uzayı | Grid 0.5 ATR, 5 ADX, discrete lookback → kaba | OK |
| c | Best params kafes sınırında | Kontrol stop criteria §5'te | OK — otomatik red |
| d | Tek sembol/periyot baskınlığı | Olabilir (BTC dominant 2022-2023) | Symbol-out CV, regime split zorunlu |
| e | Survivorship | top-20 ADV historical-aware kullanılacak (delist dahil) | Data layer'dan `build_universe(date)` |
| f | Lookahead | Donchian rolling.max → `min_periods` ve `shift(1)` test edilecek | `tests/test_lookahead.py` |
| g | Fee/slip optimize edilmiş | Sabit 7.5 bps + 5 bps — optimize edilmiyor | OK |
| h | M1 hedefi şişirilmiş mi? | Hayır — %15 yıllık mütevazi (LeStratejilerin >%50 hedefinden BİLEREK düşük) | OK |
| i | Cross-strategy korelasyon "self-referential" mı? | M6 OOS dönemine göre hesaplanıyor (IS değil) | OK |
| j | "Aktif strateji ile uyumlu olsun" diye gizli filtre var mı? | Position cap kuralı (aynı sembol-aynı yön çift giriş yok) eklendi — bu strateji-içi bağ; ölçüm üzerinde portfolio-level olarak değerlendirilecek, *stand-alone backtest M1-M5 için bağımsız hesaplanır* | OK |

**Net şüphe seviyesi:** orta. Donchian breakout bilinen, akademik ve crypto'da defalarca test edilmiş bir rejimdir; "yeni edge keşfettim" iddiası yok — iddia *düşük korelasyonlu ek diversifier*. Bu da bias açısından daha güvenli zemin.

## 9. Reproducibility

- git_hash: TBD (commit sonrası doldurulur)
- config_hash: backtest config dondurulmuş Donchian-ADX-grid TBD
- data_hash: DuckDB `ohlcv_1d` snapshot 2026-05-31
- seed: 42 (Optuna sampler), 1000 (shuffle baseline)

## 10. Sonraki Adım

1. `backtest/engine.py` config'i türet (Donchian-ADX grid 54 trial).
2. Walk-forward 3y/6m, step 3m → 12 dilim.
3. Robustness suite (SOP-3 hepsi).
4. M1..M6 toplu kontrol → karar.
5. RED → `learning.md`'ye 3-satır not. KISMİ POZİTİF (M1-M5 pas, M6 fail) → **iterate v2** (SOP-4b: filter tightening — örn. ADX>30, sembol subset) öneri olarak yeni hipotez ID açılır. TAM PAS → Lab tournament için aday manifest.

## 11. Karar (henüz alınmadı — pre-registration)
- [ ] Terfi adayı
- [ ] İterate (SOP-4b)
- [ ] Red — gerekçe: …

---
> Bu pre-registration dokümanı kod yazılmadan önce dondurulur (git commit). Sonuç ne olursa olsun bu dosya **append-only**; revize edilirse yeni doc_id ile yazılır ve `supersedes: researcher-20260531T060000-donchian-adx-breakout-low-corr-to-vsa` bağlanır.
