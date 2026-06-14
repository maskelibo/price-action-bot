---
doc_id: researcher-20260609T093000-bos-donchian-orthogonal-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-09T09:30:00Z
status: PROPOSED
confidence: med
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, cross_strategy_edge, trend_continuation, bos, donchian, orthogonal_to_vsa_climax]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-06-09-BOS-DONCHIAN-ORTHOGONAL-TO-VSA

## 0. Bağlam ve Motivasyon

Aktif kanat tek strateji çalıştırıyor: **vsa_climax_test** (volume-climax + reversal fade,
mean-reversion biçimi). Tek-edge portföy → drift riski yüksek (RAG #1 Lopez de Prado:
"Sharpe varyansı yüksekse production'a gitmemeli"). Çapraz-edge için **trend-continuation
ailesi**nden, mekaniği fade ile **doğal olarak ortogonal** bir aday arıyorum:
fade fitili yanarken continuation fitili sönsün — getiri zamanlaması farklı olsun.

## 1. İddia (ölçülebilir, pre-registered)

> **1D timeframe**, all_liquid USDT-perpetual evren (≥3 yıl, delisting'ler dahil),
> 2022-06-09 → 2026-05-31:
>
> "Close-based **BOS** (Break of Structure, swing pivot n=3) **+** Donchian-20
> kanal kırılımı confluence'ı oluşan bar'ın kapanışında girilen, 1.5×ATR(14) SL
> ve 10-bar opposite-channel trailing exit ile yürütülen trend-continuation
> stratejisi, **fee 7.5 bps taker + 5 bps slippage** dahil:
>
> 1.  Net annualized return ≥ **%35**
> 2.  OOS Sharpe ≥ **0.9**
> 3.  MaxDD ≤ **%28**
> 4.  Profit factor ≥ **1.4**
> 5.  Aylık getiri serisinin **vsa_climax_test ile Spearman korelasyonu |ρ| ≤ 0.25**
>     (orthogonal kriteri — *bu metric primary*; üst dört geçse bile bu fail ederse
>     terfi adayı **değildir**)
> 6.  Shuffle-baseline p-value < **0.01** (Sharpe için, 1000 permutation)
>
> kriterlerinin **tümünü** sağlar."

## 2. Null Hipotez

Yukarıdaki metric'lerin **herhangi biri** karşılanmazsa hipotez çürür.
Ek olarak: in-sample Sharpe / OOS Sharpe oranı > **2.5** ise (RAG #1: "IS > 3×OOS"
red bayrağı, ben 2.5'ten itibaren paranoya başlıyorum) — gate'i geçse bile **REJECT**.

## 3. Gerekçe (RAG referansları)

- **[#6 book_market_structure_order_flow]** — BOS close-based (n=3) crypto-1D'de
  "Mekanik Çalışabilirlik: Yüksek" olarak işaretli; net kural, az parametrik. Trend-
  state makinesi gerekli ama vectorizable.
- **[#7 book_kaufman_summary]** — Donchian/Turtle System 1 (20-bar high/low):
  asimetrik R-multiple, %35 WR ile pozitif beklenti, choppy rejim'de yıkıcı
  whipsaw. ATR-bazlı stop (2×ATR) ve 10-bar opposite-channel trailing exit
  default'larını ödünç alıyorum.
- **[#1 book_lopez_summary]** — Production gate'leri: DSR ≥ 0.5, PBO ≤ 0.5,
  IS Sharpe ≤ 3×OOS Sharpe, parametre/sample < 1/30. Bu hipotezin yenmesi
  gereken eşikler.
- **[#9 book_chan_summary]** — Sharpe-bazlı gating: single-asset için OOS Sharpe > 0.8
  retail-realistic. Ben 0.9 koyuyorum çünkü hedefimiz kripto fee yapısı altında.

**Not:** Mat Hold (RAG #10, "%74 continuation") gibi candle-pattern devamları
**KULLANMIYORUM** — Bulkowski'nin %74 oranı equity backtest'inden geliyor,
crypto perpetual / fee yapısı altında reprodüce edilmedi. RAG #2'deki Inside Bar
%54 oranı bu literatürün güvenilirlik tabanı için bana yeterli uyarı.

## 4. Bağımlı Değişkenler (ölçeceğim)

| Değişken | Birim | Hedef |
|---|---|---|
| `net_annual_return` | yıllık % | ≥ 35 |
| `oos_sharpe` | rakam | ≥ 0.9 |
| `max_drawdown` | % | ≤ 28 |
| `profit_factor` | rakam | ≥ 1.4 |
| `spearman_rho_vs_vsa_climax_monthly` | rakam | \|ρ\| ≤ 0.25 |
| `shuffle_p_value_sharpe` | rakam | < 0.01 |
| `trade_count` | adet | ≥ 200 (yoksa istatistik anlamsız) |
| `is_oos_sharpe_ratio` | rakam | ≤ 2.5 |
| `dsr` | rakam | ≥ 0.5 |
| `pbo` | rakam | ≤ 0.5 |

## 5. Bağımsız Değişkenler (donduracağım)

| Parametre | Aralık | Adım | Default |
|---|---|---|---|
| `swing_pivot_n` (BOS swing) | {2, 3, 5} | discrete | 3 |
| `donchian_window` | {15, 20, 30, 55} | discrete | 20 |
| `atr_period` | {10, 14, 20} | discrete | 14 |
| `atr_sl_mult` | {1.0, 1.5, 2.0} | 0.5 | 1.5 |
| `exit_channel_bars` | {7, 10, 15} | discrete | 10 |
| `htf_trend_filter` | {none, 1W EMA50} | discrete | 1W EMA50 |

**Toplam grid noktası:** 3 × 4 × 3 × 3 × 3 × 2 = **648**.
Bu yüksek bir sayı — Bonferroni / Benjamini-Hochberg düzeltmesi **zorunlu**.

## 6. Curve-Fit Kırmızı Bayrak Önceden-Kabulü

Bu hipotez için pre-registered curve-fit şüpheleri (*şimdi yazıyorum ki sonradan
inkâr etmeyeyim*):

1. **648 trial = multiple-testing patlaması.** Bonferroni sonrası α=0.05/648
   = 7.7e-5. Bu eşik altında Sharpe anlamlılığı görmezsem terfi **YOK**.
2. **Donchian + BOS confluence** çok özgür: ikisi aynı yöne işaret ederse trade
   verir. Eğer best param'lar `donchian_window ∈ {15 veya 55}` (uç değerler)
   çıkarsa → grid genişletilecek; yine uçtaysa **overfit** kabulü.
3. **ATR-mult 1.5** seçilirse iyi, ama best 2.0 (üst sınır) çıkarsa → daha geniş
   grid; yine üst sınırdaysa stratejiyi terk ediyorum.
4. **Trade sayısı 200 altı** → istatistik anlamsız (RAG #6 BOS frekansı düşük
   olabilir, özellikle HTF filter ile). N < 200 ise hipotez ölü doğdu.
5. **Orthogonality metric:** Spearman |ρ| ≤ 0.25 → eğer ρ değeri **gizli olarak
   negatif-ekstrem** (ρ < -0.6) çıkarsa, "anti-vsa" davranıyor demektir; bu
   teknik olarak ortogonal değil, *hedge*. O ayrı bir paper deserves; bu
   hipotezin amacı değil → **karar belirsiz**, ek analiz isterim.

## 7. Beklenen p-value

- **Shuffle baseline (Sharpe):** p < 0.01 (ham). Bonferroni sonrası n=648 → p_adj < **7.7e-5**.
- Bu eşiği geçmek **AGRESİF** bir gereklilik. Çoğu strateji bu duvarı geçemez —
  bu da iyi: sağlam-edge filtresi olur.

## 8. Stop Criteria (araştırmayı terk şartları)

| Tetik | Aksiyon |
|---|---|
| In-sample Sharpe < 0.5 | **DERHAL DUR**, hipotezi reddet |
| Trade sayısı < 200 (full 3y) | **DUR**, evren / TF revize et |
| `is_oos_sharpe_ratio > 2.5` | **REJECT**, gate'i geçse bile |
| Best params parametre uzayının sınırında | grid genişlet **1 kez**; yine sınırdaysa **REJECT** |
| Spearman \|ρ\| > 0.25 (vsa_climax ile) | **REJECT** — orthogonality kriteri başarısız |
| Walk-forward'da 12 dilimden < 7'si pozitif | **REJECT** (Lopez "Sharpe varyansı > ortalama" bayrağı) |
| Bonferroni-adjusted p ≥ 7.7e-5 | **REJECT** |
| Stress periodlardan (LUNA, FTX, 2024-08) birinde tek-dilim DD > %35 | **REJECT** |

## 9. Reproducibility Token (kod öncesi)

- `git_hash`: HEAD ($(git rev-parse HEAD) çağrılacak — backtest commit'inde dondurulur)
- `data_hash`: Parquet snapshot @ 2026-06-09 ingest manifest
- `config_hash`: Bu doc'un SHA256'sı + backtest yaml hash'i — sonuç raporunda yer alacak

## 10. İterate Bütçesi (SOP-4b ön-kayıt)

Eğer baseline pozitif aylık ROI verir ama DD veya orthogonality fail ederse
(SOP-4b "Iterate on Promising Edge" zorunlu):

1. **v2-risk-reduction:** risk_pct halve, daily_dd_halt %2'ye düşür.
2. **v3-confluence-tighten:** HTF trend filter zorunlu + vol_z > 1 filtre.
3. **v4-bull-only:** regime filter (rejim sınıflandırıcı çıktısı: bull-only).
4. **v5-trade-quality:** sadece breakout'tan önce ≥ 5 bar daralma (Mat Hold-vari
   konsolidasyon — RAG #10 *fikri*, yine sayı vermesi gerekir).

5 versiyon limiti; sonra deferred-archive.

## 11. Sonraki Adımlar (kod öncesi)

1. Bu doc commit edilir → `git_hash` dondurulur.
2. `backtest/engine.py` config'i bu spec'ten otomatik türetilir
   (`hypothesis_runner.py` üzerinden).
3. Robustness suite (SOP-3) **tamamı** çalıştırılır — kısa devre yok.
4. Sonuç raporu `reports/research/bos-donchian-orthogonal-to-vsa-2026-06-09.html`.
5. Karar PR: terfi adayı (Lab tournament'a) **veya** gerekçeli red arşivi.

---

> **Pre-registration kaydı:** Bu doc'tan sonra başka metric eklersem ya da
> eşiği gevşetirsem → p-hacking. Açıkça itiraf etmedikçe **tüm metric ve eşikler
> donduruldu**.
