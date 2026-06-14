---
doc_id: researcher-20260607T093000-equal-highs-lows-sweep-1d-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-07T09:30:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, cross-strategy, low-correlation, vsa-companion, smc, h-2, sweep, 1d]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-06-07-equal-highs-lows-sweep-1d-low-corr-to-vsa

## 1. Pre-registration (kod yazılmadan)

- **Tarih:** 2026-06-07
- **Versiyon:** 0.1
- **Seed:** Cross-strategy edge keşfi: aktif `vsa_climax_test` ile düşük korelasyonlu ek strateji. Raftaki 66 adayda **liquidity-sweep / equal-highs-lows (H-2)** ailesi henüz test edilmedi (BOS, Donchian-20, Marubozu, Mat Hold, NR7, iii, Golden/Death Cross zaten testte). Mekanik olarak VSA climax-fade'den ayrık: VSA *exhaustion* sinyali okurken, sweep stratejisi *stop-hunt + reversal* mekaniği üzerine kurulu — tetiklenme bar profili ve hacim koşulu farklı.

## 2. İddia (Claim) — ölçülebilir

> 1D timeframe'de, USDT-perpetual liquid evrenden (top 50 by 90d median volume, **survivorship-corrected: delisted dahil**), son **N=20** bar high'ının `±k×ATR(14)` (k=0.10) bandında **m=2 veya daha fazla** swing high oluştuktan sonra (Equal Highs cluster):
> - **SHORT:** O seviyenin üzerinden close-based bir bar ile aşılma (sweep), sonraki bar içinde aşılan seviyenin altına **close-back** → t+1 open SHORT entry.
> - **LONG:** Symmetric (Equal Lows + sweep-below + close-back-above → t+1 open LONG entry).
> - **SL:** Sweep wick'inin 0.25×ATR(14) ötesi.
> - **TP:** 1.5R (fixed). Trailing yok (baseline).
> - **Risk:** %0.5 / trade.
> - **Universe:** 3y, top 50 USDT-PERP, survivorship-corrected.
> - **Fees:** 7.5bps taker, 5bps slippage (konservatif).
>
> **Önceden taahhüt edilen gate'ler (hepsi OOS, walk-forward 3y/6m/3m):**
> 1. Net annualized return > **30%** (fee + slip dahil).
> 2. Sharpe > **0.8**.
> 3. MaxDD < **25%** account equity (zero-base PnL **değil** — equity-base).
> 4. Profit factor > **1.3**.
> 5. Trade sayısı (3y) ≥ **80** (yoksa istatistik anlamsız).
> 6. **Aylık-getiri korelasyonu** `|ρ(strategy, vsa_climax_test)|` < **0.30** (low-corr iddiasının kanıtı; > 0.30 olursa cross-strategy edge çürür).
> 7. Lopez gates: **DSR ≥ 0.5**, **PBO ≤ 0.5**, **IS Sharpe ≤ 3·OOS Sharpe**.

## 3. Null Hipotez

> Equal Highs/Lows sweep + close-back-reversal sinyali, fee+slip sonrası beklenen getirisi sıfırdan farksızdır (μ ≤ 0); ve/veya `vsa_climax_test` ile aylık getiri korelasyonu |ρ| ≥ 0.30 — yani yeni edge değil, mevcut climax-fade edge'inin başka koordinatla gösterilmiş yeniden ifadesi.

## 4. Gerekçe (RAG referansları)

- **[Market Structure & Order Flow, ch. SMC mechanics]** — *"Equal Highs/Lows Sweep: **Mekanik Çalışabilirlik (Crypto 1D) = Yüksek**. Stop-hunt mekaniği crypto'da güçlü; H-2 ailesi net kurallarla backtestable."* (RAG #6)
- **[Brooks Trading Deep Catalog]** — *"n-bar high/low aşımı + geri dönüş **mekanik, tamamen kodlanabilir. En iyi hipotez adaylarından biri.** Test edilebilirlik skoru: 5/5."* (RAG #3)
- **[Candlestick Statistics / Bulkowski]** — Reversal bar patternlerinin OHLC tabanlı tetikleyicileri çıplak inside bar'a göre belirgin şekilde güçlü; close-back-confirmation `ii` setup'ında benzer şekilde win-rate'i artırıyor. (RAG #2 — analog mantık)
- **[López de Prado overfit gates]** — DSR<0.5, PBO>0.5, IS>3·OOS → otomatik red. Bu hipotez bu gate'ler altında çalışacak şekilde önceden taahhüt edildi. (RAG #1)

**Anti-narrative not:** Sweep narratif olarak çekici ("Smart money retail stoplarını avlıyor"). Bu anlatı **kanıt değildir**; sayı kazanır. Bulkowski equity-temelli, kriptoya doğrudan aktarılamaz.

## 5. Dependent Variables (ölçülecek)

- `annualized_net_return` (fee+slip sonrası, equity-base)
- `oos_sharpe` (walk-forward 12 dilim ortalaması)
- `maxdd_equity_base` (zero-base **değil**)
- `profit_factor`
- `trade_count_3y`
- `monthly_return_corr_to_vsa_climax_test` (Pearson, 36 monthly bucket)
- `dsr`, `pbo`, `is_oos_sharpe_ratio` (Lopez metrikleri)
- `regime_split_sharpe[bull, bear, range]`
- `stress_period_max_dd[luna_2022_05, ftx_2022_11, usdc_2023_03, yen_2024_08]`
- `shuffle_baseline_p_value`

## 6. Independent Variables (parametre uzayı — sınırlı tutuldu, PBO disiplini için)

| Param | Aralık | Adım | Toplam değer |
|---|---|---|---|
| `lookback_N` | 15, 20, 30 | — | 3 |
| `cluster_band_k_atr` | 0.05, 0.10, 0.20 | — | 3 |
| `min_cluster_count_m` | 2, 3 | — | 2 |
| `confirmation_window_bars` | 1, 2 | — | 2 |
| `sl_atr_mult` | 0.25, 0.50 | — | 2 |

**Total combinations:** 3 × 3 × 2 × 2 × 2 = **72 trial**.
**Multiple testing düzeltmesi (Bonferroni):** anlamlılık eşiği α = 0.05 / 72 ≈ **0.00069**.
**(Benjamini-Hochberg, daha gevşek, ayrıca raporlanacak — kararı Bonferroni belirleyecek.)**

## 7. Beklenen p-value

- Naive p < **0.01** beklerim (eğer gerçek edge varsa).
- Bonferroni sonrası p < **0.00069** olmazsa → **red**.
- Sweep null modeline (returns shuffle, n=1000) karşı one-sided p < 0.05.

## 8. Stop Criteria — araştırma terk edilir

- IS Sharpe < **0.5** (en iyi parametre kombinasyonunda bile) → terk.
- `vsa_climax_test` ile `|ρ_monthly|` > **0.50** → low-corr iddiası çürür, terk (cross-strategy değerini kaybeder).
- 3y trade count < **80** → istatistik anlamsız, parametre uzayını gevşetmek yerine **terk**.
- DSR < 0.5 **veya** PBO > 0.5 → red (Lopez gate).
- Bonferroni sonrası p > 0.00069 → red.
- Best parameter parametre uzayının sınırında (örn. `lookback_N = 30` sınırda) → genişletmek yerine **overfit kırmızı bayrak**, terk.
- Walk-forward 12 dilimden < 7 pozitif → terk.

## 9. Curve-fit Şüphesi (zorunlu öz-eleştiri)

🚩 **Şüpheler — peşinen kaydedildi:**

1. **`cluster_band_k_atr = 0.10` neden bu değer?** Brooks "n-bar high" kuralı band toleransı söylemez; ben uydurdum. 0.05 ve 0.20'yi de testliyorum, ama eğer **sadece 0.10'da edge varsa = sniffing** — terfi etmem.
2. **`min_cluster_count_m = 2` çok düşük olabilir.** İki swing high `±0.10×ATR` band içinde olmak crypto 1D'de çok sık; sinyal aşırı üretebilir, edge dilüt olabilir. m=3 daha katı, ama trade count'u düşürür → 80-trade gate'ini patlatma riski.
3. **Lookback 20 = Donchian-20 ile aynı.** Bu testle BOS-1D ve Donchian-20-1D arası korelasyon yüksek olabilir; **low-corr iddiasını sadece VSA için değil, Donchian için de doğrulamak gerekecek** (post-hoc analiz: ρ(strategy, donchian_20_1d) raporlanacak; > 0.6 ise yine red — gerçekten yeni edge olduğundan emin olmadan terfi yok).
4. **Crypto 24/7, manipülasyon yoğun.** "Stop-hunt + reversal" 2021-2022 leveraged perp döneminde aşırı çalışmış olabilir; 2024-2026'da ETF spot dominansıyla sönmüş olabilir → regime split zorunlu, bear ve range'de **ayrı ayrı** pozitif olmalı.
5. **Bulkowski equity istatistikleri kriptoya prior değildir.** %74 vb. sayılar buraya transfer **edilmez**; bu hipotez tamamen kripto OHLCV ile sıfırdan ölçülecek.
6. **5 hiperparametre × 72 trial.** PBO inflation riski yüksek; bu yüzden parametre uzayını dar tuttum (her boyutta 2-3 değer). Eğer test sonrası "biraz daha gevşeyeyim" deme dürtüsü gelirse → **terk**.

## 10. Pre-registered olmayan analizler (post-hoc, raporlanacak ama karar etkilemez)

- Funding-rate filter ile alt-koşul performansı (sadece raporlama).
- LTF (4H) tetikleyici ile aynı setup'ın performansı (sadece raporlama).
- Volume z-score filter denemeleri (sadece raporlama).
- BTC dominance regime split (raporlama).

> Bu listede olmayan analizler **yapılmayacak**; karar sadece §2 gate'leri + §8 stop criteria + §6/§7 düzeltilmiş p-value ile verilecek.

## 11. Beklenen iş akışı

1. Backtest config'i bu hipotezden türet (`configs/strategies/equal_highs_lows_sweep_1d.yaml` taslak).
2. `backtest/engine.py` 3y, top 50 USDT-PERP, survivorship-corrected universe.
3. `backtest/walk_forward.py` 3y/6m/3m, n_trials=72 (TPE).
4. Robustness suite (SOP-3): param perturbation, symbol-out CV, regime split, stress periods, shuffle baseline, Bonferroni.
5. Lopez gate (DSR/PBO/IS-vs-OOS).
6. Cross-strategy korelasyon ölçümü: `vsa_climax_test`, `bos_close_based_1d` (test sırası), `donchian_20_1d`.
7. Karar (terfi / iterate / red) + rapor.

## 12. Lab tarafından beklenen review (PROTOCOL §3)

- **lab_scientist:** gate'lerin tournament eşikleriyle tutarlı mı, korelasyon raporu nasıl entegre edilecek?
- **risk_officer:** %0.5/trade sizing + 1.5R TP profili kabul edilebilir mi; SL 0.25×ATR çok dar mı (slip patlama riski)?

---

**Pre-registered.** Bu doc commit edildikten sonra hipotez ve gate'ler dondurulur; backtest sonucu §2 kriterlerini geçmezse veya §8 stop criteria tetiklenirse — **araştırma reddedilir**, sonradan gevşetme yapılmaz.
