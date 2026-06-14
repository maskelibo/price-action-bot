---
doc_id: researcher-20260614T100000-vol-regime-sizing-modulation
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-14T07:00:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [risk_officer, lab_scientist, adversary_engineer]
tags: [sizing, volatility_regime, rolling_performance, dynamic_deleveraging, curve_fit_risk]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-06-14-vol-regime-sizing-modulation

## 0. Meta
- **Tarih:** 2026-06-14
- **Versiyon:** 0.1 (pre-registration)
- **Seed konu:** Volatility regime sizing optimization
- **Önceki yakın hipotezler:**
  - `2026-05-15-alt-data-continuous-regime-intensity-sizer.md` (alt-data → regime → size; bu hipotez OHLCV-only)
  - `2026-05-15-correlation-graduated-sizing.md` (corr → size; ortogonal)
  - `2026-05-29-brooks-3fx-vol-targeting-risk-engineering.md` (vol-target üzerinden; bu hipotez **iki sinyali birleştirir**: realized-vol percentile + rolling 30-trade Sharpe)
- **Farklılaşma:** Sizing'i **iki bağımsız sinyalle** modüle eder:
  1. Realized-vol percentile (ATR-90) — Kaufman/López *vol-target* primitifi
  2. Rolling 30-trade Sharpe — Kaufman *performans-aware* primitifi
  - Ayrıca López *dynamic deleveraging* drawdown-tepkisi katmanı.
- **Stratejinin temel motoru DEĞİŞTİRİLMİYOR.** Mevcut champion sinyali (Phoenix Scalp 15m widestop_vsa2) sabit; bu hipotez **yalnız position-sizer'ı** kapsar (sizer ablation çalışması).

## 1. İddia (pre-registered, ölçülebilir)

> **H1:** Sabit-fraksiyon sizer (risk_per_trade=0.5%) yerine üç bileşenli `vol_regime_sizer` (ATR-percentile çarpanı × rolling-Sharpe çarpanı × DD-deleverage çarpanı, hard cap 1.5×, hard floor 0.25×) kullanıldığında, 2022-01-01 → 2026-04-30 dönemi USDT-perpetual evreninde, 15m Phoenix Scalp Widestop-VSA2 stratejisinde **eşzamanlı olarak**:
>
> 1. **OOS Sharpe artışı:** ΔSharpe ≥ **+0.20** (baseline fixed-frac OOS Sharpe'a göre)
> 2. **MaxDD azalması:** ΔMaxDD ≤ **−20%** (relative, baseline'a göre; örn. baseline %30 → aday ≤ %24)
> 3. **CVaR (5% tail loss) iyileşmesi:** ≥ **−15%** (relative)
> 4. **Net annual return KAYBI sınırlı:** ΔReturn ≥ **−15%** (yani agresif sizer'ın getiriyi katletmesi yasak)
> 5. **N_trade ≥ 500** (istatistiksel anlamlılık şartı)
> 6. **Bonferroni-corrected DSR p < 0.05** (BoxedFold / random-shuffle baseline'a karşı)
>
> Yukarıdaki 6 koşulun **HEPSİ** sağlanmazsa **H1 reddedilir**.

> **H0 (null):** vol_regime_sizer fixed-fraction sizer ile **istatistiksel olarak ayırt edilemez** OOS performans verir.

## 2. Gerekçe (RAG referansları)

| Bileşen | Kaynak | Alıntı / Kalıp |
|---|---|---|
| Rolling perf-aware sizing | [Kaufman 2013 (RAG #4)] | "Sistem son 30 trade'de %60 win rate'in üzerindeyse normal sizing; %40'ın altındaysa size %50 düşürülür. Bu basit 'regime-aware' sizing kuralı alpha decay periyodlarında sermaye korur. Sample size yeterliliği kritik — 30 trade'lik pencere noisy kalabilir." |
| Vol-target sizing | [López de Prado 2018 (RAG #5)] | "L\* = vol_target / vol_strategy" + "L_t = L\* · (1 − D_t / DD_max)^α, α ≈ 1–2" — drawdown'a göre otomatik deleveraging. |
| Fractional Kelly tavanı | [Kaufman / Vince (RAG #6)] | "Drawdown tolerance, optimal-f'in onda biri civarındadır; çoğu pratik sistem 0.1f–0.25f kullanır." → Hard cap 1.5× neden makul. |
| Crypto fat-tail uyarısı | [Kaufman (RAG #7)] | "Crypto için %0.5–1.0 daha güvenli, çünkü volatilite fat-tail." → Baseline'ı 0.5%'te tutuyorum (agresifleştirme yok). |
| Vol-cyclicality | [Grimes (RAG #9)] | "Volatilite döngüseldir — düşük vol yüksek vol'e geri döner." → Düşük-vol rejiminde size yükseltmek riskli (rejim değişiminde lev yüksek kalır); **bu yüzden floor değil cap'i 1.5× ile sınırlıyorum.** |

**Kaufman'ın kendi uyarısı** (RAG #4 son cümle) ve **López'in deleveraging asimetrisi** (RAG #5) bizatihi curve-fit riskine işaret eder — pre-registration'ı önceden katı yapıyorum.

## 3. Bağımlı Değişkenler (önceden donmuş; sonradan eklenmez)

Primer:
- `oos_sharpe_diff` (vs. baseline fixed-frac, walk-forward OOS dilimlerinin ortalaması)
- `oos_maxdd_relative_change` (account-equity tabanlı, %)
- `oos_cvar_5_relative_change`
- `oos_net_annual_return_diff_pct`
- `n_trades`
- `dsr_p_value_bonferroni_corrected`

Sekonder (info-only, karar tetiklemez):
- Profit factor, expectancy, turnover, payoff ratio
- Sharpe-regime breakdown (low-vol / mid-vol / high-vol bucketlar)
- Avg trade size çarpanı dağılımı (sizer'ın gerçekte ne kadar değiştiğini görmek için)

## 4. Bağımsız Değişkenler — DAR GRID (curve-fit önlemi)

⚠️ **Parametre kombinasyon sayısı = 3 × 3 × 3 × 3 × 2 = 162**. Bonferroni ile **anlamlılık eşiği α/162 = 0.000309** (Bonferroni-Holm uygulanacak, BH-FDR yedek).

| Parametre | Grid (KALIN, ince değil) | Gerekçe |
|---|---|---|
| `atr_percentile_window` | {60, 90, 120} bar | 90 = Kaufman literatür default; 60/120 robustness uçları |
| `vol_low_threshold` (ATR pct) | {0.20, 0.30} | Tek değer denemek tek-nokta-bias; 2 makul kalın değer |
| `vol_high_threshold` | {0.70, 0.80} | Aynı şekilde |
| `vol_low_mult` (low-vol → upsize) | {1.0, 1.25, 1.5} | 1.0 = neutral (kontrol); cap 1.5× |
| `vol_high_mult` (high-vol → downsize) | {0.5, 0.75} | %50 indirim = Kaufman default; %25 yumuşak |
| `rolling_sharpe_window` | {20, 30} trade | Kaufman 30; 20 daha hızlı ama daha noisy |
| `rolling_sharpe_low_mult` | {0.5, 0.75} | <0 Sharpe → küçült |
| `rolling_sharpe_high_mult` | {1.0, 1.25} | >1.5 → 1.0 (kontrol) veya hafif upsize |
| `dd_deleverage_alpha` (López α) | {0.0 (off), 1.0, 2.0} | 0.0 = off ablation; 1.0 lineer; 2.0 kuadratik |
| `sizer_hard_floor` | 0.25× (sabit) | Donmuş, optimize EDİLMEZ |
| `sizer_hard_cap` | 1.5× (sabit) | Donmuş, optimize EDİLMEZ |

**Yasaklananlar (curve-fit korumaları):**
- 0.01 adımlı percentile veya threshold (örn. 0.27, 0.28...) — **YASAK**
- Sembol-spesifik parametre — **YASAK**
- TF-spesifik parametre (5m/15m ayrı) — **YASAK** (sadece 15m'de test)
- Optuna n_trials > 162 (grid exhaustive) — **YASAK** (gizli "deneme" sayısı şişmesin)

## 5. Stop Criteria (önceden yazılı; gözlem-sonrası değiştirilemez)

Aşağıdakilerden **HERHANGI BİRİ** olursa hipotez **anında reddedilir** ve `learning.md`'ye 3 satır gerekçe yazılır:

1. **In-sample Sharpe < baseline fixed-frac IS Sharpe × 1.05.** Sizer-ablation IS'da bile +5% Sharpe getirmiyorsa OOS'ta da getirmez. Erken kes.
2. **Best parameters grid uçlarında.** Örn. best `vol_low_mult = 1.5` (cap) veya best `dd_deleverage_alpha = 2.0` (max) → aralık daha geniş test edilmeliydi; reddet.
3. **IS/OOS Sharpe farkı > %30.** Klasik overfit bayrağı.
4. **Walk-forward dilimlerinin < %60'ı pozitif.** 12 dilim, ≥ 8'i pozitif şartı.
5. **Symbol-out CV'de ≥ 2 sembol negatif edge.** 19-sembol pool, çıkar-bırak.
6. **Shuffle baseline'ı yenmiyor** (p > 0.05, raw; p > 0.000309 Bonferroni'den önce kontrol).
7. **Lookahead testi başarısız** (sizer t bar'ında t+1'in vol percentile'ını kullanıyorsa fail).
8. **N_trade < 500.** İstatistik anlamsız.
9. **Stress periyodlarının (LUNA 2022-05, FTX 2022-11, USDC 2023-03, Yen 2024-08) HERHANGI birinde sizer fixed-frac'tan yıkıcı kayıp gösterirse** (DD > baseline DD × 1.5 o dönemde) → reddet.

## 6. Curve-Fit Şüphesi (önceden ilan edildi)

Bu hipotezin **özellikle curve-fit'e açık olduğu** alanlar:

- **162 parametre kombinasyonu** — Bonferroni-Holm zorunlu, BH-FDR yedek.
- **3 ayrı sinyal üst üste** (ATR percentile × rolling Sharpe × DD-deleverage) — her biri tek başına edge eksikse kombine "şanslı kesişim" üretebilir. **Tek-sinyal ablation testi** zorunlu: her birini sırasıyla kapat, geri kalan 2'sinin tek başına gate'i geçemediğini göster (kombinasyon olarak da geçemezse asıl edge yok, sadece sinyal kesişimi şans).
- **Sizer-only A/B ayrı tutuluyor** — mevcut stratejinin sinyali değişmediği için "free lunch" sizer arıyoruz; bu inherently şüpheli.
- **Rolling-Sharpe modulator** kendi reflexivity'sini ekler: bot kazandıkça size'ı büyütür, kaybedince küçültür → momentum-on-equity (good in trend, devastating in mean-reverting equity). **Trade-order Monte Carlo** zorunlu (mevcut shuffle baseline pipeline'ı var).

## 7. Beklenen p-Value ve Anlamlılık Eşikleri

- **Raw DSR p:** beklenen < **0.01**
- **Bonferroni-corrected (α/162):** < **0.000309** (162 grid noktası için)
- **Eşik geçilemezse:** Bonferroni-Holm step-down + BH-FDR yedek. Yine geçemezse → reddet.
- **Walk-forward stability:** OOS dilim Sharpe'larının varyansı IS varyansının < %150'sinde olmalı (aşırı dilim-bağımlılığı reddedilir).

## 8. Backtest Setup (donmuş)

- **Engine:** `backtest/engine.py` (vectorbt)
- **Universe:** 19-sembol pool (data/futures/), survivorship-aware (delistings dahil)
- **Strateji:** Phoenix Scalp Widestop-VSA2 (mevcut champion sinyali, **değişiklik YOK**; sadece sizer override)
- **TF:** 15m primary
- **Dönem:** 2022-01-01 → 2026-04-30 (52 ay)
- **Walk-forward:** 24m train / 6m test, step 3m → ~10 dilim
- **Fees:** 4 bps taker / -1 bp maker (mevcut konservatif default)
- **Slippage:** 5 bps
- **Initial:** $10k USDT (sabit-fraksiyon, mevcut "fresh-$10k-her-ay" şişme bias'ından kaçınmak için **kümülatif tek-cüzdan** modu)
- **Baseline:** Aynı strateji, sizer = fixed 0.5% (mevcut canlı setup)
- **Adversary review:** adversary_engineer kill-probe (LUNA/FTX/Yen replay) zorunlu

## 9. Reproducibility

- `git_hash`: backtest çalıştırılırken commit edilir
- `config_hash`: SHA256 of frozen parameter grid YAML
- `data_hash`: SHA256 of DuckDB parquet manifest
- Tüm 162 trial sonucu `reports/research/HYP-2026-06-14-vol-regime-sizing-modulation/trials.parquet`

## 10. Tarihsel Bağlam ve Saklama

- **Çapraz referans (MEMORY):** [v14 testnet deploy] — mevcut canlı r0.62 risk pct'si 0.005; bu hipotez **canlı parametreleri değiştirmez**, sadece backtest aday üretir.
- **Çapraz referans:** [Backtest compounding şişmesi] — bu hipotezde **sabit-fraksiyon kümülatif cüzdan** zorunlu; "fresh-$10k-her-ay" yöntemi kullanılmayacak (10-25× şişme bias'ı).
- **Çapraz referans:** [Champion 15m launchd KeepAlive] — pre-registration TAMAMLANMADAN canlı sizer override **yasak**.

## 11. Karar Çerçevesi (sonradan doldurulacak)

- [ ] **Terfi adayı** — 9 gate'in 9'u ✓, Adversary kill-probe ✓ → Lab tournament'a teslim
- [ ] **İterate (SOP-4b)** — Aylık ROI pozitif ama DD/CVaR/p-value ≥1 gate'i geçemedi → v2 dene (ör. hard floor 0.30×, rolling Sharpe window 50, deleverage α=1.5)
- [ ] **Red (gerekçeli arşiv)** — Yukarıdaki stop criteria'lardan ≥1 tetiklendi

## 12. Beklenti (kendime not, sonradan rasyonalizasyon önlemi)

> Açık olarak yazıyorum: bu hipotezin **reddedilmesini bekliyorum.** Sizer-only modifikasyonlar, mevcut sinyal istatistiksel olarak zayıflıysa edge üretmez — yalnızca DD'yi yumuşatır ama getiriyi de eş oranda yer (vol-target literatürü Sharpe-eşdeğeri sonuç verir, ne fazla ne az). Reddedilse bile **DD ve CVaR'da net iyileşme** + **return-neutral** ortaya çıkarsa, bu **kendi başına Lab'e teslim edilecek bir mini-bulgu**dur (sizer-as-risk-manager, not sizer-as-alpha).

---

**Pre-registration hash kilidi:** Bu dosya commit edilince hash dondurulur. Sonraki tüm parametre/eşik değişiklikleri **yeni dosya + supersedes** ile yapılır; bu dosyaya **dokunulmaz**.
