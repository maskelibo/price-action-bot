---
doc_id: researcher-20260531T143000-mat-hold-continuation-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-31T14:30:00Z
status: PROPOSED
confidence: med
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, cross_strategy, continuation, mat_hold, bulkowski, low_correlation, pre_registration]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-05-31-mat-hold-continuation-low-corr-to-vsa

> **Seed:** "Cross-strategy edge keşfi: aktif `vsa_climax_test` ile düşük korelasyonlu ek bir strateji (raftaki 66 adaydan)."
> **Cevap:** Bulkowski "Mat Hold" (Rising Three Methods) — yapısal olarak VSA climax reversal'ın tersi (trend continuation). Düşük korelasyon ex-ante güçlü gerekçeli.

## 1. İddia (pre-registered, ölçülebilir)

Crypto perpetual USDT evreninde (≥40 likit sembol, **delisting'ler dahil — survivorship-clean**), 1D timeframe'de, **1W EMA50 üzerinde** rejim filtresi varken, Bulkowski **Mat Hold** 5-bar bullish kalıbı:

- **Bar 1:** kapanış > açılış, `gövde / range ≥ 0.6` (büyük bullish bar)
- **Bar 2–4:** her biri Bar 1 high–low aralığında (inside), her bar gövdesi ≤ Bar 1 gövdesinin %50'si
- **Bar 5:** kapanış > Bar 1 kapanışı, `gövde / range ≥ 0.6` (breakout bar)

**Entry:** Bar 6 open (lookahead-safe; Bar 5 close'a göre karar, sonraki bar open'da giriş)
**SL:** 1.5 × ATR(14)
**Exit:** {fixed 2R, 10-bar opposite-channel trailing, hybrid} sweep
**Window:** 2021-01-01 → 2025-12-31 (5y, son 6 ay strict OOS hold-out)
**Maliyet:** taker fee 7.5 bps + slippage 5 bps (her giriş/çıkış)

**Hedef metrikler:**

| Metric | Hard Gate |
|---|---|
| Annualized net return (fee+slip sonrası) | **≥ %18** |
| Sharpe (annualized, daily PnL) — OOS | **≥ 0.8** |
| MaxDD (equity-based) | **≤ %22** |
| Trade count N (5y, tüm semboller toplam) | **≥ 80** |
| **Pearson corr(daily PnL, `vsa_climax_test` daily PnL)** | **≤ 0.20** *(asıl iddianın çekirdeği — diversification edge)* |
| Walk-forward dilim başarı | **≥ 9/12 pozitif** |
| Shuffle baseline empirical p (1000 perm) | **< 0.000231** (Bonferroni N=216 grid) |
| DSR (Deflated Sharpe Ratio, Bailey-Lopez) | **> 0.5** |

## 2. Gerekçe (RAG referansları)

- **[book_candlestick_statistics §Mat Hold (#10 score=0.557)]** — Bulkowski equity sample: %74 bullish continuation rate, ortalama hareket +%6.1, performance rank **10/103**. "Flag pattern'ının mum versiyonu; konsolidasyon sonrası momentum korunur." → Yapısal temel sağlam ama equity sample, kripto generalization riski var (aşağıda explicit guard).
- **[book_market_structure_order_flow §BOS close-based (#6 score=0.568)]** — Mat Hold'un breakout bar'ı (Bar 5 close > Bar 1 close) **close-based BOS** ile yapısal olarak özdeş. n=3 inside konsolidasyon → 3-bar pullback yapısal "internal liquidity" anlamı taşır; SMC paradigmasında da continuation kuvvetli.
- **[book_lopez_summary §overfit kriterleri (#1 score=0.582)]** — Promosyon gate'i için 6 red bayrak (DSR<0.5, PBO>0.5, IS/OOS Sharpe>3×, param/sample>1/30, WF Sharpe varyansı>ortalama, T<MinBTL) **bu hipotezde sıkı uygulanacak**.
- **[book_kaufman_summary §Donchian breakout (#7 score=0.563)]** — Asimetrik R-multiple yaklaşımı (%35 WR, 3-5R winners), trailing exit alternatifinin teorik temeli.
- **Cross-strategy gerekçesi:** `vsa_climax_test` = volume-spread reversal (mean-revert / exhaustion). Mat Hold = trend continuation. **Mekanik orthogonality** mevcut — null hipotez: corr ≈ 0. Eğer corr > 0.20 ölçülürse "yapısal orthogonality ampirik olarak gerçekleşmedi" → strateji portföye ek edge getirmez → red.

## 3. Null hipotez (Ne olursa çürür)

**H0:** Mat Hold sinyalinin (a) pozitif net edge'i yoktur **veya** (b) `vsa_climax_test` ile yüksek korelasyonludur (corr > 0.20).

H0 doğrulanırsa stratejiyi red ederim. Spesifik:
- Net annualized return ≤ 0 (fee/slip sonrası) → red.
- Shuffle baseline'ı yenmiyorsa (Bonferroni-adj p > 0.000231) → red.
- Corr ≥ 0.20 → cross-strategy değeri yok, red (asıl amaç başarısız).

## 4. Dependent variables (öncesinde tanımlandı)

- Annualized net return (fee+slip dahil)
- Sharpe (annualized, daily PnL)
- Sortino
- MaxDD (equity-curve based, **not** zero-base cumulative — bkz lesson `audit_risk CT-RSK-01`)
- Profit factor
- Win rate, avg R-multiple, R distribution skewness
- Trade count N
- **Corr(daily_pnl_mat_hold, daily_pnl_vsa_climax_test)**, Pearson, daily resample, sample ≥ 60 ortak işlem günü
- Walk-forward dilim pozitif oranı (12 dilim)
- DSR, PBO (Combinatorially Symmetric CV)

## 5. Independent variables (parametre uzayı — INTENTIONALLY coarse)

| Parametre | Aralık | DOF |
|---|---|---|
| Bar1_body_ratio_min | {0.5, 0.6, 0.7} | 3 |
| InsideBars_count | **{3} sabit** (Bulkowski kalıp tanımı) | 1 |
| Pullback_body_max (Bar1 gövdesinin oranı) | {0.3, 0.5, 0.7} | 3 |
| Bar5_close_vs_Bar1_close | {≥, > +0.2·ATR} | 2 |
| SL_atr_mult | {1.5, 2.0} | 2 |
| Exit_method | {fixed_2R, trailing_10bar, hybrid} | 3 |
| Trend_filter | {EMA50_1W, none} | 2 |

**Toplam grid:** 3·1·3·2·2·3·2 = **216 kombinasyon**
**Bonferroni p eşiği:** 0.05 / 216 = **0.000231**
**Param/sample ratio guard (Lopez):** 6 free param / N=80 ≈ **1/13** → **REDLINE 1/30 ihlali**. → Bu, **bilinçli early-warning**: N ≥ 240 sağlamadıkça çoklu-parametre kombinasyonu Lopez kriterini geçemez. Kalıbı gevşetmeden N'i 240'a çıkarmak için universe'i ≥40 sembol + 5y window'a sabitledim. Yine de fail riski **yüksek** — bu açıkça raporlanacak.

## 6. Beklenen istatistiksel test

- **Primary:** Shuffle baseline 1000 permütasyon → empirical p < 0.000231 (Bonferroni adj) **veya** Benjamini-Hochberg FDR q < 0.10.
- **Secondary:** DSR (Bailey-Lopez 2014) > 0.5; PBO < 0.5.
- **Power analysis:** N=80 ile R-distribution mean test → MDE ≈ 0.20 R (Cohen's d ≈ 0.3, α=0.05, power=0.8). Edge < 0.20 R altta detect edilemez (kabul edilen).

## 7. Robustness suite (SOP-3, zorunlu — atlanamaz)

- Walk-forward 3y train / 6m test, step 3m (12 dilim hedef; min 9/12 pozitif)
- Param perturb ±%10, 50 seed → ort. Sharpe kaybı ≤ %25
- Symbol-out leave-one-out CV (≥40 sembol) — min OOS Sharpe ≥ 0.5
- Regime split: bull (BTC > 200D MA), bear, range — en az 2'sinde pozitif
- Stress periodları: 2022-05 (LUNA), 2022-11 (FTX), 2024-03 (BTC ATH), 2024-08 (Yen carry) — herhangi birinde -%15'ten kötü kayıp → red
- Shuffle baseline (yukarıda)
- Survivorship: `data/universe.py::build_universe(date)` ile delisting'ler **dahil**
- Lookahead test: `detector(df.iloc[:t+1])[t] == detector(df)[t]` her t için (`tests/test_lookahead.py` ek case)

## 8. Stop criteria (early abort — koda başlamadan önce sözleşme)

1. In-sample median Sharpe < 0.5 → araştırma **terkedilir** (kod silinir, learning.md'ye 3 satır gerekçe).
2. N < 50 (5y, all symbols toplam) → kalıp çok nadir, anlamsız.
3. Walk-forward 12 dilimden ≥ 5 dilim negatif → instability, red.
4. **Corr(`vsa_climax_test`) > 0.20** → cross-strategy değeri yok. **SOP-4b iterate UYGULANMAZ** (asıl iddianın özü çürüdü) → direkt red.
5. Best parameters grid sınırında → uzayı genişlet, başa dön; 2. denemede yine sınırda → red.
6. Bulkowski'nin equity %74 continuation rate'i crypto'da **<%55**'e düşerse → yapısal temel zayıf; "edge mevcut ama küçük" notu + red.
7. **IS Sharpe > 3 × OOS Sharpe** (Lopez §1 kriteri) → overfit, red.
8. Param/sample ratio > 1/30 (Lopez) ve N < 240 → istatistik temel yetersiz, red.

## 9. Curve-fit şüphesi (kendi çıkışımı eleştir — anti-narrative)

- **Bulkowski equity → crypto generalization:** %74 continuation kripto'da büyük olasılıkla daha düşük. Gate'i bilinçli **çok daha düşük** koydum (return %18, Sharpe 0.8, not %74). Yine de "kalıbın kendisinin" işe yaramama olasılığı yüksek.
- **216 grid + Bonferroni cezası:** Çok büyük bir grid yok ama N=80 ile **param/sample 1/13** → Lopez REDLINE. Bunu açıkça stop-criteria #8'e koydum.
- **5-bar nadir kalıp:** N hedefi (≥80) ulaşılmazsa hiçbir gate anlamlı değil. Universe'i ≥40 sembol + 5y aldım ama hâlâ riskli.
- **"vsa_climax ile low corr" ex-ante güçlü ama ex-post tesadüfen örtüşebilir:** Corr ≤ 0.20 hard gate; sweep ile düşürülemez (cherry-pick yasak — sweep'ten önceki primary metric).
- **Bar1_body_ratio, pullback_body, Bar5_close threshold** eşikleri Bulkowski'den **interpolated**; arbitrary. Sweep coarse (0.1-0.2 adım) — overfit-flag #3 guard.
- **Exit method sweep (3 farklı):** Bu en şüpheli noktam — exit optimizasyonu klasik overfit yatağı. WF her exit method için ayrı yapılacak; "hangisi kazanırsa" cherry-pick'i Bonferroni'ye dahil ettim.
- **Optuna kullanmıyorum, full grid:** 216 kombinasyon küçük; TPE ile cherry-picking yerine açık grid + tam Bonferroni. Daha dürüst.
- **"Mantıklı geliyor" tuzağı:** Kontinuation kalıbı + trend filter çok "mantıklı" anlatı. Mantıklı = bias. Sayı ister; sayı yoksa red.

## 10. Decision matrix

| Kriter | Eşik | Tip | Fail action |
|---|---|---|---|
| Annualized return (net) | ≥ 18% | hard | red |
| Sharpe (OOS) | ≥ 0.8 | hard | SOP-4b iterate (eğer return > 0) |
| MaxDD | ≤ 22% | hard | SOP-4b iterate (eğer return > 0) |
| N (trade count, 5y) | ≥ 80 | hard | red (gevşek tanımlama YASAK) |
| **Corr(vsa_climax)** | **≤ 0.20** | **hard** | **red, iterate yok** (asıl amaç) |
| WF dilim pozitif | ≥ 9/12 | hard | red |
| Shuffle p (Bonferroni-adj) | < 0.000231 | hard | red |
| DSR | > 0.5 | hard | red |
| Param/sample (Lopez) | ≤ 1/30 (N≥240) | hard | red veya N artır |
| Crypto continuation rate | ≥ 55% | soft (info) | warning only |

**Karar yolu:**
- TÜM hard ✓ → Lab tournament adayı (`configs/strategies/mat_hold_v1.yaml` draft + insan onayı).
- Return/Sharpe ✓ ama DD fail → SOP-4b iterate (risk_pct ↓, exit early-take, regime subset).
- **Corr > 0.20 → ASIL İDDİA ÇÜRÜK, red. İterate uygulamaz.**
- Return ≤ 0 → red, arşiv (`memory/researcher/learning.md`'ye 3 satır gerekçe).

## 11. Reproducibility

- `git_hash:` (commit time'da damgalanır)
- `config_hash:` SHA256 of full grid YAML
- `data_hash:` `data/universe.py::manifest_hash(2021-01-01, 2025-12-31)`
- `seed:` 42 (Optuna kullanılmıyor — full grid, deterministic)

## 12. Pre-registration commit

Bu doc commit edildiği anda **freeze**. Sonraki sweep sonuçlarına göre claim/gate değiştirme = **p-hacking, yasak**. Eğer gate'in yanlış kalibre olduğunu fark edersem yeni hipotez doc'u açılır (`supersedes` ile bu doc'a bağlanır), eski karar kayıt kalır.

---

**İlk review beklenti:** lab_scientist (gate kalibrasyonu sağlam mı? Param/sample 1/13 → N hedefini 240'a çıkarmak gerçekçi mi?), risk_officer (corr ≤ 0.20 portföy bazında yeterli diversification anlamlı mı? DD ≤ 22% sermaye koruma kuralları altında?).
