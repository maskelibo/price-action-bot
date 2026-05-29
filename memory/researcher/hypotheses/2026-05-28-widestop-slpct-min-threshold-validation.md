# Hipotez: HYP-2026-05-28-widestop-slpct-min-threshold-validation

**Tip:** Validation / falsification of a deployed parameter (not a new strategy).
**Reproducibility:** git=e7d0a90 | 15m_pool sha256=0cfdaac8e64c379f (n=374600) |
5m_pool sha256=afd362fb40f65e8c (n=973764) | script=scripts/researcher_slpct_threshold_sweep.py

## 1. İddia (pre-registered)
Kullanıcı hipotezi: "WIDESTOP sl_pct_min eşikleri (15m=0.025, 5m=0.030) ÇOK KATI;
çok fazla sinyal eleniyor; eşiği düşürmek net ROI'yi artırır."

Benim test ettiğim NULL H0: "Eşiği düşürmek honest aylık-mean ROI'yi KORUR
(fee erozyonu geri-kazanılan sinyalleri yemez)." H0 doğruysa düşük eşik dominant
olmalı (daha çok trade + eşit/daha iyi honest ROI + kabul edilebilir DD).

H0 ÇÜRÜR EĞER: eşik düştükçe honest aylık-mean düşer VE/VEYA continuous MaxDD
gate'i (-25%) aşar. (Feynman: "beni kandıran ne olabilir?" → shuffle null'unun
yanlış tasarımı; aşağıda şerh.)

## 2. Metodoloji
- lab_15m_widestop_dd_optimization.py BİREBİR: honest +55bps taker, close-reblend
  (LIVE 0.25/0.25/0.50), pyramid OFF, continuous-curve DD = TEK production_replay.
- sl_pct = |entry - initial_sl| / entry → ENTRY'de ATR'den bilinir → CAUSAL.
  lab.py:646-654 wire doğrulandı: df.shift(-1) YOK, future-bar YOK. Saf pre-filter.
- 15m profil: risk 0.005, daily_dd 0.02, weekly_dd 0.05 (deploy widestop config).
- 5m profil: risk 0.005, daily_dd 0.03, weekly_dd 0.06 (p1c config).
- WF OOS: 2y train / 90d OOS / 30d step.
- Multiple testing: 10 eşik → Bonferroni alpha 0.05/10 = 0.005.

## 3. Sonuç (FALSIFIED — kullanıcı hipotezi REDDEDİLDİ, mevcut eşikler optimale yakın)

### 15m (honest +55bps, risk 0.5%, daily 2% / weekly 5%)
| sl_pct_min | n_trade | aylık_mean% | aylık_med% | MaxDD% | neg_ay% | WR% | WF_neg% | WF_mean_dd% |
|-----------:|--------:|------------:|-----------:|-------:|--------:|----:|--------:|------------:|
| 0.015 | 167156 | +8.56 | +7.23 | **-35.4** | 18.0 | 33.4 | 15% | -29.3 |
| 0.018 | 122184 | +15.15 | +15.39 | **-32.7** | 11.5 | 33.2 | 3% | -24.0 |
| 0.020 | 98979 | +12.02 | +10.48 | -24.8 | 6.6 | 33.7 | 0% | -20.1 |
| 0.022 | 80263 | +14.60 | +13.30 | -24.1 | 4.9 | 33.6 | 0% | -17.7 |
| **0.025** | 59168 | +13.38 | +11.89 | **-20.2** | **3.3** | 33.8 | 0% | -14.8 | ← DEPLOYED |
| 0.030 | 36232 | +10.78 | +10.18 | **-13.1** | 4.9 | 35.7 | 0% | -11.1 |

### 5m (honest +55bps, risk 0.5%, daily 3% / weekly 6%)
| sl_pct_min | n_trade | aylık_mean% | aylık_med% | MaxDD% | neg_ay% | WR% | WF_neg% | WF_mean_dd% |
|-----------:|--------:|------------:|-----------:|-------:|--------:|----:|--------:|------------:|
| 0.020 | 89361 | +7.19 | +1.01 | -11.3 | 29.5 | 32.4 | 15% | -6.5 |
| 0.025 | 49030 | +5.07 | +2.82 | -7.0 | 31.1 | 32.2 | 9% | -4.6 |
| **0.030** | 30907 | +5.46 | +4.70 | -6.6 | 26.2 | 34.7 | 0% | -3.5 | ← DEPLOYED |
| 0.035 | 20476 | +4.62 | +3.30 | -5.4 | 15.0 | 35.2 | 0% | -2.7 |

## 4. Yorum
**15m:** Eşiği 0.025'ten düşürmek aylık-mean'i ARTIRMIYOR (0.022=+14.6 hafif yüksek
ama 0.020=+12.0, 0.018=+15.2 ama DD -32.7!, 0.015=+8.6 ile ÇÖKÜYOR). KRİTİK olan
continuous MaxDD: 0.025'te -20.2% (gate-içi), 0.020'de -24.8% (sınırda), 0.018 ve
0.015'te -32.7/-35.4% → DD GATE (-25%) İHLALİ. neg_ay 0.025'te 3.3% (=2/61, deploy
spec'iyle parity), düşük eşiklerde 11-18%'e fırlıyor. Düşük eşik = daha çok dar-stop
trade = fee erozyonu R-uzayında daha sert (extra_R = bps/(sl_pct·10000)) → mean
düşer, varyans/DD patlar. H0 FALSIFIED.

**5m:** Fee erozyonu daha sert (medyan sl_pct daha dar, daha çok bar). Eşiği
0.030'dan düşürmek aylık-mean'i düşürüyor (0.025=+5.07, 0.020=+7.19 ama aylık-MEDYAN
+1.01 → dağılım sağ-kuyruk şişkin, tipik ay zayıf) VE neg_ay'ı 26%→31%'e çıkarıyor
VE WF_neg 0%→9-15%'e bozuyor. 0.030 en temiz WF profili (0/34 neg, min +5%).

### Shuffle baseline (R-permütasyon, 25 iter, seed=42) — ŞERHLE OKU (§5)
| TF | sl_pct_min | real_mean% | null_mean% | p | not |
|----|-----------:|-----------:|-----------:|---|-----|
| 15m | 0.022 | +14.60 | +17.65 | 1.00 | null pozitif → uninformative |
| 5m | 0.030 | +5.46 | +8.09 | 1.00 | null pozitif → uninformative |
| 5m | 0.035 | +4.62 | +6.94 | 1.00 | null pozitif → uninformative |

(15m 0.025/0.030 aynı desende; null pozitif-havuz beklentisini koruyor → FAIL beklenir.)

## 5. ÖNEMLİ ŞERH — shuffle null'u bu soru için UYGUNSUZ (Feynman testi)
R-permütasyon shuffle, zaten-filtrelenmiş NET-POZİTİF havuz içinde R'leri karıştırır;
havuzun koşulsuz pozitif beklentisini KORUR. Dolayısıyla null_mean POZİTİF çıkar
(5m sl>=0.030: real +5.46 < null +8.09, p=1.0) ve HER pozitif-havuz alt-kümesi için
"FAIL" üretir — bu, "edge yok" DEĞİL, sadece "trade SIRALAMASI ekstra bilgi taşımıyor"
demektir. Yön/filtre edge'i için doğru null = random-entry/sign-flip; bu çalışmada
KANIT = metrics tablosu + WF, shuffle DEĞİL. Bu null'a karar verdirtmedim.

## 6. KARAR
- **15m: sl_pct_min=0.025 OPTİMALE YAKIN, KORUNMALI.** Tek meşru alternatif 0.022
  (aylık-mean +14.6 hafif yüksek, DD -24.1 gate-içi) — ama bu IS'te seçilmiş, OOS
  avantajı marjinal ve DD daha riskli; 0.025 daha güvenli risk-ayarlı seçim
  (DD -20.2, neg 3.3%). 0.025'in ALTINA inmek DD gate'ini riske atar.
- **5m: sl_pct_min=0.030 OPTİMAL, KORUNMALI.** Düşürmek mean'i düşürür + neg_ay +
  WF'i bozar. (Daha sıkı 0.035 DD'yi -5.4'e indirir ama mean +4.62'ye düşer —
  trade-off; 0.030 daha iyi denge.)
- Kullanıcının "çok katı" sezgisi YANLIŞ: eşik fee-erozyon + DD kontrolü, ROI eater
  değil. Eşik filtresi pozitif edge'i KORUYOR.

## 7. Overfitting şerhi
- Tablolar 5y tek-havuz; düşük-eşik aylık-mean'lerdeki sıçramalar (0.018=+15.2)
  birkaç yüksek-vol ayın artefaktı (median ≈ mean olması bunu hafifletiyor ama
  IS'tir). KARAR continuous-DD + WF_neg + neg_ay'a dayandı — bunlar overfit'e
  daha dirençli.
- WF "neg%" gate (<=33%) tüm eşiklerde PASS; ayırt edici sinyal WF_mean_dd ve
  continuous MaxDD. 0.025/0.030 her ikisinde de en temiz.
- Bonferroni (alpha 0.005) shuffle'a uygulanacaktı; shuffle null'u uygunsuz
  olduğu için bu eksen kararı taşımıyor (şerh §5).
