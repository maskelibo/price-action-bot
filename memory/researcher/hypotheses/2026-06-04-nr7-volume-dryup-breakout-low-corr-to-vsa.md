---
doc_id: researcher-20260604T100000-nr7-volume-dryup-breakout-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-04T10:00:00Z
status: DRAFT
confidence: low
depends_on:
  - researcher-20260602T000000-htf-continuation-diversifier
  - researcher-20260603T000000-donchian55-regime-gated-1d-cross-edge
  - researcher-20260602T000000-smc-trend-continuation-final-smc-test
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, nr7, crabel, volatility_contraction, low_corr, vsa_diversifier, continuation, crypto_1d]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-06-04-nr7-volume-dryup-breakout-low-corr-to-vsa

- **Tarih:** 2026-06-04
- **Versiyon:** 0.1
- **Author:** researcher

## 1. İddia (ölçülebilir, tek cümle)

> 1D timeframe'de, **15 sembollük champion universe** (mevcut vsa_climax_test paper bot'unun evreniyle birebir aynı) üzerinde, son 2y 6m (2023-12-04 → 2026-06-04) periyodunda; tetikleyici kuralı **`NR7(t) AND zvol20(t) < -0.5`** olan (NR7 = bar `t`'nin range'i son 7 bar'ın en küçüğü; `zvol20` = bar volume'unun son 20 bar'a göre z-skoru) ve t+1 açılışında **NR7 high üstüne stop-buy / NR7 low altına stop-sell** (ilk dokunan kazanır) emirleri 24 saatlik OCO time-fence ile veren, SL = giriş ± 1.5·ATR14, TP = 2R fixed olan strateji; 55 bps round-turn fee ve 5 bps slippage altında:
> - **Gross direction-shuffle null p_gross < 0.05** (BİRİNCİL ve BAĞLAYICI gate — net'ten önce gross sinyalde yön bilgisi var mı?)
> - **Net annualized return ≥ %15** (compounding değil, sabit-fraksiyon 0.5%/trade risk)
> - **OOS Sharpe ≥ 0.8** (3y/6m walk-forward, 8 dilim)
> - **MaxDD ≤ %25** (equity-base, not cumulative-PnL-base; bkz CT-RSK-01)
> - **Daily-return Pearson rho with vsa_climax_test paper trade returns ∈ [-0.20, +0.20]** (uncorrelated by construction iddiası, ayrı olarak doğrulanmalı)
> - **Per-year sign:** 6 yılın en az 5'inde net pozitif
>
> üretir.

**Null hipotez (H₀):** Bu sinyal direction-shuffle baseline'ı yenmez (`p_gross ≥ 0.05`). Yani NR7 + volume dry-up barındaki yön bilgisi rastgele yön tahmininden farklı değildir — daha önce 4 farklı continuation mekanizmasının (SMC OB/FVG/BOS, Donchian-1D, ATR-breakout, HTF EMA200-pull) çöktüğü yere düşer.

## 2. Gerekçe — Literatür (RAG referansları)

- **#5 [Kaufman, Trading Systems and Methods, "Volatility Breakout"]** — Open ± k·ATR(N) breakout'unun edge'i "Yüksek volatilite ortamı, news-driven days" koşullu; düşük-vol günlerde tetiklenmez. Crabel'in NR7 felsefesi tersini önerir: **volatilite kontraksiyonu bir sonraki expansion'ı doğurur** ("the trade is in the setup"). NR7 + volume dry-up'ın breakout güç tetikleyicisi olarak kullanılması Kaufman'da explicit volatility-cycle prior'unu somutlaştırır.
- **#7 [Kaufman, "Donchian Breakout"]** — 20/55-bar Donchian breakout'unda **asimetrik R-multiple** (winners 3-5R, losers 1R, win rate ~%35) ile pozitif beklenti. NR7-breakout aynı asimetri ailesinden ama "**setup'ı pre-conditioning**" eklediği için Donchian'ın choppy-rejim whipsaw zayıflığını azaltmayı hedefler. Donchian'ın HTF-continuation diversifier testinde (HYP-2026-06-02) p_gross < 0.05 geçti AMA net-Sharpe ~0 çıkmıştı; NR7 daha seyrek tetikleyerek fee yükünü azaltmaya çalışır. **Curve-fit uyarısı:** aynı bilgi-yapısının yeniden paketlenmesi olabilir.
- **#1 [Bailey & López de Prado, "The Deflated Sharpe Ratio"]** — DSR < 0.5, PBO > 0.5, IS Sharpe > 3·OOS Sharpe, parameter/sample > 1/30, walk-forward Sharpe variance > mean — bunlardan **biri kırmızı ise production'a gitmemeli**. NR7+zvol+ATR_k+TP-R = 4 serbest parametre; 15 sembol × 900 bar = ~13,500 sample → 4/13500 ≪ 1/30 (geçer), ama Optuna trial sayısı için BH-FDR düzeltmesi zorunlu.
- **#6 [Market Structure & Order Flow, "Crypto 1D mekanik çalışabilirlik tablosu"]** — Equal Highs/Lows Sweep crypto'da "Yüksek" mekanik fizibilite; volatilite-contraction + breakout aynı stop-hunt mekaniğinin tetiklediği bir aileden. Aksine FVG/OB "Orta" — bizim önceki SMC denemelerimiz bu sınıfta zaten çöktü.
- **#9 [Chan, "Regime-conditional ensemble"]** — Yeni strateji portföye girmeden OOS Sharpe > 0.8 (single asset) eşiği zorunlu. Bu eşik aşağıda **dependent variable** olarak benimsenmiştir.

## 3. Mekanizma — Neden VSA Climax ile UNCORRELATED

| Boyut | vsa_climax_test | NR7 + dry-up breakout |
|---|---|---|
| Volatilite rejimi | EXPANSION (range geniş, climax bar) | CONTRACTION (NR7 = range minimum) |
| Hacim profili | YÜKSEK z-vol (climax = volume_z >> 0) | DÜŞÜK z-vol (dry-up = volume_z < -0.5) |
| Sinyal frekansı | Nadir (climax event) | Orta-seyrek (NR7 ~ %1/bar) |
| Yön | Reversal (fade extreme) | Breakout-continuation |
| Aynı barda eşzamanlı sinyal? | **Mekanik olarak imkânsız** (zvol_high ∧ zvol_low çelişki) | — |

**Construction-level argument:** İki sinyal aynı bara düşemez, dolayısıyla trade-overlap = 0 (1D resolution'da). Daily-equity-return korelasyonu portföy ısı haritasında ölçülmelidir, ama prior olarak |rho| < 0.20 beklenir.

**Curve-fit şüphesi:** "Düşük korelasyon" ölçütü stratejinin **edge'sini gerektirmez** — sıfır-Sharpe rastgele bir kuralın da vsa_climax_test ile korelasyonu zayıf olur. Bu hipotezin ASIL gate'i edge'tir; korelasyon ikincildir. HTF-continuation-diversifier denemesinde (HYP-2026-06-02) tam bu hataya düştük: gross_p<0.05 + ρ<0.09 ama net day-Sharpe CI 0'ı kapsadı → **"uncorrelated noise is not a diversifier"** dersinin tekrar test edileceği nokta burası.

## 4. Dependent Variables (pre-registered ölçütler)

| Metrik | Hedef | Bağlayıcılık |
|---|---|---|
| Direction-shuffle null p_gross | < 0.05 | **HARD** (red kriteri) |
| OOS net annualized return | ≥ %15 | HARD |
| OOS Sharpe (8 walk-forward dilimi ort.) | ≥ 0.8 | HARD |
| Walk-forward Sharpe varyansı / ortalaması | < 1.0 | HARD (López §1) |
| MaxDD (equity-base) | ≤ %25 | HARD |
| Profit factor (OOS) | ≥ 1.3 | SOFT |
| Bootstrap day-Sharpe 95% CI lower bound | > 0 | **HARD** (HTF-continuation dersi) |
| Per-year sign consistency | ≥ 5/6 yıl pozitif net | HARD (V12-entry-quality dersi: ucuz ve keskin overfit dedektörü) |
| Stress-period yıkıcı kayıp (LUNA/FTX/Yen-carry/2024-08) | her dilimde > -%10 net | HARD |
| ρ(daily_ret, vsa_climax_test) | ∈ [-0.20, +0.20] | SOFT (diversifier iddiası) |
| Trade sayısı (OOS toplam) | ≥ 200 | HARD (N≥100 dersi, ek pad) |

## 5. Independent Variables (parametre uzayı)

| Parametre | Aralık | Adım | Trial cap |
|---|---|---|---|
| NR window (lookback) | {5, 7, 10} | discrete | 3 |
| zvol_threshold | {-1.0, -0.5, 0.0} | discrete | 3 |
| zvol_window | {15, 20, 30} | discrete | 3 |
| ATR_k (stop) | {1.0, 1.5, 2.0} | discrete | 3 |
| TP_R | {1.5, 2.0, 3.0} | discrete | 3 |
| OCO time-fence | {12h, 24h, 48h} | discrete | 3 |

**Toplam grid:** 3⁶ = **729 nokta**. Multiple-testing yükü ciddi → Bonferroni eşik 0.05/729 = **6.9e-5**, BH-FDR ile q < 0.05 zorunlu. **Curve-fit kırmızı bayrağı:** best parametreler grid sınırında (5 veya 10, 1.0 veya 2.0, vb.) olursa hipotez yeniden test edilmeden REDDEDİLİR.

## 6. Beklenen p-değerleri

- Pre-correction direction-shuffle p_gross: prior **0.10–0.30** (continuation prior crypto'da 4× çöktü; gerçek edge düşük olasılık)
- Post-Bonferroni eşik: 6.9e-5
- Post-BH-FDR (q<0.05) ile en az 1 survivor olma olasılığı: prior **< 20%** (önceki HTF-continuation deneyiminden tahmin)

**Bayesyen ön:** P(strateji canlıya gider) ≈ %12. Eğer geçerse, daha derin adversary stress testi (audit_research + adversary_engineer) zorunlu.

## 7. Stop Criteria (terkettiğim koşullar)

1. **EARLY ABORT:** In-sample (3y) direction-shuffle p_gross > 0.20 herhangi bir konfigürasyonda → ARAŞTIRMA TERK.
2. Trade sayısı < 80 (3y in-sample) → istatistik anlamsız, TERK.
3. Best params grid edge'inde → genişletme dene; iki kez genişletme sonrası hala edge'de → TERK.
4. IS Sharpe > 3·OOS Sharpe (López §1 kriteri) → overfit, TERK.
5. Per-year sign: en az 2 yıl negatif net → regime-luck, TERK.
6. Bootstrap day-Sharpe 95% CI 0'ı kapsıyor → "uncorrelated noise" tuzağı (HTF-continuation dersi), TERK.
7. ρ(daily_ret, vsa_climax_test) > 0.40 → diversifier iddiası çöker, ama edge bağımsız geçerse Lab tournament'a yine taşınabilir.

## 8. SOP-3 Robustness Suite Planı

- Walk-forward: 3y train / 6m test, step 3m → 8 dilim (2023-12 → 2026-06).
- Parameter perturb: best param ±%10, 50 seed → ort. Sharpe kaybı < %25.
- Symbol-out CV: 15 sembol × leave-one-out → ortalama OOS değişmemeli.
- Regime split: bull (2024-Q1, 2024-Q4), bear (2025-Q1), range (2023-Q4, 2025-Q3) → en az 2'sinde pozitif.
- Stress: 2024-03-ATH whipsaw, 2024-08 Yen carry, 2025-Q1 düşüş — yıkıcı kayıp yok.
- Shuffle baseline (direction-shuffle): 1000 permütasyon, p < 0.05.
- Adversary engineer: synthetic flash crash + weekend gap stress (kill-probe).

## 9. Bilinen Curve-Fit Riskleri (önceden ilan)

1. **Continuation prior tekrar bozulması:** SMC OB/FVG/BOS, Donchian-1D, HTF EMA200-pull, ATR-breakout-1D — hepsi crypto 1D bar-OHLCV'de gross-direction edge'i ÜRETMEDİ. NR7 aynı ailedendir; aynı dersi alabiliriz. **Prior: %70 RED.**
2. **Volume_z'nun ihtiyari eşiği:** -0.5 mı, -1.0 mı? Bu seçim Optuna'da yapılırsa BH düzeltmesi zorunlu.
3. **Fee/slippage'a hassasiyet:** Asimetrik 3R winner / 1R loser yapısında 55bps round-turn fee 1R'lik kazançların ~%5'ini siler; küçük edge silinir. WIDESTOP dersi: sl_pct_min floor olmadan fee-erozyonu boğar.
4. **Lookahead riski:** NR7 hesabı `bar t`'nin range'ini `t-6..t` ile karşılaştırır → `t` mumunun close'unda karar, `t+1` açılışında stop-emir. Causality test ZORUNLU (`detector(df.iloc[:t+1])[t] == detector(df)[t]`).
5. **Crabel'in 1990'larda ekuiti vadelilerde çalıştığı kanıtlı; crypto'da 30 yıl sonra hala buralarda durması beklentisi düşük.** Eğer çalışıyorsa muhtemelen başka bir mekanizma karıştırılmış demektir, izole edilmeli.

## 10. Reproducibility

- git_hash: (commit pending)
- config_hash: (Optuna best trial sonrası)
- data_hash: data/market.duckdb @ 2026-06-04 snapshot
- random_seed: 42 (Optuna), shuffle baseline için seed grid 1..1000

## 11. Karar Akışı

```
Step 1: Backtest 729-point grid (in-sample 3y, 2023-12 → 2025-12)
Step 2: Her config için direction-shuffle null p_gross hesapla
Step 3: BH-FDR q<0.05 filter — survivors var mı?
   ├─ HAYIR → ABORT, learning.md'ye 3 satır gerekçe.
   └─ EVET → Step 4
Step 4: Survivors'a tüm SOP-3 robustness suite
Step 5: Bootstrap day-Sharpe CI > 0?
   ├─ HAYIR → ABORT (HTF-continuation tuzağı)
   └─ EVET → Step 6
Step 6: Per-year sign ≥ 5/6 ve stress-period geçer mi?
   ├─ HAYIR → ABORT
   └─ EVET → Adversary engineer kill-probe → Lab tournament aday
```

## 12. Hipotez Hash (pre-registration freeze)

Bu doküman commit edilmeden ÖNCE backtest çalıştırılmayacak. Commit sonrası git SHA buraya yazılır ve sonuçlar bu SHA'ya bağlanır. Sonuç raporu (terfi veya red) bu doc_id'yi `depends_on`'da referans alacak.
