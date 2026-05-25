// Minimal icon set — 1.5 stroke, 18×18 viewBox, currentColor.
// Used across the dashboard. Kept atomic so we never reach for emoji.

const I = {};

I.Logo = ({size=22}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
    <path d="M3 18 L8 12 L12 15 L16 7 L21 13" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
    <circle cx="21" cy="13" r="1.6" fill="currentColor"/>
  </svg>
);

const stroke = (d, extra=null) => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    {typeof d === 'string' ? <path d={d}/> : d}
    {extra}
  </svg>
);

I.Overview    = () => stroke(<><rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/></>);
I.Positions   = () => stroke(<><path d="M3 12h4l3-8 4 16 3-8h4"/></>);
I.Scanner     = () => stroke(<><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></>);
I.Signals     = () => stroke(<><path d="M4 19c2-6 5-10 8-10s5 3 8 10"/><circle cx="12" cy="9" r="1.4" fill="currentColor"/></>);
I.Journal     = () => stroke(<><path d="M5 4h11l3 3v13H5z"/><path d="M9 9h7M9 13h7M9 17h4"/></>);
I.Risk        = () => stroke(<><path d="M12 3 4 7v6c0 4.5 3.4 7.5 8 8 4.6-.5 8-3.5 8-8V7z"/><path d="M12 9v4M12 16v.5"/></>);
I.Departments = () => stroke(<><rect x="3" y="9" width="6" height="12" rx="1"/><rect x="15" y="5" width="6" height="16" rx="1"/><rect x="9" y="13" width="6" height="8" rx="1"/></>);
I.Reports     = () => stroke(<><path d="M5 3h10l4 4v14H5z"/><path d="M15 3v4h4"/><path d="M9 13h6M9 17h6M9 9h3"/></>);
I.Phase       = () => stroke(<><circle cx="6" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="18" cy="12" r="2"/><path d="M8 12h2M14 12h2"/></>);

I.ArrowUp     = () => stroke(<><path d="m6 14 6-6 6 6"/></>);
I.ArrowDown   = () => stroke(<><path d="m6 10 6 6 6-6"/></>);
I.ArrowRight  = () => stroke(<><path d="m9 6 6 6-6 6"/></>);
I.Dot         = ({color='currentColor'}) => <svg width="8" height="8" viewBox="0 0 8 8"><circle cx="4" cy="4" r="3.2" fill={color}/></svg>;
I.Pulse       = () => stroke(<><path d="M3 12h4l2-5 4 10 2-5h6"/></>);
I.Long        = () => stroke(<><path d="m6 14 5-5 3 3 4-6"/><path d="M14 6h4v4"/></>);
I.Short       = () => stroke(<><path d="m6 10 5 5 3-3 4 6"/><path d="M14 18h4v-4"/></>);
I.Halt        = () => stroke(<><circle cx="12" cy="12" r="8.5"/><path d="m8 8 8 8M16 8l-8 8"/></>);
I.Check       = () => stroke(<><path d="m5 12 5 5 9-11"/></>);
I.Clock       = () => stroke(<><circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3 2"/></>);
I.Lock        = () => stroke(<><rect x="5" y="11" width="14" height="9" rx="1.5"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></>);
I.Spark       = () => stroke(<><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/></>);
I.Slash       = () => stroke(<><path d="M5 19 19 5"/></>);
I.Warn        = () => stroke(<><path d="M12 4 2 20h20Z"/><path d="M12 10v4M12 17v.5"/></>);
I.Brain       = () => stroke(<><path d="M9 5a3 3 0 0 0-3 3 3 3 0 0 0-2 3 3 3 0 0 0 2 3v2a3 3 0 0 0 3 3h6a3 3 0 0 0 3-3v-2a3 3 0 0 0 2-3 3 3 0 0 0-2-3 3 3 0 0 0-3-3"/></>);
I.Cog         = () => stroke(<><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/></>);
I.Heartbeat   = () => stroke(<><path d="M3 12h3l2-4 4 9 3-7 2 2h4"/></>);

window.I = I;
