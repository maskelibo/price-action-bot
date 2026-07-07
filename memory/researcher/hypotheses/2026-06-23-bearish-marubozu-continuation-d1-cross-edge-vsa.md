---
doc_id: researcher-20260623T060500Z-bear-maru-cont-d1-cross-edge-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-23T06:05:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [cross_edge, marubozu, continuation, vsa_correlation, single_bar, anti_narrative_check]
supersedes: null
hash: bb3eda1
---

# HYP-2026-06-23 — Bearish Marubozu Continuation (1D, USDT-perp) — Cross-Edge vs vsa_climax_test

## 0. Reproducibility Tags
- git_hash: `bb3eda1` (audit-hardreview-20260528, HEAD at pre-reg)
- config_hash: TBD (frozen at backtest commit)
- data_hash: ingest manifest 2026-06-22T23:59Z
- universe_builder: `data/universe.py::build_universe(date)` (survivorship-correct)

---

## 1. Pre-registered Iddia (single sentence, measurable)

> **Iddia:** USDT-perpetual evrenin (n=50 historical-active liquid sembol) 1D timeframe'inde, **1W EMA-50 altında** kapanan ve **Bulkowski-tanımlı bearish marubozu** (body ≥ range ×0.90, kapanış ≤ low + range×0.05, açılış ≥ high − range×0.05) oluşturan bar'ın **t+1 open'ında market short**, **t bar low + 1.5×ATR(14) stop**, **2R fixed TP** kuralıyla, 2022-01-01 → 2025-12-31 in-sample (4y) ve 2026-01-01 → 2026-06-22 out-of-sample (~6m) pencerelerinde, **fee 7.5bps taker + slip 5bps + %0.5 sembol-başı risk** parametrelerinde aşağıdaki HEPSİNİ tutturur:
>
> 1. OOS net annualized return ≥ **+12%** (mütevazı — single-bar pattern + 2R TP yapısı için realistic; champion'ın %1-2/ay edge'iyle uyumlu)
> 2. OOS Sharpe ≥ **0.6** (Chan eşik, single-asset Bollinger reversal baseline ≥ 0.8'in altında — DİKKAT: bu rezerv)
> 3. OOS MaxDD ≤ **18%** (vsa_climax_test'in ~%24 DD'sinin altında olmalı, aksi halde diversification value yok)
> 4. Profit factor (OOS) ≥ **1.30**
> 5. **Birincil cross-edge metrik:** vsa_climax_test ile **90-day rolling daily-return Spearman ρ**, ortalamada **|ρ| ≤ 0.30** AND tek bir 90-gün penceresinde |ρ| > 0.50 olmamalı.

**Bu beş koşulun TAMAMI sağlanmazsa hipotez REDDEDİLİR.** "5'ten 4'ü tuttu" kabul gerekçesi değildir.

---

## 2. Null Hipotezler (ne olursa iddiam çürür)

- **H0a (continuation rate):** Bulkowski'nin %64 bearish continuation rate'i kripto-1D'ye transfer olmaz; binomial test ile single-bar follow-through win-rate ≤ %55 ise (Holm-düzeltilmiş p < 0.05) → kalıp gerçek değil, kabuk.
- **H0b (cross-edge):** Rolling ρ(strategy, vsa_climax_test) ≥ 0.30 → diversification katkısı yok, marginal Sharpe ≈ 0.
- **H0c (regime dependency):** Pattern net return'ü bear-regime alt-örneklemde anlamlı pozitif, range-regime'de değil — yani edge "BTC dump günleri" alt-population'ından geliyor. Regime-out alt-örneklemde Sharpe negatife dönerse kalıp regime-conditional, bağımsız strateji değil.
- **H0d (single-trade dominance):** Toplam P&L'in %30+'sı tek bir sembol-bar olayından gelirse → tail-leakage kuşkusu, red.

---

## 3. Literatür Gerekçesi (RAG referansları, anti-narrative kontrol dahil)

- **[Bulkowski, Encyclopedia of Candlestick Charts]** (RAG #8): Bearish marubozu — body ≥ range×0.90, continuation rate %64, avg move %4.9, performance rank 22/103.
  - **Anti-narrative not:** Bulkowski örneklemi US equity 1980-2010, daily; kripto-perp 1D'ye **regime-mismatch riski** var. Bull-dominant 2017-2021 ve bear 2022 + sideways 2023-2025 farklı stat dağılımı verir. %64 → %55-60 regression olası.
- **[López de Prado, AFML — backtest overfitting]** (RAG #1): DSR ≥ 0.5 ve PBO < 0.5 zorunlu; IS Sharpe > 3×OOS Sharpe ise red; param sayısı / sample > 1/30 ise red.
  - Buradaki param sayısı: 4 (body_ratio_min, atr_window, sl_atr_mult, tp_r). Sample (trade) sayısı hedefi ≥ 200 — yani p/n ≤ 4/200 = 1/50 ≤ 1/30 ✓.
- **[Chan, Algorithmic Trading]** (RAG #9): Single-asset stratejide OOS Sharpe ≥ 0.8 eşik; 0.6 hedefimiz bu eşiğin altında, o yüzden cross-edge metrik (ρ) **primary gate** olmak zorunda — strateji solo değer için değil portföy çeşitlendirme için aday.
- **[Kaufman — channel breakout failure modes]** (RAG #7): Choppy/range rejimde geri geri whipsaw; bizim trend filter (1W EMA-50) bu modu kısmen filtreler — ama tamamen değil.

**Curve-fit alarmı (anti-narrative):** Single-bar pattern + Bulkowski'nin lehte rakamı + tek timeframe = "hikâye çekici" sınıfı. Bu nedenle bu hipotez **gate-strict** uygulanır; "yakındı, az kaldı" → red.

---

## 4. Bağımlı Değişkenler (dependent / outcome — pre-registered, başka eklenmez)

| Var | Tanım | Hedef (gate) |
|---|---|---|
| `net_annual_return_oos` | (1+r)^(365/n_days)-1, fee+slip dahil | ≥ +12% |
| `sharpe_oos` | mean(daily_pnl)/std × √365 | ≥ 0.6 |
| `maxdd_oos` | equity peak-to-trough / equity_peak | ≤ 18% |
| `profit_factor_oos` | Σ wins / |Σ losses| | ≥ 1.30 |
| `corr_to_vsa_climax_90d_mean` | rolling 90d Spearman ρ, ortalaması | \|ρ\| ≤ 0.30 |
| `corr_to_vsa_climax_90d_max` | aynı, max | ≤ 0.50 |
| `continuation_winrate_raw` | t+1→t+5 follow-through binomial | > 0.55 (H0a) |
| `oos_in_sample_sharpe_ratio` | IS_sharpe / OOS_sharpe | ≤ 3.0 (López-Prado) |
| `single_symbol_pnl_share_max` | max(symbol_pnl/total_pnl) | ≤ 0.30 |

**Hiçbir bağımlı değişken backtest sonrası eklenmez veya yeniden tanımlanmaz.** Bu kural ihlal edilirse hipotez reddedilmiş sayılır (analyst audit notunda kayıtlı).

---

## 5. Bağımsız Değişkenler (independent — parametre uzayı, DAR tutuldu)

| Param | Aralık | Adım | Kombinasyon |
|---|---|---|---|
| `body_to_range_min` | {0.85, 0.90, 0.95} | discrete | 3 |
| `atr_window` | {14, 20} | discrete | 2 |
| `sl_atr_mult` | {1.5, 2.0, 2.5} | discrete | 3 |
| `tp_r_multiple` | {1.5, 2.0, 2.5} | discrete | 3 |

Toplam: **54 kombinasyon** (3×2×3×3). Optuna trial cap = 54 (full-grid, TPE search **kullanılmaz** — multiple-testing inflation'ı tetiklemez; tam aralık deterministic).

**Curve-fit gardian kuralları (pre-registered):**
- `body_to_range_min` ucunda (0.85 veya 0.95) best param çıkarsa → daha geniş aralık değil, RED (Bulkowski tanımı sabit %90, sapma anti-prior).
- `sl_atr_mult` ucunda → red.
- En iyi 5 parametre setinin ortalama Sharpe spread'i > %40 ise → high variance, red.
- Holm-Bonferroni düzeltmesi: α = 0.05 / 54 ≈ 0.000926 (en iyi kombo bu eşiği aşmalı).

---

## 6. Backtest Setup (frozen — değişirse hash değişir)

- **Universe builder:** `data/universe.py::build_universe(date)` — her bar için o tarihte aktif olan semboller, delisting'e kadar dahil (LUNA 2022-05, FTT 2022-11, vs.). Survivorship kontrolü: `tests/test_universe.py::test_includes_delisted_symbols` PASS olmalı.
- **Liquidity filter:** 30-day avg notional volume ≥ $50M (lab champion ile aynı eşik).
- **Timeframe:** 1D primary, 1W EMA-50 trend filter.
- **Fee:** 7.5 bps taker, slip 5 bps (konservatif; champion-paper ile aynı).
- **Risk:** 0.5% / trade (rsi2-extreme-fade rescue dersinden — düşük risk_pct + cross-edge mantığı).
- **Sembol başına max concurrent:** 1 (pattern overlap olmayacak).
- **Entry:** t+1 bar open (t bar close'da karar — lookahead-safe).
- **Tests:** `tests/test_lookahead.py::test_marubozu_detector_causality` zorunlu PASS, aksi halde backtest çalıştırılmaz.

---

## 7. Robustness Suite (SOP-3, hiçbir adım atlanmaz)

1. Walk-forward 3y/6m, step 3m → 12 dilim, ≥ 8 pozitif olmalı.
2. IS/OOS Sharpe gap ≤ %30.
3. Random param perturbation ±%10 × 50 seed → ortalama Sharpe kaybı ≤ %25.
4. Symbol-out CV (leave-one-out, 50 sembol) → min Sharpe ≥ 0.3.
5. Regime split (bull / bear / range — HMM 3-state) → en az 2 rejimde pozitif Sharpe; H0c için range-only Sharpe kontrolü.
6. Stress periodları: 2022-05 (LUNA), 2022-11 (FTX), 2023-03 (USDC), 2024-03 (BTC ATH), 2024-08 (Yen carry) → her birinde DD ≤ %10.
7. Shuffle baseline: returns 1000× shuffle → p < 0.001.
8. **Cross-edge primary:** vsa_climax_test live + paper hybrid serisine karşı rolling ρ; OOS pencerede max |ρ| ölçülür.

---

## 8. Beklenen p-value ve Multiple Testing Düzeltmesi

- Naive expected (Bulkowski stat'inin kripto'ya direkt uyacağı assumption): binomial p ≈ 0.01 — ama bu **çürütülmesi muhtemel** prior.
- Realistic prior (anti-narrative): p ≈ 0.10-0.20 (no edge after fees).
- **Karar eşiği:** Holm-Bonferroni-düzeltilmiş p < 0.000926 (54 trial üstü) **VE** DSR ≥ 0.5 **VE** PBO < 0.5.
- Her ikisi de geçmezse → REJECT, "edge bulunamadı" notu.

---

## 9. Stop Criteria (erken sonlandırma — kaynak israfı önler)

- IS Sharpe < 0.4 (preliminary 3-month sub-sample) → terk et, robustness'a girme.
- Continuation win-rate raw < %50 (H0a kaba kontrol) → red, RAG cont-rate iddiası kripto'da yok.
- Tüm 54 kombinasyondan hiçbiri Holm-düzeltilmiş p < 0.000926 üretmiyorsa → red.
- ρ(strategy, vsa_climax_test) > 0.30 ortalama → cross-edge gerekçesi düştü, solo strateji olarak Chan eşiği 0.8'i geçmediği için zaten anlamsız.
- 3 iterate v2-v4 sonrası hala gate'i geçmiyorsa (SOP-4b budget) → "edge yoksa pozitif edge rescue çağrısı geçersiz" → arşiv (red, deferred değil).

---

## 10. SOP-4 Karar Yolları (3-way)

- **Terfi:** Tüm gate ✓ + tüm robustness ✓ + |ρ| ≤ 0.30 → Lab tournament queue.
- **Iterate (SOP-4b):** ROI pozitif ama DD > %18 veya |ρ| 0.30-0.45 arası → v2 (risk_pct 0.5 → 0.3), v3 (trend filter daha sıkı: 1W EMA-200 altı), v4 (sembol subset = düşük korelasyon sembol kümesi). Max 4 iterate.
- **Red:** ROI ≤ 0 veya continuation winrate H0a düşmedi veya |ρ| > 0.45.

---

## 11. Curve-Fit / Bias Şüphe Listesi (pre-registered, audit trail)

Backtest sonrası BU LİSTE adım adım kontrol edilir; herhangi biri TRUE ise terfi reddedilir:

- [ ] Best param uç noktada (body_to_range_min ∈ {0.85, 0.95} veya sl_atr_mult ∈ {1.5, 2.5}).
- [ ] IS/OOS Sharpe ratio > 3 (López-Prado kırmızı bayrak).
- [ ] Trade count < 100 (single-bar pattern + 1D + 50 sembol × 4y = beklenen ~500-1500; 100'ün altı = liquidity filter çok agresif veya pattern çok nadir → red).
- [ ] Tek sembol P&L payı > %30.
- [ ] Tek yıl (2022 / 2023 / 2024 / 2025) P&L payı > %50.
- [ ] Holm-Bonferroni sonrası anlamlı kombo sayısı 0.
- [ ] OOS regime split: bull-rejim Sharpe negatif, bear-rejim pozitif → strateji "BTC dump günleri" detector'ından ibaret (vsa_climax_test ile bu durumda korelasyon yüksek olur, cross-edge çürür).

---

## 12. Beklenen Çıktı (rapor şablonu, Lab'e teslim)

`reports/research/bear-maru-cont-d1-cross-edge-2026-06-23.html` — SOP-1 §7 standart tablosu + bu doc'a back-link + cross-edge ρ time-series grafiği.

---

## 13. Pre-Reg Commit Sözü

> Bu hipotezi commit edene kadar BACKTEST KODU YAZILMAYACAK. Backtest sonrası hiçbir bağımlı değişken eklenmeyecek, hiçbir parametre aralığı genişletilmeyecek. İhlal = `learning.md`'ye "pre-reg violation" + hipotez otomatik REJECTED.

**Pre-reg author:** researcher (LLM agent, persona @claude-opus-4-7)
**Review requested from:** lab_scientist (gate enforcement), risk_officer (sizing + DD bandı)
**SLA:** 24h critique/endorse (Risk 6h)
