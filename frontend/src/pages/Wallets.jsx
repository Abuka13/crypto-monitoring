import { h, css } from '../lib/dom';
import { icon } from '../lib/icons';
import { chip, thStyle } from '../lib/ui';
import { riskBucket } from '../lib/format';
import { walletVM } from '../lib/viewmodels';
import FilterRow from '../components/FilterRow';

export default function Wallets({ t, wallets, wRisk, wFlag, onFilter, openWallet, copy }){
  const filtered = wallets.filter(w => {
    if(wRisk !== 'all' && riskBucket(w.risk_score) !== wRisk) return false;
    if(wFlag === 'flagged' && !w.is_flagged) return false;
    return true;
  });
  const rows = filtered.map(w => walletVM(w, {t, openWallet, copy}));
  const wRiskFilters = [['all',t.all],['high',t.risk.high],['medium',t.risk.medium],['low',t.risk.low]].map(x => chip(x[1], wRisk === x[0], () => onFilter('wRisk', x[0])));
  const wFlagFilters = [['all',t.all],['flagged',t.onlyFlagged]].map(x => chip(x[1], wFlag === x[0], () => onFilter('wFlag', x[0])));

  return h('div', {style:css("height:100%;display:flex;flex-direction:column;overflow:hidden;padding:24px;")},
    h('div', {style:css("margin-bottom:16px;")},
      h('div', {style:css("font-size:21px;font-weight:800;letter-spacing:-.5px;")}, t.nav.wallets),
      h('div', {style:css("font-size:12.5px;color:var(--muted);margin-top:2px;")},
        h('span', {style:css("font-family:'JetBrains Mono',monospace;font-weight:700;color:var(--text);")}, String(rows.length)), ' ', t.found)),
    h('div', {style:css("display:flex;flex-wrap:wrap;gap:18px;margin-bottom:16px;")}, FilterRow({items:wRiskFilters}), FilterRow({items:wFlagFilters})),
    h('div', {style:css("flex:1;min-height:0;background:var(--card);border:1px solid var(--border);border-radius:16px;overflow:auto;")},
      h('table', {style:css("width:100%;border-collapse:collapse;")},
        h('thead', null, h('tr', {style:css("position:sticky;top:0;z-index:2;background:var(--card);")},
          h('th', {style:thStyle('left')}, t.cols.address), h('th', {style:thStyle()}, t.cols.label),
          h('th', {style:thStyle('right')}, t.cols.txcount), h('th', {style:thStyle('right')}, t.cols.received),
          h('th', {style:thStyle('right')}, t.cols.sent), h('th', {style:thStyle('right')}, t.cols.riskscore),
          h('th', {style:thStyle('center')}, t.cols.flag))),
        h('tbody', null, rows.map((w, i) => h('tr', {key:i, onClick:w.onOpen, style:css("cursor:pointer;border-bottom:1px solid var(--border2);")},
          h('td', {style:css("padding:12px 16px;")},
            h('span', {style:css("display:inline-flex;align-items:center;gap:8px;")},
              h('span', {style:css("font-size:12.5px;font-family:'JetBrains Mono',monospace;font-weight:600;")}, w.short),
              h('button', {onClick:w.onCopy, style:css("border:none;background:transparent;color:var(--muted);cursor:pointer;display:flex;padding:2px;")}, icon('copy', 14)))),
          h('td', {style:css("padding:12px 8px;")}, h('span', {style:css("font-size:11px;font-weight:600;padding:3px 9px;border-radius:7px;" + w.labelStyle)}, w.label)),
          h('td', {style:css("padding:12px 8px;text-align:right;font-size:12.5px;font-family:'JetBrains Mono',monospace;")}, w.txCount),
          h('td', {style:css("padding:12px 8px;text-align:right;font-size:12.5px;font-family:'JetBrains Mono',monospace;")}, w.received),
          h('td', {style:css("padding:12px 8px;text-align:right;font-size:12.5px;font-family:'JetBrains Mono',monospace;color:var(--muted);")}, w.sent),
          h('td', {style:css("padding:12px 8px;text-align:right;font-size:14px;font-weight:800;font-family:'JetBrains Mono',monospace;color:" + w.riskColor + ";")}, String(w.risk)),
          h('td', {style:css("padding:12px 16px;text-align:center;")}, w.flagged ? h('span', {style:css("color:#ff6f6f;display:inline-flex;")}, icon('flag', 15)) : null)))))));
}
