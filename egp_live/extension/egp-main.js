/* The site's own successful API request is the only source of session headers.
 * They stay in this page's memory. No challenge solving, DOM table parsing,
 * credential persistence, or cookie extraction is performed here. */
(() => {
  'use strict';
  const ORIGIN = 'https://process5.gprocurement.go.th';
  const API_PATH = '/egp-oann10-service/pb/a-egp-allt-project/announcement';
  const PROVINCES = { '500000': 'เชียงใหม่', '570000': 'เชียงราย', '560000': 'พะเยา' };
  const nativeFetch = window.fetch.bind(window);
  const open = XMLHttpRequest.prototype.open;
  const setHeader = XMLHttpRequest.prototype.setRequestHeader;
  const send = XMLHttpRequest.prototype.send;
  const requests = new WeakMap();
  let session = null;
  let busy = false;
  let stopping = false;
  let inFlight = null;
  const post = (type, data) => window.postMessage({ channel: 'EGP_LIVE_API', type, ...data }, ORIGIN);
  function searchUrl(value) {
    try { const url = new URL(value, location.href); return url.origin === ORIGIN && url.pathname === API_PATH ? url : null; }
    catch { return null; }
  }
  function rows(payload) {
    if (payload?.validateCfTurnTile === false || payload?.validateAnnouncementToken === false)
      throw new Error('กรุณาค้นหาบนหน้า e-GP เพื่อยืนยันตัวตนใหม่');
    if (payload?.success === false) throw new Error('e-GP แจ้งว่าคำขอไม่สำเร็จ จึงหยุดดึง');
    const data = Array.isArray(payload?.data) ? payload.data : payload?.data?.data;
    if (!Array.isArray(data) || data.length > 1000) throw new Error('รูปแบบ JSON ของ e-GP เปลี่ยน จึงหยุดดึง');
    return data;
  }
  function remember(info, payload) {
    if (!searchUrl(info?.url)) return;
    try {
      rows(payload);
      const headers = {};
      // Capture only the legitimate application header, never Cookie/Authorization.
      for (const [key, value] of Object.entries(info.headers || {}))
        if (['accept', 'content-type', 'x-announcement-token'].includes(key.toLowerCase())) headers[key] = value;
      session = { headers };
      post('SESSION_READY', {});
    } catch { /* Rejected search responses do not establish a session. */ }
  }
  XMLHttpRequest.prototype.open = function(method, url, ...args) {
    requests.set(this, { method: String(method).toUpperCase(), url: String(url), headers: {} });
    return open.call(this, method, url, ...args);
  };
  XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
    const info = requests.get(this);
    if (info) info.headers[String(name).toLowerCase()] = String(value);
    return setHeader.call(this, name, value);
  };
  XMLHttpRequest.prototype.send = function(...args) {
    const info = requests.get(this);
    if (info?.method === 'GET' && searchUrl(info.url)) this.addEventListener('load', () => {
      if (this.status !== 200) return;
      try { remember(info, this.responseType === 'json' ? this.response : JSON.parse(this.responseText)); } catch { }
    }, { once: true });
    return send.apply(this, args);
  };
  window.fetch = async function(input, init) {
    const result = await nativeFetch(input, init);
    const url = typeof input === 'string' || input instanceof URL ? String(input) : input.url;
    if (result.ok && searchUrl(url)) {
      const headers = Object.fromEntries(new Headers(init?.headers || (input instanceof Request ? input.headers : {})));
      result.clone().json().then(payload => remember({url, headers}, payload)).catch(() => {});
    }
    return result;
  };
  function publicPayload(payload) {
    // Keep all project fields, but never send authentication material to localhost.
    rows(payload);
    const clean = value => Array.isArray(value) ? value.map(clean)
      : value && typeof value === 'object' ? Object.fromEntries(Object.entries(value)
        .filter(([key]) => !/token|authorization|cookie|password|secret|api.?key/i.test(key))
        .map(([key, item]) => [key, clean(item)])) : value;
    return clean(payload);
  }
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  async function synchronize(command) {
    if (busy) throw new Error('มีการดึง API อยู่แล้ว');
    if (!session) throw new Error('กรุณาค้นหาบนหน้า e-GP ให้สำเร็จหนึ่งครั้งหลังโหลดตัวเชื่อม');
    const automatic = command.auto === true;
    if (![2569, 2570].includes(command.year) || !Array.isArray(command.provinces)
        || !command.provinces.length || command.provinces.length > 3 || command.provinces.some(code => !PROVINCES[code])
        || (automatic
          ? !command.startPages || command.provinces.some(code => !Number.isInteger(command.startPages[code])
              || command.startPages[code] < 1 || command.startPages[code] > 1000)
          : !Number.isInteger(command.startPage) || command.startPage < 1 || command.startPage > 1000
              || !Number.isInteger(command.maxPages) || command.maxPages < 1 || command.maxPages > 10
              || command.startPage + command.maxPages - 1 > 1000))
      throw new Error('เงื่อนไขดึง API ไม่ถูกต้อง');
    busy = true;
    stopping = false;
    let count = 0;
    let capped = false;
    try {
      for (const code of [...new Set(command.provinces)]) {
        const seen = new Set();
        const firstPage = automatic ? command.startPages[code] : command.startPage;
        const lastPage = automatic ? 1000 : firstPage + command.maxPages - 1;
        for (let page = firstPage; page <= lastPage; page++) {
          if (stopping) throw new Error('หยุดตามคำสั่งแล้ว · หน้าที่บันทึกสำเร็จยังอยู่ในฐานข้อมูล');
          const url = new URL(API_PATH, ORIGIN);
          for (const [key, value] of Object.entries({budgetYear: command.year, moiId: code,
            methodId: '16', typeId: '02', announcementTodayFlag: 'false', page})) url.searchParams.set(key, value);
          post('PROGRESS', { message: `กำลังดึง API ${PROVINCES[code]} หน้า ${page}` });
          const controller = new AbortController();
          inFlight = controller;
          const timeout = setTimeout(() => controller.abort(), 30000);
          let response;
          try {
            response = await nativeFetch(url.toString(), { method: 'GET', headers: session.headers,
              credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: controller.signal });
          } catch (error) {
            if (stopping) throw new Error('หยุดตามคำสั่งแล้ว · หน้าที่บันทึกสำเร็จยังอยู่ในฐานข้อมูล');
            throw new Error(error.name === 'AbortError' ? 'e-GP ไม่ตอบภายใน 30 วินาที จึงหยุดดึง' : 'เชื่อม API e-GP ไม่สำเร็จ จึงหยุดดึง');
          } finally { clearTimeout(timeout); inFlight = null; }
          if (stopping) throw new Error('หยุดตามคำสั่งแล้ว · หน้าที่บันทึกสำเร็จยังอยู่ในฐานข้อมูล');
          if (response.status === 429) throw new Error('e-GP จำกัดคำขอ (429) หยุดแล้ว กรุณารอก่อนดึงใหม่');
          if (!response.ok) throw new Error(`e-GP ตอบ HTTP ${response.status} จึงหยุดดึง`);
          const payload = await response.json();
          const projects = rows(payload);
          if (projects.some(row => seen.has(String(row.projectId))))
            throw new Error('API ส่งโครงการซ้ำข้ามหน้า จึงหยุดเพื่อไม่ให้รายงานความครบถ้วนผิด');
          projects.forEach(row => seen.add(String(row.projectId)));
          // An acknowledgement prevents more requests after a local validation failure.
          const receiptId = crypto.randomUUID();
          const acknowledgement = new Promise((resolve, reject) => {
            const timer = setTimeout(() => { window.removeEventListener('message', listener); reject(new Error('โปรแกรมในเครื่องไม่ตอบรับข้อมูล')); }, 20000);
            function listener(event) {
              if (event.source !== window || event.origin !== ORIGIN || event.data?.channel !== 'EGP_LIVE_CONTROL'
                  || event.data?.type !== 'RECEIPT' || event.data?.receiptId !== receiptId) return;
              clearTimeout(timer); window.removeEventListener('message', listener);
              event.data.ok ? resolve() : reject(new Error(event.data.error || 'บันทึกข้อมูลไม่สำเร็จ'));
            }
            window.addEventListener('message', listener);
          });
          post('API_PAGE', { receiptId, source_url: url.toString(), response: publicPayload(payload) });
          await acknowledgement;
          count += projects.length;
          if (stopping) throw new Error('หยุดตามคำสั่งแล้ว · หน้าที่บันทึกสำเร็จยังอยู่ในฐานข้อมูล');
          if (!projects.length) break;
          if (automatic && page === 1000) capped = true;
          if (page < lastPage) await sleep(2500);
        }
        if (stopping) throw new Error('หยุดตามคำสั่งแล้ว · หน้าที่บันทึกสำเร็จยังอยู่ในฐานข้อมูล');
        if (code !== command.provinces.at(-1)) await sleep(2500);
      }
      post('PROGRESS', { message: capped
        ? `รับ API และบันทึกแล้ว ${count} รายการ · ถึงขีดหน้า 1000 โดยยังไม่เจอหน้าว่าง ต้องตรวจบน e-GP`
        : `รับ API และบันทึกแล้ว ${count} รายการ · ยังต้องตรวจจำนวนกับ e-GP ก่อนสรุปว่าครบ` });
    } finally { busy = false; inFlight = null; }
  }
  window.addEventListener('message', event => {
    if (event.source !== window || event.origin !== ORIGIN || event.data?.channel !== 'EGP_LIVE_CONTROL'
        || !['SYNC', 'STOP'].includes(event.data?.type)) return;
    if (event.data.type === 'STOP') {
      stopping = true;
      inFlight?.abort();
    } else if (event.data.type === 'SYNC') {
      synchronize(event.data).catch(error => post('PROGRESS', { message: error.message }));
    }
  });
})();
