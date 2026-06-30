import { h, css } from '../lib/dom';
import { ruleVM } from '../lib/viewmodels';

export default function Rules({ t, rules, toggleRule }){
  const rows = rules.map(r => ruleVM(r, {toggleRule}));
  return h('div', {style:css("height:100%;display:flex;flex-direction:column;overflow:hidden;padding:24px;")},
    h('div', {style:css("margin-bottom:16px;")},
      h('div', {style:css("font-size:21px;font-weight:800;letter-spacing:-.5px;")}, t.rulesTitle),
      h('div', {style:css("font-size:12.5px;color:var(--muted);margin-top:4px;max-width:560px;line-height:1.5;")}, t.rulesSub)),
    h('div', {style:css("flex:1;min-height:0;overflow:auto;")},
      h('div', {style:css("display:flex;flex-direction:column;gap:10px;")},
        rows.map((r, i) => h('div', {key:i, style:css("background:var(--card);border:1px solid var(--border);border-radius:15px;padding:18px 20px;display:flex;align-items:center;gap:18px;")},
          h('div', {style:css("flex:1;min-width:0;")},
            h('div', {style:css("font-size:15px;font-weight:700;margin-bottom:3px;")}, r.name),
            h('div', {style:css("font-size:12.5px;color:var(--muted);line-height:1.5;")}, r.desc)),
          h('div', {style:css("text-align:center;flex-shrink:0;")},
            h('div', {style:css("font-size:22px;font-weight:800;font-family:'JetBrains Mono',monospace;color:var(--accent);")}, '+' + r.score),
            h('div', {style:css("font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;")}, t.cols.score)),
          h('button', {onClick:r.onToggle, style:css("width:42px;height:24px;border-radius:13px;border:none;cursor:pointer;position:relative;flex-shrink:0;transition:background .2s;" + r.toggleStyle)},
            h('span', {style:css("position:absolute;top:3px;left:3px;width:18px;height:18px;border-radius:50%;background:#fff;transition:transform .2s;box-shadow:0 1px 3px rgba(0,0,0,.3);" + r.knobStyle)})))))));
}
