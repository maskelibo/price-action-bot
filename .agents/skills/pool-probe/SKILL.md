---
name: pool-probe
description: Backtest pool dosyasını yükleyip (sec53_*_pool_v11_*.pkl) tarih+eşik filtresi ile trade sayısı ve sembol dağılımı verir. P1c / 15m geçmiş soruları için. Use when user asks "havuzda son N gün ne oldu", "P1c geçmişte ne yapardı", "eşik X olsa kaç trade", "geçmişte bu strateji ne yaptı".
---

# Pool Probe — backtest havuz analizi

Pre-built backtest havuzlarını (`data/sec53_*_pool_v11_*.pkl`) inspect eder.

## Mevcut havuz dosyaları

```
data/sec53_15m_pool_v11.pkl                — 15m default
data/sec53_15m_pool_v11_vsa2_top4.pkl     — 15m top4 vsa-focused
data/sec53_15m_pool_v11_vm3_backup.pkl    — 15m vm3 backup
data/sec53_5m_pool_v11_vm20.pkl           — 5m P1c base (vm=2.0)
```

## Argümanlar

- `timeframe`: "5m" veya "15m" (default 5m)
- `days`: son N gün (default 30)
- `sl_threshold`: minimum sl_pct (default 0.030 for 5m P1c, 0.025 for 15m v2)
- `drop_strategies`: liste (default `['engulfing_continuation']` for 5m P1c)

## Pool element formatı (her trade dict)

```python
{
    'entry_ts': Timestamp('2021-05-16 05:10:00+0000', tz='UTC'),
    'exit_ts': Timestamp('...'),
    'entry_price': 48233.29,
    'initial_sl': 49159.02,
    'R': -1.105,           # realized R-multiple
    'peak_R': 0.214,       # max favorable
    'symbol': 'BTC/USDT',
    'side': 'short',
    'conf': 0.333,
    'strategy': 'vsa_climax_test',
    'vol_z': 1.0
}
```

## sl_pct formülü (KRİTİK)

```python
sl_pct = abs(initial_sl - entry_price) / entry_price
```
Bu look-ahead temizdir (entry anında bilinir).

## W1 filtresi (P1c base)

```python
filt = pool[(pool['sl_pct'] >= sl_threshold) &
            (~pool['strategy'].isin(drop_strategies))]
```

## Standart probe scripti

```bash
cd ~/price-action-bot && .venv/bin/python <<'PY'
import pickle, pandas as pd

POOL = 'data/sec53_5m_pool_v11_vm20.pkl'    # <-- timeframe'e göre
DAYS = 30
SL_MIN = 0.030
DROP = ['engulfing_continuation']

with open(POOL,'rb') as f:
    pool = pickle.load(f)
df = pd.DataFrame(pool)
df['sl_pct'] = abs(df['initial_sl'] - df['entry_price']) / df['entry_price']

end = df['entry_ts'].max()
cutoff = end - pd.Timedelta(days=DAYS)
last = df[df['entry_ts'] >= cutoff].copy()
filt = last[(last['sl_pct'] >= SL_MIN) & (~last['strategy'].isin(DROP))]

print(f'Pool: {POOL}')
print(f'Son tarih: {end}')
print(f'Pencere: {cutoff.date()} → {end.date()} ({DAYS} gün)')
print(f'  Ham sinyal: {len(last)}')
print(f'  W1 filter sonrası: {len(filt)} (= {len(filt)/DAYS:.2f}/gün)')
print()
print('Sembol bazında:')
print(filt['symbol'].value_counts().to_string())
print()
print('Günlük dağılım (sadece trade olan günler):')
filt['date'] = filt['entry_ts'].dt.date
print(filt.groupby('date').size().to_string())
print()
print('Son 10 trade detay:')
print(filt[['entry_ts','symbol','side','strategy','sl_pct','R','peak_R']]
      .tail(10).to_string())
PY
```

## Yorumlama referans noktaları

| Strateji | Beklenen n/yıl | Beklenen n/gün |
|---|---|---|
| 15m v2 wide-stop (sl≥%2.5) | 1,304 | ~3.6 |
| 5m P1c (sl≥%3.0) | 537 | ~1.5 |

**Gerçek < beklentinin 1/3'ü** → rejim sorunu sinyali (2026 YTD'de yaşandı).
**Pool snapshot tarihi 7+ gün eski olabilir** — bunu kullanıcıya MUTLAKA söyle.

## Eşik simülasyonu

`SL_MIN` değiştirip yeniden çalıştır. Her seviye için trade sayısı + ortalama R + win rate karşılaştır:

```python
for thresh in [0.020, 0.025, 0.030, 0.035]:
    f = df[df['sl_pct'] >= thresh]
    print(f'{thresh}: n={len(f)}, mean_R={f["R"].mean():.3f}, '
          f'win_rate={(f["R"]>0).mean():.2%}')
```

## Çapraz referans

- Canlı bot durumu: `bot-status`
- Yakın WIDESTOP analizi: `signal-proximity`
- Pool source-of-truth + recipe: `reports/research/5m_p1c_candidate_2026-05-24.md`
