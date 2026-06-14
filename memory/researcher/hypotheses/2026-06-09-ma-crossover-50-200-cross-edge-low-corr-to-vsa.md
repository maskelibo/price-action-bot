---
doc_id: researcher-20260609T120000-ma-crossover-50-200-cross-edge
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-09T12:00:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, cross_edge, low_corr_to_vsa, trend_following, ma_crossover, curve_fit_suspect]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-06-09-ma-crossover-50-200-cross-edge

- Tarih: 2026-06-09 (TR)
- Versiyon: 0.1 (pre-registration — kod yazılmadı)
- Seed: "Aktif vsa_climax_test ile düşük korelasyonlu ek strateji adayı" — orthogonal mekanizma arayışı (trend-following vs reversal/exhaustion).

## 1. İddia (ölçülebilir, sayısal)

> 1D timeframe'de, USDT-perpetual evreninde (delisting-aware, 3y rolling, ~30 likit sembol),
> 50-EMA close 200-EMA'yı yukarı kestiği bar'ın **kapanışında karar**, sonraki bar **açılışında long**;
> simetrik short death-cross'ta;
> SL = max(50-EMA, entry − 2·ATR(14)), exit = ters cross VEYA entry ± 4·ATR(14) hedefi (hangisi önce),
> ücret (taker 7.5 bps + slippage 5 bps) + funding modelli backtest'te, son 3 yılda:
>
> | Metrik | Hedef (OOS) | Null hipotez (ne olursa çürür) |
> |---|---|---|
> | Annualized net return | > %20 | < %10 |
> | OOS Sharpe | > 0.8 | < 0.5 |
> | MaxDD | < %30 | > %35 |
> | Profit factor | > 1.3 | < 1.1 |
> | Trade sayısı (3y) | 90–250 | < 60 (istatistik anlamsız) |
> | **\|corr(strategy_returns, vsa_climax_test_returns)\| (30d rolling, daily P&L)** | **< 0.30** | **≥ 0.50 → cross-edge yok, reddet** |
> | Shuffle-baseline p-value | < 0.05 (Bonferroni n=trial → < 0.0125) | ≥ 0.05 |

## 2. Gerekçe — RAG referansları

- **[Kaufman — MA Crossover Bağlamı (RAG #4)]:** Long-horizon trend captures; daily/weekly timeframe ideal; major trend'leri yakalar; düşük frekans → düşük commission yükü. **Failure mode net belirtilmiş: sideways market'te 4–6 ardışık whipsaw.** Bu ölçülebilir bir başarısızlık — testte ölçeceğiz.
- **[Chan — Sharpe gating (RAG #9)]:** OOS Sharpe > 0.8 (single asset) eşiği var. Hedefimizi bu sınırın hemen üstüne koyduk — düşük Sharpe ile bile düşük korelasyon **portföy katkısı** sağlayabilir (marginal Sharpe argümanı, Curator perspektifi).
- **[Lopez de Prado — DSR/PBO/MinBTL gates (RAG #1)]:** "Sharpe = 2.1 → deploy" bilim değil. DSR, PBO, parametre/örnek oranı, walk-forward varyansı kontrol edilecek. Bu hipotez bu altı kriterden BİRİNİ kırarsa otomatik red.
- **Cross-edge motivasyonu:** vsa_climax_test = volume exhaustion / climactic reversal (event-driven, mean-reversion). MA crossover = pure trend-continuation (regime-driven). İki mekanizma teorik olarak ANTI-korelasyondan başlayıp en kötü düşük korelasyona yakınsamalı.

## 3. Dependent variables (ölçülecek)

- Annualized net return (fee + slippage + funding dahil)
- OOS Sharpe (1Y rolling, walk-forward 3y train / 6m test, step 3m → en az 6 dilim)
- MaxDD (equity-based, NOT cumulative-PnL-based — bkz. CT-RSK-01 dersi)
- Profit factor
- Win rate (info only, hedef yok — düşük WR / yüksek R kabul edilir)
- **Rolling 30d correlation with vsa_climax_test live daily P&L** (KEY metrik)
- Whipsaw rate: ardışık iki cross arası bar sayısı < 30 olan sinyal yüzdesi
- Bonferroni-corrected p-value (shuffle-baseline null modeli)

## 4. Independent variables (taranacak parametre uzayı — KASITLI DAR)

| Param | Aralık | Adım | Gerekçe |
|---|---|---|---|
| fast_ema | {40, 50, 60} | discrete | 50 OVERDISCOVERED — komşu değerlerin de tutması zorunlu (robustness) |
| slow_ema | {180, 200, 220} | discrete | 200 OVERDISCOVERED — aynı mantık |
| atr_sl_mult | {1.5, 2.0, 2.5} | 0.5 | İnce grid (0.1 vs.) **YASAK** — overfit riski |
| atr_tp_mult | {3.0, 4.0, 5.0} | 1.0 | Aynı |

**Toplam trial: 3 × 3 × 3 × 3 = 81.** Bonferroni → α_eff = 0.05/81 ≈ 6.2e-4 hedef p-value. Bu yüksek eşik kasıtlı — overfit'ten korunmak için.

## 5. Beklenen p-value

- Shuffle baseline (returns'leri permute et) null modeli için p < 0.05 (öncesinde).
- **Bonferroni düzeltmesi sonrası:** p < 0.0125 (3 ana metrik üzerinden) VEYA en sıkı: p < 6.2e-4 (81 trial).
- Eğer p-value 0.01–0.05 arasında **ama Bonferroni sonrası kaybediliyorsa** → red.

## 6. Stop criteria (hipotez ne zaman terkedilir)

1. **In-sample Sharpe < 0.3** → hemen abort (zayıf sinyal).
2. **\|corr with vsa_climax_test\| > 0.50** → cross-edge yok, **portföy katkı = 0**, abort. Bu HİPOTEZİN ANA SEBEBİ; düşmezse hipotez başarısız.
3. **Whipsaw rate > 40%** → Kaufman'ın belirttiği failure mode realize oldu, abort.
4. **In-sample / OOS Sharpe oranı > 2.0** → overfit kırmızı bayrağı (Lopez kriteri), abort.
5. **Best params parametre uzayının sınırında** (örn. en iyi fast=40 veya slow=220) → sınır dışında ne var bilmiyoruz, **uzay genişletip yeniden test** veya abort.
6. **Stress dönemlerinden HERHANGİ BİRİ** (LUNA 2022-05, FTX 2022-11, Yen carry 2024-08) tek başına −%40+ DD üretiyorsa → abort.
7. **Trade sayısı 3y'de < 60** → istatistik gücü yetersiz, abort (universe genişletmek hariç).

## 7. Curve-fit & overfit kırmızı bayrakları (ÖNDEN İŞARETLİ)

> **Bu hipotez baştan curve-fit şüphesi altındadır.** Aşağıdaki risk vektörleri var; tetiklenmediği kanıtlanmalı:

1. **50/200 parametreleri overdiscovered.** Akademik literatür (Faber 2007, Hurst-Ooi-Pedersen 2012, Brock-Lakonishok-LeBaron 1992 sonrası replication failures) bu spesifik çiftin post-2010 marjinalleştiğini göstermiştir. Bu yüzden **parametre perturbation test'i kritik**: (40,180) ve (60,220) komşularının ortalama Sharpe kaybı < %25 olmalı.
2. **Kripto 1D evreninde sürvivor bias riski.** Universe `data/universe.py::build_universe(date)` zaman-bilinçli olmalı (lesson: survivorship-bias-crypto). Aksi halde sonuç %20-50 şişer.
3. **Lookahead riski (düşük ama var):** EMA hesabı `min_periods` yanlış ayarlanırsa erken bar'lara gelecek bilgisi sızar. CI test `tests/test_lookahead.py::test_ma_crossover_causality` zorunlu.
4. **Hikâye çekiciliği biası.** "Golden cross çalışır" anlatısı (CNBC-tier narrative) → sayıya bakarken bu anlatıya yaslanma yasak. Sayı yoksa, anlatı YOK.
5. **Bonferroni kayboluş senaryosu.** Bekliyorum: ham p-value 0.02–0.04 civarı, 81-trial Bonferroni sonrası kayboluş ≥ %50 ihtimal. **Bu hipotezin reddedilmesi tahminim BENİM (researcher) öncel beklentim** — bunu önceden yazıyorum ki sonradan "evet biliyordum" demeyeyim.

## 8. Robustness suite (SOP-3 zorunlu liste)

- [ ] Walk-forward 3y/6m, step 3m → en az 4/6 dilim pozitif (≥ %66.7)
- [ ] In-sample / OOS Sharpe farkı < %50
- [ ] Parameter perturbation: ±%10, 50 seed → ortalama Sharpe kaybı < %25
- [ ] Symbol-out CV: her sembolü tek tek çıkar → min OOS Sharpe > 0.3
- [ ] Regime split: bull / bear / range — en az 2'sinde pozitif net return
- [ ] Stress periods: LUNA, FTX, USDC depeg, Yen carry — yıkıcı kayıp YOK (−40% DD eşik)
- [ ] Shuffle baseline: p < 0.05
- [ ] Multiple testing (Bonferroni n=81): p < 6.2e-4
- [ ] Lookahead causality test: `detector(df.iloc[:t+1])[t] == detector(df)[t]`
- [ ] **CROSS-EDGE TEST:** vsa_climax_test live 30d P&L ile korelasyon |ρ| < 0.30 (key gate)

## 9. Karar protokolü (sonuç çıktığında)

| Sonuç | Karar |
|---|---|
| Tüm robustness ✓ + korelasyon |ρ| < 0.30 + Bonferroni p < 6.2e-4 | **Terfi adayı → Lab tournament** |
| Net return > 0 ama korelasyon |ρ| ≥ 0.30 | **İterate (SOP-4b)**: regime-filter ekle (sadece trend-day) → v2 |
| Net return > 0 ama Sharpe < 0.5 | **İterate**: position management (early TP @ 1R partial) → v2 |
| Net return ≤ 0 VEYA Bonferroni sonrası anlamsız | **Red — gerekçeli arşiv** |
| Curve-fit kırmızı bayrak (sınır parametre vb.) | **Red** + RAG genişletme şerhi |

## 10. Beklenti (researcher öncel)

**Tahminim: bu hipotez REDDEDİLECEK.**

Gerekçeler:
- 50/200 MA crossover akademik literatürde post-2010 zayıflamış.
- Kripto 1D'de trend-following edge SMA tabanlı yöntemlerde 2022 sonrası tutmuyor (Donchian-20 zaten gate'i geçemedi, bkz. 2026-06-07-donchian-20-1d-low-corr-to-vsa.md).
- Bonferroni n=81 düzeltmesi muhtemelen anlamlılığı yer.

**Niye yine de pre-register ediyorum?**
1. **Düşük korelasyon eşiği** key metrik. Edge MARJİNAL olsa bile |ρ| < 0.30 doğruysa, Curator marginal-Sharpe argümanı için veri toplamış oluruz.
2. **Negatif sonuç da öğretici.** Bonferroni sonrası reddedilen hipotez `learning.md`'ye "kripto 1D trend-following SMA edge yok (3. tekrar kanıt)" olarak eklenir — analyst/lab için temiz signal.
3. Seed beklenti ≠ p-hack. Beklentiyi yazılı olarak işaretledim; sonuç beklediğim gibi çıkarsa "ah halbuki şöyle..." (post-hoc bias) yapma hakkım yok.

## 11. Reproducibility

- git_hash: <set at run>
- config_hash: <derived from this doc + backtest config>
- data_hash: <DuckDB OHLCV snapshot>
- engine: `backtest/engine.py` (vectorbt) — fee=7.5bps, slip=5bps, funding modelli
- universe: `data/universe.py::build_universe(t)` (delisting-aware)
- VSA correlation kaynağı: `data/futures_journal*.duckdb` strategy=vsa_climax_test daily returns

## 12. Next steps (kod yazımı SADECE bu doc commit'lendikten sonra)

1. Pre-registration commit (hash dondur).
2. `backtest/engine.py` config türet.
3. Walk-forward + robustness suite koş.
4. Rapor: `reports/research/ma-crossover-50-200-2026-06-09.html`.
5. Karar dokümanı: terfi / iterate / red.

---

**Pre-registration kuralı:** Bu hipotez DRAFT → PROPOSED'a geçtikten sonra body'sini DEĞİŞTİREMEM. Sonuç çıktığında ayrı bir `report` doc'unda referans alacağım. Body'yi sonradan oynatmak = p-hacking = otomatik red.
