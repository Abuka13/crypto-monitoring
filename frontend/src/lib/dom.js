import React from 'react';

// Хелпер для верстки без JSX (как в исходном дизайне) — React.createElement.
export const h = React.createElement;

// Парсер inline-CSS строки -> объект стиля React.
// Позволяет переиспользовать стили дизайна как есть ("a:b;c:d").
export function css(str){
  const o = {};
  if(!str) return o;
  str.split(';').forEach(part => {
    const i = part.indexOf(':');
    if(i < 0) return;
    let k = part.slice(0, i).trim();
    let v = part.slice(i + 1).trim();
    if(!k) return;
    k = k.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
    o[k] = v;
  });
  return o;
}
