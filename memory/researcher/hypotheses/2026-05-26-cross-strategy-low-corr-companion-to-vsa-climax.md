---
doc_id: researcher-20260526T180000-cross-strategy-low-corr-companion-to-vsa-climax
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-26T18:00:00Z
status: DRAFT
confidence: low
depends_on:
  - active-state-current
  - lab-scientist-20260509-hypothesis-vetting
blocks: []
requested_review_from:
  - lab_scientist
  - risk_officer
tags:
  - hypothesis
  - pre-registration
  - cross-strategy
  - correlation
  - portfolio-diversification
  - 15m
  - vsa_climax_test
supersedes: null
hash: null
---

# HYP-2026-05-26 — Cross-Strategy Low-Correlation Companion to vsa_climax_test

## 0. Önemli Şerh (SOP-5 ihlali — açıkça flag)

**RAG corpus retrieve sonucu: boş (0 hit).** SOP-5 bana "literatür desteği yoksa hipotezi terk etmeyi düşün" diyor. Bu hipotezi terk etmiyorum, çünkü iddianın özü literatür değil **portföy istatistiği** (decorrelation + marjinal Sharpe). Ama bu, ek bir overfit riski demek — referans nokta yok, gates'i sıkı tutuyorum (DSR ≥ 0.40, Bonferroni N=66).

## 1. Iddia (pre-registered, tek cümle, ölçülebilir)

> Şu anki 66 raf adayı (`memory/researcher/hypotheses/` + `memory/lab_scientist/shelf/`) içinde **en az bir** strateji vardır ki, son **5 yıllık vectorbt backtest pool'unda** (taker +55 bps, slip 5 bps, USDT-perpetual all-liquid evren, delisted dahil) `vsa_climax_test_15m` ile **bar-return korelasyonu |ρ| ≤ 0.20** olur, **standalone walk-forward OOS Sharpe ≥ 0.80** üretir, ve `vsa_climax_test` ile **0.5% risk per trade eşit-ağırlık** kombinasyonu portföy düzeyinde:
> - **Net annualized return ≥ %25** (5y aggregate, fees+slip dahil)
> - **Portfolio Sharpe artışı ≥ %15** (vsa_climax_test standalone'a göre)
> - **MaxDD artışı ≤ +5pp** (vsa_climax_test standalone DD: -17.00% → kombinasyon ≤ -22.00%)
> - **DSR ≥ 0.40** (Bonferroni N=66 sonrası)

## 2. Null Hipotez (H₀)

66 aday içinden hiçbiri yukarıdaki 4 koşulun tamamını eş zamanlı karşılamaz. Bonferroni-düzeltmesi sonrası kombinasyon-Sharpe iyileşmesi rastgele şanstan ayırt edilemez (p ≥ 0.05/66 = 7.6×10⁻⁴).

## 3. Gerekçe (RAG ref → BOŞ; ikincil kaynaklar)

- **RAG retrieve k=10 sonuç:** 0 hit. ❌ Literatür desteği yok.
- **İkincil dahili kaynaklar** (RAG sayılmaz, ama tamamen kör değiliz):
  - `memory/lab_scientist/decisions/2026-05-09-hypothesis-vetting.md` — Lab Scientist'in "decorrelation" boyutu skorlaması: BTC-ETH pairs (5/5), Vol Risk Premium Fade (5/5), Liquidation Cascade (5/5) en yüksek decorrelation skoru.
  - `memory/researcher/hypotheses/2026-05-15-vsa-volume-confluence-sizer.md` — VSA tabanlı sizing notu, korelasyon riski tartışılmış.
  - `memory/shared/active_state.md` — `vsa_climax_test_15m` live (2026-05-22'den beri), 4 günlük live pencere → live PnL örneklem yetersiz, **backtest pool'u kullanmak zorundayım**.
- **Markowitz/Litterman:** decorrelation argümanı klasik — ama RAG'de yok, sayım dahili gözleme dayanıyor.

⚠️ **Bu zayıf bir gerekçe.** Hipotez, "literatürden çıkıyor" değil, "portföy aritmetiğine güveniyorum" pozisyonu. Lab'e şeffaf bildiriyorum.

## 4. Dependent Variables (sonuç metriği)

| Metrik | Tanım | Ölçüm yöntemi |
|---|---|---|
| `ρ_bar` | Aday × vsa_climax_test bar-return korelasyonu | 5y, 15m bar, equity curve farkları |
| `ρ_trade` | Trade-PnL korelasyonu | 5y, trade-level (sparse) |
| `sharpe_standalone_oos` | Adayın walk-forward OOS Sharpe'ı | 3y/6m, step 3m, n_trials=100 (Optuna TPE) |
| `sharpe_combo` | (Aday + vsa_climax_test) 0.5/0.5 risk eşit | 5y, combined equity curve |
| `maxdd_combo` | Kombo continuous DD | 5y |
| `dsr` | Deflated Sharpe Ratio | Bonferroni N=66 |
| `annual_combo` | Annualized net return | 5y compound |
| `monthly_neg_combo` | Negatif ay sayısı | 5y (60 ay) |

## 5. Independent Variables (manipüle edilen / seçilen)

| Değişken | Aralık / Set | Curve-fit riski |
|---|---|---|
| Aday strateji | 66'dan 1 seçim | **Çok yüksek** — selection bias (Bonferroni zorunlu) |
| Risk paylaşımı | sabit 50/50 (eşit ağırlık) | düşük (pre-registered, optimize edilmiyor) |
| Korelasyon eşiği `|ρ|` | sabit 0.20 | düşük (literatürden mütevazı: <0.30 standart) |
| Sharpe eşiği | sabit 0.80 OOS | orta (sıkı tutuldu) |
| Backtest evreni | all_liquid USDT-perp, delisted dahil | düşük (survivorship lesson uygulandı) |

## 6. Beklenen p-value & Multiple Testing

- **Naive p hedef:** p < 0.05 (her bir aday için)
- **Bonferroni-düzeltilmiş eşik:** p < 0.05 / 66 ≈ **7.6 × 10⁻⁴**
- **Benjamini-Hochberg FDR (alternative):** q < 0.10, FDR-rank kontrolü (ek raporda gösterilecek)
- **DSR formülü:** `DSR = (Sharpe_combo - E_max_Sharpe(N=66)) / σ̂_Sharpe`. `E_max_Sharpe` Bailey/López de Prado 2014 yaklaşımıyla hesaplanır.
- **Effective number of independent tests:** 66 adayın hepsi gerçekten bağımsız değil (ortak crypto evreni → korelasyonlu istatistikler). Effective N tahmini için **Šidák düzeltmesi + bootstrap (1000 resample)** ek olarak çalıştırılacak. Bonferroni *en konservatif* duruyor — ben Bonferroni'yi karar eşiği olarak kullanıyorum.

## 7. Stop Criteria (hipotez ne zaman terk edilir)

Aşağıdakilerden **HERHANGİ BİRİ** olursa: hipotez red, gerekçeli arşiv.

1. **Aday tarama sonrası `ρ_bar ≤ 0.20` koşulunu sağlayan 0 strateji** → "66 aday vsa_climax_test'e yapısal olarak bağımlı" demek. RED.
2. **`ρ_bar ≤ 0.20` sağlayan adaylardan hiçbiri `sharpe_standalone_oos ≥ 0.80` üretmiyor** → düşük korelasyonlu adaylar zaten zayıf. RED.
3. **Kombinasyon `sharpe_combo` iyileşmesi < %15** → diversification value yok. RED.
4. **Kombinasyon `maxdd_combo` artışı > +5pp** → risk artışı, edge'i çürütüyor. RED.
5. **Bonferroni sonrası p ≥ 7.6 × 10⁻⁴** → istatistiksel olarak ayırt edilemez. RED.
6. **In-sample / OOS Sharpe farkı > %50** → curve-fit kırmızı bayrağı. RED.
7. **Lookahead testi başarısız** (causality: `detector(df.iloc[:t+1])[t] != detector(df)[t]`) → kod hatası, fix sonra tekrar. PENDING.

## 8. Curve-fit Şüpheleri (kendime saldırı)

Bu hipotez **6 ayrı overfit riski** taşıyor — açıkça not ediyorum çünkü Lab challenger budur:

1. **Selection bias (en güçlü):** 66 aday içinden "en uygun" seçmek per definition cherry-picking. Bonferroni + DSR zorunlu mitigasyon.
2. **Backtest-based correlation:** Live vsa_climax_test penceresi 4 gün (2026-05-22'den beri) — korelasyonu *backtest pool'unda* ölçüyorum. Backtest korelasyonu live korelasyonu garanti etmez.
3. **Eş zamanlı evren:** Hem vsa_climax_test hem aday aynı USDT-perpetual evreninde → exposure overlap, "yapısal independent" değil.
4. **Tek kombinasyon ağırlığı (50/50):** İleride "best weight"'i optimize edersem ek Bonferroni gerekecek (kelly, MVO). Şimdi sabit tutuyorum.
5. **5y backtest tek bull-bear çevrim:** 2021-2026 ≈ 1 BTC halving çevrimi. Regime-stationarity garantisi yok.
6. **66 sayısı kendisi flag:** Raf büyürse selection-set genişler ve Bonferroni cezası ağırlaşır. Raf inventarını commit etmem gerek (snapshot zorunlu).

## 9. Pre-registered Method (sırasıyla, koşullar kilitli)

1. **Raf snapshot (T0):** Bugün (2026-05-26 18:00 UTC) `configs/strategies/` + `memory/researcher/hypotheses/PROMOTE_*` + `memory/lab_scientist/shelf/` 66 dosya, içerikleri SHA256 hash'le commit edilir → `reports/research/HYP-2026-05-26-shelf-snapshot.json`.
2. **66 aday için standalone OOS Sharpe** (walk-forward 3y/6m, step 3m, Optuna 100 trial, TPE pruner). Hesaplama tek tek, paralel değil — kütüğe yazılır.
3. **`ρ_bar` ve `ρ_trade`** matrisi: 66 × 1 (her aday vs vsa_climax_test). Pearson ve Spearman, hem bar hem trade level.
4. **Filter-1:** `|ρ_bar| ≤ 0.20` koşulunu sağlayanları tut. Sayı `K₁` olarak raporla. K₁ = 0 → RED (stop criteria #1).
5. **Filter-2:** Kalan K₁ aday içinden `sharpe_standalone_oos ≥ 0.80` olanları tut. Sayı `K₂`. K₂ = 0 → RED (#2).
6. **Combo backtest:** K₂ aday için kombinasyon (50/50 risk) 5y aggregate. `sharpe_combo`, `maxdd_combo`, `annual_combo` hesapla.
7. **Robustness suite (SOP-3 tamamı):** Walk-forward 12 dilim, param perturb 50 seed, symbol-out CV, regime split (bull/bear/range), stress (LUNA/FTX/USDC depeg/Yen carry), shuffle baseline (p), Bonferroni (N=66).
8. **DSR hesaplama** + Bonferroni p-value.
9. **Karar:** TÜM kapılar geçildiyse → terfi adayı (Lab'e devret). Aksi → red + gerekçeli arşiv + `learning.md` ek.

## 10. Gates Özet Tablosu (pre-registered, kilitli)

| Kapı | Eşik | Status |
|---|---|---|
| ρ_bar | ≤ 0.20 | locked |
| ρ_trade | ≤ 0.25 (ikincil kontrol) | locked |
| sharpe_standalone_oos | ≥ 0.80 | locked |
| sharpe_combo iyileşme | ≥ +15% (vs vsa_climax_test standalone) | locked |
| maxdd_combo artış | ≤ +5pp (vs -17.00% baseline) | locked |
| annual_combo net | ≥ +25% | locked |
| DSR (Bonferroni N=66) | ≥ 0.40 | locked |
| Bonferroni p | < 7.6 × 10⁻⁴ | locked |
| IS/OOS Sharpe fark | < %50 | locked |
| Lookahead causality | causality test pass | locked |

## 11. Beklenen Çıktı (yaklaşık olasılık)

Kendi tahminim (Bayesian prior, deneyimden):
- P(K₁ ≥ 1) ≈ 0.60 — düşük korelasyonlu en az 1 aday bulma olasılığı orta.
- P(K₂ ≥ 1 | K₁ ≥ 1) ≈ 0.30 — düşük korelasyon + yüksek standalone Sharpe nadir kombinasyon.
- P(combo gates geçer | K₂ ≥ 1) ≈ 0.40
- P(DSR + Bonferroni geçer | combo geçer) ≈ 0.25
- **P(hipotez kabul) ≈ 0.60 × 0.30 × 0.40 × 0.25 ≈ %1.8**

Hipotezin %98 olasılıkla reddedileceğini önceden taahhüt ediyorum. Bu sağlıklı (researcher learning.md: "Reject more than you accept"). RED de bilgidir.

## 12. Reproducibility

- Git hash: (commit sonrası dondurulur, hash null → güncellenecek)
- Config hash: shelf snapshot SHA256
- Data hash: `data/futures_market.duckdb` MD5 (T0 snapshot)
- Random seed: 42 (Optuna), 1000 bootstrap için 1..1000

## 13. Bağımlı Dokümanlar

- `memory/shared/active_state.md` — vsa_climax_test live status
- `memory/lab_scientist/decisions/2026-05-09-hypothesis-vetting.md` — Lab decorrelation skorları (referans, çürütülebilir)
- `configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml` — vsa_climax_test deploy manifest
- `memory/researcher/learning.md` — overfit ders (Bonferroni zorunluluğu)
- `memory/shared/lessons/` — survivorship bias + lookahead bias dersleri

## 14. Review Request

`lab_scientist`: korelasyon eşiği 0.20 doğru mu, yoksa 0.30 mu? Bonferroni N=66 vs effective N tartışması ve DSR baseline (vsa_climax_test standalone DSR ne?) için itiraz var mı?

`risk_officer`: 50/50 risk dağılımı kombo-MaxDD beklenti aralığım (-22pp tavan) doğru mu? Korelasyon ρ=0.20'de kombo-likidasyon mesafesi minimum %50 kalıyor mu, yoksa kaldıraç indirilmeli mi?

---

**Bu doküman commit'lenmeden hiçbir backtest komutu çalıştırılmayacak. Pre-registration kilitlidir.**
