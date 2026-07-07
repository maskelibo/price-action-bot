---
doc_id: researcher-20260629T093000-vsa-climax-volume-z-threshold-sweep
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-29T09:30:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, vsa, climax, volume_z, parameter_sweep, curve_fit_risk_high]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-06-29-vsa-climax-volume-z-threshold-sweep

- **Tarih:** 2026-06-29
- **Versiyon:** 0.1
- **Strateji bazı:** `src/price_action/strategies/vsa_climax_test.py` (aktif canlı; 15m, mean R +0.586)
- **Seed konu:** vsa_climax_test — `vol_sma_mult` (2.5) tabanlı climactic-volume tetiğini `vol_z` (20-bar normalize) eşiğine dönüştürüp parametre sweep'i.

---

## 1. İddia (pre-registered, ölçülebilir)

> **"15m timeframe'de, aktif `vsa_climax_test` evreni (18 USDT-perpetual, UNI dışlanmış) üzerinde, climactic-volume tetiği `vol > vol_sma_mult × SMA(vol,20)` yerine `vol_z(20) ≥ Z_min` ile değiştirilirse, `Z_min ∈ {1.50, 1.75, 2.00, 2.25, 2.50, 2.75, 3.00}` aralığındaki 7 değerden EN AZ 1'i, son 3 yıl (2023-06-01 → 2026-05-31) walk-forward (3y/6m, step 3m) testinde, multiple-testing düzeltmesi (Bonferroni n=7, α=0.05 → per-test α=0.00714) sonrası live champion `vol_sma_mult=2.5` baseline'ına karşı:**
>   - **OOS mean R ≥ +0.700** (champion baseline +0.586'nın >%19 üzerinde)
>   - **OOS Sharpe (annualized, fee+slip dahil) ≥ champion + 0.30 (mutlak)**
>   - **OOS MaxDD ≤ champion + 5 puan**
>   - **Trade sayısı OOS ≥ 60 (istatistik anlamlılık tabanı)**
>   - **Shuffle-baseline p < 0.00714 (Bonferroni sonrası)**
> **şartlarının HEPSİNİ aynı anda karşılar."**

Tek tek değil **konjonktif** kabul — herhangi biri kırılırsa adayı yok say.

---

## 2. Null Hipotez (H0)

> `vol_z` eşiği değiştirmek `vol_sma_mult=2.5` tabanına anlamlı (Bonferroni sonrası p<0.00714) iyileştirme getirmez. Sweep'in en iyi sonucu in-sample şanstan ayırt edilemez.

**H0 reddedilemezse** → çalışma terkedilir, `vol_sma_mult` kalır.

---

## 3. Gerekçe (RAG referansları)

- **[volume_price_divergence §CVD Z-score eşiği]** (RAG #4) — "Başlangıç: ±2.0σ. Güçlü: ±2.5σ. Aşırı: ±3.0σ." → eşik aralığım literatür-uyumlu (1.5σ alt sınır deneysel, klasik aralığın hemen altı).
- **[volume_price_divergence §Stopping Volume Hypothesis]** (RAG #9) — "vol_zscore[t] > 2.0 + küçük spread + range-orta close" → klasik VSA tetiğinde z-score eşiği 2.0'dan başlatılır. Bu, mevcut `vol_sma_mult=2.5` ile sembol-bazlı volatilite farkını **normalize** ettiği için tercih edilebilir.
- **[volume_price_divergence §vol_z tanımı]** (RAG #1) — `vol_z = (vol[t] - mean_20) / std_20`. Sembol-bazlı normalize — küçük-cap sembollerin "büyük hacmi" ile BTC'nin "büyük hacmi" aynı ölçeğe çekilir. Mevcut `vol_sma_mult` yalnız ortalama-katı; volatilite-uyarlama yok.
- **[volume_price_divergence §Hacim eşiği — pattern sweep önerisi]** (RAG #4) — "0.60 ile 0.90 arasında 0.05 adımlarla sweep" diverjans için. Bizim sweep'imiz adımı kasten **0.25** tutuyor (ince grid = curve-fit; Researcher learning §overfit bayrak #3).

---

## 4. Dependent Variables (önceden tanımlı)

| Metrik | Yön | Hedef (her sweep noktası için) |
|---|---|---|
| OOS mean R per trade | ↑ | ≥ +0.700 |
| OOS Sharpe (annualized) | ↑ | ≥ champion + 0.30 |
| OOS MaxDD | ↓ | ≤ champion + 5 puan |
| OOS trade count | — | ≥ 60 |
| Profit factor | ↑ | ≥ 1.30 |
| Win rate | — | bilgi (kabul kriteri değil) |
| Shuffle baseline p-value | ↓ | < 0.00714 (Bonferroni n=7) |

**Bonferroni n=7** — sweep 7 nokta; **per-test α = 0.05/7 = 0.00714**. Eğer Optuna ile finer search'e geçilirse n trial sayısına göre güncellenir; bu hipotez kapsamında **finer search yapılmayacak**.

---

## 5. Independent Variables (sweep alanı)

| Param | Aralık | Adım | Sebep |
|---|---|---|---|
| `vol_z_min` | [1.50, 3.00] | 0.25 | Coarse grid — curve-fit ölmeli; literatürde 2.0/2.5/3.0 anchor noktalar |

**Sabit (sweep DIŞI):**
- `spread_atr_max` = mevcut canlı değer (dondurulmuş, sweep değil)
- `close_pos_threshold` = mevcut canlı değer
- `vol_sma_window` = 20 (Wyckoff klasik)
- Risk per trade, SL/TP, fee/slip = canlı v14p3 ile bit-identical
- Evren = canlı 18 USDT-perp (UNI hariç) — survivorship-aware listing dates
- Timeframe = 15m primary, 1h trend filter (mevcut)

---

## 6. Curve-Fit Kırmızı Bayrak Önlemleri (learning.md §Overfitting Bayrakları'na göre)

Sweep curve-fit'e açıktır. Önlemler **önceden** taahhüt:

1. **Coarse grid (0.25 adım)** — bayrak #3 önlemi. Adım daraltılırsa hipotez geçersiz.
2. **Bonferroni (n=7, α/7)** — bayrak #7 önlemi.
3. **Walk-forward 12 dilim, ≥9'unda pozitif R** olmalı (bayrak #6).
4. **Best param SINIRDA olamaz** — Z_min ∈ {1.50, 3.00} kazanırsa adayı RED (aralığı genişlet, hipotez yeniden kayıt — mevcut adayı atma).
5. **Periyot-bağımlılık testi** — toplam P&L'in tek bir 90-günlük diliminden ≥%40 katkı varsa adayı RED (bayrak #5).
6. **Sembol-out CV** — her sembol tek tek dışarıda; ortalama OOS Sharpe değişimi %25'i geçmesin.
7. **Regime split** — bull / bear / range rejimlerinden en az **2**'sinde pozitif R.
8. **Stress periyotlar** (zorunlu) — 2022-05 LUNA / 2022-11 FTX / 2024-03 ATH / 2024-08 Yen Carry — bu 4 dilimde de mean R > -0.30 (yıkıcı değil).
9. **Lookahead test** — `signals(df[:t+1])[t]` ≡ `signals(df)[t]` (causality unit test).
10. **Reproducibility** — `(git_hash, config_hash, data_hash)` her sweep noktasına çiviler.

---

## 7. Beklenen P-value

- **Per-test:** raw p < 0.00714 (Bonferroni sonrası) — bu olmadan hiçbir nokta promote edilmez.
- **Aile-yönlü (FWER):** Holm-Bonferroni alternatif olarak rapor edilecek; raporda her iki versiyon.
- **A-priori:** sweep noktalarının yarısının pozitif R üretmesini bekliyorum (literatürle uyumlu aralık), ama Bonferroni sonrası **anlamlı kalanın ≤ 1 olması ihtimali yüksek** — bu durumda hipotez **reddedilir, terfi olmaz**. Bu kabul edilebilir bir sonuç; pre-registration olmadan p-hacking riski olurdu.

---

## 8. Stop Criteria (araştırmayı erken bırakma)

Hipotezi **anında terkederim** eğer:

- IS Sharpe **tüm** 7 sweep noktası için < 0.5
- En iyi Z_min IS'de aralığın **sınırında** ({1.50} veya {3.00}) ise → "veriler aralığın dışını gösteriyor" — mevcut hipotez yanlış kurgulu, yeniden yazılır
- Walk-forward dilimlerinin ≥4'ünde **NEGATİF** mean R varsa (bayrak #6)
- Lookahead test başarısız → CRIT, kod fix lazım, hipotez askıya alınır
- Trade sayısı (toplam IS) < 200 → istatistik dayanak yok, evren büyütülmeli

---

## 9. Reddedilme Politikası (SOP-4 + SOP-4b)

| Sonuç | Karar |
|---|---|
| Pozitif aylık ROI + tüm gate ✓ + Bonferroni geçti | **Terfi adayı** → Lab tournament |
| Pozitif aylık ROI + DD/Sharpe gate fail | **İterate v2** (SOP-4b zorunlu) — risk-reduction / confluence / regime variant |
| Pozitif aylık ROI + Bonferroni FAIL | **İterate v2** — finer sweep yerine **alternatif hipotez** (örn. ATR-normalize vol; mevcut tutar) |
| ROI ≤ 0 (IS) | **Red** — gerekçeli arşiv `learning.md` |
| Lookahead bayrağı | **Red + CRIT** — Signal Chief'e route |

---

## 10. Reproducibility

- git branch: `audit-hardreview-20260528`
- baseline config: `configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml`
- backtest engine: `backtest/engine.py` (vectorbt), wf: `backtest/walk_forward.py`
- veri: DuckDB 15m OHLCV, ingest 2026-06-29 snapshot
- evren: canlı 18 USDT-perp (`scripts/futures_daemon.py::SYMBOLS` − UNI)
- fees: 7.5 bps taker / -1 bp maker; slip: 5 bps
- data_hash, config_hash sweep koşumunda otomatik damgalanacak

---

## 11. Notlar (anti-bias)

- "Mantıklı duruyor" gerekçesi yetmez — sweep ABSOLUTE p < 0.00714 olmadan promote yok.
- Pre-registration **kod yazılmadan önce** yapıldı (commit edilecek). Bundan sonra config/aralık değişmez — değişirse yeni hipotez (`-v2` suffix).
- Bu hipotez **active live champion'a alternatif değil — augment ihtimali test**. Live `vsa_climax_test` (vol_sma_mult=2.5) **aksini test ispatlamadıkça** dokunulmaz.
- vsa_climax_test'in mevcut canlı mean R'si +0.586 — hedef +0.700 (>%19 iyileşme). Bu eşik kazara aşılmasın diye Bonferroni + walk-forward + shuffle baseline üçlü kalkan.

---

## 12. Sonraki Adımlar (research workflow)

1. **(şimdi)** Hipotez commit → hash dondur.
2. Lab Scientist + Risk Officer + Adversary review (`requested_review_from`).
3. ACK sonrası `backtest/engine.py` ile 7-nokta sweep — `walk_forward.py` 3y/6m step 3m.
4. Robustness suite (SOP-3 tamamı).
5. Sonuç raporu `reports/research/vsa-climax-vol-z-sweep-2026-06-29.html`.
6. Karar dokümanı (terfi/iterate/red) → SOP-4 akışı.

---

**Pre-registration kapanışı:** Bu dokümanın hash'i commit ile dondurulduktan sonra **iddia, aralık, gate, Bonferroni n, stop criteria** değişmez. Değişiklik = yeni hipotez (`-v2`), eski statusu `SUPERSEDED`.
