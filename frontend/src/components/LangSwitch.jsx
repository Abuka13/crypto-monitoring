import { h, css } from '../lib/dom';

const LANGS = [{k:'ru',l:'RU'},{k:'kk',l:'KK'},{k:'en',l:'EN'}];

// Переключатель языка (RU/KK/EN). small — компактный вариант для шапки.
export default function LangSwitch({ lang, onLang, small }){
  const pad = small ? '5px 10px' : '6px 12px';
  const fs = small ? '11.5px' : '12px';
  return LANGS.map(x => {
    const active = lang === x.k;
    const st = active ? 'background:var(--accent);color:#06201c;' : 'background:transparent;color:var(--muted);';
    return h('button', {key:x.k, onClick:() => onLang(x.k),
      style:css('border:none;border-radius:8px;padding:' + pad + ';font-size:' + fs + ';font-weight:700;font-family:inherit;cursor:pointer;transition:all .18s;' + st)}, x.l);
  });
}
