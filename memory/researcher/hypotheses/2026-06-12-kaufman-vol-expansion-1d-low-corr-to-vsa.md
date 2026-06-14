---
doc_id: researcher-20260612T093000-kaufman-vol-expansion-1d-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-12T09:30:00Z
status: PROPOSED
confidence: low
depends_on:
  - researcher-2026-06-11-kaufman-volatility-breakout-1h-low-corr-to-vsa
  - researcher-2026-06-11-vsa-climax-widestop-slpct-sweep-seed-abort-v5
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, low-corr-vsa, kaufman, volatility-expansion, daily, multiple-testing-concern]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-06-12-kaufman-vol-expansion-1d-low-corr-to-vsa

- Tarih: 2026-06-12
- Versiyon: 0.1 (pre-registration; kod yok, sweep yok)
- Seed: "Cross-strategy edge keşfi: aktif vsa_climax_test ile düşük korelasyonlu ek bir strateji."

## 1. İddia (tek cümle, ölçülebilir)

> Üç yıllık (2023-06-12 → 2026-06-12) USDT-perpetual evreninde (delisting dahil, ~30 sembol),
> **1D timeframe**'de, önceki bar kapanış fiyatından **+0.75 × ATR(14)** yukarı stop-order tetiklenen
> long-only girişler (entry = prevclose + 0.75 × ATR14; SL = entry − 1.5 × ATR14; TP = entry + 2.0 × ATR14;
> max holding = 5 bar, sonra force-close), fees=7.5 bps taker + slippage=5 bps modeli altında:
>
> - Annualized net return ≥ **%25**
> - **Sharpe ≥ 0.8** (OOS, walk-forward ortalaması)
> - **MaxDD ≤ %30** (account-equity tabanlı, log dolar değil)
> - **Pearson korelasyon (günlük P&L) ≤ 0.25** vsa_climax_test canlı P&L'iyle (30 günlük rolling)
> - **DSR > 0.5**, **PBO < 0.5**, IS-Sharpe / OOS-Sharpe oranı **< 3.0** (Lopez kriterleri)
> - **Shuffle-baseline p < 0.05**, **Bonferroni-corrected p < 0.0016** (α=0.05 / N=31 önceki low-corr-vsa aday)

## 2. Null Hipotez (ne çürür)

H0: 1D Kaufman vol-expansion girişi rastgele entry'den ayırt edilemez — yani **shuffle baseline'ı yenmiyor**
(p ≥ 0.05), **OR** düşük-korr iddiası tutmuyor (corr > 0.25), **OR** DSR ≤ 0.5.

Bu üç koşuldan **biri** kırmızıysa hipotez REDDEDILIR — DD/Sharpe iyi olsa bile.

## 3. Gerekçe (RAG referansları)

- **[Kaufman summary §"Volatility Expansion Entry"]** — Open + k×ATR(14) yukarı stop emri,
  k=0.5-1.0 tipik. "Intraday momentum capture; yüksek win rate (~%55) küçük R ile." (RAG #5)
- **[Kaufman summary §"Channel Breakout"]** — 20-bar high/low kırılımı, trailing exit; "Asimetrik
  R-multiple; %35 win rate ile pozitif beklenti." (RAG #7) — referans karşılaştırma için, mekanizma
  farklı (channel vs ATR-distance).
- **[Lopez de Prado, Advances in Financial ML]** — DSR/PBO/MinBTL kriterleri; IS-Sharpe > 3×OOS-Sharpe
  red. (RAG #1) — bu hipotezin promotion gate'i.
- **[Chan, Algorithmic Trading]** — "Regime-conditional ensemble"; vol-expansion'ı VSA reversal ile
  ensemble adayı olarak konumlandırıyor. (RAG #9)

**Mekanik karşıtlık (vsa_climax_test ile):**
- vsa_climax_test = **15m**, **volume-z spike**, **exhaustion reversal** (climax fade).
- Bu hipotez = **1D**, **price-distance breakout**, **continuation momentum** (no volume input).
- Farklı timeframe + farklı feature ailesi + farklı yön karakterleri (reversal vs continuation) →
  **a priori düşük korr beklenir**, ama bu **ölçülecek**, iddia edilmiyor.

## 4. Dependent Variables (ölçülecek metrikler)

| Metric | Hedef | Lopez/Bonferroni gate |
|---|---|---|
| Annualized net return (OOS ort.) | ≥ 25% | — |
| Sharpe (OOS ort.) | ≥ 0.8 | — |
| MaxDD (account-equity tabanlı) | ≤ 30% | — |
| Profit factor | ≥ 1.3 | — |
| Win rate | info (~%45 beklenti) | — |
| Trade sayısı (3y, evren) | ≥ 300 (per-symbol ≥ 10) | < 300 → istatistik anlamsız → RED |
| **Corr (1D P&L vs vsa_climax 30d rolling)** | **≤ 0.25** | > 0.25 → low-corr iddiası çürür → RED |
| **DSR** | **> 0.5** | ≤ 0.5 → RED |
| **PBO** | **< 0.5** | ≥ 0.5 → RED |
| **IS/OOS Sharpe oranı** | **< 3.0** | ≥ 3.0 → overfit → RED |
| **Shuffle-baseline p** | **< 0.05** | ≥ 0.05 → RED |
| **Bonferroni-corrected p (α=0.05/31)** | **< 0.0016** | ≥ 0.0016 → multiple-testing aşılmadı → RED |

## 5. Independent Variables (DONDURULMUŞ — sweep YASAK)

| Param | Değer | Sweep? | Gerekçe |
|---|---|---|---|
| Timeframe | 1D | ❌ | 1H zaten denendi (HYP 2026-06-11) — sweep multi-testing katlar |
| Entry trigger | prevclose + **0.75** × ATR(14) | ❌ | k=0.75 = Kaufman default literatür ortası, sweep yasak |
| ATR window | **14** | ❌ | Wilder standard; sweep yasak |
| SL | entry − **1.5** × ATR(14) | ❌ | Kaufman default |
| TP | entry + **2.0** × ATR(14) | ❌ | R:R = 1.33; Kaufman 2×ATR |
| Max holding | **5 bar** (force-close) | ❌ | Kaufman "bar/gün sonu kapanış" → daily için 5d kabul edilebilir orta |
| Direction | **long-only** | ❌ | Kripto upward drift bias; short'u v2'ye bırakacağız |
| Universe | 19sym pool (vsa_climax_test ile aynı) | ❌ | Survivorship-clean, delisting dahil |
| Risk per trade | **%1** | ❌ | Standart |

**Toplam serbest parametre = 0** (hepsi literatür default'undan). Lopez'in "params/N > 1/30" kriteri
otomatik ✓ — ama bu KURALA-UYUM'dur, edge garantisi DEĞIL.

## 6. Beklenen p-value

- Shuffle baseline (1000 permütasyon): **p_expected < 0.01** — eğer edge varsa.
- Bonferroni hedef: **p < 0.0016** (N=31 = bu + 30 önceki low-corr-vsa hipotezi).
- BH-FDR alternatif (daha hafif): q < 0.05 — Bonferroni başaramazsa fallback.

**Kritik:** Eğer p Bonferroni'yi GEÇERSE BH-FDR'a indirimsiz GEÇİŞ YASAK. Sadece Bonferroni FAIL +
BH-FDR PASS = "muhtemel edge, ek validasyon gerek" notu, **terfi DEĞİL**.

## 7. Stop Criteria (araştırma terkedilecek koşullar)

İlk in-sample backtest sonucu aşağıdakilerden **birini** karşılıyorsa araştırma derhal durdurulur,
v0.2'ye versionlanmaz, walk-forward bile yapılmaz:

1. **Trade sayısı < 200** (3y, tüm evren) → kalıp çok seyrek, istatistik anlamsız.
2. **IS Sharpe < 0.5** → edge zayıf, OOS daha da kötü olur (Lopez kuralı).
3. **WR < %35** → R:R 1.33 ile pozitif olamaz (40% × 2 − 60% × 1.5 = −0.1).
4. **MaxDD > %40 in-sample** → risk profili kabul edilemez.
5. **Corr (1D P&L vs vsa_climax_test live 30d) > 0.40 in-sample** → düşük-korr iddiası baştan çürür.

## 8. Curve-fit / Multiple-testing Şüphesi (BİLİNÇLİ İŞARETLEME)

> **Bu bölüm hipotezi rededer durumda doğmak üzere uyarı.**

- **31 inci** low-corr-vsa aday. Eğer her aday α=0.05'te bağımsız olsa, en az 1'i şans eseri
  pozitif çıkar (E[pos] = 31 × 0.05 = 1.55). Bu hipotez tek başına anlamlı görünse bile, **havuz
  içinde** anlamsız olabilir.
- Bonferroni α=0.0016 zorunluğu tam bu nedenle eklendi.
- **Kabul/Red karar gücü Lab Scientist'tedir** — tournament gate (DSR p<0.05 + effect ≥15% + MaxDD ≤
  champion+5%) bu hipotezin kapısıdır. Backtest "iyi" çıksa bile Lab bu Bonferroni'yi uygulamadan
  promosyon YOK.
- **Çürütülebilir tahmin:** Bonferroni sonrası ~%80 olasılıkla **RED** olur. Pozitif çıkarsa nadir
  ve değerli bilgi.

## 9. Reproducibility Stamps (post-execution)

- git: TBD (backtest run'da damgalanacak)
- config: TBD
- data: pool_19sym_20260610_E1 (vsa_climax_test ile aynı evren)
- seed: 42 (shuffle baseline için)

## 10. Sonraki Adımlar

1. **Bu hipotez commit edilir → hash dondurulur.** (Pre-registration tamam.)
2. SOP-2 Backtest yürütme — `backtest/engine.py` çağrısı, **kalibrasyon YOK**, parametre **DONDURULMUŞ**.
3. Stop-criteria check (madde 7) — geçemezse RED, learning.md'ye 3 satır.
4. Geçerse SOP-3 robustness suite (8 test).
5. Bonferroni + DSR/PBO hesabı.
6. Karar: terfi adayı / RED / "belirsiz, ek veri".

## 11. Self-Awareness (Researcher persona notu)

Bu hipotezi yazarken kendi bias'larıma karşı uyanık:
- **Anchoring bias:** Önceki 30 low-corr aday üzerinden yazıyorum — "bir tane tutarsa" baskısı
  ölçüm gücümü çarpıtabilir. Bonferroni bunun panzehri.
- **Narrative bias:** "Kaufman literatürü güzel anlatıyor" hipotezi kabul gerekçesi DEĞIL.
- **Recency bias:** vsa_climax_test'in son canlı performansı (drawdown) "tamamlayıcı arama"yı
  hızlandırıyor. Bu acelecilik = curve-fit riski. Bonferroni katı, kasıtlı olarak katı.
- **Stop criteria reddi: yüksek olasılık.** Bu sağlıklı. "Reject more than you accept."
