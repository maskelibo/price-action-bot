---
doc_id: researcher-20260613T080000-kaufman-rsi-div-engulf-15m-htf-ema-low-corr
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-13T08:00:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, pre_registration, kaufman, rsi_divergence, engulfing, 15m, htf_filter, diversifier, low_corr_to_vsa, curve_fit_hardened]
supersedes: null
hash: null
---

# HYP-2026-06-13 — Kaufman RSI Divergence + Engulfing Confirmation @ 15m with 1h EMA50 Trend-Filter (low-corr diversifier)

> **Pre-registration** — kod yazılmadan önce iddia, ölçüm değişkenleri, p-value hedefi ve stop-criterion donduruldu. Curve-fit yüzeyini agresif şekilde daraltıyorum: tek serbestlik confirmation tipi `{engulfing, hammer}` (Bonferroni n=2). RSI periyodu (14), divergence lookback (10 bar), HTF EMA periyodu (50) ve TF (1h), SL/TP yapısı (divergence low/high + 2R fixed) LITERATÜRDEN DONDURULMUŞ — Optuna tetiklenmez. Bu seçim bilinçli: 15m USDT-perp tarafında halihazırda RSI-div araştırması yapılmamış (sadece 1D/4H/forex-4H mevcut), ve mevcut canlı arsenal (VSA + WIDESTOP 15m) ile düşük korelasyon hedefi var. Edge buradaysa **parametre kıvırma değil yapısal-rejim** sebebiyle olmalı; aksi takdirde reddedilir.

## 1. İddia (measurable, falsifiable)

**Universe:** 19-sym USDT-perp pool (`scripts/research/build_pool_19sym.py` v11 listesi). Survivorship: 3 yıl içinde delisting olan semboller delisting tarihine kadar dahil; yeni listing'ler listing tarihinden itibaren.

**Pencere:** 2023-01-01 → 2026-04-30 (16 ay OOS rezerv: 2026-05-01 → 2026-06-13 — backtest sırasında DOKUNULMAZ).

**Timeframe & Filter:**
- Primary TF: **15m**
- Trend filter: **1h EMA50** — long-only iff `close_1h > EMA50_1h`; short-only iff `close_1h < EMA50_1h`. 1h bar son kapanışından sonra; lookahead-safe.

**Sinyal (long, short simetrik):**
- **RSI(14) bullish divergence:** prior 10×15m-bar penceresinde `price` lower-low ve `RSI` higher-low (en az 5 bar ara, swing-low ZigZag k=2 ile).
- **Confirmation candle:** t bar ya `bullish engulfing` (önceki body'i tamamen kapsayan close>open) ya da `hammer` (lower-wick ≥ 2×body, upper-wick ≤ 0.5×body). t bar'ın low'u t-1 bar'ın low'undan AŞAĞIDA olmalı.
- **Entry:** t+1 bar OPEN (lookahead-safe; t kapanışta karar).
- **SL:** divergence ikinci low'unun 0.25×ATR(14) altı.
- **TP:** 2R fixed (sabit, optimize edilmiyor).
- **Time-stop:** 48×15m = 12 saat. Süre dolarsa flat-close at-market.

**Risk:** `risk_pct = 0.5%` (champion'un yarısı, diversifier konservatifizm), `max_concurrent = 6`, `fee = 7.5bps taker + 5bps slip`.

**İddialar (eşik):**

| Metric | Hedef (IS) | Hedef (OOS) | Hard Gate |
|---|---|---|---|
| Aylık net return (sabit-fraksiyon, fresh-$10k her ay) | ≥ +4.0% | ≥ +3.0% | OOS ≥ +2.5% |
| Sharpe (annualized, OOS) | ≥ 1.5 | ≥ 1.0 | OOS ≥ 0.8 |
| MaxDD (OOS) | ≤ −20% | ≤ −25% | ≤ −30% |
| Profit factor (OOS) | ≥ 1.4 | ≥ 1.3 | ≥ 1.2 |
| Trade sayısı (OOS) | ≥ 80 | ≥ 200 (IS+OOS) | N ≥ 150 (istatistik güç) |
| Win rate | bilgi amaçlı | bilgi amaçlı | — |
| **Kaufman ref WR ~%40-50, R ~2-3** doğrulanmalı | — | — | WR ≥ 38%, avg-R ≥ 1.8 |
| **DSR (López)** | ≥ 0.95 | — | < 0.5 ⇒ otomatik RED |
| **Correlation vs canlı VSA-15m daily-PnL serisi (overlap dönem)** | ρ ≤ 0.30 | — | ρ > 0.50 ⇒ diversifier değil, RED |

**Sentezlenen iddia tek cümle:**
> "15m USDT-perp evreninde, 1h-EMA50 trend rejimi ile filtrelenmiş, Kaufman RSI(14) divergence + engulfing/hammer confirmation kuralı, son 3 yıl içinde aylık net ≥ +3% OOS, Sharpe ≥ 1.0 OOS, MaxDD ≤ −25%, DSR ≥ 0.95, ve canlı VSA-15m ile ρ ≤ 0.30 üretir."

## 2. Null hypothesis (red kriteri)

- **H0:** OOS aylık net ≤ +2.5% **VEYA** Sharpe OOS < 0.8 **VEYA** MaxDD < −30% **VEYA** DSR < 0.5 **VEYA** ρ(VSA-15m) > 0.5
- H0 ANY-OF reddedilemezse → hipotez reddedilir, `learning.md`'ye sebep yazılır.
- Ayrıca shuffle-baseline p ≥ 0.05 ⇒ otomatik RED.

## 3. Gerekçe — RAG referansları

- **[Kaufman summary §RSI-divergence] (#6 score 0.650):**
  > "Bullish divergence (price lower-low, RSI higher-low) → confirmation candle (engulfing, hammer) sonrası long. Stop: Divergence low'unun altı. Hedef: 2-3R fixed. Failure: Strong trend'de divergence saatlerce/günlerce devam eder."
  Bu bizim **structural birincil referansımız** — kuralı kelimesi kelimesine taşıyoruz, parametre değiştirmiyoruz. "Strong trend failure" mode'u **1h-EMA50 filtre** ile adresleniyor: yalnız EMA50'nin DOĞRU TARAFINDAN gelen divergence-fade alıyoruz (trend yönünde reversal yakalama). Filtre olmadan referansın kendi failure mode'u gerçekleşir.

- **[Grimes summary §Anti-setup] (#3 score 0.657):**
  > "Win rate düşük (%40-45), ama R büyük (2-3R)... expected value hafifçe pozitif."
  Bizim WR hedefimiz (≥ 38%) ve R hedefimiz (≥ 1.8) bu beklentiyle uyumlu — düşük WR + yüksek R profili. Eğer backtest %60+ WR raporlarsa **kırmızı bayrak**: literatürle uyumsuz → over-fit/lookahead şüphesi → ekstra audit.

- **[López summary §DSR thresholds] (#9 score 0.633):**
  > "DSR > 0.95 güçlü istatistiksel kanıt. DSR < 0.5 rastlantı."
  Promotion gate'i olarak DSR ≥ 0.95 zorunlu. Bonferroni n=2 (engulfing & hammer) sonrası DSR hesabı yapılır.

- **[Grimes summary §risk-of-ruin] (#4 score 0.656):**
  > "Over-leverage / oversize iyi sistemleri kötü performans gösterir hale getiren 1 numaralı sebep."
  Bu nedenle `risk_pct = 0.5%` (champion'un yarısı) — diversifier olarak konservatifizm.

## 4. Dependent variables (ölçülecek)

1. `net_monthly_return_pct` (fresh-$10k her ay, sabit-fraksiyon, fee+slip dahil)
2. `sharpe_annualized` (IS, OOS)
3. `max_dd_pct` (account-equity based, NOT cumulative-PnL — bkz. MaxDD-base lesson)
4. `profit_factor`
5. `win_rate`
6. `avg_R` (R-multiples ortalaması)
7. `trade_count` (IS, OOS)
8. `DSR` (López formula)
9. `corr_with_vsa15m` (overlap pencere daily-PnL Pearson)
10. `shuffle_baseline_p` (Returns shuffle null model)
11. `regime_split_returns` (bull/bear/range — son 3y rejim sınıflandırması ile)

## 5. Independent variables (kontrol/sweep)

**FROZEN (sweep YOK):**
- RSI period = 14 (Kaufman default)
- Divergence lookback = 10 bar (Kaufman örnek)
- HTF = 1h, EMA period = 50
- ATR period = 14, SL offset multiplier = 0.25
- TP = 2R fixed
- Time-stop = 48 bar
- risk_pct = 0.5%
- ZigZag swing detection k = 2

**SWEEP (tek serbestlik):**
- `confirmation_type ∈ {engulfing, hammer}` (n=2)
- Bonferroni: α_eff = 0.05 / 2 = 0.025

**Multiple-testing correction:** Bonferroni n=2 (engulfing, hammer); en iyi confirmation tipi raporlanır, p-value 0.025 eşiği ile kıyaslanır. Eğer hem engulfing hem hammer ayrı ayrı geçerse `confirmation_type = any_of` ek run, ayrı n=3 düzeltmesi.

**EXPLICIT NO-GO:** Optuna trial > 10 ⇒ otomatik RED (curve-fit guard).

## 6. Expected p-value & istatistiksel güç

- Pre-Bonferroni: shuffle-baseline p < 0.01 (her iki confirmation tipi için)
- Post-Bonferroni (n=2): p < 0.025 eşiği
- DSR ≥ 0.95 (López trial-count düzeltmesi sonrası)
- Trade-count gücü: en az N=150 trade (IS+OOS); altında istatistik anlamsız → soft-RED.

## 7. Stop criteria (araştırma terkedilir)

1. **IS Sharpe < 0.5** → 1 saat içinde durdur, OOS çalıştırma.
2. **IS-OOS Sharpe gap > %50** → overfit kırmızı bayrağı; hipotez reddedilir.
3. **Best confirmation tipi tek bir rejim dilimine bağımlı** (örn. P&L'in >%70'i 2022Q4'ten) → red.
4. **MaxDD account-equity base'de < −35%** → diversifier olamaz, red.
5. **Walk-forward 12 dilimden ≥ 7'si negatif** → red.
6. **Correlation vs canlı VSA-15m ρ > 0.5** → diversifier amacı düştü, red.
7. **DSR < 0.5** → otomatik red (López).
8. **Lookahead-delay testi:** entry +1 bar geciktirdiğimde edge > %50 düşerse → "sızıntı/timing-luck" şüphesi, full audit.

## 8. Curve-fit guard checklist (çalışmadan ÖNCE doğrula)

| Risk | Önlem | Kontrol |
|---|---|---|
| Parametre uzayı ince → over-fit | Tüm sayısal params FROZEN; tek discrete sweep | ✓ pre-reg |
| Best params sınırda | Sınır yok (discrete 2-değer) | ✓ N/A |
| Trade sayısı düşük | N ≥ 150 hard-gate | ✓ |
| Tek periyot baskın | Regime-split kontrolü | ✓ |
| Walk-forward varyansı | 12 dilim, %50+ pozitif zorunlu | ✓ |
| Multiple-testing | Bonferroni n=2 (veya 3) | ✓ |
| Hikâye bias'ı | "Mantıklı" gerekçe puana etmez; sayı ister | ✓ |
| Lookahead | Causality test + bar-timing audit | ✓ |
| Survivorship | Delisting'ler dahil universe | ✓ |
| Backtest compounding inflation | fresh-$10k her ay, sabit-fraksiyon | ✓ (lesson) |
| MaxDD inflation | account-equity base, NOT cum-PnL | ✓ (CT-RSK-01 lesson) |

## 9. Pre-defined "what would make me retreat the candidate"

- WR > 65% (Kaufman/Grimes literatürü ile uyumsuz — anomali, lookahead şüphesi)
- avg-R > 4 (TP=2R fixed olduğu için strüktürel olarak imkânsız; eğer çıkarsa hesap-hatası)
- Sharpe IS > 3.5 (15m kripto 19-sym universe için non-realistic)
- Aylık net > %15 (champion mertebesinde — şişme/curve-fit alarmı)

## 10. Reproducibility

- git_hash: (commit anında doldurulacak)
- config_hash: (yaml hash)
- data_hash: (DuckDB pool snapshot)
- seed: 42 (shuffle baseline için)

## 11. Pipeline

1. `scripts/research/build_pool_19sym.py` v11 universe doğrulama (delisting check).
2. `backtest/engine.py` 15m bar, fee+slip param frozen.
3. Lookahead causality test (CI: `tests/test_lookahead.py`).
4. Walk-forward (`backtest/walk_forward.py`): 36 ay train, 6 ay test, step 3 ay (12 dilim).
5. Robustness suite (SOP-3): symbol-out CV, regime split, stress (LUNA/FTX/USDC/Yen), shuffle baseline, +1 bar lookahead-delay sanity.
6. DSR hesabı (López formula, n=2 trial düzeltmeli).
7. Correlation vs canlı VSA-15m daily-PnL serisi (Pearson, overlap pencere).
8. Karar yaz: terfi adayı / iterate / red.

## 12. Karar şablonu

- [ ] Terfi adayı (Lab tournament'a gönder)
- [ ] Iterate (SOP-4b — pozitif edge + kötü risk; v2 yaz)
- [ ] Red — gerekçe: ______

---

**Pre-registration timestamp:** 2026-06-13T08:00:00Z (Europe/Istanbul: 2026-06-13 11:00).
**Commit hash:** (yazılırken donar)
**Reviewer SLA:** lab_scientist 24h, risk_officer 6h (PROTOCOL §4).
