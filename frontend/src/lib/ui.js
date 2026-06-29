import { css } from './dom';

// Дескриптор фильтр-чипа (label + активность + обработчик + стиль).
export function chip(label, active, onClick){
  return {
    label, active, onClick,
    style: active
      ? 'background:var(--accent);color:#06201c;border:1px solid transparent;font-weight:700;'
      : 'background:transparent;color:var(--muted);border:1px solid var(--border);',
  };
}

// Стиль ячейки заголовка таблицы.
export function thStyle(align){
  return css('text-align:' + (align || 'left') + ';padding:13px 8px;font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid var(--border);');
}
