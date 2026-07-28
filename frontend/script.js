// Protect the dashboard from direct access without logging in.
if (localStorage.getItem("isLoggedIn") !== "true") {
  window.location.replace("login.html");
}

const API_BASE_URL = window.location.origin;
const DASHBOARD_REFRESH_INTERVAL_MS = 15000;

let activeAiRequest = 0;
let refreshTimer = null;


/* =========================================================
   GENERAL HELPERS
========================================================= */

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}


function safeClassName(value) {
  return String(value ?? "")
    .toLowerCase()
    .replace(/[^a-z0-9_-]/g, "");
}


async function fetchJson(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    cache: "no-store",
    ...options,
  });

  let data = null;

  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (!response.ok) {
    const message =
      data?.detail ||
      data?.error ||
      `Backend request failed with status ${response.status}.`;

    throw new Error(message);
  }

  return data;
}


function formatDateTime(value) {
  if (!value) {
    return "Waiting for data";
  }

  const normalizedValue =
    typeof value === "string" && value.includes(" ")
      ? value.replace(" ", "T")
      : value;

  const parsedDate = new Date(normalizedValue);

  if (Number.isNaN(parsedDate.getTime())) {
    return String(value);
  }

  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(parsedDate);
}


function formatRelativeStatus(value) {
  if (!value) {
    return "Not available";
  }

  const parsedDate = new Date(value);

  if (Number.isNaN(parsedDate.getTime())) {
    return formatDateTime(value);
  }

  const differenceSeconds = Math.max(
    0,
    Math.floor((Date.now() - parsedDate.getTime()) / 1000)
  );

  if (differenceSeconds < 10) {
    return "Just now";
  }

  if (differenceSeconds < 60) {
    return `${differenceSeconds}s ago`;
  }

  const differenceMinutes = Math.floor(differenceSeconds / 60);

  if (differenceMinutes < 60) {
    return `${differenceMinutes}m ago`;
  }

  return formatDateTime(value);
}


function animateCounter(element, targetValue) {
  if (!element) {
    return;
  }

  const numericTarget = Number(targetValue);

  if (!Number.isFinite(numericTarget)) {
    element.textContent = targetValue;
    return;
  }

  const startValue = Number(element.textContent) || 0;
  const duration = 650;
  const startTime = performance.now();

  function updateCounter(currentTime) {
    const progress = Math.min((currentTime - startTime) / duration, 1);
    const easedProgress = 1 - Math.pow(1 - progress, 3);

    element.textContent = Math.round(
      startValue + (numericTarget - startValue) * easedProgress
    );

    if (progress < 1) {
      requestAnimationFrame(updateCounter);
    }
  }

  requestAnimationFrame(updateCounter);
}


function renderList(items) {
  if (!Array.isArray(items) || items.length === 0) {
    return "<li>No items were returned by the AI model.</li>";
  }

  return items
    .map(item => `<li>${escapeHtml(item)}</li>`)
    .join("");
}


function updateClock() {
  const clock = document.getElementById("headerClock");

  if (!clock) {
    return;
  }

  clock.textContent = new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date());
}


function setPlatformState(state, text) {
  const liveStatus = document.getElementById("liveStatus");
  const platformStatus = document.getElementById("platformStatus");
  const systemStatusText = document.getElementById("systemStatusText");

  liveStatus?.classList.remove(
    "is-live",
    "is-warning",
    "is-offline"
  );

  liveStatus?.classList.add(`is-${state}`);

  if (platformStatus) {
    platformStatus.textContent = text;
  }

  if (systemStatusText) {
    systemStatusText.textContent = text;
  }
}


/* =========================================================
   SUMMARY
========================================================= */

function renderSummary(summary) {
  animateCounter(
    document.getElementById("onlineCount"),
    summary.online_devices ?? 0
  );

  animateCounter(
    document.getElementById("offlineCount"),
    summary.offline_devices ?? 0
  );

  animateCounter(
    document.getElementById("alertCount"),
    summary.active_alerts ?? 0
  );

  animateCounter(
    document.getElementById("criticalCount"),
    summary.critical_alerts ?? 0
  );
}


/* =========================================================
   DEVICE TABLE
========================================================= */

function getDeviceGlyph(deviceType) {
  const normalizedType = String(deviceType || "").toLowerCase();

  if (normalizedType.includes("router")) {
    return "RT";
  }

  if (normalizedType.includes("switch")) {
    return "SW";
  }

  if (normalizedType.includes("firewall")) {
    return "FW";
  }

  if (normalizedType.includes("server")) {
    return "SV";
  }

  return "ND";
}


function getDeviceHealth(device) {
  if (device.health) {
    return String(device.health).toUpperCase();
  }

  return device.status === "UP" ? "HEALTHY" : "DOWN";
}


function renderDevices(devices) {
  const table = document.getElementById("deviceTable");
  const lastUpdatedLabel = document.getElementById(
    "deviceLastUpdated"
  );

  if (!Array.isArray(devices) || devices.length === 0) {
    table.innerHTML = `
      <tr>
        <td colspan="8">
          <div class="empty-state compact">
            No network devices are available yet.
          </div>
        </td>
      </tr>
    `;

    lastUpdatedLabel.textContent = "Awaiting collection";
    return;
  }

  const latestTimestamp = devices.find(
    device => device.last_updated
  )?.last_updated;

  lastUpdatedLabel.textContent = latestTimestamp
    ? `Updated ${formatDateTime(latestTimestamp)}`
    : "Live data loaded";

  table.innerHTML = devices
    .map(device => {
      const status = String(device.status || "UNKNOWN").toUpperCase();
      const health = getDeviceHealth(device);

      const interfacesUp = Number(device.interfaces_up) || 0;
      const interfacesDown = Number(device.interfaces_down) || 0;
      const interfacesAdminDown =
        Number(device.interfaces_admin_down) || 0;
      const totalInterfaces =
        Number(device.total_interfaces) ||
        interfacesUp + interfacesDown + interfacesAdminDown;

      const interfacePercentage =
        totalInterfaces > 0
          ? Math.round((interfacesUp / totalInterfaces) * 100)
          : 0;

      return `
        <tr>
          <td>
            <div class="device-identity">
              <span class="device-glyph">
                ${escapeHtml(getDeviceGlyph(device.type))}
              </span>

              <span>
                <strong>${escapeHtml(device.name)}</strong>
                <small>ID ${escapeHtml(device.id ?? "—")}</small>
              </span>
            </div>
          </td>

          <td>
            <code class="ip-address">
              ${escapeHtml(device.ip_address || "N/A")}
            </code>
          </td>

          <td>${escapeHtml(device.type || "Network Device")}</td>

          <td>
            <span class="status-badge status-${safeClassName(status)}">
              <i></i>
              ${escapeHtml(status)}
            </span>
          </td>

          <td>
            <span class="health-badge health-${safeClassName(health)}">
              ${escapeHtml(health)}
            </span>
          </td>

          <td>
            <span class="uptime-value">
              ${escapeHtml(device.uptime || "Unknown")}
            </span>
          </td>

          <td>
            <div class="interface-metric">
              <div class="interface-metric-top">
                <span>${interfacesUp}/${totalInterfaces} up</span>
                <small>${interfacesDown} down</small>
              </div>

              <div class="interface-track">
                <span style="width: ${interfacePercentage}%"></span>
              </div>
            </div>
          </td>

          <td>
            <span class="software-version">
              ${escapeHtml(device.software_version || "Unknown")}
            </span>
          </td>
        </tr>
      `;
    })
    .join("");
}


/* =========================================================
   ALERTS
========================================================= */

function renderAlerts(alerts) {
  const alertBox = document.getElementById("alerts");
  const queueCount = document.getElementById("queueCount");

  const alertCount = Array.isArray(alerts) ? alerts.length : 0;

  queueCount.textContent =
    `${alertCount} ${alertCount === 1 ? "incident" : "incidents"}`;

  alertBox.innerHTML = "";

  if (alertCount === 0) {
    alertBox.innerHTML = `
      <div class="healthy-state">
        <div class="healthy-state-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24">
            <path d="m5 12 4 4L19 6" />
          </svg>
        </div>

        <div>
          <h3>All systems nominal</h3>
          <p>
            NOCPilot has not detected any active network incidents.
          </p>
        </div>
      </div>
    `;
    return;
  }

  alerts.forEach((alert, index) => {
    const severity = String(
      alert.severity || "UNKNOWN"
    ).toUpperCase();

    const alertButton = document.createElement("button");

    alertButton.type = "button";
    alertButton.className =
      `alert-item alert-${safeClassName(severity)}`;
    alertButton.style.setProperty(
      "--alert-delay",
      `${index * 70}ms`
    );

    alertButton.innerHTML = `
      <span class="alert-severity-line"></span>

      <span class="alert-main">
        <span class="alert-topline">
          <strong>
            ${escapeHtml(alert.device_name)}
            <span>·</span>
            ${escapeHtml(alert.alert_type)}
          </strong>

          <span class="severity-badge severity-${safeClassName(severity)}">
            ${escapeHtml(severity)}
          </span>
        </span>

        <span class="alert-description">
          ${escapeHtml(alert.description)}
        </span>

        <span class="alert-meta">
          <span>
            <i></i>
            ${escapeHtml(alert.status || "OPEN")}
          </span>

          <time>${escapeHtml(formatDateTime(alert.created_at))}</time>
        </span>
      </span>

      <span class="alert-action" aria-hidden="true">
        Analyze
        <svg viewBox="0 0 24 24">
          <path d="m9 18 6-6-6-6" />
        </svg>
      </span>
    `;

    alertButton.addEventListener(
      "click",
      () => explainAlert(alert.id, alertButton)
    );

    alertBox.appendChild(alertButton);
  });
}


/* =========================================================
   SYSTEM HEALTH
========================================================= */

function renderSystemHealth(health) {
  const collector = health.collector || {};
  const collectorRunning = Boolean(collector.running);
  const collectorError = collector.last_error;

  document.getElementById("apiStatusValue").textContent =
    health.status === "healthy" ? "Operational" : "Degraded";

  document.getElementById("pollIntervalValue").textContent =
    health.poll_interval_seconds
      ? `${health.poll_interval_seconds}s`
      : "Not reported";

  if (collectorError) {
    setPlatformState("warning", "Degraded");

    document.getElementById("collectorStatus").textContent =
      "Collection error";

    document.getElementById("collectorStateValue").textContent =
      "Attention required";
  } else if (collectorRunning) {
    setPlatformState("live", "Collecting");

    document.getElementById("collectorStatus").textContent =
      "Collecting now";

    document.getElementById("collectorStateValue").textContent =
      "Active collection";
  } else {
    setPlatformState("live", "Systems live");

    document.getElementById("collectorStatus").textContent =
      "Monitoring";

    document.getElementById("collectorStateValue").textContent =
      "Standing by";
  }

  const lastSuccess = collector.last_success;

  document.getElementById("lastCollection").textContent =
    formatRelativeStatus(lastSuccess);
}


/* =========================================================
   DASHBOARD REFRESH
========================================================= */

async function refreshDashboard() {
  const results = await Promise.allSettled([
    fetchJson("/summary"),
    fetchJson("/devices"),
    fetchJson("/alerts"),
    fetchJson("/health"),
  ]);

  const [
    summaryResult,
    devicesResult,
    alertsResult,
    healthResult,
  ] = results;

  let failedRequests = 0;

  if (summaryResult.status === "fulfilled") {
    renderSummary(summaryResult.value);
  } else {
    failedRequests += 1;
  }

  if (devicesResult.status === "fulfilled") {
    renderDevices(devicesResult.value);
  } else {
    failedRequests += 1;

    document.getElementById("deviceTable").innerHTML = `
      <tr>
        <td colspan="8">
          <div class="error-state compact">
            ${escapeHtml(devicesResult.reason.message)}
          </div>
        </td>
      </tr>
    `;
  }

  if (alertsResult.status === "fulfilled") {
    renderAlerts(alertsResult.value);
  } else {
    failedRequests += 1;

    document.getElementById("alerts").innerHTML = `
      <div class="error-state">
        ${escapeHtml(alertsResult.reason.message)}
      </div>
    `;
  }

  if (healthResult.status === "fulfilled") {
    renderSystemHealth(healthResult.value);
  } else {
    failedRequests += 1;
  }

  const syncTime = new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date());

  document.getElementById("dashboardSyncValue").textContent =
    syncTime;

  if (failedRequests === results.length) {
    setPlatformState("offline", "API unavailable");
    document.getElementById("collectorStatus").textContent =
      "Disconnected";
  } else if (failedRequests > 0) {
    setPlatformState("warning", "Partial data");
  }
}


/* =========================================================
   AI ANALYSIS
========================================================= */

function setSelectedAlert(selectedAlert) {
  document
    .querySelectorAll(".alert-item")
    .forEach(alertItem => {
      alertItem.classList.toggle(
        "is-selected",
        alertItem === selectedAlert
      );
    });
}


async function explainAlert(alertId, selectedAlert) {
  const aiBox = document.getElementById("aiBox");
  const aiSection = document.getElementById("aiSection");

  setSelectedAlert(selectedAlert);

  const requestId = ++activeAiRequest;

  aiBox.innerHTML = `
    <div class="ai-loading-container">
      <div class="ai-loader" aria-hidden="true">
        <div class="ai-orbit ai-orbit-one"></div>
        <div class="ai-orbit ai-orbit-two"></div>
        <div class="ai-orbit ai-orbit-three"></div>

        <div class="ai-loader-core">
          <img
            src="images/nocpilot-icon.png"
            alt=""
            class="ai-loader-logo"
          />
        </div>

        <span class="ai-particle particle-one"></span>
        <span class="ai-particle particle-two"></span>
        <span class="ai-particle particle-three"></span>
      </div>

      <p class="ai-processing-label">NOCPILOT INTELLIGENCE ENGINE</p>

      <h3>Analyzing the network incident</h3>

      <p class="ai-loading-text">
        Correlating live telemetry with the knowledge base and
        generating an evidence-guided response.
      </p>

      <div class="loading-steps" aria-hidden="true">
        <span>
          <i></i>
          Retrieving documentation
        </span>

        <span>
          <i></i>
          Correlating event data
        </span>

        <span>
          <i></i>
          Generating recommendations
        </span>
      </div>

      <div class="ai-progress-track" aria-hidden="true">
        <span></span>
      </div>
    </div>
  `;

  aiSection.scrollIntoView({
    behavior: "smooth",
    block: "start",
  });

  try {
    const data = await fetchJson(`/ai-explain/${alertId}`);

    if (requestId !== activeAiRequest) {
      return;
    }

    const alert = data.alert || {};
    const severity = String(
      alert.severity || "UNKNOWN"
    ).toUpperCase();

    aiBox.innerHTML = `
      <div class="ai-result">
        <div class="ai-alert-header">
          <div class="ai-alert-identity">
            <span class="ai-alert-symbol" aria-hidden="true">
              <svg viewBox="0 0 24 24">
                <path d="M12 9v4m0 4h.01M10.3 3.8 2.4 18a2 2 0 0 0 1.75 3h15.7a2 2 0 0 0 1.75-3L13.7 3.8a2 2 0 0 0-3.4 0Z" />
              </svg>
            </span>

            <div>
              <p>Incident analysis complete</p>
              <h3>${escapeHtml(alert.device_name)}</h3>
              <span>${escapeHtml(alert.alert_type)}</span>
            </div>
          </div>

          <div class="ai-header-badges">
            <span class="ai-source-badge">
              <i></i>
              Live AI + RAG
            </span>

            <span class="severity-badge severity-${safeClassName(severity)}">
              ${escapeHtml(severity)}
            </span>
          </div>
        </div>

        <div class="ai-grid">
          <section class="ai-card ai-summary-card">
            <div class="ai-card-heading">
              <span>01</span>
              <h4>Executive Summary</h4>
            </div>

            <p>${escapeHtml(data.ai_summary)}</p>
          </section>

          <section class="ai-card">
            <div class="ai-card-heading">
              <span>02</span>
              <h4>Possible Causes</h4>
            </div>

            <ul>${renderList(data.possible_causes)}</ul>
          </section>

          <section class="ai-card">
            <div class="ai-card-heading">
              <span>03</span>
              <h4>Recommended Actions</h4>
            </div>

            <ul class="action-list">
              ${renderList(data.next_steps)}
            </ul>
          </section>

          <section class="ai-card ticket-card">
            <div class="ai-card-heading">
              <span>04</span>
              <h4>Generated Ticket Note</h4>
            </div>

            <div class="ticket-note" id="ticketNote">
              ${escapeHtml(data.ticket_note)}
            </div>

            <div class="ticket-actions">
              <button
                type="button"
                class="copy-btn"
                id="copyTicketButton"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <rect x="8" y="8" width="12" height="12" rx="2" />
                  <path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" />
                </svg>

                Copy Ticket Note
              </button>

              <p
                id="copyMessage"
                class="copy-message"
                aria-live="polite"
              ></p>
            </div>
          </section>
        </div>
      </div>
    `;

    document
      .getElementById("copyTicketButton")
      .addEventListener("click", copyTicketNote);
  } catch (error) {
    if (requestId !== activeAiRequest) {
      return;
    }

    aiBox.innerHTML = `
      <div class="error-state ai-error-state">
        <div class="error-state-icon">!</div>

        <div>
          <strong>AI analysis could not be generated</strong>
          <p>${escapeHtml(error.message)}</p>
        </div>
      </div>
    `;
  }
}


async function copyTicketNote() {
  const ticketNote = document.getElementById("ticketNote");
  const message = document.getElementById("copyMessage");

  if (!ticketNote || !message) {
    return;
  }

  try {
    await navigator.clipboard.writeText(
      ticketNote.textContent.trim()
    );

    message.textContent = "✓ Ticket note copied";
    message.className = "copy-message is-success";
  } catch {
    message.textContent = "Unable to copy ticket note";
    message.className = "copy-message is-error";
  }

  window.setTimeout(() => {
    message.className = "copy-message";
  }, 2600);
}


/* =========================================================
   AUTHENTICATION AND INITIALIZATION
========================================================= */

function logout() {
  localStorage.removeItem("isLoggedIn");
}


function initializeDashboard() {
  document
    .getElementById("logoutLink")
    .addEventListener("click", logout);

  updateClock();
  window.setInterval(updateClock, 1000);

  refreshDashboard();

  refreshTimer = window.setInterval(
    refreshDashboard,
    DASHBOARD_REFRESH_INTERVAL_MS
  );

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      refreshDashboard();
    }
  });
}


document.addEventListener("DOMContentLoaded", initializeDashboard);
