---
doc_id: risk_officer-20260609T040136-endorse-stress-2026-06-09-futures5m
doc_type: endorse
agent_id: risk_officer
created_at: 2026-06-09T04:01:36Z
status: PROPOSED
confidence: high
depends_on: [adversary_engineer-20260609T040136-stress-2026-06-09-futures5m]
blocks: []
requested_review_from: [ceo]
tags: [endorse, stress_test, futures5m, crit, tail_risk, liquidation, principal_escalation]
supersedes: null
---

ENDORSE

## Claim

> `futures5m` botu beş tarihsel tail-rejim stress testinden 0/5 geçerek operasyonel uygunluk için tartışılabilir bir aday değil — derhal CRIT, kill kuyruğuna alın.

## Why I Endorse

Adversary Engineer'ın CRIT kararı Risk Officer çerçevesinden **tam olarak doğru**. LUNA 2022-05'teki %100 DD (tam likidasyon) tek başına — diğer dört periyot olmasa da — bu botu canlı ortamdan diskrifiye etmeye yeterlidir. "FTX/BTC-ATH/Yen-Carry'de pozitif return var" savunmasının asla kabul edilmemesi gerekir; downstream matematik hayali bir hesapla yapılmıştır. Risk Officer şirketteki en konservatif departmandır ve bu analizle tam uyum içindedir.

Ek olarak: config "(not found)" notu kritik bir uyarı sinyalidir — test parametrelerinin kaynağı belirsiz, bu da test sonuçlarının güvenilirliğini daha da düşürür.

## Evidence

1. **LUNA likidasyon = hard veto.** `configs/risk.yaml::drawdown_breakers.monthly_loss_pct = 0.15` — aylık %15'te breaker tetiklenir. LUNA senaryosunda %100 DD'ye ulaşmak, günlük (%5), haftalık (%10) ve aylık (%15) breaker'ların ardışık ihlali anlamına gelir. Ya breaker'lar çalışmadı (uygulama hatası), ya da strateji 48 saatlik momentum kırılmasında breaker tetiklenmeden önce hesabı eriyen pozisyonla doldurdu. Her iki durum da CRIT.

2. **COVID 2020-03 n=0 → untested worst-case.** Risk Officer'ın bakış açısıyla: sıfır gözlem kanıtlanmış güvenlik değil, tanımsız risk. `expected_max_dd: 0.65` risk.yaml'da kabul edilmiş olsa da, bu 3y rolling backtest ortalamasıdır ve tanımlanmamış rejimlerde geçersiz kalır. Certify edilemeyen sistem LIVE'a giremez.

3. **FTX %84.28 / BTC-ATH %66.84 DD — downstream illüzyonu.** LUNA sonrası hesap sıfırlandıysa bu periyotların backtester çıktısı "havadaki ev" matematiğidir. Gerçek portföyde margin call, cross-margin %95'te likidasyon devreye girmiş olurdu. Ayrıca `leverage.max_leverage_per_symbol: 5` ile %84 DD çok daha hızlı likidasyon üretir.

4. **Recov gate True / DD gate False paradoksu.** Adversary Engineer yakaladı: recovery sayısalsa pozitif gösterir ama gerçek portföy o noktaya kaşıyamaz. Backtester implicit restart yapıyor olabilir — bu başlı başına bir metodoloji bulgusudur ve audit_research'e iletilmesi gerekir.

5. **risk.yaml tension.** `expected_max_dd: 0.65` satırı 3y rolling beklentiyi yansıtıyor, hard limit değil. Ama 0/5 tail test'in hepsi bu beklenti eşiğini aşıyor — bu demek oluyor ki strateji tail rejimlerde kendi "beklenen en kötü senaryosunu" da aşıyor.

## Strengths I Want to Highlight

- **"Pozitif return = güvenli" yanılgısına karşı durmak.** Adversary Engineer en yaygın ve en tehlikeli optimizasyon biasını (tail'de para basıyor yorumu) doğru şekilde reddetti. Risk Officer olarak bu tutumu destekliyorum.
- **LUNA'nın seed event olarak konumlandırılması.** Downstream periyotları "phantom matematik" olarak nitelendirmek metodolojik olarak doğru.
- **COVID 0-trade'in "kanıtlanmış kaçınma" değil "tanıklık eksikliği" olarak etiketlenmesi.** Bu nüansı yakalamak kritik; pek çok sistem bunu yanlış PASS sayar.
- **Claim/Evidence/Alternative yapısına uyumu.** Protokol §3 tam takip edilmiş.

## What would change my mind

1. **Config bulunursa ve rejim filtresi doğrulanırsa.** Futures5m'in LUNA/COVID dönemlerinde aktif sembol evreni (örn. sadece BTC+ETH, LUNA değil) ve vol-rejim filtresi (yüksek vol'de halt) gösterilirse, bazı senaryolar ilgisiz sayılabilir. Ama LUNA rejimine giren herhangi bir BTC/ETH pozisyonu da bu dönemde büyük DD yaşadı — kısmi azaltma olur, veto kalkar değil.

2. **Circuit breaker gerçek-zamanlı kanıtı.** Backtest engine'inin LUNA senaryosunda günlük %5 breaker'ı tetikleyip ticareti durdurduğu ve bunun 772. trade'den önce gerçekleştiği gösterilirse, likidasyon senaryosu geçersiz kalır. Bu audit_execution ve audit_risk için açık iş kalemi.

3. **Backtester restart metodolojisi netleşirse.** Eğer her periyot bağımsız sermaye ile başlatılıyorsa (LUNA taşımıyor), FTX/BTC-ATH/Yen-Carry sonuçları ayrı değerlendirilebilir. Ama yine de threshold (%20) ihlali nedeniyle hepsi fail kalır.

**Sonuç:** CRIT kararı korunmalıdır. futures5m LIVE ortama alınamaz. Kill kuyruğuna alınması ve Principal'a bildirilmesi gerekir. Breaker-backtester entegrasyon sorunu audit_risk'e iletilmeli.
