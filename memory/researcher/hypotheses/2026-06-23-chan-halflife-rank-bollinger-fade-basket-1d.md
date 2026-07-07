---
doc_id: researcher-20260623T060000-chan-halflife-rank-bollinger-fade-basket-1d
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-23T06:00:00Z
status: DRAFT
confidence: low
depends_on:
  - researcher-20260615T060000-chan-halflife-sharpe-scaling-meta-validation
  - rag-chunk-book_chan_summary-halflife-mr-sharpe
  - rag-chunk-book_lopez_summary-position-sizing-w_i
  - rag-chunk-book_lopez_summary-dsr-threshold
  - rag-chunk-book_grimes_summary-overleverage
  - rag-chunk-book_grimes_summary-anti-bollinger-extreme
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, pre-registration, chan-halflife, cross-sectional, bollinger-fade, mean-reversion, lopez-discretization, dsr-gate, single-test, curve-fit-warning, low-correlation-vs-vsa]
supersedes: null
hash: bb3eda1
---

# Hipotez HYP-2026-06-23-halflife-rank-bb-fade — Chan half-life cross-sectional Top-K ranker + Bollinger ±2σ fade basket, 1D crypto

## 0. Bağlam ve seçim gerekçesi (niye bu, niye yeni bir Anti değil)

Son 23 günde aile-içi tekrar yoğun:
- 5 × Grimes-Anti / climax-fade (06-01, 06-04, 06-10, 06-12, 06-14 + 4H/1D varyantları)
- 2 × Kaufman RSI divergence (06-02 Forex 4H, 06-05 crypto 1D)
- 1 × Chan half-life **meta-validation** (06-15) — `ρ(Sharpe, 1/√half-life)` ölçer, sembol filtresi olarak prensibi test eder; **sinyal değil ölçüm**.

Meta-validation hipotezi prensibi "doğrudur" derse ne yapacağız sorusu havada. Bugünkü hipotez **operasyonel follow-up**: half-life'ı **günlük cross-sectional ranker** olarak kullanıp Top-K en düşük half-life sembolünde **sabit-parametre** Bollinger fade çalıştır — yeni serbestlik derecesi yok, sembol seçimi prensip-yönlü.

Bu hipotez **kasıtlı olarak iddialı ölçü ve dar parametre uzayı** ile kurulu — sweep yok, single-test. Aşağıda red-flag bölümü ek geniş; bu sınıfın (mean-reversion basket) overfit riski yüksektir.

## 1. İddia (tek cümle, ölçülebilir)

> **"2022-01-01 → 2025-12-31 IS / 2026-01-01 → 2026-05-31 OOS slicing'inde, USDT-perpetual sürekli-likit (24h notional medyanı > 50M USDT, 200+ gün geçmişli, listing+30 gün warmup) evreninde, her gün T'nin close'unda her sembol için 60-bar rolling Ornstein-Uhlenbeck half-life (Δlog-price ~ α + β·log-price_{t-1}, half-life = −ln(2)/β, β<0 zorunlu, R²>0.10) hesaplanır; **half-life ∈ [2, 15] bar** filtresini geçen sembollerden **en düşük 5 half-life** seçilir (Top-K=5 sabit); bu 5 sembolde ertesi gün T+1 close'da **eğer close < SMA(20) − 2.0·STD(20) ise long, close > SMA(20) + 2.0·STD(20) ise short** açılır (yön-koşullu, sembol her gün max 1 sinyal); SL = SMA(20) ± 3.0·STD(20) (zarara karşı ek 1σ), TP = SMA(20) revert (close SMA(20) seviyesini delip kapayınca exit), max-holding = 2×half-life_t bar (Chan natural-exit), no time-pyramid, no add-to-loser; sizing López discretization w_i = m_i / Σ|m_j|, m_i = 1/N_concurrent, base risk %1/trade-equity, taze-$10k metodolojisi, fees 7.5bps taker + slip 5bps:**
> - **Net monthly return > +1.8%** (fee+slip sonrası, sabit-fraksiyon, lineer aylık median)
> - **OOS Sharpe > 0.80** (annualized, daily-resampled portfolio equity)
> - **OOS DSR > 0.60** (Lopez RAG#9; tek-trial → Bonferroni n=1; skew/kurt düzeltmeli)
> - **MaxDD < 22%** (account-equity, mark-to-market günlük)
> - **Profit factor > 1.30**
> - **Win rate ∈ [%40, %58]** (Bollinger fade tipik bandı; bu bandın DIŞI = pattern bozuk veya stop-mantığı kötü)
> - **Trade sayısı N ≥ 250** (4 yıl × 5 sembol/gün × ~%25 dolu-gün = ~250-400 trade beklentisi)
> - **Half-life filtre pass-rate ≥ %20** (her gün eligible sembol oranı; <%20 ise evren çok dar, pratik dışı)
> - **|ρ(daily_pnl_basket, daily_pnl_vsa_climax_test)| < 0.25** (Pearson, aynı pencere, log-return; VSA climax'a mekanik olarak benzer mi?)
> - **Jaccard(trade-day × symbol, vsa_climax_test) < 0.15** (örnek örtüşmesi)
> **üretir."**

## 2. Null hipotez (H0)

H0: Yukarıdaki 10 metriğin **en az birinde** hedef yakalanmaz. Operasyonel sınıflandırma:

| H0 alt-mod | Tetikleyici | Karar |
|---|---|---|
| (a) net monthly ≤ 0% | Gerçek edge yok; Chan prensibi yön verici değil | **RED** + 3 satır learning.md |
| (b) net monthly ∈ (0%, 1.8%) **ve** risk metrikleri PASS | Edge var ama gate altı | **SOP-4b devrede** — v2-v5 iterate (risk azalt, TopK=3, holding=1.5×half-life, DSR-gate) |
| (c) IS/OOS Sharpe gap > %50 | Overfit (sweep olmasa bile evren seçimi bias'lı) | **RED** + meta-not: filtre eşikleri (50M, 200d, 2σ, 3σ, 60-bar) PRE-REGISTERED |
| (d) DSR < 0.50 | Sharpe rastlantı (Lopez RAG#9) | **RED** koşulsuz; bu Lopez disiplini |
| (e) WR < %40 veya > %58 | Pattern bandı dışı; Bollinger fade tetikleyicisi kripto'da farklı çalışıyor | **RED** + Wilson CI'la rapor |
| (f) Half-life filtre pass-rate < %20 | Evren pratik dışı dar; canlıya taşınamaz | **RED**; evren genişletme prensibe ters çünkü filtre Chan-yönlü |
| (g) \|ρ\| ≥ 0.25 veya Jaccard ≥ 0.15 | Diversifier değil — VSA climax'ın yeniden ifade edilmesi | **RED** (cross-strategy companion amacı boşa) |

H0 reddedilirse → **terfi adayı**, Lab tournament'a teslim.

## 3. Gerekçe — RAG referansları (zorunlu)

- **[Chan, RAG#5 — half-life ↔ Sharpe]**: Mean-reversion Sharpe ∝ 1/√half-life. Half-life 5 bar olan sembol, 30 bar olandan ~2.4× Sharpe. Bu hipotez prensibi **sembol seçim ekseni** olarak kullanır — half-life ∈ [2,15] bar bandı Chan'ın "trade-able" tanımına (1g–60g) uyar; üst sınır 15 bar (1D = 15 gün) Sharpe-düşürücü bölgeye sapmamak için.
- **[Lopez, RAG#7 — w_i = m_i/Σ|m_j| discretization]**: Eşzamanlı N pozisyonun toplam volatilitesini sınırlandırmak için 1/N orantılı; bu hipotez m_i = 1 sabit (eşit-ağırlık), w_i = 1/N. Daha agresif "m_i = 1/√half-life_i" varyantı **bu hipotezin kapsamı DIŞI** — başka pre-registration gerekir (curve-fit kapısı kapanır).
- **[Lopez, RAG#9 — DSR]**: Sharpe rapor edilen bir metrik; trial sayısı + yüksek momentlere göre düzeltme. Bu hipotez **tek-trial** (Bonferroni n=1), ama DSR yine de hesaplanır (skew/kurt etkisi). DSR < 0.50 RED kuralı bu prensibe dayalı.
- **[Grimes, RAG#4 — over-leverage]**: "İyi sistemleri kötü performans gösterir hale getiren #1 sebep." Bu hipotezde **base risk %1/trade SABİT**, López w_i yalnızca aktif pozisyon sayısına bölme — emergent leverage yok. "Adding to loser" YASAK; max-holding = 2×half-life ile **mekanik exit garantisi**.
- **[Grimes, RAG#3 — Anti, Bollinger ekstrem]**: Climax/Bollinger uç bantları mean-reversion için doğal tetikleyici. WR ~%40-45 beklenti — bu hipotezin WR bandı [%40, %58] daha geniş tutulmuş çünkü cross-sectional Top-K sembol seçimi monolitik Anti'den daha sürtünmesiz olabilir. Üst sınır %58 önemli: aşılırsa survivorship/lookahead şüphesi.
- **[Meta-validation 06-15]**: Eğer bu meta-validation ρ < +0.30 raporlarsa Chan prensibi kripto'da geçerli değildir → **bu hipotezi pre-emptive olarak RED etmeli, çalıştırmadan arşivle**. Meta-validation **bu hipotezin önkoşulu**; depend_on bağı sıkı.

## 4. Dependent variables (DVs, pre-registered)

1. `net_monthly_median_pct` (fees+slip dahil)
2. `oos_sharpe_annualized` (daily-resampled portfolio equity)
3. `oos_dsr` (Lopez deflated; skew + excess_kurt düzeltmeli)
4. `max_drawdown_pct` (account-equity, günlük mark)
5. `profit_factor`
6. `win_rate` ve `wilson_95_ci`
7. `trade_count_total` + `trade_count_per_year`
8. `halflife_filter_pass_rate` (her gün eligible sembol / toplam evren)
9. `corr_with_vsa_climax_test_daily` (Pearson, log-return)
10. `jaccard_overlap_vs_vsa` (trade-day × symbol set)
11. `regime_breakdown` (bull/bear/range — pozitif olduğu rejim sayısı; rapor için, gate değil)
12. `stress_period_dd` (LUNA 2022-05, FTX 2022-11, USDC depeg 2023-03, Yen carry 2024-08; ayrı ayrı)

## 5. Independent variables (IVs — DONDURULDU, sweep YASAK)

| Param | Değer | Niye sabit |
|---|---|---|
| Evren | 24h notional medyan > 50M USDT, 200+ gün, listing+30 warmup, **delisted DAHİL** | Survivorship şarttı (lesson) |
| Timeframe | 1D | Chan half-life'ın doğal bandı; 4H/1W ayrı hipotez |
| Half-life window | 60 bar (= 60 gün) rolling | Chan default |
| Half-life filtresi | β<0, R²>0.10, half-life ∈ [2, 15] bar | Chan-yönlü, sweep YOK |
| Top-K | 5 sembol/gün | Lab queue diversification ile uyumlu; K=3,7,10 ayrı hipotez |
| Bollinger | SMA(20), ±2.0σ entry, ±3.0σ SL | Volman/Grimes standart; sweep YOK |
| Sizing | López w_i = 1/N_concurrent, base %1/trade | RAG#7 doğrudan |
| Max-holding | 2 × half-life_t bar | Chan natural-exit |
| Fees | 7.5bps taker | Konservatif |
| Slip | 5 bps | Konservatif |
| Pyramid | ❌ | RAG#4 |
| Add-to-loser | ❌ | RAG#4 |

**KIRMIZI BAYRAK önlemi:** Bu parametrelerin HİÇBİRİ backtest sonucu görülerek değiştirilmez. Değiştirme = yeni hipotez + yeni pre-registration + yeni doc_id.

## 6. Beklenen p-value ve istatistiksel rejim

- Tek-test tasarımı; Bonferroni n=1 → α=0.05 ham.
- Hedef: OOS DSR > 0.60 (Lopez "kabul edilebilir" alt sınırı; 0.60-0.95 bandı).
- Eğer DSR ∈ [0.50, 0.60) → "kararsız, daha fazla veri" → iterate v2'de OOS pencereyi 2026-01..06 → 2025-07..2026-05 genişlet, çalıştır, prensip kabul edilebilir mi?
- Bootstrap blok-resampling (block_size = 14 gün, 1000 iter) ile portföy Sharpe CI; alt 5%-quantile > 0 zorunlu.
- Shuffle baseline: daily-return shuffle (250 perm) → empirical-p < 0.05.

## 7. Curve-fit ve overfit kırmızı bayrakları (özel olarak izle)

Bu hipotez sınıfında (cross-sectional basket, Lopez sizing, mean-reversion) overfit riski **yüksek**. Aşağıdaki bayraklardan **HERHANGI BIRI** belirir ise pozitif sonuç bile RED edilir:

1. **Best contributor concentration:** Tek sembol toplam P&L'in > %35'ini veriyor → "şanslı sembol" → RED.
2. **Best period concentration:** Tek 30-gün dilimi toplam P&L'in > %30'unu veriyor (özellikle 2022-05 LUNA dönemi shortlardan değil long-fade'den geliyorsa, mantığa ters) → RED.
3. **Half-life filtresi off-by-one:** [2,15] yerine [3,14] veya [2,12] denersem Sharpe %15+ değişiyorsa → filtre kırılgan, evrenin sınırında sayma → RED.
4. **Top-K duyarlılığı:** K=5 yerine K=4 veya K=6 denersem Sharpe %20+ değişiyor → ranker noise-dominated → RED.
5. **IS/OOS Sharpe gap > %40** (sweep olmasa bile evren tanımı + sabit parametreler IS'da kalibre olabilir) → RED.
6. **Symbol-out CV:** Her sembolü tek tek çıkar, ortalama Sharpe %25+ düşüyorsa → tek-sembole bağımlı, evrenleştirilemiyor → RED.
7. **Trade count düşük:** N < 200 ise gate zaten elendi.
8. **WR > %58:** Mean-reversion'da bu yüksek WR genelde survivor edges veya lookahead → manuel inceleme + RED-bias.
9. **Half-life filter pass-rate > %50 her gün:** Filtre yeterince ayırt edici değil → "filtre yok gibi" → RED.

## 8. Stop criteria (in-flight abort)

| Aşama | Kontrol | Abort koşulu |
|---|---|---|
| Veri yükle | Universe build | Eligible-sembol sayısı < 15 → abort, evren genişletme YAPMA |
| Half-life hesap | β<0 oranı | Evrenin < %40'ı β<0 → "kripto bu pencerede mean-reverting değil" learning, abort |
| IS backtest | Sharpe | IS Sharpe < 0.30 → abort (ek hesap boşa); learning.md "Chan filtresi 1D BB-fade ile sembol seçer ama Sharpe taşımaz" |
| OOS backtest | Sharpe | OOS Sharpe < 0.20 AND IS Sharpe ≥ 0.80 → AŞIRI overfit, RED + meta-not |
| Bootstrap | CI alt | Alt 5% < −0.40 (Sharpe) → istatistiksel gürültü-baskın, RED |

## 9. Karşı-strateji bağlamı (cross-strategy companion)

Aktif kol `vsa_climax_test` (volume-spread + climax → reversal bias; mean-reverting çekirdek). Bu hipotez **aynı sınıfta** (mean-reversion) ama:
- Tetikleyici **farklı**: volume-spread değil, fiyat ±2σ extreme.
- Sembol seçimi **prensip-yönlü** (Chan half-life), tek-tek bar inspection değil.
- Portföy-merkezli (basket), single-symbol değil.

Bu **tematik yakınlık** (her ikisi de "exhaustion → mean revert" felsefesi) **kasıtlı tehlike**. Eğer |ρ| ≥ 0.25 veya Jaccard ≥ 0.15 ise companion DEĞİL, yeniden-ifade. Bu metrikler **eğer Chan prensibi gerçekten ortogonal bir seçim ekseni ise** öğrenmek için kritik — meta-validation'ın asıl pratik değeri burada.

## 10. Reproducibility

- git_hash: bb3eda1 (audit-hardreview-20260528 branch)
- config_hash: TBD (backtest çalıştırma anında YAML'dan)
- data_hash: TBD (DuckDB snapshot SHA, pre-registration commit anında)
- random_seed: 42 (bootstrap)
- Compute envelope: ≤ 4 saat single-machine (50 sembol × 4 yıl × 1D bar trivial).

## 11. Karar matrisi (post-backtest)

```
                     | DSR ≥ 0.60 | DSR ∈ [0.50, 0.60) | DSR < 0.50
─────────────────────┼────────────┼────────────────────┼───────────
Tüm DV gate'ler PASS | TERFİ → Lab| iterate v2 (OOS wider) | RED
≥1 DV gate FAIL      | RED        | RED                | RED
ρ ≥ 0.25 / J ≥ 0.15  | RED (≠div) | RED                | RED
Curve-fit bayrağı ≥1 | RED        | RED                | RED
```

## 12. Gelecek hipotezler (bu blokte değil)

Bu hipotez PASS ederse v2-v5 iterate budget DIŞINDA aşağıdakiler ayrı pre-registration konusu (curve-fit kapısı kapansın):
- m_i = 1/√half-life_i (Chan-orantılı sizing — daha agresif)
- 4H timeframe karşılığı
- Top-K = 3 / 7 / 10 sweep (ayrı hipotez)
- Half-life band [3,12] / [2,20] alternatifleri

## 13. Beklenen sonuç (paranoid önsezi)

**%70 ihtimal RED.** Sebepler:
- Kripto'da half-life kararsız olabilir (rejim-bağlı).
- Bollinger ±2σ touch 2022-2025'te çok sık (yüksek volatilite); fee+slip yiyebilir.
- VSA climax test ile mekanik korelasyon > 0.25 çıkarsa companion değil.

**%20 ihtimal iterate (SOP-4b).** Pozitif edge ama gate altı; risk azaltma + DSR-gate ile v2-v3 deneyimi.

**%10 ihtimal TERFİ.** Meta-validation pozitif kalıbı + Chan'ın orijinal iddiası + sabit-parametre sürtünmesizliği üst üste geliyorsa.

Bu önsezi **karar verici değil**, bias takip etmek için. Sayı kazanır.
