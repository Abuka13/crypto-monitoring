// Форматирование. wei хранится строкой и переводится в ETH через BigInt,
// чтобы не терять точность на больших числах.
export function weiToEth(weiStr, dp){
  dp = dp == null ? 3 : dp;
  try{
    const v = BigInt(weiStr); const base = 10n ** 18n;
    const whole = v / base; const frac = v % base;
    let fracStr = frac.toString().padStart(18, '0').slice(0, dp).replace(/0+$/, '');
    let wholeStr = whole.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
    return fracStr ? wholeStr + '.' + fracStr : wholeStr;
  }catch(e){ return '0'; }
}

export function shorten(s, a, b){
  a = a || 6; b = b || 4;
  if(!s) return '';
  return s.slice(0, a) + '…' + s.slice(-b);
}

export function fmtDate(ms){
  if(!ms) return '—';
  const d = new Date(ms); const p = n => (n < 10 ? '0' : '') + n;
  return p(d.getDate()) + '.' + p(d.getMonth() + 1) + '.' + String(d.getFullYear()).slice(2) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
}

export function num(n){ return (n == null ? 0 : n).toLocaleString('ru-RU'); }

export function riskBucket(score){ return score >= 70 ? 'high' : score >= 40 ? 'medium' : 'low'; }
