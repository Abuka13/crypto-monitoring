import { RISK, STAT, TYPE, TXSTAT } from './meta';
import { weiToEth, shorten, fmtDate, num, riskBucket } from './format';

// Преобразование сырых записей API в данные для отображения (метки/цвета/обработчики).
// ctx содержит текущий словарь переводов t и обработчики открытия/копирования.

export function alertVM(a, ctx){
  const t = ctx.t;
  const rm = RISK[a.level] || RISK.low; const sm = STAT[a.status] || STAT.open;
  const tm = a.target_type === 'transaction' ? TYPE.tx : TYPE.wlt;
  return {
    raw:a, id:'#' + a.id, typeLabel:tm.label, typeStyle:'background:' + tm.bg + ';color:' + tm.color + ';',
    title:a.title || '—', desc:a.description || '',
    riskLabel:t.risk[a.level] || a.level, riskStyle:'background:' + rm.bg + ';color:' + rm.color + ';border:1px solid ' + rm.color + '40;',
    statusLabel:t.status[a.status] || a.status, statusStyle:'background:' + sm.bg + ';color:' + sm.color + ';',
    score:a.final_score, scoreColor:rm.color, dateStr:fmtDate(a._ts),
    isHigh:(a.level === 'high' && a.status === 'open'),
    onOpen:() => ctx.openAlert(a),
  };
}

export function walletVM(w, ctx){
  const t = ctx.t;
  const bk = riskBucket(w.risk_score); const rm = RISK[bk];
  const lbl = w.label ? (t.labels[w.label] || w.label) : t.labels.none;
  const lblColor = (w.label === 'mixer' || w.label === 'миксер') ? '#ff6f6f'
    : (w.label === 'fraud' || w.label === 'мошенник') ? '#f5b54a'
    : (w.label === 'exchange' || w.label === 'биржа') ? '#5fded0' : '#9aa3b2';
  return {
    raw:w, address:w.address, short:shorten(w.address),
    label:lbl, labelStyle:'background:' + lblColor + '1f;color:' + lblColor + ';',
    txCount:num(w.transaction_count),
    received:weiToEth(w.total_received, 2), sent:weiToEth(w.total_sent, 2),
    risk:Math.round(w.risk_score), riskColor:rm.color, flagged:w.is_flagged,
    onCopy:(e) => { e.stopPropagation(); ctx.copy(w.address); }, onOpen:() => ctx.openWallet(w),
  };
}

export function txVM(x, ctx){
  const t = ctx.t;
  const st = TXSTAT[x.status] || TXSTAT.success;
  return {
    raw:x, short:shorten(x.tx_hash, 8, 6),
    sender:shorten(x.sender_address), receiver:shorten(x.receiver_address),
    amount:weiToEth(x.amount, 3), block:num(x.block_number), dateStr:fmtDate(Date.parse(x.transaction_timestamp)),
    statusLabel:t.txStatus[x.status] || x.status, statusStyle:'background:' + st.b + ';color:' + st.c + ';',
    onCopy:(e) => { e.stopPropagation(); ctx.copy(x.tx_hash); }, onOpen:() => ctx.openTx(x),
  };
}

export function ruleVM(r, ctx){
  return {
    raw:r, name:r.name, desc:r.description || '', score:Math.round(r.score), active:r.is_active,
    toggleStyle:'background:' + (r.is_active ? 'var(--accent)' : 'var(--border)') + ';',
    knobStyle:'transform:translateX(' + (r.is_active ? '18px' : '0px') + ');',
    onToggle:() => ctx.toggleRule(r),
  };
}
