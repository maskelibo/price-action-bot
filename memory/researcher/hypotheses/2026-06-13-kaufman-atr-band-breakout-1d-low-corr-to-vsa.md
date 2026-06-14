---
doc_id: researcher-20260613T120000-kaufman-atr-band-breakout-1d-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-13T12:00:00Z
status: DRAFT
confidence: med
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [pre-registration, kaufman, atr-breakout, continuation, low-corr, vsa-diversifier, 1d, no-volume]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-06-13-kaufman-atr-band-breakout-1d

## 1. Seed konusu

`vsa_climax_test` (canlı, volume-spike + close-reversal mantıklı, kısa horizon reversal) ile **düşük korelasyonlu** ek bir aday — raftaki 66'dan. Aktif edge VSA-volume-ekseni olduğu için feature-seviyesinde ortogonal aday aranıyor: **volume-bağımsız, fiyat-momentum, continuation** yönlü. Bugünkü pre-registration kuyruğunda zaten yazılmış olanlar (Marubozu × 6, Mat Hold, Volman-ii, BOS, CHoCH, FVG, Equal-Highs Sweep, Brooks-FBO, AVWAP, Engulfing) tekrar edilmedi.

## 2. Iddia (versiyon 0.1, ölçülebilir)

> 1D timeframe'de, 19-sembol aktif perp havuzunda (Phoenix15m havuzu), **HTF rejim filtresi** (BTC.D 1W EMA-20 üstü = bull rejim ON, altı = bear rejim ON; range rejimde sinyal blok) altında:
>
> Kaufman ATR-band breakout sinyali — `t-1` bar close + `k × ATR(14, t-1)` seviyesi `t` barında close-üstü aşılırsa long; tersi short. Giriş `t+1` bar open (lookahead-safe stop emri modeli). Parametreler **TEK SET**:
>   - `k = 0.7` (Kaufman tipik aralık 0.5–1.0 orta noktasına yakın, parametre sweep YAPILMAYACAK)
>   - SL = giriş ∓ `1.5 × ATR(14, t-1)`
>   - TP = `2R` fixed
>   - Time-stop: 10 bar sonra exit (Kaufman'ın bar/gün-sonu kuralının uyarlaması)
>   - Min ATR filter: `ATR(14)/close > 0.02` (yüksek-vol koşulu; Kaufman'ın "low-vol day not triggered" mantığı)
>
> 2023-01-01 / 2026-06-13 walk-forward dönemi içinde:
>
> | Hedef | Eşik |
> |---|---|
> | Aylık net return (fee 7.5 bps taker + 5 bps slip dahil) | **> +%2.0** |
> | OOS Sharpe (12-fold walk-forward, 3y train / 6m test, step 3m) | **> 1.0** |
> | Trade-sıra MC MaxDD (p95, 1000 perm) | **< %22** |
> | Trade sayısı | **≥ 120** (yıllık ≥ 40) |
> | Profit factor (net) | **> 1.25** |
> | **vsa_climax_test ile trade-Jaccard** | **< 0.12** |
> | **vsa_climax_test ile aylık-return Pearson korelasyonu** | **\|ρ\| < 0.35** |

**ÜRETIR.**

## 3. Null hipotez (ne olursa çürür)

H0a: OOS Sharpe ≤ 0 (edge yok).
H0b: Shuffle-baseline returns'leri yenmedi (p ≥ 0.05).
H0c: Trade-Jaccard ≥ 0.12 VEYA aylık ρ ≥ 0.35 → diversifier değil, vsa'nın tekrarı.
H0d: Yıllık trade < 40 → istatistik anlamsız.

Bu dördünden **biri bile** kırmızıysa hipotez RED.

## 4. Gerekçe (RAG referansları)

- **[Kaufman summary RAG#5]** — "Open ± k×ATR breakout" — intraday momentum capture, win rate ~%55 küçük R ile. Bizim adaptasyonumuz: 1D'de close-baz, lookahead-safe stop emri olarak modellenmiş.
- **[Kaufman summary RAG#7]** — Donchian breakout failure mode: choppy/range piyasada whipsaw → HTF rejim filtresi (BTC.D EMA-20) zorunlu. ADX yerine BTC.D çünkü 19-sembol portföyde rejim BTC-bazlı.
- **[López de Prado summary RAG#1]** — 6 kırmızı bayrak: IS Sharpe > 3·OOS Sharpe **OLMAMALI**, parametre/örnek > 1/30 **OLMAMALI**. Bu hipoteze direkt baskı: parametre sweep yapılmayacak, tek set.
- **[Order-flow summary RAG#6]** — BOS/CHoCH yüksek skor ama zaten yazıldı. Kaufman gap-breakout structural-bağımsız, fiyat-saf momentum → feature ekseninde ortogonal.

## 5. Independent variables (FIX, sweep YOK)

| Param | Değer | Gerekçe |
|---|---|---|
| `k` (ATR çarpanı) | **0.7** | Kaufman 0.5–1.0 orta. Sweep yapmıyorum (overfit korkusu). |
| ATR window | **14** | Standart, sweep YOK. |
| SL multiplier | **1.5** | Kaufman önerisi. |
| TP multiple | **2R** | Klasik fixed-R; trailing eklenmiyor (parametre azaltma). |
| Time-stop | **10 bar** | Tek değer, sweep YOK. |
| Min `ATR/close` | **0.02** | %2 günlük volatilite tabanı; tek değer. |
| HTF rejim | BTC.D 1W EMA-20 | Bull/bear ON, range OFF. Tek tanım. |

**Toplam serbest param ≈ 7. Min trade hedefi 120 → 7/120 ≈ 0.058 < 1/30 (López eşiği).** Tek setlik politika curve-fit yüzeyini düşürüyor.

## 6. Dependent variables

- Aylık net return (medyan + ortalama)
- OOS Sharpe (12 dilim)
- Walk-forward dilim varyansı / ortalama (López #6 kırmızı bayrak)
- IS Sharpe / OOS Sharpe oranı (López #4 kırmızı bayrak — ≤ 3 olmalı)
- MaxDD (trade-sıra MC p95)
- Profit factor (net)
- Win rate
- Avg R-multiple
- **Trade-Jaccard vs vsa_climax_test**
- **Aylık-return Pearson ρ vs vsa_climax_test**
- Bull/bear/range rejim split-pozitiflik
- Stress dilim P/L (2024-08 Yen carry, 2024-03 BTC ATH, 2026 mevcut)
- Shuffle baseline p-value
- Lookahead-delay testi: entry +1 bar daha gecikir → edge ≥ %85 korunmalı (sızıntı tarama)

## 7. Beklenen p-value

- Shuffle baseline: p < 0.01 (1000 perm).
- Bonferroni: sweep YAPMADIĞIM için n_trials = 1 → düzeltme = ham p. Bu hipotezi savunulabilir kılan ana kalkan.
- Eğer ileride lab tournament'a girerse Lab DSR uygulayacak; ön hesabımda DSR > 0.5 hedef.

## 8. Stop criteria (terkedme kuralları)

| Tetik | Aksiyon |
|---|---|
| Trade sayısı < 50 (full 3 yıl) | Hipotez TERKEDİLİR — Kaufman ATR-band kripto 1D'de doğru horizon değil demek. |
| OOS Sharpe < 0.4 | Terk. |
| IS/OOS Sharpe ratio > 2.5 | Overfit suspicion — terk. |
| Lookahead-delay testi: edge < %60 korunuyor | Sızıntı suspicion — kod auditi, terk. |
| Trade-Jaccard ≥ 0.12 VEYA |ρ| ≥ 0.35 | Diversifier hedefi düştü — RED, iterate başlatmıyorum (vsa replikası işime yaramaz). |
| Best metrics tek bir rejim/sembolden geliyor (toplam P/L %60+ bir kaynaktan) | Konsantrasyon riski — terk. |

## 9. Curve-fit kırmızı bayrak ön-listesi (kendi paranoyam)

1. **k=0.7 sweet-spot olabilir.** İleride sweep yapılırsa Bonferroni'yi bozar. **POLİTİKA: Lab tournament aşamasına kadar parametre sweep YASAK.** Bu pre-registration'ı ihlal sayılır.
2. **Kaufman'ın orijinal mantığı INTRADAY.** 1D'ye taşımak adaptasyon → "literatür referansım var" iddiasını zayıflatır. Kripto 7/24 → "gün-açılış" bias yok, ama "1D bar" Coordinated Universal Time arbitrarı; Asya/EU/US seans yapısı yok. Bu OOS riskini yükseltir.
3. **Win rate ~%55 küçük R ile** — fee+slip duvarı yüksek. TP=2R asimetriyi bozarsa edge eriyebilir. Profit factor > 1.25 alt sınırını bu yüzden koydum (yüksek değil, gerçekçi).
4. **HTF BTC.D filter** post-hoc gelmiş gibi durabilir — Kaufman ADX kullanır; ben BTC.D koydum çünkü 19-sembol portföyde rejim BTC-merkezli. Bu seçim ön-bias riski → BTC.D filter'ı OFF varyantı da ayrı dilim olarak raporlanacak (DOĞRULAMA için, sweep değil).
5. **Continuation Bulkowski'de tipik %60-70**, Kaufman'ın %55 win rate'i de mütevazı. **Aylık +%2 hedefi çok mu yumuşak?** Evet, mütevazı — diversifier rolü için yeterli; champion adayı değil. Bu pre-registration'da kabul edilen rol.
6. **2023-2024 BTC genelde bull.** Walk-forward'da 2026'nın volatil dilimine ağırlık vermek için OOS dilim seçimi ASLA cherry-picked olmamalı; 12 dilim sabit grid (3y/6m, step 3m), seçim YOK.
7. **N=120 alt sınır** trade-Jaccard ölçümü için yeterli mi? Marjinal. İdeal n>200. Eğer 80-120 arasındaysa Jaccard güven aralığı geniş olacak — raporda CI verilecek.

## 10. Yöntem özeti (kod yazılmadan önce)

1. `backtest/engine.py` config: 19-sym pool, 2023-01 → 2026-06-13, fee 7.5/-1 bps, slip 5 bps, sermaye 10k, risk %1/trade.
2. Detector: vektörize, lookahead test (`tests/test_lookahead.py`) ZORUNLU geçecek.
3. Walk-forward 12 fold; per-fold metrik kaydı.
4. Robustness suite (SOP-3 tamamı):
   - WF varyans/ortalama oranı
   - Symbol-out CV (leave-1)
   - Regime split (bull/bear/range) ayrı pozitiflik
   - Stress dilim: 2024-03, 2024-08, 2026-04 düzeltmesi
   - Shuffle baseline 1000 perm
   - **Param perturbation testi: k=0.7 → 0.6/0.8 → her birinde Sharpe kaybı %25 altı olmalı.** Bu YALNIZCA robustness ölçümü; "best k" seçilmez, k=0.7 sabit kalır.
5. Cross-correlation çalıştırması: `analytics/cross_strategy_corr.py` (varsa) ya da scripts/ altında ad-hoc — vsa_climax_test bar-bazlı trade serisinden Jaccard + aylık-return ρ.
6. Lookahead-delay testi: entry +1 bar gecikir → metrik karşılaştırma.

## 11. Karar matrisi (SOP-4)

| Sonuç | Aksiyon |
|---|---|
| Tüm 7 hedef (§2) ✓ + tüm robustness ✓ | **Terfi adayı** → Lab tournament. |
| 5/7 hedef ✓ + diversifier kriteri (Jaccard, ρ) ✓ + DD/Sharpe yetersiz | **SOP-4b ITERATE**: risk_pct ↓, time-stop kısalt, regime subset. v2 ayrı pre-reg. |
| Diversifier kriteri ✗ | **RED kesin** (iterate yok, vsa replikası kapasitemize yaramaz). |
| Aylık ROI ≤ 0 | **RED kesin**, learning.md'ye 3 satır gerekçe. |
| Curve-fit bayrağı (§9-1, §9-4) tetiklendi | **RED**, ders yaz. |

## 12. Reproducibility

- git_hash: pending (kod yazıldıktan sonra commit'lenecek)
- config_hash: pending
- data_hash: pending (data/duckdb snapshot tag)
- random_seed: 42 (sabit, MC dahil; lab tournament'ta farklı seed'lerle re-run)

## 13. Sonraki adımlar

1. Bu pre-registration commit'lenir → hipotez dondurulur.
2. `requested_review_from`: lab_scientist (gate kontrolü), risk_officer (DD/sizing), adversary_engineer (red-team — özellikle §9 curve-fit bayraklarını döv).
3. Onay sonrası kod (detector + backtest config) yazılır.
4. Walk-forward + robustness koşulur.
5. Rapor `reports/research/kaufman-atr-band-breakout-1d-20260613.html`.
6. Karar matrisine göre terfi/iterate/red.

---

**NOT (kendime):** Bu hipotezin EN ZAYIF tarafı "Kaufman intraday → 1D adaptasyon" mantığı. Eğer adversary_engineer bunu kırarsa hipotezi 1D yerine 4H'ye taşımayı düşün — ama bu YENİ bir pre-registration olur, mevcudunu silme.
