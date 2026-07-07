---
doc_id: researcher-20260629T140000-katr-volatility-breakout-1d-vsa-companion
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-29T14:00:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, cross_strategy, low_correlation_companion, volatility_breakout, katr, vsa_climax_companion, pre_registration]
supersedes: null
---

# Hypothesis: HYP-2026-06-29-katr-volatility-breakout-1d-vsa-companion

## Seed
Cross-strategy edge — canlı `vsa_climax_test` (volume-anomaly exhaustion reversal) ile **yapısal olarak orthogonal** bir intraday-momentum / volatility-expansion companion arıyorum. Donchian-20, RTM, marubozu, golden/death, EQH/EQL, mat-hold, triple-inside, brooks-swing, HMM-TSMOM rafta var. Geriye kullanılmamış RAG ailesi olarak **Kaufman k×ATR volatility breakout** (#5) kalıyor. Bu hipotezin amacı onu pre-register etmek.

## 1. İddia (pre-registered, ölçülebilir — sayısal, gevşek değil)

> "1D timeframe'de, 2023-06-01 → 2026-06-01 USDT-perpetual evreninde (delisting-dahil ~120 sembol), günlük açılışta:
> - long stop = `Open + k×ATR(14)` üzerine fiyat çıkarsa long
> - short stop = `Open − k×ATR(14)` altına inerse short
> - SL = giriş − 1.5×ATR(14) (long), tersi (short)
> - exit = bar close (24h time-stop) **veya** 2×ATR target — hangisi önce
> - %1 risk/trade, 7.5bps taker fee + 5bps slip
>
> **HEPSİNİ aynı anda** karşılar:
> - Standalone OOS Sharpe ≥ **0.8** (Chan single-asset gate, [#9])
> - Standalone OOS net annual return ≥ **%20** (fee+slip dahil)
> - Standalone MaxDD ≤ **%25** (account-equity bazında — CT-RSK-01)
> - `vsa_climax_test` ile **Pearson(daily_returns) ≤ 0.20**
> - Eşit-ağırlık kombine portföy Sharpe ≥ **max(standalone) × 1.15**
> - Profit factor ≥ **1.3**
> - OOS trade sayısı ≥ **150** (1D × ~120 sembol × 3y bütçesi içinde rahat ulaşılabilir, params/N gate'i için zorunlu)
> - Win rate ≥ **%45** (Kaufman raporu %55 — kripto'da düşüş bekliyorum, ama %45 altında asimetri çöker)"

## 2. Null hipotezler (çürüten koşullar — explicit)

- **H0a**: Standalone OOS Sharpe ≤ 0 → raw edge yok.
- **H0b**: ρ(daily_returns, vsa_climax) > 0.30 → companion premise çürür; her iki strateji de yüksek volatilite anlarında benzer pozisyon açıyor demektir (orthogonality narratifi yıkılır).
- **H0c**: Kombine Sharpe ≤ max(standalone) → marginal Sharpe negatif; portföye eklemek risk-adjusted getiriyi düşürür.
- **H0d**: Kripto 1D'de bar-close target oranı %50'nin altında (Kaufman'ın "intraday momentum capture" mantığı 1D'de çökmüştür → 2×ATR hedefi nadiren vurulur → asimetri ters döner).

H0a/b/c/d'den **herhangi biri true** → strateji RED, learning.md'ye gerekçe.

## 3. Gerekçe (RAG referansları)

- **[#5 Kaufman — k×ATR volatility breakout]**: Open ± k×ATR(14) stop-entry, intraday momentum capture, %55 WR küçük R ile asimetri. **Kaufman'ın tarifi intraday** — 1D'ye taşırken davranış değişir (bar-close time-stop yerine 2×ATR target). Bu **bilinçli adaptasyon** ve **risk**: literatür-anchor zayıflıyor, kripto'da yeniden doğrulanması zorunlu.
- **[#9 Chan — single-asset Sharpe gate ≥ 0.8]**: portföye dahil olmak için minimum eşik.
- **[#1 López de Prado overfit kriterleri]**: DSR ≥ 0.5, PBO ≤ 0.5, IS/OOS Sharpe oranı ≤ 3.0, params/N ≤ 1/30 — accept gate'lerine explicit dahil (bkz §6).
- **vsa_climax_test orthogonality varsayımı**: VSA = low-frequency reversal at exhaustion volume; k×ATR breakout = trend-day momentum capture at range expansion. **Mantıklı bir orthogonality narratifi var ama doğrulanmamış prior** — ρ ölçülmedikçe companion claim çürük (anti-narrative discipline).
- **Anti-konfirmasyon**: Kaufman'ın %55 WR iddiası **stock indices** tabanlı. Kripto 1D rejimleri farklı (24/7, gap yok, weekend volatility), yani aynı sayıyı bekleme **HATA** olur. Bu yüzden gate %45 — Kaufman'ın altında ama hala asimetriyi koruyan minimum.

## 4. Independent variables (parameter space — bilinçli sığ)

| Param | Default | Sweep |
|---|---|---|
| `k_atr_entry` | 0.75 | {0.5, 0.75, 1.0} |
| `atr_stop_mult` | 1.5 | {1.5, 2.0} |
| `target_atr_mult` | 2.0 | {1.5, 2.0, 2.5} |
| **Toplam trial** | — | **3 × 2 × 3 = 18** |

**Curve-fit guard (zorunlu):**
- Daha ince grid (her 0.1 k step) **YASAKLI** — params/N kuralı kırılır, "overfitting kırmızı bayrak #3" deja-vu.
- Best params **uzayın sınırında** (k=0.5 veya 1.0, target=1.5 veya 2.5) gelirse → uzay yanlış kırpılmış demektir → uzay genişletilir ama params/N kuralı kırılırsa **toplam abort**.
- Kaufman'ın `k ∈ [0.5, 1.0]` tarifinin dışına çıkmak (k=0.25 veya k=1.5) literatür-anchor'ı tamamen siler → o zaman hipotez yeni bir doc olur, bu supersede edilir.

## 5. Dependent variables (pre-registered metrics — accept gate'inde sadece bunlar)

**Primary:**
- `oos_sharpe_annualized` (sqrt(252), CT-RES-01 dersi: doğru base)

**Secondary (gate'lerde kullanılır):**
- `oos_net_annual_return_pct` (fees+slip dahil)
- `oos_max_drawdown_pct` (account-equity bazında, CT-RSK-01)
- `oos_profit_factor`
- `oos_trades_total`
- `oos_win_rate`
- `pearson_corr_with_vsa_climax_daily_returns`
- `combined_portfolio_sharpe`
- `dsr` (Deflated Sharpe Ratio)
- `pbo` (Probability of Backtest Overfitting)
- `target_hit_rate_pct` (2×ATR target / time-stop) — H0d için

**Info-only (gate'te değil, raporda):**
- `regime_split_sharpe` (bull / bear / range)
- `symbol_out_cv_min_sharpe`
- `walk_forward_dilim_positive_ratio`
- `stress_period_dd` (LUNA, FTX, 2024-03 ATH, Yen carry 2024-08)

## 6. Beklenen p-value & Multiple Testing Correction

- Trial sayısı: **18**
- **Bonferroni-corrected α** = 0.05 / 18 ≈ **0.00278** (primary Sharpe için)
- **Benjamini-Hochberg FDR < 0.05** alternatif raporlanır (info)
- **López de Prado tam paket — accept için HEPSİ gerekli:**
  - DSR ≥ 0.5
  - PBO ≤ 0.5
  - IS Sharpe / OOS Sharpe ≤ 3.0
  - params/N (= 3 / OOS_trade_count) ≤ 1/30 → N ≥ 90 zaten zorunlu (≥150 gate'iyle uyumlu)

## 7. Stop criteria (terkedilme — herhangi biri tetiklerse araştırma DURUR)

1. In-sample Sharpe < **0.5** → raw edge yok.
2. ρ(daily_returns, vsa_climax) > **0.30** → companion premise çürük.
3. OOS trade sayısı < **100** → istatistik anlamsız (yine de gate 150 ama bu hard-floor).
4. Win rate < **%40** → asimetri tersine döndü (target nadir, SL sık).
5. `target_hit_rate_pct` < **%40** → 2×ATR target kripto 1D'de gerçekçi değil; time-stop yapısı çürük (H0d true).
6. Symbol-out CV: min sembol-out OOS Sharpe < **0** → 1-2 sembol whole-edge'i taşıyor → fragile.
7. Walk-forward 12 dilimden **≤ 6 pozitif** → edge persistence yok.
8. Best params uzayın **sınırında** + uzay genişletme params/N kuralını kırıyor → total abort.
9. **DSR < 0.5** VEYA **PBO > 0.5** → López de Prado red bayrağı.
10. Stress periyotlarında (LUNA, FTX, Yen carry) drawdown > **−%30** → tail çöküşü.
11. Lookahead test (`tests/test_lookahead.py::test_katr_breakout_causality`) ✗ → veri sızıntısı, total kill.

## 8. Curve-fit / bias şüphesi (kendi eleştirim — anti-confirmation, persona zorunlu)

- **"Kaufman'ın WR %55 iddiası" cherry-pick mi?** Tarihsel olarak **stocks** üzerinde. Kripto 1D'de bu sayıyı **beklemiyorum**; gate %45'e indirildi. Eğer backtest %50+ getirirse bu **şüpheli** olur (literature anchor over-fit'i taşıyabilir) — IS/OOS oranı 3.0 sınırını sıkı sıkı uygula.
- **"Intraday tarif → 1D adaptasyonu" yapısal değişiklik**: Bar-close time-stop **yeni** bir parametre değil ama davranışsal olarak Kaufman'ın orijinalini değiştirir. Bu yüzden hipotez "Kaufman replica" değil "Kaufman-inspired" — başarılı çıkarsa Lab tournament'a girer, başarısız çıkarsa Kaufman'ın suçu değil benim adaptasyonum.
- **"Trend-day momentum ⊥ VSA-reversal" narratif zayıf**: Yapısal beklenti mantıklı, ama "mantıklı geliyor" kabul gerekçesi DEĞİL (persona learning: anti-narrative bias). ρ ≤ 0.20 ölçülmedikçe companion claim çürük; ρ ∈ (0.20, 0.30] **dikkat** notuyla CEO/Lab'a; > 0.30 RED.
- **Survivorship guard**: Universe `data/universe.py::build_universe(t)` ile zaman-bilinçli, delisting'ler dahil (memory/shared/lessons/survivorship-bias-crypto). Aksi yıllık %20-50 şişer.
- **Lookahead guard**: `ATR(14)` t-1 close'a kadar; entry t open ± k×ATR stop-order ile, fill t içinde gerçekleşir; karar her zaman t-1 bilgisine dayalı. `tests/test_lookahead.py::test_katr_breakout_causality` ZORUNLU geçecek.
- **Multiple testing inflation**: 18 trial × 6 primary+secondary metrik = 108 hipotez yüzeyi → en konservatif Bonferroni 0.00046. **Sadece primary Sharpe** üzerinde 18-trial Bonferroni uygulanır; sekonderler info-only — bu sınır çekme zorunlu disiplin.
- **Backtest compounding inflation dersi**: `memory/.../backtest-compounding-inflation` — %/ay sayıları sabit-fraksiyon + borsa-truth ile rapor; compounding-şişmiş figürler engine'den dışlanacak.
- **"Open ± k×ATR" Kripto'da Open mantığı**: 24/7 piyasada "günlük açılış" suni — UTC 00:00 bar-open seçildi. Bu seçim **subjective** (Tokyo 09:00 veya NY 14:30 da seçilebilir). Sonuçlar UTC 00:00'a sıkı bağlıysa **yapısal şanstan** muzdarip olabilir → robustness suite'e "session-rotation test" eklendi (info-only: UTC 00/06/12/18 her birinde Sharpe).

## 9. Test setup (reproducibility için tam spec)

- **Universe**: 3y (2023-06-01 → 2026-06-01), USDT-perpetual, delisting-inclusive
- **Timeframe**: 1D primary, bar-open UTC 00:00
- **Fees**: 7.5bps taker / -1bp maker
- **Slippage**: 5bps konservatif (stop-entry → market = taker fee)
- **Initial capital**: 10,000 USDT
- **Risk**: %1/trade, `ATR(14)×1.5` SL default
- **Position sizing**: equal-risk-per-trade (R-based)
- **Concurrent limit**: max 10 pozisyon (vsa_climax_test çakışmasında ilk-gelen-alır; correlation cap risk_officer review'ında)
- **Walk-forward**: 3y train + 6m test, step 3m → 12 dilim
- **Stress slice'lar**: 2022-05 (LUNA), 2022-11 (FTX), 2024-03 (BTC ATH), 2024-08 (Yen carry) — ayrı raporlanır
- **Session-rotation robustness** (info): UTC 00 default + {06, 12, 18} alternatifleri; min Sharpe < default-0.4 ise default seçimi şüpheli flag

## 10. Reproducibility tag (commit'te damgalanır)

- `git_hash`: <commit-time, doldurulacak>
- `config_hash`: hypothesis_runner output
- `data_hash`: DuckDB snapshot SHA

## 11. Gelecek adımlar (eğer accept'e ulaşırsa)

- Lab tournament: challenger `vsa_climax_test + katr_breakout` kombine portföy → champion'a karşı
- Drift detection setup: KS test, Welch t-test 30d live vs backtest
- Risk officer review: max-concurrent ve correlation cap güncellemesi
- **Live'a geçiş YASAK** bu doc'tan; sadece Lab tournament + Principal sign-off yolu.

## 12. Pre-registration disiplini

- [x] Hipotez **kod yazmadan** önce yazıldı (SOP-1, zorunlu).
- [ ] Bu doc commit'lenip git_hash dondurulduktan SONRA `backtest/engine.py` çalıştırılır.
- [ ] Sonuçlara göre §1 iddialarından **herhangi biri** ✗ ise post-hoc parametre kayması YASAK (yeni hipotez yazılır, eski supersede edilir).
- [ ] requested_review_from: `lab_scientist` (tournament eligibility), `risk_officer` (correlation cap impact).

## 13. Kendi kuşkum (özet — tek paragraf)

Bu hipotezin **%65+ red ihtimaliyle yazıldığını** kabul ediyorum. En olası RED senaryoları sırayla: **H0d** (2×ATR target kripto 1D'de %40'tan az vurur → asimetri çöker, time-stop edge yer), **H0b** (kripto 1D'de "trend-day momentum" ve "volume-climax reversal" benzer tetikleyicilerle aynı volatility expansion günlerinde çakışır → ρ > 0.30), ve **stop-criteria #7** (walk-forward dilimleri ≤ 6 pozitif çünkü düşük volatilite günlerinde Kaufman'ın "tetiklenmiyor zaten istenen" özelliği kripto'da hala doğru ama trend-day'lerin azlığı edge'i seyrek bırakır). Kaufman'ın orijinal tarifi intraday — 1D'ye taşıma yapısal bir bahis ve test edilmedi. Sağlıklı bir araştırma KPI'sı için bu yüksek-red beklentisi DOĞRU yön: hipotezin %80'i red olur, bu sağlıklıdır (persona disiplin).
