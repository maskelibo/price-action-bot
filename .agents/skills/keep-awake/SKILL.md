---
name: keep-awake
description: Mac'in uyumasını engelle ama ekranın kapanmasına/kilitlenmesine izin ver — böylece arkada botlar çalışmaya devam eder. launchd `com.peyman.caffeinate` job'unu `-ims` flag'iyle kurar/doğrular/onarır. Use when user asks "caffeine", "pc uyumasın", "mac kapanmasın botlar çalışsın", "keep awake", "ekran kapansın ama pc çalışsın", "uyku ayarı".
---

# Keep Awake — Mac uyumasın, ekran kapanabilir, botlar arkada çalışsın

**Amaç:** PC SİSTEM uykusuna girmesin (futures daemon'ları arkada çalışmaya devam etsin) AMA ekran kapanabilsin + kilitlenebilsin (güç tasarrufu + gizlilik).

> ⚠️ KRİTİK FLAG: **`-ims`** olmalı.
> - `-i` = idle system sleep engelle
> - `-m` = disk idle sleep engelle
> - `-s` = AC güçteyken sistem uykusunu engelle
> - **`-d` YOK** (ekran kapanabilir) — `-dimsu` kullanma, o ekranı açık tutar!
> - **`-u` YOK** (kullanıcı-aktif zorlaması yok)

## 1) Teşhis (önce mevcut durum)

```bash
echo "=== Çalışan caffeinate flag'leri ===" && ps aux | grep -i "[c]affeinate" && \
echo "=== launchd job ===" && launchctl list | grep -i caffeinate || echo "JOB YÜKLÜ DEĞİL" && \
echo "=== pmset assertions (gerçek etki) ===" && \
pmset -g assertions | grep -E "PreventUserIdleDisplaySleep|PreventSystemSleep|PreventUserIdleSystemSleep"
```

**Doğru durum:**
- `PreventUserIdleDisplaySleep    0`  ← ekran kapanabilir ✅
- `PreventSystemSleep             1`  ← PC uyumaz ✅
- `PreventUserIdleSystemSleep     1`  ← idle uyku engelli ✅

Eğer `PreventUserIdleDisplaySleep = 1` ise → flag yanlış (`-d` veya `-u` var), onar (adım 3).

## 2) Plist (kalıcı kurulum — yoksa oluştur)

Yer: `~/Library/LaunchAgents/com.peyman.caffeinate.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.peyman.caffeinate</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/caffeinate</string>
        <string>-ims</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ProcessType</key><string>Background</string>
</dict>
</plist>
```

## 3) Kur / Onar (flag yanlışsa veya job yüklü değilse)

```bash
PLIST=~/Library/LaunchAgents/com.peyman.caffeinate.plist
# (plist'i adım 2'deki içerikle güvenli bir dosya düzenleme yöntemiyle yaz)
launchctl bootout gui/$(id -u)/com.peyman.caffeinate 2>/dev/null   # eski job'u kaldır
pkill -f "caffeinate -dimsu" 2>/dev/null                            # yanlış flag'li artık varsa öldür
launchctl bootstrap gui/$(id -u) "$PLIST"                           # yeni job'u yükle (RunAtLoad hemen başlatır)
sleep 1 && pmset -g assertions | grep -E "DisplaySleep|SystemSleep"  # doğrula
```

## Notlar

- **KeepAlive=true** → caffeinate ölürse launchd yeniden başlatır; **RunAtLoad=true** → login/reboot'ta otomatik.
- `caffeinate -i -t 300` gibi geçici (-t süreli) süreçler başka araçlardan gelir, normal; kendiliğinden expire olur, dokunma.
- Bu skill SADECE güç/uyku ayarını yönetir — botları başlatmaz/durdurmaz.
  Güncel canlı trading job'u `com.priceaction.futures_v15p2`'dir; diğer bot/job
  envanteri değişebileceği için `bot-status` veya `launchctl` ile doğrulanır.
- İlgili hafıza: `mac-keepawake-caffeinate-fix.md`.
