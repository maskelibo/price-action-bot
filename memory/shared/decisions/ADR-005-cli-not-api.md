---
adr_id: ADR-005
title: LLM Auth — Claude Code CLI Subprocess (API Key Yerine)
status: accepted
date: 2026-05-08
author: ceo
tags: [llm, auth, infra, cost]
---

# ADR-005 — LLM Auth: Claude Code CLI Subprocess (API Key Yerine)

## Bağlam

Sistem 5 LLM agent'ını (CEO / Researcher / Analyst / Lab Scientist / Ops Engineer) Claude modelleri üzerinden çalıştırır. Faz 0 mimari `agents/base.py`'de iki client adapter ile geldi:

1. **`anthropic` SDK** — `ANTHROPIC_API_KEY` ile pay-per-token API erişimi
2. **`claude_agent_sdk`** — opsiyonel paket (henüz yaygın değil)

Kullanıcı (insan principal) Claude Max abonelik paketine sahip; bu paket Claude Code CLI üzerinden token-bazlı sınırsız kullanım sağlar (rate-limit'e tabi). API key satın almak ekstra maliyet ve aboneliği değersizleştirme demek.

## Karar

**`agents/base.py`'a üçüncü bir client adapter eklendi: `_call_cli`** — `claude` CLI'ı subprocess olarak çağırır, ANTHROPIC_API_KEY gerektirmez. CLI subscription/OAuth ile auth olur.

### Öncelik sırası (`_ensure_client`)
1. `PA_LLM_DRY_RUN=true` → mock cevap (CI / unit test)
2. `PA_LLM_USE_CLI=true` **veya** API key yoksa → CLI
3. `claude_agent_sdk` import edilebilirse → SDK
4. `anthropic` SDK fallback (API key gerekir)

### Çağrı şekli
```python
subprocess.run([
    cli_path, "-p", "--output-format=json",
    "--model", self.model,
    "--append-system-prompt", system_prompt,
], input=user_text, capture_output=True, timeout=180)
```
JSON cevap: `result`, `usage` (input/output/cache tokens), `stop_reason`, `session_id`.

### Windows'a özel: `.exe` doğrudan çağrı
`claude.cmd` wrapper CMD.EXE üzerinden gider; CMD.EXE argv 8191 char ile sınırlıdır. Sistem promptu (rules + memory boot) ~30KB → CMD'i patlatır.

`_find_claude_cli()` Windows'ta önce `%APPDATA%\npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe`'yi arar — CreateProcess ile direkt çağırır (~32K limit), CMD'i bypass eder.

## Sonuç

- ✅ Sıfır API key maliyeti (Max paketinde token sınırsız, sadece rate limit)
- ✅ Auth deneyimi tek noktadan (CLI session) — token rotation, OAuth tüm avantajları
- ✅ Prompt cache aktif (CLI bunu otomatik yönetir) — tekrar çağrılarda %85 token tasarrufu
- ✅ 5 agent canlı doğrulandı: CEO/Researcher/Analyst/Lab/Ops Haiku ve Sonnet ile çalıştı
- ⚠️ **Bağımlılık:** `claude` CLI binary makinede kurulu olmalı (`@anthropic-ai/claude-code` npm paketi)
- ⚠️ **Subprocess overhead:** Her çağrı ~2-3s ekstra latency (subprocess fork + JSON parse). Yüksek-frekans LLM çağrısı olan workload'lar için anthropic SDK daha uygun olabilir — ileri faz'da revisit.
- ⚠️ **Auth göçü:** Eğer kullanıcı Max paketinden çıkar veya farklı bir hesabın CLI'ı aktif olursa, agentlar farklı identity ile çağrı yapabilir. Bu Faz 7+ canlı kullanımda manuel monitor edilmeli.

## Alternatifler (red edilen)

1. **Sadece API key (anthropic SDK)** → Reject: maliyet (kullanıcı Max'i ödeyip ekstra API ödemek istemiyor)
2. **Claude Agent SDK only** → Reject: paket henüz olgunlaşmadı, Windows desteği belirsiz
3. **OAuth proxy server** → Reject: aşırı mühendislik, Faz 0'da basit subprocess yeter

## Referans

- `src/price_action/agents/base.py` — `_call_cli`, `_find_claude_cli`, `_ensure_client`
- `tests/test_agents_cli.py` — 16 test
- `scripts/cli_smoke.py`, `scripts/live_agents_test.py` — canlı doğrulama
- CHANGELOG.md v0.2.0
