const LOCAL = 'http://127.0.0.1:8502';
const EGP = 'https://process5.gprocurement.go.th';
async function localPost(path, payload) {
  const { token } = await chrome.storage.session.get('token');
  if (!token) throw new Error('กรุณาเชื่อมตัวรับ API ที่หน้าโปรแกรมก่อน');
  const response = await fetch(LOCAL + path, { method:'POST', cache:'no-store',
    headers:{'Content-Type':'application/json', Authorization:'Bearer ' + token}, body:JSON.stringify(payload) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'โปรแกรมในเครื่องปฏิเสธข้อมูล');
  return data;
}
async function handle(message, sender) {
  const origin = new URL(sender.url || sender.tab?.url || 'about:blank').origin;
  if (message.type === 'PAIR' && origin === LOCAL) {
    if (typeof message.token !== 'string' || !/^[A-Za-z0-9_-]{32,100}$/.test(message.token)) throw new Error('ข้อมูลเชื่อมต่อไม่ถูกต้อง');
    await chrome.storage.session.set({token:message.token});
    return {ok:true};
  }
  if (['SYNC', 'STOP'].includes(message.type) && origin === LOCAL) {
    const {egpTabId} = await chrome.storage.session.get('egpTabId');
    if (Number.isInteger(egpTabId)) {
      const tab = await chrome.tabs.get(egpTabId).catch(() => null);
      if (tab?.url?.startsWith(EGP + '/egp-agpc01-web/')) {
        await chrome.tabs.sendMessage(egpTabId, message);
        return {ok:true};
      }
    }
    const tabs = await chrome.tabs.query({url: EGP + '/egp-agpc01-web/*'});
    if (!tabs.length) throw new Error('กรุณาเปิด e-GP ในเบราว์เซอร์นี้และค้นหาให้สำเร็จหนึ่งครั้ง');
    if (tabs.length > 1) throw new Error('กรุณาเหลือแท็บค้นหา e-GP เพียงหนึ่งแท็บในเบราว์เซอร์นี้');
    await chrome.tabs.sendMessage(tabs[0].id, message);
    return {ok:true};
  }
  if (origin !== EGP) throw new Error('ไม่รับข้อมูลจากเว็บไซต์นี้');
  if (message.type === 'API_PAGE') {
    const result = await localPost('/api/import', {source_url:message.source_url, response:message.response});
    return {ok:true, ...result};
  }
  if (message.type === 'PROGRESS') return localPost('/api/progress', {message:message.message});
  if (message.type === 'SESSION_READY') {
    if (Number.isInteger(sender.tab?.id)) await chrome.storage.session.set({egpTabId:sender.tab.id});
    return {ok:true};
  }
  throw new Error('ไม่รู้จักคำสั่ง');
}
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  handle(message, sender).then(respond, error => respond({ok:false, error:error.message}));
  return true;
});
