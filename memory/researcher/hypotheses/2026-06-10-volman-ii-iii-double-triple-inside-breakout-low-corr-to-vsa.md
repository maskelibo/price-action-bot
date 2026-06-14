---
doc_id: researcher-20260610T120000-volman-ii-iii-double-triple-inside-breakout-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-10T12:00:00Z
status: DRAFT
confidence: low
depends_on:
  - shared-lessons-overfitting
  - shared-lessons-survivorship
  - shared-lessons-lookahead
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, cross-strategy, inside-bar, volman, ii, iii, low-correlation, vsa-orthogonal, curve-fit-watch]
supersedes: null
hash: null
---

# Hipotez — Volman ii / iii (Double/Triple Inside Bar) Breakout, vsa_climax_test'e Düşük Korelasyonlu Aday

## 0. Bağlam (neden başka bir cross-strategy hipotezi?)

Aktif champion **vsa_climax_test** hacim-spike + bar-exhaustion mekaniği üzerine kurulu (volume-z ≥ k, geniş gövde, kapanış ekstrem). Portföy diversity'sini artırmak için VSA ile **mekanik olarak ortogonal** (hacim bağımsız, fiyat-yapısı tabanlı) bir aday arıyoruz.

Son 7 günde denenen low-corr-to-vsa adayları (Donchian-20, Marubozu, BOS-3bar, Mat Hold, ATR-k breakout, Brooks H2/L2, MA50/200, Grimes anti-climax, Equal-highs sweep): hepsi tek-bar veya breakout-only. **Henüz denenmemiş açı:** *consolidation-then-break* — Volman'ın "ii" (double inside bar) ve "iii" (triple inside bar) DD setup'ı. Bulkowski tek inside bar'ı zayıf (%54 win, rank 78/103) bulurken Volman çoklu inside bar'ı squeeze + breakout mekaniği olarak güçlü buluyor. Bu bilgi geriliminin kendisi curve-fit riskini taşır (aşağıda).

## 1. Iddia (pre-registered, ölçülebilir)

> **1D timeframe'de, USDT-perpetual likit evren (≥ 50 sembol, survivorship-corrected, 2022-01-01 → 2025-12-31), Volman ii/iii kalıbının (ardışık 2 veya 3 inside bar, her biri bir öncekinin range'i içinde) breakout entry'si — kırılım barının kapanışında karar, t+1 open'ta giriş, range yüksekliğinin 1.0×'i SL, 2.0× range TP — fee 7.5 bps taker / -1 bp maker + 5 bps slippage altında aşağıdaki üç eşiği aynı anda sağlar:**
>
> - **OOS annualized net return** > **%35** (in-sample %50 hedefi, OOS düşüş kabul)
> - **OOS Sharpe** > **0.9** (in-sample %30 düşüşe izin)
> - **OOS MaxDD (equity-base)** < **%28** ([[backtest-compounding-inflation]] dersine uygun, sabit-fraksiyon; cumulative-pnl base değil)
> - **vsa_climax_test ile günlük getiri korelasyonu** | ρ_pearson | < **0.25** (rolling 90d, OOS dönemde ortalama)

Bu **dört eşiğin tümü** aynı anda geçilmezse hipotez reddedilir. Üçünden birini ıskalamak da reddir.

## 2. Null Hipotez

> Volman ii/iii breakout'unun OOS net Sharpe'ı **0**'a istatistiksel olarak ayırt edilemez (shuffle baseline t-testinde p > 0.05). VEYA vsa_climax_test ile korelasyon ≥ 0.25 → "aslında aynı pivot anlarını yakalıyor, sadece farklı bir ad takılmış."

## 3. Gerekçe (RAG referansları — eleştirel okuma)

- **[#2 Bulkowski candlestick_statistics]:** "Tek inside bar zayıf (%54 breakout win, rank 78/103). Ancak **'ii' (double inside) veya 'iii' (triple inside) breakout daha güçlü**. Volman'ın DD setup'ı buradan türer." — **Kritik uyarı:** Bulkowski'nin tek-inside istatistiği equity için; crypto'da volatilite profilliği tamamen farklı. Volman'ın "daha güçlü" iddiasının arkasında sayısal benchmark yok, kalitatif gözlem. Bu **birinci curve-fit kırmızı bayrağı**.
- **[#1 Lopez de Prado overfitting kriterleri]:** "IS Sharpe > 3·OOS Sharpe → red." Volman setup'ı çoklu serbest parametreli (ardışık inside sayısı 2 vs 3, breakout yönü filtresi, range tanımı). FDR/Bonferroni hassas. Bu hipotezi yazarken **maks 4 Optuna parametre** ile sınırlandıracağız (n_consecutive ∈ {2,3}, sl_range_mult ∈ [0.75, 1.5], tp_range_mult ∈ [1.5, 3.0], min_range_atr ∈ [0.3, 0.8]).
- **[#6 market_structure_order_flow] (BOS/CHoCH high-feasibility):** Konsolidasyon-sonrası-yapı kırılımı kripto 1D'de "Yüksek mekanik çalışabilirlik" listesinde. ii/iii buna yapısal olarak benzer ama VSA'dan farklı (volume bağımsız).
- **[#10 Bulkowski mat hold]:** Konsolidasyon-sonrası-momentum kalıbı (%74 continuation, rank 10/103). Daha güçlü stats ama zaten dün (2026-06-08) test edildi → red. Bu, ii/iii'ün de aynı kaderi paylaşma riskini gündeme getirir (sister-pattern risk).

## 4. Dependent Variables (ölçülecek metrikler)

| Metrik | Ölçüm yeri | Hedef |
|---|---|---|
| Annualized net return (OOS) | walk-forward concat | > %35 |
| OOS Sharpe | walk-forward concat | > 0.9 |
| OOS MaxDD (equity-base, sabit-fraksiyon %1/trade) | walk-forward concat | < %28 |
| Profit factor (OOS) | walk-forward concat | > 1.3 |
| Win rate | OOS | bilgi amaçlı, eşik yok |
| Trade count (3y) | OOS | > 200 (istatistik için zorunlu) |
| ρ_pearson vs vsa_climax_test (90d rolling, OOS) | walk-forward | \|ρ\| < 0.25 |
| Shuffle baseline p-value (returns shuffle, 1000 iter) | OOS | < 0.05 |
| Bonferroni-corrected p (4 trial * 1 grid) | OOS | < 0.05 |

## 5. Independent Variables (Optuna search space — dar tutuldu, anti-curve-fit)

| Parametre | Tip | Aralık | Adım | Kısıtlama gerekçesi |
|---|---|---|---|---|
| `n_consecutive_inside` | int | {2, 3} | 1 | Volman'ın orijinal tanımı |
| `sl_range_mult` | float | [0.75, 1.5] | 0.25 | 4 değer — over-fit'i kısıtla |
| `tp_range_mult` | float | [1.5, 3.0] | 0.5 | 4 değer |
| `min_range_atr` | float | [0.3, 0.8] | 0.1 | 6 değer — range'in min ATR'ye oranı (çok dar inside'ları filtrele) |

**Toplam combinations:** 2 × 4 × 4 × 6 = **192 trial**. Bonferroni faktörü = 192. Bu nedenle **hedef p-value < 0.05 / 192 ≈ 0.00026**. Bu eşik geçilmezse FDR (Benjamini-Hochberg q < 0.10) kontrolü ek olarak uygulanacak.

## 6. Beklenen p-value

- **Pre-registration tahmini:** p ≈ 0.01 (shuffle baseline'a karşı). Eğer p < 0.001 çıkarsa şüphe artar (data-snooping veya leak).
- **Bonferroni eşiği:** p < 0.00026.
- **Eğer ham p < 0.05 ama Bonferroni sonrası > 0.00026 → REDDET** (ml_50_200 gibi).

## 7. Stop Criteria (early-abort)

Hipotez aşağıdaki herhangi biri olursa **canlı backtest sırasında durdurulur**:
1. In-sample Sharpe **< 0.4** (literatür "güçlü" diyor ama crypto'da temel eşik tutmuyor → terk).
2. In-sample trade sayısı 3y'de **< 100** (sinyal çok seyrek, istatistik kuramaz).
3. ρ vs vsa_climax_test (in-sample) **> 0.5** (cross-strategy hipotezinin temel motivasyonu çöker).
4. Best params'ın **biri** Optuna search space sınırında (örn. `sl_range_mult = 1.5` veya `min_range_atr = 0.3`) → grid'i genişletmeyi düşünür, yoksa terk.
5. Walk-forward dilimlerinin **%40+'sı** negatif Sharpe → red (regime-dependent, deploy etme).

## 8. Curve-Fit Risk Tablosu (kendime karşı dürüstlük)

| Risk kaynağı | Ciddiyet | Hafifletme |
|---|---|---|
| Volman'ın "ii/iii güçlü" iddiası kalitatif, sayısal benchmark yok | **YÜKSEK** | Shuffle baseline + Bonferroni zorunlu |
| Sister-pattern (mat hold) zaten reddedildi → ii/iii'ün de aynı kaderi paylaşma riski | **ORTA** | Mat hold'un red gerekçesini öncelikli yorumla |
| Inside bar tanımı parametrik (range filter, ATR filter) → many hyperparameter | **YÜKSEK** | Search space dar tutuldu (192 trial), Bonferroni 192 |
| Survivorship: delistlenmiş semboller dahil mi? | **YÜKSEK** | [[shared-lessons-survivorship]] uyarınca historical universe MUST |
| Lookahead: range hesabı t kapandığında bitiyor mu? | **ORTA** | `tests/test_lookahead.py::test_iii_breakout_causality` zorunlu |
| Stress periods (LUNA, FTX, Yen carry, BTC ATH 2024-03): bunlarda davranış? | **YÜKSEK** | Robustness SOP-3 #6 ayrı tablo |
| **Çoklu cross-strategy hipotezi (9 günde 10 deneme) → p-hacking riski** | **KRİTİK** | Bu hipotez **bu seri içinde 10. sırada**, Lab'e teslim ederken family-wise error rate (FWER) Lab'in görmesi gereken bir uyarı olacak. Researcher olarak ben de bu 10. hipotezde **ekstra şüpheci** kalacağım. |

## 9. Reproducibility Anchors

- Git hash: backtest çalıştırılırken HEAD commit kaydedilir.
- Config hash: `configs/research/2026-06-10-volman-ii-iii.yaml` SHA256.
- Data hash: `data/ohlcv/1d/*.parquet` SHA256 manifest.
- Random seed: 42 (Optuna sampler) — ek olarak 7 farklı seed ile re-run, ortalama OOS Sharpe raporlanır.

## 10. Karar Çerçevesi (post-backtest)

- **Tüm dependent eşikler ✓ + tüm robustness SOP-3 ✓ + Bonferroni p < 0.00026 + ρ vs vsa < 0.25 + curve-fit bayrak yok →** Lab tournament adayı, manifest hazırlanır.
- **Eşiklerin biri ✗ ama ROI pozitif aylık (örn. yıllık %20, MaxDD %35) →** [[SOP-4b iterate-on-promising-edge]] (v2: risk reduction; v3: confluence filter). Reddetmek YASAK.
- **OOS net return < 0 veya p > 0.05 →** gerekçeli red, `learning.md`'ye 3 satır.

## 11. Beklenen Süre

- Backtest engine + walk-forward: ~2-3 saat compute
- Robustness suite (param perturb, symbol-out CV, regime split, stress periods, shuffle baseline): ~6-8 saat
- Toplam: ≤ 12 saat, sonuç raporu `reports/research/volman-ii-iii-2026-06-10.html`

## 12. Lab'e Teslim Notu (önceden)

> Lab, bu hipotez 2026-06-04'ten beri 10. cross-strategy "low-corr-to-vsa" denememizdir. Family-wise error rate (FWER) artık ciddi seviyede. Bu hipotez gate'i geçse bile, **tournament'a alırken bu seriden geçen önceki adaylarla (varsa) birlikte yeni bir FDR düzeltmesi yap.** Tek başına Bonferroni ≠ multi-hypothesis program seviyesinde anlamlılık.

---

**Pre-registration commit timestamp: 2026-06-10T12:00:00Z** (kod yazımından önce).

**Sonraki adım:** `git add memory/researcher/hypotheses/2026-06-10-volman-ii-iii-*.md && git commit -m "pre-register: volman ii/iii cross-strategy hypothesis"` — hash dondur, sonra `backtest/engine.py` invoke.
