import { DSXAClient } from "../../src/index.js";
import { classifyScan } from "./policy.js";

const form = document.querySelector("#upload-form");
const filesInput = document.querySelector("#files");
const submit = document.querySelector("#submit");
const status = document.querySelector("#status");
const accepted = document.querySelector("#accepted");
const rejected = document.querySelector("#rejected");
const baseUrlInput = document.querySelector("#baseUrl");
const authTokenInput = document.querySelector("#authToken");
const protectedEntityInput = document.querySelector("#protectedEntity");
const concurrencyInput = document.querySelector("#concurrency");
const configModal = document.querySelector("#config-modal");
const configOpen = document.querySelector("#config-open");
const configClose = document.querySelector("#config-close");
const configCancel = document.querySelector("#config-cancel");
const configForm = document.querySelector("#config-form");
const statsModal = document.querySelector("#stats-modal");
const statsOpen = document.querySelector("#stats-open");
const statsClose = document.querySelector("#stats-close");
const statsContent = document.querySelector("#stats-content");
let latestResults = [];
let latestWallTimeMs = null;

function openConfigModal() {
  configModal.classList.add("open");
  configModal.setAttribute("aria-hidden", "false");
}

function closeConfigModal() {
  configModal.classList.remove("open");
  configModal.setAttribute("aria-hidden", "true");
}

function openStatsModal() {
  statsModal.classList.add("open");
  statsModal.setAttribute("aria-hidden", "false");
}

function closeStatsModal() {
  statsModal.classList.remove("open");
  statsModal.setAttribute("aria-hidden", "true");
}

function truncateMiddle(value, maxLength = 56) {
  if (!value || value.length <= maxLength) {
    return value || "";
  }
  const lead = Math.ceil((maxLength - 3) / 2);
  const tail = Math.floor((maxLength - 3) / 2);
  return `${value.slice(0, lead)}...${value.slice(-tail)}`;
}

function formatDetail(detail) {
  if (!detail) {
    return "";
  }
  return truncateMiddle(detail, 96);
}

function setCounts(summary) {
  document.querySelector("#count-total").textContent = String(summary.total);
  document.querySelector("#count-accepted").textContent = String(summary.accepted);
  document.querySelector("#count-rejected").textContent = String(summary.rejected);
  document.querySelector("#count-review").textContent = String(summary.review);
}

function renderItems(target, items, fallback) {
  if (!items.length) {
    target.innerHTML = `<div class="empty">${fallback}</div>`;
    return;
  }

  target.innerHTML = items.map((item) => `
    <div class="item ${item.tone || item.bucket}">
      <strong title="${item.filename}">${truncateMiddle(item.filename, 48)}</strong>
      <span>${item.headline} [${item.verdict}]</span>
      <span class="detail" title="${item.detail}">${formatDetail(item.detail)}</span>
    </div>
  `).join("");
}

function renderStats() {
  const durationsMs = latestResults
    .map((item) => Number(item.scanDurationInMicroseconds))
    .filter((value) => Number.isFinite(value) && value >= 0)
    .map((value) => value / 1000);

  if (!durationsMs.length) {
    statsContent.innerHTML = '<p class="stats-empty">Run a batch with scan timings to populate stats.</p>';
    return;
  }

  const totalMs = durationsMs.reduce((sum, value) => sum + value, 0);
  const averageMs = totalMs / durationsMs.length;
  const fastestMs = Math.min(...durationsMs);
  const slowestMs = Math.max(...durationsMs);
  const sortedMs = [...durationsMs].sort((a, b) => a - b);
  const middle = Math.floor(sortedMs.length / 2);
  const medianMs = sortedMs.length % 2 === 0
    ? (sortedMs[middle - 1] + sortedMs[middle]) / 2
    : sortedMs[middle];

  function formatMilliseconds(value) {
    return `${value.toFixed(2)} ms`;
  }

  const rows = [
    ["Files with scan timing", durationsMs.length],
    ["Wall time", latestWallTimeMs != null ? formatMilliseconds(latestWallTimeMs) : "n/a"],
    ["Total scan time", formatMilliseconds(totalMs)],
    ["Average scan time", formatMilliseconds(averageMs)],
    ["Median scan time", formatMilliseconds(medianMs)],
    ["Fastest scan", formatMilliseconds(fastestMs)],
    ["Slowest scan", formatMilliseconds(slowestMs)],
  ];

  statsContent.innerHTML = `
    <ul class="stats-list">
      ${rows.map(([label, value]) => `
        <li class="stats-row">
          <span>${label}</span>
          <strong>${value}</strong>
        </li>
      `).join("")}
    </ul>
  `;
}

configOpen.addEventListener("click", openConfigModal);
configClose.addEventListener("click", closeConfigModal);
configCancel.addEventListener("click", closeConfigModal);
configModal.addEventListener("click", (event) => {
  if (event.target === configModal) {
    closeConfigModal();
  }
});
statsOpen.addEventListener("click", () => {
  renderStats();
  openStatsModal();
});
statsClose.addEventListener("click", closeStatsModal);
statsModal.addEventListener("click", (event) => {
  if (event.target === statsModal) {
    closeStatsModal();
  }
});
configForm.addEventListener("submit", (event) => {
  event.preventDefault();
  status.textContent = "Configuration updated.";
  closeConfigModal();
});

async function runBounded(items, limit, worker) {
  const results = new Array(items.length);
  let nextIndex = 0;

  async function consume() {
    while (true) {
      const index = nextIndex;
      nextIndex += 1;
      if (index >= items.length) {
        return;
      }
      results[index] = await worker(items[index], index);
    }
  }

  const runners = Array.from({ length: Math.max(1, Math.min(limit, items.length)) }, () => consume());
  await Promise.all(runners);
  return results;
}

async function scanOneFile(file, client, protectedEntity) {
  try {
    const response = await client.scanFile(file, {
      protectedEntity,
      customMetadata: `loan-intake:${file.name}`,
    });
    const decision = classifyScan(response);
    const reason = response?.verdictDetails?.reason || response?.verdict_details?.reason;

    return {
      filename: file.name,
      bucket: decision.bucket,
      tone: decision.tone,
      headline: decision.headline,
      verdict: response.verdict,
      detail: reason || "Browser demo reviewed the file directly with DSXA.",
      scanGuid: response.scanGuid || response.scan_guid,
      scanDurationInMicroseconds: response.scanDurationInMicroseconds ?? response.scan_duration_in_microseconds ?? null,
    };
  } catch (error) {
    const message = error?.message || String(error);
    const likelyCause =
      message === "Failed to fetch"
        ? "Browser could not complete the DSXA request. Check CORS, endpoint reachability, and mixed-content restrictions."
        : message;

    return {
      filename: file.name,
      bucket: "review",
      tone: "review",
      headline: "Scanner error",
      verdict: "Error",
      detail: likelyCause,
      scanGuid: null,
      scanDurationInMicroseconds: null,
    };
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const files = Array.from(filesInput.files || []);
  if (!files.length) {
    status.textContent = "Select at least one file.";
    return;
  }

  const baseUrl = baseUrlInput.value.trim();
  if (!baseUrl) {
    status.textContent = "Enter a DSXA base URL.";
    return;
  }

  const protectedEntity = Number.parseInt(protectedEntityInput.value, 10);
  const concurrency = Math.max(1, Number.parseInt(concurrencyInput.value, 10) || 4);
  const client = new DSXAClient({
    baseUrl,
    authToken: authTokenInput.value.trim(),
    defaultProtectedEntity: Number.isFinite(protectedEntity) ? protectedEntity : 1,
  });

  submit.disabled = true;
  status.textContent = "Scanning files with DSXA...";
  const startedAt = performance.now();

  try {
    const results = await runBounded(files, concurrency, (file) =>
      scanOneFile(file, client, Number.isFinite(protectedEntity) ? protectedEntity : 1),
    );

    const acceptedItems = results.filter((result) => result.bucket === "accepted");
    const rejectedItems = results.filter((result) => result.bucket !== "accepted");
    const summary = {
      total: results.length,
      accepted: acceptedItems.length,
      rejected: results.filter((result) => result.bucket === "rejected").length,
      review: results.filter((result) => result.bucket === "review").length,
    };

    latestResults = results;
    latestWallTimeMs = performance.now() - startedAt;
    setCounts(summary);
    renderItems(accepted, acceptedItems, "No accepted files in this batch.");
    renderItems(rejected, rejectedItems, "No rejected or held files in this batch.");
    status.textContent = `Reviewed ${summary.total} file(s). Accepted ${summary.accepted}, held back ${summary.total - summary.accepted}.`;
    form.reset();
    protectedEntityInput.value = String(Number.isFinite(protectedEntity) ? protectedEntity : 1);
    concurrencyInput.value = String(concurrency);
    baseUrlInput.value = baseUrl;
  } finally {
    submit.disabled = false;
  }
});
