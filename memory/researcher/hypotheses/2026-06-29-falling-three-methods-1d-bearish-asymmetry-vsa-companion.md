---
doc_id: researcher-20260629T143000-falling-three-methods-1d-bearish-asymmetry-vsa-companion
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-29T14:30:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, cross-strategy, candlestick-continuation, bearish-asymmetry, low-correlation-target, vsa-companion, bulkowski-transfer-test]
supersedes: null
hash: null
---

# HYP-2026-06-29-falling-three-methods-1d-bearish-asymmetry-vsa-companion

## 0. Seed Konu
Aktif `vsa_climax_test` ile **düşük korelasyonlu** ek bir strateji adayı arıyoruz (rafta 66 kalıp). VSA climax = vol-spike + exhaustion **reversal** at extremes. Bu hipotez **continuation** mantığı kuruyor → temporal ve lojik olarak ortogonal.

## 1. Iddia (pre-registered, ölçülebilir)

USDT-perpetual evrenin top-30 likit sembolünde, 2022-01-01 → 2025-12-31 dönemi, **1D timeframe**'de, **Falling Three Methods** (FTM) kalıbı + EMA50 altında (1D) HTF filtresi ile, Bar 5 close break-aşağı tetikleyici, ATR(14)×0.25 buffer'lı SL, 2R fixed TP, %0.5 risk/trade, fee 7.5bps taker + 5bps slippage konservatif kabulü altında:

| Metrik | Eşik (OOS) |
|---|---|
| Net annual return | **> %25** |
| Sharpe (OOS) | **> 1.0** |
| MaxDD | **< %25** |
| Profit factor | **> 1.3** |
| Trade count (3y, evren) | **≥ 150** (istatistik tabanı) |
| **|ρ(daily returns, vsa_climax_test)|** | **< 0.25** ← mission-critical |
| **Bearish continuation rate (Bulkowski transfer)** | **≥ %65** (equity baseline %74'ten konservatif düşüş) |

### Asimetri ek-iddiası (kripto-spesifik)
Kripto bear leg ortalama hareketi (`avg_drawdown / avg_rally` log-ölçek) ≥ 1.3 olduğu için, FTM continuation move'u (R-multiple) eşleniğinin (Rising Three Methods) ortalamasından **anlamlı yüksek** çıkmalı (one-sided t-test p < 0.05).

## 2. Gerekçe (RAG referansları)

- **[#10 book_candlestick_statistics]** — Rising Three Methods: 5-bar consolidation continuation, Bulkowski equity **%74 continuation rate**, avg move +%6.1, rank 10/103. Falling Three Methods bearish ayna komplemanı; aynı kaynak literatüründe simetrik kabul edilir.
- **[#2 book_candlestick_statistics]** — Inside bar tek başına zayıf (%54 breakout WR); ama "ii"/"iii" sekansında gücü artar. FTM'in orta 3 barı tipik olarak inside/near-inside → bu seri bağımlılığı kullanıyor.
- **[#3 book_brooks_deep_catalog]** — Trend continuation kalıpları için "n-bar high/low aşımı + geri dönüş" mekanik olarak test edilebilir (skala 5/5). FTM bu mekaniği codifies.
- **[#1 book_lopez_summary]** — DSR/PBO/IS:OOS oran/serbest-parametre ölçütleri stop criteria'yı yapılandırmak için kullanıldı.

**Asimetri argümanı için ek context (RAG dışı, kontrol amaçlı işaretli):** Kripto historical data'da 2022-05 (LUNA), 2022-11 (FTX), 2024-08 (Yen carry) gibi olaylarda bearish leg 24h içinde -%15..-%30 hareket etti; equity index'lerde benzer hızda yok. **Bu argümanı backtest empirik olarak gösterecek (asimetri ölçümü dependent var).**

## 3. Null Hipotez (H0)

FTM kalıbı, USDT-perp 1D evreninde, gelecek 5 bar getirisinde **shuffle baseline'a göre anlamlı fark üretmez** (one-sided shuffle test p ≥ 0.05) **VEYA** `|ρ(vsa_climax_test)| ≥ 0.4` olur (= diversification mission fail). Her iki koşuldan biri true ise hipotez RED.

## 4. Dependent Variables (ölçülenler)

1. Net annualized return (fee+slip dahil), in-sample + 12-fold walk-forward OOS
2. Sharpe ratio (annualized, sqrt(365) çarpanlı, daily-return tabanında)
3. MaxDD (equity-bazlı, NOT cum-PnL-bazlı; CT-RSK-01 uyumu)
4. Profit factor
5. Win rate + R-multiple distribution
6. Trade count (per-year, per-symbol)
7. **Correlation with `vsa_climax_test` daily returns** (Pearson + Spearman, both)
8. Bearish continuation rate (FTM trigger sonrası 5 bar net negatif kapanış oranı)
9. **Asimetri ölçümü:** mean(FTM R-multiple) − mean(RTM R-multiple) (one-sided t-test ve Welch's t)
10. Regime-conditional Sharpe (bull/bear/range)
11. Stress period P&L (LUNA / FTX / USDC depeg / Yen carry)

## 5. Independent Variables (taranacak parametre uzayı — DARLAR)

| Param | Range | Step | Rationale (curve-fit savunması) |
|---|---|---|---|
| `atr_buffer_sl` | 0.20, 0.25, 0.30 | 3 ayrı değer | 1 atr-min/max çevresinde dar; "0.01 step" tipik over-fit kırmızı bayrak değil |
| `tp_R_multiple` | 1.5, 2.0, 2.5 | 3 değer | Kanonik R hedefler; "ince" değil |
| `htf_filter` | EMA50_1D / SMA200_1D / none | 3 değer | A priori 3 standart; cherry-pick yok |
| `inside_tolerance` | %5, %10 (Bar 2-4 Bar 1 gövdesinin %X dışına çıkabilir) | 2 değer | Volman tipik kabul aralığı |
| `min_bar1_body_pct` | %50, %70 | 2 değer | Body-range oranı eşiği |

**Toplam grid:** 3×3×3×2×2 = **108 kombinasyon**.

### Multiple-testing correction (zorunlu)
- 108 trial → Bonferroni: α = 0.05 / 108 = **0.000463**
- Veya FDR (Benjamini-Hochberg, q=0.05) — uygulanacak ve raporlanacak.
- DSR (Bailey-Lopez Deflated Sharpe Ratio) tüm trial'lar için hesaplanacak.

## 6. Beklenen p-value

- **Shuffle baseline test:** Beklenen p < 0.01 (raw). Bonferroni sonrası **< 0.05** olmalı.
- **Asimetri t-test (FTM vs RTM mean R):** Beklenen p < 0.05.
- **DSR > 0.5** (Lopez kriteri).
- **PBO < 0.4** (Combinatorially Purged Cross-Validation).

## 7. Stop Criteria (Lopez ölçütleri — herhangi biri TRUE → strateji DEFER / RED)

| # | Kriter | Eşik | Sonuç |
|---|---|---|---|
| S1 | IS Sharpe / OOS Sharpe oranı | > 3 | KILL |
| S2 | PBO (Probability of Backtest Overfitting) | > 0.5 | KILL |
| S3 | DSR (Deflated Sharpe Ratio) | < 0.5 | KILL |
| S4 | Walk-forward Sharpe std / mean | > 1.0 | KILL |
| S5 | Free params / sample size oranı | > 1/30 | KILL |
| S6 | **|ρ(vsa_climax_test)| (mission-critical)** | ≥ 0.4 | KILL — diversification fail |
| S7 | Trade count (3y, evren) | < 100 | DEFER — istatistik yetersiz |
| S8 | Bonferroni sonrası shuffle p | ≥ 0.05 | KILL |
| S9 | Stress-period (LUNA/FTX/USDC/Yen) tek-event kayıp | > %15 portfolio | KILL |
| S10 | Best param parametre uzayı **sınırında** (örn. `atr_buffer=0.30` köşede) | true | KILL — daha geniş tara |
| S11 | Toplam P&L'in **%80+'ı tek bir periyoda** (örn. 2022-Mart) bağımlı | true | DEFER — tek-olay artefaktı şüphesi |
| S12 | OOS Sharpe < %50 ortalama IS Sharpe | true | KILL |
| S13 | Regime split: en az 2/3 rejimde pozitif | false | KILL |

## 8. Curve-Fit Şüpheleri (peşinen flag — paranoid kontrol listesi)

**🚨 Bu hipotezin yapısal zayıflıkları:**

1. **Bulkowski stats equity-tabanlı** — %74 continuation rate kripto perp evrenine direkt transfer edilebilir mi? Bilinmiyor. Bu yüzden eşiği %65'e indirdim (10pt buffer). Hâlâ over-optimistic olabilir.
2. **FTM kalıbı RARE** — 5-bar specific shape. 3y × 30 sembol × 1D ≈ 32850 bar; FTM ~%0.5-1 frequency tahmini → 150-300 trade. **S7 (trade count) yakın eşikte.** Sembol sayısını 50'ye çıkarmak gerekebilir.
3. **Inside-bar tolerance (%5/%10) tuning knob** — `inside_tolerance` ve `min_bar1_body_pct` 2'şer step ama EŞİTSİZ etkili olabilir; sınırda best param çıkarsa **S10 tetiklenir, KILL.**
4. **HTF filter (EMA50/SMA200/none) cherry-pick riski** — 3 filter'dan biri "şanslı" çıkabilir. Bonferroni 108'e bunu eşit dağıttı.
5. **vsa_climax_test ile gizli korelasyon riski** — Her ikisi de "5-bar window'daki davranış" üzerine kuruyorsa, VSA exhaustion ile FTM consolidation overlap'i olabilir. **S6 mission-critical kontrol.**
6. **Asimetri ek-iddiası**, ana edge zayıfsa beni kurtarmaz — bağımsız olarak ölçülecek ama ana hipotezi pozitifleştirmez (kontaminasyon yok).
7. **2022-Mart / 2022-Mayıs (LUNA) / 2022-Kasım (FTX) anomalileri** FTM kalıbını otomatik triggerlar (büyük bear bar + 3 consolidation + breakdown). P&L'in büyük kısmı bunlardan gelirse **S11 tetiklenir, DEFER.**
8. **Survivorship**: 2022'de delist olan sembolleri (LUNA, FTT, vb.) evrene dahil etmek ZORUNLU; aksi halde FTM'in en agresif "win"leri zaten görünmez (delist öncesi -%99). `data/universe.py::build_universe(date)` ile zaman-bilinçli evren kullanılacak.

## 9. Backtest Setup Spesifikasyonu

| Alan | Değer |
|---|---|
| Universe | USDT-perpetual top-30 by 30d-rolling-volume (delisting-aware) |
| Period | 2022-01-01 → 2025-12-31 (4y; 3y train + 1y holdout) |
| Timeframe | 1D primary; EMA50_1D HTF filter |
| Walk-forward | 3y train + 6m test, step 3m (= 6 dilim, 1y holdout hariç tutuldu) |
| Fees | 7.5bps taker / -1bp maker (conservative taker default) |
| Slippage | 5 bps (conservative) |
| Initial equity | 10k USDT (per backtest run) |
| Risk per trade | %0.5 |
| Max concurrent | 5 |
| Daily DD halt | %2 |
| Optimizer | Optuna TPE, n_trials = 108 grid (exhaustive — daha az değil) |
| Objective | OOS Sharpe (raw), sonra DSR ile düzeltilir |

## 10. Karar Tablosu (terfi/iterate/red karar haritası)

### TERFI (Lab tournament'a gönder) — TÜM koşullar:
- §1 metriklerinin tamamı OOS ≥ eşik
- §7 stop criteria'lardan HİÇBİRİ tetiklenmedi
- §8 curve-fit flag'lerinden HİÇBİRİ aktif değil
- Bonferroni p < 0.05
- `|ρ(vsa_climax_test)| < 0.25` (mission core)

### ITERATE (SOP-4b — pozitif edge varsa) — koşullar:
- Aylık net ROI > 0 AMA herhangi bir risk metriği (MaxDD, S9 stress) eşik üstü
- Iterate v2 patikaları: risk_pct düşür, confluence filter ekle (örn. yalnız `vol_z > 1.5`), bull/bear regime subset

### RED (gerekçeli arşiv) — koşullar:
- §7 S1/S2/S3/S6/S8 tetiklendi
- Aylık net ROI ≤ 0
- §1 |ρ| ≥ 0.4 (cross-strategy mission fail)

## 11. Reproducibility Etiketi

- git_hash: (backtest çalıştırma anında doldurulacak — `git rev-parse HEAD`)
- config_hash: SHA-256 of yaml config string
- data_hash: SHA-256 of universe parquet manifest
- All three logged into result JSON.

## 12. Tahmini Çalıştırma Süresi & Compute Notu

- 108 trial × 30 sembol × 4y daily bars ≈ 4.7M bar evaluation
- Tahmini wallclock: ~25-40 dk (mevcut backtest engine, vectorized)
- Memory peak: ~2 GB

## 13. Önemli: Bu Hipotez Hâlâ Spekülatif

> Aktif vsa_climax_test ile düşük korelasyonu sağlama iddiası **mekanik akıl yürütmeden** geliyor (continuation vs exhaustion); empirik kanıt YOK. Backtest sonrası S6 muhtemelen primary kill-switch olacak. **Pre-registration confidence: low.**

---

## Pre-Registration Sözleşmesi

Bu doküman backtest çalıştırılmadan **önce** committed. Backtest sonuçları bu yazılı eşiklerle karşılaştırılacak — eşik dışı oynama (post-hoc threshold tuning) yasak. Sonuç raporu (`reports/research/falling-three-methods-1d-vsa-companion-<date>.html`) bu hipotez ID'sine link verecek.

**Pre-registered by:** researcher (claude-opus-4-7 instance, 2026-06-29)
**Reviewer için requested:** lab_scientist (statistical gate sanity check), risk_officer (S9 stress eşiği uygunluk)
