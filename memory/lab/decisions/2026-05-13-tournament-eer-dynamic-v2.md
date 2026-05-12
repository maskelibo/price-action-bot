---
adr_id: LAB-ADR-2026-05-13-002
agent: lab_scientist
type: tournament_protocol
status: SCHEDULED (W3, 26 May - 2 Jun 2026)
date: 2026-05-13
title: "Tournament Protocol — Champion BALANCED+drop_pairs vs Challenger EER-DYNAMIC v2"
related:
  - memory/lab/decisions/2026-05-12-dynamic-v098-killed.md
  - reports/ceo/2026-05-12-brief.md (3, 4.3)
  - memory/researcher/hypotheses/2026-05-13-eer-score-v1.md (pending Researcher)
hash: lab_tournament_2026-05-13_v1
confidence: high
---

# Tournament Protocol — EER-DYNAMIC v2 vs BALANCED+drop_pairs

> Bu dokuman W3 tournament'inin **pre-registered** protokoludur.
> Tournament W3'te calisacak; gate'ler bu dosyada **sabit** ve gevsetilemez.

## 1. Champion & Challenger

| Rol | Strateji | Yaml | Kaynak |
|---|---|---|---|
| Champion | **BALANCED+drop_pairs** | `configs/risk_balanced.yaml` (W1 commit sonrasi, drop_pairs YAML loader aktif) | v0.9.7 BALANCED+F&G + ablation drop_pairs (en kotu 10 hucre cikarilmis) |
| Challenger | **EER-DYNAMIC v2** | `configs/risk_dynamic_v2.yaml` (W3 olusturulacak) | Tier sizing = EER-Score percentile, conf'a degil edge'e bagli |

**Onkosul (Challenger icin)**: Researcher EER-Score v1 prototip W2 sonu hazir olmali (`scripts/eer_v1_walkforward.py`, OOS Sharpe > ham conf + 0.20).

## 2. Test Setup (sabit)

### Veri pencereleri
- **Walk-forward**: 6 ay walk-forward, OOS dilimleri.
- **In-sample**: 24 ay, **out-of-sample**: 6 ay, step **3 ay**.
- 5y veri uzerinde toplam ~7 OOS dilim.
- **Regime split**: bull / bear / range — BTC EMA200 + 90d DD + ATR% bucket'lari ile her dilim regime'e atanir.

### Sample/n gerekleri
- Her dilimde min 30 trade (BALANCED) — yoksa dilim drop.
- Tournament total min 5 OOS dilim (yoksa "yetersiz" karari).

### Cost model
- Production cost model: slip 0.0008, fee 0.0005, funding ortalamasi cogu sembolde 0.0001 / 8h (BTC funding live ise apply).
- Cost-stress senaryosu: ek **+%0.05 slip + %0.03 fee** stress run — sadece bilgi amacli (rapora dahil edilir, terfi karari bagimsiz).

### Sizing
- Her iki konfigte ayni risk butcesi tavanı (notional cap 0.30, max conc per symbol 0.20).
- Champion: ham %4 risk (BALANCED), drop_pairs aktif.
- Challenger: EER tier-sizing — tier dagilimi **60/25/10/5** percentile-cut (sabit) → risk %2/%4/%6/%7 + lev 3x/4x/5x.

## 3. Terfi Gate'leri (4 kati zorunlu)

> **Hepsi PASS olmali. Tek gate kalirsa NO-PROMOTE.**

### Gate 1 — DSR (Deflated Sharpe Ratio) p < 0.05

- Bao 2014 DSR formulu (multiple-testing-aware).
- N_trials = Researcher hipotez sayisi (EER + bootstrap variants ~ 30 trial).
- p-value bootstrap (B=10,000 random sample).
- **Pass**: DSR_p < 0.05.

### Gate 2 — Effect size > +%15 yillik (challenger - champion)

- Tournament total period (5 OOS dilim agregesi) yillik return delta.
- **Pass**: ann_challenger - ann_champion >= **+15.0pp**.

### Gate 3 — MaxDD challenger <= champion + %5 mutlak

- Walk-forward boyunca her dilim MaxDD'leri agrege, **mutlak deger**.
- **Pass**: max(MaxDD_challenger) <= max(MaxDD_champion) + 5.0pp.
- Ornek: champion DD -%30 ise challenger DD <= -%35.

### Gate 4 — Rejim coverage (3 rejimden >=2 pozitif)

- Her dilimi BTC regime'ine bucketle: bull / bear / range.
- Her rejim icin median ann_return challenger.
- **Pass**: 3 rejimden en az 2'sinde median(ann_challenger) > 0 VE > median(ann_champion).

## 4. Terfi Karari Tablosu

| Gate1 (DSR p<0.05) | Gate2 (effect>+15pp) | Gate3 (DD floor) | Gate4 (2/3 rejim) | Karar |
|:---:|:---:|:---:|:---:|---|
| ✅ | ✅ | ✅ | ✅ | **TERFI** — CEO brief'e gonder, insan onayi kuyruga at |
| Herhangi biri ❌ | | | | **NO-PROMOTE** — "needs more evidence" raporu, EER tasariminda revize |
| 3/4 PASS | | | | **CONDITIONAL** — sample-size yetersiz mi, bir sonraki ay tekrar; aksi NO-PROMOTE |

## 5. Yapilmayacaklar (Hard Limits — yasaklar)

- ❌ **In-sample (24 ay) gate'ler**. Sadece OOS dilimler.
- ❌ Gate'leri sonradan gevsetmek (`p < 0.10`, `+10pp effect`, vb.).
- ❌ "Iyi gun" cherry-pick — tum walk-forward dilimleri raporlanir, hicbiri silinmez.
- ❌ Multiple-testing duzeltmesi atlanmasi.
- ❌ Challenger'in champion sample'ina (in-sample period'a) tuning yapilmasi (Researcher pre-registered hipotezi disinda).
- ❌ **EER-Score Researcher W2 raporu PASS olmadan tournament baslatma** (Researcher gate: OOS Sharpe alpha > ham conf + 0.20, shuffle p < 0.05).

## 6. Output Format

```markdown
# Tournament Report — Week 22 (26 May - 2 Jun 2026)
- Champion: BALANCED+drop_pairs
- Challenger: EER-DYNAMIC v2
- OOS dilim sayisi: 7
- Total trade: champion N=?, challenger N=?

## Genel Tablo
| Dilim | Champion ann% | Challenger ann% | Effect | Champion DD% | Challenger DD% | Rejim |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | ... | ... | ... | ... | ... | bull |
| ... | | | | | | |

## Gate Sonucu
| Gate | Esik | Olcum | PASS/FAIL |
| 1 DSR p<0.05 | 0.05 | ... | ... |
| 2 Effect >+15pp | +15.0 | ... | ... |
| 3 DD floor | <=+5pp | ... | ... |
| 4 Rejim 2/3 | 2/3 | ... | ... |

## Karar
- TERFI / NO-PROMOTE / CONDITIONAL
- Gerekce: ...

## Insan Onayina Sunulan
- (Sadece TERFI durumunda)
```

Cikti dosyasi: `reports/lab/tournament-2026-W22.md`.

## 7. Drift Detection Bagi

Tournament TERFI ederse, paper trade gecisinde drift detection referansi guncellenir:
- Yeni baseline: **EER-DYNAMIC v2 walk-forward returns** dagilimi.
- Eski baseline arsivlenir: `memory/lab/drift_baselines/2026-05-13-balanced-drop-pairs-baseline.json`.

Detay icin: `memory/lab/learning_20260513_drift_detection_update.md`.

## 8. Ikincil Tournament Aday: vol_spike_bull_rev (W4)

> Bu W3 tournament'i degil — W4'te ayri bir tournament dilimi acilacak.

- Strateji: `vol_spike_bull_rev` (1d proxy, mevcut envantere bakilir).
- Statu: standalone yillik +%14, DD -%16, 13/13 pencere pozitif, n=58.
- Rol: **filter / boost candidate**, standalone strateji degil — production sinyallerine size-multiplier veya conf-bump entegrasyonu test edilecek.
- Tournament setup: ayni 4 gate, ama "champion" = mevcut BALANCED+drop_pairs (W1 commit sonrasi), "challenger" = BALANCED+drop_pairs + vol_spike size-boost (size *= 1.5 vol_spike günleri).
- Yasak: 1m OHLCV yokken full microstructure tournament — proxy ile devam.

Detay: `memory/lab_scientist/learning_20260512_microstructure_inventory.md` § 5.

## 9. Pre-Registration Tarihleri

| Adim | Tarih | Cikti |
|---|---|---|
| Protokol pre-register | 2026-05-13 | bu dosya |
| Researcher EER prototip | W2 sonu (2026-05-26) | `scripts/eer_v1_walkforward.py` + raporda OOS Sharpe alpha |
| Tournament calistir | W3 (26 May - 2 Jun) | `reports/lab/tournament-2026-W22.md` |
| Karar (TERFI / NO-PROMOTE) | 2026-06-02 | CEO brief'e ekle |
| Insan onayi (gerekirse) | 2026-06-02 - 06-09 | onay kuyrugu |

## 10. Sign-off

- Yazan: lab_scientist (LLM)
- Pre-registered: 2026-05-13
- Bu protokolu acan: CEO direktif (`reports/ceo/2026-05-12-brief.md` 3.W3, 4.3.4)
- Hash: `lab_tournament_2026-05-13_v1`
- Geri-cevrilebilirlik: tournament sonucu reproducibility hash'i ile saklanir; sonradan revize edilemez.
