import React from 'react';
import { h, css } from './lib/dom';
import { getT } from './i18n/translations';
import { Auth } from './auth/tokens';
import {
  loginRequest, logoutRequest, fetchMe,
  fetchAlertsPage, fetchWalletsPage, fetchTransactionsPage, fetchRules, fetchStats,
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
import { PAGE } from './lib/constants';

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
      // Списки хранят ТОЛЬКО текущую страницу (не накапливают).
      alerts:[], wallets:[], txs:[], rules:[], stats:null,
      alertsCount:0, walletsCount:0, txsCount:0,
      alertsPage:1, walletsPage:1, txsPage:1,
      listLoading:'',   // какой список сейчас перезагружается
      loading:true, error:'', toast:'',
    };
  }

  componentDidMount(){
    Auth.onExpire = () => this.forceLogout();
    this.bootstrap();
  }
  componentWillUnmount(){ clearTimeout(this._tt); clearTimeout(this._searchT); }

  // Параметры запроса страницы с учётом текущих фильтров (фильтрация — на сервере).
  _alertParams(){
    const s = this.state; const p = {limit:PAGE, offset:(s.alertsPage - 1) * PAGE};
    if(s.fRisk !== 'all') p.level = s.fRisk;
    if(s.fStatus !== 'all') p.status = s.fStatus;
    if(s.fType !== 'all') p.target_type = s.fType;
    const q = s.q.trim(); if(q) p.search = q;
    return p;
  }
  _walletParams(){
    const s = this.state; const p = {limit:PAGE, offset:(s.walletsPage - 1) * PAGE};
    if(s.wRisk !== 'all') p.risk = s.wRisk;
    if(s.wFlag === 'flagged') p.is_flagged = 'true';
    return p;
  }
  _txParams(){
    const s = this.state; return {limit:PAGE, offset:(s.txsPage - 1) * PAGE};
  }

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
      // Дашборд берёт агрегаты с сервера (не тянет все алерты), списки — первую страницу.
      const [stats, alertsP, walletsP, txsP, rules] = await Promise.all([
        fetchStats(),
        fetchAlertsPage(this._alertParams()),
        fetchWalletsPage(this._walletParams()),
        fetchTransactionsPage(this._txParams()),
        fetchRules(),
      ]);
      const alerts = (alertsP.results || []).map(a => Object.assign({}, a, {_ts: Date.parse(a.created_at)}));
      this.setState({
        stats,
        alerts, alertsCount: alertsP.count ?? alerts.length,
        wallets: walletsP.results || [], walletsCount: walletsP.count ?? 0,
        txs: txsP.results || [], txsCount: txsP.count ?? 0,
        rules,
        loading:false,
      });
    }catch(e){
      this.setState({loading:false, error:'Не удалось загрузить данные API: ' + e.message});
    }
  }

  // Перезагрузка текущей страницы списка с учётом фильтров (заменяет строки).
  async reloadList(kind){
    const cfg = {
      alerts: {fetch:() => fetchAlertsPage(this._alertParams()), arr:'alerts', count:'alertsCount',
               map:a => Object.assign({}, a, {_ts: Date.parse(a.created_at)})},
      wallets: {fetch:() => fetchWalletsPage(this._walletParams()), arr:'wallets', count:'walletsCount', map:x => x},
      txs: {fetch:() => fetchTransactionsPage(this._txParams()), arr:'txs', count:'txsCount', map:x => x},
    }[kind];
    if(!cfg) return;
    this.setState({listLoading:kind});
    try{
      const r = await cfg.fetch();
      this.setState({
        [cfg.arr]: (r.results || []).map(cfg.map),
        [cfg.count]: r.count ?? 0,
        listLoading:'',
      });
    }catch(e){
      this.setState({listLoading:''});
      this.showToast('Не удалось загрузить страницу');
    }
  }

  // Переход на страницу N.
  goToPage(kind, page){
    const key = {alerts:'alertsPage', wallets:'walletsPage', txs:'txsPage'}[kind];
    if(!key) return;
    this.setState({[key]:page}, () => this.reloadList(kind));
  }

  // Смена фильтра списка: сбрасываем на первую страницу и перезагружаем с сервера.
  setListFilter(kind, name, value){
    const pageKey = {alerts:'alertsPage', wallets:'walletsPage', txs:'txsPage'}[kind];
    this.setState({[name]:value, [pageKey]:1}, () => this.reloadList(kind));
  }

  // Поиск (шапка) фильтрует алерты на сервере, с задержкой против лишних запросов.
  onSearch(v){
    this.setState({q:v});
    clearTimeout(this._searchT);
    this._searchT = setTimeout(() => this.setState({alertsPage:1}, () => this.reloadList('alerts')), 350);
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
      s.screen === 'dashboard' ? h(Dashboard, {t, stats:s.stats, alerts:s.alerts, openAlert:a => this.openAlert(a)}) :
      s.screen === 'alerts' ? h(Alerts, {t, alerts:s.alerts, total:s.alertsCount, page:s.alertsPage, loading:s.listLoading === 'alerts', onPage:p => this.goToPage('alerts', p), fRisk:s.fRisk, fStatus:s.fStatus, fType:s.fType, alertsView:s.alertsView, onFilter:(k, v) => this.setListFilter('alerts', k, v), openAlert:a => this.openAlert(a)}) :
      s.screen === 'wallets' ? h(Wallets, {t, wallets:s.wallets, total:s.walletsCount, page:s.walletsPage, loading:s.listLoading === 'wallets', onPage:p => this.goToPage('wallets', p), wRisk:s.wRisk, wFlag:s.wFlag, onFilter:(k, v) => this.setListFilter('wallets', k, v), openWallet:w => this.openWallet(w), copy:x => this.copy(x)}) :
      s.screen === 'transactions' ? h(Transactions, {t, txs:s.txs, total:s.txsCount, page:s.txsPage, loading:s.listLoading === 'txs', onPage:p => this.goToPage('txs', p), openTx:x => this.openTx(x), copy:x => this.copy(x)}) :
      h(Rules, {t, rules:s.rules, toggleRule:r => this.toggleRule(r)});

    return h('div', {style:css("display:flex;height:100vh;")},
      h(Sidebar, {t, screen:s.screen, expanded:s.sidebarExpanded, onNav:id => this.setScreen(id), onLogout:() => this.doLogout()}),
      h('div', {style:css("flex:1;display:flex;flex-direction:column;min-width:0;")},
        h(Topbar, {
          t, lang:s.lang, onLang:k => this.setState({lang:k}),
          theme:s.theme, onToggleTheme:() => this.setState({theme:s.theme === 'dark' ? 'light' : 'dark'}),
          q:s.q, onSearch:v => this.onSearch(v),
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
