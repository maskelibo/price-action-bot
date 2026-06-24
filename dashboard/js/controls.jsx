// Action primitives: Button variants, Confirm modal, Toast host, useActions hook.
// Wires monitor-only screens into an actionable control surface.

const Button = ({tone='soft', size='sm', icon, children, onClick, disabled=false, danger=false, title}) => {
  const cls = `pa-btn pa-btn--${tone} pa-btn--${size} ` + (danger ? 'pa-btn--danger' : '') + (disabled ? ' pa-btn--off' : '');
  return (
    <button type="button" className={cls} onClick={onClick} disabled={disabled} title={title}>
      {icon && <span className="pa-btn-icon">{icon}</span>}
      {children && <span>{children}</span>}
    </button>
  );
};

const Confirm = ({open, title, body, confirmLabel, cancelLabel, tone='accent', onConfirm, onCancel}) => {
  if (!open) return null;
  return (
    <div className="pa-modal-scrim" onClick={onCancel}>
      <div className="pa-modal" onClick={e => e.stopPropagation()}>
        <div className="pa-modal-icon" data-tone={tone}>
          {tone === 'loss' ? <I.Halt/> : tone === 'profit' ? <I.Check/> : <I.Warn/>}
        </div>
        <div className="pa-modal-title">{title}</div>
        <div className="pa-modal-body">{body}</div>
        <div className="pa-modal-actions">
          <Button tone="soft" onClick={onCancel}>{cancelLabel}</Button>
          <Button tone={tone === 'loss' ? 'danger' : 'primary'} onClick={onConfirm}>{confirmLabel}</Button>
        </div>
      </div>
    </div>
  );
};

const ToastHost = ({toasts, onDismiss}) => (
  <div className="pa-toast-host">
    {toasts.map(t => (
      <div key={t.id} className={`pa-toast pa-toast--${t.tone || 'accent'}`} onClick={() => onDismiss(t.id)}>
        <span className="pa-toast-icon">
          {t.tone === 'loss' ? <I.Halt/> : t.tone === 'warn' ? <I.Warn/> : <I.Check/>}
        </span>
        <span>{t.msg}</span>
      </div>
    ))}
  </div>
);

// useActions — central hook for control flow. Owns: confirm state, toast queue,
// and the action implementations (which mutate `setData` so the UI reacts).
function useActions(data, setData, lang) {
  const t = STRINGS[lang];
  const [confirmState, setConfirmState] = React.useState(null);
  const [toasts, setToasts] = React.useState([]);

  const pushToast = React.useCallback((msg, tone='accent') => {
    const id = Math.random().toString(36).slice(2);
    setToasts(ts => [...ts, { id, msg, tone }]);
    setTimeout(() => setToasts(ts => ts.filter(x => x.id !== id)), 4200);
  }, []);

  const ask = React.useCallback((cfg) => setConfirmState(cfg), []);
  const dismiss = React.useCallback(() => setConfirmState(null), []);

  const actions = {
    haltBot: () => ask({
      title: t.confirm.halt_title,
      body: t.confirm.halt_body,
      confirmLabel: t.action.halt,
      cancelLabel: t.action.cancel,
      tone: 'loss',
      onConfirm: () => {
        setData(d => ({...d, halted: true}));
        pushToast(t.toast.halted, 'loss');
        dismiss();
      },
    }),
    resumeBot: () => ask({
      title: t.confirm.resume_title,
      body: t.confirm.resume_body,
      confirmLabel: t.action.resume,
      cancelLabel: t.action.cancel,
      tone: 'profit',
      onConfirm: () => {
        setData(d => ({...d, halted: false}));
        pushToast(t.toast.resumed, 'accent');
        dismiss();
      },
    }),
    closePosition: (pos) => ask({
      title: t.confirm.close_title,
      body: t.confirm.close_body.replace('{sym}', pos.symbol),
      confirmLabel: t.action.close_pos,
      cancelLabel: t.action.cancel,
      tone: pos.unrealized_pnl_usdt < 0 ? 'loss' : 'profit',
      onConfirm: () => {
        setData(d => ({...d, positions: d.positions.filter(p => p.symbol !== pos.symbol)}));
        pushToast(t.toast.closed.replace('{sym}', pos.symbol), pos.unrealized_pnl_usdt < 0 ? 'loss' : 'accent');
        dismiss();
      },
    }),
    approveSignal: (sig) => ask({
      title: t.confirm.approve_title,
      body: t.confirm.approve_body.replace('{sym}', sig.symbol),
      confirmLabel: t.action.approve,
      cancelLabel: t.action.cancel,
      tone: 'profit',
      onConfirm: () => {
        setData(d => ({
          ...d,
          pending_signals: d.pending_signals.map(s => (s.ts === sig.ts && s.symbol === sig.symbol) ? {...s, gate_state: 'risk_approved'} : s)
        }));
        pushToast(t.toast.approved.replace('{sym}', sig.symbol), 'accent');
        dismiss();
      },
    }),
    rejectSignal: (sig) => ask({
      title: t.confirm.reject_title,
      body: t.confirm.reject_body.replace('{sym}', sig.symbol),
      confirmLabel: t.action.reject,
      cancelLabel: t.action.cancel,
      tone: 'loss',
      onConfirm: () => {
        setData(d => ({
          ...d,
          pending_signals: d.pending_signals.map(s => (s.ts === sig.ts && s.symbol === sig.symbol) ? {...s, gate_state: 'risk_rejected', reject_reason: 'manual_override'} : s)
        }));
        pushToast(t.toast.rejected.replace('{sym}', sig.symbol), 'warn');
        dismiss();
      },
    }),
    saveRiskConfig: (changes) => {
      setData(d => ({...d, risk_config: {...(d.risk_config || {}), ...changes}}));
      pushToast(t.toast.saved, 'accent');
    },
  };

  return { actions, confirmState, dismiss, toasts, pushToast, removeToast: id => setToasts(ts => ts.filter(x => x.id !== id)) };
}

window.Button = Button;
window.Confirm = Confirm;
window.ToastHost = ToastHost;
window.useActions = useActions;
