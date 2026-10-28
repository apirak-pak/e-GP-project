const $ = (id) => document.getElementById(id);
let projects = [];
let toastTimer;
let activeFilters = new URLSearchParams();
let currentPage = 1;
let projectPageSize = 50;
let projectPageTotal = 1;
let refreshSequence = 0;
let selectedWinner = "";
let winnerPage = 1;
let winnerPageTotal = 1;
let winnerSequence = 0;

const money = (value) => value == null ? "—" : new Intl.NumberFormat("th-TH", { maximumFractionDigits: 2 }).format(value) + " ฿";
const thaiDate = (value) => {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || "")) return value || "—";
  return new Date(`${value}T00:00:00Z`).toLocaleDateString("th-TH", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
};
const shortMoney = (value) => {
  if (value == null) return "—";
  if (value >= 1_000_000_000) return (value / 1_000_000_000).toLocaleString("th-TH", { maximumFractionDigits: 2 }) + " พันล้าน ฿";
  if (value >= 1_000_000) return (value / 1_000_000).toLocaleString("th-TH", { maximumFractionDigits: 2 }) + " ล้าน ฿";
  return money(value);
};
const safe = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"})[char]);
const statusClass = (status) => ({"ประกาศใหม่":"status-new","ระหว่างประมูล":"status-bidding","ประกาศผู้ชนะ":"status-won","ทำสัญญาแล้ว":"status-won"})[status] || "status-other";
const workArea = (row) => row.province && row.province !== "ไม่ระบุพื้นที่โครงการ" ? row.province : "ยังระบุไม่ได้";
const agencyArea = (row) => row.agency_province || "ไม่ระบุจังหวัดหน่วยจัดซื้อ";
const REVIEW_KEY = "egp-radar.project-marks.v1";
let projectMarks = {};
try {
  const stored = JSON.parse(localStorage.getItem(REVIEW_KEY) || "{}");
  if (stored && typeof stored === "object" && !Array.isArray(stored)) projectMarks = stored;
} catch { /* Cards remain usable when local storage is unavailable. */ }
function projectMark(id) {
  const value = Object.hasOwn(projectMarks,id) ? projectMarks[id] : null;
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}
const cardIcons = {
  interested: '<path d="m5 12 4 4L19 6"/>',
  skip: '<path d="m6 6 12 12M18 6 6 18"/>',
  saved: '<path d="M6 4h12v17l-6-4-6 4z"/>',
  link: '<path d="m10 13 4-4m-6 7-1 1a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0m2 1 1-1a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0"/>',
};
const cardIcon = name => `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${cardIcons[name]}</svg>`;

function projectTimeline(row) {
  const hasWinner = Boolean(row.winner && ["ประกาศผู้ชนะ", "ทำสัญญาแล้ว"].includes(row.status));
  const hasContract = row.status === "ทำสัญญาแล้ว";
  const events = [
    {label:"วันที่ประกาศ", value:row.announced_at ? thaiDate(row.announced_at) : "ยังไม่มีข้อมูล", known:Boolean(row.announced_at)},
    {label:"ยื่นข้อเสนอ", value:"ยังไม่มีข้อมูล", known:false},
    {label:"พิจารณาผล", value:"ยังไม่มีข้อมูล", known:false},
    {label:"ผู้ชนะ", value:hasWinner ? "มีข้อมูลผู้ชนะ" : "ยังไม่มีข้อมูล", known:hasWinner},
    {label:"สัญญา", value:hasContract ? "มีข้อมูลสัญญา" : "ยังไม่มีข้อมูล", known:hasContract},
  ];
  return `<ol class="project-timeline" aria-label="ข้อมูลตามขั้นตอนโครงการ">${events.map(event=>`<li class="${event.known ? 'known' : 'unknown'}"><span class="timeline-dot" aria-hidden="true">${event.known ? '✓' : ''}</span><span class="timeline-label">${event.label}</span><span class="timeline-value">${safe(event.value)}</span></li>`).join('')}</ol>`;
}

function renderProjectCards(rows) {
  $("projectRows").innerHTML = rows.map((row,index)=>{
    const mark = projectMark(row.project_id);
    const actions = [
      ['interested','ทำเครื่องหมายสนใจ',mark.review === 'interested'],
      ['skip','ทำเครื่องหมายไม่สนใจ',mark.review === 'skip'],
      ['saved','ติดตามบนเบราว์เซอร์นี้',Boolean(mark.saved)],
      ['link','คัดลอกลิงก์ค้นหาโครงการบนเครื่องนี้',false],
    ];
    const info = (label,value,missing=false) => `<div class="card-fact"><dt>${label}</dt><dd${missing ? ' class="missing-value"' : ''}>${safe(value)}</dd></div>`;
    return `<article class="project-card" data-index="${index}" aria-labelledby="project-title-${index}">
      <div class="project-card-bar"><div class="card-identity"><span class="status ${statusClass(row.status)}">${safe(row.status)}</span><span class="card-project-id">เลขที่โครงการ <strong>${safe(row.project_id)}</strong></span>${row.is_demo ? '<span class="demo-label">ข้อมูลตัวอย่าง</span>' : ''}</div><div class="card-actions">${actions.map(([action,label,active])=>`<button type="button" class="card-action action-${action}${active ? ' is-active' : ''}" data-action="${action}" aria-label="${label}" title="${label}"${action !== 'link' ? ` aria-pressed="${Boolean(active)}"` : ''}>${cardIcon(action)}</button>`).join('')}</div></div>
      <div class="project-card-body"><h3 id="project-title-${index}"><button type="button" class="project-title-button" data-action="details">${safe(row.title)}</button></h3>
      <dl class="card-facts">${info('หน่วยงาน',row.agency || 'ยังไม่มีข้อมูล')}${info('ประเภทงาน',row.project_type || 'ยังไม่มีข้อมูล')}${info('จังหวัดหน่วยจัดซื้อ',agencyArea(row))}${info('พื้นที่โครงการ',workArea(row))}${info('เกณฑ์พิจารณา','ไม่มีข้อมูลในชุดที่เก็บ',true)}${info('ผลงานขั้นต่ำ','ไม่มีข้อมูลในชุดที่เก็บ',true)}</dl>
      ${projectTimeline(row)}
      <div class="card-price-row"><div><span>งบประมาณ</span><strong>${safe(money(row.budget))}</strong></div><div><span>ราคากลาง</span><strong>${safe(money(row.reference_price))}</strong></div><div><span>ราคาที่ชนะ</span><strong>${safe(money(row.winning_price))}</strong></div><button type="button" class="card-details-button" data-action="details">ดูรายละเอียด <span aria-hidden="true">›</span></button></div>
      </div></article>`;
  }).join('');
}

function notify(message, error = false) {
  const node = $("toast");
  node.textContent = message;
  node.classList.toggle("error", error);
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.hidden = true; }, 4500);
}

async function request(path, options = {}) {
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "เกิดข้อผิดพลาด");
  return result;
}

async function post(path, data = {}) {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

function setOptions(id, items, placeholder, counts = null) {
  const select = $(id);
  const current = select.value;
  select.replaceChildren();
  const first = new Option(placeholder, "");
  select.add(first);
  for (const item of items) select.add(new Option(counts ? `${item} (${(counts[item] || 0).toLocaleString("th-TH")})` : item, item));
  select.value = [...select.options].some((option) => option.value === current) ? current : "";
}

function selectedProvinces() {
  return [...$("provinceOptions").querySelectorAll('input[name="province"]:checked')].map((input) => input.value);
}

function updateProvinceSummary() {
  const names = selectedProvinces();
  $("provinceSummary").textContent = names.length === 0 ? "ทุกพื้นที่" : names.length <= 2 ? names.join(", ") : `เลือก ${names.length} จังหวัด`;
}

function filterProvinceOptions() {
  const query = $("provinceSearch").value.trim().toLocaleLowerCase("th-TH");
  $("provinceOptions").querySelectorAll(".province-option").forEach((option) => {
    option.hidden = !option.dataset.province.toLocaleLowerCase("th-TH").includes(query);
  });
}

function renderProvinceOptions(items, counts) {
  const selected = new Set(selectedProvinces());
  $("provinceOptions").innerHTML = items.map((name) => `
    <label class="province-option" data-province="${safe(name)}">
      <input type="checkbox" name="province" value="${safe(name)}" ${selected.has(name) ? "checked" : ""}>
      <span>${safe(name)}</span><small>${(counts[name] || 0).toLocaleString("th-TH")}</small>
    </label>`).join("");
  updateProvinceSummary();
  filterProvinceOptions();
}

function selectedFilters() {
  const values = new FormData($("filters"));
  const query = new URLSearchParams();
  for (const [key, value] of values.entries()) {
    if (String(value).trim()) query.append(key, String(value).trim());
  }
  return query;
}

function renderProjects(rows, pagination) {
  renderProjectCards(rows);
  $("emptyState").hidden = rows.length !== 0;
  const { total, offset, page_size } = pagination;
  projectPageSize = page_size;
  currentPage = Math.floor(offset / page_size) + 1;
  projectPageTotal = Math.max(1, Math.ceil(total / page_size));
  $("tableCount").textContent = total.toLocaleString("th-TH");
  $("visibleCount").textContent = total ? `รายการ ${(offset + 1).toLocaleString("th-TH")}–${(offset + rows.length).toLocaleString("th-TH")} จาก ${total.toLocaleString("th-TH")}` : "ไม่มีรายการ";
  $("projectPage").value = currentPage;
  $("projectPage").max = projectPageTotal;
  $("pageTotal").textContent = `/ ${projectPageTotal.toLocaleString("th-TH")}`;
  $("previousPage").disabled = currentPage <= 1;
  $("nextPage").disabled = currentPage >= projectPageTotal;
  $("goToPage").disabled = total === 0;
  $("emptyExplanation").textContent = selectedProvinces().length
    ? "ยังไม่มีรายการที่ตรงเงื่อนไขในฐานข้อมูล ไม่ได้หมายความว่าพื้นที่เหล่านี้ไม่มีโครงการจริง"
    : "ข้อมูล DGA ดิบเก็บไว้เพื่อเลือกฟิลด์ก่อน ยังไม่แปลงเป็นการ์ดโครงการ";
}

function renderMarket(data) {
  const { summary, shares, meta, filters } = data;
  const areas = filters.provinces;
  $("marketScope").textContent = `จังหวัดหน่วยจัดซื้อ: ${areas.length === 0 ? "ทุกจังหวัด" : areas.length <= 3 ? areas.join(", ") : `${areas.slice(0, 3).join(", ")} และอีก ${areas.length - 3} จังหวัด`}`;
  $("marketTotal").textContent = `${summary.share_project_total.toLocaleString("th-TH")} งานที่ระบุผู้ชนะ`;
  $("marketRows").innerHTML = shares.length ? shares.map((row) => `
    <div class="market-row">
      <div class="market-line"><button class="winner-link" type="button" data-winner="${safe(row.winner)}" title="ดูโครงการที่ ${safe(row.winner)} ชนะ">${safe(row.winner)}</button><strong>${safe(row.percent)}%</strong></div>
      <div class="market-bar"><i style="width:${Math.max(0, Math.min(100, row.percent))}%"></i></div>
      <span class="market-sub">ชนะ ${row.count.toLocaleString("th-TH")} งาน</span>
    </div>`).join("") : "<p class='market-note'>ยังไม่มีโครงการที่ระบุชื่อผู้ชนะในเงื่อนไขนี้</p>";
  const notes = ["สัดส่วนนี้แยกตามจังหวัดหน่วยจัดซื้อและคำนวณจากงานที่มีในฐานข้อมูลเท่านั้น ไม่ใช่ส่วนแบ่งตลาดของพื้นที่ก่อสร้าง", "นับหนึ่งโครงการเป็นหนึ่งงาน; ชื่อผู้ชนะที่สะกดต่างกันยังนับแยก"];
  if (summary.share_winner_total > shares.length) notes.push(`แสดง ${shares.length} อันดับแรกจาก ${summary.share_winner_total.toLocaleString("th-TH")} ชื่อผู้ชนะ`);
  if (meta.api_count) notes.push(`ฐานข้อมูลมี ${meta.api_count.toLocaleString("th-TH")} รายการจาก API ซึ่งยังเป็นข้อมูลบางส่วน`);
  if (summary.share_is_demo) notes.unshift("ตัวเลขนี้มาจากข้อมูลตัวอย่างเท่านั้น");
  if (summary.excluded_winner_count) notes.push(`ไม่รวม ${summary.excluded_winner_count.toLocaleString("th-TH")} งานที่ไม่มีชื่อผู้ชนะ`);
  $("marketNote").textContent = notes.join(" · ");
}

function render(data) {
  projects = data.projects;
  $("statCount").textContent = data.summary.count.toLocaleString("th-TH");
  $("statBudget").textContent = shortMoney(data.summary.budget_total);
  $("statProvinces").textContent = data.summary.province_count.toLocaleString("th-TH");
  $("statWinners").textContent = data.summary.winner_count.toLocaleString("th-TH");
  const updated = data.meta.updated_at;
  $("lastUpdated").textContent = updated ? `อัปเดตในเครื่อง ${new Date(updated).toLocaleString("th-TH")}` : "ยังไม่มีข้อมูล";
  renderProvinceOptions(data.meta.provinces, data.meta.province_counts);
  setOptions("manualProvince", data.meta.province_reference, "เลือกจังหวัด");
  setOptions("manualAgencyProvince", data.meta.province_reference, "เลือกจังหวัด");
  setOptions("project_type", data.meta.project_types, "ทุกประเภท");
  setOptions("status", data.meta.statuses, "ทุกสถานะ");
  renderProjects(projects, data.pagination);
  renderMarket(data);
  const demoCount = data.meta.demo_count;
  const realCount = data.meta.total_in_database - demoCount;
  $("notice").querySelector("strong").textContent = data.meta.raw_mode ? "กำลังตรวจข้อมูลดิบจาก DGA" : data.meta.api_count ? `มีข้อมูลจาก API ใน ${data.meta.covered_province_count} จังหวัด` : demoCount ? "ข้อมูลตัวอย่างอยู่ในระบบ" : "ต้นแบบบนเครื่องของคุณ";
  $("notice").querySelector("span").textContent = data.meta.api_count
    ? `ข้อมูลโครงการและสัญญา ${data.meta.api_count.toLocaleString("th-TH")} รายการที่เก็บไว้ · ยังไม่ครบทุกผลค้นหา · วันยื่นข้อเสนอและเงื่อนไขเข้าร่วมยังไม่มีในชุดนี้${demoCount ? ` · มีข้อมูลจำลองอีก ${demoCount} รายการ` : ""}`
    : data.meta.raw_mode ? `เก็บคำตอบ API ${data.meta.raw_captures.toLocaleString("th-TH")} ชุด รวม ${data.meta.raw_projects.toLocaleString("th-TH")} รายการดิบในฐานใหม่ · ยังไม่เลือกฟิลด์เพื่อแสดงบนการ์ด` : demoCount ? `มีข้อมูลจำลอง ${demoCount} รายการในฐานข้อมูล · ตัวเลขเหล่านี้ไม่ใช่ผลจัดซื้อจัดจ้างจริง` : realCount ? "ข้อมูลปัจจุบันมาจากรายการที่บันทึกหรือนำเข้าเอง" : "ฐานแดชบอร์ดยังไม่มีโครงการ ข้อมูล DGA ดิบจะยังไม่แสดงจนกว่าจะตรวจและเลือกฟิลด์";
  $("sampleButton").hidden = data.meta.raw_mode || demoCount > 0 || realCount > 0;
  $("clearSampleButton").hidden = demoCount === 0;
  $("addButton").hidden = data.meta.raw_mode;
  $("importButton").hidden = data.meta.raw_mode;
}

async function refresh(page = 1, applyForm = false) {
  try {
    const sequence = ++refreshSequence;
    const pageChanged = page !== currentPage;
    const requestedFilters = applyForm ? selectedFilters() : activeFilters;
    const query = new URLSearchParams(requestedFilters);
    query.set("offset", String((page - 1) * projectPageSize));
    const data = await request("/api/dashboard?" + query);
    if (sequence === refreshSequence) {
      if (applyForm) activeFilters = new URLSearchParams(requestedFilters);
      render(data);
      if (pageChanged && !applyForm) $("projects").scrollIntoView({ block: "start" });
    }
  } catch (error) {
    notify(error.message, true);
  }
}

function showDetails(row) {
  $("detailTitle").textContent = row.title;
  const sourceLabel = { demo: "ข้อมูลจำลอง", csv: `ไฟล์ CSV: ${row.source_name || "ไม่ทราบชื่อไฟล์"}`, manual: "บันทึกด้วยมือ", api: "EGP-CONTRACT API (ข้อมูลการทำสัญญา)" }[row.source_kind] || row.source_kind;
  const locationRemark = !row.agency_province
    ? "รายการนี้ไม่ได้ระบุจังหวัดหน่วยจัดซื้อ จึงไม่ปรากฏเมื่อเลือกกรองจังหวัด"
    : row.province === "ไม่ระบุพื้นที่โครงการ"
      ? "ทราบจังหวัดหน่วยจัดซื้อ แต่ยังยืนยันจังหวัดที่ก่อสร้างไม่ได้"
      : row.province !== row.agency_province
        ? `หน่วยจัดซื้ออยู่${row.agency_province} แต่งานก่อสร้างอยู่${row.province} ตามข้อมูลที่มี`
        : "จังหวัดหน่วยจัดซื้อและพื้นที่งานที่บันทึกไว้ตรงกัน โปรดตรวจประกาศต้นทางก่อนใช้ตัดสินใจ";
  const fields = [
    ["รหัสโครงการ", row.project_id], ["จังหวัดหน่วยจัดซื้อ", agencyArea(row)], ["จังหวัดที่ตั้งงาน", workArea(row)],
    ["ที่มาของจังหวัดที่ตั้งงาน", row.source_kind === "api" ? (row.province_source === "title" ? "ระบุชัดในชื่อประกาศ" : "ยังระบุไม่ได้") : "ข้อมูลที่ผู้บันทึกระบุ"],
    ["ที่มาของข้อมูล", sourceLabel],
    ["ประเภทงาน", row.project_type], ["หน่วยงาน", row.agency],
    ["สถานะ", row.status], ["วันที่ประกาศ", thaiDate(row.announced_at)],
    ["วงเงินงบประมาณ", money(row.budget)], ["ราคากลาง", money(row.reference_price)],
    ["ราคาที่ชนะ", money(row.winning_price)], ["ผู้ชนะ", row.winner],
  ];
  const url = row.source_url && /^https?:\/\//i.test(row.source_url) ? row.source_url : "";
  $("detailBody").innerHTML = `${row.is_demo ? "<p>ข้อมูลตัวอย่างเพื่อทดสอบหน้าจอ ไม่ใช่ประกาศจริง</p>" : ""}<div class="detail-status"><span class="status ${statusClass(row.status)}">${safe(row.status)}</span><span>เลขที่โครงการ ${safe(row.project_id)}</span></div>${projectTimeline(row)}<p class="location-remark">${safe(locationRemark)}</p><div class="detail-grid">${fields.map(([label, value]) => `<div class="detail-item"><small>${safe(label)}</small><strong>${safe(value || "—")}</strong></div>`).join("")}</div><p class="detail-availability">กำหนดยื่นข้อเสนอ เกณฑ์พิจารณา และผลงานขั้นต่ำ: ยังไม่มีในชุดข้อมูลที่เก็บ ไม่ใช้สถานะนี้ยืนยันว่าเปิดรับประมูลอยู่</p>${url ? `<a class="detail-link" href="${safe(url)}" target="_blank" rel="noopener noreferrer">เปิดประกาศต้นทาง ↗</a>` : "<p>ยังไม่มีลิงก์ประกาศต้นทาง</p>"}`;
  $("detailDialog").showModal();
}

function renderWinnerProjects(data) {
  const { winner, filters, projects: rows, pagination, summary } = data;
  selectedWinner = winner;
  winnerPage = Math.floor(pagination.offset / pagination.page_size) + 1;
  winnerPageTotal = Math.max(1, Math.ceil(pagination.total / pagination.page_size));
  $("winnerTitle").textContent = winner;
  $("winnerScope").textContent = `จังหวัดหน่วยจัดซื้อ: ${filters.provinces.length ? filters.provinces.join(", ") : "ทุกจังหวัด"} · พื้นที่ก่อสร้างจริงอาจต่างกัน`;
  const totalPrice = summary.priced_count ? money(summary.winning_price_total) : "ยังไม่มีราคาที่ชนะ";
  $("winnerSummary").innerHTML = `<strong>ชนะ ${summary.count.toLocaleString("th-TH")} งาน</strong><span>ราคาที่ชนะรวม ${safe(totalPrice)} · มีราคา ${summary.priced_count.toLocaleString("th-TH")} จาก ${summary.count.toLocaleString("th-TH")} งาน${summary.is_demo ? " · ข้อมูลตัวอย่าง" : ""}</span>`;
  $("winnerProjects").innerHTML = rows.length ? rows.map((row) => `
    <article class="winner-project">
      <h3>${safe(row.title)}</h3>
      <p>หน่วยจัดซื้อ: ${safe(agencyArea(row))} · พื้นที่งาน: ${safe(workArea(row))} · ${safe(thaiDate(row.announced_at))} · รหัส ${safe(row.project_id)}</p>
      <div class="winner-values"><span>ราคาที่ชนะ <strong>${safe(money(row.winning_price))}</strong></span><span>วงเงินงบประมาณ <strong>${safe(money(row.budget))}</strong></span></div>
    </article>`).join("") : "<p>ไม่พบโครงการในหน้านี้</p>";
  $("winnerPageLabel").textContent = `หน้า ${winnerPage.toLocaleString("th-TH")} / ${winnerPageTotal.toLocaleString("th-TH")}`;
  $("winnerPrevious").disabled = winnerPage <= 1;
  $("winnerNext").disabled = winnerPage >= winnerPageTotal;
}

async function showWinner(winner, page = 1) {
  const sequence = ++winnerSequence;
  selectedWinner = winner;
  $("winnerTitle").textContent = winner;
  $("winnerSummary").textContent = "";
  $("winnerProjects").textContent = "กำลังโหลดโครงการ...";
  $("winnerPageLabel").textContent = "";
  $("winnerPrevious").disabled = true;
  $("winnerNext").disabled = true;
  if (!$("winnerDialog").open) $("winnerDialog").showModal();
  const query = new URLSearchParams(activeFilters);
  query.set("winner", winner);
  query.set("offset", String((page - 1) * projectPageSize));
  try {
    const data = await request("/api/winner-projects?" + query);
    if (sequence === winnerSequence) renderWinnerProjects(data);
  } catch (error) {
    if (sequence === winnerSequence) $("winnerProjects").textContent = error.message;
  }
}

$("provinceOptions").addEventListener("change", updateProvinceSummary);
$("provinceSearch").addEventListener("input", filterProvinceOptions);
$("clearProvinces").addEventListener("click", () => {
  $("provinceOptions").querySelectorAll('input[name="province"]').forEach((input) => { input.checked = false; });
  updateProvinceSummary();
});
$("provincePicker").addEventListener("keydown", (event) => {
  if (event.key === "Escape") $("provincePicker").open = false;
});
$("filters").addEventListener("submit", (event) => {
  event.preventDefault();
  $("provincePicker").open = false;
  refresh(1, true);
});
$("resetFilters").addEventListener("click", () => {
  $("filters").reset();
  $("provinceOptions").querySelectorAll('input[name="province"]').forEach((input) => { input.checked = false; });
  $("provinceSearch").value = "";
  $("provincePicker").open = false;
  updateProvinceSummary();
  filterProvinceOptions();
  refresh(1, true);
});
$("previousPage").addEventListener("click", () => refresh(currentPage - 1));
$("nextPage").addEventListener("click", () => refresh(currentPage + 1));
function goToProjectPage() {
  const page = Number($("projectPage").value);
  if (!Number.isInteger(page) || page < 1 || page > projectPageTotal) {
    notify(`เลือกหน้า 1–${projectPageTotal.toLocaleString("th-TH")}`, true);
    $("projectPage").value = currentPage;
    return;
  }
  refresh(page);
}
$("goToPage").addEventListener("click", goToProjectPage);
$("projectPage").addEventListener("keydown", (event) => {
  if (event.key === "Enter") { event.preventDefault(); goToProjectPage(); }
});
$("marketRows").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-winner]");
  if (button) showWinner(button.dataset.winner);
});
$("winnerPrevious").addEventListener("click", () => showWinner(selectedWinner, winnerPage - 1));
$("winnerNext").addEventListener("click", () => showWinner(selectedWinner, winnerPage + 1));
$("addButton").addEventListener("click", () => $("projectDialog").showModal());
$("importButton").addEventListener("click", () => $("importDialog").showModal());
document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => $(button.dataset.close).close()));
$("projectRows").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  const card = button?.closest(".project-card[data-index]");
  if (!card) return;
  const row = projects[Number(card.dataset.index)];
  const action = button.dataset.action;
  if (action === "details") { showDetails(row); return; }
  if (action === "link") {
    const url = new URL(location.origin); url.searchParams.set('q',row.project_id);
    try { await navigator.clipboard.writeText(url.href); notify('คัดลอกลิงก์ค้นหาโครงการบนเครื่องนี้แล้ว'); }
    catch { notify('คัดลอกไม่ได้ กรุณาใช้เลขโครงการ ' + row.project_id,true); }
    return;
  }
  if (!["saved","interested","skip"].includes(action)) return;
  const previous = projectMark(row.project_id);
  const mark = {review:previous.review || '',saved:Boolean(previous.saved)};
  if (action === 'saved') mark.saved = !mark.saved;
  else mark.review = mark.review === action ? '' : action;
  const next = {...projectMarks,[row.project_id]:mark};
  try { localStorage.setItem(REVIEW_KEY,JSON.stringify(next)); }
  catch { notify('บันทึกไม่ได้ เบราว์เซอร์ไม่อนุญาตพื้นที่จัดเก็บ',true); return; }
  projectMarks = next;
  const index = card.dataset.index;
  renderProjectCards(projects);
  document.querySelector(`.project-card[data-index="${index}"] [data-action="${action}"]`)?.focus({preventScroll:true});
  notify('บันทึกเครื่องหมายบนเบราว์เซอร์นี้แล้ว');
});

$("projectForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = Object.fromEntries(new FormData(event.target));
  try {
    const result = await post("/api/projects", payload);
    $("projectDialog").close();
    event.target.reset();
    notify(result.message);
    await refresh();
  } catch (error) { notify(error.message, true); }
});

$("importSubmit").addEventListener("click", async () => {
  const file = $("csvFile").files[0];
  if (!file) { notify("กรุณาเลือกไฟล์ CSV", true); return; }
  if (file.size > 5_000_000) { notify("ไฟล์ต้องไม่เกิน 5 MB", true); return; }
  $("importSubmit").disabled = true;
  try {
    const result = await post("/api/import", { filename: file.name, csv: await file.text() });
    $("importDialog").close();
    $("csvFile").value = "";
    notify(result.message);
    await refresh();
  } catch (error) { notify(error.message, true); }
  finally { $("importSubmit").disabled = false; }
});

$("sampleButton").addEventListener("click", async () => {
  try { const result = await post("/api/demo/load"); notify(result.message); await refresh(); }
  catch (error) { notify(error.message, true); }
});
$("clearSampleButton").addEventListener("click", async () => {
  try { const result = await post("/api/demo/clear"); notify(result.message); await refresh(); }
  catch (error) { notify(error.message, true); }
});

function updateNavigation() {
  const section = location.hash || "#projects";
  document.querySelectorAll(".nav-link").forEach((link) => {
    const active = link.getAttribute("href") === section;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
}
window.addEventListener("hashchange", updateNavigation);
updateNavigation();
const initialSearch = new URLSearchParams(location.search).get('q');
if (initialSearch) $("q").value = initialSearch;
activeFilters = selectedFilters();
refresh();
