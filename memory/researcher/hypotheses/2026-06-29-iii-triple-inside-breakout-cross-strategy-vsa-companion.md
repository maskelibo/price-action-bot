---
doc_id: researcher-20260629T063000Z-iii-triple-inside-breakout-cross-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-29T06:30:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [cross_edge, inside_bar, iii_breakout, volman, price_only, vsa_correlation, anti_narrative_check]
supersedes: null
hash: 80e1cdc
---

# HYP-2026-06-29 — iii (Triple Inside Bar) Breakout (1D, USDT-perp) — Cross-Edge vs vsa_climax_test

## 0. Reproducibility Tags
- git_hash: `80e1cdc` (audit-hardreview-20260528, HEAD at pre-reg)
- config_hash: TBD (frozen at backtest commit)
- data_hash: ingest manifest 2026-06-28T23:59Z
- universe_builder: `data/universe.py::build_universe(date)` (survivorship-correct, delisting'ler dahil)

---

## 1. Pre-registered Iddia (single sentence, measurable)

> **Iddia:** USDT-perpetual evrenin (n ≈ 50 historical-active liquid sembol) 1D timeframe'inde, **ardışık 3+ inside bar** (bar_k.high < bar_{k-1}.high AND bar_k.low > bar_{k-1}.low for k ∈ {t-2, t-1, t}; "iii" block) oluştuktan sonra, **t+1 bar'ında iii-bloğunun yüksek/alçağını 0.10×ATR(14) tampon ile kıran** taraf yönünde **t+1 bar kapanış**ta market entry, **iii-bloğunun karşı ekstremi − 0.5×ATR(14) stop**, **1.8R fixed TP**; **1W EMA-50 trend filter** (long sadece price>EMA50, short sadece price<EMA50); 2022-01-01 → 2025-12-31 in-sample (4y) + 2026-01-01 → 2026-06-28 out-of-sample (~6m), fee 7.5bps taker + slip 5bps + %0.5 sembol-başı risk parametrelerinde aşağıdaki BEŞ koşulun **TAMAMI**:
>
> 1. OOS net annualized return ≥ **+10%** (mütevazı — multi-bar consolidation pattern + 1.8R TP; champion +%1-2/ay edge ile uyumlu)
> 2. OOS Sharpe ≥ **0.6** (Chan single-asset 0.8 eşiğinin altında — DİKKAT: bu, cross-edge gerekçesini ZORUNLU kılar)
> 3. OOS MaxDD ≤ **18%** (account-equity bazında, CT-RSK-01 zero-base hatası YAPILMAZ)
> 4. Profit factor (OOS) ≥ **1.30**
> 5. **Birincil cross-edge metrik:** vsa_climax_test (canlı + paper hybrid daily-return serisi) ile **90-day rolling daily-return Spearman ρ**, ortalamada **|ρ| ≤ 0.25** AND tek bir 90-gün penceresinde |ρ| > 0.45 olmamalı.

**Beş koşuldan biri kırmızıysa REDDEDİLİR.** "4'ü tuttu, marjinal" → red; mantra "reject more than you accept".

---

## 2. Null Hipotezler (ne olursa iddiam çürür)

- **H0a (iii breakout edge yok):** Bulkowski'nin tekli inside bar %54 win-rate'i çoklu-iç (iii) tabakasında transfer olmaz; binomial test ile breakout follow-through win-rate ≤ %52 (Holm-düzeltilmiş p < 0.05) → kalıp şans, red.
- **H0b (cross-edge yok):** Rolling ρ(strategy, vsa_climax_test) ortalama ≥ 0.25 → diversification katkısı sıfır; solo değer Chan 0.8 eşiğini geçmediği için zaten anlamsız → red.
- **H0c (trend filter cheating):** 1W EMA-50 filter olmadan Sharpe negatife dönerse, strateji aslında "EMA-50 trend follower" oluyor, "iii breakout" ek bilgi katmıyor. Filter-off Sharpe / filter-on Sharpe > 0.7 olmazsa H0c reddedilir → kalıp gerçek değil, filter trivial edge.
- **H0d (single-trade dominance):** Toplam P&L'in %25+'sı tek sembol-bar'dan gelirse → tail-leakage, red.
- **H0e (regime parazit):** Pattern net return'ü sadece bull rejimde pozitif, bear ve range'de ≤ 0 ise → "yükselen piyasada her şey çalışır" sınıfı; bağımsız edge değil.

---

## 3. Literatür Gerekçesi (RAG referansları, anti-narrative check dahil)

- **[Bulkowski, Encyclopedia of Candlestick Charts]** (RAG #2): Tekli inside bar breakout win-rate **%54** (zayıf), performance rank 78/103. Volman eklemi: "ii" (double inside) ve "iii" (triple inside) breakout **daha güçlü**; Volman DD setup'ı buradan türer.
  - **Anti-narrative not:** Volman %s vermez, sadece kalitatif "daha güçlü" der. **Bu hipotezde "daha güçlü" → en az %58 follow-through win-rate** olarak operasyonalize edildi (H0a eşiği). Eğer iii %54-58 arası kalırsa "Volman haklıydı ama edge marjinal" denir, gate-strict altında red.
- **[López de Prado, AFML]** (RAG #1): DSR ≥ 0.5, PBO < 0.5, IS Sharpe ≤ 3×OOS Sharpe, param/sample ≤ 1/30. Burada param sayısı = 4 (inside_count, breakout_buffer_atr, sl_atr_mult, tp_r); hedef trade ≥ 200 → p/n = 4/200 = 1/50 ≤ 1/30 ✓.
- **[Brooks, ch.7 multi-bar consolidation]** (RAG #3 başlığı altı — "n-bar high/low aşımı + reversal mekanik, test edilebilirlik 5/5"): konsolidasyon-sonrası kırılım Brooks'un da onayladığı sınıf; ancak Brooks "ATR-eşik buffer" şart koşar (gürültü filtreleme), pre-reg'de 0.10×ATR olarak sabitlendi.
- **[Chan, Algorithmic Trading]** (RAG #9): Single-asset OOS Sharpe ≥ 0.8 gate; bu hipotez 0.6 hedefliyor → solo değil **portföy companion** olarak değerlendirilir. Eğer ρ gate'i geçmezse Chan eşiği sebebiyle zaten anlamsız.
- **[Kaufman channel breakout failure]** (RAG #7): Range rejimde whipsaw; 1W EMA-50 filter bu modu kısmen kapatır ama tamamen değil — bu yüzden regime split (H0e) zorunlu.

**Curve-fit alarmı (anti-narrative):** Multi-bar pattern + Volman kalitatif onayı + cross-edge gerekçesi = "hikâye temiz" sınıfı. Bu nedenle gate-strict; "yakındı" → red. **Volman'ın kalitatif iddiası sayısal hedefe operasyonalize edildi (H0a %58 eşik)** — narrative'ı dondurdum.

---

## 4. Bağımlı Değişkenler (dependent / outcome — pre-registered, başka eklenmez)

| Var | Tanım | Hedef (gate) |
|---|---|---|
| `net_annual_return_oos` | (1+r)^(365/n_days)-1, fee+slip dahil | ≥ +10% |
| `sharpe_oos` | mean(daily_pnl)/std × √365 (daily, ann. doğru) | ≥ 0.6 |
| `maxdd_oos` | account_equity peak-to-trough / equity_peak (CT-RSK-01 doğru baz) | ≤ 18% |
| `profit_factor_oos` | Σ wins / \|Σ losses\| | ≥ 1.30 |
| `corr_to_vsa_climax_90d_mean` | rolling 90d Spearman ρ ortalaması | \|ρ\| ≤ 0.25 |
| `corr_to_vsa_climax_90d_max` | aynı, max | ≤ 0.45 |
| `breakout_followthrough_winrate` | t+1→t+5 follow-through binomial | > 0.58 (H0a) |
| `is_oos_sharpe_ratio` | IS_sharpe / OOS_sharpe | ≤ 3.0 (López-Prado) |
| `single_symbol_pnl_share_max` | max(symbol_pnl/total_pnl) | ≤ 0.25 |
| `filter_off_to_filter_on_sharpe` | sharpe(no_ema) / sharpe(with_ema) | ≤ 0.70 (H0c) |
| `regime_positive_count` | bull/bear/range içinde pozitif Sharpe sayısı | ≥ 2/3 (H0e) |

**Hiçbir bağımlı değişken backtest sonrası eklenmez veya yeniden tanımlanmaz.** Pre-reg violation = otomatik REJECTED + `learning.md` not.

---

## 5. Bağımsız Değişkenler (independent — parametre uzayı, DAR tutuldu)

| Param | Aralık | Adım | Kombinasyon |
|---|---|---|---|
| `inside_count_min` | {2, 3, 4} | discrete (Volman ii/iii/iiii) | 3 |
| `breakout_buffer_atr` | {0.05, 0.10, 0.20} | discrete | 3 |
| `sl_atr_mult` | {0.5, 1.0, 1.5} | discrete (iii-block karşı ekstremine ek tampon) | 3 |
| `tp_r_multiple` | {1.5, 1.8, 2.5} | discrete | 3 |

Toplam: **81 kombinasyon** (3×3×3×3). **Full-grid deterministic** (TPE/Optuna search KULLANILMAZ — search-space inflation tetiklemez).

**Curve-fit gardian kuralları (pre-registered, sonradan değişmez):**
- `inside_count_min` ucunda best (== 2 veya == 4) → red. Volman teorisi "üç" merkezli; uç = anti-prior.
- `breakout_buffer_atr` ucunda (== 0.05 veya == 0.20) → red.
- `sl_atr_mult` ucunda → red.
- En iyi 10 parametre setinin Sharpe spread'i (max-min)/mean > %50 ise → high variance, red.
- Holm-Bonferroni: α = 0.05 / 81 ≈ 0.000617 (en iyi kombo bu eşiği aşmalı).
- DSR ≥ 0.5 AND PBO < 0.5 zorunlu (López-Prado).

---

## 6. Backtest Setup (frozen — değişirse hash değişir)

- **Universe builder:** `data/universe.py::build_universe(date)` — survivorship-correct (LUNA, FTT, vs. delisting tarihine kadar dahil). Test `tests/test_universe.py::test_includes_delisted_symbols` PASS.
- **Liquidity filter:** 30-day avg notional volume ≥ $50M.
- **Timeframe:** 1D primary, 1W EMA-50 trend filter.
- **Fee/Slip:** 7.5 bps taker, 5 bps slip (konservatif).
- **Risk:** 0.5% / trade (rsi2-extreme-fade rescue dersi — düşük risk_pct + cross-edge mantığı).
- **Sembol başına max concurrent:** 1.
- **Entry:** t+1 bar **kapanışı** (intraday breakout teyit edilmiş, lookahead-safe).
- **Tests:** `tests/test_lookahead.py::test_iii_detector_causality` PASS zorunlu — yoksa backtest çalıştırılmaz.
- **Sharpe annualization:** daily√252 (CT-RES-01 — 17.3 hatası tekrar etmez; 1D bar → √252 NOT √365_bars; 365=takvim, 252=bar-count uygun değişen koşula).
  - **NOT (bilinçli seçim):** Kripto 7/24 işliyor → bar sayısı yıllık ≈ 365; ama Sharpe annualization rate-of-return × √(bars/year). Burada bar = günlük takvim günü → √365. Bu çelişki CT-RES-01 ile karıştırılmamalı: oradaki hata `√252×60` gibi bileşik şişme idi; burada √365 kripto-1D için doğru.

---

## 7. Robustness Suite (SOP-3, hiçbir adım atlanmaz)

1. Walk-forward 3y/6m, step 3m → 12 dilim, ≥ 8 pozitif olmalı.
2. IS/OOS Sharpe gap ≤ %30.
3. Random param perturbation ±%10 × 50 seed → ort. Sharpe kaybı ≤ %25.
4. Symbol-out CV (leave-one-out) → min Sharpe ≥ 0.3.
5. Regime split (HMM 3-state bull/bear/range) → ≥ 2 rejimde pozitif Sharpe (H0e).
6. Stress periodları: 2022-05 LUNA, 2022-11 FTX, 2023-03 USDC, 2024-03 BTC ATH, 2024-08 Yen carry → her birinde drawdown ≤ %10.
7. Shuffle baseline: returns 1000× shuffle → p < 0.001.
8. **Filter-off ablation (H0c primary):** EMA-50 filter kapatılır; Sharpe(no-filter) / Sharpe(with-filter) ≤ 0.70 zorunlu (yoksa edge filter'dan, iii'den değil).
9. **Cross-edge primary:** vsa_climax_test daily-return serisine karşı rolling 90d ρ ölçülür; OOS pencerede max |ρ| → gate.

---

## 8. Beklenen p-value ve Multiple Testing Düzeltmesi

- Naive prior (Volman kalitatif "daha güçlü" → kripto'ya transfer): p ≈ 0.02-0.05.
- Realistic prior (anti-narrative): p ≈ 0.15-0.30 (no edge after fees + filter contamination).
- **Karar eşiği:** Holm-Bonferroni p < 0.000617 (81 trial) **VE** DSR ≥ 0.5 **VE** PBO < 0.5.
- Hepsi geçmezse → REJECT.

---

## 9. Stop Criteria (erken sonlandırma — kaynak israfı önler)

- IS Sharpe < 0.4 (preliminary 6-month sub-sample) → terk, robustness'a girme.
- Breakout follow-through win-rate < %52 (H0a kaba) → red, iii'nin Volman'ın iddia ettiği kadar güçlü olmadığı kanıtı.
- 81 kombinasyondan hiçbiri Holm-düzeltilmiş p < 0.000617 üretmiyorsa → red.
- ρ(strategy, vsa_climax_test) ortalama > 0.25 → cross-edge gerekçesi düştü, Chan 0.8 eşiği zaten geçilmediği için solo aday değil → red.
- Filter-off ablation Sharpe oranı > 0.70 → edge EMA-50 filtresinden, iii sinyalinden değil → red (H0c).
- 3 iterate v2-v4 sonrası hala gate'siz (SOP-4b budget) → arşiv.

---

## 10. SOP-4 Karar Yolları (3-way)

- **Terfi:** Tüm gate ✓ + tüm robustness ✓ + |ρ| ≤ 0.25 + H0c ✓ → Lab tournament queue.
- **Iterate (SOP-4b — pozitif edge rescue):** ROI pozitif ama (DD > %18) VEYA (|ρ| 0.25-0.40 arası) VEYA (filter-off Sharpe ratio 0.70-0.85 arası):
  - v2 — risk_pct 0.5 → 0.3, max_concurrent 1 → koru
  - v3 — sembol subset (top-15 düşük korelasyon)
  - v4 — TP early-take (1R partial + 1.8R full) trail-stop
  - Max 4 iterate; sonra arşiv.
- **Red:** ROI ≤ 0 VEYA H0a düştü VEYA |ρ| > 0.40 VEYA filter-off ratio > 0.85.

---

## 11. Curve-Fit / Bias Şüphe Listesi (pre-registered, audit trail)

Backtest sonrası BU LİSTE adım adım kontrol; herhangi biri TRUE → terfi REDDEDİLİR:

- [ ] Best param uç noktada (`inside_count_min` ∈ {2,4} VEYA `breakout_buffer_atr` ∈ {0.05, 0.20} VEYA `sl_atr_mult` ∈ {0.5, 1.5}).
- [ ] IS/OOS Sharpe ratio > 3 (López-Prado kırmızı).
- [ ] Trade count < 100 (1D + 50 sembol × 4y, iii nadir-orta sıklık → beklenen 250-800; <100 = liquidity over-aggressive veya pattern fiili yok → red).
- [ ] Tek sembol P&L payı > %25.
- [ ] Tek yıl (2022/23/24/25) P&L payı > %50.
- [ ] Holm-Bonferroni sonrası anlamlı kombo = 0.
- [ ] Filter-off ablation Sharpe oranı > 0.70 (edge filter'dan).
- [ ] OOS regime split: sadece bull rejimde pozitif (H0e).
- [ ] Bull-rejim Sharpe yüksek + vsa_climax_test bear-rejim Sharpe yüksek → ρ raw düşük çıkıyor olabilir ama bu "rejim-anti-korelasyon" cross-edge sayılmaz; her ikisi de regime-conditional → red.

---

## 12. Beklenen Çıktı (Lab'e teslim raporu)

`reports/research/iii-triple-inside-breakout-d1-cross-edge-2026-06-29.html` — SOP-1 §7 standart tablosu + bu doc'a back-link + cross-edge ρ time-series + filter-off ablation tablosu.

---

## 13. Pre-Reg Commit Sözü

> Bu hipotezi commit edene kadar BACKTEST KODU YAZILMAZ. Backtest sonrası HİÇBİR bağımlı değişken eklenmez, HİÇBİR parametre aralığı genişletilmez. İhlal = `learning.md`'ye "pre-reg violation" + hipotez otomatik REJECTED. Volman'ın kalitatif "daha güçlü" iddiası burada **%58 follow-through win-rate** olarak operasyonalize edilmiştir; bu sayı sonradan değiştirilmez.

**Pre-reg author:** researcher (LLM agent, persona @claude-opus-4-7)
**Review requested from:** lab_scientist (gate enforcement + tournament admission), risk_officer (sizing 0.5% + DD bandı + leverage 1x default)
**SLA:** 24h critique/endorse (Risk 6h)
