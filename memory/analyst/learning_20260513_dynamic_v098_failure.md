# Learning — DYNAMIC v0.9.8 Failure Forensics (2026-05-13)

1. Conf_pct top-tier (>=0.90, n=3711) avg_R = +0.3216 vs bot-tier (n=851) avg_R = +0.2309 → edge orani 1.39x; DYNAMIC %7 risk + 5x lev tier'i icin gereken 3.5x+ avg_R uplift'i YOK. Tier hipotezi sayisal olarak yanlis.
2. 61-trade gap'in 61'i (%100) `reject_concentration_per_symbol` — DYNAMIC'in buyuk notional'lari %20 per-symbol cap'i tek-pozisyonda doldurdu; ayni sembolde ikinci trade matematiksel olarak reddediliyor. Cap yapisinin tier sizing'le UYUMSUZ olmasi DYNAMIC'i mekanik olarak BALANCED'dan kucuk yapti.
3. Top-tier (>=0.90) sinyallerin %41.1'i TEK strateji (brooks_failed_breakout) — rolling-180g percentile rank strateji-invariant degil. EER-Score veya tier yapilarinda STRATIFIED bucket zorunlu (Lab'a iletildi).
