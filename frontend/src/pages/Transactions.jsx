import { h, css } from '../lib/dom';
import { icon } from '../lib/icons';
import { thStyle } from '../lib/ui';
import { txVM } from '../lib/viewmodels';

export default function Transactions({ t, txs, openTx, copy }){
  const rows = txs.map(x => txVM(x, {t, openTx, copy}));
  return h('div', {style:css("height:100%;display:flex;flex-direction:column;overflow:hidden;padding:24px;")},
    h('div', {style:css("margin-bottom:16px;")},
      h('div', {style:css("font-size:21px;font-weight:800;letter-spacing:-.5px;")}, t.nav.transactions),
      h('div', {style:css("font-size:12.5px;color:var(--muted);margin-top:2px;")},
        h('span', {style:css("font-family:'JetBrains Mono',monospace;font-weight:700;color:var(--text);")}, String(rows.length)), ' ', t.found)),
    h('div', {style:css("flex:1;min-height:0;background:var(--card);border:1px solid var(--border);border-radius:16px;overflow:auto;")},
      h('table', {style:css("width:100%;border-collapse:collapse;")},
        h('thead', null, h('tr', {style:css("position:sticky;top:0;z-index:2;background:var(--card);")},
          h('th', {style:thStyle('left')}, t.cols.hash), h('th', {style:thStyle()}, t.cols.sender),
          h('th', {style:thStyle()}, t.cols.receiver), h('th', {style:thStyle('right')}, t.cols.amount),
          h('th', {style:thStyle('right')}, t.cols.block), h('th', {style:thStyle('right')}, t.cols.time),
          h('th', {style:thStyle('center')}, t.cols.status))),
        h('tbody', null, rows.map((x, i) => h('tr', {key:i, onClick:x.onOpen, style:css("cursor:pointer;border-bottom:1px solid var(--border2);")},
          h('td', {style:css("padding:12px 16px;")},
            h('span', {style:css("display:inline-flex;align-items:center;gap:8px;")},
              h('span', {style:css("font-size:12.5px;font-family:'JetBrains Mono',monospace;font-weight:600;")}, x.short),
              h('button', {onClick:x.onCopy, style:css("border:none;background:transparent;color:var(--muted);cursor:pointer;display:flex;padding:2px;")}, icon('copy', 14)))),
          h('td', {style:css("padding:12px 8px;font-size:12.5px;font-family:'JetBrains Mono',monospace;color:var(--muted);")}, x.sender),
          h('td', {style:css("padding:12px 8px;font-size:12.5px;font-family:'JetBrains Mono',monospace;color:var(--muted);")}, x.receiver),
          h('td', {style:css("padding:12px 8px;text-align:right;font-size:13px;font-weight:700;font-family:'JetBrains Mono',monospace;")}, x.amount),
          h('td', {style:css("padding:12px 8px;text-align:right;font-size:12px;font-family:'JetBrains Mono',monospace;color:var(--muted);")}, x.block),
          h('td', {style:css("padding:12px 8px;text-align:right;font-size:12px;font-family:'JetBrains Mono',monospace;color:var(--muted);white-space:nowrap;")}, x.dateStr),
          h('td', {style:css("padding:12px 16px;text-align:center;")}, h('span', {style:css("font-size:11px;font-weight:600;padding:3px 9px;border-radius:7px;" + x.statusStyle)}, x.statusLabel))))))));
}
