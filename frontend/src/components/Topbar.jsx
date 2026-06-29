import { h, css } from '../lib/dom';
import { icon } from '../lib/icons';
import LangSwitch from './LangSwitch';

export default function Topbar({ t, lang, onLang, theme, onToggleTheme, q, onSearch, expanded, onToggleSidebar, user }){
  return h('div', {style:css("height:62px;flex-shrink:0;border-bottom:1px solid var(--border);background:var(--panel);display:flex;align-items:center;gap:14px;padding:0 20px;")},
    h('button', {onClick:onToggleSidebar,
      style:css("width:38px;height:38px;border:1px solid var(--border);border-radius:10px;background:transparent;color:var(--muted);display:flex;align-items:center;justify-content:center;cursor:pointer;flex-shrink:0;transition:all .18s;")},
      icon(expanded ? 'chevronLeft' : 'chevronRight', 18)),
    h('div', {style:css("flex:1;max-width:520px;display:flex;align-items:center;gap:10px;background:var(--card2);border:1px solid var(--border);border-radius:11px;padding:9px 14px;color:var(--muted);")},
      icon('search', 18),
      h('input', {value:q, onInput:e => onSearch(e.target.value), onChange:e => onSearch(e.target.value), placeholder:t.searchPh,
        style:css("flex:1;background:transparent;border:none;outline:none;color:var(--text);font-size:13.5px;font-family:inherit;")})),
    h('div', {style:css("flex:1;")}),
    h('div', {style:css("display:flex;gap:4px;background:var(--card2);border:1px solid var(--border);border-radius:10px;padding:3px;")}, LangSwitch({lang, onLang, small:true})),
    h('button', {onClick:onToggleTheme,
      style:css("width:38px;height:38px;border:1px solid var(--border);border-radius:10px;background:var(--card2);color:var(--muted);display:flex;align-items:center;justify-content:center;cursor:pointer;transition:all .18s;")},
      icon(theme === 'dark' ? 'sun' : 'moon', 18)),
    h('div', {style:css("width:38px;height:38px;border:1px solid var(--border);border-radius:10px;background:var(--card2);color:var(--muted);display:flex;align-items:center;justify-content:center;position:relative;")},
      icon('bell', 19),
      h('span', {style:css("position:absolute;top:8px;right:9px;width:6px;height:6px;border-radius:50%;background:#ff6f6f;")})),
    h('div', {style:css("display:flex;align-items:center;gap:9px;")},
      h('div', {style:css("width:38px;height:38px;border-radius:50%;background:var(--accent-soft);color:var(--accent);display:flex;align-items:center;justify-content:center;border:1px solid var(--border);flex-shrink:0;")}, icon('user', 18)),
      user ? h('span', {style:css("font-size:13px;font-weight:600;white-space:nowrap;max-width:160px;overflow:hidden;text-overflow:ellipsis;")}, ((user.first_name || '') + ' ' + (user.last_name || '')).trim() || user.username) : null));
}
