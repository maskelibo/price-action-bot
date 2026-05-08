---
type: lesson
date: 2026-05-08
authored_by: human_principal
applies_to: [data_engineer, researcher, lab_scientist]
confidence: high
tags: [survivorship_bias, methodology, anti-pattern]
---

# Survivorship Bias — Kripto'da Dramatik

## Ders

Kripto'da delisting çok sık. Eğer evrenini "bugün listede olan coinler" olarak tanımlarsan, geçmişte var olup şimdi olmayan onlarca coini görmezsin. Bu, backtest sonuçlarını **dramatik şekilde iyimser** yapar — çünkü kötü performans gösterip delist olanlar evrene girmez.

## Pratik Kural

> Sembol evrenini **historical** olarak kur: bir tarihte listede olan tüm semboller, delisting tarihine kadar dahil edilir.

## Pratik Adımlar

1. `data/universe.py::build_universe(date)` zaman-bilinçli olmalı — verilen tarihte aktif olanları döndürür.
2. Backtest engine her bar için "o tarihte aktif olan" sembolleri kullanır.
3. Delisting tarihi sonrası sembol pozisyonu zorla kapatılır (Execution layer simulator).

## Tarihsel Örnekler (kripto)

- LUNA/UST 2022-05 — Binance perpetual delisted; price near zero.
- FTT 2022-11 — Binance/Bybit perpetual hızlı delisting.
- Birçok DeFi token 2022-2023 hacim ölünce delisted.

## Etki Büyüklüğü

Survivorship bias ile düzeltilmiş backtest sonuçları arasındaki fark, 3 yıllık kripto evreninde **yıllık %20-50 fark** üretebilir. Yani backtest'in "yıllık %100" diyorsa survivorship'siz gerçek "yıllık %50-80" olabilir.

## Yakalanma

CI testi: `tests/test_universe.py::test_includes_delisted_symbols` zorunlu.
