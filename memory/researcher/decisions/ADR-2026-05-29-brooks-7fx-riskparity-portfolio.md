# ADR-2026-05-29 — brooks 7-FX risk-parity portfolio (terfi adayı)

- Status: CANDIDATE (Lab kabulü + insan onayı bekler — researcher final yazamaz)
- Hipotez: HYP-2026-05-29-brooks-7fx-uncorrelated-legs
- Repro: git=$(git rev-parse --short HEAD) seed=12345 data_hash(8sym)=see script stdout
- Script: scripts/brooks_portfolio_7fx.py (reuses forex_4h_research.gather VERBATIM)

## Karar
brooks_failed_breakout'u 8 FX 4H sembolünün risk-parity havuzunda çalıştır. AUD/USD+NZD/USD
(+0.89 fiyat korel) tek risk birimi (her biri half-risk). Diversification varyansı sıkıştırdı:
matched aggregate exposure'da STD ~yarıya, moSharpe +%40, MC_medDD ~yarıya, medyan korundu.
Robustluk (WF/symbol-out CV/shuffle OOS) tamamı geçti.

## Gerekçe
- 8/8 sembol standalone pozitif (BH-FDR PASS), mean pairwise R-corr +0.106.
- Vol-targeting (önceki RED) yapamadığını çeşitlenme yaptı — pre-reg null H0-b/H0-c reddedildi.

## Şerh (dürüst)
- IS→OOS degradasyon gerçek (moSharpe 0.81→0.46) ama OOS pozitif kalıyor.
- Medyan %15-20 hedefi ancak DD -35%+ ile gelir. Temiz tavan: medyan ~%11 @ MC_medDD -18% (7fx@1.07%).
- NZD/USD en zayıf bacak; 7-leg (NZD'siz) ~ aynı sonucu daha düşük DD ile verir.
