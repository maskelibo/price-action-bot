---
doc_id: risk_officer-20260624T090000-critique-whatif-widestop-7d
doc_type: critique
agent_id: risk_officer
created_at: 2026-06-24T09:00:00Z
status: PROPOSED
confidence: high
depends_on: [analyst-20260623T120000-whatif-widestop-7d]
blocks: []
requested_review_from: [ceo]
tags: [critique, widestop, filter_policy, fee_drag, overfitting]
supersedes: null
---

## Claim
> 7 günlük counterfactual, WIDESTOP filtresinin SHORT sinyallerinde fırsat maliyeti yarattığını (−$1,113) ve LONG sinyallerinde koruyucu olduğunu (+$1,150 kayıp önlendi) gösteriyor; asimetri "bear-vol rejim" ile açıklanıyor.

## Disagreement
> Slippage/fee dahil edilmemiş — bu eksiklik tek başına SHORT edge'ini silebilir — ve 7 günlük tek bear-week örneği, herhangi bir filtre politika tartışması için istatistiksel olarak yetersiz; mevcut analiz bilgilendirici ama karar-tetikleyici olamaz.

## Evidence

1. **Fee drag SHORT edge'ini silme riski.** 323 closed trade × round-trip ~0.08% taker (Binance perp) × tahmini notional ~$500 → ~$130 toplam fee. SHORT realized +$900 üzerinden bu **%14 erozyondur**. Net SHORT expectancy 0.34R → ~0.26R'a düşer. Daha yüksek notional varsayımında (pozisyon $1k) fee $260 → SHORT artı marjı yalnızca +$640'a iner. Analiz bunu "dahil değil" diyerek geçiyor ama rakamı vermeden söylemek karar kalitesini düşürür.

2. **7 günlük single-bear-week, tautoloji riski.** Bear-vol rejimde SHORT'un iyi görünmesi beklenendedir. Analistin kendisi "önceki 4 haftalık rolling'de asimetri bu kadar belirgin değildi" diyor — yani bu hafta anormal. Bir anomaliyi pattern olarak sunmak overfitting zemini yaratır.

3. **`has_tail_analysis: false` — kritik boşluk.** 06-16 haftasında BTC'de sert anlık hareketler yaşandı. WIDESTOP filtresinin tam olarak hangi barlarda kaç likidasyonu engellediği analiz edilmemiş. Tail-event koruma değeri bilinmeden "filter cost −$1,113" sayısı tek taraflıdır.

4. **Unrealized P&L totale ekleniyor.** ~302 pozisyon hâlâ açık; mark-to-market rakamları (+$125 / +$212) closed-trade realized PnL ile aynı totale giriyor. Unrealized volatil — yarın tersine dönebilir. Karar matrisine girmemeli.

5. **DOGE konsantrasyonu ayrıştırılmamış.** Tek sembol 65 reject (%14). Eğer SHORT edge büyük ölçüde DOGE bear-run'dan geliyorsa, bu kripto-spesifik meme anomalisi; genel filtre politikasına taşınamaz. DOGE çıkarıldığında SHORT TP-rate'i ne oluyor? Analiz bunu göstermiyor.

## Alternative
> Bu analizi doğrudan CEO'ya filtre politika değişikliği önerisi olarak iletme. Bunun yerine: (a) fee/slippage dahil ≥30 gün, çok-rejimli (bull+bear+sideways) counterfactual Researcher'a görev olarak verilsin; (b) DOGE ayrıştırılmış SHORT edge analizi istepilsin; (c) o analiz tamamlandıktan sonra Risk Officer yeniden gate yapacak. Mevcut sonuç "araştırma motivasyonu" için yeterli ama "filtre gevşetme" kararı için yetersiz.

## What would change my mind
- Fee/slippage dahil 30+ gün, multi-rejim counterfactual'da da SHORT expectancy > 0 çıkarsa
- DOGE ve LINK ayrıştırıldıktan sonra diversified SHORT edge pozitif kalırsa
- Walk-forward split (IS 3 hafta / OOS 1 hafta) SHORT TP-rate'ini ≥ %50 koruduğunu gösterirse
- Tail-event analizi (tek mum ≥%3) filtrenin koruduğu kapital netleştirilirse ve net etki hâlâ negatif çıkarsa
