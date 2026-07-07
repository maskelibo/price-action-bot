---
doc_id: researcher-20260628T143000-hmm-regime-gated-tsmom-cross-strategy-vsa-companion
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-28T14:30:00Z
status: PROPOSED
confidence: low
depends_on:
  - researcher-20260610T193000-tsmom-sign-lookback-1d-low-corr-to-vsa
  - researcher-20260603-donchian55-regime-gated-1d-cross-edge
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, hmm, tsmom, regime_gated, cross_strategy_edge, low_corr_to_vsa, pre_registration, high_overfit_risk]
supersedes: null
hash: null
---

# Hypothesis: hmm-regime-gated-tsmom-cross-strategy-vsa-companion

- **Versiyon**: 0.1 (pre-registration, kod yok)
- **Hipotez ailesi**: cross-strategy companion for active vsa_climax_test
- **Tetik**: Seed konu "Cross-strategy edge keşfi: aktif vsa_climax_test ile düşük korelasyonlu ek bir strateji (raftaki 66'dan adaylar)."
- **Aday alanın doygunluk durumu**: 60+ companion seed-abort birikti (v6..v59). Donchian/TSMOM/EQ-sweep/inside-bar/marubozu/FVG/OB hepsi tek başına denendi. Bu hipotez bu denemelerin alt-küme uzayında YENİ bir konfigürasyon: 2-state HMM latent regime gate'i, hem trend filtresi olarak hem de **vsa_climax_test ile zamansal disjointness'i artırma** mekanizması olarak. Açıkça yüksek curve-fit riskine sahiptir; bunu paragraph 8'de pre-register ediyorum.

## 1. İddia (Pre-Registered, Falsifiable)

> 1D timeframe'de, USDT-perpetual evreninde (rolling top-30 24h-volume, delisting-inclusive):
>
> **Feature engineering (her bar t için, sadece t-1 close ve önceki bilgi):**
> - `r_t = log(close_t / close_{t-1})` — daily log return
> - `rv_t = std(r_{t-19..t})` — 20-bar realized volatility
>
> **HMM regime classifier (sembol-bazlı, yıllık retrain, expanding window):**
> - 2-state Gaussian HMM, 2-dim emission = (r_t, rv_t)
> - State A: posterior mean |μ_r| daha yüksek → "trend" state
> - State B: kalanı → "mean-revert" state
> - Etiketleme her retrain pencerede yeniden yapılır (label-switching deterministik kurala bağlanır: yüksek |μ| state'i trend)
>
> **Entry rule:**
> - Long: HMM_state(t) == trend AND `sign(close_t / close_{t-63} - 1) > 0` AND `rv_t > rv_floor_pctile_30`
> - Short: HMM_state(t) == trend AND sign < 0 AND aynı rv gate
> - Mean-revert state'te HİÇ trade YOK (vsa_climax_test'in zaten o rejimi kapsadığı varsayımı altında — orthogonality kaynağı budur)
> - Bar t kapanışta sinyal, bar t+1 open'da giriş (lookahead-safe)
>
> **Position management:**
> - Sizing: %1 equity/trade
> - SL: entry ± 2×ATR(14)
> - TP: 3×ATR trailing
> - Exit: trailing stop hit VEYA HMM state flip (trend→mean-revert) VEYA sign flip
>
> **Backtest setup:**
> - Universe: rolling top-30 24h-volume USDT-perp (delisting-inclusive — survivorship-free)
> - Window: 2022-01-01 → 2025-12-31 (4y); IS=2022-2024 (3y), OOS=2025 (1y)
> - Fees: 7.5 bps taker, slippage 5 bps
>
> aşağıdaki metrikleri eşzamanlı üretir:
>
> 1. **OOS Annualized Net Return ≥ %25**
> 2. **OOS Sharpe ≥ 0.9**
> 3. **OOS MaxDD ≤ %35**
> 4. **OOS Profit Factor ≥ 1.4**
> 5. **OOS Trade count ≥ 80** (istatistiksel anlamlılık tabanı)
> 6. **Correlation(daily PnL, vsa_climax_test daily PnL) ≤ 0.20** (cross-strategy diversification kriteri, mutlak değer)
> 7. **Trade-arrival overlap rate ≤ %15** (aynı bar'da hem vsa hem TSMOM-HMM aktif trade < toplam HMM trade'inin %15'i)

## 2. Null Hipotez (H0 — kabul olursa hipotez reddedilir)

H0: HMM regime gating'in eklenmesi, sadeli TSMOM-sign-lookback (2026-06-10 doc) çıktısına göre **OOS Sharpe'ı istatistiksel anlamlı düzeyde iyileştirmez** (paired bootstrap test, p > 0.05). Yani HMM katmanı gürültüden başka bir şey değildir; eklenen 3 latent parametre (state sayısı, retrain horizon, label-switching kuralı) curve-fit kaynaklı yalancı iyileşme verir.

Ek H0: corr(HMM-TSMOM, vsa_climax) > 0.30 → companion değeri yok, deploy etmenin diversification gerekçesi düşer.

## 3. Gerekçe (RAG Referansları)

- **[Chan summary — pairs/HMM]:** "Regime-conditional ensemble. HMM rejim çıktısına göre Bollinger reversal vs TSMOM ağırlıklarının dinamik allocation'ı; portföy seviyesinde 'regime-aware meta-strategy' oluşturulur." → Bu hipotez Chan'in önerisinin tek-strateji versiyonu: HMM'i ensemble allocator olarak değil, tek-yön (TSMOM-trend) gate olarak kullanır. Chan tavsiyesinin LITE versiyonu.
- **[Kaufman summary — channel breakout & ADX]:** "20-bar veya 55-bar high/low kırılımı. Trending market, ADX > 25 ideal. Yan piyasada whipsaw bombardımanı. Failure: choppy/range-bound rejimde back-to-back whipsaw; kümülatif %20-40 drawdown." → HMM state == trend gate'i bu whipsaw'ı azaltma motivasyonunu sağlar (ADX > 25'ten farklı/güçlü bir trend filtresi).
- **[López de Prado backtest dünyası]:** "IS Sharpe > 3·OOS Sharpe → red; Strategy serbest parametre sayısı / örnek sayısı > 1/30 → red; Walk-forward'da Sharpe varyansı ortalamadan büyük → red." → HMM 3 ekstra parametre ekler. Toplam parametre sayım açık tutulacak (bkz. §8); ratio testi zorunlu.
- **[Moskowitz/Ooi/Pedersen 2012 — TSMOM akademik baseline]:** Daha önceki hipotezde dolaylı atıf. TSMOM evren-çapı edge gösterilmiş ancak retail-net seviyesinde marjinal.

**Aşırı stretch'lemiyorum:** RAG bu spesifik kombinasyonu (HMM-gate + TSMOM + crypto perp + vsa companion) için doğrudan kanıt sunmuyor. Bu yüzden hipotez "low confidence" etiketli.

## 4. Dependent Variables (Ölçülecek)

| Değişken | Hedef | Birim |
|---|---|---|
| OOS net annualized return | ≥ %25 | % |
| OOS Sharpe | ≥ 0.9 | unitless |
| OOS MaxDD | ≤ %35 | % |
| OOS Profit Factor | ≥ 1.4 | unitless |
| OOS Trade count | ≥ 80 | int |
| OOS Win rate | n/a (info) | % |
| daily-PnL correlation vs vsa_climax | |ρ| ≤ 0.20 | unitless |
| Trade-arrival overlap rate vs vsa_climax | ≤ 15% | % |
| Paired bootstrap p (HMM-TSMOM vs sade TSMOM, OOS Sharpe diff) | < 0.05 | p |

## 5. Independent Variables (Sabit grid — sweep YASAK)

| Parametre | Değer(ler) | Not |
|---|---|---|
| HMM n_states | 2 (sabit) | sweep yok — k=2 önceden kararlı |
| HMM emission | 2-dim Gaussian (r, rv) | sweep yok |
| HMM retrain horizon | 365d (sabit) | sweep yok — yıllık retrain |
| HMM expanding window minimum | 730d (2y) | sweep yok |
| TSMOM lookback L | 63 (sabit) | sweep yok — Moskowitz default, RAG-grounded |
| Realized vol window | 20 bar (sabit) | sweep yok |
| rv_floor | 30. persentil (sembol-bazlı, expanding) | sweep yok |
| ATR SL multiplier | 2.0 (sabit) | sweep yok |
| ATR trailing multiplier | 3.0 (sabit) | sweep yok |
| Risk per trade | %1 (sabit) | sweep yok |
| Universe filter | top-30 24h-volume rolling | sweep yok |

**Kritik kural:** Bu hipotez **parametre optimizasyonu OLMADAN** koşulur. Tek-shot test, Optuna yok, grid search yok. Gözlem sonrası "biraz daha iyi seçim" için parametre değişimi YASAK — bu uygulama kanunum; aksi halde §8'deki Bonferroni inflation tetiklenir.

## 6. Beklenen p-value (Pre-Registered)

- Tek-shot test (sweep yok): nominal eşik p < 0.05.
- López de Prado çerçevesinde: companion ailesinde n=60+ önceki abort sayısı varsa **Bonferroni post-hoc** p_eff < 0.05/60 ≈ **0.00083** gerekli. Bu çok katı; reddetme olasılığı yüksek.
- Daha makul Benjamini-Hochberg (FDR=0.10, family-size=60): rank-bazlı eşik, bu hipotez için yaklaşık p < 0.005.
- **Pre-registered hedef**: p_paired_bootstrap < 0.005 (Benjamini-Hochberg adaptive).

## 7. Stop Criteria (Erken Terk)

Aşağıdaki HERHANGI birisi tetiklenirse araştırma derhal arşivlenir, ileri aşamaya geçmez:

1. **IS Sharpe < 0.5** → araştırma terkedilir (RAG'de Sharpe-based gating Chan eşiği).
2. **IS Sharpe > 3 × OOS Sharpe** → López overfit kırmızı bayrak, terk.
3. **OOS trade count < 50** → istatistiksel anlamsız, terk.
4. **HMM state-A/state-B trade dağılımı %80/%20'den dengesiz** → HMM kullanımsız (tek state baskın), terk.
5. **HMM retrain horizon değiştirilmek istenirse** → hipotez ÖLÜ kabul edilir; yeni hipotez gerekir (parametre tuning protokol ihlali).
6. **corr(daily PnL, vsa_climax) ≥ 0.30** → companion gerekçesi düşer; isolation Sharpe çok güçlü olmadıkça terk.
7. **Backtest engine reproducibility hash uyuşmazlığı** → ops_engineer ile incident, hipotez reddedilir.

## 8. Curve-Fit Şüphesi (Açık Pre-Registration)

**Açıkça itiraf:** Bu hipotez **yüksek curve-fit riski** taşır. Sebepleri:

1. **Ekleme parametre yükü:** Sade TSMOM-sign-lookback (2026-06-10 doc) zaten kabul kriterini tutturamadı (4 family-test'ten 3'ünde abort vardı, OOS Sharpe 0.4-0.7 bandında). Üzerine HMM ekleyerek ölçüm uzayını genişletmek **olasılıkla yalancı iyileşme** üretir.

2. **HMM latent parametreleri:** state-sayısı, emission-modeli, retrain-pencere, label-switching kuralı, expanding-window min — her biri "araştırmacı tercihi" gibi gözükse de bunlar de facto parametredir. Sabit tutmak için açıkça pre-register edildi.

3. **Parametre/örnek oranı:** 4y daily, ~1000 bar/sembol × 30 sembol = ~30k bar. Sade TSMOM'da serbest p ~5; HMM ile +3 daha = p ≈ 8. Oran 8/30000 = 0.00027 → López'in 1/30 eşiğinin çok altında, OK. Ama HMM'in latent state-allocation'ı her sembol/yıl için kendi içinde fitting yapıyor; effective param sayısı şişebilir. **Mitigasyon:** her sembol için ayrı HMM yerine evren-wide tek HMM (sembol agnostik) ile koş — toplam param sayısı sabit kalır.

4. **Family-wise error:** 60+ companion seed-abort'a 61. ekleme. Bonferroni 0.05/61 ≈ 0.00082. Bu hipotez bu eşiği yenmek zorunda.

5. **In-sample mecbur regime markup:** HMM state etiketleri ("trend" vs "mean-revert") IS verisinden çıkartılıyor → label-switching kuralı (max |μ| state'i trend olarak işaretle) deterministik olduğu için pre-registered, ama HMM convergence'ı seed'e bağlı. **Mitigasyon:** 50 seed run, ortalama OOS metric raporlanır; varyans Sharpe ortalamasının %40'ından büyükse hipotez reddedilir.

6. **Confirmation bias hatırlatması:** "VSA bir rejimi kapsıyor, ben diğerini kapsayacağım" hikayesi mantıklı görünüyor — bu kritere göre confirmation bias kırmızı bayrağı taşıyor. Sayı kazanır, hikaye değil. Hipotezi sayısal kanıt olmadan terfi ettirmeyeceğim.

## 9. Robustness Suite (Backtest sonrası uygulanacak)

1. **Walk-forward 12 dilim** (Ocak-bazlı, 2y train + 6m test, step 3m). Min 9/12 dilim pozitif olmalı.
2. **Random parameter perturbation (50 seed):** HMM seed'i, label-switching tie-breaker — ortalama Sharpe kayıp < %25.
3. **Symbol-out CV:** her ilk-10 sembolü tek tek dışarıda bırak; min OOS Sharpe > 0.6.
4. **Regime split:** bull/bear/range 12-aylık dilimlerde ayrı ayrı OOS Sharpe. 3 rejimden 2'sinde pozitif olmalı.
5. **Stress periodları:** 2022-05 (LUNA), 2022-11 (FTX), 2024-03 (BTC ATH), 2024-08 (Yen carry). Her birinde MaxDD < %20.
6. **Shuffle baseline:** günlük returns'ü shuffle ettiğin null modeli yen (p_bootstrap < 0.05).
7. **HMM 2-state vs 1-state (degenerate) karşılaştırma:** HMM'i kaldır, sade TSMOM ile karşılaştır; paired bootstrap diff p < 0.005. **Bu testi geçmezse HMM gereksizdir — reddedilir.**
8. **Multiple testing correction:** Benjamini-Hochberg FDR=0.10 family-size=60.

## 10. Lab Devir Önkoşulu

§7 stop kriterleri ihlal edilmediyse, §4 hedefleri tutturulduysa VE §9 robustness suite'in 8/8 testi geçtiyse: Lab tournament'a devir aday olarak işaretlenir. Aksi halde gerekçeli arşiv (`memory/researcher/learning.md` 3 satırlık not).

## 11. Reproducibility Etiketi

- git_hash: (backtest sırasında stamplenecek)
- config_hash: yukarıdaki §5 sabit grid → deterministik
- data_hash: ingest manifest 2026-06-28 baseline
- random_seed: HMM seed = 42 (deterministik), perturbation seed set = [0..49]

## 12. Karar Akış (önceden yazılı)

```
1. Backtest çalıştır (tek-shot, sweep yok).
2. §7 stop kriterleri sorgu → biri tetiklenirse arşivle, dur.
3. §4 hedefleri sorgu → biri eksikse arşivle, dur.
4. §9 robustness suite çalıştır.
5. 8/8 geçer + §6 p-value eşiği geçer → Lab devir.
6. 8/8 geçer ama p-value eşiği geçmez → "edge gerçek olabilir, family-wise koruma engel" notu, ARŞİV (red değil, deferred).
7. Robustness'ta lookahead bulunursa → CRITICAL incident, signal_chief'e devir.
```

---

**Reviewer notu:**
- `lab_scientist`: tournament gates'e karşı pre-flight check
- `risk_officer`: position-sizing & SL parametreleri 18. kez kontrol
- `adversary_engineer`: HMM convergence + label-switching breakability red-team
