---
doc_id: researcher-20260612T071500-choch-close-based-n3-1d-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-12T07:15:00Z
status: PROPOSED
confidence: med
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, cross_strategy, low_corr, choch, market_structure, 1d, vsa_diversifier, pre_registered]
supersedes: null
hash: null
---

# HYP-2026-06-12 — CHoCH (Change of Character, close-based, n-swing, 1D) as Low-Correlation Diversifier to `vsa_climax_test`

## 0. Curve-fit Şüphesi (Honest Disclosure — açık önce)

- Raftaki 66 candidates içinden CHoCH'u "uygun aday" diye seçişimin **kendisi** zayıf bir multiple-testing zincirinin parçası. CHoCH ortogonal **görünüyor** çünkü literatürde öyle anlatılıyor; sayı değil hikâye.
- BOS hipotezi (HYP-2026-06-11) henüz tamamlanmadı; CHoCH onun mekanik aynası — BOS PASS olursa CHoCH overlap'i artar; BOS RED olursa CHoCH muhtemelen aynı sebepten redde gider. **Yüksek koşullu bağımlılık.**
- Grid 4×3 = 12 trial → her trial bağımsız test sayılırsa Bonferroni eşiği p < 0.00417. **Tek bir parametre değişikliği post-hoc yapılırsa hipotez yakılır.**
- RAG #6'nın "Yüksek mechanical workability" değerlendirmesi bir **edge garantisi değil**, sadece "kodlanabilir" demek. Bulkowski tarzı win-rate verisi yok — bu RAG hattında CHoCH için **prior istatistik yok**, yalnız mekanik tanım var. Bu bir kırmızı bayraktır: literatür hak edilmemiş güven sağlayabilir.
- Stop criteria önceden yazılı: IS Sharpe < 0.5 ise derhal terk. Tetik çekildiğinde **iterate çağrısı yok** (SOP-4b only after positive monthly ROI confirmed); aksi halde p-hacking.

## 1. Seed & Motivation

Aktif strateji `vsa_climax_test` — **volume-fade / mean-revert at exhaustion** sınıfından. Aranan diversifier'ın yapısal olarak farklı olması şart (DSR shrinkage'i azaltmak, effective-N artırmak için).

CHoCH = **trend-rejim değişimi** sinyali: önceki HH/HL diziliminin LL ile kırılması (long bias → short bias geçişi) veya tersi. Tetik koşulu:
- Mevcut trend yönünde son n-bar swing değiştirildi (close-based confirmation).
- VSA climax ile **kavramsal ortak nokta yok**: VSA hacim bağımlı, CHoCH yalnız price-structure'a bakar.
- Beklenen rolling-90d Spearman ρ ≈ 0.0–0.15 (hipotez tarafı; testte düşecek).

Aktif kol `vsa_climax_test` (1D, volume-z + climax bar + fade) → CHoCH'un 1D üzerinde swing-yapı tabanlı tetiklemesi entry-time çakışmalarını **doğal olarak azaltır** (climax bar'lar tipik trend ortasında / tepelerde olur; CHoCH yapısal olarak **trend bittikten sonra** tetikler).

## 2. Hypothesis (pre-registered, fixed before any code run)

> **Iddia:** 2022-01-01 → 2025-06-30 in-sample / 2025-07-01 → 2026-06-10 out-of-sample, **19-sembol all-liquid USDT-perpetual pool**'unda (build_pool_19sym), **1D timeframe** üzerinde, **CHoCH-long sinyali** (downtrend evresinde fiyatın son n-bar swing-high'ı close-based kırması, trend-state önceki LH+LL→HH dönüşümü) + **ATR-stop k × ATR(14)** + **10-bar opposite swing trailing exit** + fee 7.5 bps taker / slip 5 bps modeliyle, **sabit-fraksiyon %1 risk/trade** non-compounding ölçümünde:
>
> 1. **OOS net annualized return** ≥ **+15 %/yıl** (BOS'tan daha mütevazı eşik; CHoCH frekansı doğal olarak düşük, daha az trade → daha düşük getiri beklenir)
> 2. **OOS Sharpe** ≥ **0.80** (Chan retail-realistic single-asset eşiği, RAG #9)
> 3. **OOS MaxDD** ≤ **22 %** (account-equity-base, trade-shuffle Monte Carlo p95 ile bantlı)
> 4. **|rolling-90d Spearman ρ(CHoCH-long daily PnL, vsa_climax_test daily PnL)|** < **0.25** (OOS dilimi; BOS hipotezinden daha sıkı çünkü CHoCH yapısal olarak daha ortogonal olmalı — değilse zaten diversifier sıfatı yok)
> 5. **DSR (Lopez)** > **0.50** ve **PBO (Combinatorially Symmetric CV)** < **0.50**
> 6. **Profit factor** > **1.3**, **OOS trade sayısı** ≥ **90** (19 sembol × ortalama ≥ 4.7 trade — düşük frekans tolere edilir ama 90 altı underpowered)
> 7. **Jaccard(entry-bar overlap, vsa_climax_test)** < **0.05** (Grimes ABC 0.019 başarısının altın standardı; ≥ 0.05 ise diversifier değil duplicate)

**Yedi maddeden biri dahi sağlanmazsa hipotez REDDEDİLİR — terfi adayı çıkmaz, iterate denemesi açılmaz (çünkü positive monthly ROI yoksa SOP-4b tetiklenmez).**

## 3. Null Hypothesis & Falsification

- **H0 (edge):** CHoCH-long sinyali, fee+slip sonrası, shuffle-baseline'a göre istatistiksel anlamlı edge üretmez (shuffle p ≥ 0.05, n=1000 permütasyon).
- **H0' (correlation):** CHoCH PnL serisi vsa_climax_test PnL serisiyle |ρ| ≥ 0.25 — diversifier sıfatını hak etmez.
- **H0'' (overlap):** Entry-bar Jaccard ≥ 0.05 — duplicate trade.

**Falsification koşulları (her biri tek başına TERK için yeter):**

| # | Koşul | Sebep |
|---|---|---|
| F1 | IS Sharpe < 0.5 | Lopez red flag — IS bile yoksa OOS umut yok |
| F2 | IS/OOS Sharpe oranı > 3.0 | Lopez red flag #4 — curve-fit |
| F3 | Walk-forward dilim pozitif/toplam < 60 % | Unstable edge |
| F4 | Stress dilim (LUNA 2022-05, FTX 2022-11, USDC depeg 2023-03, Yen carry 2024-08) MaxDD > 25 % | Tail-fragile |
| F5 | Shuffle-baseline p ≥ 0.05 | Şans |
| F6 | Bonferroni p_corrected ≥ 0.00417 (= 0.05 / 12 trial) | Multiple-testing inflation |
| F7 | OOS trade sayısı < 90 | Underpowered |
| F8 | Symbol-out CV: 19 sembolün herhangi 1'i çıkarılınca OOS Sharpe %30+ düşüyor | Single-symbol bias (LUNA-tipi outlier kaldıracı) |
| F9 | Regime split: bull/bear/range 3 rejimden 2'sinden azı pozitif | Regime-fragile |

## 4. Independent Variables (grid — coarse, 12 nokta, **post-hoc genişleme YASAK**)

| Param | Grid | Adım | Toplam | Gerekçe |
|---|---|---|---|---|
| `swing_n` (CHoCH için bakılan bar) | {3, 5, 7, 10} | 4 nokta | 4 | RAG #6 "n=3" baseline; 5/7/10 standart swing analizi |
| `atr_k` (stop multiplier) | {1.5, 2.0, 2.5} | 3 nokta | 3 | Klasik Kaufman/Brooks aralığı; daha geniş aralık curve-fit |
| **TOPLAM TRIAL** | | | **12** | Bonferroni 0.05 / 12 = **0.00417** |

**Sabit (deney boyunca dondurulmuş):**
- Universe: build_pool_19sym (delisting-aware, survivorship-bias-free)
- Timeframe: 1D primary
- Fees: 7.5 bps taker (konservatif), -1 bps maker (kullanılmıyor — entry market)
- Slip: 5 bps (her trade'de simetrik)
- Risk: %1 sabit-fraksiyon, non-compounding (Memory note: backtest-compounding-inflation)
- Trailing exit: 10-bar opposite swing (Turtle System 1 default, RAG #7) — **fixed, not tuned**
- HTF filter: yok (CHoCH zaten trend-değişim mekaniği)
- Entry bar: t close-based confirmation → entry t+1 open (lookahead-safe)

## 5. Dependent Variables (raporlanacak metrikler)

| Metrik | IS | OOS | Hedef | Critical? |
|---|---|---|---|---|
| Net annualized return | x | x | OOS ≥ +15 % | Y |
| Sharpe (annualized) | x | x | OOS ≥ 0.80 | Y |
| MaxDD (account-equity) | x | x | OOS ≤ 22 % | Y |
| Profit factor | x | x | OOS > 1.3 | Y |
| Trade count | x | x | OOS ≥ 90 | Y |
| Win rate | x | x | n/a (info) | N |
| Spearman ρ vs vsa_climax_test (rolling 90d) | — | x | OOS < 0.25 | Y |
| Entry Jaccard vs vsa_climax_test | — | x | OOS < 0.05 | Y |
| DSR (Lopez) | — | x | > 0.50 | Y |
| PBO (CSCV, k=16) | — | x | < 0.50 | Y |
| Shuffle p-value (n=1000) | — | x | < 0.05 | Y |
| Bonferroni p_corrected | — | x | < 0.00417 | Y |
| Walk-forward (3y/6m/step 3m, ~6 dilim) % positive | x | — | ≥ 60 % | Y |
| Symbol-out CV: min OOS Sharpe across 19 leave-one-out | — | x | drop ≤ 30 % | Y |
| Stress slice MaxDD (LUNA/FTX/USDC/Yen) | — | x | each ≤ 25 % | Y |
| Regime split (bull/bear/range): which rejected positive Sharpe | — | x | ≥ 2/3 positive | Y |

## 6. Expected p-value (paranoid)

- Raw single-best-trial p: hedef **< 0.001** (shuffle baseline)
- 12-trial Bonferroni: hedef **< 0.00417**
- Benjamini-Hochberg FDR (q=0.10): hedef listesi top-k anlamlı
- DSR (Lopez): hedef **> 0.50** (account for trial count + Sharpe variance + skew + kurtosis)
- **Eğer raw p < 0.05 ama Bonferroni p ≥ 0.00417 → RED** (BOS hipotezinde de aynı kural)

## 7. Stop Criteria (terk anı)

1. IS Sharpe < 0.5 (en geç in-sample run sonunda) → araştırma derhal sonlanır, learning.md'ye 3 satır gerekçe.
2. Walk-forward 6 dilimin 3'ünden fazlası negatif → terk.
3. Lookahead audit (`tests/test_lookahead.py`) PASS değilse → kod hatası, terk + Signal Chief uyarı.
4. Compute budget: tek configurasyon walk-forward > 8 saat → engine optimize edilmeden ileri gidilmez.
5. Trial sayısı 12'yi geçerse → **derhal red** (post-hoc parameter exploration p-hacking sınırı).

## 8. RAG Referansları (kullanılan)

- **#6 (book_market_structure_order_flow):** CHoCH close-based n=3 → "YÜKSEK mechanical workability". Trend-state machine literatürü.
- **#1 (book_lopez_summary):** DSR < 0.5, PBO > 0.5, IS/OOS Sharpe > 3, params/sample > 1/30 → kırmızı bayrak; gate'lere doğrudan çevrildi.
- **#7 (book_kaufman_summary):** 10-bar opposite channel trailing exit (Turtle S1 default) — fixed exit logic, optimize edilmedi.
- **#9 (book_chan_summary):** Single-asset OOS Sharpe > 0.8 retail-realistic eşiği — KPI #2.

**Yetersiz referans uyarısı:** CHoCH için Bulkowski tarzı statik win-rate verisi RAG'de yok. Yalnız mekanik tanım var; bu hipotez doğrulanırsa **yeni veri katkısı** olur, doğrulanmazsa **literatürün "high mechanical workability" değerlendirmesinin edge garantisi olmadığı** tezi güçlenir.

## 9. Karar Akışı

```
1. Reproducibility hash freeze (git, config, data) → bu doc commit edildiğinde
2. IS run → Sharpe ≥ 0.5? hayır → STOP (F1)
3. OOS run + robustness suite (S0-S9) → hepsi PASS?
   - hayır → RED, gerekçeli arşiv, learning.md update
4. Cross-correlation + Jaccard vs vsa_climax_test → eşikler PASS?
   - hayır → "edge var ama duplicate" notu, RED
5. Bonferroni & DSR → PASS?
   - hayır → RED (multiple-testing inflation)
6. TÜM gate PASS → terfi adayı `configs/strategies/choch_n3_1d_diversifier.yaml` (TASLAK, insan onayı gerekir)
   → Lab Scientist'e tournament için devredilir
7. Eğer OOS monthly ROI > 0 ama gate'lerden biri kötü → SOP-4b iterate path (risk reduction, regime filter, confluence)
```

## 10. Reproducibility

- Git commit: bu doc commit'i sonrası `<sha>` hash sabitlenir (env: `RESEARCH_GIT_HASH`)
- Config hash: yaml config'in SHA256'sı backtest manifest'e yazılır
- Data hash: pool dosyası SHA256 + line count (build_pool_19sym → `sec53_*_pool_v11_*.pkl`)
- Reproducibility hedefi: bit-identical PnL serisi (`tests/test_backtest_reproducibility.py`)

---

**Bu doc commit edildikten sonra parametre uzayı veya threshold'lar değiştirilemez. Değiştirilirse hipotez yakılır, yeni doc (post-hoc) açılır, ama `supersedes` ile bağlı ve eski sonuçlar `unbiased baseline` olarak işaretlenir.**

**Status:** PROPOSED — Lab Scientist + Risk Officer + Adversary Engineer review bekliyor.
