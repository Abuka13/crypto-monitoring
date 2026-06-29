// Агрегаты для дашборда — считаются на клиенте из уже загруженных алертов/кошельков
// (как в исходном дизайне).
export function computeStats(alerts, wallets){
  const now = Date.now();
  const s = {total:alerts.length, open:0, in_progress:0, closed:0, false_positive:0, high:0, medium:0, low:0, last24:0, flagged:0};
  alerts.forEach(x => {
    if(s[x.status] != null) s[x.status]++;
    if(s[x.level] != null) s[x.level]++;
    if(now - x._ts < 24 * 3600 * 1000) s.last24++;
  });
  s.flagged = wallets.filter(w => w.is_flagged).length;
  return s;
}

export function trendSeries(alerts){
  const days = 14; const now = Date.now(); const arr = new Array(days).fill(0);
  alerts.forEach(x => { const d = Math.floor((now - x._ts) / (24 * 3600 * 1000)); if(d >= 0 && d < days) arr[days - 1 - d]++; });
  return arr;
}
