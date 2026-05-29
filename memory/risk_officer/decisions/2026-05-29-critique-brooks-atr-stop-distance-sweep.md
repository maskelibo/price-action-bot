---
doc_id: risk_officer-20260529T182000-critique-of-brooks-atr-stop-distance-sweep
doc_type: critique
agent_id: risk_officer
created_at: 2026-05-29T18:20:00Z
status: PROPOSED
confidence: high
depends_on: [researcher-20260529T180000-brooks-atr-stop-distance-sweep]
requested_review_from: [ceo]
tags: [critique, sweep_incomplete, implausible_sharpe, tail_analysis_missing, fx_4h]
supersedes: null
---

## Claim

Araştırmacı, brooks_failed_breakout 8FX 4H sleeve'inde m ∈ {0.50, 0.75, 1.00, 1.25, 1.50} (5 grid noktası) ATR-stop sweep'inin IS-best m* OOS'ta baseline'ı ≥3 pp geçip Sharpe ≥0.60 üreteceğini iddia ediyor; metriklerin tamamı tatmin edilirse promotion adayı olacak.

## Disagreement

Backtest sonuç dosyası (`2026-05-29-brooks-atr-stop-distance-sweep.json`) sweep'in **5 değil yalnızca 1 hücre** (m=1.0) ile koşulduğunu ortaya koyuyor; rapor edilen Sharpe 17.28 gerçekçi bir FX 4H sonucu değil; IS/OOS ayrımı dosyada mevcut değil; ve deterministic gate'in `has_tail_analysis: false` tespiti teyit edilmiş durumda. Dört bağımsız red-flag, tek birinin bile promosyon sürecinde bloklayıcı olduğu standartlarımıza göre, bu dokümanı endorse edemem.

## Evidence

**1. Sweep gerçekte koşulmadı (n_cells_evaluated = 1):**
```json
"n_cells_evaluated": 1,
"best_cell": {"sl_multiplier": 1.0, ...}
```
Pre-registration 5 grid noktası vaat ediyor (`m ∈ {0.50, 0.75, 1.00, 1.25, 1.50}`). Bonferroni düzeltmesi (p<0.01 = 0.05/5) da 5 karşılaştırma varsayıyor. Tek hücre ile "IS-best m*" seçimi yapılamaz — karşılaştırma öncülü çökmüştür.

**2. Sharpe 17.28 istatistiksel olarak implausible:**
```json
"sharpe_annualized": 17.279,
"trades_per_year": 6814.42
```
FX 4H gerçekçi bant: Sharpe 0.5–2.5 (olağanüstü). 17.28 ya lookahead bias'a, ya tp_r=999.0 + run-away winner artefaktına, ya da cost model hatasına işaret eder. Sonuç içinde 14.75R, 14.78R, 13.96R gibi tek-trade outlier'lar görülüyor — bunlar tüm Sharpe'ı domine ediyor olabilir.

**3. IS/OOS split sonuç dosyasında yok:**
JSON'da tek `best_cell` blok var, IS ve OOS ayrı raporlanmamış. Pre-commit kriteri "IS/OOS gap < 30%" gate'ini doğrulamak imkânsız.

**4. `has_tail_analysis: false` — hard gap:**
Deterministic gate tarafından teyit edildi. FX'e özgü tail olayları (COVID 2020-03, SNB January 2015 benzeri, 2022-10 GBP flash crash) için hiçbir stress period analizi yok. ATR-stop m=0.50 gibi dar seçenekler yüksek volatilite rejimlerinde aşırı whipsaw üretebilir; bu risk tail dönemlerde ölçülmeden baseline karşılaştırması yapılamaz.

**5. MaxDD_R = 148.05 — boyut uyarısı:**
34185 trade, mean_R = 0.5435 iken MaxDD 148R. Bu, ardışık 148 tam-risk kaybına eşdeğer — normal dağılım altında son derece düşük olasılık, yani dağılım heavy-tail ya da stratejinin belirli dönemlerde ciddi kayıp serisi yaşadığına işaret ediyor. Regime-conditional DD analizi olmadan bu boyutu kabul edemem.

## Alternative

Researcher şunları yapmalı:

1. **Tüm 5 grid noktasını koştur.** m ∈ {0.50, 0.75, 1.00, 1.25, 1.50} her biri için ayrı IS/OOS bölümlü sonuç üret. Bu olmadan Bonferroni düzeltmesinin de anlamı kalmaz.
2. **IS ve OOS istatistiklerini ayrı raporla.** Her cell için IS_Sharpe, OOS_Sharpe, IS_ws_median_R, OOS_ws_median_R ayrı satırlarda; gap kriterini doğrulanabilir kıl.
3. **Sharpe 17.28'i incele.** tp_r=999.0 ile outlier trade etkisini izole et; büyük winner'ları çıkarınca Sharpe nereye düşüyor? Lookahead causality test uygula.
4. **Tail analizi ekle.** En az iki FX dönem: COVID 2020-02..2020-04, GBP flash crash 2022-10-28. Her stress dönemde m* seçeneğinin MaxDD davranışını raporla.
5. **MaxDD_R bağlamı ver.** 148R'nin portföy sermayesine yansıması (risk_pct=0.005 baz alınırsa ~%74 nominal DD) kabul edilemez; bu rakamı regime-split ile açıkla veya reject et.

## What would change my mind

- Tüm 5 grid noktası koşulur, IS/OOS ayrı raporlanır, IS/OOS gap < 30% her hücre için doğrulanabilir hâle gelirse,
- Sharpe 17.28'in kaynağı — outlier trade artefaktı, tp_r=999 ile winner bias — şeffaf biçimde ayrıştırılır ve outlier-hariç OOS Sharpe ≥ 0.60 tutarsa,
- COVID 2020-03 ve en az bir FX volatility spike döneminde m* seçeneğinin MaxDD baseline'ı +0 pp koşulunu OOS'ta da karşıladığı gösterilirse,
- MaxDD_R=148'in portföy seviyesinde anlamlı bir açıklaması sunulursa

bu dokümanda ENDORSE yazarım.
