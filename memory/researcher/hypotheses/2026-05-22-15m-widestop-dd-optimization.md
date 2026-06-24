# Pre-Registration: HYP-2026-05-22-15m-widestop-dd-optimization

**Lab Scientist — joint optimization pre-registration. Ölçümden (grid run) ÖNCE
yazıldı. IMMUTABLE.**
Tarih: 2026-05-22 | git: feat/pyramid-be-protect

## Bağlam
Researcher (2026-05-21, `reports/researcher/2026-05-21_15m_honest_edge_hunt.md`)
15m wide-stop honest edge buldu: `sl_pct >= %1.8` filtre, honest +55bps taker
altında pool-R **+78.000 R**, aylık-mean ROI **+21.72%**, 8/8 robustness PASS,
WF anti-overfit 0/34 neg.

**KRİTİK ŞERH (Researcher kendi raporunda flag etti):** "+21.72%/ay" = 61
BAĞIMSIZ $10k replay'in ORTALAMASI (`per_month` metodu), sürekli-equity-eğrisi
DEĞİL. Gerçek sürekli-eğri DD **−40.9%** (`production_replay(full_pool)` tek
koşum) — deploy için kabul edilemez. Principal hedefi: 15m dürüst aylık ≥%10
VE deploy-edilebilir DD profili.

## İddia (H1)
**`sl_pct eşiği × risk_pct × DD-throttle` joint optimizasyonuyla, sürekli-equity-
eğrisi DD ≤ −%25 KISITINI sağlayan EN AZ BİR parametre seti vardır VE bu sette
honest (+55bps) aylık mean ROI ≥ %10 korunur.**

Mekanizma: DD −41%'in kaynağı yüksek `risk_pct` (%2) + gevşek DD-throttle. Risk
küçültmek + DD-halt eşiklerini sıkmak DD'yi düşürür; trade-off: getiri sıkışır.
Soru getiri-DD sınırının %10/ay'ın üstünde mi altında mı kaldığı.

## Null hipotez (H0)
DD ≤ −%25 kısıtını sağlayan her parametre setinde honest aylık mean ROI < %10'a
düşer — yani DD-return trade-off'u 15m wide-stop'u %10 hedefinin altına çeker.
Veya: hiçbir parametre seti sürekli-eğri DD ≤ −%25'i sağlamaz.
Çürütür: feasible set boş VEYA tüm feasible adaylarda OOS aylık mean < %10.

## Bağımsız değişkenler (parametre uzayı — grid)
- `sl_pct` eşiği: {0.018, 0.020, 0.022, 0.025, 0.030} (5 nokta)
- `risk_pct`: {0.005, 0.0075, 0.010, 0.015, 0.020} (5 nokta)
- DD-throttle (daily/weekly/monthly DD halt): 4 kademe loose→vtight
  - loose: 0.04/0.08/0.99 (mevcut config)
  - med: 0.03/0.06/0.20
  - tight: 0.025/0.05/0.12
  - vtight: 0.02/0.04/0.08
- `vol_target_atr_pct`: {0.008, 0.010, 0.012} (3 nokta)
- Toplam: 5×5×4×3 = 300 trial

## Bağımlı değişkenler (pre-registered metrikler)
- **Sürekli-eğri DD** = `production_replay(full_pool).max_drawdown` — TEK koşum,
  KANONIK deploy metriği (61-replay ortalaması DEĞİL).
- Aylık mean/median ROI (sürekli-eğri compound zinciri: her ay önceki ayın
  final_equity'sinden başlar — `monthly_on_curve`).
- Negatif ay sayısı, max aylık kayıp, CV.
- WF OOS: 2y train / 90d OOS / 30d step, neg pencere.
- Honest pool-sumR.

## Anti-overfit protokolü
- Parametreler **TRAIN penceresinde** (2021-05-16 → 2024-11-01, ~3.5y) seçilir.
- En iyi adaylar **OOS penceresinde** (2024-11-01 → 2026-05-14, ~1.5y)
  raporlanır. TRAIN→OOS aylık-mean degradasyonu = gerçek overfit metriği.
- FULL 5y sürekli-eğri DD ayrıca raporlanır (deploy = full curve).

## Hedef fonksiyon
TRAIN penceresinde: `DD ≤ −25%` KISITI altında aylık mean ROI maksimize.
Kısıt ihlali → ihlal büyüklüğüyle orantılı ceza (her 1pp ihlal −10 puan).

## Kabul kriteri (HARD gate — deploy adayı için hepsi geçmeli)
1. FULL 5y sürekli-eğri DD ≤ −%25
2. OOS aylık mean ROI ≥ %10
3. OOS negatif ay ≤ %35
4. WF OOS neg pencere ≤ %33
5. TRAIN→OOS aylık-mean degradasyonu < %40 (overfit kontrolü)
6. +65bps stres senaryosunda hâlâ pozitif aylık mean (maliyet duyarlılığı)

## Çoklu test düzeltmesi
300 trial grid. Bonferroni α = 0.05/300 = 0.000167. DSR: N=300 deneme deflation
ağır. Asıl korunak: TRAIN/OOS split (in-sample seçim, OOS rapor). Bu masada EER
v1/v2, ML v1/v2, regime-cond, quasimodo, HTF — HEPSİ RED. Overfit'e paranoyak.

## Önsel tahmin
DD −41% → −25% sıkıştırması yaklaşık `(25/41) ≈ 0.61` risk-ölçeklemesi demek.
Sabit-edge'de getiri lineer ölçeklenirse aylık mean +21.72% × 0.61 ≈ +13.2%.
AMA DD-throttle halt'ları getiriyi NON-lineer kırpar (en iyi ayların bir kısmı
halt'a takılır). Tahminim: feasible set BOŞ DEĞİL ama OOS aylık mean **%6-11
bandına** düşer — %10'u ya tam tutturur ya hafif altında kalır.
Verdict tahminim: **BORDERLINE — deploy-edilebilir set muhtemelen VAR ama aylık
%10 sınırda; net üstü değil.** Strong opinions, loosely held.

## Stop criteria
TRAIN feasible set boşsa → anında "DD kısıtı altında deploy edilemez" hükmü.
OOS aylık mean tüm top-6 adayda < %4 ise → "wide-stop DD-throttle ile %10 yapısal
tavanın üstünde" hükmü.

---

## SONUÇ — (grid run sonrası doldurulacak)
