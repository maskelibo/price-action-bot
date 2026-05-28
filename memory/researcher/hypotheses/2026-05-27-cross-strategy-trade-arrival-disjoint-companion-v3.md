---
doc_id: researcher-20260527T140000-cross-strategy-trade-arrival-disjoint-companion-v3
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-27T14:00:00Z
status: DRAFT
confidence: low
depends_on:
  - researcher-20260526T180000-cross-strategy-low-corr-companion-to-vsa-climax
  - researcher-20260526T214500-cross-strategy-tail-corr-companion-v2
  - active-state-current
blocks: []
requested_review_from:
  - lab_scientist
  - risk_officer
tags:
  - hypothesis
  - pre-registration
  - cross-strategy
  - trade-arrival-decorrelation
  - jaccard
  - portfolio-diversification
  - 15m
  - vsa_climax_test
  - sibling-v3
supersedes: null
hash: null
---

# HYP-2026-05-27-v3 — Trade-Arrival Disjoint Companion to vsa_climax_test

## 0. Bağlam ve Farklılaşma (sibling-v3 gerekçesi)

Aynı seed altında iki kardeş hipotez 26 Mayıs'ta pre-register'landı:

- **v1** (`researcher-20260526T180000-...`): unconditional bar-return korelasyonu `|ρ_bar| ≤ 0.20`.
- **v2** (`researcher-20260526T214500-...tail-corr-companion-v2`): vsa drawdown pencerelerinde conditional `ρ_dd ≤ 0.30`.

v1'in (kısıtlı 6-strateji örneklem üzerinde) ilk koşumu: bütün çiftlerde `|ρ_bar| < 0.10` çıktı — yani unconditional ρ pratikte kısıtlayıcı bir filtre değil. Bottleneck `sharpe_standalone` + combo gates. Bu, **decorrelation seçim ekseninde başka bir boyutun denenmesi gerektiği** işareti.

v3'ün **farkı: equity-curve değil sinyal-zamanlama**. İki strateji bar-bazlı return'leri "ortalamada decorrelate" görünse bile **aynı barlarda fire ediyorlarsa** execution-risk (margin churn, slip yığılması, kapasite sınırı) ve canlıda örtük korelasyon yaratırlar. v3 bunu ölçüyor:

> **Trade-arrival disjointness:** İki stratejinin "sinyal üreten bar" kümeleri arasındaki Jaccard indeksi `τ ≤ 0.10`. (Tetik barları kesişimi / birleşimi.)

**Bu üç hipotez paralel test EDİLEMEZ.** Seçim seti aynı 66 aday; XOR karar şart. Lab + CEO arbitrate. Effective N tartışması (66 vs 132 vs 198) review request'te.

## 0.1 Önemli Şerh (SOP-5 ihlali — açıkça flag)

**RAG retrieve k=10 → 0 hit.** Literatür desteği yok. Hatırladığım ikincil referanslar (RAG sayılmaz):
- López de Prado, *Advances in Financial Machine Learning* (2018), §16: "ensemble diversification ≠ sample diversification"; sinyal-arrival cluster'ları portföy gerçek-N'ini düşürür.
- Bailey-LdP 2014 DSR — selection bias düzeltmesi (v1/v2 ile ortak).
Hipotez literatürden değil **execution-risk + portföy aritmetiği** sezgisinden doğuyor. Bu zayıf bir taban; gates'i sıkı tutuyorum.

## 1. Iddia (pre-registered, tek cümle, ölçülebilir)

> Şu anki 66 raf adayı içinde **en az bir** strateji vardır ki, son **5 yıllık vectorbt backtest pool'unda** (taker +55 bps, slip 5 bps, USDT-perpetual all-liquid evren, delisted dahil), `vsa_climax_test_15m` ile **bar-fire setlerinin Jaccard indeksi `τ ≤ 0.10`** (yani 90%+ disjoint trade-arrival), **standalone walk-forward OOS Sharpe ≥ 0.80** üretir, **fire-aktif barlarda return-conditional ρ `ρ_active` ≤ 0.25** ve `vsa_climax_test` ile **50/50 risk eşit-ağırlık** kombinasyonunda portföy düzeyinde:
> - **Net annualized return ≥ %25** (5y aggregate, fees+slip dahil)
> - **Portfolio Sharpe artışı ≥ %20** (vsa_climax_test standalone'a göre — v1/v2'nin %15'inden sıkı, çünkü trade-arrival disjoint olduğunda mekanik smoothing daha güçlüdür → arttırılmış eşik daha katı bir gerçek-edge ispatı)
> - **MaxDD artışı ≤ +4pp** (vsa_climax_test standalone -17.00% → kombinasyon ≤ -21.00%)
> - **Sharpe iyileşmesinin "mechanical smoothing" payı ≤ %50** (decomposition: aşağıda §6.5)
> - **DSR ≥ 0.40** (Bonferroni N=66 sonrası)

## 2. Null Hipotez (H₀)

66 aday içinden hiçbiri yukarıdaki 5 koşulun tamamını eş zamanlı karşılamaz. Trade-arrival disjoint olan adayların ya standalone Sharpe'ı çöküktür ya da combo Sharpe iyileşmesi tamamen mechanical smoothing'den gelir (gerçek edge sıfır). Bonferroni p ≥ 7.6×10⁻⁴.

## 3. Gerekçe (RAG ref → BOŞ; ikincil)

- **RAG retrieve k=10:** 0 hit. ❌
- **Dahili gözlem:** v1 ilk koşumda 6-strateji örneklemde ortalama |ρ| ≈ 0.05; unconditional ρ çoktan düşük → "bottleneck başka yerde". Sinyal-arrival overlap ölçülmedi.
- **Execution-risk teorisi (hafıza, RAG değil):** Aynı bar'da iki sinyal → margin allocation çakışması, slippage süperpozisyonu, dead-man's switch latency üst üste binmesi. Backtest equity'sinin gizli execution maliyeti.
- **Portföy aritmetiği:** Disjoint arrival = naive equity curve "alternating contribution"; bu yalın çeşitlendirme (variance ↓) ama edge artışı garanti etmez → §6.5'te ayrıştırıyorum.

⚠️ Zayıf gerekçe. Hipotez deneysel/sezgisel; literatür referansı yok.

## 4. Dependent Variables

| Metrik | Tanım | Ölçüm |
|---|---|---|
| `τ_jaccard` | |fire_A ∩ fire_B| / |fire_A ∪ fire_B|, bar set (15m) | 5y, set ops |
| `overlap_ratio` | |fire_A ∩ fire_B| / E[fire_A ∩ fire_B] (E rastgele beklenti = N_A·N_B/T) | 5y |
| `ρ_full` | Unconditional bar-return ρ (v1 ile karşılaştırma) | 5y Pearson |
| `ρ_active` | Conditional ρ — yalnızca her iki strateji de fire-aktif olduğu barlarda | 5y, mask altında |
| `sharpe_standalone_oos` | WF OOS Sharpe | 3y/6m, step 3m, Optuna 100 trial |
| `sharpe_combo` | (Aday + vsa_climax_test) 50/50 risk | 5y |
| `sharpe_combo_mech` | Mekanik smoothing pay tahmini (§6.5) | bootstrap |
| `sharpe_combo_real` | Real edge artış payı = sharpe_combo − sharpe_combo_mech | hesaplanır |
| `maxdd_combo` | 5y continuous DD | 5y |
| `annual_combo` | Annualized net return | 5y |
| `dsr` | Deflated Sharpe (Bailey-LdP, N=66) | analytic |

## 5. Independent Variables

| Değişken | Aralık / Set | Curve-fit riski |
|---|---|---|
| Aday strateji | 66'dan 1 seçim | **Çok yüksek** (Bonferroni zorunlu) |
| Jaccard eşiği `τ` | sabit 0.10 (pre-register) | düşük — optimize edilmez |
| `ρ_active` eşiği | sabit 0.25 | orta (conditional sample küçülür) |
| Bar granülariteti | 15m sabit | düşük (deploy bar'ı eşleşiyor) |
| Risk paylaşımı | sabit 50/50 | düşük (pre-register) |
| Backtest evreni | all_liquid USDT-perp, delisted dahil | düşük (survivorship lesson uygulanmış) |

## 6. Beklenen p-value & Multiple Testing

- **Naive p hedef:** p < 0.05
- **Bonferroni N=66:** p < 7.6 × 10⁻⁴
- **Seçim-seti overlap (v1∪v2∪v3):** Üç hipotez aynı 66 aday üzerinden farklı filter'larla seçim yapıyor. Eğer Lab üçünü de tournament'a alırsa effective N = 198, eşik p < 2.5×10⁻⁴. Pre-register'da **karar kuralı XOR** (sadece bir tane terfi). XOR korunursa N=66 kalır. Lab/CEO arbitrate.
- **Šidák alternatifi:** `1 − (1−α)^(1/N)` ile karşılaştırma rapor edilecek.
- **DSR:** Bailey-LdP 2014, `E_max_Sharpe(N=66)`.
- **Pre-gate: minimum overlap sample.** `|fire_A ∩ fire_B|` < 100 ise `ρ_active` istatistik gücü yetersiz → o aday için `ρ_active` rapor edilir ama gate olarak kullanılmaz; `τ` baskın gate.

## 6.5 Mechanical Smoothing Decomposition (v3-özgün)

> **Bu adım v1/v2'de yok ve v3'ün özgün katkısı.** Trade-arrival disjoint olduğunda kombinasyon Sharpe'ı *mekanik* olarak yükselir (variance averaging via uncorrelated arrival times) — gerçek edge değil. Bunu ayrıştırmak şart, yoksa "iyileşme tamamen smoothing artefaktı" durumunu kabul etmiş oluruz.

**Yöntem:**
1. **Null bootstrap:** Aday equity curve'ünü 1000 kez **block-shuffle** (block=20 bar) → aynı return dağılımı, **rastgele zamanlama**. Her shuffle için `sharpe_combo_null` hesapla.
2. **`sharpe_combo_mech` = median(sharpe_combo_null)** — bu adayın return dağılımı + rastgele arrival ile elde edebilecek "smoothing-only" Sharpe.
3. **`sharpe_combo_real` = sharpe_combo − sharpe_combo_mech** — gerçek (arrival-timing'e bağlı) edge artışı.
4. **Gate:** `sharpe_combo_mech / sharpe_combo_improvement ≤ %50`. Yani toplam iyileşmenin en fazla yarısı smoothing'den gelebilir; gerisi gerçek edge olmalı.

Bu decomposition v1/v2'de yok çünkü onlar arrival timing'e değil, equity-curve ρ'sına odaklı. v3'ün literatürde net karşılığı bulunmuyor — eğer Lab daha temiz bir ayrıştırma metodu önerirse (örn. Hasanhodzic-Lo replication style benchmark) review request açık.

## 7. Stop Criteria (HERHANGİ BİRİ → RED)

1. **66 aday içinde `τ ≤ 0.10` sağlayan 0 strateji** → trade-arrival ortogonal aday yok. RED.
2. **Kalan adayların hiçbirinde `sharpe_standalone_oos ≥ 0.80`** → ortogonal adaylar zayıf. RED.
3. **`ρ_active > 0.25`** (overlap ≥ 100 bar olan adaylarda) → fire-aktif anlarda hâlâ korelasyon → görünüşte disjoint ama "kavgalı" portföy. RED.
4. **Kombinasyon `sharpe_combo` iyileşmesi < %20** → diversification value zayıf. RED.
5. **`sharpe_combo_mech / sharpe_combo_improvement > %50`** → iyileşme çoğunlukla mekanik smoothing artefaktı. RED. **(v3-özgün gate)**
6. **`maxdd_combo` artışı > +4pp** → risk artışı. RED.
7. **Bonferroni sonrası p ≥ 7.6×10⁻⁴** (XOR korunursa) → ayırt edilemez. RED.
8. **IS/OOS Sharpe farkı > %50** → curve-fit. RED.
9. **Lookahead causality testi FAIL** → kod hatası. PENDING.
10. **`τ_jaccard` < 0.005** (yani tamamen disjoint — neredeyse hiç kesişmiyor) → kuşkulu, çünkü aday muhtemelen vsa_climax_test'in **hiç fire etmediği rejimlerde** çalışıyor; bu rejimleri aynı evrende mi paylaşıyorlar? Sembol-rejim overlap kontrolü → fail ederse RED.

## 8. Curve-fit Şüpheleri (kendime saldırı)

1. **Selection bias:** 66 aday — v1/v2 ile aynı. Bonferroni mecbur.
2. **τ eşiği 0.10 keyfi.** Sweep yapmıyorum — pre-register kilidi. Lab challenger "neden 0.10, 0.05 değil" sorabilir → cevabım: literatür referansı yok, ben deneysel olarak "%90+ disjoint" sezgisini kullanıyorum, daha sıkı eşik conditional sample'ı yok eder.
3. **Mechanical smoothing decomposition kendisi yeni bir model.** Block-shuffle null seçimi (block=20 bar, neden 20?) keyfi. Block 20 bar = 5 saat (15m × 20), kripto autocorrelation pencereyi aşan değer; ama hassasiyet kontrolü için block ∈ {10, 20, 40} hep rapor edilecek (sweep değil, "robustness check").
4. **`ρ_active` overlap sample küçüklüğü:** Eğer N_overlap < 100, ρ_active gate'i atlatılır; bu küçük örneklem stratejileri için bir loophole. Pre-register: bu durumda τ baskın, ama post-hoc inceleme ZORUNLU (`learning.md`'ye not).
5. **50/50 ağırlık keyfi.** v1/v2 ile aynı: gelecekteki "best weight" optimize edilirse ek Bonferroni gerekir.
6. **v1/v2/v3 üçü de aynı seed → meta-overfit:** Üç farklı filtre denedik; en az bir tanesi "şans" sebebiyle geçebilir. Effective N tartışması review'da kritik. Lab kabul ederse XOR şart.
7. **Sembol-rejim overlap körlüğü:** İki strateji disjoint bar'larda fire etse de aynı sembollerde aynı rejimleri severlerse exposure tail-corr'u patlar. v2 (tail-corr) bunu adresliyor; v3 sadece zamanlama bakıyor. Bu, v3'ün **zayıf yanı** — Stop Criteria #10 ile kısmen mitigasyon.
8. **`vsa_climax_test` standalone MaxDD -17.00% varsayımı sabit** — commit öncesi verify et (Lab review request #3, v2'den miras).

## 9. Pre-registered Method

1. **T0 snapshot:** v1 ile aynı SHA256 raf snapshot. Aynı 66 aday. (Eğer raf v1-T0'dan beri değiştiyse fark loglanır; eklenen adaylar bu hipoteze dahil DEĞİL — kilitli.)
2. **vsa_climax_test fire-bar set'ini 5y backtest pool'undan çıkar.** `fire_vsa`: trade entry bar timestamp'leri kümesi.
3. **66 aday × fire-bar set:** her aday için `fire_cand`.
4. **`τ_jaccard` = |fire_vsa ∩ fire_cand| / |fire_vsa ∪ fire_cand|** hesapla. Tüm 66 için raporla.
5. **`overlap_ratio`** = `|fire_vsa ∩ fire_cand| / E[overlap]`. Sub-1 değer "rastgeleden daha az çakışma" demek.
6. **Filter-1:** `τ ≤ 0.10` AND `overlap_ratio ≤ 0.5` → K₁ aday.
7. **Filter-2:** K₁ içinden standalone WF OOS Sharpe ≥ 0.80 → K₂.
8. **`ρ_active` hesapla** (fire-aktif barlarda Pearson). K₂ içinden `ρ_active ≤ 0.25` (overlap ≥ 100) veya overlap < 100 olan → K₃.
9. **Combo backtest:** K₃ aday için 50/50 risk, 5y aggregate.
10. **Mechanical smoothing decomposition (§6.5):** block-shuffle null × 1000, `sharpe_combo_mech` ve `sharpe_combo_real` hesapla. Gate uygula.
11. **Robustness suite (SOP-3 tamamı):** WF 12 dilim, param perturb 50 seed, symbol-out CV, regime split, stress periods (LUNA/FTX/USDC/Yen), shuffle baseline, Bonferroni N=66.
12. **DSR + Bonferroni p.**
13. **Sembol-rejim overlap kontrolü** (Stop Criteria #10): aday ve vsa_climax_test'in fire-bar'larındaki ortalama BTC dominance, ATR percentile, EMA20 vs EMA50 spread → KS testi, p ≥ 0.05 ise "aynı rejim, sadece zaman farklı" → bu OK; p < 0.05 ise "farklı rejimde fire ediyorlar" → bu da OK ama Stop Criteria #10'a göre dikkatli rapor.
14. **Karar:** Tüm gates ✓ → Lab tournament aday (XOR: v1/v2/v3 sadece biri); aksi → RED + `learning.md` ek + ADR (XOR seçimi gerekçeli).

## 10. Gates Tablosu (kilitli)

| Kapı | Eşik | Status |
|---|---|---|
| τ_jaccard | ≤ 0.10 | locked |
| overlap_ratio | ≤ 0.5 | locked |
| τ_jaccard alt sınır | ≥ 0.005 (Stop #10) | locked |
| ρ_active (overlap ≥ 100) | ≤ 0.25 | locked |
| ρ_full (kontrol, gate değil) | rapor | locked |
| sharpe_standalone_oos | ≥ 0.80 | locked |
| sharpe_combo iyileşme | ≥ +20% | locked |
| sharpe_combo_mech / Δsharpe | ≤ %50 | locked **(v3-özgün)** |
| maxdd_combo artış | ≤ +4pp | locked |
| annual_combo net | ≥ +25% | locked |
| DSR (Bonferroni N=66, XOR korunur) | ≥ 0.40 | locked |
| Bonferroni p | < 7.6×10⁻⁴ | locked |
| IS/OOS Sharpe fark | < %50 | locked |
| Lookahead causality | pass | locked |
| Sembol-rejim overlap KS-p | rapor (info) | locked |

## 11. Beklenen Çıktı

Bayesian prior:
- P(τ ≤ 0.10 sağlayan ≥ 1 aday) ≈ 0.50 — trade-arrival disjoint olabilen aday çok değil; ama 66 büyük havuz.
- P(overlap_ratio ≤ 0.5 | τ ≤ 0.10) ≈ 0.70 — τ küçükse overlap_ratio de küçük olur eğilimi.
- P(K₂ ≥ 1 | K₁ ≥ 1) ≈ 0.20 — disjoint adaylar genellikle daha sığ Sharpe'a sahip (vsa_climax_test'in atladığı zamanlarda fire ediyorlar → muhtemelen daha az "premium" setup'lar).
- P(ρ_active ≤ 0.25 | K₂ ≥ 1) ≈ 0.50.
- P(combo gates + smoothing decomposition geçer | K₃ ≥ 1) ≈ 0.25 — `sharpe_combo_mech ≤ %50` gate'i en sıkı yeni gate.
- P(DSR/Bonferroni ≥ 0.40) ≈ 0.20.
- **P(kabul) ≈ 0.50 × 0.70 × 0.20 × 0.50 × 0.25 × 0.20 ≈ %0.18**

v1 (%1.8) > v2 (%0.5) > v3 (%0.18). v3'ün gates'i bilinçli olarak en sıkı (yeni smoothing-decomposition gate ekstra). Üç hipotezin de %98+ reddedilme olasılığı tahmin edilmiş; XOR seçimi pratikte "üçü de RED" durumunu da makul gösteriyor (kombine yaklaşık %96+).

## 12. Reproducibility

- Git hash: (commit sonrası dondurulur)
- Config hash: v1 ile ortak shelf snapshot SHA256
- Data hash: `data/futures_market.duckdb` MD5 (T0 snapshot, v1 ile aynı)
- Random seed: 42 (Optuna), 1..1000 (bootstrap block-shuffle), block ∈ {10, 20, 40} sensitivity
- Vsa baseline backtest: `configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml` standalone 5y aggregate (commit öncesi verify)

## 13. Bağımlı Dokümanlar

- `researcher-20260526T180000-cross-strategy-low-corr-companion-to-vsa-climax` (sibling-v1 — XOR)
- `researcher-20260526T214500-cross-strategy-tail-corr-companion-v2` (sibling-v2 — XOR)
- `memory/shared/active_state.md` — vsa_climax_test live
- `configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml` — vsa_climax_test deploy
- `memory/researcher/learning.md` — overfit ders, Bonferroni zorunlu
- `memory/shared/lessons/` — survivorship, lookahead, overfit kırmızı bayraklar

## 14. Review Request

`lab_scientist`:
1. v1 / v2 / v3 üçü XOR mu, paralel mi tournament'a alıyoruz? Üçü paralelse effective N=198, Bonferroni eşiği p < 2.5×10⁻⁴ (ben şu an N=66 varsaydım). Karar?
2. Mechanical smoothing decomposition (§6.5) block-shuffle null modeli yeterli mi, yoksa daha temiz bir benchmark (Hasanhodzic-Lo replication, ML factor model) gerekir mi?
3. `τ ≤ 0.10` eşiği makul mü? Şu ana kadar 6-strateji örneklemde Jaccard hesaplanmadı — pre-flight tahmin ister misin (50-100 random pair Jaccard dağılımı)?
4. v1 ilk koşumun 6 strateji, tam 66 değildi — bu hipotezler tam 66 üzerinde koşmadan karar verilemez. Tam tarama timeline?

`risk_officer`:
1. Trade-arrival disjoint kombo daha mı az margin churn üretir? Execution-cost simülasyonu (gerçek slippage + funding) backtest'e dahil edilmeli mi, yoksa post-promotion paper-trade pencerede mi gözlenmeli?
2. `maxdd_combo` +4pp v2'nin +3pp'sinden gevşek (çünkü iddia DD-koruması değil zamanlama). Bu makul mü?
3. Trade-arrival disjoint olduğunda **aynı anda** her iki strateji portföyü dolduramaz → daha düşük ortalama pozisyon sayısı. `max_open_positions` limiti bu kombinasyonda gevşetilebilir mi, yoksa korunsun mu?

---

**Bu doküman commit'lenmeden hiçbir backtest komutu çalıştırılmayacak. Pre-registration kilitlidir. v1 / v2 / v3 arası karar XOR olarak Lab + CEO arbitrate gerekir.**
