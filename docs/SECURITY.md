# Security Policy — Faz 14.27 ORTA C7 fix

## Bandit (Python Code Security)

CI/Workflow `.github/workflows/ci.yml` `security` jobu iki ayrı **Bandit**
taraması çalıştırır:

- Blocking HIGH kapısı: `src/` ile canlı daemon, retry/protection, E13 ve
  dashboard runtime giriş noktaları.
- Informational geniş tarama: `src/` + tüm `scripts/`; gerçek exit code ve JSON
  artifact görünür, fakat araştırma script'lerindeki mevcut bulgular kapanana
  kadar merge kapısı değildir.

11 Temmuz 2026 yerel kanıtında `src` + `scripts` Bandit HIGH taraması
`rc=0` döndü. Bu yalnız statik HIGH bulgu kapısının temiz olduğunu kanıtlar;
dependency advisory'lerini veya runtime exposure review'i ikame etmez.

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
# Blocking runtime yüzeyini yerelde yeniden üret
bandit -r \
  src \
  scripts/futures_daemon.py \
  scripts/futures_daemon_v14.py \
  scripts/futures_trade_15m.py \
  scripts/futures_trade_daily.py \
  scripts/process_pending_entries.py \
  scripts/e13_shadow_tick.py \
  scripts/e13_exit_evidence.py \
  scripts/dashboard \
  --severity-level high

# Repo-geneli bulguları görünür üret (şu an informational)
bandit -r src scripts --severity-level medium
```

> `-ll` ile `--severity-level medium` aynı çağrıda kullanılmaz. Güncel Bandit
> bunu argüman hatası sayar. CI JSON raporundaki taranan LOC değerini de kontrol
> eder; scanner çalışmadan boş raporla yeşil sonuç üretilemez.

`pyproject.toml` bandit config (optional):
```toml
[tool.bandit]
exclude_dirs = ["tests", "scripts/proposed"]
skips = ["B101"]  # assert (test code)
```

## pip-audit (Dependency CVE)

CI `pip-audit` bulgularını non-blocking fakat gerçek exit code ile görünür
tutar. Audit öncesindeki `pip install -e '.[dev]'` ayrı ve **blocking** bir setup
adımıdır; `set -o pipefail` nedeniyle install/tee hatası yutulamaz. Install logu
artifact olur. Manual review weekly.

### Response Policy

| CVE Severity | Action | Patch Window |
|---|---|---|
| **CRITICAL (9.0+)** | Upgrade immediately | 24h |
| **HIGH (7.0-8.9)** | Upgrade within 1 week | 7 days |
| **MEDIUM (4.0-6.9)** | Plan upgrade with next sprint | 30 days |
| **LOW (<4.0)** | Track, no immediate action | N/A |

## Secret Scanning

Pre-commit `gitleaks` yerelde çalışır. **PENDING:** CI'da bağımsız gitleaks job'ı
henüz yoktur; Bandit genel secret-history tarayıcısının yerine geçmez. Bu açık
kapanana kadar GitHub'a gönderilen her değişiklik local pre-commit'ten geçmelidir.

## Runtime capability isolation — 2026-07-11

- Binance private REST'in tek sürekli sahibi canlı v15p2 trade daemonudur.
  CEO wrapper/plist'i `PA_DISABLE_PRIVATE_EXCHANGE_API=1` taşır;
  `get_futures_exchange()` bu süreç kapısını credential okumadan, CCXT client
  oluşturmadan ve ağ çağrısından önce fail-closed uygular. CEO aktif 418 olayı
  ve güvenli trade-daemon restartı tamamlanana kadar ayrıca unloaded tutulur.
- Dashboard PnL/pozisyon/rate-limit görünürlüğünü yalnız yerel journal, fill DB
  ve bounded daemon-log kanıtından üretir. Private API fallback'i yoktur.
- E13 shadow tick yalnız tamamlanmış yerel 15m snapshotını okur; ölçülen doğal
  koşumlarda `exchange_calls=0` ve `network_calls=0` kalmıştır.
- Diskteki yeni 15m DMS wiring'i heartbeat'i ana bar döngüsünden alır. Arka
  planda 20 saniyede bir account/positions polling yapmaz; ortak 418 cooldown
  süresi dolmadan acil-flatten'in sınırlı retry bütçesini tüketmez.
- TF signal-shadow worker'ı pinned kaynak snapshotından çalışır. Seatbelt
  profili varsayılan file-read deny, network/process/write deny uygular; repo,
  secret ve `/etc/hosts` erişimi kapalıdır.

Trade daemonunun çalışan PID'i açık pozisyonlar nedeniyle eski process image'ını
taşımaktadır. Bu maddelerin DMS/rate-limit kısmı güvenli doğal restart ve 48
saatlik saha kanıtı tamamlanana kadar **code-ready / deploy-pending** kabul edilir.

## Current Dependency Exceptions — 2026-07-11

- Yerel lock kanıtı:
  `uvx --python .venv/bin/python pip-audit -r requirements-lock.txt --desc`
  kurulumdan sonra gerçek `rc=1` döndü; **3 advisory, üçünde de fix
  version boş**. Bu nedenle CI audit bulgusu informational kalır ama raporu
  ve exit code'u gizlenmez.
- `chromadb==1.5.9`: `PYSEC-2026-311`, upstream fix yok. Bulgudaki pre-auth
  code-injection exposure'ı Chroma API server endpoint'inin dışa açılmasına
  bağlıdır. Repo yalnız embedded `PersistentClient` kullanacak ve server'ı
  yayınlamayacaktır; bu deployment varsayımı ayrıca operasyonel olarak
  doğrulanmalıdır. Fix çıktığında lock yükseltilecek.
- `torch==2.10.0`: `PYSEC-2026-139` yerel PT2 loading/deserialization ve
  `CVE-2025-3000` yerel `torch.jit` memory-corruption riskleri; ikisinde de fix
  version yok. Repo doğrudan `torch.load` veya `torch.jit.script` çağırmaz ve
  güvenilmeyen yerel model/PT2/JIT artifact'i kabul etmemelidir. RAG/embedding
  yolunun bu yüzeyi transitif olarak açmadığı exposure review ile kanıtlanana
  kadar risk **açık/accepted-pending-verification** olarak izlenir.
- `soupsieve==2.8.4`: fixlenebilir DoS advisory'leri için dependency floor,
  lock ve yerel venv 11 Temmuz'da yükseltildi.

Bu istisnalar "temiz audit" anlamına gelmez. `pip-audit` CI'da hâlen
non-blockingdir; fixlenebilir paket ve lock güncellemesi ayrı kapanış kanıtı ister.

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
