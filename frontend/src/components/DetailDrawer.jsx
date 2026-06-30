import React from 'react';
import { h, css } from '../lib/dom';
import { icon } from '../lib/icons';
import { ringGauge } from '../lib/charts';
import { RISK, STAT, TYPE, TXSTAT } from '../lib/meta';
import { weiToEth, shorten, fmtDate, num, riskBucket } from '../lib/format';

// Сборка модели детали (алерт / кошелёк / транзакция) — как в исходном detailVM.
function detailVM(selected, kind, detailData, t){
  const sel = selected; if(!sel) return null;

  if(kind === 'alert'){
    const d = detailData;
    const rm = RISK[sel.level] || RISK.low; const sm = STAT[sel.status] || STAT.open;
    const score = sel.final_score;
    let fired = [], ctxRows = [];
    if(d){
      fired = (d.fired_rules || []).map(f => ({name:f.name, score:f.score}));
      const c = d.context || {};
      if(d.target_type === 'transaction'){
        ctxRows = [
          {k:t.f.hash, v:shorten(c.tx_hash, 10, 8)},
          {k:t.f.amount, v:weiToEth(c.amount, 4) + ' ETH'},
          {k:t.f.sender, v:shorten(c.sender_address)},
          {k:t.f.receiver, v:shorten(c.receiver_address)},
          {k:t.f.block, v:num(c.block_number)},
          {k:t.f.time, v:fmtDate(Date.parse(c.transaction_timestamp))},
        ];
      } else {
        ctxRows = [
          {k:t.f.address, v:shorten(c.address, 10, 8)},
          {k:t.f.txcount, v:num(c.transaction_count)},
          {k:t.f.received, v:weiToEth(c.total_received, 3) + ' ETH'},
          {k:t.f.sent, v:weiToEth(c.total_sent, 3) + ' ETH'},
          {k:t.f.riskscore, v:String(Math.round(c.risk_score))},
        ];
      }
    }
    const actions = [];
    if(sel.status === 'open') actions.push({label:t.act.take, status:'in_progress'});
    if(sel.status === 'in_progress'){
      actions.push({label:t.act.close, status:'closed'});
      actions.push({label:t.act.false, status:'false_positive'});
    }
    return {
      kind:(sel.target_type === 'transaction' ? TYPE.tx.label : TYPE.wlt.label), id:'#' + sel.id,
      title:sel.title, desc:sel.description,
      riskLabel:t.risk[sel.level] || sel.level, riskStyle:'background:' + rm.bg + ';color:' + rm.color + ';border:1px solid ' + rm.color + '40;',
      statusLabel:t.status[sel.status] || sel.status, statusStyle:'background:' + sm.bg + ';color:' + sm.color + ';',
      gauge:ringGauge(score, rm.color), score:score, scoreColor:rm.color,
      fired:fired, ctxRows:ctxRows, actions:actions, hasActions:actions.length > 0,
      loadingCtx:!d,
    };
  }
  if(kind === 'wallet'){
    const bk = riskBucket(sel.risk_score); const rm = RISK[bk];
    const lbl = sel.label ? (t.labels[sel.label] || sel.label) : t.labels.none;
    return {
      kind:TYPE.wlt.label, id:' ' + shorten(sel.address, 10, 8), title:lbl, desc:'',
      riskLabel:t.risk[bk], riskStyle:'background:' + rm.bg + ';color:' + rm.color + ';border:1px solid ' + rm.color + '40;',
      gauge:ringGauge(sel.risk_score, rm.color), score:Math.round(sel.risk_score), scoreColor:rm.color,
      ctxRows:[
        {k:t.f.address, v:shorten(sel.address, 10, 8)},
        {k:t.f.txcount, v:num(sel.transaction_count)},
        {k:t.f.received, v:weiToEth(sel.total_received, 3) + ' ETH'},
        {k:t.f.sent, v:weiToEth(sel.total_sent, 3) + ' ETH'},
        {k:t.f.flagged, v:sel.is_flagged ? t.yes : t.no},
      ], fired:[], actions:[], hasActions:false, loadingCtx:false,
    };
  }
  // tx
  const x = sel; const st = TXSTAT[x.status] || TXSTAT.success;
  return {
    kind:TYPE.tx.label, id:' ' + shorten(x.tx_hash, 8, 6), title:'', desc:'',
    statusLabel:t.txStatus[x.status] || x.status, statusStyle:'background:' + st.b + ';color:' + st.c + ';',
    gauge:null, score:null,
    ctxRows:[
      {k:t.f.hash, v:shorten(x.tx_hash, 10, 8)},
      {k:t.f.sender, v:shorten(x.sender_address)},
      {k:t.f.receiver, v:shorten(x.receiver_address)},
      {k:t.f.amount, v:weiToEth(x.amount, 4) + ' ETH'},
      {k:t.f.block, v:num(x.block_number)},
      {k:t.f.time, v:fmtDate(Date.parse(x.transaction_timestamp))},
    ], fired:[], actions:[], hasActions:false, loadingCtx:false,
  };
}

export default function DetailDrawer({ t, selected, kind, detailData, onClose, onSetStatus }){
  if(!selected) return null;
  const d = detailVM(selected, kind, detailData, t);
  if(!d) return null;
  return h(React.Fragment, null,
    h('div', {onClick:onClose, style:css("position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:40;")}),
    h('div', {style:css("position:fixed;top:0;right:0;bottom:0;width:440px;max-width:94vw;background:var(--panel);border-left:1px solid var(--border);z-index:50;box-shadow:var(--shadow);display:flex;flex-direction:column;")},
      h('div', {style:css("display:flex;align-items:center;justify-content:space-between;padding:20px 22px;border-bottom:1px solid var(--border);flex-shrink:0;")},
        h('div', {style:css("display:flex;align-items:center;gap:10px;")},
          h('span', {style:css("font-size:10px;font-weight:700;padding:3px 8px;border-radius:6px;background:var(--accent-soft);color:var(--accent);font-family:'JetBrains Mono',monospace;")}, d.kind),
          h('span', {style:css("font-size:14px;font-weight:700;font-family:'JetBrains Mono',monospace;")}, d.id)),
        h('button', {onClick:onClose, style:css("width:34px;height:34px;border:1px solid var(--border);border-radius:9px;background:transparent;color:var(--muted);display:flex;align-items:center;justify-content:center;cursor:pointer;")}, icon('close', 18))),
      h('div', {style:css("flex:1;overflow:auto;padding:22px;")},
        h('div', {style:css("display:flex;align-items:center;gap:18px;margin-bottom:22px;")},
          d.gauge ? h('div', {style:css("position:relative;display:flex;align-items:center;justify-content:center;flex-shrink:0;")},
            d.gauge,
            h('div', {style:css("position:absolute;text-align:center;")},
              h('div', {style:css("font-size:26px;font-weight:800;font-family:'JetBrains Mono',monospace;color:" + d.scoreColor + ";")}, String(d.score)),
              h('div', {style:css("font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;")}, 'score'))) : null,
          h('div', {style:css("flex:1;min-width:0;")},
            d.title ? h('div', {style:css("font-size:16px;font-weight:700;line-height:1.35;margin-bottom:8px;")}, d.title) : null,
            d.desc ? h('div', {style:css("font-size:12.5px;color:var(--muted);line-height:1.5;margin-bottom:10px;")}, d.desc) : null,
            h('div', {style:css("display:flex;gap:6px;flex-wrap:wrap;")},
              d.riskLabel ? h('span', {style:css("font-size:11px;font-weight:700;padding:3px 10px;border-radius:7px;" + d.riskStyle)}, d.riskLabel) : null,
              d.statusLabel ? h('span', {style:css("font-size:11px;font-weight:600;padding:3px 10px;border-radius:7px;" + d.statusStyle)}, d.statusLabel) : null))),

        d.loadingCtx ? h('div', {style:css("font-size:12.5px;color:var(--muted);margin-bottom:18px;")}, 'Загрузка деталей…') : null,

        (d.fired && d.fired.length) ? h('div', {style:css("margin-bottom:22px;")},
          h('div', {style:css("font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin-bottom:10px;")}, t.detail.rules),
          h('div', {style:css("display:flex;flex-direction:column;gap:8px;")},
            d.fired.map((f, i) => h('div', {key:i, style:css("display:flex;align-items:center;gap:10px;padding:11px 14px;background:var(--card);border:1px solid var(--border);border-radius:11px;")},
              h('span', {style:css("flex:1;font-size:13px;")}, f.name),
              h('span', {style:css("font-size:13px;font-weight:800;font-family:'JetBrains Mono',monospace;color:var(--accent);")}, '+' + f.score))))) : null,

        (d.ctxRows && d.ctxRows.length) ? h('div', {style:css("margin-bottom:22px;")},
          h('div', {style:css("font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin-bottom:10px;")}, t.detail.context),
          h('div', {style:css("background:var(--card);border:1px solid var(--border);border-radius:13px;overflow:hidden;")},
            d.ctxRows.map((row, i) => h('div', {key:i, style:css("display:flex;align-items:center;gap:10px;padding:11px 14px;border-bottom:1px solid var(--border2);")},
              h('span', {style:css("font-size:12.5px;color:var(--muted);flex-shrink:0;width:130px;")}, row.k),
              h('span', {style:css("flex:1;text-align:right;font-size:12.5px;font-family:'JetBrains Mono',monospace;font-weight:600;word-break:break-all;")}, row.v))))) : null),

      d.hasActions ? h('div', {style:css("display:flex;gap:8px;padding:18px 22px;border-top:1px solid var(--border);flex-shrink:0;")},
        d.actions.map((ac, i) => h('button', {key:i, onClick:() => onSetStatus(ac.status),
          style:css("flex:1;border-radius:11px;padding:12px;font-size:13px;font-weight:700;font-family:inherit;cursor:pointer;border:1px solid var(--border);background:var(--card2);color:var(--text);transition:all .16s;")}, ac.label))) : null));
}
