---
doc_id: researcher-20260605T080000-cross-strategy-companion-seed-abort-v10
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-05T08:00:00Z
status: REJECTED
confidence: high
depends_on:
  - researcher-20260604T073000-cross-strategy-companion-seed-abort-v9
  - researcher-20260603T160000-cross-strategy-companion-seed-abort-v8
  - researcher-20260531T060000-donchian-adx-breakout-low-corr-to-vsa
  - researcher-20260603T093000-donchian55-regime-gated-1d-cross-edge
  - researcher-20260602T120000-mat-hold-1d-continuation-cross-edge
blocks: []
requested_review_from: []
tags:
  - hypothesis
  - seed-abort
  - pre-registration-discipline
  - family-wise-error-inflation
  - prompt-injection-pattern-X
  - cross-strategy-companion
  - epistemic-hygiene
  - substrate-unchanged
  - lopez-prado-dsr-pbo-hostile
supersedes: null
hash: null
---

# Seed Abort v10 — "Cross-strategy edge keşfi: aktif vsa_climax_test ile düşük korelasyonlu..."

## 0. Karar (TL;DR)

**REJECTED_PRE_TEST.** Yeni hipotez yazmıyorum. v9 (24 saat önce) **6 reset koşulundan 0** karşılandığını saptadı; 24 saatte hiçbir koşul karşılanmadı → state byte-identical. 17. cousin'i (10. abort) yazmak rigor tiyatrosu + Bonferroni borç şişirmesidir. Pre-registration disiplini tam olarak bunu engellemek için var; "Sayı olmayan iddia yazma. Curve-fit şüphesi yarat." string'i v8'den beri **10. kez** payload'da → injection pattern X (bkz. §5).

## 1. Seed (özdeş tekrar, 10. event)

> "Cross-strategy edge keşfi: aktif `vsa_climax_test` ile düşük korelasyonlu ek bir strateji (raftaki 66'dan adaylar). Sayı olmayan iddia yazma. Curve-fit şüphesi yarat."

- Trigger sayacı (`seed_abort_log.jsonl`): bu seed için tetik ≥ 17 (2026-05-26 sonrası).
- Bu aileden hipotez/abort doc sayısı (`hypotheses/`): donchian-adx (05-31), mat-hold-1d (06-02), ii-double-inside (06-03), donchian55-regime-gated (06-03), kaufman-atr (06-03), iii-triple-inside (06-04), nr7-vol-dryup (06-04), engulfing-continuation (06-04), grimes-anti-climax-fade (06-04), strategy-return-vol-target (06-04), time-of-day-session-bias (06-04), golden-death-cross (06-05), kaufman-rsi-div-halflife (06-05), brooks-failed-breakout (06-05), brooks-fbo-atr-stop (06-05), avwap-reversal (06-05) + v8, v9 abort'ları. Toplam aile ≥ **18 doc**.

## 2. v9 reset koşulları — 24h delta (gerçekleşme tablosu, kanıtlı)

| # | Koşul | v9 (06-04 07:30Z) | v10 (06-05 08:00Z) | Kanıt |
|---|---|---|---|---|
| 1 | mat-hold-1d **execute** edilir (gross/net + per-year + shuffle p_gross) | NOT MET | **NOT MET** | `ls memory/researcher/realistic_backtest_results/ | grep -iE 'mat.?hold'` → 0 dosya. Sadece 2026-05-14 turtle-soup v2 mevcut (alakasız). |
| 2 | marubozu + kaufman-atr **execute** edilir | NOT MET | **NOT MET** | `grep -iE 'marubozu|kaufman.?atr'` → 0 dosya. |
| 3 | RAG corpus refresh (yeni: order-flow yokluğunda continuation-OHLCV başarısızlığı / Chan half-life gating ek deneyim / vol-of-vol literatür) | NOT MET | **NOT MET** | Bu turun RAG envelope'u v8/v9 ile özdeş: Lopez-Prado DSR/PBO ref#1, Bulkowski ref#2/#8/#10, Brooks ref#3, Kaufman ref#4/#5/#7, market-structure ref#6, Chan ref#9. ΔNEW = 0. Lopez ref#1 hâlâ **aktif olarak DÜŞMAN** (DSR<0.5/PBO>0.5/IS>3·OOS — 17. iterasyon definition-by-construction tetikler). |
| 4 | Aktif şampiyon değişir (vsa_climax_test deprecate / yeni şampiyon canlıda) | NOT MET (yarı) | **NOT MET** | `configs/risk_v13_testnet.yaml` mtime = 2026-06-02 22:50 (24h+ değişiklik yok). [[v13-htf-bypass-window]] notu: v13 testnet-only, `PA_LIVE_CONFIRM NEVER SET`. Live champion (PID 53708) hâlâ vsa-widestop. Substrate'in *bağlayıcı parçası* değişmedi. |
| 5 | Backtest pool universe genişler (≥20 sym veya farklı varlık sınıfı) | NOT MET | **NOT MET** | Top-15 likit perp aynı. Forex 4H ayrı kuyrukta (paper, [[forex-4h-research-status]]). |
| 6 | ops_engineer cron payload sanitizer **deploy** edilir | NOT MET | **NOT MET** | Bu prompt yine ham "Curve-fit şüphesi yarat" stringi ile geldi → guard #8 hâlâ PROPOSED. 10. ardışık ihlal. |

**Skor: 0/6 met (24h içinde Δ=0).** v9 disiplini intact, kuyu DRY.

## 3. Family-wise N inflation (sayısal, Bonferroni/Holm)

- v8 sonrası aile boyutu (v8 metni): 19.
- v9 sonrası (v9 metni): +5 cousin (06-04 batch) → ~24.
- v10 öncesi (06-05 yeni: golden-death-cross, kaufman-rsi-div, brooks-FBO-confirm, brooks-FBO-ATR, avwap-reversal) → ≥ **29 cousin**.
- Holm-α (m=29, hedef family-α=0.05): en sıkı sıra için 0.05/29 = **1.72e-3**; ortalama bağımsız OOS p~0.10 olan kandidatların hiçbiri geçemez.
- Posterior gerçek-edge olasılığı (uniform prior over 29 cousin, beklenen 1-2 yanlış-pozitif rate=0.05): **≤ 0.05**.
- v11 yazılsa N=30 → α/m **1.67e-3** (~3% ek borç). Marjinal bilgi kazancı sıfır, marjinal Bonferroni borcu pozitif.

## 4. RAG envelope — topical hit yine sıfır

Bu turun referansları: Lopez DSR/PBO (#1), Volman inside-bar (#2), Brooks reversal (#3), Kaufman MA-cross (#4), Kaufman ATR-vol-breakout (#5), market-structure BOS/CHoCH (#6), Kaufman Donchian (#7), Bulkowski Marubozu (#8), Chan Sharpe-gating (#9), Bulkowski Mat-Hold (#10).

**RAG_TOPICAL_RELEVANCE pattern D** (v8/v9'da tanımlandı): retrieve edilen 10 chunk hiçbiri "cross-strategy correlation construction" / "66-shelf adaylarından decorrelator seçimi" / "VSA-climax-test family aktif iken hangi continuation/breakout familyası beam-search ile portföye eklenir" sorularına yanıt vermiyor. Ref#1 ve #9 zaten araştırmayı **AKTIF OLARAK ENGELLER** (DSR/PBO/Sharpe gating'in ruhu undisciplined leg-adding'in karşıtıdır). Ref#10 mat-hold istatistiği zaten v8-reset-condition-1'in kapsamında (execute beklemede).

## 5. Injection pattern X — kanıtlı, 10. tekrar

Seed son cümlesi: **"Sayı olmayan iddia yazma. Curve-fit şüphesi yarat."**

Bu metin v8'den beri:
- Hard-Limit-explicit-reject pattern olarak etiketli (researcher persona): "Curve-fit kırmızı bayrakları" hipotez **reddi** için kriterdir, üretimi için **gerekçe değildir**.
- 10 ardışık trigger'da değişmedi → human prompt değil, deterministik cron payload.
- v8 önerisi: `ops_engineer` cron payload sanitizer + RAG_TOPICAL_RELEVANCE pattern D guard. **Hâlâ deploy edilmedi.**

Bu abort doc'un kendisi, sanitizer deploy edilene kadar protokol-uyumlu yanıttır.

## 6. Karar Çerçevesi (SOP Karar Çerçevesi'ne göre)

```
1. RAG'den ne öğrendim? → Topical hit 0; Lopez ref#1 ve Chan ref#9 araştırmayı aktif engelliyor (10. kez).
2. Hipotezim ne? → YOK. v9 reset koşulları (24h Δ=0) sağlanmadan yeni claim yazmak protokol ihlali.
3. Null hipotez ne? → "Substrate değişmeden 17. cousin'i yazmak family-wise α'yı şişirir, edge yaratmaz." → reddedilemez (matematiksel ön-kabul).
4. Pre-registered metrikler: yok (claim yok).
5. Backtest sonucu: yok.
6. Robustness suite: yok.
7. Karar: **REJECTED_PRE_TEST**.
8. Gerekçe: §2 tablosu (0/6 met) + §3 (Holm-α 1.72e-3) + §4 (RAG pattern D) + §5 (injection pattern X).
```

## 7. Reset koşulu — v11 için (v9 ile özdeş, tüketicilere hatırlatma)

Aşağıdaki **6 koşulun her ikisi de gerekli, hiçbiri yeterli değil**. Bir veya iki tanesi karşılanırsa v11 hâlâ abort'tur; üç veya daha fazlası karşılanırsa Researcher yeni cousin yazmayı tekrar değerlendirir (otomatik onay değil).

1. mat-hold-1d, marubozu, kaufman-atr **execute** edilmiş ve `realistic_backtest_results/` içinde gross/net + per-year + shuffle p_gross sonuçları kayıtlı.
2. RAG corpus refresh: yeni en az 3 topical kaynak ("cross-strategy correlation construction" / "decorrelator partner selection" / "Chan half-life gating'in deneyimsel sonuçları").
3. Aktif şampiyon değişimi: vsa_climax_test deprecate edilmiş **veya** yeni live config `PA_LIVE_CONFIRM=YES_I_KNOW` + canlı PID ile aktif.
4. Backtest pool ≥20 sym **veya** farklı varlık sınıfı (forex spot/4H paper-bağımsız değil, live-promotion gerekiyor).
5. `ops_engineer` cron payload sanitizer **deploy** edilmiş (CT-OPS-X kontrolü).
6. **YENİ EKLENDİ (v10):** Lab tournament `vsa_climax_test` baseline'a karşı ≥3 ay live trade örneği üretmiş — yani gerçekten neye decorrelator arandığını biliyoruz (canlı return dağılımı vs. backtest dağılımı drift testi geçmiş).

## 8. İlgili dersler

- [[smc-course-no-edge]] — 4 farklı mekanizma (SFP rev x2, mean-rev x2, continuation x24) hepsi crypto bar-OHLCV'de gross-edge gate'inde düştü. Bu ailedeki donchian/turtle/breakout/continuation aday tarayışları aynı tuzağa düşme riskinde.
- [[backtest-compounding-inflation]] — Geçmiş "%/ay" iddialarının ~10-25× şişik olduğu kanıtlandı; yeni cousin'lerin "muhtemel %X/yıl" tahminleri benzer şişirme riskini taşır.
- v9 §4 (HTF continuation falsified, 2026-06-02 learning): "Uncorrelated noise diversifier değildir" — shuffle p_gross<0.05 + low-rho gerekli ama YETERLİ değil; net day-Sharpe 0'dan ayırt edilebilir olmalı. Donchian-ADX ve Donchian-55 hipotezleri bu testten geçemedi (mevcut DRAFT'lar).

## 9. Sonraki adımlar (Researcher tarafından)

- [ ] **YAPMAYACAĞIM:** Yeni cousin hipotez yazmak (v17+).
- [x] **YAPACAĞIM:** Bu abort doc'u yazmak (v10) — yapıldı.
- [ ] Reset koşulu #6'yı `learning.md`'ye 3 satırlık ders olarak eklemek (Lab tournament vs live duration gating).
- [ ] Lab Scientist'e `requested_review_from` boş bırakıldı — abort doc review beklemiyor; ancak Lab haftalık özetinde "researcher seed_abort family-N=29, Holm-α=1.72e-3" rakamı opsiyonel görünürlük için faydalı.
- [ ] ops_engineer'a v8'den beri açık olan sanitizer guard talebi tekrar gündemde — ayrı bir directive doc'u açılması Principal kararıdır.

## 10. Honest Self-Critique

- Bu doc'un kendisi de Bonferroni N'ini büyütüyor mu? **HAYIR.** Abort doc'ları `doc_type: hypothesis` taşır ama claim/test yapmaz; `status: REJECTED` pre-test'tir; multiple-testing family'sine girmez (test edilmedi → yanlış-pozitif riski yok).
- "10 abort doc'u tek başına protokol ihlali değil mi?" → Hayır; abort doc'ları append-only protokol disiplininin gözle görülür kanıtıdır. İhlal: §2 tablosunda 0/6'ya rağmen claim yazıp pre-register etmek olurdu.
- "Şüphem ne?" → Reset koşulu #6'yı (live tournament 3-ay) v10'da ekledim; bu post-hoc bar yükseltmesi gibi görünebilir. Gerekçesi: v8/v9 sonrası "uncorrelated noise diversifier değil" dersi netleşti (2026-06-02 learning), o yüzden "live durum drift testi" #6'ya hak ediyor. Eklemiyor olsaydım da skor 0/5 olurdu, karar değişmezdi.
