---
doc_id: researcher-20260601T143000-atr-volatility-breakout-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-01T14:30:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, volatility_breakout, kaufman, low_correlation_to_vsa, momentum_expansion]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-06-01-atr-volatility-breakout-low-corr-to-vsa

- Versiyon: 0.1
- Pre-registration timestamp: 2026-06-01T14:30:00Z (kod yazılmadan önce)
- Seed konu: Cross-strategy edge keşfi — aktif `vsa_climax_test` ile düşük korelasyonlu ek strateji.

## 1. İddia (measurable)

> "1D kripto USDT-perpetual evreninde (top 20 likidite, survivorship-düzeltilmiş), 3y test penceresinde (2023-06-01 → 2026-05-31), aşağıdaki Kaufman-tarzı volatilite-breakout kuralı:
>
> - Tetik bar: günlük bar açılışı `O_t`; aynı bar içinde fiyat `O_t + k * ATR14_{t-1}` üzerine çıkarsa long-stop emri tetiklenir (k ∈ [0.5, 1.0], default 0.7).
> - Trend filtresi: `EMA50_{t-1} > EMA200_{t-1}` (long-only — short tarafı bu hipotez kapsamı dışı).
> - Volatilite gate: `ATR14_{t-1} / Close_{t-1} ≥ 0.020` (düşük-vol günler filtrelensin).
> - SL: giriş - 1.5 * ATR14_{t-1}.
> - TP: 2R fixed target VEYA `t+1` bar kapanışında çıkış (early close — Kaufman default).
> - Fee+slip: 7.5bps taker + 5bps slippage, konservatif.
>
> Aşağıdaki ölçülebilir hedefleri sağlar:
>
> | Metrik | Hedef |
> |---|---|
> | Net annual return (OOS) | ≥ %25 |
> | Sharpe (OOS, ann.) | ≥ 1.0 |
> | MaxDD (OOS, equity-base) | ≤ %20 |
> | Profit factor (OOS) | ≥ 1.4 |
> | Trade count (3y, full universe) | ≥ 80 |
> | **Korelasyon (30d rolling returns, vsa_climax_test ile)** | **|ρ| ≤ 0.30** |
> | Shuffle baseline p (returns shuffle) | < 0.01 |
> | Bonferroni-corrected p (trial sayısı = n) | < 0.05 |"

**Ana sav iki ayaklı:** (a) bağımsız edge gerçektir (yukarıdaki tüm gate'ler), (b) `vsa_climax_test` ile **düşük korelasyon** (|ρ| ≤ 0.30) — yani portföye marginal Sharpe katkısı sağlar. Sadece (a) sağlanıp (b) sağlanmazsa hipotez **REJECT** (zaten benzer rejimi tutan stratejimiz var).

## 2. Null hipotezler (ne olursa çürür)

- H0a (edge yok): Net annual return OOS < %0 veya shuffle baseline'ı yenemez (p > 0.05) → red.
- H0b (overfit): IS Sharpe / OOS Sharpe > 2.0 → red.
- H0c (yetersiz örnek): Trade count < 80 → istatistiksel güç yetersiz, red (deferred — daha uzun tarih veya daha geniş evren ile yeniden test).
- H0d (yüksek korelasyon — ana sav çürür): vsa_climax_test ile 30d rolling correlation |ρ| > 0.30 → ana motivasyon (cross-strategy edge) düşer; bağımsız edge olsa bile portföye eklemek anlamsız → red.
- H0e (regime-fragility): Bull rejimde pozitif AMA bear veya range rejimde -%30+ kayıp → red.

## 3. Gerekçe (RAG referansları)

- **[Kaufman summary, §ATR Volatility Breakout — RAG #5]:** "Open + k×ATR(14) üzerine fiyat çıkarsa long stop emri; k tipik 0.5-1.0. Edge: intraday momentum capture; yüksek win rate (~%55) küçük R ile. Failure: düşük volatilite günlerinde tetiklenmez (zaten istenen); ama trend-day'de erken kâr alır, asimetri kaybolur."
- **[Kaufman summary, §Donchian Breakout — RAG #7]:** Trending market filtresi (ADX > 25) gerekliliği — bu hipotezde EMA50/EMA200 cross + ATR/Close eşiği o yerine geçer (basit, daha az parametre).
- **[Lopez de Prado summary — RAG #1]:** "PBO > 0.5, T < MinBTL, IS Sharpe > 3·OOS Sharpe, parametre/örnek > 1/30 → production'a gitmemeli." Bu hipotez 4 serbest parametre alır (k, atr_floor, sl_mult, tp_method); MinBTL kontrolü zorunlu.

**Önemli not (transferability spekülatif):** Kaufman'ın ATR breakout açıklaması US futures/equities intraday içindi (5-30 dakika TF). 1D kripto'ya transfer hipotezi spekülatif; literatürde direkt destek yok. Bu, hipotezin a-priori p(success) tahminini DÜŞÜRÜR (~%20-25 başarı bekliyorum).

## 4. Dependent variables (ölçülecekler)

| Variable | Birim | Ölçüm |
|---|---|---|
| `net_ann_return` | % | Final equity'den geometric mean ann. |
| `sharpe_oos_ann` | scalar | OOS dilim ortalamasının ann. Sharpe (√252) |
| `maxdd_equity_base` | % | Equity peak-to-trough (cumPnL DEĞİL — equity base, CT-RSK-01 dersine uygun) |
| `profit_factor` | scalar | sum(wins) / |sum(losses)| |
| `trade_count` | int | Toplam giriş sayısı |
| `win_rate` | % | Bilgilendirme amaçlı, gate değil |
| `corr_with_vsa_30d` | scalar (Pearson) | 30d rolling returns Pearson ρ — ana sav metriği |
| `shuffle_p` | scalar | Returns shuffle null hipotezi p-value (n=1000 permutation) |
| `bonferroni_p` | scalar | Trial sayısına göre düzeltilmiş p |
| `wf_positive_slices` | int / 12 | Walk-forward 12 dilimden kaçı pozitif |

## 5. Independent variables (taranacak parametre uzayı — Optuna)

| Param | Range | Grid step | Default |
|---|---|---|---|
| `k_atr_mult` | 0.5 – 1.0 | 0.1 | 0.7 |
| `atr_floor_pct` | 0.015 – 0.030 | 0.005 | 0.020 |
| `sl_atr_mult` | 1.0 – 2.0 | 0.25 | 1.5 |
| `tp_method` | `2R_fixed` / `t+1_close` / `2R_or_trail_1ATR` | categorical | `2R_fixed` |
| `trend_filter_method` | `ema50>ema200` / `ema50_slope>0` / `none` | categorical | `ema50>ema200` |
| `universe_top_n` | 10 / 20 / 30 | step | 20 |

**Toplam kombinasyon (kaba):** 6 × 4 × 5 × 3 × 3 × 3 = **3240** noktalı bir Optuna araması — Bonferroni düzeltmesinde p < 0.05/3240 ≈ **1.5e-5** gerekiyor. Bu MÜTHIŞ AGRESIF bir eşik; gerçek edge varsa bile büyük ihtimal geçmez.

→ **Pratik adım:** Optuna'yı 100 trial ile sınırla; FDR (Benjamini-Hochberg, q=0.10) kullan. Yine de IS/OOS ayrımı zorunlu — best Optuna trial OOS'ta independent test edilecek.

## 6. Beklenen p-value

- Raw shuffle baseline p (single best config): **< 0.01** hedef.
- Bonferroni after 100 trials: p < 0.0005 gerekir → realistik olarak çok zor.
- **A-priori başarı tahminim: %20-25.** Düşük çünkü:
  1. Kaufman'ın orijinali intraday içindi; 1D'de momentum davranışı farklı.
  2. Kripto 1D bar açılışı "anlamlı" bir referans değil (7/24 piyasa, açılış arbitrary).
  3. Trend-day'de erken kâr alma yapısal asimetri kaybı (Kaufman'ın belirttiği failure mode kripto'da daha sık).

## 7. CURVE-FIT KIRMIZI BAYRAKLARI (a-priori)

Bu hipotezin curve-fit risk profili **ORTA-YÜKSEK**. Aşağıdaki bayraklar tetiklenirse anında red:

1. **Best `k_atr_mult` parametre uzayının sınırında (0.5 veya 1.0):** kalıp asıl değerini kanıtlamadı → red.
2. **Best `tp_method` katmanlı (2R_or_trail_1ATR):** daha karmaşık TP daha iyi performans gösteriyorsa overfit şüphesi → konservatif `2R_fixed` ile yeniden test.
3. **`atr_floor_pct` çok ince hassasiyet (0.018 vs 0.022 büyük Sharpe farkı):** patolojik — parametre uzayını genişlet.
4. **IS/OOS Sharpe farkı > %50:** klasik overfit → red.
5. **Trade count < 80 ama Sharpe yüksek:** birkaç şanslı trade → istatistik yetersiz → defer.
6. **2024-03 BTC ATH veya 2024-08 Yen carry stress dilimlerinde tüm yıllık PnL'in %40+'sı geliyorsa:** tek-periyot baskın katkı → "edge gerçek değil, regime-luck" → red.
7. **Bonferroni sonrası anlamlılık kayboluyor:** klasik p-hacking → red.

## 8. Stop criteria (terk koşulları — backtest yarıda kesilebilir)

- In-sample Sharpe < 0.5 → araştırma terkedilir (compute boşa harcanmaz).
- Trade count < 50 (yarı evren) → power yetersiz, terk.
- Walk-forward 12 dilimden 3'ten azı pozitifse → red, devam etmiyorum.
- vsa_climax_test ile 30d correlation > 0.50 (basit sample üzerinde) → ana sav çürür, devam anlamsız.
- 2022-05 LUNA dilimi -%25'ten kötü kayıp → catastrophic tail, red (uzun-only momentum'un LUNA gibi olaylara karşı korumasız olması beklenti — ama -%25 üstü tolere edilemez).

## 9. Reproducibility

- `git_hash`: backtest çalıştırılırken doldurulacak (HEAD@2026-06-01).
- `config_hash`: backtest config YAML'ı hash'lenecek.
- `data_hash`: 2026-05-31 23:59 UTC kapanış snapshot.
- Random seed: 42 (Optuna TPE).
- Walk-forward seed: train_start=2023-06-01, train_window=18m, test_window=3m, step=3m → 12 dilim.

## 10. Operasyonel plan

1. **T+0 (bugün):** Bu pre-registration commit → hash dondurulur.
2. **T+1:** `backtest/engine.py` config hazırla, IS dilimleri (2023-06 → 2025-05) çalıştır.
3. **T+2:** Eğer IS Sharpe ≥ 0.5 → OOS dilimi (2025-06 → 2026-05) çalıştır.
4. **T+3:** Robustness suite (SOP-3 zorunlu 8 test).
5. **T+4:** Korelasyon hesabı (vsa_climax_test 30d returns ile Pearson ρ).
6. **T+5:** Sonuç raporu yaz → `reports/research/atr-volatility-breakout-2026-06-01.html`.
7. **T+6:** Karar: terfi adayı (lab_scientist + risk_officer + adversary_engineer review request) / iterate (SOP-4b) / red.

## 11. Bilinmeyenler ve riskler

- **Korelasyon hesabı için vsa_climax_test 30d live/paper returns serisi gerekli.** Eğer aktif bot loglarında yeterli örnek yok (< 60 gün) → backtest IS dönemi returns'leriyle proxy hesabı yapılacak ama bu **zayıf korelasyon tahmini** — flag.
- ATR14 hesabı `min_periods=14` zorunlu (lookahead bias riski — SOP-5/lessons/lookahead).
- Bar açılışındaki stop-emir simülasyonu intra-bar fill — gerçek hayatta gap-up'ta slip büyük olabilir; konservatif slippage 5bps yetersiz olabilir → adversary_engineer review'a not.

## 12. Decision Tree (önceden taahhüt)

```
backtest sonucu →
  IS Sharpe < 0.5 ya da trade<50? → DEFER/REJECT (stop criteria)
  Tüm gate'ler (1-7) ✓ + |corr| ≤ 0.30? → TERFI ADAYI (lab tournament'a)
  Gate'ler ✓ ama |corr| > 0.30? → REJECT (cross-strategy değer yok, zaten benzer rejimi yakalıyor)
  Net annual return > 0 AMA MaxDD veya başka risk metrigi gate'i geçemedi? → ITERATE (SOP-4b: risk reduction, position management, regime subset)
  Net annual return ≤ 0? → REJECT (gerçek edge yok)
  IS/OOS divergence > %50? → REJECT (overfit)
  Bonferroni sonrası p > 0.05 ama gerçek edge görünüyor? → ITERATE (parametre uzayını daralt, yeniden test)
```

---

**Önceden taahhüt (pre-commitment):** Bu hipotezi sonuçlara göre değiştirmem. Eğer "korelasyon 0.32" çıkarsa "0.35'e tolerans tanıyalım" demem — red. Eğer "Sharpe 0.95" çıkarsa "0.9'a indirelim" demem — defer/iterate. Pre-registration **kuralları taşa yazmaktır**; sonuçtan sonra esnetilmez.
