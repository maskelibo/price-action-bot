---
name: bot-status
description: Price-action-bot 15m daemon snapshot - PID, uptime, last scan TR/UTC, log freshness, next bar, recent log lines, cumulative counters (SCAN/WIDESTOP/STALE/RISK/MISSED/ENTRY). Use when user asks "durum nedir", "bot çalışıyor mu", "tarama yaptı mı", "status".
---

# Bot Status — 15m daemon snapshot

Tek seferde bot durum raporu üret. Kullanıcı her seans 3-4 kez ister; standart format şart.

## Komut (tek bash bloğu)

```bash
date && echo "---" && \
ps -p 17267 -o pid,etime,stat,command 2>/dev/null || echo "PID 17267 ÇALIŞMIYOR" && \
echo "---" && \
cd ~/price-action-bot && stat -f "Log mtime: %Sm" logs/futures_daemon.log && \
echo "---" && tail -15 logs/futures_daemon.log && \
echo "---SAYIM---" && \
echo "Toplam tarama:" $(grep -c "15M_SCAN:" logs/futures_daemon.log) && \
echo "WIDESTOP red:" $(grep -c "15M_REJECT_WIDESTOP" logs/futures_daemon.log) && \
echo "STALE red:" $(grep -c "15M_REJECT_STALE" logs/futures_daemon.log) && \
echo "RISK red:" $(grep -c "15M_REJECT_RISK" logs/futures_daemon.log) && \
echo "MISSED bar:" $(grep -c "15M_MISSED_BARS" logs/futures_daemon.log) && \
echo "ENTRY:" $(grep -cE "ACCEPT|ENTRY|FILL|POSITION_OPEN" logs/futures_daemon.log)
```

## Önemli notlar (yorumlanırken)

- **Log timestamp'leri UTC**, TR = UTC+3. `[18:00:11]` log satırı = **21:00:11 TR**.
- **Bar close timestamp'leri zaten UTC** olarak yazılı (`sonraki bar kapanış HH:MM:05 UTC`).
- **PID 17267** mevcut deploy (15m v2 paper, sl_pct ≥ %2.5). Başka PID'ler için `ps aux | grep futures_daemon` ile bul.
- `STAT=S` (sleeping) = normal, bar bekliyor. `STAT=R` (running) = tarama anında. Hiçbiri görünmüyorsa ÖLMÜŞTÜR.
- **Log mtime ile şimdi arası > 16 dakika** → kaçırılmış bar veya bot dondu, alert ver.

## Rapor formatı (kullanıcıya verirken)

Tablolarla özetle:

```
## Durum (HH:MM TR — son kontrolden +Xs)

**Sistem [sağlıklı ✅ / sorunlu ⚠️ / ölü ❌]**
- PID 17267 aktif, uptime: **Xg Ys Zd**
- Son tarama: **HH:MM TR** (Xdk önce)
- Sıradaki tarama: **HH:MM TR** (~Xdk sonra)

**Kümülatif sayaçlar:**
| Metrik | Değer | Δ (son kontrolden) |
|---|---|---|
| Toplam tarama | X | +Y |
| WIDESTOP red | X | +Y |
| ENTRY | 0 | – |

**Son scan'ler özeti:** [1-2 cümle, en dikkat çekici olan]
```

## Önceki kontrol değerini hatırlama

Eğer önceki bot-status çağrısı varsa Δ hesapla. Yoksa "ilk kontrol" yaz, sadece mutlak değerleri göster.

## İleri analiz tetikleyicileri

- WIDESTOP red ani artarsa (>20 son saatte) → `signal-proximity` öner (volatilite kıpırdıyor mu?)
- ENTRY > 0 → pozisyon detaylarını `data/execution_fills.duckdb`'den çek
- MISSED bar artarsa → network/exchange sorunu, kullanıcıyı uyar
- PID ölmüşse → `daemon-restart` skill'ini öner (henüz yoksa kullanıcıyı bilgilendir)
