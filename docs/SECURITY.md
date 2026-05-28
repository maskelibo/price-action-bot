# Security Policy — Faz 14.27 ORTA C7 fix

## Bandit (Python Code Security)

CI/Workflow `.github/workflows/ci.yml` `security` jobu **bandit** çalıştırır.

### Severity Levels & Response

| Severity | Action | CI Block | Response Time |
|---|---|---|---|
| **HIGH** | Fix BEFORE merge | ✅ BLOCKS | Immediate |
| **MEDIUM** | Review, fix or document | ⚠️ Warning | 1 week |
| **LOW** | Document if intentional | ❌ No block | Optional |

### HIGH Severity Examples (Block)

- `subprocess` with `shell=True` and user input
- `pickle.loads()` from external source
- Hardcoded credentials/API keys/passwords
- SQL injection patterns
- Insecure deserialization (`yaml.load` without Loader)
- Weak crypto: MD5, SHA1, DES, RC4 for security

### MEDIUM Severity Examples (Document)

- `assert` in production code (Python optimization removes these)
- `try/except: pass` (bandit B110) — but our codebase intentionally uses this
  for defensive failure tolerance (notifications, log writes)

### Bandit Configuration

```bash
# Local manual run
bandit -r src -ll --severity-level medium
```

`pyproject.toml` bandit config (optional):
```toml
[tool.bandit]
exclude_dirs = ["tests", "scripts/proposed"]
skips = ["B101"]  # assert (test code)
```

## pip-audit (Dependency CVE)

CI runs `pip-audit` non-blocking. Manual review weekly.

### Response Policy

| CVE Severity | Action | Patch Window |
|---|---|---|
| **CRITICAL (9.0+)** | Upgrade immediately | 24h |
| **HIGH (7.0-8.9)** | Upgrade within 1 week | 7 days |
| **MEDIUM (4.0-6.9)** | Plan upgrade with next sprint | 30 days |
| **LOW (<4.0)** | Track, no immediate action | N/A |

## Secret Scanning

Pre-commit `gitleaks` runs locally. CI duplicates via bandit (hardcoded patterns).

### If Secret Leaked

1. **Immediately revoke** at provider (Binance, Anthropic, Telegram)
2. **git filter-repo** rewrite history (or `git filter-branch`)
3. **Push --force** with team notification
4. **Update** `.gitignore` if pattern wasn't blocked

### Current Secrets Inventory

| Secret | Location | Rotation |
|---|---|---|
| BINANCE_FUTURES_TESTNET_API_KEY | `.env` (gitignored, 600 perms) | After incident |
| ANTHROPIC_API_KEY | `.env` — EMPTY (CLI subscription auth) | N/A |
| TELEGRAM_BOT_TOKEN | `.env` (gitignored) | Annually |

## Incident Response

Security incident:
1. Notify Principal via Telegram CRIT push
2. Stop affected daemon (`launchctl bootout`)
3. Rotate credentials
4. Write postmortem in `memory/shared/incidents/`
5. Add regression test if applicable
