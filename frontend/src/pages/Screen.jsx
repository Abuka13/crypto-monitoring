import React from 'react';
import { h, css } from '../lib/dom';
import { icon } from '../lib/icons';
import { RISK } from '../lib/meta';
import { ringGauge } from '../lib/charts';
import { weiToEth, shorten, fmtDate, num } from '../lib/format';

const LEVEL_KEY = {LOW:'low', MEDIUM:'medium', HIGH:'high', CRITICAL:'critical'};
const rm = (level) => RISK[LEVEL_KEY[level] || 'low'] || RISK.low;

// Скрининг идёт несколько секунд (сеть + расчёты), поэтому показываем этапы —
// иначе кажется, что интерфейс завис.
const STEP_MS = 1400;

export default class Screen extends React.Component {
  constructor(props){
    super(props);
    this.state = {address:'', result:null, loading:false, error:'', step:0, history:[]};
  }

  componentDidMount(){ this.loadHistory(); }
  componentWillUnmount(){ clearInterval(this._stepT); }

  async loadHistory(){
    try{ const r = await this.props.fetchScreenHistory(); this.setState({history:r.results || []}); }
    catch(e){ /* история не критична */ }
  }

  async paste(){
    try{
      const text = await navigator.clipboard.readText();
      if(text) this.setState({address:text.trim(), error:''});
    }catch(e){ /* браузер может не дать доступ — тогда просто вставят руками */ }
  }

  async check(addr, force){
    const address = ((addr != null ? addr : this.state.address) || '').trim();
    if(!address) return;
    const t = this.props.t;
    if(!/^0x[0-9a-fA-F]{40}$/.test(address)){
      this.setState({error:t.screen.invalid, result:null});
      return;
    }
    this.setState({address, loading:true, error:'', result:null, step:0});
    clearInterval(this._stepT);
    this._stepT = setInterval(() => {
      this.setState(s => ({step: Math.min(s.step + 1, t.screen.steps.length - 1)}));
    }, STEP_MS);

    const res = await this.props.screenAddress(address, force);
    clearInterval(this._stepT);
    if(!res.ok){
      this.setState({loading:false, error:(res.data && res.data.detail) || t.screen.failed});
      return;
    }
    this.setState({loading:false, result:res.data});
    this.loadHistory();
  }

  render(){
    const t = this.props.t; const s = this.state; const sc = t.screen;

    return h('div', {style:css("height:100%;overflow:auto;padding:24px;")},
      h('div', {style:css("max-width:940px;margin:0 auto;")},
        h('div', {style:css("margin-bottom:18px;")},
          h('div', {style:css("font-size:21px;font-weight:800;letter-spacing:-.5px;")}, sc.title),
          h('div', {style:css("font-size:12.5px;color:var(--muted);margin-top:2px;")}, sc.sub)),

        // ---- Поле ввода ----
        h('div', {style:css("display:flex;gap:10px;margin-bottom:18px;flex-wrap:wrap;")},
          h('div', {style:css("position:relative;flex:1;min-width:280px;")},
            h('span', {style:css("position:absolute;left:14px;top:50%;transform:translateY(-50%);color:var(--muted);display:flex;")}, icon('lock', 17)),
            h('input', {
              value:s.address, placeholder:sc.addrPh, spellCheck:false,
              onChange:e => this.setState({address:e.target.value, error:''}),
              onKeyDown:e => { if(e.key === 'Enter') this.check(); },
              style:css("width:100%;padding:14px 16px 14px 42px;border-radius:12px;border:1px solid var(--border);background:var(--card);color:var(--text);font-size:14px;font-family:'JetBrains Mono',monospace;outline:none;transition:border-color .18s;"),
            })),
          h('button', {onClick:() => this.paste(), title:sc.paste,
            style:css("width:46px;border-radius:12px;border:1px solid var(--border);background:var(--card);color:var(--muted);display:flex;align-items:center;justify-content:center;cursor:pointer;transition:all .18s;")}, icon('copy', 17)),
          h('button', {onClick:() => this.check(), disabled:s.loading,
            style:css("padding:14px 26px;border-radius:12px;border:none;background:var(--accent);color:#06201c;font-size:13.5px;font-weight:700;font-family:inherit;cursor:" + (s.loading ? 'default' : 'pointer') + ";opacity:" + (s.loading ? '.6' : '1') + ";transition:all .18s;")}, sc.check)),

        s.error ? h('div', {style:css("padding:13px 16px;border-radius:12px;background:rgba(255,90,90,.12);border:1px solid rgba(255,90,90,.35);color:#ff6f6f;font-size:13px;margin-bottom:18px;animation:fadeIn .2s ease;")}, s.error) : null,

        s.loading ? this._progress(sc) : null,
        (!s.loading && !s.result && !s.error) ? h('div', {style:css("padding:44px;text-align:center;color:var(--muted);font-size:13.5px;background:var(--card);border:1px solid var(--border);border-radius:16px;margin-bottom:18px;")}, sc.empty) : null,
        (!s.loading && s.result) ? this._verdict(s.result, t) : null,

        this._history(t)));
  }

  // Индикатор с этапами — запрос может идти несколько секунд.
  _progress(sc){
    return h('div', {style:css("padding:30px;background:var(--card);border:1px solid var(--border);border-radius:16px;margin-bottom:18px;animation:fadeIn .2s ease;")},
      h('div', {style:css("display:flex;flex-direction:column;gap:11px;")},
        sc.steps.map((label, i) => {
          const done = i < this.state.step, active = i === this.state.step;
          return h('div', {key:i, style:css("display:flex;align-items:center;gap:12px;font-size:13px;transition:all .3s;color:" + (active ? 'var(--text)' : done ? 'var(--muted)' : 'var(--muted)') + ";opacity:" + (active || done ? '1' : '.45') + ";")},
            h('span', {style:css("width:9px;height:9px;border-radius:50%;flex-shrink:0;background:" + (done ? '#34d399' : active ? 'var(--accent)' : 'var(--border)') + ";" + (active ? "animation:pulseDot 1.4s infinite;" : ""))}),
            h('span', null, label));
        })));
  }

  _verdict(d, t){
    const sc = t.screen;
    const m = rm(d.risk_level);
    const src = d.sources || {};
    const scores = d.scores || {};
    const meta = [];
    if(d.cached) meta.push(sc.cached + ' ' + fmtDate(Date.parse(d.last_screened_at)));
    else if(d.collected) meta.push(sc.collected);
    if(d.tx_fetched) meta.push(sc.fetched + ': ' + num(d.tx_fetched) + (d.truncated ? ' (' + sc.truncated + ')' : ''));
    if(d.elapsed_ms) meta.push(sc.elapsed + ' ' + (d.elapsed_ms / 1000).toFixed(1) + ' c');

    const chip = (label, active, text) => h('div', {key:label,
      style:css("display:flex;align-items:center;justify-content:space-between;gap:10px;padding:11px 14px;border-radius:11px;font-size:12.5px;" +
        (active ? "background:var(--accent-soft);border:1px solid var(--accent);" : "background:var(--card2);border:1px solid var(--border);color:var(--muted);"))},
      h('span', {style:css("font-weight:700;")}, label),
      h('span', {style:css("font-family:'JetBrains Mono',monospace;font-weight:700;")}, text));

    const stat = (k, v) => h('div', {style:css("padding:13px 15px;background:var(--card2);border:1px solid var(--border);border-radius:12px;")},
      h('div', {style:css("font-size:11px;color:var(--muted);margin-bottom:5px;")}, k),
      h('div', {style:css("font-size:14px;font-weight:700;font-family:'JetBrains Mono',monospace;")}, v));

    const sm = d.summary || {};
    return h('div', {style:css("background:var(--card);border:1px solid var(--border);border-radius:16px;padding:22px;margin-bottom:18px;animation:fadeIn .25s ease;")},
      // Шапка вердикта
      h('div', {style:css("display:flex;align-items:center;gap:20px;flex-wrap:wrap;margin-bottom:20px;")},
        h('div', {style:css("position:relative;display:flex;align-items:center;justify-content:center;flex-shrink:0;")},
          ringGauge(Math.round((d.confidence || 0) * 100), m.color),
          h('div', {style:css("position:absolute;text-align:center;")},
            h('div', {style:css("font-size:20px;font-weight:800;font-family:'JetBrains Mono',monospace;color:" + m.color + ";")}, Math.round((d.confidence || 0) * 100) + '%'),
            h('div', {style:css("font-size:8.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;")}, sc.confidence))),
        h('div', {style:css("flex:1;min-width:210px;")},
          h('div', {style:css("display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px;")},
            h('span', {style:css("font-size:24px;font-weight:800;letter-spacing:-.5px;color:" + m.color + ";")}, t.risk[LEVEL_KEY[d.risk_level] || 'low']),
            d.label ? h('span', {style:css("font-size:11.5px;font-weight:700;padding:4px 11px;border-radius:8px;background:" + m.bg + ";color:" + m.color + ";")},
              (t.labels[d.label] || d.label) + (d.label_source ? ' · ' + (t.labelSources[d.label_source] || d.label_source) : '')) : null),
          h('div', {style:css("font-size:12.5px;font-family:'JetBrains Mono',monospace;color:var(--muted);word-break:break-all;")}, d.address),
          meta.length ? h('div', {style:css("font-size:11.5px;color:var(--muted);margin-top:7px;opacity:.85;")}, meta.join(' · ')) : null),
        h('div', {style:css("display:flex;gap:8px;flex-wrap:wrap;")},
          h('button', {onClick:() => this.props.onShowGraph(d.address),
            style:css("display:flex;align-items:center;gap:8px;padding:10px 15px;border-radius:11px;border:1px solid var(--accent);background:var(--accent-soft);color:var(--accent);font-size:12.5px;font-weight:700;font-family:inherit;cursor:pointer;transition:all .18s;")},
            icon('graph', 15), h('span', null, sc.showGraph)),
          d.found ? h('button', {onClick:() => this.props.onOpenWallet(d.address),
            style:css("padding:10px 15px;border-radius:11px;border:1px solid var(--border);background:var(--card2);color:var(--text);font-size:12.5px;font-weight:700;font-family:inherit;cursor:pointer;transition:all .18s;")}, sc.openWallet) : null)),

      d.no_activity ? h('div', {style:css("padding:13px 16px;border-radius:12px;background:var(--card2);border:1px solid var(--border);color:var(--muted);font-size:13px;margin-bottom:18px;")}, sc.noActivity) : null,

      // Причины — главное для объяснимости
      (d.reasons && d.reasons.length) ? h('div', {style:css("margin-bottom:20px;")},
        h('div', {style:css("font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin-bottom:10px;")}, sc.reasons),
        h('div', {style:css("display:flex;flex-direction:column;gap:7px;")},
          d.reasons.map((r, i) => h('div', {key:i, style:css("display:flex;gap:9px;font-size:12.5px;line-height:1.55;padding:11px 14px;background:var(--card2);border:1px solid var(--border);border-radius:11px;")},
            h('span', {style:css("color:" + m.color + ";flex-shrink:0;")}, '•'),
            h('span', null, r))))) : null,

      // Вклад источников
      h('div', {style:css("margin-bottom:20px;")},
        h('div', {style:css("font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin-bottom:10px;")}, sc.sources),
        h('div', {style:css("display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px;")},
          chip(sc.srcHard, !!(src.hard_signal && src.hard_signal.active), (src.hard_signal && src.hard_signal.active) ? sc.yes : sc.no),
          chip(sc.srcRule, !!(src.rule && src.rule.high), String(Math.round(scores.rule || 0))),
          chip(sc.srcMl, !!(src.ml && src.ml.high), (src.ml && src.ml.available) ? String(Math.round(scores.ml || 0)) : sc.unavailable),
          chip(sc.srcGraph, !!(src.graph && src.graph.high), scores.graph != null ? String(Math.round(scores.graph)) : sc.unavailable))),

      // Агрегаты активности
      h('div', null,
        h('div', {style:css("font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin-bottom:10px;")}, sc.summary),
        h('div', {style:css("display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;")},
          stat(sc.txCount, num(sm.tx_count)),
          stat(sc.received, weiToEth(sm.total_received, 4) + ' ETH'),
          stat(sc.sent, weiToEth(sm.total_sent, 4) + ' ETH'),
          stat(sc.counterparties, num(sm.unique_counterparties)),
          stat(sc.period, Math.round(sm.active_period_days || 0) + ' ' + sc.days))));
  }

  _history(t){
    const sc = t.screen; const items = this.state.history;
    return h('div', {style:css("background:var(--card);border:1px solid var(--border);border-radius:16px;padding:18px;")},
      h('div', {style:css("font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin-bottom:12px;")}, sc.history),
      items.length ? h('div', {style:css("display:flex;flex-direction:column;gap:6px;")},
        items.map((it, i) => {
          const m = rm(it.risk_level);
          return h('div', {key:i, onClick:() => this.check(it.address),
            style:css("display:flex;align-items:center;gap:11px;padding:10px 13px;border-radius:11px;background:var(--card2);border:1px solid var(--border);cursor:pointer;transition:all .16s;")},
            h('span', {style:css("width:8px;height:8px;border-radius:50%;background:" + m.color + ";flex-shrink:0;")}),
            h('span', {style:css("flex:1;font-size:12.5px;font-family:'JetBrains Mono',monospace;")}, shorten(it.address, 14, 8)),
            it.label ? h('span', {style:css("font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:6px;background:var(--card);color:var(--muted);")}, t.labels[it.label] || it.label) : null,
            h('span', {style:css("font-size:11px;font-weight:700;color:" + m.color + ";")}, t.risk[LEVEL_KEY[it.risk_level] || 'low']),
            h('span', {style:css("font-size:11px;color:var(--muted);")}, fmtDate(Date.parse(it.last_screened_at))));
        }))
        : h('div', {style:css("font-size:12.5px;color:var(--muted);padding:8px 0;")}, sc.historyEmpty));
  }
}
