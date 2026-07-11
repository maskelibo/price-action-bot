# ops/launchd/

> **⚠️ 2026-05 TARİHSEL BÖLÜMLERİ VAR — güncel durum 2026-07-11:**
> Canlı trading servisi **`com.priceaction.futures_v15p2`** (`run_futures_v15p2.sh` → `futures_daemon_v14.py` wrapper). Yardımcı servislerin gerçek loaded/running durumu her zaman `launchctl print gui/$(id -u)/<label>` ile ayrı ayrı kanıtlanır.
> **EMEKLİ plist'ler: `futures15m` (+`_v11`/`_v63`), `futures5m`, v14 dönemi script'leri — ASLA `cp`+`load` ETMEYİN.** KeepAlive'lı emekli plist reboot'ta dirilir → split-brain çift-daemon (2× yaşandı; bkz memory "champion-15m-launchd-keepalive" dersi). Aşağıdaki §3 tarihsel arşivdir, uygulamayın.

> **DR DURUMU (2026-07-11): DEGRADED.** `com.priceaction.healthping` kurulu
> olsa da `HEALTHCHECKS_PING_URL` yoksa INERT/WARN'dır; Mac-dışı alarm yoktur.
> Repo-kontrollü şifreli off-site backup/restore kanıtı da henüz yoktur. Bu iki
> kalem `docs/OPERATIONS_PENDING_2026-07-11.md` kapanmadan "DR hazır" denmez.

macOS launchd plist'leri — Mac mini'nin boot anında otomatik başlattığı servisler.

## Dosyalar

| Plist | Servis | Yükleme durumu | Komutu |
|---|---|---|---|
| `com.priceaction.futures_v15p2.plist` | `run_futures_v15p2.sh` (CANLI trading bot, v15p2) | **YÜKLÜ (canlı)** | — |
| `com.priceaction.healthping.plist` | health ping | **YÜKLÜ, INERT (URL yok)** | dış credential bekliyor |
| `com.priceaction.e13_shadow_tick.plist` | yerel E13 ATR-trail eşlenik kanıt toplayıcı | **YÜKLÜ; scheduler sağlıklı** | 300 sn interval, son launchd exit `0`; emir/ağ çağrısı yok |
| `com.priceaction.ceo.plist` | `pa-ceo --mode daily --telegram` (orchestrator) | **INTENTIONALLY UNLOADED** — 418 incident + eski trade PID | guarded deploy sırası §2 |
| `com.priceaction.futures15m.plist` (+`_v11`/`_v63`) | eski 15m daemon | **EMEKLİ (15 Haz 2026, 3-adım bootout)** — yükleme! | §3 TARİHSEL |
| `com.priceaction.futures5m.plist` | eski 5m daemon | **EMEKLİ (30 Haz 2026, 0 fill)** — yükleme! | — |

> **E13 saha kanıtı (11 Temmuz 2026):** kontrollü policy migration sonrası
> `com.priceaction.e13_shadow_tick` launchd'ye yüklendi; `StartInterval=300`,
> ilk saha kanıtında `runs=12`, `last exit code=0`; manuel ingest→consumer
> snapshotı `newest_bar=2026-07-11T01:45:00Z`, `bytes=1637363712` ve sonraki
> `2026-07-11T02:06:53.878478Z` tick'i `status=OK` verdi. Kalıcı akış
> hardening'i sonrasında kick/restart yapılmadan gelen doğal ingest run `766`,
> `2026-07-11T02:17:41Z` anında doğrulanmış atomik snapshot yayınladı:
> `newest_bar=2026-07-11T02:00:00Z`, `bytes=1637363712`, `rows=10611632`;
> source/consumer `COUNT(*)` ve `MAX(ts)` birebir eşleşti, WAL/geçici kopya
> kalmadı. Bunun ardından E13 doğal run `15`,
> `2026-07-11T02:21:55.200552Z` tick'inde `status=OK`, `fail_closed=false`,
> `bars_applied=1`, `open_shadow_trades=1`, `issues=[]`, policy
> `fb2d4db2…a96d77d`, `exchange_calls=0`, `network_calls=0` verdi.
> Daha eski tick'lerde yerel market snapshotı son kapanmış bara yetişmediğinde
> görülen `HOLD_LOCAL_EVIDENCE_GAPS` satırları fail-closed davranış kanıtıdır;
> scheduler çökmesi değildir. Son gerçek payload her zaman
> `tail -1 logs/launchd/e13_shadow_tick.stdout.log` ile kontrol edilir. Restore
> scripti E13'ü yalnız restore öncesinde loaded yakaladıysa geri başlatır;
> sırf plist repoda var diye koşulsuz başlatmaz.

## §1 launchd nedir?

macOS'un init sistemi. Linux'taki `systemd` benzeri. Boot anında plist'leri okur, `RunAtLoad=true` olanları başlatır, `KeepAlive` ile crash sonrası restart eder.

Logs: `~/Library/Logs/com.priceaction.*` ve `logs/launchd/*.log`

## §2 CEO orchestrator — yükleme

**Bu plist `pa-ceo --mode daily --telegram` çalıştırır.** Mac mini boot olunca
otomatik başlar; crash olursa en az 60sn throttle ile restart eder.

> **11 Temmuz 418 kapısı:** plist ve wrapper
> `PA_DISABLE_PRIVATE_EXCHANGE_API=1` taşır; CEO içindeki account/position/income
> yolları credential/client/network öncesi fail-closed olur. Buna rağmen job,
> açık pozisyon taşıyan eski v15p2 PID'i güvenli restart edilip ilk temiz
> `POS_CHECK + RATE_BUDGET` barı görülene kadar **load edilmez**. Araştırma/rapor
> faydası bu incident sınırını genişletmez.

### İlk kurulum (bir kez)

```bash
cd ~/price-action-bot

# 1) Log dizinini hazırla
mkdir -p logs/launchd

# 2) Plist'i LaunchAgents'a kopyala (symlink değil — launchd symlink'i sevmez)
cp ops/launchd/com.priceaction.ceo.plist ~/Library/LaunchAgents/

# 3) Yükle ve başlat
launchctl load ~/Library/LaunchAgents/com.priceaction.ceo.plist

# 4) Doğrula (5sn sonra)
launchctl list | grep priceaction
# Beklenen: PID  Status  Label
#           XXXX  0       com.priceaction.ceo
```

### Çalıştığını doğrula

```bash
# Process aktif mi?
ps aux | grep "ceo_loop" | grep -v grep

# Log dosyaları yazılıyor mu?
tail -f logs/launchd/ceo.stdout.log
tail -f logs/launchd/ceo.stderr.log

# Scheduler job'ları kaydoldu mu? (ilk birkaç dk içinde)
grep "scheduler.jobs_registered" logs/launchd/ceo.stdout.log
```

### Durdurmak / kaldırmak

```bash
# Geçici durdur (plist kalır, sonra load ile geri başlar)
launchctl unload ~/Library/LaunchAgents/com.priceaction.ceo.plist

# Tamamen kaldır
launchctl unload ~/Library/LaunchAgents/com.priceaction.ceo.plist
rm ~/Library/LaunchAgents/com.priceaction.ceo.plist

# Log dosyalarını da temizle (opsiyonel)
rm logs/launchd/ceo.{stdout,stderr}.log
```

### Yeniden başlat (kod güncellendikten sonra)

```bash
launchctl unload ~/Library/LaunchAgents/com.priceaction.ceo.plist
launchctl load ~/Library/LaunchAgents/com.priceaction.ceo.plist
```

### Hata ayıklama

`launchctl load` başarılı oldu ama process çalışmıyorsa:

```bash
# 1) syslog'a bak
log show --predicate 'subsystem == "com.priceaction.ceo"' --last 1h
log show --predicate 'process == "python"' --last 5m | grep -i error

# 2) stderr dosyasını oku
cat logs/launchd/ceo.stderr.log

# 3) Plist syntax doğrula
plutil -lint ops/launchd/com.priceaction.ceo.plist
# beklenen: "OK"

# 4) Manuel çalıştır (kullanıcı uid altında)
cd ~/price-action-bot
PYTHONPATH=src PA_LLM_USE_CLI=true PA_CEO_PUSH_TELEGRAM=true \
  PA_DISABLE_PRIVATE_EXCHANGE_API=1 \
  .venv/bin/python -m price_action.orchestrator.ceo_loop --mode once --telegram
```

## §3 futures15m daemon — EMEKLİ (TARİHSEL ARŞİV — UYGULAMAYIN)

> **⚠️ EMEKLİ (2026-07-10 şerhi):** futures15m botu 15 Haz 2026'da 3-adım (bootout+disable+plist taşı) ile KALICI emekli edildi; PID 17267 çoktan yok. Aşağıdaki geçiş prosedürünü çalıştırmak emekli KeepAlive plist'ini diriltir → canlı v15p2 ile split-brain. Bu bölüm yalnız tarihsel kayıttır.

**Bu plist HAZIR ama YÜKLENMEDİ.** (tarihsel not — artık EMEKLİ)

Mevcut durum (2026-05 itibarıyla — BAYAT):
- PID 17267 manuel `python -u scripts/futures_daemon.py --timeframe 15m` ile çalışıyor
- 2+ gün uptime, paper testnet'te aktif
- **Eğer plist'i yüklersen iki daemon aynı anda emir gönderir** → felaket

### Geçiş prosedürü (Principal kararı ile)

```bash
# 1) Mevcut PID 17267'yi yumuşakça durdur
kill 17267
# Veya SIGTERM ile graceful
kill -TERM 17267

# 2) State'in temiz kapandığını doğrula
tail -20 logs/futures_daemon.log
# Beklenen: son satır "shutdown_complete" veya benzer

# 3) Log dizinini hazırla
mkdir -p logs/launchd

# 4) Plist'i yükle
cp ops/launchd/com.priceaction.futures15m.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.priceaction.futures15m.plist

# 5) İlk 15dk gözlemle — bar kapanışını yakaladı mı?
tail -f logs/launchd/futures15m.stdout.log
tail -f logs/futures_daemon.log
```

### Geri al (rollback)

```bash
launchctl unload ~/Library/LaunchAgents/com.priceaction.futures15m.plist
rm ~/Library/LaunchAgents/com.priceaction.futures15m.plist

# Manuel yeniden başlat (eski yöntem)
cd ~/price-action-bot
nohup .venv/bin/python -u scripts/futures_daemon.py --timeframe 15m \
  > logs/futures_daemon.log 2>&1 &
echo $! > logs/futures_daemon.pid
```

## §4 Yaygın sorunlar

### "Couldn't find ProgramArguments"
Plist syntax bozuk. `plutil -lint ops/launchd/com.priceaction.ceo.plist` ile valide et.

### Process başlıyor ama hemen ölüyor (KeepAlive throttle aktif)
- `ThrottleInterval` 30sn — yani 30sn'de bir restart denenir
- 5 kez peş peşe başarısız olursa launchd verir → manuel inceleme gerek
- `cat logs/launchd/ceo.stderr.log` → root cause

### `launchctl load` hatası: "Load failed: 5"
- Plist daha önce yüklenmiş — önce unload edin
- `launchctl unload ~/Library/LaunchAgents/com.priceaction.ceo.plist`

### Telegram push gelmiyor ama process çalışıyor
- `TELEGRAM_BOT_TOKEN` ve `TELEGRAM_CHAT_ID` env vars set edilmiş mi?
- macOS launchd `.env` dosyasını okumaz; plist'in `EnvironmentVariables` kısmında YA da kullanıcı bash profile'da olmalı
- Test: manuel `.venv/bin/python -c "import os; print(os.environ.get('TELEGRAM_BOT_TOKEN', 'EMPTY'))"`
- Eğer EMPTY çıkarsa plist'e ekle (token'ı plist'e yazmak en pratik ama git'lemeden önce sanitize et)

## §5 Faz 4 hardening — sonraki adım

Sonraki ay (Faz 4):
- Log rotation (`/usr/local/etc/newsyslog.d/priceaction.conf`)
- `ThrottleInterval` 30→60 (crash storm daha tolerant)
- Resource limit `NumberOfFiles` 4096→8192
- Token budget alarmı (OpsAgent weekly report)

Şu an bu Faz 1, minimum viable autostart için yeterli.
