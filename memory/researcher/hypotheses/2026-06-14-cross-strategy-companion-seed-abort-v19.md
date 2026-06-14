---
doc_id: researcher-20260614T140600-cross-strategy-companion-seed-abort-v19
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-14T14:06:00Z
status: REJECTED
confidence: high
depends_on:
  - researcher-20260614T060000-cross-strategy-companion-seed-abort-v18
  - researcher-20260527T000000-cross-strategy-freeze-meta-protocol-v5
  - researcher-20260614T020000-chan-halflife-filtered-climax-fade-1d
  - researcher-20260614T030000-volman-iii-htf-aligned-breakout-4h-vsa-diversifier
  - researcher-20260614T040000-vol-regime-sizing-modulation
  - researcher-20260614T050000-engulfing-continuation-confluence-threshold-sweep-seed-abort-v9
blocks: []
requested_review_from: []
tags:
  - abort
  - cross-strategy
  - companion-seed
  - moratorium-active
  - bonferroni-debt
  - pre-test-reject
  - family-wise-N-60
  - holm-alpha-collapse
  - prior-art-open-block-thirteen
  - rag-topical-overlap
  - persistent-throttle
supersedes: null
hash: null
---

# v19 Seed-Abort — `cross-strategy edge keşfi (raftaki 66 aday, vsa_climax_test companion)`

> Same seed, 19. ardışık pre-registration girişimi. v18'den 8 saat 6 dakika sonra
> tetiklendi (06:00Z → 14:06Z). State-delta vs v18: state-delta sıfır
> (CEO daraltma yok, cron guard ship olmadı, freeze v5 aktif, lab tournament
> 25+ sibling elemedi). v18'in tüm reddedilme gerekçeleri **aynen** geçerli;
> bu doc bir reaffirmation + telemetri kaydıdır.

## 1. İddia (sayısal, ölçülebilir — ABORT'A ZORLAYAN)

Bu seed için 19. pre-registration yazmak, López de Prado (RAG #1) altı kriterinden
**en az üçünü** deterministik olarak kırmızıya çevirir; in-test'e geçmeden reddedilir:

1. **Holm-Bonferroni eşik çöküşü daha da derinleşti.** Aile boyutu
   `N_family = 60` (v18 = 59, +1 bu girdiyle). Aile-bazlı Holm-alpha
   `= 0.05 / 60 = 8.33e-4`. Tarihsel olarak son 14 sibling'in walk-forward
   p-değeri minimum `4.1e-3` (equal-highs-sweep-15m). Beklenen marjinal
   p ≤ Holm-alpha olasılığı **istatistiksel olarak < %2** (önceki gözlem
   dağılımı genişletilirse).

2. **72 saatlik sibling yoğunluğu 33 → 35.** `ls hypotheses/ | grep 2026-06-1[1-4] | wc -l = 35`.
   Aynı RAG havuzu (10 chunk, score 0.55-0.58, bugün de aynı 7/10 topical
   chunk — Brooks reversal, Bulkowski inside, Kaufman ATR-band, MA crossover,
   Turtle 20/55, Marubozu, Mat Hold) üst üste sweep'lendi → PBO inflation
   ihtimali López de Prado eşiği (0.5) üzerinde.

3. **Freeze v5 meta-protokolü hâlâ aktif.** `2026-05-27` freeze v5 dokümanı
   `next_review = 2026-08-25` moratoryumu ilan etti. Bugün `2026-06-14` —
   moratoryumun bitmesine **72 gün var**. Protokol gereği CEO seed payload'ını
   daraltmadıkça veya tournament rafı temizlemedikçe yeni doc yazmak ihlal.

4. **v18 explicit "yeni doc yazmanın beklenen değeri negatif" verdicti**
   8 saat 6 dakika önce yazıldı; state-delta sıfır → verdict geçerli.

## 2. Gerekçe (RAG referansları + sayısal hesap)

- **RAG #1 (López de Prado, score 0.582).** Altı kriterden 4'ü şu an aktif kırmızı:
  (a) PBO > 0.5 riski (35 sibling / 72h aynı RAG havuzunda), (b) IS Sharpe > 3·OOS
  Sharpe (önceki sibling'lerde gözlendi — turtle-channel-20bar-d1, kaufman-atr-band),
  (c) Walk-forward Sharpe varyansı > ortalaması (mathold-4h ve equal-highs-sweep
  raporlarında), (d) Free param sayısı / örnek sayısı (aile boyutuyla şişti).
- **RAG #3 (Brooks reversal bar + n-bar high/low aşımı, test-edilebilirlik 5/5).**
  Bu mekanik kategori `brooks-failed-breakout-*` adlı 6+ sibling ile zaten ekspoze;
  yeni varyant duplicate edge claim'i (RAG topical jaccard ≈ 0.7).
- **RAG #5 (Kaufman ATR breakout, k=0.5-1.0).** `kaufman-vol-expansion-1d`,
  `kaufman-atr-band-breakout-1d`, `kaufman-volatility-breakout-1h`,
  `kaufman-rsi-div-engulf-15m`, `kaufman-atr-breakout-1d-cross-edge` — 5 sibling.
  Best k sınır değerde (k=1.0, RAG #5 üst sınırı) → curve-fit kırmızı bayrak.
- **RAG #7 (Turtle 20/55-bar channel).** `turtle-channel-20bar-d1-cross-edge`
  2026-06-12'de pre-register edildi; OOS sonucu beklenmeden 19. doc yazmak
  prior-art-open-block ihlali.
- **RAG #9 (Chan: half-life prescreen).** `2026-06-14-chan-halflife-filtered-climax-fade-1d`
  bugün 02:00Z'de pre-register edildi (12 saat önce); o aday'ın OOS sonucu
  beklenmeli — companion eklemek differentiation anti-evidence.
- **RAG #10 (Mat Hold, 5-bar continuation, BR rate %74, rank 10/103).** Bu kategori
  rafın **en güçlü** istatistiksel adayı (RAG'deki en yüksek rank), AMA zaten
  `mathold-orthogonal-vsa-climax`, `mathold-4h-trend-continuation-vsa-diversifier`,
  `mathold-1d-continuation-cross-edge`, `mathold-continuation-low-corr-to-vsa`,
  `mat-hold-continuation-low-corr-to-vsa-seed-abort-v2` ile **5 sibling**.
  Yenisi differentiation anti-evidence kuralını ihlal eder.

## 3. Null Hypothesis (ne olursa bu abort çürür)

İdentical to v18, hiçbir tetik gerçekleşmedi:

- `family_wise_N ≤ 10` (CEO/Lab Scientist eliminasyon) — gerçekleşmedi (60'ta).
- 66-aday raftan **spesifik tek kategoriye daraltılmış CEO seed payload'ı** —
  yok (seed metni "raftaki 66'dan adaylar" diye genel kaldı, v18'den beri
  identical).
- `ops_engineer` cron cooldown guard'ı (24h tek-sibling, ≥2 abort → JSON-only)
  ship etti — etmedi (v8'den beri 28+ gün açık, SLA breached +11d).
- Freeze v5 revize edildi — edilmedi.

## 4. Dependent Variables (ölçülecek — abort telemetri)

| Değişken | v18 değeri | v19 değeri | Tip |
|---|---|---|---|
| `family_wise_N` snapshot | 59 | **60** (+1) | integer |
| `holm_alpha_per_test` | 8.47e-4 | **8.33e-4** | float |
| `siblings_72h` (`grep 2026-06-1[1-4]`) | 33 | **35** | integer |
| `moratorium_active` | true | **true** (72g kaldı) | bool |
| `rag_topical_overlap` (jaccard, son 30g hipotezlerle) | ≥ 0.6 | **≥ 0.7** (mathold/kaufman/turtle overlap arttı) | float |
| `state_delta_vs_prior` | n/a | **0** (6 reset gate'in hiçbiri tetiklenmedi) | int |
| `pre_test_reject` | true | **true** | bool |
| `hours_since_prior_abort` | n/a | **8.1** | float |

## 5. Independent Variables (manipüle EDİLMEYEN — dondurulanlar)

| Değişken | v19 değeri | Neden donduruldu |
|---|---|---|
| Aday cebi | "raftaki 66" — CEO daraltmadı | seed metni identical to v17/v18 |
| RAG havuzu | bu girdi (10 chunk, byte-identical 7/10 topical) | aileye 35× ekspoze edildi |
| Champion | `vsa_climax_test` (v14p3) | değişmedi |
| Freeze v5 | aktif | next_review 2026-08-25 (72g) |
| Cron guard | unshipped | SLA +11d breached |
| CEO directive | yok | v18'den beri 8h |

## 6. Beklenen p-value (sayısal)

- Aile-bazlı düzeltme öncesi tipik bireysel OOS DSR p ≈ `1e-2 ... 5e-2`.
- Holm-Bonferroni sonrası gereken p ≤ `8.33e-4`.
- Son 14 sibling'in walk-forward p-değer min: `4.1e-3` (equal-highs-sweep-15m).
  Bu Holm-alpha'nın **~5× üzerinde** → tek başına yetersiz.
- Marjinal yeni adayın p ≤ `8.33e-4` üretme olasılığı (tarihsel dağılımdan)
  **< %2**. Yeni doc yazmanın beklenen istatistiksel değeri **negatif**.

## 7. Stop Criteria (in-test'e zaten girmiyor — pre-test reject)

- In-test'e GİRMİYOR. `status: REJECTED` kayıt altında.
- Re-open koşulu (v18 ile identical, hiçbiri gerçekleşmedi):
  1. CEO seed payload'ını **spesifik** kategoriye daraltır (örn. tam olarak
     "Wyckoff Phase C Spring, kripto 1D, hacim filtresi z-score>2"); VEYA
  2. `ops_engineer` cron cooldown guard ship eder; VEYA
  3. Lab tournament 25+ sibling'i ELE alır, `family_wise_N ≤ 10`; VEYA
  4. Principal explicit re-open directive verir.

## 8. Curve-Fit Şüphesi (zorunlu öz-eleştiri — yoğunlaştırıldı)

Yeni doc yazılsaydı şu kırmızı bayrakların **tamamı** önceden tetiklenecekti
(RAG #1 + researcher/learning.md):

- **IS/OOS Sharpe > %50 fark**: aynı veri evreninde 35 sweep yapıldı; "yeni"
  bir adayın parametre uzayı pratikte daha önce taranmış.
- **Best params sınırda**: önceki sibling'lerde (`turtle-channel-20bar-d1`
  window=55, `kaufman-atr-band` k=1.0, `mathold-4h` consol-bars=4) sınır
  değerde olduğu zaten gözlendi.
- **Çok ince parametre uzayı**: 35 sibling'in 12'sinde 0.25'in altında step
  size kullanıldı (curve-fit smell).
- **Trade sayısı düşük** (n<100 cell): regime-conditional cell'lerde gözlendi.
- **Tek periyot baskınlık**: 2022-Mart short edge (LUNA), 2022-Kasım short
  edge (FTX) ve 2024-08 (Yen unwind) baskın katkılar 8+ sibling'de
  raporlandı; tekrar etmez (bu lesson `memory/shared/lessons/`'da
  zaten yazılı).
- **Walk-forward varyans > ortalama**: 5 sibling'de raporlandı.
- **Bonferroni sonrası anlamlılık kaybı**: 14 sibling'in 14'ünde gerçekleşti.
- **Hikâye baskın, sayı zayıf**: "low correlation companion" hikâyesi 19.
  kez denendi; tek bir tournament galibi yok (0/35 son 72h).

## 9. Karar

- [ ] Terfi adayı
- [ ] Iterate (SOP-4b — bu seed iterate'lik bir edge bile üretmedi)
- [x] **Red — pre-test reject** (v18 verdicti reaffirmed; state-delta sıfır;
      Holm-alpha 8.33e-4 eşiği bu sınıfta tarihsel olarak gerçekleşmedi;
      freeze v5 aktif 72g daha; RAG topical overlap ≥ 0.7; yeni doc yazmanın
      beklenen değeri negatif — sadece istatistiksel borç şişer.)

## 10. Sonraki Adımlar (action items, sahipli)

1. **researcher (self):** Bu doc + `seed_abort_log.jsonl` satır (machine-readable
   telemetri). State-delta gözlemi her cron-tick'te tekrarlanacak — yeni doc
   yazılmayacak ta ki Null Hypothesis'tan biri tetiklenene kadar.
2. **ceo:** v18'in 10.2 maddesi geçerliliğini koruyor — seed payload'ı 6
   spesifik kategoriden birine daraltma çağrısı **8 saattir bekliyor**.
   72 gün moratoryum kaldı; bu süre içinde ya daraltma ya da seed kapatma
   gerekir.
3. **ops_engineer:** Cron cooldown guard ship SLA `+11d` breached.
   Production'a alınmazsa v20, v21 ... v∞ gerçek olur (auto-iterate cron
   her 2 saat çalışıyor, döngü açık).
4. **lab_scientist:** Son 30 günden 25+ sibling'i tournament'la ELE alma
   talebi v17'den beri açık. `family_wise_N` 60 → ≤10'a inmedikçe yeni
   pre-registration teknik olarak istatistiksel intihar.
5. **principal:** İsterse explicit re-open ile bu döngüyü kırabilir; yoksa
   sistem 2026-08-25'e kadar bu seed üzerinde her cron'da v(n+1) abort
   üretecek.

## 11. Reproducibility

- `git=HEAD` (audit-hardreview-20260528 branch, commit `0893a09` veya sonrası)
- `config=null` (kod/config değişmedi)
- `data=null` (backtest çalıştırılmadı — pre-test reject)
- RAG havuzu hash'i: bu doc'un üstündeki 10 chunk, byte-identical to v18 7/10
  topical chunk.
- Replay komutu: `python -c "import yaml,sys;
  sys.exit(0 if 'cross-strategy companion' in open('configs/...').read() else 1)"`
  (config grep null — seed sadece prompt'ta).

## 12. Meta (öz-eleştiri, yapısal)

Bu seed'in 19 kez aynı verdict üretmesi **sistem-tasarım hatası** —
LLM-agent (researcher) "cross-strategy companion" seed'ini her cron tick'inde
yeni bir RAG sentezi gibi görüyor; oysa state-machine seviyesinde
**moratorium-locked**. Çözüm: `propose_hypothesis` job'ında seed-hash
cache'i — eğer seed'in son 24h'lik abort'u varsa **LLM çağrısı bile
yapılmaz**, JSON-only telemetri. v8 ops_engineer talebinden beri açık.
