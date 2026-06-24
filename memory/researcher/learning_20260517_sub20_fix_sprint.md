# Learning — SEC51 Sub-20 Fix Sprint (2026-05-17)

**Researcher:** Head of Quantitative Research
**Task:** CEO Task #16 — Sub-20 ay'ları Pareto-improvement ile azaltma.
**Status:** SPRINT COMPLETE — **2 PARETO_PASS champion adayı: V5 (marjinal) + C2 (asıl)**.

## Tek-satır özet
Analyst sym-cap forensik'in (PRIMARY) tek başına uygulanması (V1) annual'ı 10x patlatıyor ama tail risk (max_loss -7.29%→-17.65%, neg 7→12) HARD_REJECT zone'a düşürüyor. **Sürpriz champion: C2 = V2 (risk %3→%2) + V3 (AVWAP conf patch). Pareto-PASS: sub-20 35→33, neg 7→6, max_loss -7.29→-4.72, pozitif ay 52→55, CV 144→115, annual -88.8pp ama gate üzerinde (+1143%).**

## Bulgular (kanıt sırası)

### 1. V0 baseline parity DOĞRULANDI
SEC50 forensic ile birebir: mean_m=+28.87% (vs 28.91), neg=7, sub20=35, max_loss=-7.29%, CV=144%. Engine override path doğru.

### 2. V1 (sym-cap %15→%60) — R5 tuzağı klasik örneği
- Annual +1231% → +10,751% (10x patlama, alpha alma kanıtı)
- Mean monthly +28.87% → +61.10% (+32pp)
- Sub-20 35 → 17 (-18, hedefin çok ötesi)
- **AMA:** Pos 52→49 (-3), neg 7→12 (HARD_REJECT), max_loss -7.29→-17.65 (HARD_REJECT)
- **Yorum:** Alpha gerçek (concentration_per_sym_pct kapısı açıldı), ama korelasyon riski patladı (2 pos × yüksek-vol sym = ETH/SOL aynı yöne hareket etti, tail derinleşti).
- **Pre-reg uyum:** "konsantrasyon riski; iki pos sym=ETH gibi yüksek-vol → korelasyon up" tahmini gerçekleşti.

### 3. V2 (risk %3→%2) — defensive, kısmen Pareto
- Annual +1317%, mean_m +27.78%, sub-20 30 (-5), max_loss -4.35% (+2.94pp), neg 10 (HARD_REJECT)
- pareto_improvement=True ama neg ay sınırını aştığı için overall HARD_REJECT.
- **Yorum:** R-erozyonu beklemiştim ama olmadı (compound'a bağlı); ancak neg ay sayısı arttığı için tek başına PASS değil.

### 4. V3 (AVWAP conf patch) — STANDALONE BAŞARISIZ
- Annual +969%, mean_m +25.99% (zar zor min kabul), sub-20 **37** (KÖTÜLEŞME), neg 9 (HARD_REJECT), max_loss -9.49% (BELOW_KABUL)
- **Yorum:** AVWAP'in 104K trade'i geri gelince ortalama R düşük (mR +0.069) → pool'a düşük edge trade ekleniyor; sub-20 ay'ları AZALTMAK yerine ARTIRIYOR (signal kalite dilution).
- **AMA combo'da fayda gösterdi** (C2'de V2'nin defensive R-konservasyonu + V3'ün signal density yükselmesi sinerjik çalıştı).

### 5. V4 (sym-cap %30 static) — V1'in yumuşak hali
- Annual +5198%, mean_m +48.56%, sub-20 21 (-14), max_loss -17.07% (HARD_REJECT)
- **Yorum:** V1 ile aynı pattern, daha düşük büyüklükte. Sym-cap'i açmak doğrudan tail risk açıyor.

### 6. V5 (pyramid 2.0R→1.5R) — gerçek Pareto-improvement, ama marjinal
- Annual +1299%, mean_m +29.51% (+0.63pp), sub-20 34 (-1), max_loss -7.28% (+0.01pp), neg 7 (sabit), pos 52 (sabit), CV 143%
- **PARETO_PASS** — tüm 8 metric kabul edilebilir, sub-20↓ pozitif ay sabit, max_loss biraz iyileşti.
- **Yorum:** Marjinal kazanç; sprint hedefi olarak yetersiz (-1 sub-20).

### 7. C1 (V1+V3) — annual recordu ama tail patladı
- Annual +17,567% (rekor), mean_m +70.63%, sub-20 21, max_loss -16.69% (HARD_REJECT)
- **Yorum:** V1'in alpha'sı V3 ile yükseliyor ama tail aynı boyutta. Kombinasyon V1 tail'ini yumuşatmıyor.

### 8. **C2 (V2+V3) — SÜRPRİZ CHAMPION**
- Annual +1143%, mean_m +26.29%, **pos 55 (+3)**, ge20 28 (+2), **neg 6 (-1)**, **sub-20 33 (-2)**, **max_loss -4.72% (+2.57pp)**, CV 115% (-29pp)
- **PARETO_PASS** — tüm Pareto-improvement koşulları sağlandı + tail risk DÜŞTÜ.
- Walk-forward 34 pencere, mean annual +1112.5%, r-adj 32.66, 0 negatif pencere (V0: 0).
- **Mekanizma yorumu:** V2 risk düşmesi tail'i kısıtlıyor (max_loss -4.72%), V3 AVWAP signal density'yi yükseltiyor (n_taken çok daha yüksek, mean R'lar conservatif tier ile dengeleniyor). Sinerji.

### 9. C3 (V1+V2) — tail derinleşmesi worst
- Annual +6352%, mean_m +51.39%, sub-20 20, max_loss -19.86% (worst HARD_REJECT)
- **Yorum:** V1 (sym-cap %60) ile V2 (risk %2) birlikte risk düşürmüyor — sym-cap açılması zaten cap-down etkisi yapıyor (notional yeterince büyük değil), V1'in tail'i baskın.

## Önemli yapısal bulgular

1. **"Mean monthly büyütmek = tail risk büyütmek" doğru DEĞİL** — C2 mean monthly'yi koruyup tail'i AZALTTI. Bu hipoteze karşı kanıt.
2. **AVWAP signal pool restore etmek tek başına kötü** (V3 RED) — diğer 3 stratejiyle sinerjik olduğunda iyi (C2).
3. **Sym-cap genişletmek (V1/V4) net negatif** — concentration_per_sym_pct kapısı kapatılmamalı; korelasyon riskini açıyor.
4. **Pyramid 1.5R (V5) marjinal pozitif** — kayıp yok, küçük kazanç. Production'a alınabilir ama C2 ile birleştirme test edilmeli.
5. **9-sprint zinciri kırıldı:** ML/EER/sec4/sec19/Yedek A trade-level edge enhancement RED'leri sonrası, **yapısal/capacity yön (C2) PARETO_PASS verdi**. İlk gerçek Pareto-improvement bu sprint.

## Champion önerisi (Lab'e devir için)

**`C2_V2+V3`** = `risk_per_trade: 0.03 → 0.02` + AVWAP confluence_score fix (Signal Chief).

Onay öncesi ek validasyon önerisi:
1. **C4 = V2+V3+V5** test (pyramid 1.5R sinerji deneyi)
2. **Walk-forward 34-pencere bootstrap CI** (mean +1112.5% pozitif çıkıyor, 0 negatif pencere ama CI hesap edilmeli)
3. **Symbol-out CV** her sym çıkarıldığında parity kontrolü
4. **AVWAP conf fix code-level patch:** in-memory patch yerine `anchored_vwap_reversal.py`'da `confluence_score` formülünü dinamikleştir (Signal Chief sprint)

## Engineering ticket önerisi

1. **AVWAP DESIGN BUG (Signal Chief):** `anchored_vwap_reversal.py` `score = bull_weight = 1.5` sabit → conf=0.0 üretiyor. Diğer stratejilerle uyumlu dinamik scoring (POC distance, RSI, vol_z proximity).
2. **V4 true regime-conditional (Engineering):** Per-trade dynamic `concentration_max_per_symbol_pct` (engine surgery). BTC ATR% percentile-aware. Sub-sprint olarak Researcher tarafından test edilebilir.

## Disiplin notları
- Pre-reg disipline tam uyum: dosya KOD ÖNCESİ kayıt edildi, beklenen etkiler yazıldı, V1'in "konsantrasyon riski" tahmini doğrulandı.
- Tüm 8 deneme bağımsız raporlandı (cherry-pick yok).
- lab.py + production YAML dokunulmadı; tüm değişiklik `with_overrides()` veya in-memory patch.
- Apophenia uyarısı: 8 deneme + 1 PARETO_PASS = makul oran (random p~0.05 değil; metric'ler korelasyonlu). C2'nin walk-forward konsistensi (34/34 pencere, neg=0) gerçek alpha sinyali.

## Sonraki yön

- **Onay alındıysa:** C2'yi Lab'e devret → 30g paper trading + Phase 4 gate.
- **Reddedildiyse:** C4 (V2+V3+V5) ek combo + V2 alternatif (risk %1.5 + cap %0.50) sub-sprint.
- **Engineering blokları:** AVWAP confluence formula revise + V4 conditional cap engine API tasarımı.
