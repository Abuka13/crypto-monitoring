import React from 'react';
import { h, css } from '../lib/dom';
import { icon } from '../lib/icons';
import { fmtDate } from '../lib/format';

const LANGS = [['ru','RU'], ['kk','KK'], ['en','EN']];

// Блок LLM-объяснения алерта.
// Важно для прозрачности: текст помечен как сгенерированный языковой моделью,
// а уровень риска здесь только ОТОБРАЖАЕТСЯ — модель его не определяет и не меняет.
export default class ExplainBlock extends React.Component {
  constructor(props){
    super(props);
    this.state = {open:false, loading:false, data:null, error:'', lang:props.lang || 'ru'};
  }

  // Смена алерта — сбрасываем показанное объяснение.
  componentDidUpdate(prev){
    if(prev.alertId !== this.props.alertId){
      this.setState({open:false, loading:false, data:null, error:''});
    }
  }

  async load(force, lang){
    const useLang = lang || this.state.lang;
    this.setState({open:true, loading:true, error:'', lang:useLang,
                   data:force ? null : this.state.data});
    const res = await this.props.explainAlert(this.props.alertId, useLang, force);
    if(!res.ok){
      const d = res.data || {};
      this.setState({loading:false,
        error: d.configured === false ? this.props.t.explain.notConfigured
                                      : (d.detail || this.props.t.explain.failed)});
      return;
    }
    this.setState({loading:false, data:res.data});
  }

  render(){
    const t = this.props.t; const e = t.explain; const s = this.state;

    // До первого запроса — только кнопка, чтобы не дёргать LLM на каждый просмотр.
    if(!s.open){
      return h('button', {onClick:() => this.load(false),
        style:css("display:flex;align-items:center;justify-content:center;gap:9px;width:100%;padding:12px;margin-bottom:22px;border-radius:11px;border:1px solid var(--border);background:var(--card2);color:var(--text);font-size:13px;font-weight:700;font-family:inherit;cursor:pointer;transition:all .18s;")},
        icon('sparkle', 16), h('span', null, e.button));
    }

    return h('div', {style:css("margin-bottom:22px;animation:fadeIn .2s ease;")},
      h('div', {style:css("display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px;flex-wrap:wrap;")},
        h('div', {style:css("display:flex;align-items:center;gap:7px;font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;")},
          icon('sparkle', 14), h('span', null, e.title)),
        h('div', {style:css("display:flex;align-items:center;gap:4px;")},
          LANGS.map(([code, label]) => h('button', {key:code,
            onClick:() => this.load(false, code),
            style:css("padding:3px 8px;border-radius:7px;font-size:10.5px;font-weight:700;font-family:inherit;cursor:pointer;transition:all .16s;" +
              (s.lang === code ? "background:var(--accent);color:#06201c;border:1px solid transparent;"
                               : "background:transparent;color:var(--muted);border:1px solid var(--border);"))}, label)))),

      s.loading ? h('div', {style:css("display:flex;align-items:center;gap:10px;padding:14px 16px;background:var(--card2);border:1px solid var(--border);border-radius:11px;font-size:12.5px;color:var(--muted);")},
        h('span', {style:css("width:8px;height:8px;border-radius:50%;background:var(--accent);animation:pulseDot 1.4s infinite;flex-shrink:0;")}),
        h('span', null, e.generating)) : null,

      (!s.loading && s.error) ? h('div', {style:css("padding:13px 16px;border-radius:11px;background:rgba(245,170,60,.12);border:1px solid rgba(245,170,60,.35);color:#f5b54a;font-size:12.5px;line-height:1.5;")}, s.error) : null,

      (!s.loading && s.data) ? h(React.Fragment, null,
        h('div', {style:css("padding:14px 16px;background:var(--card2);border:1px solid var(--border);border-radius:11px;font-size:12.5px;line-height:1.65;white-space:pre-wrap;")},
          s.data.text),

        // Прозрачность: аналитик должен понимать происхождение текста.
        h('div', {style:css("display:flex;align-items:flex-start;gap:7px;margin-top:9px;padding:9px 12px;background:var(--card);border:1px dashed var(--border);border-radius:10px;font-size:10.5px;color:var(--muted);line-height:1.5;")},
          h('span', {style:css("flex-shrink:0;display:flex;margin-top:1px;")}, icon('sparkle', 12)),
          h('span', null, e.disclaimer)),

        h('div', {style:css("display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:9px;flex-wrap:wrap;")},
          h('span', {style:css("font-size:10.5px;color:var(--muted);")},
            [s.data.cached ? e.cached : null,
             s.data.model ? e.model + ': ' + s.data.model : null,
             s.data.generated_at ? fmtDate(Date.parse(s.data.generated_at)) : null,
            ].filter(Boolean).join(' · ')),
          h('button', {onClick:() => this.load(true),
            style:css("padding:6px 12px;border-radius:9px;border:1px solid var(--border);background:transparent;color:var(--muted);font-size:11px;font-weight:600;font-family:inherit;cursor:pointer;transition:all .16s;")}, e.regenerate))) : null);
  }
}
