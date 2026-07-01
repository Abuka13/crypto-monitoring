import { h, css } from '../lib/dom';
import { icon } from '../lib/icons';

// Список номеров страниц с окном вокруг текущей и многоточиями: 1 … 4 5 [6] 7 8 … 20
function buildPages(page, total){
  const win = 2;
  const out = [];
  let last = 0;
  for(let i = 1; i <= total; i++){
    if(i === 1 || i === total || (i >= page - win && i <= page + win)){
      if(last && i - last > 1) out.push('…');
      out.push(i); last = i;
    }
  }
  return out;
}

const btn = (extra) =>
  css("min-width:34px;height:34px;padding:0 9px;border-radius:9px;font-size:13px;font-weight:700;"
    + "font-family:inherit;display:flex;align-items:center;justify-content:center;transition:all .16s;" + extra);

// Нумерованная пагинация. Живёт под скролл-контейнером таблицы (данные скроллятся
// в одном контейнере, страницы переключаются здесь).
export default function Pagination({ t, page, total, pageSize, onPage, loading }){
  const pageCount = Math.max(1, Math.ceil((total || 0) / pageSize));
  if(pageCount <= 1) return null;
  const pages = buildPages(page, pageCount);
  const nav = (target, disabled, ic) =>
    h('button', {onClick:() => (!disabled && !loading) && onPage(target), disabled:disabled || loading,
      style:btn("border:1px solid var(--border);background:var(--card2);color:var(--muted);cursor:"
        + (disabled || loading ? 'default' : 'pointer') + ";opacity:" + (disabled ? '.4' : '1') + ";")}, icon(ic, 16));

  return h('div', {style:css("display:flex;align-items:center;justify-content:center;gap:6px;padding:14px 0 2px;flex-wrap:wrap;")},
    nav(page - 1, page <= 1, 'chevronLeft'),
    pages.map((p, i) => p === '…'
      ? h('span', {key:'e' + i, style:css("color:var(--muted2);padding:0 4px;font-size:13px;")}, '…')
      : h('button', {key:p, onClick:() => (p !== page && !loading) && onPage(p), disabled:loading,
          style:btn(p === page
            ? "border:1px solid transparent;background:var(--accent);color:#06201c;cursor:default;"
            : "border:1px solid var(--border);background:var(--card2);color:var(--text);cursor:pointer;")}, String(p))),
    nav(page + 1, page >= pageCount, 'chevronRight'),
    h('span', {style:css("margin-left:8px;font-size:12px;color:var(--muted);font-family:'JetBrains Mono',monospace;")},
      t.shown + ' ' + total));
}
