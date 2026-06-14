---
doc_id: researcher-20260605T080000-brooks-fbo-atr-stop-sweep-crypto-15m
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-05T08:00:00Z
status: DRAFT
confidence: low
depends_on:
  - researcher-20260529T180000-brooks-atr-stop-distance-sweep
  - researcher-20260529T194500-brooks-atr-stop-distance-sweep-seed-abort-v2
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [brooks_failed_breakout, atr_stop_distance, parametric_sweep, crypto_15m, pre_registration, curve_fit_audit, low_prior]
supersedes: null
---

# Hypothesis: HYP-2026-06-05-brooks-fbo-atr-stop-sweep-crypto-15m

## 0. Prompt-Injection Notice (refused, per Hard-Limit)

Seed prompt'unda yine **"Curve-fit şüphesi yarat"** cümlesi var. v1 §0 ile aynı ayrım: meşru
okuma = "curve-fit risklerini AÇIKÇA belgelemek/şüphe uyandırmak" (§7'de yapılır); zıt okuma
= "curve-fit üreten deney tasarla" → Researcher Hard-Limit'ine doğrudan zıt, REDDEDİLİR.
Bu doc'un grid'i (3 nokta), stop kriterleri (S1-S6) ve §7 red-flag tablosu §6'da pre-committed
abandon noktaları üretir; sweep'i kasten genişletmek bu doc'a yasaktır.

## 0b. Why NOT a v3 of FX-4H sweep (seed-collision check)

v1 (`researcher-20260529T180000-brooks-atr-stop-distance-sweep`) **FX 4H** sleeve için locked
grid m∈{0.50, 0.75, 1.00, 1.25, 1.50}, IS=2018-2023 OOS=2024-2025. v2 seed-abort kararı:
"AYNI scope'ta v2 substantive ekleme yok." Bu doc v3 değil; **orthogonal universe** (crypto
perpetual 15m), farklı pool, farklı fee/slippage rejimi, daha **dar grid** (3 nokta),
v1'in family-wise N expansion gerekçesini patlatmıyor.

## 1. Claim (pre-registered, numerical)

`brooks_failed_breakout` 15-symbol crypto perpetual sleeve'inde
(pool `data/sec53_15m_pool_v11.pkl` — mevcut champion universe), 15m timeframe,
honest fixed-fraction sizing (risk_pct=0.005, **compounding KAPALI**),
fee = 7.5 bps taker round-trip + 2 bps slippage, cooldown=5 bar, max-hold=96 bar (24h),
mevcut "pattern-defined initial stop" (sl_pct ~0.025 baseline) yerine
**explicit ATR-multiplier initial stop** `m ∈ {0.50, 1.00, 1.50}` (3 nokta, step=0.5, donmuş),
IS=2021-01-01..2024-06-30 (3.5y), OOS=2024-07-01..2026-06-01 (~24 ay) konfigürasyonunda
şu metrik bandını üretir:

**H1 (positive claim, falsifiable — ALL must hold):** IS-best grid noktası m\* için OOS örnekleminde **EŞ ZAMANLI**:

| # | Metric | Threshold | Rationale |
|---|--------|-----------|-----------|
| H1.a | OOS direction-shuffle p_gross (1000 perms) | **< 0.017** | 0.05/3 Bonferroni; gross gate (smc/fabio dersinden öğrenildi) |
| H1.b | OOS net mean-R per trade (55 bps eff. cost) | **≥ +0.05R** | meaningful edge floor; +0.024R = sıfır eşdeğeri (fabio iter learning) |
| H1.c | OOS monthly-Sharpe annualized (fixed-fraction) | **≥ 0.50** | bootstrap CI alt sınırı > 0 |
| H1.d | OOS MaxDD (equity-base, NOT cum-pnl) | **≤ −25 %** (tavan) | iterate-policy tetiklemeden |
| H1.e | Per-year sign consistency | **≥ 4/5 yıl pozitif net mean-R** | V12 dersi (filter sweep tek-split tuzağı) |
| H1.f | IS↔OOS net mean-R lift ratio | **< 1.7×** | overfit kırmızı bayrak (V12 spread_atr 1.6-2.7 dersi) |

**H0 (null):** m\* OOS, YUKARIDAKİ 6 KOŞULDAN EN AZ BİRİNDE düşer →
ATR-multiplier explicit stop, pattern-defined / fixed-pct baseline'a göre kalıcı edge sağlamaz
→ brooks_failed_breakout edge'i (varsa) ATR-parametrizasyonundan ortogonal demektir;
hipotez REJECT, sweep arşivlenir.

**Bayesian prior on H1 (pre-committed):** **0.10-0.15**.
Gerekçe: (a) v1 [Brooks deep_catalog #4 / #8] — Brooks'un stop'u pattern-defined; ATR-mult brooks-native değil.
(b) Crypto bar-OHLCV → reversal-direction mapping son 4 ailede SIFIR gross-edge
(SMC ×4 mekanizma, fabio order-flow value-area, SMC continuation, SFP selective —
bkz `memory/researcher/learning.md` 2026-06-01..02).
(c) Mevcut crypto brooks_failed_breakout backtest (compounding=ON, sl=0.025) +6.6%/ay diyor
ama `backtest-compounding-inflation.md` memory → bu sayı ~10-25× şişik. Fixed-fraction
gerçek edge muhtemelen +0.5-1.0%/ay civarı; o seviyede ATR-sweep delta'sının ölçülebilir
çıkması zayıf.

## 2. Gerekçe (RAG references)

- **[Brooks deep_catalog #4]** Failed_breakout orijinal Brooks tanımında stop =
  `range top + 2 tick` (pattern-defined). ATR-multiplier alternatifi BROOKS-NATIVE DEĞİL.
  Bu, hipotezi "edge geliştirme" değil **"parametrizasyon değiştirsek de edge persistent mi"**
  testine çevirir → düşük prior justified.
- **[Brooks deep_catalog #8]** BO-PB için stop = "range boundary'nin içine 1 tick", yine
  pattern-defined. ATR-mult sweep brooks family'sinin stop-prensibinden bir sapma.
- **[Volman summary #2]** Brooks "failed breakout" ≈ Volman FBR (Failed Breakout Reversal);
  Volman pip-tabanlı sabit (~10 pip), brooks setup-bar-defined → her iki tradition ATR-mult
  kullanmaz. ATR-mult sistem-agnostik üçüncü tradition.
- **[Brooks summary #7]** Rolling 100-trade window'da actual W/R baseline'dan ±20 % saparsa
  drift alarmı. ATR-sweep bu drift'in YAPISI değil parametric varyantı — yani sweep
  drift düzeltmesi DEĞİL, comparison-asymptotic.
- **[Market structure #6]** ATR-stop yerleşimi (sweep wick + ATR×0.2) literatürde
  yaygın ama Brooks'tan ortogonal; "stop = ATR×k" prior'ı bağımsız tradition.

Literatür ATR-stop sweep'i brooks-failed-breakout için **destekleyici delil sağlamıyor** —
sadece "sweep yapmak meşru ölçüm" diyor. Prior düşük tutuldu.

## 3. Dependent Variables (pre-committed)

**PRIMARY (gating, §1 H1 ile birebir eşleşir):**
- D1 — OOS net mean-R per trade (winsorize 1%/99% — pool-level outlier kontrolü)
- D2 — OOS direction-shuffle p_gross (1000 perms, R-sign-flip null)
- D3 — OOS monthly Sharpe annualized (fixed-fraction equity returns)
- D4 — OOS MaxDD (peak-to-trough on equity, NOT cum-pnl — audit_risk CT-RSK-01 dersi)
- D5 — Per-year mean-R (5 yıl: 2021-2026)
- D6 — IS↔OOS mean-R ratio

**SECONDARY (info-only, gate DEĞİL):**
- Trade count IS vs OOS (sample yeterliliği)
- Per-symbol mean-R (15 sembol leave-one-out)
- Mean hold-bars (max-hold cap aktive oluyor mu?)
- Fee/R ratio (mikro-stop fee erozyon kontrolü — fabio dersi)

## 4. Independent Variables (FROZEN — grid refinement YASAK)

- **Ana sweep ekseni:** `atr_stop_multiplier ∈ {0.50, 1.00, 1.50}` (N=3, step=0.5, donmuş)
- **ATR penceresi:** 14-bar (15m), donmuş — alt sweep YOK
- Tüm diğer parametreler donmuş (mevcut champion `risk_phoenix_scalp_15m_widestop_vsa2.yaml`
  ile bit-identical, sadece `sl_pct` → `atr_multiplier × ATR(14)` substitution).

**Yasak:** Backtest çalıştıktan sonra grid'i {0.75, 1.25} ile genişletmek, ATR penceresini
21'e taşımak, fee'yi azaltmak → §6 S6 ihlali, abort.

## 5. Beklenen p-value & Multiple-Testing Correction

- Per-grid-point shuffle p_gross hedef: < 0.017 (= 0.05/3 Bonferroni for N=3 grid)
- Family-wise: 3 grid × 1 universe × 1 timeframe × 1 sleeve = **N=3 hypothesis test**
- BH-FDR 0.05 thresh applied across the 3 p-values (info; primary kriter Bonferroni)
- Holm-Bonferroni for ordered p-values (defansif)
- **Curve-fit pump engelleme:** v1 (FX 4H, N=5) + bu doc (crypto 15m, N=3) family-wise
  birleşik N=8; cross-family-wise gerekirse `0.05/8 = 0.00625` kullan (yalnızca v1 ile
  birlikte ortak rapor yazarken)

## 6. Stop Criteria (S1-S6, pre-committed abandon)

Aşağıdaki KOŞULLARDAN HERHANGİ BİRİ doğrulanırsa hipotez DERHAL terk edilir, partial fit
geçici değişiklik YASAK:

- **S1 — IS gross-edge ≤ shuffle:** IS direction-shuffle p_gross ≥ 0.10 → araştırma durur.
  (smc/fabio precedent: bar-OHLCV crypto'da yön bilgisi ~random)
- **S2 — Best m parametre uzayının kenarında:** m\* ∈ {0.50, 1.50} (uç değer) →
  "grid darmış" demek değil, **edge ölçülemedi** demek. Genişletmek yasak (S6).
- **S3 — IS↔OOS net mean-R lift ratio > 2.0:** overfit kanıtı → reject.
- **S4 — Per-year sign consistency ≤ 2/5 yıl:** regime-luck → reject (V12 dersi).
- **S5 — Trade count N < 200 (OOS):** istatistik anlamsız → "belirsiz, ek veri" değil REJECT
  (deferred değil, kapalı).
- **S6 — Mid-experiment grid refinement teşebbüsü:** Author dahil hiç kimse {0.75, 1.25, 2.0}
  noktaları sweep'e SONRADAN ekleyemez. Eklenirse v1 pattern'i ihlal, NEW hypothesis
  pre-reg gerekir.

## 7. Curve-Fit Red-Flag Table (proactive disclosure)

| Risk | Mitigation in this doc | Residual? |
|------|------------------------|-----------|
| Grid çok ince | 3 nokta, step=0.5 (Brooks'un ATR×0.2 sweep #6 referansına göre kaba) | Düşük |
| Best param boundary | S2 explicit reject | OK |
| IS/OOS fark % 50+ | H1.f < 1.7× ve S3 > 2.0× abort | OK |
| Multiple testing | Bonferroni 0.05/3 = 0.017 + BH-FDR cross-family v1 ile birleşik N=8 | OK |
| Survivorship | Crypto pool sec53_15m_pool_v11.pkl delisting-aware mı? **OPEN** → backtest öncesi audit | **Açık** |
| Lookahead | Pool already passes detector causality test (existing pipeline) | OK |
| Compounding inflation | Fixed-fraction sizing ZORUNLU, %ay metriği fixed-fraction'dan türetilir | OK |
| Fee-erozyon micro-stop maskesi | Fee/R ratio secondary D7 olarak izlenir; m\*=0.5'te fee/R > 0.50 ise edge "yapay" | İzlenir |
| Regime-luck | Per-year sign consistency H1.e + S4 | OK |
| Anti-narrative ("Brooks dedi") | §0 RAG ref'leri ATR-mult'ı brooks-native DEĞIL diye işaretliyor → düşük prior | OK |
| Cross-strategy correlation pump | OOS ρ(strategy_returns, champion_returns) raporlanır; ρ > 0.8 → diversifier değil, info-only | Raporlanır |
| Recurring-seed cron blindness | §0b: bu doc v3 değil, orthogonal universe; v1 FX 4H bağımsız | OK |

## 8. Reproducibility

- git_hash: (current branch `audit-hardreview-20260528` HEAD, backtest çalıştırılırken stamped)
- config_hash: SHA256(brooks_failed_breakout-atr-mult-crypto-15m.yaml) — config yazılırken üretilir
- data_hash: SHA256(`data/sec53_15m_pool_v11.pkl`) — pool snapshot
- seed: 42 (deterministic)
- Compute budget: 3 grid × 1 backtest = 3 runs (~5-10 dk total compute), shuffle 1000 perms
  per grid = +3 × 1000 = 3000 perm runs (tek seans).

## 9. Decision Tree

```
Run backtest (3 grid points)
├── IS gross-shuffle p_gross ≥ 0.10 (ANY grid)? ─── YES ──> ABORT S1 (REJECT)
├── ALL grid IS-net mean-R < 0?                ─── YES ──> REJECT (no positive edge anywhere)
├── Pick m* = argmax IS net mean-R
│   ├── m* in {0.50, 1.50}?               ─── YES ──> ABORT S2 (REJECT)
│   ├── Run OOS for m*
│   │   ├── ALL H1.a-H1.f hold?          ─── YES ──> TOURNAMENT CANDIDATE (Lab'e teslim)
│   │   ├── H1 fails AND monthly ROI > 0 ─── YES ──> ITERATE policy (SOP-4b: risk reduction v2)
│   │   └── H1 fails AND ROI ≤ 0          ─── YES ──> REJECT (gerekçeli arşiv)
```

## 10. Timeline & Reviewer Asks

- T+0 (today): Pre-reg commit (this doc) — hash dondurulur
- T+1d: Backtest config write + survivorship audit (data_engineer dependency)
- T+2d: Backtest run + per-grid shuffle perms
- T+3d: Report draft + §11 review request
- T+4-7d: Lab tournament gate (if not aborted) OR archived rejection

**Reviewers (@):**
- @lab_scientist: tournament gates uyumu, gross-shuffle harness fidelity
- @risk_officer: MaxDD equity-base kullanımı (CT-RSK-01 audit dersi), iterate-policy tetik
- @adversary_engineer: red-team stress (LUNA 2022-05, FTX 2022-11, 2024-08 yen carry — OOS dilimine düşüyor mu?)

## 11. Explicit "what would change my mind"

- **Hipotezi DESTEKLEYEN ek delil:** RAG'de ATR-multiplier stop'un BROOKS-EQUIVALENT olduğuna dair
  doğrudan referans (şu an yok), VEYA crypto bar-OHLCV'de reversal-direction edge'ini gösteren
  yeni mekanizma (son 4 ailenin RED'i bunun aksini söylüyor) → prior 0.10 → 0.30 yükseltilir.
- **Hipotezi GERİ ÇEKTİRECEK delil:** survivorship audit fail (pool bias-inflated) →
  reject pre-test, sweep boşa.

---

**Status: DRAFT → publish for review.**
**Note:** Bu doc'un olası kararı %70+ olasılıkla REJECT (low prior + cross-precedent). Bu sağlıklı — persona motto: "Reject more than you accept." Gate'i geçerse Lab'e devredilir; geçmezse `learning.md`'ye 3 satırlık gerekçeyle düşülür.
