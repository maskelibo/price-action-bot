---
doc_id: researcher-20260613T093000-order-block-4h-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-13T09:30:00Z
status: DRAFT
confidence: med
depends_on:
  - lab_scientist-active-vsa_climax_test
  - shared/facts/exchange_behaviors
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, cross-strategy, low-correlation, order-block, ict, 4h, pre-registration]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-06-13-OB-4H-VSA-DIVERSIFIER

- **Tarih:** 2026-06-13
- **Versiyon:** 0.1 (pre-registration — kod yazılmadan önce)
- **Seed:** Cross-strategy edge keşfi — aktif `vsa_climax_test`'e düşük korelasyonlu ek strateji adayı (raftaki 66'dan).
- **Aday seçimi gerekçesi:** Aşağıdaki taze-olmama / orthogonality filtresinden geçti:
  - Golden Cross 1D (2026-06-01, 2026-06-05) → **tekrar etme**.
  - BOS / CHoCH 1D, Donchian 20/55 1D, Mat Hold / Rising Three 1D-4H, Kaufman ATR/Marubozu/RSI-div, Volman ii/iii 1D, Equal-Highs Sweep 15m → **hepsi yazıldı**.
  - **Order Block (ICT konvansiyonu, displacement-anchored) — saf hâliyle pre-register edilmemiş.** 4H TF, vsa_climax_test'in 15m climax-fade mekaniğine çift-orthogonal (TF + sebep zinciri farklı: structural displacement reaction ≠ volume climax fade).

## 1. İddia (sayısal, ölçülebilir)

> **Universe:** `principal_pool_v11` 19 sembol perp (USDT-M).
> **Periyot:** 2022-01-01 → 2025-12-31 (in-sample 2022-01-01 → 2024-12-31, OOS 2025-01-01 → 2025-12-31).
> **Setup:** 4H bar üzerinde **Bullish Order Block (OB) reaction long**:
>   1. `t-3 .. t-1` bar serisinde **displacement-up** = `(close[t-1] - open[t-3]) / ATR(14)[t-3] >= 1.0` ve seri içinde 3 bar net pozitif.
>   2. **OB = son bearish (kırmızı) bar** displacement'tan ÖNCEKİ son negatif gövdeli bar (lookback ≤ 5 bar).
>   3. **Trigger:** sonraki herhangi bir bar (≤ 10 bar pencere) içinde fiyat OB'un gövde-üst sınırına ≤ 0.2×ATR yaklaşır → bir sonraki bar **open**'ında market long.
>   4. **SL:** OB low − 1.0×ATR(14)[entry].
>   5. **TP:** 2R fixed (BE-protect 1R'de etkin).
>   6. **Bear OB short** simetrik (vice versa).
>   7. Fee 7.5 bps taker, slippage 5 bps.
>   8. Risk per trade: 0.5% (sabit-fraksiyon, compounding YOK — RESUME-2026-06-10 dersi).
>
> **Aşağıdaki TÜM gate'ler eşzamanlı sağlandığında hipotez DOĞRULANIR:**
>
> | Metric | Hedef | Notu |
> |---|---|---|
> | OOS annualized net return | **≥ 12%** (sabit-fraksiyon) | vsa_climax canlı +%10/ay değil — fair-base |
> | OOS Sharpe (annual.) | **≥ 0.7** | Single-asset eşik (Chan, RAG #9) |
> | OOS MaxDD | **≤ 25%** | Sermaye koruma > getiri (shared/lessons leverage) |
> | OOS Profit Factor | **≥ 1.3** | — |
> | OOS Trade count (3y IS + 1y OOS toplam) | **≥ 250** | Lopez de Prado MinBTL eşiği, T-test gücü |
> | IS/OOS Sharpe oranı | **≤ 1.8** (yani OOS, IS'nin en az %55'i) | Lopez "IS > 3×OOS → red" |
> | Shuffle baseline (returns reshuffle, 500 sim) | **p < 0.01** | Bonferroni dahil |
> | **Jaccard overlap with vsa_climax_test signals (aynı bar = aynı sym ± 4 bar tolerans)** | **< 0.10** | Asıl orthogonality testi |
> | **Daily-returns Pearson |r| with vsa_climax_test** | **< 0.20** | Portföy diversifier kriteri |
> | Walk-forward (8 dilim, 36m train / 6m test, step 6m) | **≥ 6/8 dilim pozitif** + dilim Sharpe std < ortalama | RAG #1 madde 6 |
> | Symbol-out CV (leave-one-symbol-out × 19) | **min sym OOS Sharpe ≥ 0.3** | Tek sembole bağımlı değil |
> | Regime split (bull / bear / range) | **en az 2/3'te pozitif** | Tek rejimden beslenmiyor |
> | Stress periyotları (2022-05 LUNA, 2022-11 FTX, 2024-03 ATH, 2024-08 Yen) | **dilim başına DD ≤ 15%** | Yıkıcı kayıp yok |
> | Lookahead-delay test (entry +1 bar gecikme) | **edge'in ≥ %75'i korunur** | Sızıntı yok |

## 2. Null hipotez (çürütme şartı)

H₀: 4H Order Block reaction strateji 19-sym kripto perp evreninde **vsa_climax_test'ten istatistiksel olarak ayırt edilebilir bağımsız edge üretmez**.

H₀ kabul kriterleri (en az biri yeterli → hipotez RED):
- OOS Sharpe < 0.4 (eşik altı edge).
- Shuffle baseline yenilemiyor (p ≥ 0.05).
- Jaccard ≥ 0.20 VEYA |Pearson r| ≥ 0.30 → orthogonality kaybı, "yeni edge" değil.
- Trade N < 150 (3.5y × 19 sym) → istatistik altı güç, deploy mantıksız.
- IS/OOS Sharpe oranı > 2.5 → overfit kuvvetli sinyal.
- WF dilim varyansı ortalamadan büyük (Lopez de Prado kriterleri).
- Lookahead-delay test edge'in > %60'ını yiyor → mikro-yapı zaman sızıntısı.

## 3. Bağımlı değişkenler (önceden listelendi — p-hack engeli)

Birincil:
1. OOS annualized net return (compounding-bağımsız sabit-fraksiyon)
2. OOS Sharpe (annualized; √252 day, daily-equity vary.)
3. OOS MaxDD (% of starting equity, intraday değil bar-close bazlı)
4. **Orthogonality: Jaccard(@4h overlap) + Pearson(daily returns)**

İkincil (raporda görünür ama gate değil):
- Avg R, profit factor, win rate, expectancy, max drawdown duration (gün), avg holding period (bar).
- Per-symbol Sharpe matrix.
- Per-regime decomposition.

**İlave metrik EKLENMEYECEK** sonradan (bilinçli p-hack engeli — RAG #1 Lopez de Prado).

## 4. Bağımsız değişkenler — TÜMÜ DONDURULDU (curve-fit guard)

Bu hipotez **TEK-SET pre-registration**. Hiçbir parametre optimize edilmeyecek, sweep çalıştırılmayacak:

| Parametre | Değer | Kaynak |
|---|---|---|
| TF | 4H | Vsa 15m'ye TF-orthogonal (sabit) |
| displacement_window | 3 bar | ICT konvansiyon literatür standart |
| displacement_threshold | **1.0 × ATR(14)** | RAG #6 "displacement eşiği kalibrasyon gerektirir" — TEK eşik denenir |
| OB tanımı | son opposite-color body bar (lookback ≤ 5) | ICT konvansiyon |
| trigger_window | ≤ 10 bar | Sabit |
| entry trigger tolerance | 0.2 × ATR(14) | Sabit |
| SL | OB low − 1.0 × ATR(14) | Sabit, Brooks atr-stop konvansiyonu |
| TP | 2R fixed | Sabit (RAG #5 Kaufman 2×ATR target benzeri) |
| BE-protect | 1R'de SL → entry | Sabit (mevcut altyapı) |
| risk_pct | 0.5% / trade | shared/lessons fixed |
| Universe | principal_pool_v11 (19 sym) | Sabit |
| Fee model | 7.5 bps taker + 5 bps slippage | Sabit, konservatif |

**Toplam free parameter sweep'i: 0.** Lopez de Prado (RAG #1) "param/sample ratio < 1/30" kuralı için 0/250 = 0 ✓.

## 5. Beklenen p-value ve multiple-testing bütçesi

- Beklenen shuffle-baseline p: **< 0.005** (tek pre-registered test → Bonferroni çarpanı n=1).
- WF 8 dilim parça testi: FDR (BH) düzeltilmiş anlamlılık ≥ 6 dilimde p < 0.05.
- Orthogonality testi (Jaccard < 0.10 + |r| < 0.20): nominal değil, **hard cut-off** (anlamlılık değil eşik).

## 6. Gerekçe (RAG referansları)

- **[RAG #6 — Market Structure & Order Flow]:** "Bullish/Bearish OB | Orta workability | Displacement eşiği kalibrasyonu gerektirir." Pre-reg'de TEK eşik (1.0×ATR) sabit → kalibrasyon ihtiyacı ÖN-VERİLDİ, sonradan sweep yok.
- **[RAG #1 — Lopez de Prado]:** Pre-registration disiplin + multiple-testing bütçesinin temeli. 6 kırmızı bayrak kontrolü zorunlu.
- **[RAG #9 — Chan summary]:** Single-asset eşik OOS Sharpe > 0.8 (biz 0.7'ye gevşettik çünkü diversifier rolü — portfolio etki ölçülecek).
- **[Brooks 2012 ATR-stop]:** SL = swing low − 1×ATR konvansiyonu.
- **vsa_climax_test (mevcut canlı):** 15m, volume + spread climax fade. TF + mekanizma → 4H displacement-reaction ile çift-orthogonal beklenir.

## 7. Curve-fit kırmızı bayrakları — ÖN-KONTROL

| Bayrak | Riskimiz | Mitigation |
|---|---|---|
| Best param ekstrem değerde | **Yok** — sweep yok, tek set | ✓ |
| IS/OOS gap > 50% | Beklenir bir risk | Gate 1.8x = %44 |
| Çok ince param uzayı | Yok | ✓ |
| Trade N düşük | **GERÇEK RİSK** — 4H + OB seyrek olabilir | Gate ≥ 250; <150 → RED |
| Tek periyot baskın katkı | Bilinmiyor | WF + regime split kontrol |
| WF dilim varyansı | Bilinmiyor | Lopez kriteri zorunlu |
| Bonferroni kaybı | n=1 → minimal | ✓ |
| "Hikaye çok mantıklı" bias | ICT topluluğu ego-cult — dikkat | Sayı kazanır; story ignored |

## 8. Stop criteria (araştırma terkedilir)

Aşağıdakilerden **HERHANGI BİRİ** gerçekleşirse hipotez derhal RED + arşiv:
1. IS dönemi (2022-2024) Sharpe < 0.4 → erken kapatma, OOS bile çalıştırılmaz.
2. IS trade N < 180 (3y × 19 sym × 0.003/bar/sym) → istatistik gücü yetersiz.
3. Lookahead-delay test (entry +1 bar gecikme) edge'in > %60'ını yer → kod-seviyesi sızıntı şüphesi.
4. Bonferroni-sonrası shuffle p > 0.05 → şans.
5. Jaccard with vsa_climax ≥ 0.20 → orthogonality yok, "diversifier" iddia çürür.
6. WF 8 dilimden < 4'ü pozitif → kararsız.

**Eğer 5+ koşul sağlanırsa ve sadece DD veya bir tek risk metriği bozulmuşsa → SOP-4b iterate (RED YASAK).**

## 9. İterate patikası (önceden tanımlı — pozitif edge bulunursa)

ROI pozitif + bir risk metriği gate'i geçemezse:
- **v2 risk-reduction:** risk_pct 0.5% → 0.3%, max_concurrent 8→4.
- **v3 confluence filter:** displacement_threshold 1.0 → 1.5 ATR (sadece güçlü displacement'lar).
- **v4 regime gate:** sadece bull veya sadece bear rejim subset.
- **v5 TF micro-shift:** 4H → 1D (eğer 4H trade N düşükse).

Maks 5 iterate. Sonra ya Lab tournament ya "deferred archive".

## 10. Beklenen iş yükü ve teslim

- Backtest engine config dosyası: `configs/strategies/order_block_4h_v1.yaml` (TASLAK — Lab kabulüne kadar).
- Run komutu: `python -m price_action.backtest.engine --strategy order_block_4h --universe principal_pool_v11 --start 2022-01-01 --end 2025-12-31 --fee-bps 7.5 --slip-bps 5`.
- Tahmini compute: ~15 dk (4H × 19 sym × 4 yıl ≈ 70k bar).
- Robustness suite tam (SOP-3, 8 madde).
- Rapor: `reports/research/order-block-4h-2026-06-13.html`.

## 11. Reproducibility

- git_hash: <kod commit'inden sonra doldurulacak>
- config_hash: <SHA256 of order_block_4h_v1.yaml>
- data_hash: <DuckDB principal_pool_v11 4h Parquet snapshot SHA256>
- seed: 42 (shuffle baseline + Optuna kullanılmayacağı için sadece shuffle için)

## 12. Karar yeri (boş — backtest sonrası doldurulacak)

- [ ] Terfi adayı (Lab tournament)
- [ ] İterate (v2-v5 patikası)
- [ ] Red (gerekçeli arşiv)

---

**Bu pre-registration commit edildikten sonra hipotez DONDURULMUŞTUR.** Sonradan parametre değiştirilirse yeni doc (v2, v3...) yazılır; bu doc `supersedes`'e bağlanır.
