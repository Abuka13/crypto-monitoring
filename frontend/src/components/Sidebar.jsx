import { h, css } from '../lib/dom';
import { icon } from '../lib/icons';

const NAV = ['dashboard','alerts','wallets','transactions','screen','graph','rules'];

export default function Sidebar({ t, screen, expanded, onNav, onLogout }){
  return h('div', {style:css("width:" + (expanded ? '224px' : '66px') + ";flex-shrink:0;background:var(--panel);border-right:1px solid var(--border);display:flex;flex-direction:column;padding:14px 0 16px;z-index:5;transition:width .22s cubic-bezier(.4,0,.2,1);overflow:hidden;")},
    h('div', {style:css("display:flex;align-items:center;gap:11px;padding:0 13px 16px;min-width:0;")},
      h('div', {style:css("width:40px;height:40px;border-radius:12px;background:var(--accent);color:#06201c;display:flex;align-items:center;justify-content:center;flex-shrink:0;")}, icon('shield', 22)),
      expanded ? h('div', {style:css("min-width:0;overflow:hidden;")},
        h('div', {style:css("font-size:15px;font-weight:800;letter-spacing:-.4px;white-space:nowrap;")}, t.appName),
        h('div', {style:css("font-size:10.5px;color:var(--muted);white-space:nowrap;line-height:1.4;margin-top:2px;")}, t.appSub)) : null),
    h('div', {style:css("display:flex;flex-direction:column;gap:3px;padding:0 10px;flex:1;")},
      NAV.map(id => {
        const active = screen === id;
        const st = active ? 'background:var(--accent-soft);color:var(--accent);border:1px solid var(--accent);' : 'background:transparent;color:var(--muted);border:1px solid transparent;';
        return h('button', {key:id, onClick:() => onNav(id), title:t.nav[id],
          style:css("display:flex;align-items:center;gap:11px;padding:10px 11px;border-radius:11px;cursor:pointer;font-size:13.5px;font-weight:600;font-family:inherit;width:100%;transition:all .18s;white-space:nowrap;overflow:hidden;min-width:0;" + st)},
          h('span', {style:css("flex-shrink:0;display:flex;")}, icon(id, 20)),
          expanded ? h('span', null, t.nav[id]) : null);
      })),
    expanded ? h('div', {style:css("display:flex;align-items:center;gap:8px;padding:10px 21px;border-top:1px solid var(--border);font-size:12px;color:var(--muted);margin-top:8px;")},
      h('span', {style:css("width:7px;height:7px;border-radius:50%;background:#34d399;animation:pulseDot 1.8s infinite;flex-shrink:0;")}),
      h('span', {style:css("white-space:nowrap;")}, t.systemsActive)) : null,
    h('div', {style:css("display:flex;justify-content:center;padding:0 10px;")},
      h('button', {onClick:onLogout, title:'Logout',
        style:css("width:42px;height:42px;border:none;border-radius:12px;background:transparent;color:var(--muted);display:flex;align-items:center;justify-content:center;cursor:pointer;transition:all .18s;")}, icon('logout', 20))));
}
