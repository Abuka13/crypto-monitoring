import { h, css } from '../lib/dom';

// Ряд фильтр-чипов. items — дескрипторы из lib/ui.chip().
export default function FilterRow({ items }){
  return h('div', {style:css("display:flex;gap:6px;flex-wrap:wrap;")},
    items.map((c, i) => h('button', {key:i, onClick:c.onClick,
      style:css("border-radius:9px;padding:7px 13px;font-size:12.5px;font-family:inherit;cursor:pointer;transition:all .18s;" + c.style)}, c.label)));
}
