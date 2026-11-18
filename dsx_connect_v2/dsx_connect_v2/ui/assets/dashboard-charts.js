const dashboardUnderLoadSignatures = new WeakMap();

function renderDashboardMetric(id, data, metrics, summary, format, comparisonUrls = []) {
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
  const x = (i) => plotLeft + i * plotWidth / Math.max(1, series.length - 1);
  const y = (n) => 95 - n / max * 75;
  const lines = metrics.map(([key, label, color]) => {
    const segments = []; let points = [];
    series.forEach((bucket, i) => {
      if (bucket[key] == null) { if (points.length) segments.push(points); points = []; }
      else points.push([x(i), y(bucket[key])]);
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
  const labels = [...new Set([0, Math.floor((series.length - 1) / 2), series.length - 1])].filter((i) => series[i]).map((i) => `<text x="${x(i)}" y="125" text-anchor="middle" fill="var(--muted)" font-size="12">${escapeHtml(new Date(series[i].at).toLocaleString([], data.bucket === "hour" ? {hour:"2-digit",minute:"2-digit",timeZone:"UTC"} : {month:"short",day:"numeric",timeZone:"UTC"}))}</text>`).join("");
  const links = comparisonUrls.map((url, i) => {
    if (!url) return "";
    const left = i ? (x(i - 1) + x(i)) / 2 : plotLeft - 8;
    const right = i < series.length - 1 ? (x(i) + x(i + 1)) / 2 : plotRight + 8;
    return `<a href="${escapeHtml(url)}" data-dashboard-compare aria-label="Compare scans for ${escapeHtml(series[i].at)}"><rect x="${left}" y="12" width="${right - left}" height="102" fill="transparent"/></a>`;
  }).join("");
  if (!updateDashboardWidgetHtml(id, `<strong style="font-size:24px">${escapeHtml(summary)}</strong><div class="dashboard-chart"><div class="dashboard-chart-tooltip${links ? " is-interactive" : ""}" ${links ? "" : 'role="tooltip"'} hidden></div><svg viewBox="0 0 450 140" preserveAspectRatio="none" role="${links ? "group" : "img"}" aria-label="${escapeHtml(metrics.map(([,label]) => label).join(", "))} over time in UTC" style="width:100%;height:130px;display:block"><path d="M${plotLeft} 20V95H${plotRight}" fill="none" stroke="var(--line)"/><text x="${plotLeft - 10}" y="25" text-anchor="end" fill="var(--muted)" font-size="12">${escapeHtml(maxLabel)}</text><text x="${plotLeft - 10}" y="99" text-anchor="end" fill="var(--muted)" font-size="12">0</text>${lines}${activityMarkers}${labels}${links}</svg></div><div class="dashboard-actions">${metrics.map(([,label,color]) => `<span style="color:var(--${color})">● ${escapeHtml(label)}</span>`).join("")}</div><details><summary class="dashboard-muted">View exact values</summary><div class="table-wrap"><table><thead><tr><th>UTC</th>${metrics.map(([,label]) => `<th>${escapeHtml(label)}</th>`).join("")}</tr></thead><tbody>${series.map((bucket, i) => `<tr><td>${comparisonUrls[i] ? `<a href="${escapeHtml(comparisonUrls[i])}">${escapeHtml(bucket.at)}</a>` : escapeHtml(bucket.at)}</td>${metrics.map(([key]) => `<td>${escapeHtml(metricValue(bucket, key))}</td>`).join("")}</tr>`).join("")}</tbody></table></div></details>`, id === "dashboard-under-load")) return;
  const svg = target.querySelector("svg");
  const tooltip = target.querySelector(".dashboard-chart-tooltip");
  const hoverArea = links ? target.querySelector(".dashboard-chart") : svg;
  svg.addEventListener("pointermove", (event) => {
    const bounds = svg.getBoundingClientRect();
    const index = Math.max(0, Math.min(series.length - 1, Math.round(((event.clientX - bounds.left) / bounds.width * 450 - plotLeft) / plotWidth * (series.length - 1))));
    const bucket = series[index];
    tooltip.innerHTML = `<strong>${escapeHtml(new Date(bucket.at).toLocaleString([], {timeZone:"UTC"}))} UTC</strong>${metrics.map(([key,label,color]) => `<div><span style="color:var(--${color})">● ${escapeHtml(label)}</span><strong>${escapeHtml(metricValue(bucket, key))}</strong></div>`).join("")}${bucket.samples != null ? `<div>${bucket.samples} timing samples</div>` : ""}`;
    if (comparisonUrls[index]) {
      const link = document.createElement("a");
      link.href = comparisonUrls[index];
      link.textContent = "Compare scan results";
      tooltip.append(link);
    }
    tooltip.hidden = false;
    tooltip.style.left = `${Math.max(0, Math.min(event.clientX - bounds.left + 12, bounds.width - tooltip.offsetWidth))}px`;
  });
  hoverArea.addEventListener("pointerleave", () => { tooltip.hidden = true; });
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
  const notes = [comparison + change,
    `Rates require ${data.minimum_sustained_wait_seconds} seconds of continuous backlog. Hollow circles below the axis mark completed file scans without a qualifying rate. Hover for counts or open View exact values.`];
  if (current.files_per_second !== null) {
    notes.push(`${current.scans.toLocaleString()} file scans completed during ${rate(current.waiting_seconds)} s of sustained load. File mix and concurrency can differ between periods.`);
  }
  if (!selectedConnector) notes.push("Lines show the top five connectors by completed file scans. The headline covers all scans.");
  for (const note of notes) {
    const paragraph = document.createElement("p");
    paragraph.className = "dashboard-muted";
    paragraph.textContent = note;
    target.append(paragraph);
  }
}
