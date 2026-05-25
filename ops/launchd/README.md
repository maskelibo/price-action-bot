# ops/launchd/

macOS launchd plist'leri — Mac mini'nin boot anında otomatik başlattığı servisler.

## Dosyalar

| Plist | Servis | Yükleme durumu | Komutu |
|---|---|---|---|
| `com.priceaction.ceo.plist` | `pa-ceo --mode daily --telegram` (orchestrator) | **YÜKLENEBİLİR** | aşağıda §2 |
| `com.priceaction.futures15m.plist` | `futures_daemon.py --timeframe 15m` (trading bot) | **YÜKLENMEDİ** (mevcut manuel PID 17267) | dikkatli! §3 |

## §1 launchd nedir?

macOS'un init sistemi. Linux'taki `systemd` benzeri. Boot anında plist'leri okur, `RunAtLoad=true` olanları başlatır, `KeepAlive` ile crash sonrası restart eder.

Logs: `~/Library/Logs/com.priceaction.*` ve `logs/launchd/*.log`

## §2 CEO orchestrator — yükleme

**Bu plist `pa-ceo --mode daily --telegram` çalıştırır.** Mac mini boot olunca otomatik başlar; crash olursa 30sn sonra restart eder.

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
  .venv/bin/python -m price_action.orchestrator.ceo_loop --mode once --telegram
```

## §3 futures15m daemon — DİKKAT

**Bu plist HAZIR ama YÜKLENMEDİ.**

Mevcut durum:
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
