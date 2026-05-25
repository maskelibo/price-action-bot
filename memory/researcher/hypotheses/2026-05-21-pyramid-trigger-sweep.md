# Hipotez: HYP-2026-05-21-pyramid-trigger-sweep

- **İddia:** Phoenix 15m'de pyramid trigger'ını TP1(1.0R)/TP2(1.5R) arasındaki ~1.2-1.3R
  boşluğa kaydırmak (B-3 çakışmasını çözmek için), fee tasarrufu sağlar AMA `pk >= trig`
  eligibility daraldığı için pyramid'e uygun trade sayısı azalır. Net edge belirsiz.
- **Gerekçe (referanslar):** CEO `2026-05-20_pyramid_vs_multitarget_conflict.md` (E/E2 büyük
  kaydırma RED), Lab `2026-05-21_scenario_b_engine_rerun.md` (compound artefakt + pool-R mandate).
- **Dependent variables:** yıllık ROI, mean ay, neg ay (61), max aylık kayıp, r-adj, pool-R toplamı.
- **Independent variables:** pyramid_triggers (6 set: [1.0,1.5]..[1.5,2.5]); sizes sabit [0.50,0.30].
- **Null hipotez:** trigger kaydırma ROI'yi etkilemez (eligibility eğrisi düz).
- **Kabul kriteri:** ROI ≥ baseline VE neg ≤ baseline VE maxloss ≥ baseline → "yener".
- **Önsel tahmin:** hiçbir trigger HEM ROI HEM DD'de baseline'ı yenmez; CEO E/E2 ince sweep'te
  doğrulanır; en yakın aday [1.2,1.7].
- **Stop criteria:** pool-sumR monoton negatifse → RED, sweep durdur.

## SONUÇ — RED (2026-05-21)

Net-negatif. 6/6 trigger × 2/2 fee koşusu pool-sumR monoton ↓ (istisna yok). Hiçbiri ROI'de
baseline'ı yenmedi. Ek bulgu: B-3 çakışması fee israfı YARATMIYOR — leg-2 fill çakışsa da
ayrılsa da aynı round-trip fee'yi öder; "fee tasarrufu" ayağı çürütüldü. `[1.3,1.8]` fee=0'da
DD-iyi görünüyor ama pool-sumR −5.082 (alpha-feda karşılığı). Canlı [1.0,1.5] korunur.
Rapor: `reports/researcher/2026-05-21_pyramid_trigger_sweep.md`.
