import pandas as pd
ct = pd.read_csv('reports/analyst/_postmortem_22h_trades_v2.csv')
ct['open_ts'] = pd.to_datetime(ct['open_ts'])
ct['close_ts'] = pd.to_datetime(ct['close_ts'])
gross_gain = ct[ct['rpnl']>0]['rpnl'].sum()
gross_loss = -ct[ct['rpnl']<0]['rpnl'].sum()
pf = gross_gain / gross_loss if gross_loss>0 else float('inf')
print(f'gross_gain ${gross_gain:.3f}  gross_loss ${gross_loss:.3f}  PF {pf:.3f}')
print(f'avg_R={ct["R"].mean():.3f}, sum_R={ct["R"].sum():.3f}')
wins = ct[ct['rpnl']>0]; losses = ct[ct['rpnl']<0]
print(f'avg_win_R={wins["R"].mean():.3f}  avg_loss_R={losses["R"].mean():.3f}')
print(f'losers MFE/|MAE| ratio mean: {(losses["MFE_pct"]/losses["MAE_pct"].abs()).mean():.3f}')
sl_dist = losses.apply(lambda r: abs(r['avg_entry']-r['sl'])/r['avg_entry']*100 if pd.notna(r['sl']) else float('nan'), axis=1)
losses_w_sl = losses[sl_dist.notna()]
sl_dist_v = sl_dist.dropna()
mfe_share = losses_w_sl['MFE_pct'].values / sl_dist_v.values
print('MFE / SL_dist per loser:', list(zip(losses_w_sl['sym'].tolist(), [round(x,2) for x in mfe_share])))
print(f'noise_hit_share (>50%): {(mfe_share>0.5).sum()/len(mfe_share)*100:.0f}%')
print(f'noise_hit_share (>30%): {(mfe_share>0.3).sum()/len(mfe_share)*100:.0f}%')
total_fee = 3.9759
print(f'total fees ${total_fee:.3f}, per trade ${total_fee/9:.3f}, fee/equity {total_fee/5055.66*100:.3f}%')
print(f'net rpnl ${ct["rpnl"].sum():.2f}, total = rpnl + fees = ${ct["rpnl"].sum() - total_fee:.2f}')
# Strategy decomposition
print('\n--- BFB only (5 trades) ---')
bfb = ct[ct['strategy']=='brooks_failed_breakout']
print(f'BFB: n={len(bfb)}, rpnl_sum=${bfb["rpnl"].sum():.2f}, avg_R={bfb["R"].mean():.3f}')
# XRP vsa : 3 trades = -3.16 + 0.25 + 0.25 = -2.66 — wins were partial TP of a SL'd trade
print('\nXRP vsa biography:')
xrp = ct[(ct['sym']=='XRPUSDT')&(ct['strategy']=='vsa_climax_test')].sort_values('open_ts')
print(xrp[['open_ts','close_ts','avg_entry','exit_price','rpnl','R','hold_min']].to_string())
