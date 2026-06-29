import { h } from './dom';

// SVG-графики дашборда и детали. Перенесены 1-в-1 из исходного дизайна.
export function areaChart(series, ht){
  const w = 620, pad = 6; ht = ht || 190;
  const max = Math.max(1, ...series); const n = series.length;
  const xs = i => pad + i * (w - 2 * pad) / (n - 1);
  const ys = v => ht - pad - (v / max) * (ht - 2 * pad - 12);
  let line = ''; series.forEach((v, i) => { line += (i ? 'L' : 'M') + xs(i).toFixed(1) + ' ' + ys(v).toFixed(1) + ' '; });
  const area = line + 'L' + xs(n - 1).toFixed(1) + ' ' + ht + ' L' + xs(0).toFixed(1) + ' ' + ht + ' Z';
  return h('svg', {viewBox:'0 0 ' + w + ' ' + ht, preserveAspectRatio:'none', style:{width:'100%', height:ht, display:'block'}},
    h('defs', null, h('linearGradient', {id:'tgrad', x1:0, y1:0, x2:0, y2:1},
      h('stop', {offset:'0%', stopColor:'var(--accent)', stopOpacity:0.34}),
      h('stop', {offset:'100%', stopColor:'var(--accent)', stopOpacity:0}))),
    h('path', {d:area, fill:'url(#tgrad)'}),
    h('path', {d:line, fill:'none', stroke:'var(--accent)', strokeWidth:2.5, strokeLinejoin:'round', strokeLinecap:'round'}));
}

export function barChart(items){
  const max = Math.max(1, ...items.map(i => i.value));
  return h('div', {style:{display:'flex', alignItems:'flex-end', gap:12, height:150, padding:'0 2px'}},
    items.map((it, i) => h('div', {key:i, style:{flex:1, display:'flex', flexDirection:'column', alignItems:'center', gap:8, height:'100%', justifyContent:'flex-end'}},
      h('div', {style:{fontSize:13, fontWeight:700, color:'var(--text)', fontFamily:'JetBrains Mono, monospace'}}, String(it.value)),
      h('div', {style:{width:'100%', maxWidth:30, height:Math.max(4, it.value / max * 100) + '%', background:it.color, borderRadius:'7px 7px 3px 3px', transition:'height .7s cubic-bezier(.2,.8,.2,1)'}}),
      h('div', {style:{fontSize:10.5, color:'var(--muted)', textAlign:'center', lineHeight:1.2, minHeight:24}}, it.label))));
}

export function donut(items, total){
  const r = 52, c = 2 * Math.PI * r, cx = 70, cy = 70; let off = 0;
  const segs = items.filter(i => i.value > 0).map((it, i) => {
    const len = (it.value / (total || 1)) * c;
    const el = h('circle', {key:i, cx:cx, cy:cy, r:r, fill:'none', stroke:it.color, strokeWidth:15, strokeDasharray:len.toFixed(2) + ' ' + (c - len).toFixed(2), strokeDashoffset:(-off).toFixed(2), transform:'rotate(-90 ' + cx + ' ' + cy + ')', style:{transition:'stroke-dasharray .7s ease'}});
    off += len; return el;
  });
  return h('svg', {width:140, height:140, viewBox:'0 0 140 140', style:{flexShrink:0}},
    h('circle', {cx:cx, cy:cy, r:r, fill:'none', stroke:'var(--border)', strokeWidth:15}), segs);
}

export function ringGauge(score, color){
  const r = 46, c = 2 * Math.PI * r; const len = (score / 100) * c;
  return h('svg', {width:120, height:120, viewBox:'0 0 120 120'},
    h('circle', {cx:60, cy:60, r:r, fill:'none', stroke:'var(--border)', strokeWidth:9}),
    h('circle', {cx:60, cy:60, r:r, fill:'none', stroke:color, strokeWidth:9, strokeLinecap:'round', strokeDasharray:len.toFixed(2) + ' ' + (c - len).toFixed(2), transform:'rotate(-90 60 60)', style:{transition:'stroke-dasharray .8s cubic-bezier(.2,.8,.2,1)'}}));
}

export function semiGauge(pct, color){
  const r = 70, c = Math.PI * r; const len = pct * c;
  return h('svg', {viewBox:'0 0 180 104', style:{width:'100%', maxWidth:230, display:'block', margin:'0 auto'}},
    h('path', {d:'M16 92 A74 74 0 0 1 164 92', fill:'none', stroke:'var(--border)', strokeWidth:15, strokeLinecap:'round'}),
    h('path', {d:'M16 92 A74 74 0 0 1 164 92', fill:'none', stroke:color, strokeWidth:15, strokeLinecap:'round', strokeDasharray:len.toFixed(2) + ' ' + (c - len).toFixed(2), style:{transition:'stroke-dasharray .9s cubic-bezier(.2,.8,.2,1)'}}));
}
