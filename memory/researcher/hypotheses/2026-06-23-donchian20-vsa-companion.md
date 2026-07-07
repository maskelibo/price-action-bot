---
doc_id: researcher-20260623T080000-donchian20-vsa-companion
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-23T08:00:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, cross_strategy, low_correlation_companion, donchian_breakout, vsa_climax_companion, pre_registration]
supersedes: null
---

# Hypothesis: HYP-2026-06-23-donchian20-vsa-companion

## Seed
Cross-strategy edge keşfi — canlıdaki `vsa_climax_test` (volume-spread reversal/mean-reversion) ile **yapısal olarak düşük korelasyonlu** trend-takipçi companion adayı.

## 1. İddia (pre-registered, ölçülebilir)

> "1D timeframe'de, son 3 yıl USDT-perpetual evreninde (delisting-dahil ~120 sembol), **20-bar Donchian high/low close-onaylı breakout** sinyali — `ATR(14)×2.0` SL, 10-bar opposite-channel trailing exit, %1 risk/trade — `vsa_climax_test` ile birlikte koşturulduğunda **HEPSİNİ aynı anda** karşılar:
>
> - Standalone OOS Sharpe ≥ **0.8** (Chan single-asset gate, [#9])
> - Standalone OOS annualized net return ≥ **%25** (fee 7.5bps taker + 5bps slip dahil)
> - Standalone MaxDD ≤ **%25** (account-equity bazında, %0-base PnL değil — CT-RSK-01 dersi)
> - `vsa_climax_test` ile **Pearson(daily_returns) ≤ 0.20** (düşük-korelasyon premise)
> - Eşit-ağırlıklı kombine portföy Sharpe ≥ **max(standalone Sharpe) × 1.15** (gerçek marginal diversification kanıtı)
> - Profit factor ≥ **1.4**
> - OOS trade sayısı ≥ **100**"

## 2. Null hipotezler (çürüten koşullar — explicit)

- **H0a**: Donchian-20 standalone OOS Sharpe ≤ 0 (raw edge yok).
- **H0b**: ρ(daily_returns, vsa_climax) > 0.30 (companion premise çürür — eşit-edge çift saymak diversification değil; portföye eklemenin marginal Sharpe artışı yok).
- **H0c**: Kombine Sharpe ≤ max(standalone) (eklenen edge negatif marginal — risk-adjusted portföyü kötüleştiriyor).

H0a/b/c'den **herhangi biri true** → strateji RED, learning.md'ye gerekçe.

## 3. Gerekçe (RAG referansları)

- **[#7 Kaufman — Donchian/Turtle System 1/2]**: 20/55-bar channel breakout, %35 WR + asimetrik R-multiple ile pozitif beklenti; ADX > 25 trending rejimde çalışır, choppy'de drawdown. **Mekanik, 3 parametre** (window, ATR çarpanı, exit-channel) → curve-fit yüzeyi bilinçli sığ.
- **[#9 Chan — single-asset Sharpe gate ≥ 0.8]**: portföye girmesi için minimum eşik; primary OOS gate olarak adopte edildi.
- **[#6 SMC tablo — BOS close-based n=3 "Yüksek" testable]**: kripto 1D'de close-onaylı breakout ailesinin sade, az-parametrik halini Donchian-20 temsil eder.
- **[#1 López de Prado overfit kriterleri]**: PBO ≤ 0.5, DSR ≥ 0.5, IS Sharpe / OOS Sharpe ≤ 3.0, params/N ≤ 1/30 — accept gate'lerine **explicit** dahil edildi (bkz §6).
- **Anti-konfirmasyon notu**: vsa_climax_test = volume-anomaly reversal; Donchian-20 = strict trend-follower → **structural orthogonality** beklentim **doğrulanmamış prior**; ρ ölçülmedikçe companion claim'i çürük.

## 4. Independent variables (parameter space — bilinçli sığ)

| Param | Default | Sweep |
|---|---|---|
| `donchian_window` | 20 | {15, 20, 25, 40, 55} (Turtle System 1+2 + 2 ara) |
| `atr_stop_mult` | 2.0 | {1.5, 2.0, 2.5} |
| `exit_channel_bars` | 10 | {10, 20} |
| **Toplam trial** | — | **5 × 3 × 2 = 30** |

**Curve-fit guard (zorunlu)**:
- Daha ince grid (her 0.1 ATR-mult, 1-bar window step) **YASAKLI** — López de Prado params/N kuralı (>1/30) kırılır, learning.md "overfitting kırmızı bayrak #3" deja-vu.
- Best params **uzayın sınırında** (window=15 veya 55) gelirse → uzay yanlış kırpılmış demektir, RED.

## 5. Dependent variables (pre-registered metrics — sadece bunlar accept gate'inde)

**Primary:**
- `oos_sharpe_annualized` (sqrt(252) annualization, CT-RES-01 dersi: doğru base)

**Secondary (gate'lerde kullanılır):**
- `oos_net_annual_return_pct` (fees+slip dahil)
- `oos_max_drawdown_pct` (account-equity bazında, CT-RSK-01)
- `oos_profit_factor`
- `oos_trades_total`
- `pearson_corr_with_vsa_climax_daily_returns`
- `combined_portfolio_sharpe` (eşit-ağırlık vsa_climax_test + donchian20)
- `dsr` (Deflated Sharpe Ratio)
- `pbo` (Probability of Backtest Overfitting)

**Info-only (gate'te değil, raporda):**
- `regime_split_sharpe` (bull / bear / range)
- `symbol_out_cv_min_sharpe`
- `walk_forward_dilim_positive_ratio`

## 6. Beklenen p-value & Multiple Testing Correction

- Trial sayısı: **30**
- **Bonferroni-corrected α** = 0.05 / 30 = **0.00167** (primary Sharpe metriği için)
- **Benjamini-Hochberg FDR < 0.05** alternatif raporlanır (info)
- **López de Prado tam paket — accept için HEPSİ gerekli:**
  - DSR ≥ 0.5
  - PBO ≤ 0.5
  - IS Sharpe / OOS Sharpe ≤ 3.0
  - params/N (= 3 / OOS_trade_count) ≤ 1/30 → N ≥ 90 zaten zorunlu (trade ≥ 100 gate'iyle uyumlu)

## 7. Stop criteria (terkedilme — herhangi biri tetiklerse araştırma DURUR)

1. In-sample Sharpe < **0.5** (raw edge yok — daha derinine kazma).
2. `ρ(daily_returns, vsa_climax)` > **0.30** (companion premise çürük — Donchian zaten VSA ile aynı şeyi yapıyor demek; diversification iddiası yıkılır).
3. OOS trade sayısı < **100** (istatistik anlamsız).
4. Symbol-out CV: min sembol-out OOS Sharpe < **0** (1-2 sembol whole-edge'i taşıyor → fragile).
5. Walk-forward 12 dilimden **≤ 6 pozitif** (edge persistence yok).
6. Best params parametre uzayının **sınırında** (window = 15 veya 55, ATR = 1.5 veya 2.5) → uzay yanlış cropped, geniş grid'le yeniden test (ama params/N kuralı kırılırsa total abort).
7. **DSR < 0.5** VEYA **PBO > 0.5** (López de Prado red bayrağı).
8. Stress periyotlarında (2022-05 LUNA, 2022-11 FTX, 2024-08 Yen carry) drawdown > **-%30**.
9. Lookahead test (`tests/test_lookahead.py::test_donchian_causality`) ✗.

## 8. Curve-fit / bias şüphesi (kendi eleştirim — anti-confirmation, persona zorunlu)

- **"Donchian-20 iconic Turtle parametresi" → cherry-pick mi?** Default 20 olarak entry ediyorum çünkü literatür-anchor, **ama sweep grid'i 15→55 dahil**; 20 dışında bir değer kazanırsa hipotez literatür-anchor olarak zayıflar AMA sayı kazanır.
- **"Trend-following ⊥ VSA-reversal" narratif zayıf**: yapısal beklenti var, fakat "mantıklı geliyor" kabul gerekçesi DEĞİL (persona learning: anti-narrative bias). ρ ≤ 0.20 ölçülmedikçe companion claim çürük; ρ ∈ (0.20, 0.30] **PROPOSED ama dikkat** notuyla CEO/Lab'a; > 0.30 → RED.
- **Survivorship guard**: Universe `data/universe.py::build_universe(t)` ile zaman-bilinçli kurulacak; delisting'ler dahil (memory/shared/lessons/survivorship-bias-crypto). Aksi takdirde sonuç **yıllık %20-50 şişer**.
- **Lookahead guard**: Donchian high/low t-1 close'a kadar; entry t open'da; `tests/test_lookahead.py::test_donchian_causality` ZORUNLU geçecek.
- **Multiple testing inflation kontrolü**: 30 trial × 5 metrik = 150 hipotez yüzeyi → en konservatif Bonferroni 0.00033. **Sadece primary Sharpe** üzerinde 30-trial Bonferroni uygulanır; sekonderler info-only — bu sınır çekme ZORUNLU disiplin, "tüm metrikler primary" yapsam multiple testing'i suistimal etmiş olurum.
- **Backtest compounding inflation dersi**: `memory/.../backtest-compounding-inflation` — %/ay sayıları sabit-fraksiyon + borsa-truth ile rapor edilecek; compounding-şişmiş figürler engine'den dışlanacak.

## 9. Test setup (reproducibility için tam spec)

- **Universe**: 3y (2023-06-01 → 2026-06-01), USDT-perpetual, delisting-inclusive
- **Timeframe**: 1D primary (HTF: 1W EMA trend filter info-only, hipotezde gate değil)
- **Fees**: 7.5bps taker / -1bp maker
- **Slippage**: 5bps konservatif
- **Initial capital**: 10,000 USDT
- **Risk**: %1/trade, `ATR(14)×2.0` SL
- **Position sizing**: equal-risk-per-trade (R-based)
- **Concurrent limit**: max 10 pozisyon (vsa_climax_test çakışmasında ilk-gelen-alır; correlation cap risk_officer review'ında)
- **Walk-forward**: 3y train + 6m test, step 3m → 12 dilim
- **Stress slice'lar**: 2022-05, 2022-11, 2024-03, 2024-08 ayrı raporlanır

## 10. Reproducibility tag (commit'te damgalanır)

- `git_hash`: <commit-time>
- `config_hash`: hypothesis_runner output
- `data_hash`: DuckDB snapshot SHA

## 11. Gelecek adımlar (eğer accept'e ulaşırsa)

- Lab tournament: challenger `vsa_climax_test + donchian20` kombine portföy → champion'a karşı
- Drift detection setup: KS test, Welch t-test 30d live vs backtest
- Risk officer review: portföy-seviyesi max-concurrent + correlation cap güncellemesi
- **Live'a geçiş YASAK** bu doc'tan; sadece Lab tournament + Principal sign-off yolu.

## 12. Pre-registration disiplini

- [x] Hipotez **kod yazmadan** önce yazıldı (SOP-1, zorunlu).
- [ ] Bu doc commit'lenip git_hash dondurulduktan SONRA `backtest/engine.py` çalıştırılır.
- [ ] Sonuçlara göre §1 iddialarından **herhangi biri** ✗ ise post-hoc parametre kayması YASAK (yeni hipotez yazılır, eski supersede edilir).
- [ ] requested_review_from: `lab_scientist` (tournament eligibility), `risk_officer` (correlation cap impact).

## 13. Kendi kuşkum (özet — tek paragraf)

Yapısal "trend-follower ⊥ reversal" beklentim mantıklı görünüyor ama kendisini doğrulamaz; en olası RED senaryosu **H0b** (ρ > 0.30) — kripto 1D rejimlerinde her iki sinyalin de breakout/exhaustion korelasyonlu tetiklemesi mümkün. İkinci olası RED **stop-criteria #5** (walk-forward dilimleri ≤ 6 pozitif) çünkü Donchian choppy rejimde whipsaw bombardımanı yer (#7 failure modu). Hipotezin %60+ red ihtimaliyle yazıldığını ön kabul ediyorum — sağlıklı bir araştırma KPI'sı için bu beklenti DOĞRU yön.
