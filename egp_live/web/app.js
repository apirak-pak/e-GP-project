const $ = id => document.getElementById(id);
const LOCAL = location.origin;
let extensionId = null, currentPage = 1, latestCount = 0;
const num = n => Number(n || 0).toLocaleString('th-TH');
const money = n => n == null || n === '' ? '—' : Number(n).toLocaleString('th-TH', {maximumFractionDigits: 2}) + ' บาท';
const date = s => s ? new Date(s).toLocaleString('th-TH') : '—';
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function localPost(data) { window.postMessage({channel:'EGP_LIVE_LOCAL', ...data}, LOCAL); }
function status(message) { $('syncStatus').textContent = message; }

async function pair() {
  if (!extensionId) { localPost({type:'HELLO'}); status('ไม่พบส่วนขยายใน Edge นี้ · ติดตั้งหรือโหลดหน้าใหม่ก่อน'); return; }
  try {
    const response = await fetch('/api/pair', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({extension_id:extensionId})});
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'เชื่อมไม่สำเร็จ');
    localPost({type:'PAIR', token:data.token});
  } catch (error) { status(error.message); }
}
window.addEventListener('message', event => {
  if (event.source !== window || event.origin !== LOCAL || event.data?.channel !== 'EGP_LIVE_EXTENSION') return;
  const data = event.data;
  if (data.type === 'READY') { extensionId = data.extensionId; status('พบส่วนขยายแล้ว · กดเชื่อมตัวรับ API'); }
  if (data.type === 'PAIRED') status('เชื่อมแล้ว · เปิด e-GP และกดค้นหาหนึ่งครั้ง');
  if (data.type === 'COMMAND_RESULT') status(data.ok
    ? (data.action === 'STOP' ? 'ส่งคำสั่งหยุดแล้ว · รอให้หน้าปัจจุบันสิ้นสุด' : 'ส่งคำสั่งแล้ว · รอข้อมูลจาก e-GP')
    : data.error);
});
$('connect').addEventListener('click', pair);
function showMode() {
  const automatic = $('syncMode').value === 'auto';
  document.querySelectorAll('.manual-control').forEach(element => { element.hidden = automatic; });
  $('autoHint').hidden = !automatic;
  $('syncButton').textContent = automatic ? 'เริ่มดึงต่อเนื่อง' : 'ดึง API และบันทึก';
}
$('syncMode').addEventListener('change', showMode);
showMode();
$('syncButton').addEventListener('click', async () => {
  const provinces = [...document.querySelectorAll('input[name="syncProvince"]:checked')].map(e => e.value);
  const year = Number($('syncYear').value);
  const startPage = Number($('startPage').value), maxPages = Number($('maxPages').value);
  if (!provinces.length) return status('เลือกอย่างน้อยหนึ่งจังหวัด');
  if (!extensionId) return status('กรุณาติดตั้งและเชื่อมตัวรับ API ก่อน');
  if ($('syncMode').value === 'manual') {
    if (!Number.isInteger(startPage) || startPage < 1 || startPage + maxPages - 1 > 1000) return status('เลขหน้าไม่ถูกต้อง');
    localPost({type:'SYNC', year, provinces, auto:false, startPage, maxPages});
    return;
  }
  try {
    const response = await fetch('/api/state?year=' + year, {cache:'no-store'});
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'อ่านหน้าที่บันทึกแล้วไม่สำเร็จ');
    const names = {'500000':'เชียงใหม่','570000':'เชียงราย','560000':'พะเยา'};
    const startPages = {}, active = [];
    for (const code of provinces) {
      const coverage = data.coverage.find(c => c.fiscal_year === year && c.province === names[code]);
      if (coverage?.complete) continue;
      const next = coverage?.next_page || 1;
      if (next > 1000) continue;
      startPages[code] = next;
      active.push(code);
    }
    if (!active.length) return status('จังหวัดที่เลือกถึงหน้าว่างหรือขีดสูงสุดแล้ว · ใช้ Manual หากต้องการดึงหน้าเก่าซ้ำ');
    status('เริ่มอัตโนมัติ: ' + active.map(code => `${names[code]} หน้า ${startPages[code]}`).join(', '));
    localPost({type:'SYNC', year, provinces:active, auto:true, startPages});
  } catch (error) { status(error.message); }
});
$('stopButton').addEventListener('click', () => {
  if (!extensionId) return status('ยังไม่พบตัวเชื่อมใน Edge');
  localPost({type:'STOP'});
});

function filters() {
  const p = new URLSearchParams({year:$('filterYear').value,page:String(currentPage)});
  if ($('filterProvince').value) p.set('province',$('filterProvince').value);
  if ($('filterStatus').value) p.set('status',$('filterStatus').value);
  if ($('filterQuery').value.trim()) p.set('q',$('filterQuery').value.trim());
  return p;
}
async function refresh() {
  try {
    const response = await fetch('/api/state?' + filters(), {cache:'no-store'});
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'โหลดข้อมูลไม่สำเร็จ');
    $('totalProjects').textContent = num(data.total_projects);
    $('totalPages').textContent = num(data.total_api_pages);
    $('filteredCount').textContent = num(data.count);
    if (data.connection.connected) status(data.connection.message);
    const previous = $('filterStatus').value;
    $('filterStatus').innerHTML = '<option value="">ทุกสถานะ</option>' + data.statuses.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join('');
    if (data.statuses.includes(previous)) $('filterStatus').value = previous;
    $('coverageRows').innerHTML = data.coverage.length ? data.coverage.map(c => `<div class="coverage-item"><strong>${esc(c.province)} · ปี ${c.fiscal_year}</strong><span>รับ ${num(c.pages)} หน้าที่ไม่ซ้ำ · ต่อเนื่องถึงหน้า ${num(c.contiguous_through)}</span><span>${c.complete ? `เจอหน้าว่างที่หน้า ${num(c.empty_page)} · อัตโนมัติจะข้าม` : `หน้าถัดไปที่ยังขาด: ${num(c.next_page)}${c.missing_pages.length ? ' · มีช่องว่างก่อนหน้าสูงสุด' : ''}`}</span><span>รายการในหน้าล่าสุดรวม ${num(c.rows_received)} · ล่าสุด ${esc(date(c.updated_at))}</span></div>`).join('') : '<div class="empty">ยังไม่รับหน้า API</div>';
    $('projectRows').innerHTML = data.projects.map(p => `<article class="project-card"><div class="card-top"><span>เลขโครงการ ${esc(p.project_id)} · ${esc(p.agency_province)} · ปี ${p.fiscal_year}</span><span class="status">${esc(p.status || 'ไม่ระบุสถานะ')}</span></div><div class="card-body"><h3>${esc(p.title)}</h3><div class="card-meta"><div>หน่วยจัดซื้อ<strong>${esc(p.agency || '—')}</strong></div><div>วงเงินงบประมาณ<strong>${esc(money(p.budget))}</strong></div><div>รับข้อมูลล่าสุด<strong>${esc(date(p.last_seen_at))}</strong></div></div></div><div class="card-actions"><button type="button" data-raw="${esc(p.project_id)}">ดู JSON ดิบ</button><a href="${esc(p.source_url)}" target="_blank" rel="noopener noreferrer">ตรวจบน e-GP ↗</a></div></article>`).join('');
    $('empty').hidden = data.count > 0;
    $('pageLabel').textContent = `หน้า ${num(currentPage)} จาก ${num(Math.max(1, Math.ceil(data.count / data.page_size)))}`;
    $('prev').disabled = currentPage <= 1;
    $('next').disabled = currentPage * data.page_size >= data.count;
    latestCount = data.count;
  } catch (error) { status(error.message); }
}
$('filters').addEventListener('submit', event => {event.preventDefault(); currentPage=1; refresh();});
$('prev').addEventListener('click', () => {if (currentPage>1) {currentPage--;refresh();}});
$('next').addEventListener('click', () => {if (currentPage*30<latestCount) {currentPage++;refresh();}});
$('projectRows').addEventListener('click', async event => {
  const id = event.target.closest('[data-raw]')?.dataset.raw;
  if (!id) return;
  try {
    const response = await fetch('/api/project?id=' + encodeURIComponent(id));
    const data = await response.json();
    if (!response.ok) throw Error(data.error);
    $('rawTitle').textContent = `โครงการ ${id}`;
    $('rawContent').textContent = JSON.stringify(data.raw, null, 2);
    $('rawDialog').showModal();
  } catch (error) { status(error.message); }
});
$('closeRaw').addEventListener('click', () => $('rawDialog').close());
localPost({type:'HELLO'});
setTimeout(() => { if (!extensionId) status('ยังไม่พบส่วนขยายใน Edge · ติดตั้งแล้วโหลดหน้านี้ใหม่'); }, 1500);
refresh();
setInterval(refresh, 3000);
