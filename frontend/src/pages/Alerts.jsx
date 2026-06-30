import { h, css } from '../lib/dom';
import { chip, thStyle } from '../lib/ui';
import { alertVM } from '../lib/viewmodels';
import FilterRow from '../components/FilterRow';

// Фильтрация алертов (как в исходном getFilteredAlerts).
function filterAlerts(alerts, f){
  const ql = (f.q || '').trim().toLowerCase();
  return alerts.filter(a => {
    if(f.fRisk !== 'all' && a.level !== f.fRisk) return false;
    if(f.fStatus !== 'all' && a.status !== f.fStatus) return false;
    if(f.fType !== 'all' && a.target_type !== f.fType) return false;
    if(ql){ const hay = (('#' + a.id) + ' ' + (a.title || '') + ' ' + (a.description || '')).toLowerCase(); if(!hay.includes(ql)) return false; }
    return true;
  });
}

export default function Alerts({ t, alerts, fRisk, fStatus, fType, q, alertsView, onFilter, openAlert }){
  const filtered = filterAlerts(alerts, {fRisk, fStatus, fType, q});
  const rows = filtered.map(a => alertVM(a, {t, openAlert}));
  const riskFilters = [['all',t.all],['high',t.risk.high],['medium',t.risk.medium],['low',t.risk.low]].map(x => chip(x[1], fRisk === x[0], () => onFilter('fRisk', x[0])));
  const statusFilters = [['all',t.all],['open',t.status.open],['in_progress',t.status.in_progress],['closed',t.status.closed],['false_positive',t.status.false_positive]].map(x => chip(x[1], fStatus === x[0], () => onFilter('fStatus', x[0])));
  const typeFilters = [['all',t.all],['transaction',t.typeTx],['wallet',t.typeWlt]].map(x => chip(x[1], fType === x[0], () => onFilter('fType', x[0])));
  const viewTableChip = chip(t.view.table, alertsView === 'table', () => onFilter('alertsView', 'table'));
  const viewCardsChip = chip(t.view.cards, alertsView === 'cards', () => onFilter('alertsView', 'cards'));

  return h('div', {style:css("height:100%;display:flex;flex-direction:column;overflow:hidden;padding:24px;")},
    h('div', {style:css("display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;flex-wrap:wrap;gap:12px;")},
      h('div', null,
        h('div', {style:css("font-size:21px;font-weight:800;letter-spacing:-.5px;")}, t.nav.alerts),
        h('div', {style:css("font-size:12.5px;color:var(--muted);margin-top:2px;")},
          h('span', {style:css("font-family:'JetBrains Mono',monospace;font-weight:700;color:var(--text);")}, String(filtered.length)), ' ', t.found)),
      h('div', {style:css("display:flex;gap:6px;background:var(--card2);border:1px solid var(--border);border-radius:10px;padding:3px;")},
        h('button', {onClick:viewTableChip.onClick, style:css("border-radius:8px;padding:7px 14px;font-size:12.5px;font-family:inherit;cursor:pointer;transition:all .18s;" + viewTableChip.style)}, t.view.table),
        h('button', {onClick:viewCardsChip.onClick, style:css("border-radius:8px;padding:7px 14px;font-size:12.5px;font-family:inherit;cursor:pointer;transition:all .18s;" + viewCardsChip.style)}, t.view.cards))),
    h('div', {style:css("display:flex;flex-wrap:wrap;gap:18px;margin-bottom:16px;align-items:center;")},
      FilterRow({items:riskFilters}), FilterRow({items:statusFilters}), FilterRow({items:typeFilters})),

    alertsView === 'table' ?
      h('div', {style:css("flex:1;min-height:0;background:var(--card);border:1px solid var(--border);border-radius:16px;overflow:auto;")},
        h('table', {style:css("width:100%;border-collapse:collapse;")},
          h('thead', null, h('tr', {style:css("position:sticky;top:0;z-index:2;background:var(--card);")},
            h('th', {style:thStyle('left')}, t.cols.id), h('th', {style:thStyle()}, t.cols.type),
            h('th', {style:thStyle()}, t.cols.signal), h('th', {style:thStyle()}, t.cols.risk),
            h('th', {style:thStyle()}, t.cols.status), h('th', {style:thStyle('right')}, t.cols.score),
            h('th', {style:thStyle('right')}, t.cols.date))),
          h('tbody', null, rows.map((a, i) => h('tr', {key:i, onClick:a.onOpen, style:css("cursor:pointer;border-bottom:1px solid var(--border2);")},
            h('td', {style:css("padding:13px 16px;font-size:12.5px;font-family:'JetBrains Mono',monospace;font-weight:600;")},
              h('span', {style:css("display:inline-flex;align-items:center;gap:7px;")},
                a.isHigh ? h('span', {style:css("width:7px;height:7px;border-radius:50%;background:#ff6f6f;animation:pulseDot 1.4s infinite;")}) : null, a.id)),
            h('td', {style:css("padding:13px 8px;")}, h('span', {style:css("font-size:10px;font-weight:700;padding:3px 7px;border-radius:6px;" + a.typeStyle)}, a.typeLabel)),
            h('td', {style:css("padding:13px 8px;max-width:260px;")},
              h('div', {style:css("font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;")}, a.title),
              h('div', {style:css("font-size:11.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;")}, a.desc)),
            h('td', {style:css("padding:13px 8px;")}, h('span', {style:css("font-size:11px;font-weight:700;padding:3px 9px;border-radius:7px;" + a.riskStyle)}, a.riskLabel)),
            h('td', {style:css("padding:13px 8px;")}, h('span', {style:css("font-size:11px;font-weight:600;padding:3px 9px;border-radius:7px;" + a.statusStyle)}, a.statusLabel)),
            h('td', {style:css("padding:13px 8px;text-align:right;font-size:14px;font-weight:800;font-family:'JetBrains Mono',monospace;color:" + a.scoreColor + ";")}, String(a.score)),
            h('td', {style:css("padding:13px 16px;text-align:right;font-size:12px;color:var(--muted);font-family:'JetBrains Mono',monospace;white-space:nowrap;")}, a.dateStr))))))
    :
      h('div', {style:css("flex:1;min-height:0;overflow:auto;")},
        h('div', {style:css("display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px;padding-bottom:4px;")},
          rows.map((a, i) => h('div', {key:i, onClick:a.onOpen, style:css("background:var(--card);border:1px solid var(--border);border-radius:15px;padding:16px;cursor:pointer;transition:all .16s;")},
            h('div', {style:css("display:flex;align-items:center;justify-content:space-between;margin-bottom:11px;")},
              h('span', {style:css("font-size:10px;font-weight:700;padding:3px 7px;border-radius:6px;" + a.typeStyle)}, a.typeLabel),
              h('span', {style:css("font-size:11.5px;font-family:'JetBrains Mono',monospace;color:var(--muted);")}, a.id)),
            h('div', {style:css("font-size:14px;font-weight:700;margin-bottom:5px;")}, a.title),
            h('div', {style:css("font-size:12px;color:var(--muted);line-height:1.5;margin-bottom:14px;min-height:36px;")}, a.desc),
            h('div', {style:css("display:flex;align-items:center;justify-content:space-between;")},
              h('div', {style:css("display:flex;gap:6px;")},
                h('span', {style:css("font-size:11px;font-weight:700;padding:3px 9px;border-radius:7px;" + a.riskStyle)}, a.riskLabel),
                h('span', {style:css("font-size:11px;font-weight:600;padding:3px 9px;border-radius:7px;" + a.statusStyle)}, a.statusLabel)),
              h('span', {style:css("font-size:18px;font-weight:800;font-family:'JetBrains Mono',monospace;color:" + a.scoreColor + ";")}, String(a.score)))))))
  );
}
