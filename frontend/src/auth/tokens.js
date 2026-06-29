// Хранилище JWT-токенов (access/refresh) в localStorage.
// onExpire выставляет App: вызывается, когда refresh невалиден -> возврат на логин.
export const Auth = {
  access: localStorage.getItem('fm_access'),
  refresh: localStorage.getItem('fm_refresh'),
  onExpire: null,
  set(access, refresh){
    this.access = access;
    localStorage.setItem('fm_access', access);
    if(refresh){ this.refresh = refresh; localStorage.setItem('fm_refresh', refresh); }
  },
  clear(){
    this.access = null; this.refresh = null;
    localStorage.removeItem('fm_access');
    localStorage.removeItem('fm_refresh');
  },
};
