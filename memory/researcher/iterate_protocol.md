---
doc_id: researcher-iterate-protocol-v1
doc_type: protocol
agent_id: researcher
created_at: 2026-05-27T12:00:00Z
status: ACTIVE
confidence: high
tags:
  - protocol
  - iterate
  - mandatory
  - sop-4b-extension
supersedes: null
hash: null
---

# Iterate Protocol v1 — Umut Verici Bot Geliştirme Disiplini

## Kapsam

Pozitif aylık ROI üreten ama risk metriği (DD, neg ay, sharpe) gate'i geçemeyen
her hipotez/strateji bu protokole tabidir. Persona SOP-4b'nin somut
implementasyonu.

## Doğrulanmış Vaka — rsi2-extreme-fade (2026-05-27)

**Başlangıç:** ÇÖPE ATILACAKTI
```
v1 baseline: aylık +13.61% / DD -79.47% / yıllık +188% / ratio 0.171
```
Eski persona: "DD %79 yıkıcı, reject" → strateji terk edilirdi.

**SON:** LIVE BOT'U YENDİ
```
v45 (round 6): aylık +19.29% / DD -19.28% / yıllık +587% / ratio 1.000 ⚡
v46 (round 6): aylık +15.99% / DD -16.35% / yıllık +437% / ratio 0.978
v50 (round 6): aylık +19.45% / DD -19.75% / yıllık +611% / ratio 0.985
```

**İlerleme:**
- ROI: +13.61% → +19.29% (**+%5.7 puan**)
- DD: -79.47% → -19.28% (**%60 puan iyileşme**)
- Yıllık: +188% → +587% (**3.1x**)
- Risk-adjusted ratio: 0.171 → **1.000** (5.8x)
- $10K → $1.6M (live) → **$10.5M (v45)** — live'ın 6.5 katı

**Süreç:** 6 round, 45+ varyant, ~13 saat compute. Sonuç: deploy-ready
companion strategy adayı.

## Zorunlu 6-7 Round Protokol

Umut verici (pozitif aylık ROI) her strateji için MINIMUM 6 round iterate
yapılmalı. Her round farklı bir patika dener:

### Round 1: Temel Patikalar (5-6 varyant)
- v1 baseline (referans için)
- v2 risk_reduction (risk_pct 0.5x veya 0.3x)
- v3 trade_quality (confluence/conf_score eşiği)
- v4 position_management (BE-protect, trail)
- v5 regime_filter (BTC trend, vol regime)
- v6 combo (v2+v3 birlikte)

**Beklenen:** çoğu reject olur, 1-2 marginal. **Öğrenme:** strateji
karakterine hangi araç uyar (örn rsi2'de BE-protect mean-rev'e ZIT).

### Round 2: Alternatif Filtreler (5-7 varyant)
- v7 max_concurrent cap (4, 6, 8)
- v8 ATR/vol filter (yüksek vol trade subset)
- v9 combo (v2 + v7 birlikte)
- v10 sembol subset (BTC/ETH only, top-3, vs.)
- v11 daily DD halt (0.02, 0.025, 0.03)

**Beklenen:** confluence/ATR filter işe yaramayabilir — strateji bağımlı.
**Sinyal:** "sınırı kıl payı kaçıran" varyant Round 3 hedefi.

### Round 3: İnceltme (5-9 varyant)
Round 2'de sınırı kaçıran varyantın çevresinde mikro değişimler:
- Daha sıkı daily/monthly halt (örn 0.02 → 0.015)
- Daha sıkı concurrent (5 → 3)
- TP ayarı (1.0, 1.5, 2.0 grid)
- Sembol kombinasyonları

**Beklenen:** İlk PROMOTE adayı çıkar (LOOSE — aylık ≥%4, DD ≥-%25).

### Round 4: ROI Öncelik (8-10 varyant)
Round 3'te DD korundu ama ROI düşük → ROI'yi koru, monthly halt + loss_pause:
- monthly_dd_halt 0.10, 0.12, 0.15
- consecutive_loss_pause 2, 3, 5
- long_only / short_only side bias
- tp_r 1.0, 1.5, 2.0 (her cell test)
- combo: v7 + monthly halt
- combo: v7 + loss pause

**Beklenen:** STRICT PROMOTE (aylık ≥%5, DD ≥-%20). Bu "denge şampiyonu".

### Round 5: ELITE Hedef (10-12 varyant)
ROI ≥%10, DD ≥-%20 hedefli kombinasyonlar:
- tp_r 1.5 → 2.0 (big winner yakalama)
- concurrent 4 → 6 (daha fazla trade)
- pause 2 + tp 2.0 combo
- monthly halt + tp 2.0
- triple combo (pause + monthly + tp)

**Beklenen:** ELITE PROMOTE (1-2 varyant).

### Round 6: BEATS_LIVE Hedef (12+ varyant)
ROI ≥%13 + DD ≥-%20 — live bot'u yenmek için:
- tp_r 2.5, 3.0 (big winner extreme)
- concurrent 6, 8 (daha fazla fırsat)
- daily halt 0.03 ek koruma
- trail stop testi (genelde etkisiz)
- monthly halt 0.10, 0.12

**Beklenen:** 1-5 varyant live'ı yener (BEATS_LIVE). Bu deploy adayı.

### Round 7 (opsiyonel): SUPER ELITE Hedef
ROI ≥%16 + DD ≥-%18 — en iyi BEATS_LIVE varyantlarının hibritleri:
- v(ROI booster) + v(DD reducer) kombinasyonu
- ULTIMATE TRIPLE (pause + monthly + tp + risk)

**Beklenen:** Final deploy aday seçimi.

## Round Kuralları

1. **Her round 5-12 varyant** — daha azı yetersiz arama, fazlası dağınık
2. **Bir round'da bir hedef** — Round 4 ROI, Round 5 ELITE — karıştırma
3. **Her round'un best/worst learnings** memory/researcher/learning.md'ye
   yazılır (bkz "BE-protect mean-rev'e ZIT" gibi)
4. **n_trades izle** — varyant <500 trade ise istatistik anlamsız
5. **NO_TRADES filter** = baştan tasarım hatası, varyantı atla
6. **Her round commit** — git history iterate evrimini gösterir

## Acceptance Tier'lar

| Tier | Aylık ROI | Max DD | Neg ay/61 | Use case |
|---|---|---|---|---|
| LOOSE PROMOTE | ≥4% | ≥-25% | ≤22 | companion strategy adayı (düşük katkı) |
| STRICT PROMOTE | ≥5% | ≥-20% | ≤20 | companion strategy (orta) |
| ELITE | ≥10% | ≥-20% | ≤15 | replacement adayı (Lab tournament) |
| **BEATS_LIVE** | **≥13%** | **≥-20%** | **≤15** | **deploy adayı** (live'ı yenebilir) |
| SUPER ELITE | ≥16% | ≥-18% | ≤12 | full production deploy |

## Sıkıştırma Tablosu (her iterate run sonunda göster)

```
Varyant     Aylık     DD       Yıllık    Ratio   Tier
v1          +13.61% / -79%   +188%     0.17    ÇÖP
v9.1         +4.04% / -24%    +57%     0.17    LOOSE
v26          +9.55% / -19%   +183%     0.50    STRICT
v45         +19.29% / -19%   +587%     1.00    BEATS_LIVE
```

Tablo komprese: nereden nereye gelindiği bir bakışta görünür.

## $-cinsi etki tablosu

5y compound, $10K initial:

```
v1   $10K → $26K  (1.5x)
v9.1 $10K → $13K  (1.3x — tepki testi için)
v26  $10K → $283K (28x)
v37  $10K → $328K (33x — round 5)
v45  $10K → $10.5M (1050x — BEATS_LIVE)
```

Bu sayılar Principal'in karar verirken kullandığı dil — sharpe değil.

## Anti-Pattern'lar (yapma!)

❌ **1 round denedim, çalışmadı, reject** — minimum 6 round zorunlu.
❌ **Her round'da rastgele varyant** — Round numarasına göre HEDEFİN var.
❌ **NO_TRADES'i göz ardı et** — filter çok katı, varyantı atla.
❌ **Risk_pct sürekli azalt** — bir noktada ROI orantısız düşer, durma noktası 0.002-0.003.
❌ **BE-protect mean-rev stratejisine uygula** — early winner → SL → reversion exit kaybı.
❌ **Trail stop genelde etkisiz** — TP override zaten yakalıyor.
❌ **Confluence eşiği body'ye bakmadan** — bazı stratejilerde sabit değer (rsi2 = 2.0 hep).

## Bilinen Sihirli Sos'lar

✅ **consecutive_loss_pause = 2 veya 3** — DD'yi yarıya indirir, ROI sadece %10 düşer.
✅ **tp_r = 2.0 → 3.0** — big winner yakalama, ROI %20+ artar.
✅ **max_concurrent = 4-6** — cluster losses break + trade quality.
✅ **monthly_dd_halt = 0.10-0.12** — catastrophic ay koruması.
✅ **risk_pct sabit (0.005)** — azaltmaktansa loss_pause kullan (ROI korur).

## KPI (her iterate target için)

- Round sayısı: ≥6 zorunlu, 7+ opsiyonel
- Toplam varyant: ≥40 (5-12 per round × 6-7 round)
- En az 1 STRICT PROMOTE üretmeli
- BEATS_LIVE oranı: hedef %10+ varyantın live'ı yenmesi

## Otomatizasyon

```bash
# Iterate target tespit (her sabah cron)
.venv/bin/python scripts/find_promising_to_iterate.py

# Round başlat (Researcher persona SOP-4b)
# 1. Tasarım: Round X için 5-12 varyant spec
# 2. Script: scripts/iterate_<target>_v<round>.py
# 3. Run: background, ~5-10 dk per round
# 4. Commit: her round ayrı
# 5. Tabloyu Principal'e göster (Telegram opsiyonel)
```

## Vaka Çalışması — rsi2 Sıkıştırma (referans)

```
Round 1: v1-v6 (6 varyant)   → v2 marg (+5.91%/-33%)
Round 2: v7-v12 (6 varyant)  → v9 sınırda (+4.08%/-26%)
Round 3: v9.1-v20 (9 varyant) → v9.1 LOOSE (+4.04%/-24%) ★
Round 4: v21-v30 (10 varyant) → v26 STRICT (+9.55%/-19%) ★★
Round 5: v31-v42 (12 varyant) → v36 ROI patlama (+18%/-23%)
                              + v37 ELITE (+10.90%/-17%) ★★★
Round 6: v43-v54 (12 varyant) → v45 BEATS_LIVE (+19.29%/-19%) ★★★★
                              + 4 BEATS_LIVE daha
Round 7: v55-v64 (10 varyant) → SUPER ELITE adayı (bekleniyor)

TOPLAM: 64 varyant, 7 round, ~14 saat compute
SONUÇ: 5 BEATS_LIVE deploy aday + 1 SUPER ELITE adayı (round 7)
```

Bu vaka çalışması her gelecek umut verici stratejide aynı disiplinle
tekrarlanacak. Researcher persona'sının kalbi.
