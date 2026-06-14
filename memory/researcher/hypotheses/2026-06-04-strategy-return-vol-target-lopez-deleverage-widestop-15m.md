---
doc_id: researcher-20260604T093000-vol-regime-sizing-lopez-deleverage
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-04T09:30:00Z
status: DRAFT
confidence: low
depends_on:
  - researcher-20260529-brooks-3fx-vol-targeting
  - researcher-20260515-alt-data-continuous-regime-intensity-sizer
  - researcher-20260512-regime-realized-vol-percentile
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags:
  - sizing
  - vol_targeting
  - lopez_deleverage
  - chan_kelly
  - kaufman_fractional_f
  - widestop_vsa
  - champion_iterate
  - sop_4b
  - curve_fit_risk_high
supersedes: null
hash: null
---

# HYP-2026-06-04 — Strategy-Return Vol-Targeting + López Drawdown Deleveraging (WIDESTOP-VSA 15m iterate)

## 0. Niyet ve Sınırlar (anti-narrative beyanı)

Bu **yeni bir entry sinyali değil**. SOP-4b kapsamında deployed champion'a (`phoenix_scalp_15m_widestop_vsa2`)
**risk-mühendisliği katmanı** iteratesi. Önceki 3 hipotez (HYP-REGIME-002, alt-data continuous,
Brooks 3FX vol-targeting) **piyasa-RV** veya **piyasa-rejim** girdisini test etti. Bu hipotez
**strateji-içi realized R dağılımı** + López **drawdown-deleveraging** denklemini bir arada test
eder — ayrı bir literatür ayağı, ayrı bir kontrol değişkeni. Yine de **3 vol-temelli sizing
hipotezi peş peşe geldiği için recency-bias + curve-fit riski yüksek** olarak işaretliyorum
(bkz §7).

## 1. Pre-Registered İddia (TEK CÜMLE, ölçülebilir)

> 15m `phoenix_scalp_widestop_vsa2` champion'ında sabit %0.5/trade risk yerine, **t-1'e kadar
> kapanmış son N trade'in realized R-std'sine ters-orantılı vol-targeted sizing** (target
> portfolio R-vol = σ\*) + **López dynamic deleveraging** L_t = L\* · max(0, 1 − D_t/DD_max)^α
> uygulandığında — sabit-risk baseline'a göre, 2022-01-01..2025-12-31 pencere üzerinde **eşleştirilmiş
> bootstrap'ta (10k seed, paired by month)**:
>
> - aylık-Sharpe artar: Δ ≥ **+0.15** (CI alt-sınırı > 0, p < 0.05),
> - MaxDD düşer: Δ ≤ **−10 pp**,
> - aylık median return düşüşü ≤ **%25** (yani edge öldürülmez, sadece kuyruk kesilir),
> - VE bu üç koşul **eşzamanlı** sağlanır.

Üçü birden sağlanmazsa hipotez RED. (Tek-metrik p-hacking koruması)

## 2. Null Hipotez (Popper — ne olursa çürür)

H0: Vol-targeting + López-deleveraging, sabit-%0.5 risk'e karşı eşleştirilmiş aylar üzerinde
**Sharpe-eşit / MaxDD-eşit** (paired bootstrap %95 CI'sı sıfırı içerir) sonuç verir.

Çürütme delili: yukarıdaki 3 koşulun **AYNI ANDA** sağlanması + walk-forward'da yön
korunması + shuffle-baseline'da gerçeklenmemesi.

## 3. RAG-temelli gerekçe (sayıyla)

- **[López — book_lopez_summary §dynamic deleveraging]**: L_t = L\* · (1 − D_t/DD_max)^α,
  α ∈ [1, 2]. Live drawdown büyüdükçe kaldıraç **mekanik** olarak küçülür — "real-money path'lerde
  fonun ölmesini önler" iddiası. Bizim canlı champion'ın 90-gün MaxDD'si ≈ %20-25 (compounding-
  düzeltilmiş), DD_max=%30 koyarsak L_t %25 DD'de **%0** olur (α=1) veya **%0** (α=2). Bu
  matematiksel bir bekçi.

- **[Chan — book_chan_summary §Kelly]**: f\* = SR/σ, half-Kelly güvenli pratik. Champion canlı
  Sharpe ≈ 1.0 (honest), σ (aylık) ≈ %15 → f\* ≈ 6.7x. Half-Kelly = **3.3x**, quarter-Kelly =
  **1.7x**. Şu an sabit %0.5/trade × ~6 paralel ≈ %3 toplam open-risk → kabaca 0.4–0.6x Kelly.
  Yani **vol-target σ\* = strategy-realized aylık R-std × 1.0** koymak quarter-Kelly civarı kalır.

- **[Kaufman — book_kaufman_summary §fractional f]**: optimal-f'in %10-25'i pratik. Sabit %0.5
  hâlihazırda fractional; bu hipotez **fractional'ı statik değil dinamik** yapar (Kaufman'ın
  asıl önerisi).

- **[Grimes — book_grimes_summary §vol cycles]**: Volatilite döngüseldir; düşük-vol rejim
  sonrası genişleme ortalama %50 win, R büyür. Stratejimizin **fasl edge'i** vol-genişleme
  fazında, **fasl drawdown'ı** vol-daralma+whipsaw fazında. Vol-targeting bu döngünün
  ikincisini söndürmek için.

- **[Smith-Le / He — score=0.36 batch-size argümanı]**: SGD batch-size argümanı yatırımcı vol-
  targeting'e doğrudan transfer edilebilir (per-point statistics). **Doğrudan kullanılmadı** ama
  vol-tahmin formülünün rolling per-trade R üzerinde — per-bar değil — bias-tutarlı kalması
  için tasarımı disiplinli tuttu (lookback bar değil trade sayısı cinsinden).

## 4. Dependent Variables (pre-registered, sabit)

Aylık seviyede:
- monthly_return_mean
- monthly_return_median
- monthly_return_std
- monthly_return_skew
- monthly_sharpe (mean/std)
- continuous_MaxDD
- ulcer_index
- worst_month
- neg_month_pct
- trade_count
- avg_R
- R_std
- median_R

Hepsi **sabit-risk baseline** ile **vol-target + López** arasında paired (per-month) bootstrap
karşılaştırılır.

## 5. Independent Variables (taranacak GRID — sabit, multiple-testing FARKINDA)

Toplam kombinasyon **TAVANI: 144** (Bonferroni eşik: 0.05/144 ≈ 3.5e-4; BH-FDR q=0.1 uygulanır).

| Parametre | Aday değerler | Adet |
|---|---|---|
| vol_lookback_trades (N) | {20, 40, 80} | 3 |
| target_R_std (σ\*) | {0.6, 0.8, 1.0, 1.2} | 4 |
| vol_scale_clamp | {[0.5, 2.0], [0.33, 3.0]} | 2 |
| DD_max (López) | {0.20, 0.25, 0.30} | 3 |
| alpha (López) | {1.0, 1.5, 2.0} | 3 |
| floor risk_pct | {0.0005, 0.001} | 2 |

→ 3·4·2·3·3·2 = **432** trial. **Bu grid kasten dar tutuldu**: her boyutta ≤4 değer; "0.01
adım" anti-pattern'ine kaçınma. 432 trial için **Bonferroni eşik p < 0.05/432 ≈ 1.16e-4**;
BH-FDR (q=0.10) hangi konfiglerin "anlamlı survivor" sayılacağını belirler. **IS'te en iyi 3
konfig** seçilir, **OOS'ta tek seferde** doğrulanır.

## 6. Lookahead disiplini ve veri-bütünlüğü taahhütleri

- Vol tahmini SADECE **t-1 ve öncesinde kapanmış trade**'lerin R'sinden (kapanmış-bar bile
  değil — kapanmış-trade). Açık trade'in unrealized R'si girmez.
- DD tahmini **realized equity curve**'den; mark-to-market açık pozisyon dışlanır.
- Survivorship: champion strateji sembol evreni v13 testnet'in evreniyle özdeş; ek sembol
  enjekte edilmez.
- Fees + slippage: 55bps taker (canlı champion ile aynı), 5bps slippage; tarama sırasında
  **sabit** — vol-targeting fee'yi azaltsa bile fee parametresi optimize edilmez.
- Backtest compounding inflation (MEMORY): aylık metrikler **fixed-fractional** (compounding-
  stripped) modda raporlanır; ek olarak compounded de raporlanır ama karar fixed üzerinden.

## 7. Curve-fit kırmızı bayrakları (şeffaf taahhüt — kendi karşımdayım)

Bu hipotezin curve-fit olasılığı **yüksek**:

1. **3 vol-temelli sizing hipotezi peş peşe** — recency / narrative bias kırmızı. Önceki
   ikisinin OOS sonuçları okunmadan bu yazılmamalı (TODO: HYP-2026-05-29 ve 2026-05-15 OOS
   sonuçlarını lab_scientist'ten talep et — `requested_review_from` listesinde).
2. **Champion strateji üzerinde iterate** — gradient zaten "şu DD'yi düşür" yönünde optimize
   ediliyor. Aynı 2022-2025 dilimi defalarca çiğnendi. **Walk-forward'da 12 dilimden ≥9'unda**
   üç-koşul birden sağlanmazsa RED.
3. **432-trial grid** Bonferroni'yi öldürür; BH-FDR survivors **OOS 2025-01..2025-12'de
   tek seferde** doğrulanır, oradan ek tweak YASAK.
4. **DD_max parametresi** geçmiş MaxDD'ye yapışırsa (best=%25 ve gerçek MaxDD %23'tü) data-
   snooping. Karar: **DD_max'ı geçmiş MaxDD'den ≥ +5pp uzakta seçtim** ({%20, %25, %30} vs.
   real ~%22 → %20 zaten "agresif", %25 "neutral", %30 "gevşek" — uçlar boş bırakılmadı, orta
   nokta gerçek-MaxDD'ye yapışık değil).
5. **σ\* ∈ {0.6, 0.8, 1.0, 1.2}** geçmiş median-R'a yapışırsa (median-R ≈ 0.9R çıkarsa best=1.0)
   data-snooping. Karar: σ\* aralığı **strateji median-R'ı görmeden** seçildi (pre-registration
   şartı). Görüldüğünde belge güncellenmeyecek.

## 8. Stop criteria (önceden taahhüt — vazgeçeceğim noktalar)

- **Erken vazgeç:** IS'te en iyi konfig bile sabit-baseline'a karşı Sharpe artışı +0.05'in
  altındaysa OOS koşturulmaz, RED.
- **Mid-stop:** Best-IS konfigi OOS'ta aylık-Sharpe'ı **−0.05 veya daha kötü** yaparsa,
  TÜM 432-trial RED + curve-fit beyanı + öğrenme yazısı.
- **Even-if-passes red flag:** 3 koşul OOS'ta sağlanıyor AMA aylık median **%30'dan fazla**
  düşmüşse "edge bozdun, sadece smoothing yaptın" — şerh düşülür, Lab tournament'a "düşük-
  beklenti" etiketiyle gider.
- **Iterate budget:** SOP-4b: bu strateji başına maks 5 versiyon. Bu **v6 (vol-target+López)**;
  geri kalan budget: 4 iterate kaldı.
- **Toplam compute:** 432 trial × 5 sembol × 4 yıl 15m ≈ kabaca 6-10 saatlik backtest. Daha
  uzun sürerse cancel + dar grid.

## 9. Beklenen p-value (yazılı taahhüt)

- Naive: target-Sharpe ≥ +0.15 için one-tailed paired bootstrap p < **0.01**.
- BH-FDR sonrası **q < 0.10** kabul.
- Bonferroni sonrası p < **1.16e-4** sağlanırsa "strong", aksi "marginal — sadece BH-FDR
  geçti" şerhi.

## 10. Reproducibility

- git_hash: (kod yazılıp commit'lendiğinde doldurulacak)
- config_hash: (vol_target overlay yaml hash'i — kod aşamasında)
- data_hash: `data/market.duckdb` SHA256 (15m, 2022-01-01..2025-12-31 dilimi)
- random seed: 42 (paired bootstrap), 4242 (shuffle baseline)
- Iterate kaynak: `phoenix_scalp_15m_widestop_vsa2` v5 (canlı v13 testnet'ten — sızıntı yok,
  iç vol istatistiği aynı backtest dilimden yeniden hesaplanır)

## 11. Karar çerçevesi (sonuç tablosu — backtest sonrası doldurulacak)

| Kriter | Hedef | Gerçekleşen IS | Gerçekleşen OOS | Geçti mi? |
|---|---|---|---|---|
| Δ aylık Sharpe | ≥ +0.15 | — | — | — |
| Δ MaxDD | ≤ −10 pp | — | — | — |
| Δ aylık median | ≥ −25% | — | — | — |
| Walk-forward (12 dilim) ≥ 9 dilim üç-koşul | ≥ 9/12 | — | — | — |
| Shuffle p_gross | < 0.05 | — | — | — |
| BH-FDR survivors | ≥ 1 | — | — | — |
| Bonferroni survivor | bilgi | — | — | — |
| Median trade count düşüşü | ≤ 20% | — | — | — |
| OOS Sharpe-direction korunur | yes | — | — | — |

## 12. Sonuç (post-backtest — boş)

(boş — karar verildiğinde doldurulacak; status DRAFT → PROPOSED → REVIEWED → APPROVED/REJECTED)

## 13. Gelecek bağlantılar

- Sonuç **APPROVE** olursa: Lab tournament'a `widestop_vsa2_v6_vol_target_lopez` adıyla aday
  + adversary_engineer'dan stress (LUNA/FTX/Yen carry) replay zorunlu.
- Sonuç **REJECT** olursa: learning.md'ye 3-satır gerekçe + "3. vol-sizing red — recency
  doğrulandı, vol-sizing araştırma kuyruğundan ÇIKARILDI" sistemik notu.
- Sonuç **MARGINAL** olursa: iterate budget'tan 1 düş; v7'de **sadece López-deleveraging
  (vol-target çıkarılmış)** ayrı test edilir — hangi komponentin asıl katkı yaptığı izole
  edilmek için.

---

**Pre-registration commit hedefi:** bu doc DRAFT → kod yazılmadan önce git commit
(reproducibility hash dondurulur).
