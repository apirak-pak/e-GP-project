(() => {
  'use strict';
  const local = location.origin === 'http://127.0.0.1:8502';
  const channel = local ? 'EGP_LIVE_LOCAL' : 'EGP_LIVE_API';
  function post(data) { window.postMessage(data, location.origin); }
  window.addEventListener('message', async event => {
    if (event.source !== window || event.origin !== location.origin || event.data?.channel !== channel) return;
    const data = event.data;
    try {
      if (local && data.type === 'HELLO') post({channel: 'EGP_LIVE_EXTENSION', type:'READY', extensionId: chrome.runtime.id});
      else if (local && data.type === 'PAIR') {
        const result = await chrome.runtime.sendMessage({type:'PAIR', token:data.token});
        if (!result?.ok) throw new Error(result?.error || 'จับคู่ไม่สำเร็จ');
        post({channel:'EGP_LIVE_EXTENSION', type:'PAIRED'});
      } else if (local && data.type === 'SYNC') {
        const result = await chrome.runtime.sendMessage({type:'SYNC', year:data.year, provinces:data.provinces,
          auto:data.auto, startPages:data.startPages, startPage:data.startPage, maxPages:data.maxPages});
        post({channel:'EGP_LIVE_EXTENSION', type:'COMMAND_RESULT', action:'SYNC', ...result});
      } else if (local && data.type === 'STOP') {
        const result = await chrome.runtime.sendMessage({type:'STOP'});
        post({channel:'EGP_LIVE_EXTENSION', type:'COMMAND_RESULT', action:'STOP', ...result});
      } else if (!local && ['API_PAGE', 'PROGRESS', 'SESSION_READY'].includes(data.type)) {
        const result = await chrome.runtime.sendMessage(data);
        if (data.type === 'API_PAGE') post({channel:'EGP_LIVE_CONTROL', type:'RECEIPT', receiptId:data.receiptId, ...result});
      }
    } catch {
      if (!local && data.type === 'API_PAGE') post({channel:'EGP_LIVE_CONTROL', type:'RECEIPT', receiptId:data.receiptId, ok:false, error:'เชื่อมโปรแกรมในเครื่องไม่สำเร็จ'});
      else if (local) post({channel:'EGP_LIVE_EXTENSION', type:'COMMAND_RESULT', ok:false, error:'ตัวเชื่อมขัดข้อง กรุณาโหลดหน้าโปรแกรมใหม่'});
    }
  });
  chrome.runtime.onMessage.addListener(message => {
    if (!local && ['SYNC', 'STOP'].includes(message.type)) post({channel:'EGP_LIVE_CONTROL', ...message});
  });
})();
