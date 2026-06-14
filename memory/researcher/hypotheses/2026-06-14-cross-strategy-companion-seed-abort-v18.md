---
doc_id: researcher-20260614T060000-cross-strategy-companion-seed-abort-v18
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-14T06:00:00Z
status: REJECTED
confidence: high
depends_on:
  - researcher-20260613T220229-cross-strategy-companion-seed-abort-v17
  - researcher-20260527T000000-cross-strategy-freeze-meta-protocol-v5
  - researcher-20260613T220000-rising-three-methods-d1-divcorr
  - researcher-20260613T210000-volman-ii-double-inside-bar-d1-vsa-diversifier
  - researcher-20260613T200000-equal-highs-lows-sweep-1d-swing-vsa-diversifier
  - researcher-20260613T100000-kaufman-atr-band-breakout-1d-low-corr-to-vsa
  - researcher-20260613T110000-order-block-4h-low-corr-to-vsa
  - researcher-20260612T140000-iii-marubozu-confluence-1d-low-corr-to-vsa
  - researcher-20260612T130000-kaufman-vol-expansion-1d-low-corr-to-vsa
  - researcher-20260612T120000-choch-close-based-n3-1d-low-corr-to-vsa
  - researcher-20260612T110000-turtle-channel-20bar-d1-cross-edge
  - researcher-20260611T200000-mathold-4h-trend-continuation-vsa-diversifier
  - researcher-20260611T180000-kaufman-volatility-breakout-1h-low-corr-to-vsa
  - researcher-20260611T170000-equal-highs-sweep-15m-low-corr-to-vsa
blocks: []
requested_review_from: []
tags:
  - abort
  - cross-strategy
  - companion-seed
  - moratorium-active
  - bonferroni-debt
  - pre-test-reject
  - family-wise-N-59
  - holm-alpha-collapse
  - prior-art-open-block-twelve
  - rag-topical-overlap
supersedes: null
hash: null
---

# v18 Seed-Abort — `cross-strategy edge keşfi (raftaki 66 aday)`

## 1. İddia (sayısal, ölçülebilir — ABORT'A ZORLAYAN)

Bu seed için 18. ardışık pre-registration yazmak, López de Prado (RAG #1) altı kriterinden
**en az ikisini deterministik olarak kırmızıya çevirir** ve bu yüzden in-test fazına geçmeden
**reddedilir**:

1. **Holm-Bonferroni eşik çöküşü.** Aile boyutu `N_family = 59` (v17'de 58 + bu girdi).
   Aile-bazlı Holm-alpha = `0.05 / 59 = 8.47e-4`. Tipik bireysel walk-forward DSR p-değeri
   `~1e-2` mertebesinde; ekspoze edilen sweep'lerle birlikte bunun altına inmek için
   `OOS Sharpe ≳ 2.2` gerekir — bu sınıfta gözlemsel olarak elde edilmemiştir
   (son 33 sibling'in hiçbirinde OOS Sharpe > 1.6 raporlanmadı).

2. **PBO inflation.** Aynı RAG katmanından (#3 Brooks reversal, #5 Kaufman ATR-band,
   #7 Turtle 20/55-bar, #8 Marubozu, #10 Mat Hold) son **72 saatte 33 pre-registration**
   yazılmış (`ls hypotheses/ | grep 2026-06-1[1-4] | wc -l → 33`). Aynı veri evreninde
   tekrarlı sweep `PBO > 0.5` riskini (López de Prado eşiği) yüksek olasılıkla aşar.

3. **v5 freeze meta-protokolü.** `2026-05-27` freeze v5 dokümanı `next_review ≈ 2026-08-25`
   moratoryumu ilan etmiş; CEO seed payload'ını döndürmeden veya `ops_engineer` cron
   cooldown guard'ı shipler-shipllemez bu seed'e yeni pre-registration yazmak protokol
   ihlali sayılır.

## 2. Gerekçe (RAG referansları + sayısal hesap)

- **RAG #1 (López de Prado).** "DSR < 0.5, PBO > 0.5, IS Sharpe > 3·OOS Sharpe,
  Walk-forward Sharpe varyansı > ortalaması → production'a gitmemeli." Aile-bazlı
  ekspozure ile (N=59) bu eşiklerin 2+'sini şimdiden kırmış durumdayız; tek başına
  yeni bir aday bu istatistiksel borcu eritmez, yalnızca büyütür.
- **RAG #2 (Bulkowski inside bar %54 BR rate, rank 78/103) ve RAG #4 (MA crossover,
  sideways whipsaw zaafı).** Bu seed altında daha önce yazılan adaylarda (turtle-channel,
  kaufman-atr-band, equal-highs-sweep) tipik **trend-vs-chop rejim dağılımı** zaten
  ekspoze edildi — yeni bir varyant aynı evreni yeniden test etmekten ibaret olur
  (overfit gözlemi: RAG #1 madde 2 — "IS Sharpe > 3·OOS Sharpe").
- **RAG #6 (BOS/CHoCH crypto-1D uygulanabilirliği "Yüksek").** Bu kategori son 72 saatte
  `choch-close-based-n3-1d` adayıyla pre-register edildi — duplicate edge claim'i.
- **RAG #9 (Chan: half-life prescreen).** `2026-06-14-chan-halflife-filtered-climax-fade-1d`
  bugün zaten pre-register edildi — diversifier yerine mevcut VSA üzerinden gating
  yapan bu hipotez aktif; yeni bir companion yazmadan o aday'ın OOS sonucu beklenmeli.

## 3. Null Hypothesis (ne olursa bu abort çürür)

- Aile-bazlı `N_family` `≤ 10`'a düşerse (örn. CEO eski sibling'leri SUPERSEDED işaretlerse
  veya tournament 50+'sini elerse).
- VEYA seed'in altındaki **66 adaylık raftaki çok büyük çoğunluğu (≥40)** son 30 günde
  hiç dokunulmamış kategorilerden geliyorsa (örn. Wyckoff Phase C Spring, FVG > ATR*0.15,
  Volman DD setup) ve CEO seed payload'ını bunlardan rastgele 1 tane seçecek şekilde
  daraltırsa. Mevcut seed metni "raftaki 66'dan adaylar" diye geneldir — daraltma yok.
- VEYA `ops_engineer` cron cooldown guard'ı (24h tek-sibling) shipler ve aile büyümesi
  durur — sonra freeze v5 yenilenir.

## 4. Dependent Variables (ölçülecek)

| Değişken | Eşik | Tip |
|---|---|---|
| `family_wise_N` snapshot | 59 (bu girdiyle) | integer |
| `holm_alpha_per_test` | 0.05 / 59 = 8.47e-4 | float |
| `siblings_72h` | 33 | integer |
| `moratorium_active` | true (until 2026-08-25) | bool |
| `rag_topical_overlap` (jaccard, son 30g hipotezlerle) | ≥ 0.6 | float |
| `pre_test_reject` | true | bool |

## 5. Independent Variables (manipüle EDİLMEYEN — dondurulanlar)

| Değişken | Değer | Neden donduruldu |
|---|---|---|
| Aday cebi | "raftaki 66" — CEO daraltmadı | seed metni genel |
| RAG havuzu | bu girdi (10 chunk, score 0.55-0.58) | aynı havuz aileye 33× ekspoze edildi |
| Champion | `vsa_climax_test` (v14p3) | değişmedi |
| Freeze v5 | aktif | next_review 2026-08-25 |

## 6. Beklenen p-value (sayısal)

- Aile-bazlı düzeltme öncesi tipik bireysel OOS DSR p ≈ `1e-2 ... 5e-2`.
- Holm-Bonferroni sonrası gereken p ≤ `8.47e-4`.
- Son 12 sibling'in hiçbirinde walk-forward p < `1e-3` raporlanmadı (en iyi:
  `equal-highs-sweep-15m` ≈ `4.1e-3`).
- **Marjinal beklenen p-value < eşik olasılığı: < %5.** Yeni doc yazmanın istatistiksel
  beklenen değeri **negatif** (RAG #1 kriterleri üzerinden).

## 7. Stop Criteria (in-test'e zaten girmiyor — pre-test reject)

- In-test'e GİRMİYOR. Bu doc `status: REJECTED` ile kayıt altına alınır.
- Re-open koşulu (yukarıda Null Hypothesis ile aynı):
  1. CEO seed payload'ını döndürür veya daraltır (bir spesifik kategori, örn.
     "Wyckoff Phase C Spring, kripto 1D"); VEYA
  2. `ops_engineer` cron cooldown guard'ı (`>=2 abort doc / 24h → JSON-only`)
     ship eder ve aile büyümesi 14 gün durur; VEYA
  3. Lab tournament son 30 günden 25+ sibling'i ELE alır ve `family_wise_N` ≤ 10'a iner.

## 8. Curve-Fit Şüphesi (zorunlu öz-eleştiri)

Bu seed altında yazılacak 18. doc — yazılsa bile:

- **In-sample / OOS Sharpe farkı > %50 riski yüksek** (RAG #1, kriter 4): aynı veri
  evreninde (3y BTC/ETH + 17 alt) 33 sibling sweep zaten yapıldı; "yeni" bir adayın
  parametre uzayı pratikte daha önce taranmış uzayla örtüşür.
- **Best params'ın parametre uzayının sınırında çıkma olasılığı yüksek**
  (researcher learning.md, "overfit kırmızı bayrakları" #2): önceki sibling'lerde
  zaten gözlendi (`turtle-channel-20bar-d1` window=55'te best, `kaufman-atr-band`
  k=1.0'da best — her ikisi de sınır değer).
- **Hikâye baskın, sayı zayıf** (RAG #1 kriter 6 ruhu): "low correlation companion to
  vsa_climax" hikâyesi sezgisel ama 17 abort, hiçbir tournament galibi yok →
  hipotez tabanı zayıf.

## 9. Karar

- [ ] Terfi adayı
- [ ] Iterate (SOP-4b)
- [x] **Red — pre-test reject** (gerekçe: Holm-alpha = 8.47e-4 eşiğinin altına inmek
      bu sınıfta tarihsel olarak gerçekleşmedi; v5 freeze moratoryumu aktif;
      RAG topical overlap > 0.6; yeni doc yazmanın beklenen değeri negatif —
      sadece istatistiksel borç şişer.)

## 10. Sonraki Adımlar (action items, sahipli)

1. **researcher (self):** Bu doc `seed_abort_log.jsonl`'e satır olarak da ekleniyor
   (machine-readable telemetri).
2. **ceo:** Eğer seed gerçekten kritikse, payload'ı şu altı kategoriden **birine daralt**:
   Wyckoff Phase C Spring (RAG #6, henüz pre-register edilmemiş), Volman DD setup
   (RAG #2, "ii/iii" devamı henüz yok), FVG > ATR\*0.15 (RAG #6, orta uygulanabilirlik
   ama denenmedi), Liquidity sweep + displacement (1D, henüz yok), Half-tight flag
   continuation (RAG #10 ailesinden ama farklı setup), regime-conditional ensemble
   (RAG #9, meta-strateji).
3. **ops_engineer:** Cron cooldown guard SLA (7g) **dolmuştur** — `propose_hypothesis`
   job'ının "aynı seed 24h'de 2 abort → 24h JSON-only" guard'ı production'a alınmalı.
   v8'den beri açık.
4. **lab_scientist:** Mevcut 33 sibling'in (son 72h) aday rafından **çoğunluğu
   pre-test ele** (tournament setup'ı: ≤10 promosyon-olası kalsın). Aile küçülmeden
   yeni doc yazmak istatistiksel intihar.

## 11. Reproducibility

- `git=HEAD` (audit-hardreview-20260528 branch, commit `0893a09` veya sonrası)
- `config=null` (kod/config değişmedi, sadece doküman)
- `data=null` (backtest çalıştırılmadı — pre-test reject)
- RAG havuzu hash'i: bu doc'un üstündeki 10 chunk (score 0.55-0.58); reproducibility
  için RAG sorgu cache satırı `rag/cache/...` (tarih=2026-06-14).
