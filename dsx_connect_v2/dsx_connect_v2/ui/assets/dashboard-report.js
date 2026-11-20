/* A report freezes only displayed widget content, never connector configuration. */
function reportEscape(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[character]));
}

function reportUtc(value) {
  return new Date(value).toISOString().replace("T", " ").replace(/\.\d{3}Z$/, " UTC");
}

function cleanReportNode(original) {
  const clone = original.cloneNode(true);
  clone.removeAttribute("popover");
  clone.removeAttribute("hidden");
  clone.querySelectorAll("script,style,iframe,object,embed,img,image,video,audio,template,input,select,textarea,form,[hidden],.hidden,[popover],.dashboard-chart-tooltip,.dashboard-hover-marker,[data-dashboard-compare],[data-scan-bucket],.dashboard-copy-status").forEach((node) => node.remove());
  clone.querySelectorAll("button").forEach((button) => {
    if (!button.classList.contains("dashboard-kpi")) { button.remove(); return; }
    const card = document.createElement("div");
    card.className = button.className;
    card.append(...button.childNodes);
    button.replaceWith(card);
  });
  clone.querySelectorAll("a").forEach((link) => link.replaceWith(...link.childNodes));
  [clone, ...clone.querySelectorAll("*")].forEach((node) => {
    for (const attribute of [...node.attributes]) {
      if (/^on/i.test(attribute.name) || ["tabindex", "autofocus", "popovertarget", "inert"].includes(attribute.name)) node.removeAttribute(attribute.name);
    }
    if (node.tagName.toLowerCase() === "svg") node.setAttribute("preserveAspectRatio", "xMidYMid meet");
  });
  return clone;
}

function reportNodeText(node) {
  const clone = node.cloneNode(true);
  clone.querySelectorAll("svg").forEach((svg) => svg.remove());
  clone.querySelectorAll("br").forEach((br) => br.replaceWith("\n"));
  clone.querySelectorAll("td,th,.dashboard-bar-row > *").forEach((cell) => cell.append("\t"));
  clone.querySelectorAll(".dashboard-kpi > *").forEach((line) => line.append("\n"));
  clone.querySelectorAll("h1,h2,h3,h4,p,li,tr,section,.dashboard-list-row,.dashboard-bar-row,.dashboard-kpi,.dashboard-actions").forEach((block) => block.append("\n"));
  return clone.textContent.replace(/[ \t]+/g, " ").replace(/ *\n */g, "\n").replace(/\n{3,}/g, "\n\n").trim();
}

function collectDashboardReport({data, history, integrationId, days, generatedAt = new Date().toISOString()}) {
  const selected = Number(days);
  const reference = history || data.coverage || data.worker_time || data.dsxa_time;
  const floor = new Date(generatedAt);
  floor.setUTCMinutes(0, 0, 0);
  if (selected !== 1) floor.setUTCHours(0);
  const fallbackStart = new Date(floor.getTime() - (selected === 1 ? 23 * 3600000 : (selected - 1) * 86400000)).toISOString();
  const connectorRows = (data.connectors?.connectors || []).filter((row) => !integrationId || row.integration.integration_id === integrationId);
  const connectors = connectorRows.map(({integration}) => ({id:integration.integration_id, name:integration.display_name, enabled:integration.enabled}));
  const warnings = [];
  const dashboardWarning = document.getElementById("dashboard-error").textContent.trim();
  if (dashboardWarning) warnings.push(dashboardWarning);
  const incomplete = (data.coverage?.inventory || []).filter((row) => row.state !== "complete");
  if (incomplete.length) warnings.push(`Asset inventory is incomplete for ${incomplete.length} connector${incomplete.length === 1 ? "" : "s"}. Coverage totals reflect the known inventory.`);
  if (!connectors.length) warnings.push("The connector list is unavailable or empty; connector coverage could not be confirmed.");
  const historical = new Set(["dashboard-under-load", "dashboard-job-activity", "dashboard-job-duration", "dashboard-history", "dashboard-backlog", "dashboard-latency", "dashboard-throughput", "dashboard-quarantine", "dashboard-types"]);
  const scopes = {
    "dashboard-kpis":"Current connector and scope configuration, plus up to 50 recent jobs. These figures are not restricted to the reporting window.",
    "dashboard-coverage":"Recorded asset inventory and protection capabilities over the reporting window.",
    "dashboard-work":"Item states across up to 50 recent jobs; not restricted to the reporting window.",
    "dashboard-outcomes":"Sampled findings across up to 50 recent jobs; not lifetime totals or a complete period total.",
    "dashboard-attention":"Issues identified in the latest available health and recent-job data; a current snapshot.",
    "dashboard-connectors":"Connector health at the latest available refresh; a current snapshot.",
    "dashboard-jobs":"Up to eight displayed jobs from up to 50 recent jobs; not restricted to the reporting window.",
  };
  const sections = [];
  const add = (id, title, card, target) => {
    const source = historical.has(id) ? history : id === "dashboard-coverage" ? data.coverage
      : id === "dashboard-worker-time" ? data.worker_time : id === "dashboard-dsxa-time" ? data.dsxa_time
      : id === "dashboard-outcomes" ? data.results : id === "dashboard-connectors" ? data.connectors : data.overview;
    const graphic = cleanReportNode(target.tagName === "TBODY" ? target.closest("table") : target);
    const info = card?.querySelector(".dashboard-info-popover");
    const supporting = info ? cleanReportNode(info) : null;
    const description = card?.querySelector(":scope > p.dashboard-muted")?.textContent.trim() || "";
    const section = {
      id, title, description, scope:scopes[id] || "Selected reporting window.",
      asOf:source?.end || null, available:Boolean(source),
      graphicHtml:graphic.outerHTML, supportingHtml:supporting?.innerHTML || "",
      text:[description, reportNodeText(graphic), supporting ? reportNodeText(supporting) : ""].filter(Boolean).join("\n\n"),
    };
    if (!section.available) warnings.push(`${title}: its source data was unavailable at capture time.`);
    sections.push(section);
  };
  const visible = (node) => !node.closest("[hidden], .hidden") && getComputedStyle(node).display !== "none";
  const kpis = document.getElementById("dashboard-kpis");
  if (kpis && visible(kpis)) add(kpis.id, "Operational overview", null, kpis);
  [...document.querySelectorAll("#dashboard-grid > .dashboard-card")].filter(visible).sort((a, b) => {
    const left = a.getBoundingClientRect(), right = b.getBoundingClientRect();
    return left.top - right.top || left.left - right.left;
  }).forEach((card) => {
    const target = card.querySelector("[data-dashboard-widget]");
    if (target && visible(card) && visible(target)) add(target.id, card.querySelector("h3")?.textContent.trim() || target.id, card, target);
  });
  return {
    title:"DSX-Connect Operator Report", generatedAt, days:selected,
    start:reference?.start || fallbackStart, end:generatedAt,
    connectorSelection:integrationId ? connectors[0]?.name || integrationId : "All connectors",
    connectors, warnings:[...new Set(warnings)], sections,
    captureNote:"This is a fixed snapshot of the displayed dashboard. Widgets use their latest successful refreshes, which may differ. Each section states whether it covers the selected window or current/recent records. Charts and figures do not update after capture.",
  };
}

function dashboardReportText(report) {
  return [report.title, `Range: ${reportUtc(report.start)} to ${reportUtc(report.end)} (${report.days}d selected)`,
    `Generated: ${reportUtc(report.generatedAt)}`, `Connectors: ${report.connectorSelection}`,
    ...report.connectors.map((row) => `- ${row.name}${row.enabled ? "" : " (disabled)"}`), report.captureNote,
    ...(report.warnings.length ? ["Coverage and data warnings", ...report.warnings.map((warning) => `- ${warning}`)] : []),
    ...report.sections.map((section, index) => [`${index + 1}. ${section.title}`, section.scope,
      section.asOf ? `Data through: ${reportUtc(section.asOf)}` : "Captured current/recent snapshot.",
      section.available ? "" : "Source unavailable at capture time.", section.text].filter(Boolean).join("\n")),
  ].join("\n\n");
}

function dashboardReportHtml(report) {
  const e = reportEscape;
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>${e(report.title)}</title><style>
    :root{color-scheme:light;--surface:#fff;--ink:#17233a;--text:#17233a;--muted:#5b677a;--line:#d8e0e8;--accent:#007fa8;--good:#187c4b;--warn:#9d6c00;--danger:#b62e42;--violet:#7c3aed}
    *{box-sizing:border-box}body{margin:0;background:#edf1f5;color:var(--ink);font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:1040px;margin:24px auto;background:white;padding:44px 52px;border:1px solid var(--line)}h1{font-size:30px;line-height:1.2;margin:8px 0 24px}h2{font-size:22px;margin:0 0 8px;break-after:avoid}h3,h4{font-size:15px;margin:18px 0 6px;break-after:avoid}p{margin:6px 0 12px}ul{padding-left:22px}.eyebrow{color:var(--accent);text-transform:uppercase;letter-spacing:.12em;font-size:11px;font-weight:700}.metadata{display:grid;grid-template-columns:130px 1fr;gap:6px 16px;margin:0 0 20px}.metadata dt{font-weight:650}.metadata dd{margin:0}.muted,.dashboard-muted{color:var(--muted);font-size:12px}.warning{border-left:4px solid var(--warn);background:#fff7e5;padding:12px 16px;margin:22px 0}.report-section{border-top:1px solid var(--line);margin-top:30px;padding-top:26px}.figure{margin:18px 0;break-inside:avoid}.figure>div>strong{display:block;margin-bottom:8px}.supporting{margin-top:16px}.dashboard-timing-summary{white-space:pre-line;line-height:1.7}.supporting section:first-child h4{margin-top:0}.scope{color:var(--muted);font-size:12px}.dashboard-chart svg{width:100%!important;height:230px!important;display:block}.dashboard-chart{margin:12px 0}.dashboard-actions{display:flex;flex-wrap:wrap;gap:10px;font-size:12px}.dashboard-kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.dashboard-kpi{border:1px solid var(--line);border-radius:8px;padding:14px;display:flex;flex-direction:column;gap:6px}.dashboard-kpi strong{font-size:26px}.dashboard-kpi>span{font-size:12px}.dashboard-bar-row{display:grid;grid-template-columns:minmax(150px,1fr) 2fr 80px;gap:14px;align-items:center;margin:9px 0}.dashboard-bar{height:8px;background:#e7edf2;border-radius:4px;overflow:hidden}.dashboard-bar>span{display:block;height:100%;background:var(--accent)}.dashboard-list-row{display:flex;justify-content:space-between;gap:18px;padding:9px 0;border-bottom:1px solid var(--line)}table{width:100%;border-collapse:collapse;font-size:11px;table-layout:fixed}th,td{text-align:left;vertical-align:top;padding:9px 8px;border-bottom:1px solid var(--line);overflow-wrap:anywhere}th{background:#f1f5f8}tr{break-inside:avoid}.table-wrap{overflow:visible}.pill{display:inline-block;font-size:11px}.pill.good{color:var(--good)}.pill.warn{color:var(--warn)}.pill.danger{color:var(--danger)}footer{margin-top:36px;border-top:1px solid var(--line);padding-top:14px;font-size:11px;color:var(--muted)}
    @media(max-width:700px){main{margin:0;padding:24px}.metadata{grid-template-columns:1fr;gap:2px}.metadata dd{margin-bottom:8px}.dashboard-kpis{grid-template-columns:repeat(2,1fr)}}
    @media print{@page{size:auto;margin:16mm}body{background:white;font-size:10pt}main{max-width:none;margin:0;padding:0;border:0}.report-section{margin-top:20px;padding-top:16px}.dashboard-chart svg{height:180px!important}*{-webkit-print-color-adjust:exact;print-color-adjust:exact}h1{font-size:25pt}.figure{break-inside:avoid}p,li{orphans:3;widows:3}}
  </style></head><body><main><header><div class="eyebrow">Operations · Dashboard snapshot</div><h1>${e(report.title)}</h1><dl class="metadata"><dt>Range covered</dt><dd>${e(reportUtc(report.start))} to ${e(reportUtc(report.end))} (${report.days}d selected)</dd><dt>Connectors covered</dt><dd>${e(report.connectorSelection)}${report.connectors.length ? ` (${report.connectors.length})` : ""}<br>${report.connectors.map((row) => e(row.name) + (row.enabled ? "" : " (disabled)")).join(" · ")}</dd><dt>Generated</dt><dd>${e(reportUtc(report.generatedAt))}</dd></dl><p class="muted">${e(report.captureNote)}</p>${report.warnings.length ? `<aside class="warning"><strong>Coverage and data warnings</strong><ul>${report.warnings.map((warning) => `<li>${e(warning)}</li>`).join("")}</ul></aside>` : ""}</header>${report.sections.map((section, index) => `<article class="report-section" data-report-widget="${e(section.id)}"><h2>${index + 1}. ${e(section.title)}</h2><p class="scope">${e(section.scope)}${section.asOf ? ` Data through ${e(reportUtc(section.asOf))}.` : ""}</p>${!section.available ? '<p class="warning">Source data unavailable at capture time.</p>' : ""}${section.description ? `<p class="muted">${e(section.description)}</p>` : ""}<div class="figure">${section.graphicHtml}</div>${section.supportingHtml ? `<div class="supporting">${section.supportingHtml}</div>` : ""}</article>`).join("")}<footer>${e(report.title)} · ${e(reportUtc(report.generatedAt))} · All timestamps UTC. This report captures displayed summaries and samples, not a full audit export.</footer></main></body></html>`;
}
