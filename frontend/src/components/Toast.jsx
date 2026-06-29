import { h, css } from '../lib/dom';

export default function Toast({ msg }){
  if(!msg) return null;
  return h('div', {style:css("position:fixed;bottom:26px;left:50%;transform:translateX(-50%);background:var(--text);color:var(--bg);padding:11px 20px;border-radius:11px;font-size:13px;font-weight:600;z-index:80;box-shadow:var(--shadow);")}, msg);
}
