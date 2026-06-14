---
doc_id: researcher-20260610T000000-vol-regime-sizing-opt
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-10T00:00:00Z
status: PROPOSED
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, sizing, position_sizing, volatility_regime, risk_modulation, curve_fit_high_risk]
supersedes: null
hash: null
---

# HYP-2026-06-10 — Volatility-Regime Dynamic Sizing vs. Fixed-Fractional

## 0. Pre-registration Note

Kod yazılmadan donduruldu. Parametre uzayı geniş (4 hiper); **curve-fit kırmızı bayrağı**: çok değişkenli sizing kuralları "in-sample'da daha iyi" olmaya neredeyse garanti. Bu yüzden eşikler **literatürden alıntı** (Kaufman, López); grid'i hipotezden sonra genişletmek yasaktır.

## 1. İddia (measurable)

**1D timeframe phoenix-scalp-15m strateji ailesinde**, son 3y (2023-06-10 → 2026-06-09) tüm-likit USDT-perpetual evreninde, fixed-fractional `risk_pct=0.005` baseline'ına karşı, **volatilite-rejim sizing kuralı**:

```
size_mult = clip( (vol_target / σ_60d) , 0.5, 2.0 )       # López §5
        ·  (1 − DD_30d / DD_max) ^ α   ,  α = 1           # López deleveraging
        ·  (1 if WR_30trade ≥ 0.55 else 0.5)              # Kaufman regime gate
risk_pct_effective = 0.005 · size_mult
```

aşağıdaki **eş-zamanlı** koşulları sağlar (hepsi gate, OR değil):

| Metric | Baseline (fixed) | Dynamic (claim) | Δ koşulu |
|---|---|---|---|
| OOS annualized return (net) | X₀ | X₁ | X₁ ≥ X₀ |
| OOS Sharpe | S₀ | S₁ | (S₁ − S₀) ≥ 0.25 |
| OOS MaxDD | DD₀ | DD₁ | DD₁ ≤ DD₀ × 0.80 (≥%20 düşüş) |
| OOS Calmar | C₀ | C₁ | C₁ ≥ C₀ × 1.30 |
| Trade sayısı | N₀ | N₁ | \|N₁ − N₀\| / N₀ ≤ 0.30 (size-cull değil edge) |

Yani: **DD'yi en az %20 azalt, Sharpe'ı 0.25 puan yükselt, return baseline'ın altına düşmesin.** Tek metrikte iyileşme yetersiz.

## 2. Gerekçe (RAG referansları)

- **[Kaufman §sizing]** Rolling WR/Sharpe ile sizing modulation; 30-trade pencere; %60+ normal, %40− %50 kıs. — *Sample noise riski kabul edilmiş, eşikleri yumuşatıyoruz (0.55 / 0.45).*
- **[López §dynamic_deleveraging]** L_t = L* · (1 − D_t / DD_max)^α, α∈[1,2]. — *α=1 muhafazakar.*
- **[López §vol_targeting]** L* = vol_target / vol_strategy; rolling σ ile leverage ters. — *σ_60d daily-return std.*
- **[Kaufman §optimal_f]** 0.1f − 0.25f bölgesinde kal. — *Bizim fixed 0.005 ≈ 0.05f; dynamic mult ≤ 2.0 → max 0.01 ≈ 0.10f tavanı.*
- **[Grimes §vol_cycles]** Volatilite döngüsel; düşük → yüksek geri döner. — *vol_target lookback 60d, döngünün altında kalıyor — overfit riski.*

## 3. Null Hypothesis (H₀)

**H₀:** Dynamic sizing kuralı, fixed-fractional `risk_pct=0.005` baseline'ı **OOS'ta yenmez** (yukarıdaki 5 eş-zamanlı koşulun en az 1'i fail). Bu sonuç da sayılır — IS'ta yenip OOS'ta yenememek **overfit kanıtıdır**.

**Spesifik çürütme senaryoları:**
1. OOS Sharpe iyileşmesi < 0.25 → red.
2. DD azalması < %20 → red (sizing'in *tek* meşru gerekçesi tail-risk azaltma; getiri varsa da DD'yi koruyamıyorsa kompleksite işe yaramaz).
3. Trade sayısı %30+ değişti → sizing değil, *unintended* filtre etkisi. Red.
4. In-sample / OOS Sharpe farkı > %40 → overfit. Red (kalitedeki kayıp).

## 4. Dependent Variables (önceden seçildi)

- OOS net annualized return
- OOS Sharpe (annualized, daily-return base, 365)
- OOS MaxDD (equity-base, **bug-aware**; CT-RSK-01 reçetesine uygun)
- OOS Calmar
- IS-OOS Sharpe Δ (overfit detector)
- Trade sayısı
- Per-regime (bull/bear/range) breakdown

## 5. Independent Variables (donduruldu)

| Parametre | Değer | Neden bu? |
|---|---|---|
| vol_target (annualized) | **0.30** (30%) | Champion gerçekleşen vol bölgesi; literatür "10-40%" tipik |
| σ lookback | **60 gün** | López §5 önerisi; daha kısa noisy |
| size_mult clip | **[0.5, 2.0]** | Kaufman 0.1f-0.25f sınırı |
| DD_max | **0.25** (25%) | Mevcut risk.yaml halt eşiğine yakın |
| α (deleveraging power) | **1** | López "1 muhafazakar" |
| WR lookback | **30 trade** | Kaufman önerisi |
| WR gate eşiği | **0.55 / kıs** | Kaufman 0.60/0.40'tan yumuşak |
| Cut multiplier | **0.5** | Kaufman önerisi |

**Hiçbir parametreyi optimize etmeyeceğim.** Bu hipotezin amacı **kural ailesinin** literatürdeki forma sadakatle iyileşme sağlayıp sağlamadığını ölçmek; grid search değil.

## 6. Beklenen p-value & Multiple Testing

- **Ham hedef:** p < 0.01 (Sharpe Δ bootstrap, 10,000 resample, paired by-day).
- **Bonferroni:** k=5 metrik test ediliyor → α' = 0.01/5 = 0.002.
- **Shuffle baseline:** Sizing kuralını **rastgele** bir size_mult sequence ile değiştirip aynı simülasyonu 1,000 kez koş; gerçek kural shuffle dağılımının %99'unu yenmeli.
- **Reality check (López):** White's Reality Check, k=1 strateji ile aynı sonucu vermeli.

## 7. Stop Criteria (kod yazmadan önce yazılı)

1. **In-sample Sharpe Δ < 0.10** → araştırma terkedilir. Edge sinyali yok.
2. **OOS trade sayısı baseline'ın %30 dışında** → red, yeni hipoteze geçilir.
3. **Walk-forward 12 dilimden 4'ten azı baseline'ı yeniyor** → red.
4. **Optuna *kullanılmıyor* — parametre uzayını süpürmüyorum.** Eğer hipotez bu şekliyle başarısız olursa, **yeni hipotez** açılır; aynı dosyada parametre değiştirilmez (p-hacking koruması).

## 8. Robustness Suite Plan

SOP-3 tamamı zorunlu. Ek olarak:

- **Sizing-kapalı/açık ayrıştırma:** 3 ayrı koşu — sadece vol-targeting, sadece DD-deleveraging, sadece WR-gate. Her birinin bireysel katkısı raporlanır. Hangi bileşen edge'i taşıyor?
- **σ proxy alternatifi:** σ_60d yerine `realized_vol_TR` (Garman-Klass) → kural sağlam mı, yoksa σ tanımına bağımlı mı?
- **Stress periyotları:** 2022-05 LUNA, 2022-11 FTX, 2024-08 Yen unwind — bu dönemlerde dynamic sizing baseline'dan **daha az** kayıp vermeli (varlık sebebi bu).

## 9. Curve-Fit Risk Beyanı

**Bu hipotez yüksek curve-fit riski taşır.** Şu işaretler bekleniyor:
- Çok hiperparametreli kural (4 hiper × clip ranges).
- Literatür "iyi gelen" eşiklerinin **post-hoc** seçildiği iddiası kolay.

**Koruma:**
- Hiçbir hiper hipotezden sonra revize edilmeyecek.
- IS-OOS farkı sıkı ölçülecek.
- Shuffle-baseline + Bonferroni zorunlu.
- Eğer bu kural başarısız olursa, **basitleştirilmiş** bir alt-kural (sadece DD-deleveraging) **ayrı hipotez** olarak açılır; aynı dosyada "iterate" yapılmaz.

## 10. Backtest Setup (özet)

| Item | Değer |
|---|---|
| Universe | USDT-perpetual all-liquid (historical, delisting-inclusive) |
| Timeframe | 15m primary, 1H trend filter (champion ile birebir) |
| Period | 2023-06-10 → 2026-06-09 (3y) |
| Train/Test split | walk-forward 24m train + 6m test, step 3m → 12 dilim |
| Fees | 7.5 bps taker / -1 bp maker |
| Slippage | 5 bps konservatif |
| Initial equity | 10,000 USDT |
| Baseline | Aktif champion config (`configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml`) |

## 11. Karar Çerçevesi (önceden taahhüt)

- **Tüm 5 gate ✓** → terfi adayı, Lab tournament.
- **DD ✓ + Sharpe ✓** (return zayıf) → "DD-protective sizing" *farklı* hipotez olarak yeni dosyaya. Bu hipotez red.
- **Sadece IS iyi, OOS zayıf** → red + `learning.md`'ye "vol-regime sizing overfit'lendi (3. kez)" notu.
- **Hiç fark yok** → red + Kaufman/López sizing literatürünün kripto-perpetual'a transferinin zor olduğu temel notu eklenir.

## 12. Reproducibility Stub

```
git: <commit at run time>
config_hash: <derived from this file frozen>
data_hash: <duckdb manifest at run>
seed: 20260610
```

---

**Pre-registration zamanı:** 2026-06-10T00:00:00Z. Bu noktadan sonra:
- Parametre değişimi → yeni hipotez.
- Eşik gevşemesi → yeni hipotez.
- "Bir de şunu deneyelim" → yeni hipotez.

Bu disiplin tek başına bu hipotezin değerini belirler.
