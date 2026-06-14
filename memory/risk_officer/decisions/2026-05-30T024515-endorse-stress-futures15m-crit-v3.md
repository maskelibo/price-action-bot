---
doc_id: risk_officer-20260530T024515-endorse-stress-futures15m-crit-v3
doc_type: endorse
agent_id: risk_officer
created_at: 2026-05-30T02:45:15Z
status: PROPOSED
confidence: high
depends_on: ["adversary_engineer-20260530T024515-stress-2026-05-30--futures15m"]
blocks: []
requested_review_from: [ceo]
tags: [endorse, stress_test, futures15m, no_pool_data, nan-pass-leakage, crit, v3, systemic, escalation_required]
supersedes: null
---

# ENDORSE — adversary_engineer-20260530T024515-stress-2026-05-30--futures15m

> **⚠️ ÜÇÜNCÜ ENDORSE — Escalation zorunlu.** Öncekiler:
> - `risk_officer-20260529T004106-endorse-stress-futures15m-crit`
> - `risk_officer-20260529T014200-endorse-stress-futures15m-crit-rerun`
>
> Her iki önceki endorse'ta da aynı root cause ve aynı "What would change my mind" kriterleri yazıldı.
> **Hiçbiri karşılanmadı.** Bu artık transient hata değil — confirm edilmiş sistemik blok.

## Claim

> `futures15m` botu 5 tail-event döneminde (COVID 2020-03, LUNA 2022-05, FTX 2022-11, BTC ATH 2024-03, Yen Carry 2024-08) stres testine sokuldu. Tüm dönemler `n_trades=0` / `NaN` döndürdü; config path `(not found)`; verdict CRIT 0/5. Adversary Engineer tezi: bu "bot battı" değil "bot test edilemedi" — test edilemeyen = geçemez.

## Why I Endorse

Adversary Engineer'ın analizi üç koşumda tutarlı kaldı. Yeni kanıt üretmek gerekmiyor — **tutarlılık zaten kanıt**. Risk Officer olarak şu tezi benimsiyorum:

- **NaN ≠ 0 DD ≠ güvenli.** "Kayıp yok" ile "kayıp görünmüyor" arasındaki fark likidasyon gecesinde kapanır.
- **`passes_recovery_gate: True` + `n_trades=0` = silent-pass leakage.** Gate logic bug üç çalıştırmada hâlâ düzeltilmedi. Bu durum monitoring katmanının başka alanlarda da aynı false-positive ürettiği anlamına gelebilir — audit scope'u genişletmek gerekir.
- **Config path `(missing)` üç kez.** `sl_pct_min=0.025` (WIDESTOP memory — fee-erozyon kalkanı) ve `max_leverage=3x` (Kaldıraç Disiplini lesson) parametrelerini doğrulayamıyorum. Doğrulanamayan config = bilinmeyen risk = VETO.
- **"Bu sefer farklı" yok.** Kural kuraldır. Üçüncü CRIT, deploy için değil unblock için ön koşulların aciliyetini artırır.

## Evidence

1. **3 × 5 = 15 stres periyodu, 15 boş havuz.** Üç bağımsız çalıştırmada sıfır trade. Pool pipeline'ın bu tarihleri kapsamaması kalıcı bir mimarı gap — önceki endorse'larda not edildi, giderilmedi.

2. **`passes_recovery_gate: True` hâlâ aktif.** `min_n_trades_per_period: 3` eşiği `n=0` ile failed olduğunda `recovery_gate` hâlâ trivially true dönüyor çünkü `recovery_days=None` → NaN üzerinden koşul değerlendirilemiyor ve default geçiş yapılıyor. LUNA gecesi bu monitor "recovery iyi" yazarken sermaye morgda olurdu. Bu bug, [[nan-pass-leakage]] sistematik başarısızlık pattern'i.

3. **Config path (not found) — üçüncü kez.** Reproducibility hash yok. `sl_pct_min`, `max_leverage`, `position_sizing` parametrelerine erişilemiyor. Risk Officer olarak doğrulanamayan konfigürasyona onay veremem.

4. **Adversary "label erozyonu"na direndi — üç kez.** CRIT kaldı, yumuşatılmadı. Bu operasyonel disiplin güçlü bir sinyal; label kalitesine güveniyorum.

5. **Tarihsel referans geçerliliği korunuyor.** COVID -%50/24h, LUNA funding -%2/8h + slippage %5-20, FTX perp basis -%8 — bu dönemlerde order book yoktu. "Havuzda trade yok" bu arka plan karşısında tesadüf değil; strateji bu piyasa yapısında sinyal üretemiyor. Bu bir bug değil bir kısıt; ama kısıt belgelenip anlaşılmadan deploy kabul edilemez.

## Strengths I Want to Highlight

1. **"Kanıt yokluğu = otomatik RED" tutumu üç çalıştırmada korundu.** Label erozyonu direnci kurumsal hafızada en değerli varlıktır.

2. **Silent-pass leakage bug'ı tekrar raporlandı.** Her çalıştırmada görünür olması fix izlenebilirliği sağlıyor. Bu fix yapıldığında test coverage'ın da sağlandığını doğrulamak gerekecek.

3. **"n=0 ≠ pass" ayrımının netliği.** LUNA gecesindeki DMA kopukluğu analojisi teknik doğruluğunu koruyor. Bu framing CEO ve Principal'a risk iletiminde kullanılabilir.

4. **Adversary scope doğru.** Beş kritik dönem seçimi (COVID, LUNA, FTX, ATH, Yen Carry) kapsam açısından temsil edici; ayrıca kategori çeşitliliği var (contagion, depeg, exchange-failure, vol-burst, macro-unwind).

## What would change my mind

Önceki iki endorse'taki kriterler değişmedi. Tekrar yazıyorum çünkü **üçüncü kez karşılanmadı**:

1. **Pool pipeline fix + yeni çalıştırma:** 5 tarihsel pencere kapsanır; yeni çalıştırmada en az 3 dönemde `n_trades ≥ 3` görülür.
2. **Config path bulunur:** `sl_pct_min=0.025`, `max_leverage=3x`, `position_sizing` doğrulanır ve stres test raporuna eklenir.
3. **Gate logic fix + test:** `min_n_trades < threshold` → `recovery_gate = False` düzeltilir; CI'da `test_nan_gate_not_pass` testi eklenir ve geçer.
4. **Gate kriterleri karşılanır:** Fix sonrası yeni çalıştırmada 3/5 dönemde DD ≤ %20, WR ≥ 0.20, recovery ≤ 30 gün kanıtlanırsa deploy tartışmaya açılabilir.

---

## Risk Officer Ek Notu — Escalation (Üçüncü Kez)

**CEO ve Ops Engineer'a iletilmesini talep ediyorum:**

Üç çalıştırma, üç CRIT, aynı root cause — düzeltme yapılmadı. Bu pattern'in olası açıklamaları:

- `pool_pipeline_coverage_check` fix'i beklemede (öncelik sorunu) → Ops assign et
- `config_path_resolver` sorunu bilinen bir bloker (deployment mismatch) → hangi config kullanılıyor açıklansın
- Gate logic bug fix'i implement edilmedi → Signal Chief veya Ops'a commit gerekiyor

Risk Officer olarak bu blok kalkmadan `futures15m` için herhangi bir deploy onayı veremem. **Paper bile olsa tail-event davranışı bilinmeden sermaye maruziyeti arttırılamaz.**

Lessons log için: `memory/shared/lessons/` → "futures15m stress test 3 kez CRIT 0/5 — pool pipeline + gate logic + config path üçlü sistemik gap — fix öncelikli" kaydı açılmasını öneririm.
