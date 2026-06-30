import { h, css } from '../lib/dom';
import { icon } from '../lib/icons';
import LangSwitch from '../components/LangSwitch';

// Экран входа. Управляемые поля логина/пароля; ошибка показывается на текущем языке.
export default function Login({ t, lang, onLang, loginUser, loginPass, loginError, onUser, onPass, onSubmit }){
  return h('div', {style:css("height:100vh;display:flex;align-items:center;justify-content:center;position:relative;background:radial-gradient(900px 600px at 50% -10%,var(--accent-soft),transparent 60%),var(--bg);overflow:hidden;")},
    h('div', {style:css("position:absolute;top:24px;right:28px;display:flex;gap:6px;background:var(--card);border:1px solid var(--border);border-radius:11px;padding:4px;")}, LangSwitch({lang, onLang, small:false})),
    h('div', {style:css("width:400px;max-width:92vw;background:var(--card);border:1px solid var(--border);border-radius:22px;padding:38px 34px;box-shadow:var(--shadow);")},
      h('div', {style:css("display:flex;flex-direction:column;align-items:center;gap:14px;text-align:center;margin-bottom:26px;")},
        h('div', {style:css("width:60px;height:60px;border-radius:17px;background:var(--accent-soft);color:var(--accent);display:flex;align-items:center;justify-content:center;border:1px solid var(--accent);")}, icon('shield', 26)),
        h('div', null,
          h('div', {style:css("font-size:23px;font-weight:800;letter-spacing:-.5px;")}, t.appName),
          h('div', {style:css("font-size:13.5px;color:var(--muted);margin-top:8px;line-height:1.5;max-width:300px;")}, t.login_sub))),
      h('div', {style:css("display:flex;flex-direction:column;gap:14px;")},
        h('div', null,
          h('div', {style:css("font-size:12px;color:var(--muted);margin-bottom:7px;font-weight:600;")}, t.login_user),
          h('input', {type:'text', placeholder:t.login_userPh, value:loginUser,
            onChange:e => onUser(e.target.value),
            onKeyDown:e => { if(e.key === 'Enter') onSubmit(); },
            style:css("width:100%;background:var(--card2);border:1px solid var(--border);border-radius:11px;padding:13px 14px;color:var(--text);font-size:14px;font-family:inherit;outline:none;")})),
        h('div', null,
          h('div', {style:css("font-size:12px;color:var(--muted);margin-bottom:7px;font-weight:600;")}, t.login_pass),
          h('input', {type:'password', placeholder:t.login_passPh, value:loginPass,
            onChange:e => onPass(e.target.value),
            onKeyDown:e => { if(e.key === 'Enter') onSubmit(); },
            style:css("width:100%;background:var(--card2);border:1px solid var(--border);border-radius:11px;padding:13px 14px;color:var(--text);font-size:14px;font-family:inherit;outline:none;")})),
        loginError ? h('div', {style:css("display:flex;align-items:center;gap:8px;background:rgba(255,90,90,.12);border:1px solid rgba(255,90,90,.4);color:#ff6f6f;border-radius:10px;padding:10px 13px;font-size:12.5px;font-weight:600;")}, loginError) : null,
        h('button', {onClick:onSubmit, style:css("margin-top:8px;width:100%;background:var(--accent);color:#06201c;border:none;border-radius:11px;padding:14px;font-size:14.5px;font-weight:700;font-family:inherit;cursor:pointer;")}, t.login_btn),
        h('div', {style:css("display:flex;align-items:center;gap:7px;justify-content:center;color:var(--muted2);font-size:11.5px;margin-top:6px;")}, icon('lock', 16), h('span', null, t.login_sub)))));
}
