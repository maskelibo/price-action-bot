# memory/shared/templates/

Standart frontmatter şablonları. Tüm agent çıktıları bu şablonların ilgili olanına dayanmalı.

## Şablonlar

| Şablon | Kim kullanır | doc_type |
|---|---|---|
| `brief.md.tmpl` | CEO (daily/weekly) | brief |
| `hypothesis.md.tmpl` | Researcher (pre-registration) | hypothesis |
| `tournament.md.tmpl` | Lab Scientist (haftalık) | tournament |
| `drift_alert.md.tmpl` | Lab Scientist (event) | drift_alert |
| `critique.md.tmpl` | herhangi (itiraz) | critique |
| `postmortem.md.tmpl` | Analyst (trade), Ops Engineer (incident) | postmortem |
| `whatif.md.tmpl` | Analyst (Faz 2 sonrası) | whatif |
| `directive.md.tmpl` | CEO (öneri, Principal onayı) | directive |

## Kullanım

Agent kodu (Faz 1.5'te `LLMAgentBase.write_protocol_doc()` helper'ı) şablonu okur, frontmatter alanlarını doldurur, doc_id üretir, diske yazar, inbox.jsonl'e satır ekler.

Tüm `{{placeholder}}` ifadeleri runtime'da doldurulur. Boş bırakılan zorunlu alan → `protocol_violation` flag (Ops alarm).

## Frontmatter spec

Full spec: `memory/shared/protocol.md` §1.
