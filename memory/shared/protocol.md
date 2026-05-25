---
doc_id: protocol-2026-05-25-v1
doc_type: protocol
agent_id: human_principal
created_at: 2026-05-25T00:00:00Z
status: ACTIVE
confidence: high
depends_on: []
blocks: []
requested_review_from: []
tags: [protocol, governance, communication]
supersedes: null
---

# Inter-Agent Communication Protocol

> Tüm 10 agent (ceo, researcher, lab_scientist, analyst, risk_officer, portfolio_manager, signal_chief, execution_chief, ops_engineer, data_engineer) bu kontratı **okur** ve uygular. Sistem bu protokole bağımlıdır; uymayan agent çıktısı `ops_engineer` tarafından flag'lenir.

## 1. Frontmatter — zorunlu spec

Her agent çıktısının **ilk satırı** `---` ile başlamalı, geçerli YAML frontmatter içermeli ve aşağıdaki alanlardan **ZORUNLU** olanları doldurmalı:

```yaml
---
# CORE (her doc'ta zorunlu)
doc_id: <agent>-<yyyymmddTHHMMSS>-<slug>  # globally unique, ASCII, kebab-case
doc_type: brief | hypothesis | tournament | drift_alert | whatif | adr | postmortem | incident | directive | critique | endorse | protocol | learning | decision
agent_id: ceo | researcher | lab_scientist | analyst | risk_officer | portfolio_manager | signal_chief | execution_chief | ops_engineer | data_engineer | human_principal
created_at: 2026-05-25T14:30:00Z   # ISO 8601 UTC, mandatory
status: DRAFT                       # see §2 state machine
confidence: low | med | high       # subjective, on the work product

# REVIEW / DEPENDENCY (varsa zorunlu, yoksa boş liste)
depends_on: []                     # doc_id listesi — bu dokümanın okuduğu/dayandığı girdiler
blocks: []                          # doc_id listesi — bu doc tamamlanmadan ilerlemeyecek dokümanlar
requested_review_from: []           # agent_id listesi — review/critique istenenler

# OPSİYONEL
tags: []                            # filtreleme/aramada faydalı
supersedes: null | <prior_doc_id>   # bu doc bir öncekini geçersiz mi kılıyor
hash: null | <git_sha>              # reproducibility (kod/data değişikliği varsa)
---
```

## 2. State machine — doc lifecycle

```
                  +-------------------+
                  |      DRAFT        |   ilk yazıldı, henüz paylaşılmadı
                  +---------+---------+
                            | (author publish'ler)
                            v
                  +-------------------+
                  |    PROPOSED       |   review için kuyruğa girdi
                  +---------+---------+
                            | (reviewer'ler critique/endorse yazar)
                            v
                  +-------------------+
                  |    REVIEWED       |   tüm requested_review_from yanıtladı
                  +---+-----------+---+
                      |           |
        (approve)     |           |   (reject)
                      v           v
              +-----------+   +-----------+
              | APPROVED  |   | REJECTED  |
              +-----+-----+   +-----------+
                    |
                    v
              +-----------+
              |  ACTIVE   |   uygulamada (canlı bot, deploy edilen config, vb.)
              +-----+-----+
                    |
                    v
              +-----------+   +-----------+
              | COMPLETED |   |SUPERSEDED |   yeni doc bunu geçersiz kıldı
              +-----------+   +-----------+
```

**Geçiş kuralları:**
- **Sadece doc'un orijinal `agent_id`'si status değiştirebilir.** Reviewer agent statüye dokunmaz; ayrı `critique` veya `endorse` doc yazar.
- `APPROVED → ACTIVE` geçişi yalnızca `human_principal` veya yetkili `ceo` tarafından yapılır (configs/orchestration tarafında deploy adımıyla eşleştirilir).
- `REJECTED` geri açılamaz; revize edilecekse yeni doc oluşturulur, eskisi `supersedes` ile bağlanır.
- `SUPERSEDED` doc'lar silinmez (append-only), sadece `status` değişir.

## 3. "How to disagree" — critique protokolü

Bir agent başka agent'ın çıktısına katılmıyorsa **kendi pozisyonunu zorlama** — `doc_type: critique` ile yeni doc yazar:

```yaml
---
doc_id: <critique-agent>-<ts>-critique-of-<original-slug>
doc_type: critique
agent_id: <eleştiren agent_id>
created_at: <ts>
status: PROPOSED
depends_on: [<orijinal doc_id>]
requested_review_from: [ceo]   # arbitrate için
confidence: high
tags: [critique, ...]
---
```

**Body zorunlu 5 alan:**

```markdown
## Claim
> Orijinal dokümanın iddiası ne (tek cümle)

## Disagreement
> Hangi noktada katılmıyorum (tek cümle)

## Evidence
> Hangi veri/argüman bu eleştiriyi destekliyor (madde madde, kaynaklar)

## Alternative
> Bunun yerine ne öneriyorum (somut)

## What would change my mind
> Hangi yeni bilgi/veri görsem bu eleştiriyi geri çekerim
```

**Endorse protokolü:** Katılıyorsa `doc_type: endorse` ile aynı format, ama "Disagreement" yerine "Why I endorse", "Alternative" yerine "Strengths I want to highlight" olur.

## 4. ACK kuralı — review tamamlama

- Bir doc'un `status: PROPOSED → REVIEWED` geçmesi için `requested_review_from` listesindeki **her agent** ya `critique` ya `endorse` yazmış olmalı.
- Reviewer agent inbox'ında bu request varsa SLA: **24 saat** (Risk Officer için 6 saat). Aşarsa `ops_engineer` flag + Principal'a Telegram WARN.
- Reviewer "yetkim yok / domain dışı" derse `doc_type: endorse` + body'de "out of scope, deferring to <other_agent>" — bu sayı `requested_review_from`'dan düşmez ama traceable kalır.

## 5. Çatışma çözümü — CEO arbitrate

Aynı `depends_on` (= aynı orijinal doc) için birbiriyle **zıt** critique'ler oluşursa:
- `ceo` otomatik `arbitrate(<original_doc_id>)` çağrısı yapar (daily_brief başında `_check_conflicts()`)
- CEO çıktısı `doc_type: adr` veya `directive`, status `APPROVED`
- Tüm conflicting critique'ler `supersedes` ile bu ADR'ye bağlanır

**Timeout:** CEO 24 saat içinde karar veremezse Principal'a CRIT push (`configs/conflict_policy.yaml` per-conflict-type).

## 6. Inbox / message bus

**Kalıcı backup:** `memory/protocol/inbox.jsonl` (gitignore, append-only)

Her doc oluşturulduğunda 1 satır:
```json
{"doc_id":"researcher-20260525T120000-vsa-only-d2","sender":"researcher","recipient":"lab_scientist","topic":"new_hypothesis","ref_path":"memory/researcher/hypotheses/2026-05-25-vsa-only-d2.md","created_at":"2026-05-25T12:00:00Z","ack_at":null}
```

`requested_review_from` listesindeki her agent için ayrı satır yazılır (recipient farklı).

Reviewer kendi job'unda `inbox.jsonl`'i filtreler (`recipient == self.name AND ack_at IS NULL`), işler, `ack_at` doldurur.

## 7. Kim ne yazabilir — yetki matrisi

| Doc type | Kim yazar | Kim review eder |
|---|---|---|
| `brief` | ceo | (none — sadece tüketici principal) |
| `hypothesis` | researcher | lab_scientist, risk_officer |
| `tournament` | lab_scientist | researcher (challenged setup), risk_officer (gates) |
| `drift_alert` | lab_scientist | researcher |
| `whatif` | analyst | risk_officer, researcher |
| `critique` | herhangi | (ceo arbitrate) |
| `endorse` | herhangi | (sadece tüketici) |
| `directive` | ceo | (none — Principal onayı) |
| `adr` | herhangi | (Principal nihai) |
| `postmortem` | analyst, ops_engineer | (herkes okur) |
| `incident` | ops_engineer | (acil → CRIT push) |

## 8. Hard limits — protokol dahili kurallar

- ❌ Hiçbir agent başka agent'ın doc'unu **edit edemez** (append-only). Düzeltme = yeni doc + `supersedes`.
- ❌ Hiçbir LLM-agent doğrudan **trading config** yazmaz; `configs/risk*.yaml` ve `configs/orchestrator/*.yaml` sadece **human_principal** veya deployment script tarafından yazılabilir. (ADR-002 koruma)
- ❌ `status: APPROVED` doc'lar yeniden review'a açılmaz. Yeni durum = yeni doc.
- ❌ Eğer `requested_review_from` listesi boşsa doc otomatik `REVIEWED` sayılır (review beklenmiyor — örn. brief, learning).
- ❌ doc_id duplicate edilirse `ops_engineer` CRIT alarm; protokol bozulmuş demektir.

## 9. Versioning

Bu protokol revize edilirse:
1. Yeni `protocol.md` yaz (status: PROPOSED)
2. `supersedes: protocol-2026-05-25-v1`
3. Tüm agent'lar yeni job çağrısında yeni protokolü okuyacak (`base.py._load_system_prompt` cache'siz)
4. Eski protokol `status: SUPERSEDED` (manuel, principal tarafından)

---

**Bu protokol agent'lar tarafından her oturum başında okunur (`LLMAgentBase._load_system_prompt`'a ek).** Uymayan agent çıktısı `ops_engineer` `protocol_violation` etiketi ile incident doc yazar.
