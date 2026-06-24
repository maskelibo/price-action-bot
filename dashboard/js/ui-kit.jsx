// i18n + formatters + tiny shared UI primitives (Card, KpiTile, Sparkline, Badge…)

const STRINGS = {
  tr: {
    brand: 'Price Action Co.',
    tagline: 'Otonom Swing Trading Şirketi',
    monitoring: 'İZLEME MODU',
    paper: 'PAPER · BİNANCE TESTNET',
    halted: 'DURDURULDU — BREAKER TETİKLENDİ',
    nav: { overview:'Genel Bakış', positions:'Açık Pozisyonlar', scanner:'Tarayıcı', signals:'Sinyal Akışı', journal:'İşlem Geçmişi', risk:'Risk & Breaker', departments:'Departmanlar', reports:'Raporlar' },
    section: { equity:'Sermaye Eğrisi', kpi:'KPI Özeti', risk_state:'Risk Durumu', live_pos:'Açık Pozisyonlar', recent:'Tüm İşlem Geçmişi', scan_activity:'Tarama Aktivitesi', phases:'Faz İlerlemesi', dept_health:'Departman Sağlığı', universe:'Sembol Evreni', signal_queue:'Sinyal Kuyruğu', breakers:'Drawdown Breaker', corr:'Korelasyon Matrisi', leverage:'Kaldıraç Kullanımı', latest_ceo:'En Son CEO Direktifi', latest_analytics:'En Son Analytics Brief', strat_perf:'Strateji Performansı (30g)', system_flow:'Sistem Akışı', signal_flow:'Otomatik Sinyal Akışı', by_symbol:'Coin Bazında Performans', win_vs_loss:'Kazanan ve Kaybedenler', risk_config:'Risk Konfigürasyonu' },
    label: { trades:'İşlem', net_pnl:'Net PnL', sharpe:'Sharpe', sortino:'Sortino', pf:'Profit Factor', win:'Kazanma Oranı', dd:'Maks Drawdown', expectancy:'Beklenti R', calmar:'Calmar', open:'Açık', notional:'Notional', exposure:'Exposure', symbol:'Sembol', side:'Yön', entry:'Giriş', current:'Anlık', sl:'SL', tp:'TP', upnl:'Anlık PnL', rmul:'R-çarpan', strat:'Strateji', pattern:'Kalıp', confluence:'Confluence', age:'Yaş', leverage:'Lev', pending:'Bekleyen', approved:'Risk Onaylı', rejected:'Reddedildi', awaiting:'Risk Bekliyor', signal_only:'Sadece Sinyal', timeframe:'TF', direction:'Yön', atr:'ATR%', daily:'Günlük', weekly:'Haftalık', monthly:'Aylık', used:'kullanıldı', limit:'limit', tripped:'TETİKLENDİ', clean:'temiz', last_run:'Son çalışma', status:'Durum', llm:'LLM Şefli', kpi:'KPI', package:'Paket', note:'Not', phase:'Faz', gate:'Gate', value:'Değer', done:'Tamam', active:'Aktif', locked:'Kilit', skipped:'Atlandı', win_rate:'Kazanma', loss:'Zarar', long:'LONG', short:'SHORT', today:'Bugün', total_notional:'Toplam Notional', volume:'İşlem Hacmi', avg_win:'Ort. Kazanç', avg_loss:'Ort. Zarar', avg_lev:'Ort. Lev', avg_hold:'Ort. Tutma', rr_ratio:'R/R Oranı', hold:'Tutma', exit:'Çıkış', dist:'Dağılım', classification:'Sınıflandırma', clean_exec:'temiz', n_trades:'İşlem', win_lbl:'Win', uptime:'Çalışma Süresi', warnings:'Uyarı', llm_led:'LLM Şefli', setups:'Hazır', watch:'İzlemede', universe_size:'Evren', last_scan:'Son Tarama', avg_atr:'Ort. ATR', avg_confluence:'Ort. Confluence', risk_per_trade:'işlem başına risk', kelly_cap:'kelly tavanı', max_lev:'maks. kaldıraç', corr_gate:'korelasyon kapısı', symbols:'sembol', edit:'düzenle', editable:'düzenlenebilir', automated:'otomatik', live:'canlı', live_now:'şimdi canlı' },
    chip: { phase6:'Faz 6 · Paper Trading', monitoring:'izleme', symbols:'sembol taranıyor' },
    scan: { setup:'HAZIR', watch:'İZLE', up:'YUKARI', down:'AŞAĞI', flat:'YATAY', scanned:'son tarama' },
    misc: { search:'sembol/kalıp ara…', filter:'Filtre', all:'Tümü', longs:'Long', shorts:'Short', wins:'Kazanan', losses:'Kaybeden', empty:'kayıt yok', refresh:'Yenile', ago:'önce', sec:'sn', view_all:'tümünü gör' },
    action: { halt:'Bot\u2019u Durdur', resume:'Devam Ettir', close_pos:'Kapat', approve:'Onayla', reject:'Reddet', edit:'Düzenle', save:'Kaydet', cancel:'İptal', confirm_btn:'Onayla' },
    confirm: {
      halt_title:'Bot durdurulsun mu?',
      halt_body:'Yeni emirler bloke olur. Açık pozisyonlar açık kalır; istersen ayrı ayrı kapatabilirsin.',
      resume_title:'Bot tekrar aktif edilsin mi?',
      resume_body:'Sinyal akışı ve emir gönderimi yeniden başlar. Risk breaker durumu kontrol edildi mi?',
      close_title:'Pozisyon kapatılsın mı?',
      close_body:'{sym} pozisyonu market emirle kapatılacak. PnL realize edilir.',
    },
    toast: { halted:'Bot durduruldu', resumed:'Bot tekrar aktif', closed:'{sym} kapatıldı', saved:'Risk konfigürasyonu kaydedildi' },
    subs: {
      overview: 'paper · faz 6 · binance testnet',
      positions: 'açık pozisyonlar · gerçek zamanlı',
      scanner: 'sinyal mühendisliği · 1G + 1H kapanış',
      signals: 'sinyal → risk → portföy → execution · otomatik',
      journal: 'analytics departmanı · 90 günlük pencere',
      risk: 'risk departmanı · breaker + korelasyon',
      departments: '10 departman · 4\u2019ü LLM şefli',
      reports: 'CEO + Analytics · markdown · günlük',
    },
    pipeline: { stage_scanner:'Tarayıcı', stage_signal:'Sinyal Mühendisliği', stage_risk:'Risk Officer', stage_portfolio:'Portföy', stage_exec:'Execution', auto_note:'bot manuel onay beklemeden çalışır · LLM emir vermez · deterministik kod karar verir' },
    flow: { observers:'Araştırmacılar', leadership:'Yönetim', operations:'Operasyon', note:'LLM departmanları (mint vurgulu) yalnızca hipotez ve rapor üretir. Emir veren tek katman Execution\u2019dır. Researcher ve Lab bilgi RAG\u2019dan beslenir; Analytics fill\u2019leri okur ve CEO\u2019ya brief yazar.' },
    risk_cfg: { fixed_frac:'fixed-fractional', paranoid:'paranoid', per_sym:'sembol başına', halve:'ρ > kapı ise boyut yarıya iner', blocks:'yeni emirler bloke', manual_review:'manuel inceleme', freeze:'dondur + post-mortem', liq:'1dk hacminin %1\u2019i', split:'parçala veya iptal' },
    reports_tab: { ceo:'CEO Direktifi', analytics:'Analytics Brief', markdown:'markdown' },
    notes: { queued:'execution kuyruğunda', risk_review:'risk officer incelemesinde', below_thr:'confluence eşiğinin altında', breaker_block:'breaker tetiklendi · yeni emir yok' },
  },
  en: {
    brand: 'Price Action Co.',
    tagline: 'Autonomous Swing Trading Firm',
    monitoring: 'MONITOR-ONLY',
    paper: 'PAPER · BINANCE TESTNET',
    halted: 'HALTED — BREAKER TRIPPED',
    nav: { overview:'Overview', positions:'Open Positions', scanner:'Scanner', signals:'Signal Queue', journal:'Trade Journal', risk:'Risk & Breakers', departments:'Departments', reports:'Reports' },
    section: { equity:'Equity Curve', kpi:'KPI Snapshot', risk_state:'Risk State', live_pos:'Open Positions', recent:'Recent Trades', scan_activity:'Scan Activity', phases:'Phase Progress', dept_health:'Department Health', universe:'Symbol Universe', signal_queue:'Signal Queue', breakers:'DD Breakers', corr:'Correlation Matrix', leverage:'Leverage Usage', latest_ceo:'Latest CEO Directive', latest_analytics:'Latest Analytics Brief', strat_perf:'Strategy Perf (30d)' },
    label: { trades:'Trades', net_pnl:'Net PnL', sharpe:'Sharpe', sortino:'Sortino', pf:'Profit Factor', win:'Win Rate', dd:'Max DD', expectancy:'Expectancy R', calmar:'Calmar', open:'Open', notional:'Notional', exposure:'Exposure', symbol:'Symbol', side:'Side', entry:'Entry', current:'Last', sl:'SL', tp:'TP', upnl:'Unrealized', rmul:'R-mult', strat:'Strategy', pattern:'Pattern', confluence:'Confluence', age:'Age', leverage:'Lev', pending:'Pending', approved:'Risk Approved', rejected:'Rejected', awaiting:'Awaiting Risk', signal_only:'Signal Only', timeframe:'TF', direction:'Side', atr:'ATR%', daily:'Daily', weekly:'Weekly', monthly:'Monthly', used:'used', limit:'limit', tripped:'TRIPPED', clean:'clean', last_run:'Last run', status:'Status', llm:'LLM-led', kpi:'KPI', package:'Package', note:'Note', phase:'Phase', gate:'Gate', value:'Value', done:'Done', active:'Active', locked:'Locked', skipped:'Skipped', win_rate:'Win', loss:'Loss', long:'LONG', short:'SHORT' },
    chip: { phase6:'Phase 6 · Paper Trading', monitoring:'monitor', symbols:'symbols scanning' },
    scan: { setup:'SETUP', watch:'WATCH', up:'UP', down:'DOWN', flat:'FLAT', scanned:'last scan' },
    misc: { search:'search symbol/pattern…', filter:'Filter', all:'All', longs:'Long', shorts:'Short', wins:'Win', losses:'Loss', empty:'nothing here', refresh:'Refresh', ago:'ago', sec:'s' },
    action: { halt:'Halt Bot', resume:'Resume', close_pos:'Close', approve:'Approve', reject:'Reject', edit:'Edit', save:'Save', cancel:'Cancel', confirm_btn:'Confirm' },
    confirm: {
      halt_title:'Halt the bot?',
      halt_body:'New orders are blocked. Open positions stay; you can close each individually.',
      resume_title:'Resume the bot?',
      resume_body:'Signal flow and order routing resume. Did you check the risk breaker state?',
      close_title:'Close position?',
      close_body:'{sym} will be closed at market. PnL is realized.',
      approve_title:'Approve signal?',
      approve_body:'{sym} signal will skip risk and go to the execution queue.',
      reject_title:'Reject signal?',
      reject_body:'{sym} signal is dropped from the queue and logged with reason.',
    },
    toast: { halted:'Bot halted', resumed:'Bot resumed', closed:'{sym} closed', approved:'{sym} approved', rejected:'{sym} rejected', saved:'Risk config saved' },
  },
};

const F = {
  usd: (n, opts={}) => {
    const sign = n > 0 ? '+' : '';
    const abs = Math.abs(n);
    let s;
    if (opts.compact && abs >= 10000) s = (abs/1000).toFixed(1) + 'k';
    else s = abs.toLocaleString('en-US', {minimumFractionDigits: opts.dp ?? 2, maximumFractionDigits: opts.dp ?? 2});
    return (n < 0 ? '−' : sign) + '$' + s;
  },
  num: (n, dp=2) => (n).toLocaleString('en-US', {minimumFractionDigits: dp, maximumFractionDigits: dp}),
  pct: (n, dp=1) => (n*100).toFixed(dp) + '%',
  pctSigned: (n, dp=2) => (n>0?'+':'') + (n*100).toFixed(dp) + '%',
  bps: (n, dp=1) => n.toFixed(dp) + ' bps',
  r: (n, dp=2) => (n>0?'+':'') + n.toFixed(dp) + 'R',
  ageHours: (iso) => {
    const h = (Date.now() - new Date(iso).getTime()) / 3_600_000;
    if (h < 1) return Math.round(h*60) + 'm';
    if (h < 24) return h.toFixed(1) + 'h';
    return (h/24).toFixed(1) + 'd';
  },
  shortDate: (iso) => {
    const d = new Date(iso);
    return d.toLocaleDateString('en-GB', { day:'2-digit', month:'short' }) + ' ' + d.toLocaleTimeString('en-GB', {hour:'2-digit', minute:'2-digit'});
  },
};

// ---- shared primitives ----------------------------------------------------

const Card = ({title, subtitle, action, children, padded=true, className=''}) => (
  <section className={`card ${className}`}>
    {(title || action) && (
      <header className="card-head">
        <div>
          {title && <h3 className="card-title">{title}</h3>}
          {subtitle && <p className="card-sub">{subtitle}</p>}
        </div>
        {action && <div className="card-action">{action}</div>}
      </header>
    )}
    <div className={padded ? 'card-body' : 'card-body card-body--flush'}>{children}</div>
  </section>
);

const Pill = ({tone='neutral', children, icon, dim=false}) => (
  <span className={`pill pill--${tone} ${dim ? 'pill--dim' : ''}`}>
    {icon && <span className="pill-icon">{icon}</span>}
    {children}
  </span>
);

const KpiTile = ({label, value, sub, tone, big=false}) => (
  <div className={`kpi-tile ${big ? 'kpi-tile--big' : ''}`}>
    <div className="kpi-tile-label">{label}</div>
    <div className={`kpi-tile-value ${tone ? `tone--${tone}` : ''}`}>{value}</div>
    {sub && <div className="kpi-tile-sub">{sub}</div>}
  </div>
);

// SVG sparkline / area chart with gradient fill
const AreaChart = ({points, height=280, color='var(--accent)', minimal=false, fillOpacity=0.18}) => {
  if (!points || !points.length) return null;
  const W = 1000, H = height, pad = minimal ? 4 : 28;
  const xs = points.map((_, i) => i);
  const ys = points.map(p => p.equity ?? p);
  const yMin = Math.min(...ys), yMax = Math.max(...ys);
  const xScale = i => pad + (i / (xs.length - 1)) * (W - pad*2);
  const yScale = v => H - pad - ((v - yMin) / (yMax - yMin || 1)) * (H - pad*2);
  const linePath = ys.map((v,i) => (i?'L':'M') + xScale(i).toFixed(1) + ' ' + yScale(v).toFixed(1)).join(' ');
  const areaPath = linePath + ` L ${xScale(xs.length-1)} ${H-pad} L ${xScale(0)} ${H-pad} Z`;
  const gid = 'g-' + Math.abs([...linePath].reduce((a,c)=>a+c.charCodeAt(0),0));
  // y-axis ticks (4)
  const yTicks = minimal ? [] : [0,1,2,3,4].map(k => yMin + (yMax-yMin)*k/4);
  // x-axis ticks (5)
  const xTicks = minimal ? [] : [0, 0.25, 0.5, 0.75, 1].map(p => Math.floor((xs.length-1)*p));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="area-chart" width="100%" height={height}>
      <defs>
        <linearGradient id={gid} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%"   stopColor={color} stopOpacity={fillOpacity}/>
          <stop offset="100%" stopColor={color} stopOpacity="0"/>
        </linearGradient>
      </defs>
      {!minimal && yTicks.map((v,i) => (
        <g key={i}>
          <line x1={pad} x2={W-pad} y1={yScale(v)} y2={yScale(v)} stroke="var(--border-soft)" strokeWidth="1" strokeDasharray="2 4"/>
          <text x={pad-6} y={yScale(v)+4} textAnchor="end" fontSize="11" fill="var(--text-muted)" fontFamily="var(--font-mono)">{(v/1000).toFixed(1)}k</text>
        </g>
      ))}
      {!minimal && xTicks.map((i,k) => {
        const ts = points[i]?.ts;
        if (!ts) return null;
        const d = new Date(ts);
        const lbl = d.toLocaleDateString('en-GB', { day:'2-digit', month:'short' });
        return (
          <text key={k} x={xScale(i)} y={H-6} textAnchor="middle" fontSize="11" fill="var(--text-muted)" fontFamily="var(--font-mono)">{lbl}</text>
        );
      })}
      <path d={areaPath} fill={`url(#${gid})`}/>
      <path d={linePath} fill="none" stroke={color} strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round"/>
    </svg>
  );
};

// Tiny inline sparkline (no axes)
const Spark = ({values, width=120, height=28, color='var(--accent)'}) => {
  if (!values?.length) return null;
  const mn = Math.min(...values), mx = Math.max(...values);
  const path = values.map((v,i) => {
    const x = (i / (values.length-1)) * (width-2) + 1;
    const y = height - 2 - ((v - mn) / (mx - mn || 1)) * (height - 4);
    return (i?'L':'M') + x.toFixed(1) + ' ' + y.toFixed(1);
  }).join(' ');
  return (
    <svg width={width} height={height} className="spark">
      <path d={path} fill="none" stroke={color} strokeWidth="1.4" strokeLinecap="round"/>
    </svg>
  );
};

// Progress bar with optional warning/limit tick
const ProgressBar = ({value, max, tone='accent', label, secondary, dangerAt=0.8}) => {
  const pct = Math.min(1, Math.abs(value) / max);
  const danger = pct >= dangerAt;
  return (
    <div className="pbar">
      <div className="pbar-head">
        <span className="pbar-label">{label}</span>
        {secondary && <span className="pbar-secondary">{secondary}</span>}
      </div>
      <div className="pbar-track">
        <div className={`pbar-fill tone--${danger ? 'loss' : tone}`} style={{width: (pct*100).toFixed(1) + '%'}}/>
      </div>
    </div>
  );
};

window.STRINGS = STRINGS;
window.F = F;
window.Card = Card;
window.Pill = Pill;
window.KpiTile = KpiTile;
window.AreaChart = AreaChart;
window.Spark = Spark;
window.ProgressBar = ProgressBar;
