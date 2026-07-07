---
doc_id: researcher-20260624T180000-vol-regime-sizing-v9
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-24T18:00:00Z
status: DRAFT
confidence: med
depends_on:
  - researcher-20260620T000000-volatility-regime-sizing-optimization
  - researcher-20260616T023500-vol-regime-sizing-optimization-seed-abort-v7
  - researcher-20260614T100000-vol-regime-sizing-modulation
  - researcher-20260612T093000-vol-regime-sizing-v1
  - researcher-20260610T023100-volatility-regime-sizing-optimization
  - researcher-20260606T143500-volatility-regime-sizing-optimization-seed-abort-v3
  - researcher-20260531T143500-volatility-regime-sizing-optimization-seed-abort-v2
  - researcher-20260531T030500-volatility-regime-sizing-seed-abort
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags:
  - hypothesis
  - sizing
  - volatility_regime
  - kaufman_regime_aware
  - lopez_dynamic_deleveraging
  - fractional_kelly
  - sop_1
  - pre_registration
  - familywise_n_9
  - curve_fit_warning
supersedes: null
hash: null
---

# Hypothesis: HYP-2026-06-24-vol-regime-sizing-v9

## 0. Meta
- **Hipotez ID:** HYP-2026-06-24-vol-regime-sizing-v9
- **Versiyon:** 0.1 (seed'in 9. enjeksiyonu; aile-içi v8 mantıksal devamı)
- **Pre-registration:** 2026-06-24 (kod yazılmadan önce)
- **Seed:** "Volatility regime sizing optimization"
- **Familywise N (Bonferroni base):** **9** — aynı seed için 8 prior hipotez (3 explicit abort, 5 setup) → α' = 0.05 / 9 = **5.56e-3**. Bu hipotez α'≥5.56e-3 ile geçemezse REDDEDİLİR.
- **Carrier:** Aktif live champion = `configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml` (v14 family, `risk_pct=0.005`, 19-sembol live evreni). Carrier'ın entry/exit sinyalleri SABİT — sadece sizing politikası değişir (orthogonality).

---

## 1. İddia (ölçülebilir, tek cümle, sıfır sweep)

> "USDT-perpetual evreni (19 sembol, live universe v14, delisting-aware), 15m timeframe, carrier = `risk_phoenix_scalp_15m_widestop_vsa2`, in-sample 2023-12-01 → 2026-04-30 (~17 ay) + walk-forward OOS 2026-05-01 → 2026-06-19 (12 ardışık 4-günlük dilim). Sizing wrapper: **ATR(14) / close**'un son **60-bar tersile rejimi** ile carrier `risk_pct=0.005` baz oranını çarp — **{low(Q≤0.33)=1.00, mid(Q0.33–0.66)=0.70, high(Q≥0.66)=0.45}** — ve López dynamic deleveraging `L_t = (1 − D_t / 0.20)^1` ile **ek çarpan** uygula (D_t = rolling-30-bar account-equity DD; clip≥0). Carrier-only (sabit 0.005, deleveraging YOK) baseline'a karşı, fee=7.5bps taker + slippage=5bps, başlangıç 10k USDT, paired bootstrap (10k resample) ile OOS dilimde:
>
> 1. **OOS Sharpe Δ ≥ +0.20** (göreli ≥ %15)
> 2. **OOS MaxDD Δ ≥ %25 mutlak azalış** (örn. baseline −%24 → aday ≤ −%18)
> 3. **OOS net annualized return Δ ≥ −2pp** (return cost'u kabul edilebilir; aday return'ü baseline'dan ≤ 2 puan altına inmesin)
> 4. **OOS Calmar Δ ≥ +%20**
> 5. **Walk-forward 12 dilimden ≥ 8'inde DD iyileşmesi** (Wilcoxon paired)
> 6. **Shuffle baseline'a karşı p < 5.56e-3** (Bonferroni N=9 floor) **VE** Holm step-down ile aynı eşik
>
> **TÜM 6 KRİTER birlikte** sağlanmazsa terfi yok."

---

## 2. Null hipotez

> H₀: ATR-tersile rejim sizing × López deleveraging wrapper, carrier sabit-risk_pct=0.005 baseline'ına göre OOS Sharpe iyileşmesi getirmez (ΔSharpe ≤ 0). Shuffle null = OOS bar-index'leri permüte ederek aynı wrapper'ı uygulamak.

---

## 3. Gerekçe (RAG referansları)

- **[#4 Kaufman]** Rolling Sharpe / win-rate ile "regime-aware fixed-fractional" sizing — gerçekleşen edge zayıfsa size'ı yarıya indir. Bizim wrapper buna ATR-percentile analoğu (returns yerine volatilite proxy).
- **[#5 López de Prado]** Dynamic deleveraging `L_t = L* · (1 − D_t / DD_max)^α`, α∈[1,2]. α=1 sabit alındı (en konservatif — sweep yapılırsa familywise-N şişer).
- **[#6 Kaufman]** Fractional Kelly 0.1f–0.25f pratiği — 1.00/0.70/0.45 çarpanları bu bandın içinde kalır (carrier zaten 0.005=0.5%).
- **[#9 Grimes]** Volatilite döngüseldir; düşük→yüksek→düşük geçişleri sistematik. Sizing'i bu döngüye bağlamak teorik olarak symmetric capital allocation.
- **[#7 Kaufman]** Crypto için %0.5–1.0 risk bandı; carrier zaten 0.005=düşük tarafta — yani wrapper'ın etkisi "negative-skew dönemleri kestiği" tezi üzerinden ölçülür.

---

## 4. Dependent variables (önceden taahhüt)

- OOS net annualized return (after fee+slip)
- OOS Sharpe (annualized, paired vs baseline)
- OOS MaxDD (account-equity tabanlı, **cum-PnL DEĞİL** — bkz. CT-RSK-01 ders)
- OOS Calmar (return / |MaxDD|)
- OOS Profit factor
- 12-dilim DD iyileşme sayısı (Wilcoxon paired)
- Shuffle null'a karşı p-value (10k resample)
- IS↔OOS Sharpe gap (curve-fit barometresi)

---

## 5. Independent variables (TÜMÜ SABİT — sweep YOK)

| Parametre | Değer | Kaynak |
|---|---|---|
| ATR window | 14 | Wilder klasik (sweep yapılmaz) |
| Percentile lookback | 60 bar (15m = 15 saat) | Tek değer; 30/90/120 denenmez |
| Bin sayısı | 3 (tersile) | Sabit |
| Multiplier vector | [1.00, 0.70, 0.45] | Kaufman fractional kelly 0.1f–0.25f bandı içinden 3 nokta |
| López α | 1.0 | Sabit; α=2 denenmez (familywise-N) |
| López DD_cap | 0.20 | Sabit; 0.15/0.25/0.30 denenmez |
| López D_t pencere | 30 bar (rolling equity DD) | Sabit |
| Carrier (host) | risk_phoenix_scalp_15m_widestop_vsa2 | Aktif live champion; değiştirilmez |
| Universe | 19 sembol live evreni | Sabit |
| IS dönem | 2023-12-01 → 2026-04-30 | Sabit |
| OOS dönem | 2026-05-01 → 2026-06-19 | Sabit (12 × 4-gün dilim) |
| Fee/slip | 7.5bps / 5bps | Konservatif sabit |

**Sweep değişkeni sayısı: 0.** Bu bir **dataset koşulu olarak tek-noktasal test**tir. Geçerse "sizing wrapper konsepti vol-regime için pozitif edge'lidir" demektir; geçmezse seed kapalıdır.

---

## 6. Beklenen p-value ve istatistiksel düzeltme

- **Pre-registered α' = 0.05 / 9 = 5.56e-3** (familywise-N = bu seed'in 9. enjeksiyonu)
- **Holm-Bonferroni step-down:** 6 birincil metrik için ortak p-vektörü üzerine uygulanır
- **Paired bootstrap:** 10k resample, baseline trade-by-trade equity curve vs aday equity curve
- **Wilcoxon signed-rank:** 12 walk-forward dilim DD-Δ ≥ 0 sayımı
- **DSR (Deflated Sharpe Ratio):** N_trials=9 ile düzeltilmiş aday Sharpe; DSR > 0 olmalı

**Eğer aday Sharpe p-value > 5.56e-3 ise — sayısal olarak iyi görünse bile — REDDET.**

---

## 7. Stop criteria (hipotez terk koşulları)

| Tetik | Sebep |
|---|---|
| IS Sharpe iyileşmesi < +0.10 | edge konsept-altı |
| IS↔OOS Sharpe gap > %40 | overfit (mevcut kırmızı bayrak listemizden) |
| OOS dilim 12'de < 6 pozitif DD-Δ | tutarsız |
| Multiplier vector değiştirme isteği | sweep yasak — değişiklik **yeni hipotez** olur |
| López α / DD_cap değiştirme isteği | aynı sebep |
| Carrier değişmesi gerekirse | wrapper'ın carrier-bağımsız iddiası çürür |
| Best params kapalı-form değerlerinden uzaklaşırsa | overfit eğilimi |
| Shuffle null p > 5.56e-3 | reddet |

---

## 8. Curve-fit kırmızı bayrakları (yapısal şüphe — açık)

1. **🚩 Familywise-N = 9 inflation.** Bu seed son 24 günde 9. kez işleniyor. Her tekrar prior bir red'in sayısallaştırılmış halini denemek demek. Bonferroni floor α/9 = 5.56e-3 — pratikte 0.5%-anlamlılık. Bu eşik aşılmazsa seed teorik olarak ÖLÜ olarak işaretlenir; v10 yazılmaz.
2. **🚩 Multiplier vector [1.00, 0.70, 0.45] keyfi.** Kaufman literatürü "high vol = küçült" diyor ama 0.70 ve 0.45 sayısal seçimleri savunması zor. **Sweep yasağı** bu zayıflığı kapamaz — yalnızca *bu specific noktanın* test edilmesini garantiler. Geçerse "vol-regime sizing genel olarak iyi" değil "bu özel parametreleştirme tesadüfen geçti" demek olabilir → çoklu-noktaları test eden bağımsız bir genişleme (yeni hipotez) gerekir.
3. **🚩 Carrier (host) seçimi v14 = live champion.** Live champion zaten son 14 günde "iyi giden" bir koldur (selection bias). Wrapper'ın katkısı host'un kendi iyi gidişinin yarattığı bir trend illüzyonu olabilir → host'u **fixed-as-of date** kullanmak (canlı performansa bakmadan yıl başı snapshot) IDEALI, ama eldeki tek production carrier bu — kabul edilen bir confounding.
4. **🚩 OOS dönem kısa (50 gün).** 12 × 4-gün dilim. Walk-forward Wilcoxon güçlü değil. Δ-Sharpe noise'a karşı kırılgan. Bu yüzden zorunlu **OOS net return kötüleşmesi ≤ 2pp** kriteri — return'ün düşmemesi sizing'in "kötü zamanı kesip iyi zamanı koruduğu" tezinin tek pre-registered korumasıdır.
5. **🚩 60-bar lookback "neden 60?" — savunması zayıf.** 15m × 60 = 15 saat; günlük rejim geçişlerini yakalar ama "neden 30 değil" sorusunun cevabı yok. Tek noktasal seçim → familywise-N tüketmez ama post-hoc yorum şüphesi kalır.
6. **🚩 López α=1 (lineer) keyfi.** α=2 quadratic deleveraging hipotetik olarak daha güçlü drawdown koruma. α=1 seçimi konservatif ama sweep yapmamak için. Geçerse "α=1 yeterli" değil "α=1 bu noktada şans" da olabilir.
7. **🚩 8 prior + 3 abort = bu seed'in "p-hacking" şüphesi.** Sürekli yeniden kurulması, sayı işin içinde olduğu için değil **istenen sonuca ulaşana kadar formülasyon değiştirme** kalıbı. v9 geçerse de v9'un test setup'ı 8 prior'ın "neyin işe yaramadığı"ndan beslendiği için **şartlandırılmış post-hoc** sayılır → bağımsız bir validation set ile (örn. forex 4H carrier) tekrar doğrulanmadan terfi YOK.

---

## 9. Reject criteria (bu testi geçse bile)

| Koşul | Aksiyon |
|---|---|
| 1–6'dan herhangi birinin sağlanmaması | **Reddet**, "seed teorik olarak ölü" işareti |
| Geçerse de IS↔OOS gap > %30 | Suspended → bağımsız carrier (örn. brooks_failed_breakout v11 dataset'i) ile cross-validation; o da geçerse Lab tournament aday |
| Geçerse + cross-validation geçerse | Lab tournament'a aday olarak verilir; direkt deploy YOK |

---

## 10. Pre-test reproducibility hash

- Carrier config snapshot SHA: <runtime'da hesaplanacak — `git rev-parse HEAD:configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml`>
- Data manifest SHA: `data/manifest.json` 2026-06-24 snapshot
- Backtest engine git SHA: HEAD (test öncesi dondurulacak)
- Test setup commit SHA: bu doc'un kayıt edildiği commit

---

## 11. Decision tree (test sonrası)

```
Run backtest (carrier + wrapper) → IS+OOS metrics
  ├─ IS Sharpe Δ < +0.10                → REJECT (edge konsept altı)
  ├─ IS/OOS gap > %40                    → REJECT (overfit)
  ├─ 6 kriterden herhangi biri ✗         → REJECT
  ├─ 6/6 ✓ + p < 5.56e-3                 → SUSPEND for cross-validation
  │   └─ cross-validation (brooks v11) ✓ → Lab tournament aday (drift gate)
  │   └─ cross-validation ✗              → REJECT (carrier-specific overfit)
  └─ Familywise-N geçer + DSR > 0        → seed yaşar; v10 hipotezi ANCAK kavramsal yeni axis ile yazılabilir (yeni multiplier vektörü sweep'i ≠ yeni hipotez)
```

---

## 12. Beklenti (subjektif prior)

- P(geçer | curve-fit suspicion) ≈ **%15-20**.
- P(geçer × cross-validation) ≈ **%5-8**.
- Yani bu hipotezin asıl değeri **REDDEDİLMESİNDEN** beklenen sinyal — eğer 6/6 kriterli sıkı setup yine geçemezse "vol-regime sizing fixed-multiplier şemasıyla **edge YOK**" konklüzyonu pre-registered olarak destek bulur ve seed kapanır.

---

## 13. Çıkar çatışması notu

- Bu wrapper canlı v14 host üzerinde test edileceği için, "wrapper iyi gözüktü" sonucunun sebebi **canlı carrier'ın iyi gidişatı** olabilir. Bu yüzden **OOS dönem live trading başlangıcından (2026-06-11) bağımsız** seçildi (2026-05-01 → 2026-06-19). Live influence'ı 8 günle sınırlı.

---

> **Pre-registration commit:** Bu dosya değiştirilmeden önce bir hash alınır; testten sonra değişiklik = pre-registration ihlali = hipotez geçersiz.
