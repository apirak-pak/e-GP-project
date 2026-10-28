// Synthetic network tests: these do not claim that live e-GP authorization works.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const source = fs.readFileSync(path.join(__dirname, '../egp_live/extension/egp-main.js'), 'utf8');
const origin = 'https://process5.gprocurement.go.th';
const api = origin + '/egp-oann10-service/pb/a-egp-allt-project/announcement';
const row = {projectId:'69100000001', projectName:'Synthetic API fixture', deptName:'Agency',
  deptSubName:'Unit', flowName:'หนังสือเชิญชวน/ประกาศเชิญชวน', projectMoney:42, apiKey:'MUST_NOT_LEAVE_PAGE'};
function environment(reply, receiptOk=true) {
  const listeners = new Set();
  const messages = [];
  const calls = [];
  const window = {addEventListener:(_, f)=>listeners.add(f), removeEventListener:(_, f)=>listeners.delete(f)};
  function emit(data) { for (const f of [...listeners]) f({source:window, origin, data}); }
  window.postMessage = message => {
    messages.push(message);
    if (message.type === 'API_PAGE') queueMicrotask(() => emit({channel:'EGP_LIVE_CONTROL',
      type:'RECEIPT', receiptId:message.receiptId, ok:receiptOk, error:receiptOk?undefined:'Invalid API row'}));
  };
  window.fetch = async (url, options) => {
    calls.push({url, options});
    const response = reply(new URL(url));
    return {ok:response.status === 200, status:response.status, json:async()=>response.body};
  };
  class XHR {
    constructor() { this.listeners = []; this.status = 200; this.responseType = 'json'; }
    open() {} setRequestHeader() {} send() {}
    addEventListener(_, fn) { this.listeners.push(fn); }
  }
  vm.runInNewContext(source, {window, XMLHttpRequest:XHR, URL, Headers, Request, AbortController, location:{href:origin+'/egp-agpc01-web/announcement'},
    crypto, setTimeout:(fn,ms)=>setTimeout(fn, ms === 20000 ? 1000 : 0), clearTimeout, console});
  function establish(payload={data:[row]}) {
    const xhr = new XHR();
    xhr.open('GET', api);
    xhr.setRequestHeader('X-Announcement-Token', 'LEGITIMATE_SESSION_SECRET');
    xhr.setRequestHeader('Cookie', 'MUST_NOT_COPY_COOKIE');
    xhr.response = payload; xhr.send(); xhr.listeners.forEach(f=>f());
  }
  const sync = (command={}) => emit({channel:'EGP_LIVE_CONTROL',type:'SYNC',year:2570,
    provinces:['500000'],startPage:1,maxPages:2,...command});
  const stop = () => emit({channel:'EGP_LIVE_CONTROL',type:'STOP'});
  return {messages,calls,establish,sync,stop};
}
async function finished(env) {
  for (let i=0;i<100;i++) {
    const message = env.messages.findLast(m=>m.type==='PROGRESS');
    if (message && !message.message.startsWith('กำลังดึง')) return message.message;
    await new Promise(resolve=>setTimeout(resolve,5));
  }
  throw new Error('No completion status');
}
test('uses API JSON, authenticated page session, pagination and excludes credentials from messages', async()=>{
  const env = environment(url=>({status:200,body:{data:url.searchParams.get('page')==='1'?[row]:[]}}));
  env.establish(); env.sync(); await finished(env);
  assert.equal(env.calls.length,2);
  assert.equal(env.messages.filter(m=>m.type==='API_PAGE').length,2);
  assert.equal(env.calls[0].options.credentials,'same-origin');
  assert.equal(env.calls[0].options.headers['x-announcement-token'],'LEGITIMATE_SESSION_SECRET');
  assert.equal(env.calls[0].options.headers.cookie,undefined);
  assert.equal(JSON.stringify(env.messages).includes('LEGITIMATE_SESSION_SECRET'),false);
  assert.equal(JSON.stringify(env.messages).includes('MUST_NOT_LEAVE_PAGE'),false);
  assert.equal(env.calls[0].url.includes('moiId=500000'),true);
});
test('stops on Cloudflare denial without forwarding or retrying',async()=>{
  const env=environment(()=>({status:200,body:{validateCfTurnTile:false}}));
  env.establish(); env.sync(); assert.match(await finished(env),/ยืนยันตัวตน/);
  assert.equal(env.calls.length,1);
  assert.equal(env.messages.some(m=>m.type==='API_PAGE'),false);
});
test('stops on HTTP 429 without retrying',async()=>{
  const env=environment(()=>({status:429,body:{}}));
  env.establish(); env.sync(); assert.match(await finished(env),/429/);
  assert.equal(env.calls.length,1);
});
test('a rejected bootstrap response never establishes a session',async()=>{
  const env=environment(()=>{throw new Error('must not request');});
  env.establish({validateCfTurnTile:false}); env.sync();
  assert.match(await finished(env),/ค้นหาบนหน้า e-GP/);
  assert.equal(env.calls.length,0);
});
test('does not fetch another page after the local validator rejects a batch',async()=>{
  const env=environment(()=>({status:200,body:{data:[row]}}),false);
  env.establish(); env.sync(); assert.match(await finished(env),/Invalid API row/);
  assert.equal(env.calls.length,1);
});
test('detects duplicated pages instead of counting the same projects twice',async()=>{
  const env=environment(()=>({status:200,body:{data:[row]}}));
  env.establish(); env.sync(); assert.match(await finished(env),/ซ้ำข้ามหน้า/);
  assert.equal(env.calls.length,2);
  assert.equal(env.messages.filter(m=>m.type==='API_PAGE').length,1);
});

test('automatic mode starts at saved next page and ends after an empty page',async()=>{
  const env=environment(url=>{
    const page=Number(url.searchParams.get('page'));
    return {status:200,body:{data:page===13?[]:[{...row,projectId:String(69100000000+page)}]}};
  });
  env.establish();
  env.sync({auto:true,startPages:{'500000':11}});
  assert.match(await finished(env),/รับ API และบันทึกแล้ว 2 รายการ/);
  assert.deepEqual(env.calls.map(c=>new URL(c.url).searchParams.get('page')),['11','12','13']);
  assert.equal(env.messages.filter(m=>m.type==='API_PAGE').length,3);
});

test('stop command prevents the next page after a saved receipt',async()=>{
  const env=environment(()=>({status:200,body:{data:[row]}}));
  const original=env.messages.push.bind(env.messages);
  env.messages.push=(message)=>{const result=original(message); if(message.type==='API_PAGE') queueMicrotask(env.stop); return result;};
  env.establish(); env.sync({auto:true,startPages:{'500000':11}});
  assert.match(await finished(env),/หยุดตามคำสั่ง/);
  assert.equal(env.calls.length,1);
  assert.equal(env.messages.filter(m=>m.type==='API_PAGE').length,1);
});
