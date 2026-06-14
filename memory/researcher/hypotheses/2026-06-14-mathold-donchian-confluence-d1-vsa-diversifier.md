---
doc_id: researcher-20260614T101500-mathold-donchian-confluence-d1-vsa-diversifier
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-14T10:15:00Z
status: PROPOSED
confidence: low
depends_on:
  - researcher-20260608T-mathold-continuation-low-corr-to-vsa
  - researcher-20260607T-donchian-20-1d-low-corr-to-vsa
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, mat_hold, donchian, confluence, vsa_diversifier, curve_fit_risk]
supersedes: null
hash: null
---

# HYP-2026-06-14: Mat Hold × Donchian-20 Confluence (1D, VSA-Diversifier)

## 1. İddia (tek cümle, pre-registered, ölçülebilir)

> 1D timeframe'de, 19-sym pool'unda (2022-01-01 → 2025-12-31), `vsa_climax_test`
> aktif champion'una **düşük korelasyonlu** (ρ < 0.30, 30-bar rolling günlük
> getiri Pearson) yeni bir aday üretmek için:
>
> **Setup:** Bulkowski **Mat Hold (5-bar)** kalıbı + son bar **Donchian-20-high
> üstü** kapanış (long); sembolde mirror short Mat Hold + Donchian-20-low altı.
>
> **Risk paketi:** %0.3 / trade, SL = 2.0×ATR(14), TP = 2R fixed, fee 7.5bps
> taker + 5bps slip, 19-sym pool, no leverage > 3x.
>
> **Pre-registered ölçütler (in-sample 2022–2024, OOS 2025):**
> - Annualized net return OOS > **+25%**
> - Sharpe OOS > **1.0**
> - MaxDD OOS < **25%**
> - Profit factor OOS > **1.4**
> - Trade sayısı (3y, 19 sym) ∈ [80, 240]
> - ρ(daily returns, vsa_climax_test) < **0.30** (rolling 30 bar, ortalama)
> - IS / OOS Sharpe oranı < **1.5** (overfit guardrail)

## 2. Gerekçe (RAG referansları)

| # | Kaynak | Sayı / argüman |
|---|---|---|
| RAG #10 | `book_candlestick_statistics — Mat Hold` | Bulkowski bullish continuation rate %74, average move %6.1, performance rank **10 / 103**. Eşik bar 5: tüm consolidation'ı kıran kapanış. Equity üzerinde test, kripto'ya tercüme şüpheli — kontrol etmek zorundayız. |
| RAG #7 | `book_kaufman_summary — Donchian/Turtle` | 20-bar high breakout trending rejim yakalama tabanı, ADX>25'de pozitif beklenti, choppy'de whipsaw. Bizim için filtre değil, **rejim koşulu** — pattern'i çıplak değil trend ortamında tetikle. |
| RAG #3 | `book_brooks_deep_catalog` | Brooks: "Önceki SR + overextended trend + reversal bar kalitesi yüksek + HTF opposition" mekanik kodlanabilir. Bizim setup tersi — continuation, ama "HTF onayı" mantığı transfer ediliyor (Donchian-20 = HTF onay proxy). |
| RAG #1 | `book_lopez_summary — anti-overfit kriterleri` | params/samples > 1/30 = red bayrak. Bizim setup: 5-bar pattern (4 iç gövde toleransı: %X, %Y, %Z, %W) + Donchian periyodu + ATR mult + TP-R + Mat Hold close-tolerance ≈ **7-9 serbest param**. 19 sym × 3y ≈ 100-200 trade beklentisi → param/sample > 1/30 eşiğine **çok yakınız** — kırmızı uyarı. |
| RAG #9 | `book_chan_summary — Sharpe gating ≥0.8 single asset` | Bizim eşik OOS Sharpe > 1.0 (multi-asset portfolio), Chan'in 1.2 multi-asset bar'ının altında — bilinçli olarak. Geçemezse terk. |

**Anti-narrative kontrol:** Mat Hold'un %74 sayısı 1980-2000 US equities'den. Kripto 24/7, deep liquidity 2017+, regime shifts daha sık. **Sayı şüpheli**, hipotezi bu hikâyeye dayandırmak naif olur — bu yüzden mutlak hedef olarak **+25% annual** (mütevazı), %74 değil.

## 3. Null Hipotez

> Mat Hold × Donchian-20 confluence'ı, 19-sym pool 2022–2025'te shuffle baseline
> (returns shuffled, aynı entry timing) ile karşılaştırıldığında Sharpe farkı
> p ≥ 0.05 (1000 permütasyon). Yani: kalıbın gerçek edge'i yoktur, in-sample
> getiri tamamen şans + Bonferroni-shrinkage öncesi multiple-testing artifact.

## 4. Dependent Variables (pre-registered)

| Metric | Hedef | Curve-fit guard |
|---|---|---|
| Annualized net return OOS | > 25% | IS/OOS oran < 2.0 |
| Sharpe OOS | > 1.0 | IS/OOS < 1.5 |
| MaxDD OOS | < 25% | 30-day rolling DD < 15% |
| Profit factor OOS | > 1.4 | regime-split bull ∧ range pozitif |
| Trade sayısı (3y, 19 sym) | [80, 240] | <80 → istatistik yok, terk |
| ρ(vsa_climax_test, daily) | < 0.30 | iki strateji aynı bar'da firing rate < %15 |
| OOS shuffle p-value | < 0.01 | Bonferroni 50 trial sonrası < 0.05 |

## 5. Independent Variables (parametre grid, Optuna ≤ 50 trial)

| Param | Aralık | Adım | Not |
|---|---|---|---|
| `mat_hold_body_pct` (bar 1) | [0.5, 0.8] | 0.1 | gövde / range eşiği |
| `mat_hold_inner_tol_pct` | [0.0, 0.2] | 0.05 | bar 2-4 bar 1 gövdesi dışına ne kadar taşabilir |
| `donchian_period` | {15, 20, 25} | enum | 3 nokta — fazla "ince" değil |
| `atr_mult_sl` | [1.5, 2.5] | 0.25 | SL genişliği |
| `tp_r` | {1.5, 2.0, 2.5} | enum | fixed-R TP |

**Toplam param uzayı ≈ 3×3×3×5×5 = 1125**, Optuna TPE 50 trial → multiple-testing
düzeltmesi: Benjamini-Hochberg FDR q=0.05.

**🚨 Curve-fit Kırmızı Bayraklar (önceden taahhüt):**
- Best `mat_hold_inner_tol_pct` = 0.0 veya 0.2 (uç değer) → red
- Best `donchian_period` = 15 veya 25 (uç değer) → red
- Param uzayını genişletmek istersem (örn. `tol_pct` 0.3'e çıkar) → bu noktada **dur, hipotezi terk et**. Genişletme = post-hoc rationalization.

## 6. Beklenen p-value

- **Shuffle baseline (single test):** p < 0.01 (yoksa edge fake)
- **Bonferroni / FDR sonrası (50 trial):** p < 0.05 (yoksa multiple-testing artifact)
- **PBO (Probability of Backtest Overfit) — Lopez de Prado SOP:** PBO < 0.5
- **DSR (Deflated Sharpe Ratio):** DSR ≥ 0.95 (Lopez de Prado eşiği)

## 7. Stop Criteria (önceden taahhüt — değiştirilmez)

Aşağıdakilerden **HERHANGİ BİRİ** tetiklenirse araştırma **derhal** terk
edilir, `seed-abort-v*` formatında arşivlenir:

1. **In-sample Sharpe < 0.8** → continuum çok zayıf, devam etme.
2. **Trade sayısı (3y, 19 sym) < 50** → istatistik anlamsız.
3. **Mat Hold tanımının `inner_tol_pct`'sini > 0.2'ye çekmek gerekirse** → kalıp tanımını zorluyorsun, post-hoc.
4. **Best params parametre uzayının sınırında** (yukarıdaki bayraklar) → overfit.
5. **vsa_climax_test ile ρ > 0.40** (30-bar rolling avg) → diversifikasyon değeri yok.
6. **IS / OOS Sharpe oranı > 2.0** → overfit, Lopez de Prado eşiği.
7. **Regime split:** bull ∧ range rejimlerinin **en az birinde** pozitif değilse → fragil.
8. **Stress periyot kayıpları** (2022-05 LUNA, 2022-11 FTX, 2024-08 yen-carry): herhangi birinde DD > %20 → fragil.

## 8. Reproducibility

- `git_hash`: (commit'te sabitlenecek)
- `config_hash`: (config YAML SHA256)
- `data_hash`: 19-sym pool snapshot, `data/parquet/futures_1d_*.parquet` SHA256
- Optuna seed: 42 (sabit)
- Walk-forward seed: 42
- Shuffle seed: deterministic (1000 permütasyon, seed 0..999)

## 9. Lookahead Sanity (CI gate)

- Mat Hold detector: pure-function (df[:t+1] → df[:T] aynı sinyal t üretmeli)
- Donchian-20: `rolling(20).max().shift(1)` (gelecek bar bilgisi kapalı)
- Entry: bar 5 kapanışında karar, bar 6 açılışında giriş (bar timing kontratı)
- `tests/test_lookahead.py::test_mat_hold_donchian` zorunlu (yazılacak)

## 10. Beklenen sonuç tahmini (humility check)

Şahsi öncül (prior): Bu hipotezin **gate'i geçme olasılığı %15-25**.
- Mat Hold çıplak halinde defalarca seed-abort olmuş (2026-05-31, 2026-06-02, 2026-06-08, 2026-06-10, 2026-06-11).
- Donchian-20 tek başına da gate'i geçememiş (2026-06-07).
- İkisinin konfluansı **filtre eklediği için trade sayısını düşürür** → istatistik anlamlılık kaybı riski yüksek (stop criteria #2).
- Beklentim: trade sayısı 80'in altına düşecek, p-value Bonferroni sonrası > 0.05 → **stop criteria #2 veya #5 ile terk**.
- Eğer beklenmedik bir şekilde gate'i geçerse → adversary_engineer'e kill-probe için, lab tournament'a çift-kör değerlendirme için göndereceğim.

## 11. Sonraki Adım

1. Bu doc commit edilir (hash dondurulur).
2. `scripts/research/build_pool_19sym.py` ile pool refresh.
3. `backtest/engine.py` Mat Hold detector + Donchian-20 filter implementation.
4. Lookahead test zorunlu pass.
5. Walk-forward (2022–2024 IS, 2025 OOS, 6m step).
6. Robustness suite (SOP-3 8 madde).
7. Karar dokümanı: terfi adayı / iterate (SOP-4b) / red.

---

**🚫 Bu doc commit edildikten sonra parametre uzayı, hedefler veya stop
criteria DEĞİŞTİRİLMEZ.** Değişiklik gerekirse `seed-abort-v*` ile arşivle,
yeni hipotez aç.
