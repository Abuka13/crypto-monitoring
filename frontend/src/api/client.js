import { Auth } from '../auth/tokens';

// База API. По умолчанию '/api' — работает и в dev (через прокси Vite на Django),
// и в проде (статика отдаётся тем же Django, один источник). Можно переопределить
// через VITE_API_URL.
export const API = import.meta.env.VITE_API_URL || '/api';

async function refreshAccess(){
  if(!Auth.refresh) return false;
  const r = await fetch(API + '/auth/refresh/', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({refresh: Auth.refresh}),
  });
  if(!r.ok) return false;
  const d = await r.json();
  Auth.set(d.access);
  return true;
}

// Единая точка запросов: подставляет Bearer-токен; при 401 один раз пробует
// обновить access через refresh и повторить. Если refresh невалиден — чистит
// токены и зовёт Auth.onExpire (возврат на экран логина).
export async function apiFetch(url, opts){
  opts = opts || {};
  const withAuth = () => {
    const headers = Object.assign({}, opts.headers || {});
    if(Auth.access) headers['Authorization'] = 'Bearer ' + Auth.access;
    return fetch(url, Object.assign({}, opts, {headers}));
  };
  let r = await withAuth();
  if(r.status === 401){
    const ok = await refreshAccess();
    if(ok) r = await withAuth();
    if(!ok || r.status === 401){
      Auth.clear();
      if(Auth.onExpire) Auth.onExpire();
      throw new Error('unauthorized');
    }
  }
  return r;
}

export async function getJSON(url){
  const r = await apiFetch(url, {});
  if(!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}

export async function patchJSON(url, body){
  const r = await apiFetch(url, {method:'PATCH', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  const data = await r.json().catch(() => ({}));
  return {ok:r.ok, status:r.status, data};
}

// Логин — без токена (обычный fetch).
export async function loginRequest(username, password){
  const r = await fetch(API + '/auth/login/', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({username, password})});
  const data = await r.json().catch(() => ({}));
  return {ok:r.ok, status:r.status, data};
}

// Высокоуровневые вызовы домена.
export const fetchAlerts = () => getJSON(API + '/alerts/?limit=1000');
export const fetchWallets = () => getJSON(API + '/wallets/');
export const fetchTransactions = () => getJSON(API + '/transactions/');
export const fetchRules = () => getJSON(API + '/rules/');
export const fetchMe = () => getJSON(API + '/auth/me/');
export const fetchAlertDetail = (id) => getJSON(API + '/alerts/' + id + '/');
export const setAlertStatus = (id, status) => patchJSON(API + '/alerts/' + id + '/status/', {status});
export const setRuleActive = (id, isActive) => patchJSON(API + '/rules/' + id + '/', {is_active: isActive});

export async function logoutRequest(){
  if(!Auth.refresh) return;
  try{
    await fetch(API + '/auth/logout/', {
      method:'POST',
      headers:{'Content-Type':'application/json', 'Authorization':'Bearer ' + Auth.access},
      body: JSON.stringify({refresh: Auth.refresh}),
    });
  }catch(e){ /* выход всё равно локально завершится */ }
}
