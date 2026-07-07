---
doc_id: researcher-20260622T090000-chan-halflife-symbol-filter-on-frozen-champion
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-22T09:00:00Z
status: DRAFT
confidence: med
depends_on:
  - researcher-20260615T000000-chan-halflife-sharpe-scaling-meta-validation-crypto
  - researcher-20260614T000000-chan-halflife-filtered-climax-fade-1d
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, chan, halflife, symbol_filter, frozen_champion, falsification_test, no_param_sweep, family_bonferroni]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-06-22-chan-halflife-symbol-filter-on-frozen-champion

## 1. Pre-Registration

### 1.1 İddia (ölçülebilir, tek cümle)

> **2023-01-01 → 2026-05-31 dilimi (3y 5m), USDT-perpetual likit evren (delisting dahil, N≥40 sembol), `vsa_climax_test` champion'ının CANLIDAKI EXACT FROZEN CONFIG'i ile (sl=1.25 ATR, tp=2.0 R, risk=0.0030 — `configs/risk_phoenix_scalp_15m.yaml`'dan kopya, hiçbir parametre sweep'lenmez), sembol evrenine tek bir Chan-half-life ön-filtresi uygulandığında:**
>
> **Filtre:** Her sembolün 180-bar rolling OU half-life'ı (close-to-close log returns üzerinde, Ornstein-Uhlenbeck MLE) son 30 bardaki **medyan ∈ [3, 14] gün** olan semboller "tradeable mean-reversion zone" sayılır. Chan'ın 1-60 gün aralığının alt üçtebiri (RAG #5: Sharpe ∝ 1/√half_life → daha kısa half-life daha yüksek Sharpe ⇒ alt çeyrek seçilir).
>
> Aşağıdaki dört iddianın **TAMAMI** birlikte tutmazsa hipotez REDDEDİLİR:
>
> 1. **Sharpe lift:** Filtrelenmiş evrenin trade-ağırlıklı ortalama Sharpe'ı (annualized) ≥ **1.30 ×** filtre-öncesi ortalama (lift gate)
> 2. **Yön (Chan'ın iddiası):** Sembol bazında per-symbol Sharpe vs (1/√half_life) için Spearman ρ ≥ **+0.35**, p < 0.01 **family-Bonferroni adjusted (α_adj = 0.05 / 210 = 0.000238)** — 210 = `ls memory/researcher/hypotheses/2026-06-*.md | wc -l` (bu hipotez ailesinin Haziran trial sayısı)
> 3. **DSR (Lopez):** Filtrelenmiş evren toplam DSR ≥ **0.60** (RAG #9: rastlantı eşiği)
> 4. **Sample size:** Filtrelenmiş sembol sayısı ≥ **12** ve filtrelenmiş trade sayısı ≥ **150**

### 1.2 Null Hipotez (H0)

> Half-life filtresi Sharpe lift'i ≤ 1.0 × üretir (yani işe yaramaz veya kötüler), VEYA Spearman ρ ≤ 0 (Chan'ın iddiasının tersi), VEYA DSR < 0.5. Bu durumda Chan'ın kripto-perp evreninde uygulanabilir olmadığı kabul edilir.

### 1.3 Gerekçe — RAG Referansları

- **[Chan, "Algorithmic Trading" ch. mean-reversion / half-life]** (RAG #5): "Mean-reversion stratejisinin Sharpe'ı half-life'ın square root'una ters orantılıdır. Half-life 5 gün olan bir çift, half-life 30 gün olandan ~2.4× daha yüksek Sharpe verir, diğer her şey eşit." — **Bu hipotezin direkt formal-testi.** "1-60 gün tradeable" → [3,14] alt çeyrek seçimi a priori, post-hoc değil.
- **[Lopez de Prado — DSR]** (RAG #9): Trial sayısı şişiren ailede DSR'ye geçiş zorunlu — burada family Bonferroni (n=210) + DSR > 0.6 çift kalkan.
- **[Grimes — over-leverage]** (RAG #4): "İyi sistemleri kötü performans gösterir hale getiren 1 numaralı sebep." → Risk %0.30/trade sabit, kaldıraç tavanı 3x — config frozen.

### 1.4 Curve-Fit / Overfit Şüphesi (ZORUNLU — kendi hipotezimi suçluyorum)

**Bu hipotezi yazarken şüphe etmem gereken noktalar:**

1. **Family-wide p-hacking riski (KIRMIZI BAYRAK):** `memory/researcher/hypotheses/` altında Haziran'da 206 hipotez var, bunların ≥10'u doğrudan Grimes-Anti / Chan-halflife / climax-fade kesişiminde. Tek başına α=0.05 ile test edersem **beklenen false positive ~10.3**. Bu yüzden Bonferroni n=210 zorunlu (α_adj = 0.000238).
2. **Filtre parametresi (3, 14) seçildi — neden 2-10 veya 5-20 değil?** Çünkü 2026-06-14 hipotezinde `halflife_band` `{[2,10],[3,14],[4,18],[5,20]}` 4-noktalı sweep'lendi (henüz sonuç red gibi). [3,14] orta kırpma + Chan alt-üçtebir gerekçesi (1/3 × 60 = 20 üst sınır, ama 14'e indirildi çünkü Chan "kısa daha iyi" diyor). **Bu da ÖNCEDEN denenen bir nokta** → meta-overfit riski var. Bu yüzden lift gate **1.30×** (sıradan değil yüksek) seçildi: marjinal bir gelişme bile reddedilir.
3. **Frozen champion ile test ediliyor — ama champion 2026-06-11 testnet'te canlı, training dilimine sızıntı OLMAYAN bir filtreleme şart.** Half-life her bar **rolling** hesaplanır, filtre **t-1'de bilinen** veri ile uygulanır (lookahead'siz). Test edilecek: `tests/test_lookahead.py::test_halflife_filter_causality`.
4. **Sembol evreni kompozisyonu drift'i:** [3,14] filtre çoğu zaman aynı 8-10 sembolü seçebilir (örn. SOL, XRP, DOGE) → reel filtre yok, sadece sembol seçimi. Robustness suite'te **symbol-out CV** zorunlu (her seçileni tek tek dışarıda bırak → ortalama Sharpe %30'dan fazla düşmemeli).
5. **OU MLE half-life numerik:** Negatif AR(1) coef → matematiksel olarak undefined half-life; bu noktalarda sembol filtre dışı tutulur (NaN = HAYIR, asla "düzelt" deme).

### 1.5 Pre-Registered Metrikler

**Birincil:**
- `sharpe_lift_ratio` = (Sharpe_filtered_mean / Sharpe_unfiltered_mean), hedef ≥ **1.30**
- `spearman_rho_sharpe_vs_inv_sqrt_hl`, hedef ≥ **+0.35**, p < **0.000238** (Bonferroni adj)
- `dsr_filtered`, hedef ≥ **0.60**

**İkincil (raporlanır ama gate değil):**
- Filtered net annual return
- Filtered MaxDD
- Filtered trade count
- Filtered symbol count (distinct)
- Symbol selection drift over time (filtre kararlılığı — Jaccard sim 90d windows)

### 1.6 Independent Variables (kasıtlı OLARAK MİNİMUM)

- `halflife_lookback_bars`: **180** (sabit, sweep YOK)
- `halflife_band_days`: **[3, 14]** (sabit, sweep YOK)
- `halflife_method`: **OU MLE on log returns** (sabit; AR(1) ya da Ornstein-Uhlenbeck regression — RAG #5 standart)
- `apply_at`: **t-1 close** (lookahead-safe, sabit)
- Strateji parametreleri: HEPSİ FROZEN (champion config'i kopyalanır, hiçbir parametre değiştirilmez).

→ **Toplam optimize edilen parametre sayısı: 0.** Sweep YOK. Tek bir koşum, tek bir sonuç.

### 1.7 Beklenen p-value

- Tek başına: < 0.01 hedef
- Bonferroni n=210: **< 0.000238 zorunlu** (geçemezse otomatik red)

### 1.8 Stop Criteria (her biri için TERK et)

| Bayrak | Eşik | Davranış |
|---|---|---|
| Lift ratio | < 1.00 | RED — Chan filtresi zarar veriyor |
| Lift ratio | 1.00–1.30 | RED — gelişme var ama gate altı; "weak signal, no ship" |
| Spearman ρ | < 0 | RED — Chan'ın iddiasının tersi → teori yanlış (en güçlü falsifikasyon) |
| Spearman ρ | 0 – 0.35 | RED — yön doğru ama anlamsız |
| Spearman p (Bonferroni-adj) | > 0.000238 | RED — istatistiksel anlamsız |
| DSR | < 0.60 | RED — trial inflation sonrası rastlantı |
| Filtered symbol count | < 12 | RED — sample size yetersiz, sonuç güvenilir değil |
| Symbol-out CV ortalama Sharpe düşüş | > %30 | RED — sonuç 1-2 sembole kilitli (genelleme yok) |
| In-sample / Out-of-sample Sharpe oranı | < 0.5 | RED — overfit |
| `tests/test_lookahead.py::test_halflife_filter_causality` | FAIL | RED — lookahead sızıntısı |

### 1.9 Robustness Suite (SOP-3 zorunlu, hepsi koşmalı)

1. Walk-forward (3y/6m, step 3m)
2. Symbol-out CV — her seçileni tek tek bırak
3. Regime split (bull/bear/range) — en az 2'sinde lift ≥ 1.20
4. Stress dönemleri: 2023-03 (USDC depeg), 2024-08 (Yen carry) — yıkıcı kayıp yok
5. Shuffle baseline — returns shuffle p < 0.05
6. Lookahead causality test (zorunlu)
7. Half-life filtre kararlılığı (Jaccard 90d sembol overlap)

### 1.10 Karar Patikası (SOP-4)

- **Tüm gate ✓ + tüm robustness ✓** → Lab tournament adayı (`vsa_climax_test_v2_halflife_filtered`)
- **Lift ≥ 1.0 ama gate altı** → SOP-4b iterate YAPILMAZ (bu zaten frozen-champion testi, iterate başka hipotez konusu); ANCAK pozitif lift varsa **`learning.md`'ye not + Curator'a sembol-rotation heuristik önerisi**
- **Lift < 1.0 veya ρ ≤ 0** → RED, "Chan'ın kripto-perp'te uygulanamadığı" 7. kanıt; aile-konsolide ADR yazılır ve Chan-half-life dalı **kapatılır** (yeni hipotez açılmaz, 90 gün moratorium)

---

## 2. Sonuçlar Bölümü (boş — kod çalışmadan doldurulmaz)

> Pre-registration commit hash dondurulduktan sonra hipotez immutable. Sonuçlar `memory/researcher/backtest_results/2026-06-22-chan-halflife-symbol-filter-on-frozen-champion.json` dosyasına yazılır; bu dosya append-only ve hash-locked.

## 3. Beklenen Family Etkisi

Bu hipotez ÖZELLİKLE Chan-half-life dalını kapatmak için tasarlandı:
- **POZİTİF sonuç** → Chan filtresi production'a Curator katmanı olarak girer (1 küçük config değişikliği, hiçbir strateji parametresi dokunulmaz)
- **NEGATİF sonuç** → Aile genelinde "Chan kripto-perp'te işe yaramaz" sonucu kabul, 90 gün moratorium → araştırma zamanı diğer dallara (Volman pullback, ICT FVG, Wyckoff phase) kayar

Her iki sonuç da bilgi yoğun. Bu yüzden bu hipotez **family-closing decisive test** olarak işaretlendi.
