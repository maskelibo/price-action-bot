# Ortak Sözlük

## Trading
- **Bar / Mum:** Belirli timeframe'in OHLCV özeti.
- **Pin bar:** Uzun gölgeli, kısa gövdeli reversal mumu.
- **Engulfing:** Önceki mum gövdesini tamamen yutan zıt yön mumu.
- **Inside bar:** Tamamen önceki mumun range'i içinde kalan mum.
- **Swing high/low:** n-bar fractal tepe/dip.
- **S/R (Support/Resistance):** Yatay fiyat kümeleri.
- **BOS (Break of Structure):** Önceki swing'i yön değişikliğiyle kıran hareket.
- **CHoCH (Change of Character):** Trend yapısının ilk net kırılma sinyali.
- **R-multiple:** Kazanç/kayıp birim risk (SL'e olan mesafe) cinsinden.
- **ATR:** Average True Range; volatilite ölçümü.
- **VWAP:** Volume-weighted average price.

## Risk
- **MaxDD:** Maximum drawdown — peak-to-trough en derin kayıp.
- **Sharpe:** Excess return / std dev of returns.
- **Sortino:** Excess return / downside std dev.
- **Calmar:** Annualized return / MaxDD.
- **Profit factor:** Toplam kâr / |toplam kayıp|.
- **Expectancy:** Trade başına ortalama R.
- **MAE / MFE:** Maximum Adverse / Favorable Excursion.

## Mimari
- **Department:** Bir alanın sorumluluğunu üstlenen Python paketi + (varsa) LLM agent.
- **Champion / Challenger:** Canlı stratejinin (champion) yeni adaylarla (challenger) yarıştığı tournament.
- **Walk-forward:** Rolling train-test pencereleriyle backtest.
- **Drift:** Canlı performansın backtest dağılımından sapması.
- **Manifest:** `(git_hash, config_hash, data_hash)` üçlüsü; reproducibility için.
- **Gate:** Bir fazın sayısal başarı eşiği.

## LLM
- **Identity / know-how / learning:** Memory tipleri (bkz. memory/README.md).
- **RAG:** Retrieval-Augmented Generation; ChromaDB üzerinden price action literatürü sorgusu.
- **Pre-registration:** Hipotezi kod yazmadan önce yazılı kaydetmek.
