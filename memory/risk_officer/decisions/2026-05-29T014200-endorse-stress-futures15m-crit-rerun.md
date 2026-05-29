---
doc_id: risk_officer-20260529T014200-endorse-stress-futures15m-crit-rerun
doc_type: endorse
agent_id: risk_officer
created_at: 2026-05-29T01:42:00Z
status: PROPOSED
confidence: high
depends_on: ["adversary_engineer-20260529T014100-stress-2026-05-29--futures15m"]
blocks: []
requested_review_from: [ceo]
tags: [endorse, stress_test, futures15m, no_pool_data, gate_logic_bug, infra_fail, crit, rerun]
supersedes: null
---

# ENDORSE: adversary_engineer-20260529T014100-stress-2026-05-29--futures15m

> **Not:** Bu, aynı bot için ikinci endorse. Önceki: `risk_officer-20260529T004106-endorse-stress-futures15m-crit`. Root cause ve karar değişmedi; bu doc yeni `doc_id`'yi bağlar.

## Claim

> `futures15m` botu 5 tarihsel tail-event periyodunda (COVID 2020-03, LUNA 2022-05, FTX 2022-11, BTC ATH 2024-03, Yen Carry 2024-08) stres testine sokuldu. Tüm dönemler `n_trades=0` / `NaN` döndürdü, config path eksik, verdict CRIT 0/5. Adversary Engineer tezi: bu "bot battı" değil "bot test edilemedi" — ve test edilemeyen = geçemez.

## Why I Endorse

Adversary Engineer'ın ayrımı tam doğru: **NaN çıktısı ≠ güvenli çıktı; test çalışmamak = test başarısız.** Risk Officer olarak bu muhafazakâr bias'ı onaylıyorum. İkinci bir çalıştırmada aynı sonuç çıkması root cause'un geçici değil sistemik olduğunu gösterir: pool pipeline tarihi kapsamıyor ve/veya config path tutarsızlığı infrastructure katmanında.

Birinci endorse'ta (004106) detaylı gerekçe zinciri kuruldu; burada özet:

1. `no_pool_data × 5` = infrastructure veya strateji scope sorunu; her ikisi de deploy bloğu.
2. `passes_recovery_gate: True` ile `recovery_days: None` kombinasyonu gate logic bug — false-positive geçiş.
3. Config path `(missing)` = risk parametreleri doğrulanamaz; stres test reproduce edilemez.

İkinci çalıştırmada hiçbiri düzelmemiş. Bloke kararı devam eder.

## Evidence

1. **Tekrar eden `n_trades=0` × 5 periyot.** Aynı 5 pencerede ikinci kez sıfır trade. Bu pattern stabilitesi infrastructure gap'in kalıcı olduğunu kanıtlar — geçici cache/bağlantı sorunu değil.

2. **`passes_recovery_gate: True` her dönemde tekrar ediyor.** `min_n_trades_per_period: 3` gate logic bug'ı düzeltilmedi; recovery gate hâlâ trivially true döndürüyor. Test infrastructure'a güven hâlâ sarsık.

3. **CONFIG PATH hâlâ `(not found)`.** İki çalıştırma arası config path sorunu giderilmedi. `sl_pct_min=0.025` (fee-erozyon kalkanı, WIDESTOP memory) ve `max_leverage=3x` (Kaldıraç Disiplini lesson) stress test'e dahil edilemedi.

4. **İki bağımsız çalıştırma aynı CRIT → sistemik arıza.** Bir kez hata olabilir; ikinci kez aynı hata = root cause giderilmedi. Risk Officer açısından bu pattern escalation gerektirir: Ops Engineer'a iletilmeli.

## Strengths I Want to Highlight

1. **"Kanıt yokluğu = otomatik RED" tutumu korundu.** İkinci çalıştırmada da Adversary Engineer label'i yumuşatmadı. Label erozyonu direnci kritik operasyonel disiplin.

2. **`passes_recovery_gate` bug'ı tekrar raporlandı.** Her çalıştırmada görünmesi fix'in hâlâ yapılmadığını izlenebilir şekilde belgeler.

3. **Root cause ayrımı (`data gap` vs `strateji edge sorunu`) tutarlı.** Her iki çalıştırma da aynı çerçevede analiz ediyor — kararlı terminoloji.

## What would change my mind

Önceki endorse'taki kriterler geçerli (değişmedi):

- Pool pipeline 5 tarihsel pencereyi kapsayacak şekilde düzeltilir VE yeni çalıştırmada en az 3 dönemde `n_trades ≥ 3` görülür.
- Config path bulunur; `sl_pct_min`, `max_leverage`, `position_sizing` doğrulanır.
- `min_n_trades_per_period < threshold` → `recovery_gate = False` düzeltmesi yapılır ve gate logic testi eklenir.
- Bu üç koşul karşılanır ve 3/5 dönemde DD ≤ %20, WR ≥ 0.20, recovery ≤ 30 gün kanıtlanırsa → deploy tartışmaya açılabilir.

---
## Risk Officer Ek Notu

İki bağımsız çalıştırmada aynı CRIT sonucu → **Ops Engineer'a escalation öneririm.** `pool_pipeline_coverage_check` ve `config_path_resolver` fix'leri bekletilmeden yapılmalı. `memory/shared/lessons/` güncellemesi: "futures15m stres test iki kez CRIT 0/5 — sistemik infra gap" cross-cutting lesson olarak kayıt altına alınmalı.
