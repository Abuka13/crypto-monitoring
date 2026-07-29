import React from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { h, css } from '../lib/dom';
import { icon } from '../lib/icons';
import { RISK } from '../lib/meta';
import { weiToEth, shorten, num } from '../lib/format';

// Цвет узла по уровню риска — та же светофорная схема, что и во всём интерфейсе.
const LEVEL_KEY = {LOW:'low', MEDIUM:'medium', HIGH:'high', CRITICAL:'critical'};
const nodeColor = (n) => (RISK[LEVEL_KEY[n.risk_level] || 'low'] || RISK.low).color;

// Помеченные адреса рисуем иначе: миксер/санкции/мошенник — ромб, биржа — квадрат.
const SPECIAL = {mixer:'diamond', sanctioned:'diamond', fraud:'diamond', exchange:'square'};
const LABEL_RING = {mixer:'#c05bff', sanctioned:'#ff6f6f', fraud:'#ff6f6f', exchange:'#5fded0'};

const RADIUS = {center: 11, d1: 7, d2: 5};
const nodeRadius = (n) => n.is_center ? RADIUS.center : (n.depth >= 2 ? RADIUS.d2 : RADIUS.d1);

// Суммарный поток по ребру — BigInt, чтобы не терять точность на больших wei.
function edgeWeight(edges){
  let max = 1n;
  edges.forEach(e => { try{ const v = BigInt(e.total_amount); if(v > max) max = v; }catch(_){} });
  return (amount) => {
    try{
      const v = BigInt(amount);
      // Толщина 0.6..4 — логарифмически, иначе один крупный перевод «съедает» шкалу.
      const ratio = Number((v * 1000n) / max) / 1000;
      return 0.6 + 3.4 * Math.sqrt(Math.max(0, Math.min(1, ratio)));
    }catch(_){ return 0.6; }
  };
}

// Рисуем узел на canvas: форма по метке, цвет по риску, обводка у центра.
function drawNode(node, ctx, globalScale, t){
  const r = nodeRadius(node);
  const color = nodeColor(node);
  const shape = SPECIAL[node.label];

  ctx.save();
  if(node.is_center){
    ctx.beginPath();
    ctx.arc(node.x, node.y, r + 5, 0, 2 * Math.PI);
    ctx.strokeStyle = color;
    ctx.globalAlpha = 0.45;
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  ctx.beginPath();
  if(shape === 'diamond'){
    ctx.moveTo(node.x, node.y - r * 1.3); ctx.lineTo(node.x + r * 1.3, node.y);
    ctx.lineTo(node.x, node.y + r * 1.3); ctx.lineTo(node.x - r * 1.3, node.y);
    ctx.closePath();
  } else if(shape === 'square'){
    ctx.rect(node.x - r, node.y - r, r * 2, r * 2);
  } else {
    ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
  }
  ctx.fillStyle = color;
  ctx.fill();
  if(shape){
    ctx.strokeStyle = LABEL_RING[node.label] || color;
    ctx.lineWidth = 2;
    ctx.stroke();
  }
  ctx.restore();

  // Подписи прячем на сильном отдалении, иначе холст превращается в кашу.
  if(globalScale >= 0.7){
    const fontSize = Math.max(9, 11 / Math.max(globalScale, 1));
    ctx.font = `600 ${fontSize}px 'JetBrains Mono', monospace`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillStyle = node.__labelColor || '#8b93a7';
    ctx.fillText(shorten(node.address, 6, 4), node.x, node.y + r + 3);
    if(node.label){
      ctx.font = `700 ${fontSize - 1}px 'Manrope', sans-serif`;
      ctx.fillStyle = LABEL_RING[node.label] || color;
      ctx.fillText(node.__labelText || node.label, node.x, node.y + r + 3 + fontSize + 1);
    }
  }
}

export default class GraphFlows extends React.Component {
  constructor(props){
    super(props);
    this.state = {
      address: props.initialAddress || '',
      depth: 1,
      data: null,          // {nodes, links}
      meta: null,          // {truncated, total_neighbors, shown_neighbors, center_id}
      loading: false,
      error: '',
      selected: null,
      hover: null,
      expanded: {},        // id -> true (какие узлы уже раскрывали)
    };
    this.fgRef = React.createRef();
    this._wrap = React.createRef();
    this.state.size = {w: 800, h: 600};
  }

  componentDidMount(){
    this._resize = () => {
      const el = this._wrap.current;
      if(el) this.setState({size:{w: el.clientWidth, h: el.clientHeight}});
    };
    this._resize();
    window.addEventListener('resize', this._resize);
    if(this.props.initialAddress) this.build(this.props.initialAddress);
  }
  componentWillUnmount(){ window.removeEventListener('resize', this._resize); }

  // Внешний переход «Показать связи» — перестроить граф на новый адрес.
  componentDidUpdate(prev){
    if(this.props.initialAddress && this.props.initialAddress !== prev.initialAddress){
      this.setState({address:this.props.initialAddress}, () => this.build(this.props.initialAddress));
    }
  }

  _toGraph(payload){
    const nodes = payload.nodes.map(n => Object.assign({}, n));
    const links = payload.edges.map(e => Object.assign({}, e));
    return {nodes, links};
  }

  async build(addr, depth){
    const address = (addr != null ? addr : this.state.address).trim();
    if(!address) return;
    const d = depth != null ? depth : this.state.depth;
    this.setState({loading:true, error:'', selected:null});
    try{
      const payload = await this.props.fetchGraph({address, depth:d, limit:80});
      this.setState({
        data: this._toGraph(payload),
        meta: payload,
        expanded: {[payload.center_id]: true},
        loading: false,
      }, () => setTimeout(() => this.fit(), 350));
    }catch(e){
      this.setState({loading:false, data:null, meta:null,
        error: this.props.t.graph.notFound});
    }
  }

  // Клик по узлу: догрузить его соседей и влить в текущий вид (не перестраивая всё).
  async expand(node){
    if(this.state.expanded[node.id]) { this.setState({selected:node}); return; }
    this.setState({selected:node, loading:true});
    try{
      const payload = await this.props.fetchGraph({wallet_id:node.id, depth:1, limit:40});
      const cur = this.state.data;
      const byId = new Map(cur.nodes.map(n => [n.id, n]));
      let added = 0;
      payload.nodes.forEach(n => {
        if(byId.has(n.id)) return;
        // Новые узлы появляются рядом с раскрытым — граф не «взрывается».
        byId.set(n.id, Object.assign({}, n, {
          is_center:false, depth:(node.depth || 0) + 1,
          x:node.x + (Math.random() - 0.5) * 40, y:node.y + (Math.random() - 0.5) * 40,
        }));
        added++;
      });
      const seen = new Set(cur.links.map(l => this._linkKey(l)));
      const links = cur.links.slice();
      payload.edges.forEach(e => {
        if(seen.has(this._linkKey(e))) return;
        if(!byId.has(e.source) || !byId.has(e.target)) return;
        seen.add(this._linkKey(e));
        links.push(Object.assign({}, e));
      });
      this.setState({
        data:{nodes:[...byId.values()], links},
        expanded:Object.assign({}, this.state.expanded, {[node.id]:true}),
        loading:false,
      });
      this.props.onToast(added ? this.props.t.graph.expanded : this.props.t.graph.noNewLinks);
    }catch(e){
      this.setState({loading:false});
    }
  }

  _linkKey(l){
    const s = typeof l.source === 'object' ? l.source.id : l.source;
    const tg = typeof l.target === 'object' ? l.target.id : l.target;
    return s + '>' + tg;
  }

  fit(){ if(this.fgRef.current) this.fgRef.current.zoomToFit(500, 60); }

  // Суммарные потоки выбранного узла (для боковой панели).
  _flows(nodeId){
    const links = (this.state.data && this.state.data.links) || [];
    let inW = 0n, outW = 0n;
    links.forEach(l => {
      const s = typeof l.source === 'object' ? l.source.id : l.source;
      const tg = typeof l.target === 'object' ? l.target.id : l.target;
      try{
        const v = BigInt(l.total_amount);
        if(tg === nodeId) inW += v;
        if(s === nodeId) outW += v;
      }catch(_){}
    });
    return {inW:inW.toString(), outW:outW.toString(), total:(inW + outW).toString()};
  }

  render(){
    const t = this.props.t;
    const s = this.state;
    const g = t.graph;
    // Шкала толщины рёбер пересчитывается на текущем наборе связей.
    const widthOf = s.data ? edgeWeight(s.data.links) : () => 1;

    return h('div', {style:css("height:100%;display:flex;flex-direction:column;overflow:hidden;padding:24px;")},
      // ---- Заголовок + поиск ----
      h('div', {style:css("margin-bottom:14px;flex-shrink:0;")},
        h('div', {style:css("font-size:21px;font-weight:800;letter-spacing:-.5px;")}, g.title),
        h('div', {style:css("font-size:12.5px;color:var(--muted);margin-top:2px;")}, g.sub)),

      h('div', {style:css("display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap;align-items:center;flex-shrink:0;")},
        h('div', {style:css("position:relative;flex:1;min-width:260px;max-width:520px;")},
          h('span', {style:css("position:absolute;left:13px;top:50%;transform:translateY(-50%);color:var(--muted);display:flex;")}, icon('search', 16)),
          h('input', {
            value:s.address, placeholder:g.addrPh,
            onChange:e => this.setState({address:e.target.value, error:''}),
            onKeyDown:e => { if(e.key === 'Enter') this.build(); },
            style:css("width:100%;padding:11px 14px 11px 38px;border-radius:11px;border:1px solid var(--border);background:var(--card);color:var(--text);font-size:13px;font-family:'JetBrains Mono',monospace;outline:none;transition:border-color .18s;"),
          })),
        h('button', {onClick:() => this.build(),
          style:css("padding:11px 18px;border-radius:11px;border:none;background:var(--accent);color:#06201c;font-size:13px;font-weight:700;font-family:inherit;cursor:pointer;transition:all .18s;")}, g.build),

        // Глубина 1/2
        h('div', {style:css("display:flex;align-items:center;gap:7px;margin-left:4px;")},
          h('span', {style:css("font-size:12px;color:var(--muted);")}, g.depth),
          [1, 2].map(d => h('button', {key:d, onClick:() => this.setState({depth:d}, () => s.meta && this.build(null, d)),
            style:css("width:34px;height:34px;border-radius:9px;font-size:12.5px;font-weight:700;font-family:inherit;cursor:pointer;transition:all .18s;" +
              (s.depth === d ? "background:var(--accent);color:#06201c;border:1px solid transparent;"
                             : "background:transparent;color:var(--muted);border:1px solid var(--border);"))}, String(d)))),

        s.meta ? h(React.Fragment, null,
          h('button', {onClick:() => this.fit(), title:g.center,
            style:css("width:36px;height:36px;border-radius:10px;border:1px solid var(--border);background:var(--card);color:var(--muted);display:flex;align-items:center;justify-content:center;cursor:pointer;transition:all .18s;")}, icon('target', 17)),
          h('button', {onClick:() => this.build(), title:g.reset,
            style:css("padding:0 14px;height:36px;border-radius:10px;border:1px solid var(--border);background:var(--card);color:var(--muted);font-size:12.5px;font-weight:600;font-family:inherit;cursor:pointer;transition:all .18s;")}, g.reset)) : null),

      // ---- Полоса статуса: счётчики + усечение ----
      s.meta ? h('div', {style:css("display:flex;gap:14px;flex-wrap:wrap;align-items:center;margin-bottom:12px;font-size:12px;color:var(--muted);flex-shrink:0;")},
        h('span', null,
          h('b', {style:css("color:var(--text);font-family:'JetBrains Mono',monospace;")}, String(s.data ? s.data.nodes.length : 0)), ' ' + g.nodes),
        h('span', null,
          h('b', {style:css("color:var(--text);font-family:'JetBrains Mono',monospace;")}, String(s.data ? s.data.links.length : 0)), ' ' + g.edges),
        s.meta.truncated ? h('span', {style:css("padding:4px 11px;border-radius:8px;background:rgba(245,170,60,.14);color:#f5b54a;font-weight:600;")},
          g.truncated.replace('{shown}', num(s.meta.shown_neighbors)).replace('{total}', num(s.meta.total_neighbors))) : null,
        h('span', {style:css("margin-left:auto;font-size:11.5px;opacity:.75;")}, g.hint)) : null,

      // ---- Холст + боковая панель ----
      h('div', {style:css("flex:1;min-height:0;display:flex;gap:14px;")},
        h('div', {ref:this._wrap, style:css("flex:1;min-width:0;position:relative;background:var(--card);border:1px solid var(--border);border-radius:16px;overflow:hidden;")},
          s.error ? this._msg(s.error) :
          (!s.data && !s.loading) ? this._msg(g.empty) : null,

          s.data ? h(ForceGraph2D, {
            ref:this.fgRef,
            graphData:s.data,
            width:s.size.w, height:s.size.h,
            backgroundColor:'rgba(0,0,0,0)',
            nodeRelSize:6,
            nodeId:'id',
            nodeLabel:() => '',           // свой тултип (ниже), нативный отключаем
            nodeCanvasObject:(n, ctx, scale) => drawNode(n, ctx, scale, t),
            nodePointerAreaPaint:(n, color, ctx) => {
              ctx.fillStyle = color;
              ctx.beginPath();
              ctx.arc(n.x, n.y, nodeRadius(n) + 4, 0, 2 * Math.PI);
              ctx.fill();
            },
            linkColor:() => 'rgba(140,150,175,.32)',
            linkWidth:(l) => widthOf(l.total_amount),
            linkDirectionalArrowLength:4.5,
            linkDirectionalArrowRelPos:1,
            linkCurvature:0.06,
            cooldownTicks:80,
            d3VelocityDecay:0.32,
            onNodeClick:(n) => this.expand(n),
            onNodeRightClick:(n) => this.build(n.address),
            onNodeHover:(n) => this.setState({hover:n || null}),
            onBackgroundClick:() => this.setState({selected:null}),
          }) : null,

          // Тултип при наведении
          s.hover ? this._tooltip(s.hover, t) : null,

          s.loading ? h('div', {style:css("position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.28);backdrop-filter:blur(2px);font-size:13px;color:var(--text);")},
            h('div', {style:css("padding:12px 20px;border-radius:12px;background:var(--panel);border:1px solid var(--border);font-weight:600;")}, g.loading)) : null,

          // Легенда
          s.data ? this._legend(t) : null),

        // Боковая панель выбранного узла
        s.selected ? this._panel(s.selected, t) : null));
  }

  _msg(text){
    return h('div', {style:css("position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:13.5px;text-align:center;padding:28px;")}, text);
  }

  _tooltip(n, t){
    const g = t.graph;
    const f = this._flows(n.id);
    const rk = LEVEL_KEY[n.risk_level] || 'low';
    return h('div', {style:css("position:absolute;left:14px;top:14px;z-index:6;pointer-events:none;background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:12px 14px;box-shadow:var(--shadow);max-width:290px;animation:fadeIn .16s ease;")},
      h('div', {style:css("font-size:12px;font-family:'JetBrains Mono',monospace;font-weight:700;margin-bottom:7px;word-break:break-all;")}, shorten(n.address, 12, 8)),
      h('div', {style:css("display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px;")},
        h('span', {style:css("font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:6px;background:" + RISK[rk].bg + ";color:" + RISK[rk].color + ";")}, t.risk[rk]),
        n.label ? h('span', {style:css("font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:6px;background:var(--card2);color:" + (LABEL_RING[n.label] || 'var(--muted)') + ";")}, t.labels[n.label] || n.label) : null),
      h('div', {style:css("font-size:11.5px;color:var(--muted);line-height:1.7;")},
        h('div', null, t.f.txcount + ': ' + num(n.tx_count)),
        h('div', null, g.inflow + ': ' + weiToEth(f.inW, 4) + ' ETH'),
        h('div', null, g.outflow + ': ' + weiToEth(f.outW, 4) + ' ETH'),
        n.graph_score != null ? h('div', null, t.f.graphScore + ': ' + Math.round(n.graph_score)) : null));
  }

  _legend(t){
    const g = t.graph;
    const item = (dot, text) => h('div', {style:css("display:flex;align-items:center;gap:7px;")}, dot,
      h('span', {style:css("font-size:10.5px;color:var(--muted);")}, text));
    const dot = (color, shape) => h('span', {style:css("width:10px;height:10px;flex-shrink:0;background:" + color + ";" +
      (shape === 'diamond' ? "transform:rotate(45deg);" : shape === 'square' ? "" : "border-radius:50%;"))});
    return h('div', {style:css("position:absolute;right:14px;bottom:14px;z-index:5;background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:11px 13px;box-shadow:var(--shadow);")},
      h('div', {style:css("font-size:10px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin-bottom:8px;")}, g.legend),
      h('div', {style:css("display:flex;flex-direction:column;gap:5px;")},
        item(dot(RISK.low.color), t.risk.low),
        item(dot(RISK.medium.color), t.risk.medium),
        item(dot(RISK.high.color), t.risk.high),
        item(dot(RISK.critical.color), t.risk.critical),
        h('div', {style:css("height:1px;background:var(--border);margin:3px 0;")}),
        item(dot(LABEL_RING.mixer, 'diamond'), t.labels.mixer + ' / ' + t.labels.sanctioned),
        item(dot(LABEL_RING.exchange, 'square'), t.labels.exchange),
        h('div', {style:css("font-size:10px;color:var(--muted);opacity:.8;margin-top:2px;")}, g.legendEdge)));
  }

  _panel(n, t){
    const g = t.graph;
    const f = this._flows(n.id);
    const rk = LEVEL_KEY[n.risk_level] || 'low';
    const row = (k, v) => h('div', {style:css("display:flex;justify-content:space-between;gap:10px;padding:8px 0;border-bottom:1px solid var(--border2);")},
      h('span', {style:css("font-size:12px;color:var(--muted);")}, k),
      h('span', {style:css("font-size:12px;font-family:'JetBrains Mono',monospace;font-weight:600;text-align:right;")}, v));
    const btn = (label, onClick, primary) => h('button', {onClick,
      style:css("width:100%;padding:10px;border-radius:10px;font-size:12.5px;font-weight:700;font-family:inherit;cursor:pointer;transition:all .18s;margin-top:8px;" +
        (primary ? "background:var(--accent);color:#06201c;border:none;"
                 : "background:var(--card2);color:var(--text);border:1px solid var(--border);"))}, label);

    return h('div', {style:css("width:280px;flex-shrink:0;background:var(--card);border:1px solid var(--border);border-radius:16px;padding:16px;overflow:auto;animation:fadeIn .2s ease;")},
      h('div', {style:css("font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin-bottom:10px;")}, g.selected),
      h('div', {style:css("display:flex;align-items:center;gap:8px;margin-bottom:10px;")},
        h('span', {style:css("font-size:12.5px;font-family:'JetBrains Mono',monospace;font-weight:700;word-break:break-all;flex:1;")}, shorten(n.address, 10, 8)),
        h('button', {onClick:() => this.props.copy(n.address),
          style:css("border:none;background:transparent;color:var(--muted);cursor:pointer;display:flex;padding:2px;flex-shrink:0;")}, icon('copy', 14))),
      h('div', {style:css("display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px;")},
        h('span', {style:css("font-size:11px;font-weight:700;padding:3px 9px;border-radius:7px;background:" + RISK[rk].bg + ";color:" + RISK[rk].color + ";")}, t.risk[rk]),
        n.label ? h('span', {style:css("font-size:11px;font-weight:700;padding:3px 9px;border-radius:7px;background:var(--card2);color:" + (LABEL_RING[n.label] || 'var(--muted)') + ";")}, t.labels[n.label] || n.label) : null),

      h('div', null,
        row(t.f.txcount, num(n.tx_count)),
        row(t.f.riskscore, String(Math.round(n.final_score))),
        n.graph_score != null ? row(t.f.graphScore, String(Math.round(n.graph_score))) : null,
        row(g.inflow, weiToEth(f.inW, 4) + ' ETH'),
        row(g.outflow, weiToEth(f.outW, 4) + ' ETH'),
        row(g.totalFlow, weiToEth(f.total, 4) + ' ETH')),

      btn(g.expand, () => this.expand(n)),
      btn(g.makeCenter, () => this.build(n.address), true),
      btn(g.openWallet, () => this.props.onOpenWallet(n.address)));
  }
}
