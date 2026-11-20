function hideDashboardChartHover(svg, tooltip) {
  if (tooltip.matches(":popover-open")) tooltip.hidePopover();
  tooltip.hidden = true;
  const marker = svg.querySelector(".dashboard-hover-marker");
  if (marker) marker.style.display = "none";
}

function bindDashboardChartHover(svg, tooltip) {
  let hideTimer;
  const cancelHide = () => window.clearTimeout(hideTimer);
  const scheduleHide = () => {
    cancelHide();
    hideTimer = window.setTimeout(() => hideDashboardChartHover(svg, tooltip), 200);
  };
  svg.addEventListener("pointerenter", cancelHide);
  svg.addEventListener("pointerleave", scheduleHide);
  tooltip.addEventListener("pointerenter", cancelHide);
  tooltip.addEventListener("pointerleave", scheduleHide);
}

function showDashboardChartHover(svg, tooltip, chartX, points) {
  let marker = svg.querySelector(".dashboard-hover-marker");
  if (!marker) {
    marker = document.createElementNS("http://www.w3.org/2000/svg", "g");
    marker.classList.add("dashboard-hover-marker");
    marker.setAttribute("aria-hidden", "true");
    marker.setAttribute("pointer-events", "none");
    svg.append(marker);
  }
  marker.style.display = "";
  marker.innerHTML = `<line x1="${chartX}" x2="${chartX}" y1="20" y2="108" stroke="var(--muted)" stroke-dasharray="3 3"/>${points.map(([y, color]) => `<circle cx="${chartX}" cy="${y}" r="3.5" fill="var(--surface)" stroke="var(--${color})" stroke-width="2"/>`).join("")}`;
  tooltip.style.maxHeight = "";
  tooltip.hidden = false;
  if (!tooltip.matches(":popover-open")) tooltip.showPopover();
  const chart = svg.getBoundingClientRect();
  const box = tooltip.getBoundingClientRect();
  const viewportWidth = document.documentElement.clientWidth;
  const viewportHeight = document.documentElement.clientHeight;
  const selectedX = chart.left + chartX / 450 * chart.width;
  const plotTop = chart.top + 20 / 140 * chart.height;
  const plotBottom = chart.top + 108 / 140 * chart.height;
  const gap = 12;
  let top = plotTop - box.height - gap;
  if (top < 8) top = plotBottom + gap;
  if (top + box.height > viewportHeight - 8) {
    // When vertical space is limited, use the open side of the chart.
    const right = chart.right + gap;
    const left = chart.left - box.width - gap;
    if (right + box.width <= viewportWidth - 8 || left >= 8) {
      tooltip.style.left = `${left >= 8 ? left : right}px`;
      tooltip.style.top = `${Math.max(8, Math.min(chart.top, viewportHeight - box.height - 8))}px`;
      return;
    }
    const above = Math.max(0, plotTop - gap - 8);
    const below = Math.max(0, viewportHeight - plotBottom - gap - 8);
    tooltip.style.maxHeight = `${Math.max(24, Math.max(above, below))}px`;
    top = above >= below ? 8 : plotBottom + gap;
  }
  tooltip.style.left = `${Math.max(8, Math.min(selectedX - box.width / 2, viewportWidth - box.width - 8))}px`;
  tooltip.style.top = `${top}px`;
}

function dismissDashboardChartHovers(event) {
  if (event?.target?.closest?.(".dashboard-chart-tooltip")) return;
  document.querySelectorAll(".dashboard-chart-tooltip:popover-open").forEach((tooltip) => {
    const svg = tooltip.parentElement.querySelector("svg");
    if (svg) hideDashboardChartHover(svg, tooltip);
  });
}
window.addEventListener("scroll", dismissDashboardChartHovers, true);
window.addEventListener("resize", dismissDashboardChartHovers);
window.addEventListener("keydown", (event) => { if (event.key === "Escape") dismissDashboardChartHovers(); });

const dashboardUnderLoadSignatures = new WeakMap();

function appendDashboardViewAction(tooltip, {at, label = "View records", href, onView}) {
  const action = document.createElement(href ? "a" : "button");
  action.className = "icon-button view-scan-action dashboard-point-view";
  const description = `${label} (${new Date(at).toLocaleString([], {timeZone:"UTC"})} UTC)`;
  action.title = description;
  action.setAttribute("aria-label", description);
  action.innerHTML = iconSvg("eye");
  if (href) action.href = href;
  else { action.type = "button"; action.onclick = onView; }
  const heading = tooltip.querySelector(":scope > strong");
  const row = document.createElement("div");
  row.className = "dashboard-hover-heading";
  if (heading) row.append(heading);
  row.append(action);
  tooltip.prepend(row);
  tooltip.classList.add("is-interactive");
  tooltip.removeAttribute("role");
}

function renderDashboardMetric(id, data, metrics, summary, format, comparisonUrls = [], options = {}) {
  const target = document.getElementById(id);
  if (!target) return;
  const series = data.series;
  const values = series.flatMap((bucket) => metrics.map(([key]) => bucket[key])).filter((value) => value !== null && value !== undefined);
  const hasCompletedScans = series.some((bucket) => metrics.some(([key]) => bucket[`${key}_scans`] > 0));
  if (!values.length && !hasCompletedScans) { updateDashboardWidgetHtml(id, '<p class="dashboard-muted">No data in this period.</p>'); return; }
  const max = Math.max(0, ...values) || 1;
  const maxLabel = values.length ? format(max) : "";
  const plotLeft = Math.max(48, maxLabel.length * 7 + 18);
  const plotRight = 398;
  const plotWidth = plotRight - plotLeft;
  const timeStart = new Date(data.start).getTime(), timeEnd = new Date(data.end).getTime();
  const x = (i) => plotLeft + (data.time_scale
    ? (new Date(series[i].at).getTime() - timeStart) / Math.max(1, timeEnd - timeStart)
    : i / Math.max(1, series.length - 1)) * plotWidth;
  const y = (n) => 95 - n / max * 75;
  const lines = metrics.map(([key, label, color]) => {
    const segments = []; let points = [];
    series.forEach((bucket, i) => {
      if (bucket[key] == null) { if (points.length) segments.push(points); points = []; }
      else {
        if (data.step && points.length) points.push([x(i), points[points.length - 1][1]]);
        points.push([x(i), y(bucket[key])]);
      }
    });
    if (points.length) segments.push(points);
    return segments.map((segment) => segment.length === 1
      ? `<circle cx="${segment[0][0]}" cy="${segment[0][1]}" r="3" fill="var(--${color})"/>`
      : `<polyline points="${segment.map((point) => point.join(",")).join(" ")}" fill="none" stroke="var(--${color})" stroke-width="2"/>`).join("");
  }).join("");
  const activityMarkers = metrics.map(([key, , color], metricIndex) => series.map((bucket, i) =>
    bucket[key] == null && bucket[`${key}_scans`] > 0
      ? `<circle cx="${x(i) + (metricIndex - (metrics.length - 1) / 2) * 8}" cy="108" r="3" fill="none" stroke="var(--${color})" stroke-width="2"/>`
      : "").join("")).join("");
  const metricValue = (bucket, key) => {
    const scans = bucket[`${key}_scans`];
    if (scans === undefined) return bucket[key] == null ? "—" : format(bucket[key]);
    const count = `${scans.toLocaleString()} file scans completed`;
    if (bucket[key] != null) return `${format(bucket[key])} · ${count}`;
    return scans > 0 ? `${count} · insufficient sustained backlog` : "No completed file scans";
  };
  const ticks = data.time_scale
    ? [0, .5, 1].map((fraction) => ({at: timeStart + fraction * (timeEnd - timeStart), x: plotLeft + fraction * plotWidth}))
    : [...new Set([0, Math.floor((series.length - 1) / 2), series.length - 1])].filter((i) => series[i]).map((i) => ({at: series[i].at, x: x(i)}));
  const labels = ticks.map((tick) => `<text x="${tick.x}" y="125" text-anchor="middle" fill="var(--muted)" font-size="12">${escapeHtml(new Date(tick.at).toLocaleString([], data.bucket === "hour" ? {hour:"2-digit",minute:"2-digit",timeZone:"UTC"} : {month:"short",day:"numeric",timeZone:"UTC"}))}</text>`).join("");
  const pointUrls = options.onView
    ? series.map((bucket) => bucket.discovered == null ? null : "#") : comparisonUrls;
  const links = pointUrls.map((url, i) => {
    if (!url) return "";
    const left = i ? (x(i - 1) + x(i)) / 2 : plotLeft - 8;
    const right = i < series.length - 1 ? (x(i) + x(i + 1)) / 2 : plotRight + 8;
    return `<a href="${escapeHtml(url)}" data-dashboard-compare data-point-index="${i}" aria-label="${escapeHtml(options.viewLabel || "View scan results")} at ${escapeHtml(series[i].at)}"><rect x="${left}" y="12" width="${right - left}" height="102" fill="transparent"/></a>`;
  }).join("");
  if (!updateDashboardWidgetHtml(id, `<strong style="font-size:24px">${escapeHtml(summary)}</strong><div class="dashboard-chart"><div class="dashboard-chart-tooltip${links ? " is-interactive" : ""}" popover="manual" ${links ? "" : 'role="tooltip"'} hidden></div><svg viewBox="0 0 450 140" preserveAspectRatio="none" role="${links ? "group" : "img"}" aria-label="${escapeHtml(metrics.map(([,label]) => label).join(", "))} over time in UTC" style="width:100%;height:130px;display:block"><path d="M${plotLeft} 20V95H${plotRight}" fill="none" stroke="var(--line)"/><text x="${plotLeft - 10}" y="25" text-anchor="end" fill="var(--muted)" font-size="12">${escapeHtml(maxLabel)}</text><text x="${plotLeft - 10}" y="99" text-anchor="end" fill="var(--muted)" font-size="12">0</text>${lines}${activityMarkers}${labels}${links}</svg></div><div class="dashboard-actions">${metrics.map(([,label,color]) => `<span style="color:var(--${color})">● ${escapeHtml(label)}</span>`).join("")}</div>`, id === "dashboard-under-load")) return;
  const svg = target.querySelector("svg");
  const tooltip = target.querySelector(".dashboard-chart-tooltip");
  bindDashboardChartHover(svg, tooltip);
  const showBucket = (index) => {
    const bucket = series[index];
    tooltip.innerHTML = `<strong>${escapeHtml(new Date(bucket.at).toLocaleString([], {timeZone:"UTC"}))} UTC</strong>${metrics.map(([key,label,color]) => `<div><span style="color:var(--${color})">● ${escapeHtml(label)}</span><strong>${escapeHtml(metricValue(bucket, key))}</strong></div>`).join("")}${bucket.samples != null ? `<div>${bucket.samples} timing samples</div>` : ""}${(bucket.notes || []).map((note) => `<div>${escapeHtml(note)}</div>`).join("")}`;
    if (options.onView && bucket.discovered != null) {
      appendDashboardViewAction(tooltip, {at: bucket.at, label: options.viewLabel,
        onView: () => { hideDashboardChartHover(svg, tooltip); options.onView(bucket.at); }});
    } else if (comparisonUrls[index]) {
      appendDashboardViewAction(tooltip, {at: bucket.at, label: options.viewLabel || "Compare scan results", href: comparisonUrls[index]});
    }
    const points = metrics.filter(([key]) => bucket[key] != null).map(([key, , color]) => [y(bucket[key]), color]);
    showDashboardChartHover(svg, tooltip, x(index), points);
  };
  svg.addEventListener("pointermove", (event) => {
    const bounds = svg.getBoundingClientRect();
    const cursor = (event.clientX - bounds.left) / bounds.width * 450;
    let index;
    if (data.time_scale) {
      index = 0;
      for (let i = 0; i < series.length && x(i) <= cursor; i++) index = i;
    } else {
      index = Math.max(0, Math.min(series.length - 1, Math.round((cursor - plotLeft) / plotWidth * (series.length - 1))));
    }
    showBucket(index);
  });
  svg.addEventListener("focusin", (event) => {
    const point = event.target.closest("[data-point-index]");
    if (point) showBucket(Number(point.dataset.pointIndex));
  });
  if (options.onView) svg.addEventListener("click", (event) => {
    const point = event.target.closest("[data-point-index]");
    if (!point) return;
    event.preventDefault();
    hideDashboardChartHover(svg, tooltip);
    options.onView(series[Number(point.dataset.pointIndex)].at);
  });
}

function renderDashboardUnderLoad(data, connectorNames, selectedConnector, comparisonUrl) {
  const {current, previous} = data.under_load;
  const id = "dashboard-under-load";
  const target = document.getElementById(id);
  if (!target) return;
  const signature = JSON.stringify([data.under_load, data.under_load_series, data.series.map((bucket) => bucket.at),
    data.end, Array.from(connectorNames), selectedConnector]);
  if (dashboardUnderLoadSignatures.get(target) === signature && target.querySelector("svg")) return;
  dashboardUnderLoadSignatures.set(target, signature);
  const rate = (value) => value.toLocaleString(undefined, {maximumSignificantDigits: 3});
  const headline = current.files_per_second === null
    ? "No sustained scan load recorded in this period."
    : `${rate(current.files_per_second)} files/s`;
  const comparison = previous.files_per_second === null
    ? "No sustained scan load recorded in the previous equal-length period."
    : `Previous equal-length period: ${rate(previous.files_per_second)} files/s`;
  const change = previous.files_per_second > 0 && current.files_per_second !== null
    ? ` (${(current.files_per_second / previous.files_per_second - 1).toLocaleString(undefined, {style: "percent", signDisplay: "exceptZero", maximumFractionDigits: 1})})`
    : "";
  const colors = ["accent", "good", "warn", "violet", "danger"];
  const lines = data.under_load_series;
  const metrics = lines.map(({integration_id}, i) => [
    i, selectedConnector ? "Files/s" : connectorNames.get(integration_id) || integration_id, colors[i],
  ]);
  const series = data.series.map((bucket, i) => ({
    at: bucket.at,
    ...Object.fromEntries(lines.flatMap(({files_per_second, completed_scans}, j) => [
      [j, files_per_second[i]],
      [`${j}_scans`, completed_scans?.[i]],
    ])),
  }));
  if (series.some((bucket) => metrics.some(([key]) => bucket[key] != null || bucket[`${key}_scans`] > 0))) {
    const comparisonUrls = series.map((bucket, i) => {
      const connectorIds = lines.filter(({files_per_second, completed_scans}) => files_per_second[i] != null || completed_scans?.[i] > 0)
        .map(({integration_id}) => integration_id);
      if (!connectorIds.length) return "";
      const end = series[i + 1]?.at || data.end;
      return Date.parse(end) > Date.parse(bucket.at) ? comparisonUrl(bucket.at, end, connectorIds) : "";
    });
    renderDashboardMetric(id, {...data, series}, metrics, headline, (value) => `${rate(value)} files/s`, comparisonUrls);
  } else {
    target.textContent = headline;
  }
  const info = document.getElementById("dashboard-under-load-info-content");
  if (!info) return;
  info.replaceChildren();
  const notes = [comparison + change,
    `Rates require ${data.minimum_sustained_wait_seconds} seconds of continuous backlog. Hollow circles below the axis mark completed file scans without a qualifying rate. Hover over the chart for counts.`];
  if (current.files_per_second !== null) {
    notes.push(`${current.scans.toLocaleString()} file scans completed during ${rate(current.waiting_seconds)} s of sustained load. File mix and concurrency can differ between periods.`);
  }
  if (!selectedConnector) notes.push("Lines show the top five connectors by completed file scans. The headline covers all scans.");
  for (const note of notes) {
    const paragraph = document.createElement("p");
    paragraph.className = "dashboard-muted";
    paragraph.textContent = note;
    info.append(paragraph);
  }
}
