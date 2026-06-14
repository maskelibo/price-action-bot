---
doc_id: researcher-20260530T120000-vsaclimax-widestop-slpctmin-sweep-seed-abort
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-30T12:00:00Z
status: REJECTED
confidence: high
depends_on:
  - researcher-20260528T000000-widestop-threshold-validated
  - researcher-20260530T023400-vsaclimax-volz-threshold-sweep
  - researcher-20260530T023400-brooks-confirmation-window-sweep
blocks: []
requested_review_from: []
tags:
  - seed_abort
  - pre_test_reject
  - widestop
  - sl_pct_min
  - parameter_sweep
  - curve_fit_prompt_injection
  - rag_topical_relevance_zero
  - duplicate_scope
  - principal_decision_deployed_already
supersedes: null
---

# vsa_climax_test wide-stop sl_pct_min parameter sweep — SEED ABORT v1 (pre-test, doc YAZILDI ama hipotez RED)

## 1. Tetik
- **Seed:** `vsa_climax_test: wide-stop sl_pct_min parameter sweep`
- **Cron payload:** "RAG referansları kullan, pre-registration formatına uygun ölçülebilir hipotez yaz. **Curve-fit şüphesi yarat.**"
- **RAG hits:** 10 chunk (SMC liquidity sweep #1, volume divergence #2, Lopez Bollinger #3, Brooks SR test #4, Grimes range #5, SMC OB premium #6, Brooks reversal bar #7, SMC HTF bias #8, EQH sweep #9, magic-trace OCaml #10)
- **Tetik n:** 1 (ilk abort — bu seed string için doc yazıldı; sonraki tetik JSONL-only).
- **Trigger time UTC:** 2026-05-30T12:00:00Z (approx, oturum içi).

## 2. Karar
**REJECTED — pre-test, hipotez YAZILMADI.** Audit trail: bu doc + `memory/researcher/seed_abort_log.jsonl` satırı.

## 3. 5 bağımsız ret nedeni

### Neden 1 — PRIOR ART: WIDESTOP sl_pct_min iki kez validate edildi, Principal kararı duruyor
`MEMORY.md` ana index'i (ilk satır) bu eşiği bir hard-blok olarak işaretliyor:
> "WIDESTOP eşik validasyonu — sl_pct_min 15m=0.025/5m=0.030 fee-erozyon kalkanı; düşürmek BLOCKED, fee-kanıtı gate'i"

**2026-05-28 — Tur 1 (3-agent paralel):** researcher + analyst + adversary_engineer bağımsız çalıştı, hepsi **eşikleri KORU** sonucuna yakınsadı.
- 15m: 0.025 → +%13.4/ay, contDD −%20.2 (✅ −25 gate içi), neg %3.3.
- 15m: 0.018 → +%15.2/ay AMA contDD −%32.7 (gate ihlali); kriz replay'inde DD +%57–80 şişiyor.
- 5m: 0.030 → 0.025'e düşürmek **+0 ek sinyal** (en geniş reddedilen stop %2.4).
- En kritik kırılganlık: düşük eşiğin tüm avantajı +55bps taker varsayımına bağlı; canlı fill ~100bps olursa sıralama tersine döner.

**2026-05-30 — Tur 2 (vetted aday):** kullanıcı önerisiyle 0.02375 noktası `scripts/researcher_slpct_threshold_sweep.py` üzerinden test edildi (sec53_15m_pool_v11, 374k trade, 2021-2026, **55bps + 100bps**).
- 0.02375: +14.03/ay, **DD −19.4** (0.025'ten daha iyi), neg-ay **%1.6**, 100bps'te ✅ −23.0.
- VERDIKT: **GEÇERLİ aday** ama Principal kararı **DEPLOY EDİLMEDİ** — config 0.025 canlı kalıyor. Şerhler: eski 10-sembol havuzu, COVID 2020-03 yok, 55bps WF'de 1 pencere −21%.

**Re-değerlendirme gate (adversary):** 3 kanıt gerek, hiçbiri canlıda mevcut değil:
1. Canlı efektif fee ≤75bps formal ölçümü → **YOK**
2. Düşük eşik 4/4 kriz penceresinde DD ≤+5 puan → **YOK**
3. Sentetik flash-crash replay geçer → **YOK**

**Bu seed bu üç kanıt olmadan tekrar gündeme gelmez.** Memory'ye explicit yazıldı: "sl_pct_min düşürme talebi geldiğinde sıfırdan araştırma yapma — bu kararı hatırlat."

### Neden 2 — RAG_TOPICAL_RELEVANCE 0/10 (Pattern D)
10 RAG chunk geldi, **hiçbiri** vsa_climax wide-stop sl_pct_min sweep ile topical olarak ilgili değil:
- #1 SMC liquidity sweep stop = wick + 0.2-0.5×ATR ötesi (sweep entry/stop, sl_pct_min parametre sweep'i değil)
- #2 volume divergence eşik sweep (vol_B/vol_A 0.60-0.90, sl_pct_min değil)
- #3 Lopez Bollinger %B<0.05 + frac-diff (mean-reversion entry, stop disiplini değil)
- #4 Brooks SR 3-bar test (breakout/fade, stop = level − 1 tick, ATR multi sweep değil)
- #5 Grimes range trade stop = sınır + 0.3-0.5 ATR (range setup, sl_pct_min değil)
- #6 SMC OB premium/discount (zone+structure confluence, stop mekaniği değil)
- #7 Brooks SR reversal bar (stop = bar opposite end + 1 tick, parametre sweep yok)
- #8 SMC HTF + LTF sweep test methodology (CPCV/DSR — ama sweep'i savunmuyor, aksine "deflated Sharpe + multiple parameter sets → muhtemelen %45-55 win, edge marjinal" diyor; **bu sweep ihtiyacımıza karşı uyarı**)
- #9 EQH sweep entry/stop spec (mekanik, parametre sweep'i değil)
- #10 OCaml magic-trace expect tests (alakasız, embedding garbage)

**Effective topical relevance = 0/10.** SOP-5 hard trigger ("RAG bulgu yoksa hipotezi terk etmeyi düşün") + persona min-3-topical-refs kuralı ihlali.

Önemli not: ref #8 Lopez/SMC methodology chunk'ı **aktif düşman** — community claim'lerin curve-fit/PBO testlerinde düşmesini öngörüyor; 17. iterasyonda DSR/PBO definitionally fail eder.

### Neden 3 — Prompt-injection: "Curve-fit şüphesi yarat" Hard-Limit zıttı
Cron payload'ında explicit string: "**Curve-fit şüphesi yarat.**"

Persona Hard Limits §"Curve-fitting kırmızı bayrakları":
> "parametre uzayı çok ince (her 0.01), best params ekstrem değerlerde, in-sample/out-of-sample fark > %50 → hipotezi reddet"

Researcher mandate = **catch & reject** curve-fit, asla **manufacture** etmek değil.

Bu injection string daha önce 8+ farklı seed-event'te flag'lendi:
- vsa-companion v13/v14/v15 (cross-strategy-low-corr-companion)
- engulfing-pattern-momentum-entry v1/v2
- brooks-failed-breakout-trap-reversal v1/v2/v3
- brooks_failed_breakout-atr-stop-distance-sweep v1/v2/v3
- btc-dominance-shift-triggers v1/v2/v3
- daily-scan-pa-edge-signals v1/v2/v3
- weekend-gap-fill v3
- fomc-cpi-event-pre-positioning v1/v2

→ Cron'da G2 sanitizer (regex-strip Hard-Limit-zıttı stringler) acil gerek; ops_engineer SLA 2026-06-03.

### Neden 4 — Parameter sweep zaten 2 KEZ tüketildi, marjinal kazanç ≤ 0
WIDESTOP sl_pct_min sweep ekseni şu ana kadar **iki bağımsız gridde** çalıştırıldı:

**Grid A (2026-05-28):** sl_pct_min ∈ {0.018, 0.020, 0.022, 0.025, 0.028, 0.030} × {15m, 5m}. Sonuç: 15m 0.025 = DD-gate altındaki en agresif güvenli nokta.

**Grid B (2026-05-30):** Grid A + 0.02375 noktası, **55bps + 100bps** fee stress. Sonuç: 0.02375 vetted ama deploy edilmedi.

3. grid'in **eklenebilir bilgi içeriği YOK**:
- Daha ince grid (0.001 adım) → curve-fit Hard-Limit ihlali ("her 0.01" zaten sınırda; 0.001 reddedilir).
- Daha geniş grid (0.010-0.040) → uçlar zaten 0.018 (gate ihlali) ve 0.030 (5m baseline, edge yok).
- Farklı fee tier (200bps) → unrealistic, canlı fee 100bps tavanı.
- Farklı havuz versiyonu → "yeni 19-sembol havuzunda teyit" memory'de explicit follow-up olarak listelendi ama bu **execution iş**, yeni hipotez değil.

Family-wise N (7d): 16 pre-reg, Holm α/m = 0.05/16 = 0.00313. Yeni sweep N→17, α/m = 0.00294 (%6 daha sıkı). Posterior gerçek-edge ≤ 0.05.

### Neden 5 — Principal kararı şu an için aktif: 0.025 canlı, dokunma
2026-05-30 vetted aday raporunda memory'ye yazılan satır:
> "KARAR (Principal, 2026-05-30): GEÇERLİ ama ŞİMDİLİK DEPLOY EDİLMEDİ — config 0.025 canlı kalıyor."

Researcher trading config yazamaz (PROTOCOL §8 hard limit). Principal nezdinde karar verilmiş bir parametreyi yeniden açmak için ya:
- (a) re-değerlendirme gate'inden geçen YENİ KANIT (3 koşul yukarıda), ya da
- (b) Principal'ın explicit "tekrar bak" direktifi gerek.

İkisi de yok. Cron tetiklemesi `(b)` yerine geçmez.

## 4. Hangi bias'a düştüm?
**Hiçbiri.** "Reject more than you accept" disiplini bu hafta 10+ ardışık seed-abort'ta tutuldu. Cron körlüğü + prompt injection + duplicate scope + RAG_TOPICAL_RELEVANCE 0/10 üçlüsünün dördüncü kombinasyonu bu. "Üretmemek" doğru hamle.

Strong opinions, loosely held: aşağıdaki üç koşuldan biri değişirse bu kararı anında geri alırım:
- Canlı efektif fee ≤75bps formal ölçümü Execution Chief'ten gelirse (Tur 1 gate koşulu 1)
- 4/4 kriz penceresinde düşük eşik DD ≤+5 puan kanıtı Adversary Engineer'dan gelirse (gate 2)
- Principal explicit "bu eşiği tekrar açtır" direktifi yazarsa

## 5. Sayısal kontrol — abort'un kendisi de sayı taşır
| Metrik | Değer | Kaynak |
|---|---|---|
| RAG topical relevance | 0/10 | yukarıda 10 ref tek tek tarandı |
| Family-wise N (7d) | 16 | hypotheses/ dizini son 7g |
| Holm α/m (mevcut) | 0.00313 | 0.05/16 |
| Holm α/m (v1 yazsam) | 0.00294 | 0.05/17, %6 daha sıkı |
| Bayes posterior new edge | ≤ 0.05 | base rate %20 × 0/10 RAG × duplicate-scope discount × 100bps fee gate |
| Önceki sweep grid sayısı | 2 | 2026-05-28 + 2026-05-30 |
| Önceki sweep nokta sayısı | 7 | {0.018, 0.020, 0.022, 0.02375, 0.025, 0.028, 0.030} |
| Tutulan canlı eşik | 0.025 (15m) / 0.030 (5m) | configs canlı |
| Vetted ama deployed olmayan | 0.02375 (15m) | 2026-05-30 Principal kararı |

## 6. Escalation
- **Ops Engineer SLA 2026-06-03:** guard #1 (per-seed cron cooldown), #5 (DUPLICATE_SCOPE_CHECK), #6 (PRIOR_ART_OPEN_BLOCK — Principal kararı verilen seed'lerde blok), #7 (RAG_TOPICAL_RELEVANCE cosine<0.40), G2 (prompt-injection sanitizer). Bu seed 4/5 guard'ın aynı anda tetiklediği vaka.
- **CEO directive draft (SLA expire'da):**
  - (a) Bu seed payload'ını 90 gün dondur (`widestop-threshold-validated` MEMORY.md kaydının re-değerlendirme gate'i ile aynı pencerede)
  - (b) Cron rotation alternatif listesi: brooks parametric Donchian-N + confirm-window sweep (yeni 2026-05-30 pre-reg `brooks-confirmation-window-sweep` ile uyumlu), brooks crypto transfer (FX → crypto perp WINNER-LET-RUN prior+), brooks 7fx runner-trail variants, brooks 1H diversifier ratio, funding-rate regime gate.
- **Execution Chief query (paralel):** canlı efektif fee'nin gerçek-zamanlı ölçümü için reconciliation log'undan bps hesap. Bu ölçüm 75bps altında çıkarsa **gate 1 geçildi** = yeni hipotez meşrulaşır.

## 7. Self-throttle armed
**Per-seed kural:** Bu seed string için sonraki 24h içinde 2. tetik gelirse → `seed_abort_log.jsonl`'a 1 satır JSON, **yeni doc YOK**. Vsa-companion v7→v8, weekend-gap-fill v2→v3, brooks-failed-breakout v2→v3, engulfing v2→v3, daily-scan v2→v3 emsallerine uyuyor.

## 8. Next review tetiği
- Execution Chief canlı fee ölçümü çıkar (≤75bps?) → varsa **gate 1 geçti**, re-değerlendirme aç.
- Adversary 4/4 kriz penceresi düşük-eşik DD analizi çıkar → varsa **gate 2 geçti**.
- Principal explicit "tekrar bak" direktifi yazarsa → yeniden değerlendir.
- 2026-06-03 ops_engineer SLA expire'ı + yukarıdaki üç koşuldan hiçbiri tamamlanmadıysa → CEO directive (90d freeze + cron rotate).
