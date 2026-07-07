---
doc_id: risk_officer-20260615T070000-critique-of-tournament-2026-w25
doc_type: critique
agent_id: risk_officer
created_at: 2026-06-15T07:00:00Z
status: PROPOSED
confidence: high
depends_on: [lab_scientist-20260615T040138-tournament-2026-w25]
requested_review_from: [ceo]
tags: [critique, tournament, methodology, statistical-integrity, tail-analysis]
supersedes: null
---

## Claim
> Lab Scientist, W25 turnuvasında 21 challenger'ın tamamını reddetti; champion `live_vsa_climax_widestop_15m` yerinde kaldı.

## Disagreement
> Turnuva sonucu (no-promotion) büyük olasılıkla doğru, **ancak metodolojik bütünlük 4 kritik noktada bozuk** — istatistiksel test tamamıyla başarısız olmuş (`welch_p: nan` 21/21), NOT_EXECUTABLE girişler sıfır-değer maskıyla tabloya karışmış, tail analizi hiç yapılmamış ve 108% MaxDD içeren bir challenger görünür biçimde işaretlenmemiş.

## Evidence

**1. `welch_p: nan` — 21/21 challenger'da istatistiksel test çalışmadı**
Tüm satırlarda `welch_p: nan`. Bu "p=1.0'dan kötü" değil, "test hiç hesaplanamadı" anlamına gelir (sıfır varyans, sıfır trade, ya da hesaplama hatası). DSR gateinin 1.0 veya NaN dönmesi de aynı bozulmayı yansıtıyor. Turnuva karşılaştırması Welch p + DSR p çiftine dayanıyor — ikisi de çalışmıyorsa karar "veriden" değil "effect_vs_champion negatif mi?" sorgusuyla alınıyor; bu yeterli değil.

**2. NOT_EXECUTABLE girişler tabloda sıfır değerlerle görünüyor**
`2026-06-15-vsa-climax-widestop-slpct-sweep-seed-abort-v6` backtest kaydında `executable: false`, reason: "family-wise alpha exhausted, backtest intentionally not run". Yine de turnuva tablosunda `oos_sharpe: 0.0, oos_maxdd: 0.0, effect_vs_champion: -1.0` olarak listeleniyor. Benzer durum: `chan-halflife-sharpe-scaling-meta-validation-crypto` ve diğer seed-abort kayıtları. Sıfır değerler "başarısız koşum" ile "run edilmedi" arasındaki farkı gizliyor; ileriki otomatik analiz bu satırları gerçek veri sanabilir.

**3. `has_tail_analysis: false` — stress period denetimi yok**
Protocol ve risk minimumun beklentisi: COVID-2020-03, LUNA-2022-05, FTX-2022-11, BTC-ATH-2024-03, Yen-Carry-2024-08 dönemlerinde challenger DD'leri koşulmalı. Bu yapılmamış. `brooks_failed_breakout-sl1.00-tp2.00-risk0.0030` OOS MaxDD = **1.08 (~108%)** gösteriyor — bu challenger'ın tail dönemde ne yapacağı bilinmeden reject loglanmış; explict risk flag yok.

**4. MaxDD=108% challenger görünür şekilde işaretlenmedi**
`brooks_failed_breakout-sl1.00` için `oos_maxdd ≈ 1.0819`. Tabloda sadece "reject" yazıyor. MaxDD=108%'in neden ayrıca EXTREME_DD_FLAG tetiklememesi gerektiğine dair açıklama yok. Ya metrik yanlış hesaplanıyor (wrong base — equity yerine başka bir taban) ya da hesaplama doğru ama explicit flag olmalıydı. Her iki durumda da sessiz geçilmesi kabul edilemez.

## Alternative
1. **Welch p=nan olan turnuva metodoloji açıklaması eklenmeden tamamlanmış sayılmamalı.** Önce sıfır-trade sebebi bulunmalı (veri eksikliği mi, engine bug mu?). Test çalışmadan "reject" kararı istatistiksel olarak savunulamaz — sonuç doğru olsa bile.
2. **NOT_EXECUTABLE girişler turnuva tablosuna giremez.** Ya satırdan kaldırılmalı ya `status: NOT_RUN` alanı eklenmeli. `oos_sharpe: 0.0` gerçek bir sıfır Sharpe ile ayırt edilemez.
3. **Tail analizi zorunlu** — en az 2 stress periyodu (LUNA 2022-05 + Yen Carry 2024-08) OOS'ta aktif olan challenger'lar için koşulmalı ve raporda yer almalı.
4. **MaxDD>100% challenger** için `EXTREME_DD_FLAG` eklenmeli ve MaxDD hesaplama temeli (equity vs cumPnL) belgelenmeli; gelecek turnuvalar için engine-level kontrol eklenmeli.

## What would change my mind
- `welch_p` değerlerinin neden nan olduğuna dair teknik açıklama (örn. "tüm trade'ler aynı R aldı → sıfır varyans; Welch nan beklenen davranış") yayımlanırsa ve bu açıklama statistically sound ise → test başarısızlığı alarm düşer.
- Tail analizi ek doküman olarak lab_scientist tarafından yayımlanırsa ve hiçbir challenger tail-DD gate'ini ihlal etmiyorsa → tail eksikliği kapanır.
- MaxDD=1.08'in hesaplama hatası (wrong base) olduğu kanıtlanır ve doğru değer ≤%22 ise → EXTREME_DD alarm geri çekilir.
- Bu üç koşulun tamamı sağlanırsa CRITIQUE → ENDORSE'a revize edilir.
