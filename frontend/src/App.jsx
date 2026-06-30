import React from 'react';
import { h, css } from './lib/dom';
import { getT } from './i18n/translations';
import { Auth } from './auth/tokens';
import {
  loginRequest, logoutRequest, fetchMe,
  fetchAlerts, fetchWallets, fetchTransactions, fetchRules,
  fetchAlertDetail, setAlertStatus, setRuleActive,
} from './api/client';
import Sidebar from './components/Sidebar';
import Topbar from './components/Topbar';
import DetailDrawer from './components/DetailDrawer';
import Toast from './components/Toast';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Alerts from './pages/Alerts';
import Wallets from './pages/Wallets';
import Transactions from './pages/Transactions';
import Rules from './pages/Rules';

// Корневой компонент: владеет состоянием, аутентификацией, загрузкой данных и
// маршрутизацией между экранами. Сохраняет ту же машину состояний, что и прежний
// монолит (class + setState) — поведение 1-в-1; экраны вынесены в отдельные компоненты.
export default class App extends React.Component {
  constructor(props){
    super(props);
    this.state = {
      booting:true, loggedIn:false, user:null,
      loginUser:'', loginPass:'', loginError:'',
      theme:'dark', lang:'ru', screen:'dashboard',
      sidebarExpanded:true,
      fRisk:'all', fStatus:'all', fType:'all', q:'', alertsView:'table',
      wRisk:'all', wFlag:'all',
      selected:null, selectedKind:null, detailData:null,
      alerts:[], wallets:[], txs:[], rules:[],
      loading:true, error:'', toast:'',
    };
  }

  componentDidMount(){
    Auth.onExpire = () => this.forceLogout();
    this.bootstrap();
  }
  componentWillUnmount(){ clearTimeout(this._tt); }

  T_(){ return getT(this.state.lang); }

  // ---------- аутентификация ----------
  async bootstrap(){
    if(Auth.access){
      try{
        const me = await fetchMe();
        this.setState({user:me, loggedIn:true, booting:false});
        this.loadAll();
        return;
      }catch(e){ /* токен невалиден -> на экран логина */ }
    }
    this.setState({booting:false, loggedIn:false});
  }

  async doLogin(){
    const {loginUser, loginPass} = this.state;
    if(!loginUser || !loginPass){ this.setState({loginError:this.T_().login_error}); return; }
    this.setState({loginError:''});
    const res = await loginRequest(loginUser, loginPass);
    if(!res.ok){ this.setState({loginError:this.T_().login_error}); return; }
    Auth.set(res.data.access, res.data.refresh);
    try{
      const me = await fetchMe();
      this.setState({user:me, loggedIn:true, loginPass:'', loginError:''});
      this.loadAll();
    }catch(e){ this.setState({loginError:this.T_().login_error}); }
  }

  forceLogout(){
    Auth.clear();
    this.setState({loggedIn:false, user:null, selected:null, selectedKind:null, detailData:null, loginPass:''});
  }

  async doLogout(){
    await logoutRequest();
    this.forceLogout();
  }

  async loadAll(){
    try{
      this.setState({loading:true, error:''});
      const [alertsResp, wallets, txs, rules] = await Promise.all([
        fetchAlerts(), fetchWallets(), fetchTransactions(), fetchRules(),
      ]);
      const alerts = (alertsResp.results || alertsResp).map(a => Object.assign({}, a, {_ts: Date.parse(a.created_at)}));
      this.setState({alerts, wallets, txs, rules, loading:false});
    }catch(e){
      this.setState({loading:false, error:'Не удалось загрузить данные API: ' + e.message});
    }
  }

  // ---------- helpers ----------
  showToast(msg){ this.setState({toast:msg}); clearTimeout(this._tt); this._tt = setTimeout(() => this.setState({toast:''}), 1600); }
  copy(text){ try{ navigator.clipboard && navigator.clipboard.writeText(text); }catch(e){} this.showToast(this.T_().copied); }
  setScreen(id){ this.setState({screen:id, selected:null, selectedKind:null, detailData:null}); }

  // ---------- detail ----------
  async openAlert(a){
    this.setState({selected:a, selectedKind:'alert', detailData:null});
    try{ const d = await fetchAlertDetail(a.id); this.setState({detailData:d}); }
    catch(e){ this.showToast('Ошибка загрузки деталей'); }
  }
  openWallet(w){ this.setState({selected:w, selectedKind:'wallet', detailData:null}); }
  openTx(x){ this.setState({selected:x, selectedKind:'tx', detailData:null}); }
  closeDetail(){ this.setState({selected:null, selectedKind:null, detailData:null}); }

  async setStatus(ns){
    const sel = this.state.selected; if(!sel) return;
    const res = await setAlertStatus(sel.id, ns);
    if(!res.ok){ this.showToast(res.data.detail || 'Недопустимый переход'); return; }
    const upd = res.data;
    const alerts = this.state.alerts.map(a => a.id === sel.id ? Object.assign({}, a, {status:upd.status, resolved_at:upd.resolved_at}) : a);
    const detailData = this.state.detailData ? Object.assign({}, this.state.detailData, {status:upd.status, resolved_at:upd.resolved_at}) : null;
    this.setState({alerts, detailData});
    this.showToast(this.T_().statusChanged);
  }
  async toggleRule(r){
    const res = await setRuleActive(r.id, !r.is_active);
    if(!res.ok){ this.showToast('Не удалось изменить правило'); return; }
    const rules = this.state.rules.map(x => x.id === r.id ? Object.assign({}, x, {is_active:res.data.is_active}) : x);
    this.setState({rules});
  }

  // ============================ RENDER ============================
  render(){
    const s = this.state;
    if(s.booting){
      return h('div', {'data-theme':s.theme, style:css("min-height:100vh;height:100vh;background:var(--bg);")});
    }
    return h('div', {'data-theme':s.theme, style:css("min-height:100vh;height:100vh;background:var(--bg);color:var(--text);font-family:'Manrope',system-ui,sans-serif;overflow:hidden;")},
      s.loggedIn ? this.renderApp() : this.renderLogin(),
      h(Toast, {msg:s.toast}));
  }

  renderLogin(){
    const s = this.state;
    return h(Login, {
      t:this.T_(), lang:s.lang, onLang:k => this.setState({lang:k}),
      loginUser:s.loginUser, loginPass:s.loginPass, loginError:s.loginError,
      onUser:v => this.setState({loginUser:v, loginError:''}),
      onPass:v => this.setState({loginPass:v, loginError:''}),
      onSubmit:() => this.doLogin(),
    });
  }

  renderApp(){
    const s = this.state; const t = this.T_();
    const page =
      s.loading ? this.renderInfo(t.loading || 'Загрузка…') :
      s.error ? this.renderInfo(s.error) :
      s.screen === 'dashboard' ? h(Dashboard, {t, alerts:s.alerts, wallets:s.wallets, openAlert:a => this.openAlert(a)}) :
      s.screen === 'alerts' ? h(Alerts, {t, alerts:s.alerts, fRisk:s.fRisk, fStatus:s.fStatus, fType:s.fType, q:s.q, alertsView:s.alertsView, onFilter:(k, v) => this.setState({[k]:v}), openAlert:a => this.openAlert(a)}) :
      s.screen === 'wallets' ? h(Wallets, {t, wallets:s.wallets, wRisk:s.wRisk, wFlag:s.wFlag, onFilter:(k, v) => this.setState({[k]:v}), openWallet:w => this.openWallet(w), copy:x => this.copy(x)}) :
      s.screen === 'transactions' ? h(Transactions, {t, txs:s.txs, openTx:x => this.openTx(x), copy:x => this.copy(x)}) :
      h(Rules, {t, rules:s.rules, toggleRule:r => this.toggleRule(r)});

    return h('div', {style:css("display:flex;height:100vh;")},
      h(Sidebar, {t, screen:s.screen, expanded:s.sidebarExpanded, onNav:id => this.setScreen(id), onLogout:() => this.doLogout()}),
      h('div', {style:css("flex:1;display:flex;flex-direction:column;min-width:0;")},
        h(Topbar, {
          t, lang:s.lang, onLang:k => this.setState({lang:k}),
          theme:s.theme, onToggleTheme:() => this.setState({theme:s.theme === 'dark' ? 'light' : 'dark'}),
          q:s.q, onSearch:v => this.setState({q:v}),
          expanded:s.sidebarExpanded, onToggleSidebar:() => this.setState({sidebarExpanded:!s.sidebarExpanded}),
          user:s.user,
        }),
        h('div', {style:css("flex:1;min-height:0;overflow:hidden;")}, page)),
      h(DetailDrawer, {
        t, selected:s.selected, kind:s.selectedKind, detailData:s.detailData,
        onClose:() => this.closeDetail(), onSetStatus:ns => this.setStatus(ns),
      }));
  }

  renderInfo(msg){
    return h('div', {style:css("height:100%;display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:14px;padding:24px;text-align:center;")}, msg);
  }
}
