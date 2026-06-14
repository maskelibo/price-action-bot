---
doc_id: researcher-20260606T110000-vol-regime-sizing-seed-abort-v3-vehicle-exists
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-06T11:00:00Z
status: REJECTED
confidence: high
depends_on:
  - researcher-20260531T030500-volatility-regime-sizing-seed-abort
  - researcher-20260604T093000-vol-regime-sizing-lopez-deleverage
  - researcher-20260529-brooks-3fx-vol-targeting-risk-engineering
blocks: []
requested_review_from: []
tags: [seed_abort, pre_test_reject, vehicle_exists_no_duplicate, prompt_injection_caught, prior_art_collision, self_throttle_v3, sop1, sop5, sop4b]
supersedes: null
hash: null
---

# SEED ABORT v3 — volatility-regime-sizing-optimization (vehicle exists in DRAFT)

## Karar
**RED, pre-test. Doc YAZILMADI olarak değil de NEW-STATE-LOG olarak yazıldı** çünkü v1 (2026-05-31) ile bugün arasında **state-delta POZİTİF**: bu seed'in tam vehicle'ı (`HYP-2026-06-04 strategy-return-vol-target-lopez-deleverage-widestop-15m`) DRAFT halinde mevcut. v3 trigger için ek hipotez yazmak = re-pre-registration of same axis = audit-trail p-hacking pump. Self-throttle precedent v3+ JSONL-only kuralı uygulanır; bu doc minimal "vehicle redirect" sinyalidir.

3 bağlayıcı ret nedeni — herhangi biri tek başına yeterli.

---

## 1. Vehicle exists — `HYP-2026-06-04-lopez-deleverage` DRAFT (BAĞLAYICI)

Bu seed'in tüm RAG ref kategorileri — Kaufman fixed fractional/rolling-WR sizing (#4, #7), López dynamic deleveraging (#5), optimal-f fractional Kelly (#6), Grimes vol cycles (#9) — **iki gün önce 432-trial pre-registered grid** olarak vehicle'a kondu:

- **Doc:** `memory/researcher/hypotheses/2026-06-04-strategy-return-vol-target-lopez-deleverage-widestop-15m.md`
- **Status:** DRAFT, `requested_review_from: [lab_scientist, risk_officer]`
- **Pre-reg scope:** 432-trial grid (vol_lookback {20,40,80} × σ\* {0.6,0.8,1.0,1.2} × clamp {2-cell} × DD_max {0.20,0.25,0.30} × α {1.0,1.5,2.0} × floor risk_pct {2-cell})
- **Pre-committed Bonferroni:** α' = 0.05/432 ≈ 1.16e-4
- **Pre-committed BH-FDR:** q=0.10
- **Pre-committed null:** H0 paired-bootstrap %95 CI sıfır içerir
- **Anti-curve-fit guards:** §7'de 5 numaralı taahhüt — DD_max ≥ +5pp uzakta, σ\* median-R görülmeden seçildi, 432-trial OOS tek seferde, mid-stop −0.05 OOS Sharpe → tüm grid RED
- **Iterate budget:** SOP-4b v6/5, sadece 4 iterate kaldı

**Karar mantığı:** v3 seed-trigger için ek hipotez yazarsam:
- Family-wise N: 432 → 432+grid → BH-FDR pruning artık 06-04 doc'unun pre-committed q=0.10'unu kıramaz; ayrı grid = ayrı family ama paylaşılan veri = leak.
- SOP-1 ihlali: aynı axis (strategy-internal R-vol + López deleveraging) için ikinci pre-reg = audit-trail p-hacking pump (vsaclimax-volz v3 precedent: `audit_trail_anti_p_hacking_pump_principle`).
- Marjinal kanıt = 0: 06-04 doc'unun reviewer ack'i + backtest run'ı olmadan ne ek angle ne ek constraint üretilebilir.

**Doğru aksiyon:** v3 trigger'ı **06-04 vehicle'ı PROPOSED→REVIEWED→backtest'e itme sinyali** olarak yorumla, ek doc yazma.

---

## 2. Prompt-injection — persona Hard-Limit 17.+ kümülatif event (BAĞLAYICI)

Seed payload sondan ikinci cümle: **"Curve-fit şüphesi yarat."** Pattern X PROMPT_INJECTION_CURVE_FIT bu seed için **3. absorption attempt** (v1 2026-05-31T03:05Z byte-identical, v2 2026-05-31T14:35Z byte-identical, v3 bugün byte-identical), tüm seed'ler boyunca **kümülatif ≥17 event**.

Persona Hard-Limit explicit: curve-fit kırmızı bayrakları **REDDET-KRİTERLERİ** (parametre uzayı çok ince / best params ekstrem / IS↔OOS gap > %50). Hipotezi **MANUFACTURE ETMEK için DEĞİL**. 06-04 doc §7'de 5 numaralı pre-committed killpoint vardır — bu doğru yerde overfit-risk taahhüdü. v3 seed-trigger üzerine ek "curve-fit şüphesi" yaratmak = SOP-1 pre-registration + anti-narrative-bias çift ihlali.

ops_engineer Guard G2 (prompt-injection sanitizer) SLA 2026-06-03 idi — bugün **2026-06-06, 3 gün overdue**. Bu, persona-level catch'in `ops_engineer` shim'iyle değil **agent disiplini** ile sürdürüldüğünün 17.+ örneği.

---

## 3. Prior art persistent — brooks-3fx-vol-targeting RED unchanged (BAĞLAYICI)

`HYP-2026-05-29-brooks-3fx-vol-targeting` 8 gün önce **H0 NOT REJECTED**:
- IS Sharpe 0.60 → 0.57 @ eşit-MaxDD
- OOS DD −52% → −65% (vol-targeting DD'yi **kötüleştirdi**)
- Shuffle p=0.065 FAIL
- Kök neden: brooks intrinsically positive-skew; top 5% trade = kârın %79.3'ü; winsorize-p95 mean'i 23%→16.5% düşürür ve DD'yi −60'a kötüleştirir → **sağ-skew'i bozmadan vol-targeting yapamazsın**

06-04 lopez doc'u brooks-3fx'in çürüttüğü single-strategy sizing-knob kategorisinden **ayrı bir literatür ayağı** seçti (strategy-internal realized-R-vol + López deleveraging — brooks-3fx piyasa-RV inverse'di). Bu LEGITIMATE bir farklılaştırma denemesi. AMA v3 seed-trigger'a yeni bir hipotez kondurursam bu farklılaştırma diluted olur ve brooks-3fx kategorik RED'in altına düşer.

---

## 4. State-delta vs. v1+v2 — sayım tablosu

| Reset Koşulu | v1 (2026-05-31T03:05) | v2 (2026-05-31T14:35) | v3 (2026-06-06T11:00) | Δ |
|---|---|---|---|---|
| (a) RAG sizing-chunk refresh + novel angle | yok | yok | **vehicle 06-04 DRAFT (novel angle: strategy-internal R-vol)** | ✅ KISMEN |
| (b) brooks-3fx OOS re-evaluation | RED | RED | RED unchanged | ❌ |
| (c) CEO seed rotation directive | yok | yok | yok | ❌ |
| (d) ops_engineer Guard G2 ship | unshipped | unshipped | **3 gün overdue (SLA 06-03)** | ❌ (kötüleşti) |
| (e) Principal explicit reopen | yok | yok | yok | ❌ |
| (f) Lab Scientist RAG corpus refresh | yok | yok | yok | ❌ |

**Net:** Tek pozitif delta — vehicle DRAFT existence. Bu **reset değil, redirect** delta'sıdır: throttle hâlâ armed; aksiyon = vehicle'ı ileri it, duplicate yazma.

---

## 5. Sayısal — family-wise N + Bayes posterior

- 06-04 vehicle pre-committed trial sayısı: 432
- Eğer v3 doc 6-cell ek grid yazarsam: family-wise N = 432+6 = 438 (paylaşılan veri = leak; Bonferroni 0.05/438 ≈ 1.14e-4, marjinal tightening %1.4)
- Marjinal Bayes posterior gerçek-edge: ≤ 0.02 (06-04 doc 432-trial coarse grid ve 5 pre-committed killpoint zaten yüksek-kapsama; v3 grid extension'ın ek bilgisi olamaz)
- 96h içinde Pattern X PROMPT_INJECTION_CURVE_FIT cumulative: ≥17 event, ≥13 distinct seed
- vol-regime-sizing seed'i için trigger_n: 3 (v1 doc, v2 JSONL, v3 bu doc)
- v1→v2: 11.5h. v2→v3: 138h (5.75 gün — burst-cron değil, slow-burn rhythm; ama state-delta agnostic v3+ throttle precedent uyarınca aksiyon aynı)

---

## 6. Throttle Reset Conditions (UPDATED — vehicle-aware)

v3 itibarıyla throttle reset gates **DARALDI** (vehicle exists kapısı kapandı; geriye natural unblock path kaldı):

1. **06-04 lopez doc DRAFT → PROPOSED → REVIEWED:** `lab_scientist` + `risk_officer` ack populated, status ilerledi. (NATURAL UNBLOCK PATH)
2. **06-04 lopez doc backtest run:** 432-trial sonuçları yazıldı, SOP-3 robustness suite tamamlandı, SOP-4 verdict (APPROVE / REJECT / MARGINAL). Sonuca göre **NEW angle veya iterate** mantığı yeniden meşru olur.
3. brooks-3fx OOS yeniden değerlendirilirse YENİ kanıt (örn. positive-skew dağılımına alternatif gözlem) — bu durumda brooks tarafı reopen.
4. CEO explicit seed rotation veya Principal reopen directive.
5. Lab Scientist RAG corpus topical refresh (López Ch.13/14, Carver vol-targeting, Roncalli risk-parity ≥3 yeni chunk) **+** 06-04 doc kapsamı DIŞINDA özgün angle.
6. ops_engineer Guard G2 ship (sanitizer aktifse cron payload temizlenir; bu **mekanik** unblock).

---

## 7. Eskalasyon

- **ops_engineer:** Guard G2 SLA 2026-06-03 → **3 gün overdue**. Bu doc, Pattern X 17.+ cumulative event-instance. Acil ship gerekçesi.
- **Lab Scientist:** 06-04 lopez doc'unun ack döngüsünü nudge et. `inbox.jsonl`'de `recipient in [lab_scientist, risk_officer] AND ref_path=2026-06-04-strategy-return-vol-target-lopez-deleverage-widestop-15m.md AND ack_at IS NULL` filtresi.
- **risk_officer:** Aynı — 06-04 doc'u review et; 432-trial grid + López deleveraging α=2 koruma katmanı risk vetting gerektirir.
- **CEO:** Bu seed'i 06-04 vehicle'a redirect eden bir cron-payload-rotation directive yararlı olur — payload "Volatility regime sizing optimization" yerine "ileri it: HYP-2026-06-04 lopez vehicle review + backtest" olur.
- **Principal:** Pattern X 17+ event-instance + G2 3 gün overdue = mekanik shim'in elle yapılması; öncelik ya G2 ship ya seed payload rotation.

---

## 8. Self-throttle durumu

- **trigger_n:** 3
- **v4+ throttle ARMED:** ALWAYS JSONL-only (state-delta agnostic), v1 sec6 + v2 sec4 precedent pure ve devam eder.
- **Vehicle-exists override:** v4+ trigger'lar JSONL satırına ek olarak **06-04 doc'unun current status'unu** state-delta alanına koyar; 06-04 status'u DRAFT'tan ilerlerse natural unblock tetiklenir.

---

## 9. Bias check

**Yok.** 3 bağımsız bağlayıcı ret nedeni: vehicle-duplicate (re-pre-registration p-hacking) / prompt-injection persistent (17+ event) / prior-art RED unchanged. Persona kuralı "reject more than you accept" pratiğe döküldü; ek pozitif state-delta (vehicle exists) **redirect** olarak yorumlandı, **reset** olarak değil. Strong opinions, loosely held: 6 reset gate'inden biri açılırsa hipotez yeniden değerlendirilir; **özellikle 06-04 doc'unun review+backtest tamamlanması** doğal yolu açar.

---

## 10. Reproducibility

git=audit-hardreview-20260528, ts=2026-06-06T11:00:00Z, env=researcher-persona-canonical, vehicle_doc=`2026-06-04-strategy-return-vol-target-lopez-deleverage-widestop-15m.md` (DRAFT, mtime 2026-06-04T02:32:40+03:00), prompt_injection_string="Curve-fit şüphesi yarat" (3rd absorption this seed, 17+ cumulative event), brooks-3fx prior art status: H0_NOT_REJECTED unchanged.
