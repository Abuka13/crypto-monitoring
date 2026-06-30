import { h, css } from '../lib/dom';
import { areaChart, barChart, donut, semiGauge } from '../lib/charts';
import { computeStats, trendSeries } from '../lib/stats';
import { alertVM } from '../lib/viewmodels';

export default function Dashboard({ t, alerts, wallets, openAlert }){
  const stats = computeStats(alerts, wallets);
  const statCards = [
    {label:t.stats.total, value:stats.total},
    {label:t.stats.open, value:stats.open},
    {label:t.stats.in_progress, value:stats.in_progress},
    {label:t.stats.closed, value:stats.closed},
    {label:t.stats.false_positive, value:stats.false_positive},
    {label:t.stats.last24, value:stats.last24},
  ];
  const riskItems = [
    {label:t.risk.high, value:stats.high, color:'#ff6f6f'},
    {label:t.risk.medium, value:stats.medium, color:'#f5b54a'},
    {label:t.risk.low, value:stats.low, color:'#34d399'},
  ];
  const riskTotal = stats.high + stats.medium + stats.low;
  const statusBarItems = [
    {label:t.status.open, value:stats.open, color:'#f5b54a'},
    {label:t.status.in_progress, value:stats.in_progress, color:'#5fded0'},
    {label:t.status.closed, value:stats.closed, color:'#34d399'},
    {label:t.status.false_positive, value:stats.false_positive, color:'#9aa3b2'},
  ];
  const closedPct = stats.total ? (stats.closed + stats.false_positive) / stats.total : 0;
  const recent = alerts.slice(0, 8).map(a => alertVM(a, {t, openAlert}));

  return h('div', {style:css("height:100%;overflow-y:auto;overflow-x:hidden;padding:24px;")},
    h('div', {style:css("display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));gap:14px;margin-bottom:16px;")},
      statCards.map((c, i) => h('div', {key:i, style:css("background:var(--card);border:1px solid var(--border);border-radius:16px;padding:18px 18px 16px;")},
        h('div', {style:css("font-size:12px;color:var(--muted);font-weight:600;margin-bottom:10px;")}, c.label),
        h('div', {style:css("font-size:30px;font-weight:800;font-family:'JetBrains Mono',monospace;letter-spacing:-1px;color:var(--text);")}, String(c.value))))),

    h('div', {style:css("display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr);gap:14px;margin-bottom:16px;")},
      h('div', {style:css("background:var(--card);border:1px solid var(--border);border-radius:18px;padding:20px;")},
        h('div', {style:css("display:flex;align-items:baseline;justify-content:space-between;margin-bottom:14px;")},
          h('div', {style:css("font-size:15px;font-weight:700;")}, t.dash.trend),
          h('div', {style:css("font-size:12px;color:var(--muted);")}, t.dash.trendSub)),
        areaChart(trendSeries(alerts), 190)),
      h('div', {style:css("background:var(--card);border:1px solid var(--border);border-radius:18px;padding:20px;")},
        h('div', {style:css("font-size:15px;font-weight:700;margin-bottom:10px;")}, t.dash.riskDist),
        h('div', {style:css("display:flex;align-items:center;gap:16px;")},
          h('div', {style:css("position:relative;display:flex;align-items:center;justify-content:center;")},
            donut(riskItems, riskTotal),
            h('div', {style:css("position:absolute;text-align:center;")},
              h('div', {style:css("font-size:24px;font-weight:800;font-family:'JetBrains Mono',monospace;")}, String(riskTotal)))),
          h('div', {style:css("display:flex;flex-direction:column;gap:9px;flex:1;")},
            riskItems.map((r, i) => h('div', {key:i, style:css("display:flex;align-items:center;gap:8px;font-size:13px;")},
              h('span', {style:css("width:9px;height:9px;border-radius:3px;background:" + r.color + ";")}),
              h('span', {style:css("color:var(--muted);flex:1;")}, r.label),
              h('span', {style:css("font-weight:700;font-family:'JetBrains Mono',monospace;")}, String(r.value)))),
            h('div', {style:css("display:flex;align-items:center;gap:8px;font-size:13px;border-top:1px solid var(--border);padding-top:9px;margin-top:2px;")},
              h('span', {style:css("color:var(--muted);flex:1;")}, t.dash.flagged),
              h('span', {style:css("font-weight:700;font-family:'JetBrains Mono',monospace;color:#ff6f6f;")}, String(stats.flagged))))))),

    h('div', {style:css("display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr);gap:14px;")},
      h('div', {style:css("background:var(--card);border:1px solid var(--border);border-radius:18px;padding:20px;display:flex;flex-direction:column;min-height:0;")},
        h('div', {style:css("font-size:15px;font-weight:700;margin-bottom:12px;")}, t.dash.recent),
        h('div', {style:css("max-height:330px;overflow:auto;display:flex;flex-direction:column;gap:8px;padding-right:4px;")},
          recent.map((a, i) => h('div', {key:i, onClick:a.onOpen, style:css("display:flex;align-items:center;gap:12px;padding:11px 12px;border-radius:12px;background:var(--card2);border:1px solid var(--border2);cursor:pointer;transition:all .16s;")},
            h('span', {style:css("font-size:10px;font-weight:700;padding:3px 7px;border-radius:6px;" + a.typeStyle)}, a.typeLabel),
            h('div', {style:css("flex:1;min-width:0;")},
              h('div', {style:css("font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;")}, a.title),
              h('div', {style:css("font-size:11px;color:var(--muted);font-family:'JetBrains Mono',monospace;")}, a.id)),
            h('span', {style:css("font-size:11px;font-weight:700;padding:3px 9px;border-radius:7px;" + a.riskStyle)}, a.riskLabel),
            h('span', {style:css("font-size:13px;font-weight:700;font-family:'JetBrains Mono',monospace;color:" + a.scoreColor + ";width:30px;text-align:right;")}, String(a.score)))))),
      h('div', {style:css("display:flex;flex-direction:column;gap:14px;")},
        h('div', {style:css("background:var(--card);border:1px solid var(--border);border-radius:18px;padding:20px;")},
          h('div', {style:css("font-size:15px;font-weight:700;margin-bottom:8px;")}, t.dash.byStatus),
          barChart(statusBarItems)),
        h('div', {style:css("background:var(--card);border:1px solid var(--border);border-radius:18px;padding:20px;text-align:center;")},
          h('div', {style:css("font-size:15px;font-weight:700;margin-bottom:6px;text-align:left;")}, t.dash.resolveRate),
          h('div', {style:css("position:relative;")},
            semiGauge(closedPct, 'var(--accent)'),
            h('div', {style:css("position:absolute;bottom:6px;left:0;right:0;font-size:26px;font-weight:800;font-family:'JetBrains Mono',monospace;color:var(--accent);")}, Math.round(closedPct * 100) + '%'))))));
}
