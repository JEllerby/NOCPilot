// Protect the dashboard from direct access without logging in.
if (localStorage.getItem("isLoggedIn") !== "true") {
  window.location.replace("login.html");
}

const API_BASE_URL =
  `${window.location.protocol}//${window.location.hostname}:8000`;

let activeAiRequest = 0;
let selectedDeviceId = null;


/**
 * Escape API-provided text before inserting it into HTML.
 * This prevents unexpected HTML from being rendered by the browser.
 */
function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}


/**
 * Request JSON from the backend and throw a readable error
 * when the backend returns a non-success status.
 */
async function fetchJson(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, options);

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


function setButtonBusy(button, isBusy, busyText) {
  if (!button) return;

  if (isBusy) {
    button.dataset.originalText = button.textContent;
    button.textContent = busyText;
    button.disabled = true;
    return;
  }

  button.textContent = button.dataset.originalText || button.textContent;
  button.disabled = false;
}


function renderList(items) {
  if (!Array.isArray(items) || items.length === 0) {
    return "<li>No items were returned by the AI model.</li>";
  }

  return items
    .map(item => `<li>${escapeHtml(item)}</li>`)
    .join("");
}


async function loadDevices() {
  const table = document.getElementById("deviceTable");

  try {
    const devices = await fetchJson("/devices");

    const onlineDevices = devices.filter(
      device => device.status === "UP"
    ).length;

    const offlineDevices = devices.length - onlineDevices;

    document.getElementById("onlineCount").textContent = onlineDevices;
    document.getElementById("offlineCount").textContent = offlineDevices;

    table.innerHTML = devices
      .map(device => {
        const isOnline = device.status === "UP";
        const statusClass = isOnline ? "status-up" : "status-down";

        return `
<tr
  class="device-row"
  data-device-id="${escapeHtml(device.id)}"
  data-device-name="${escapeHtml(device.name)}"
  data-device-ip="${escapeHtml(device.ip_address)}"
  tabindex="0"
  role="button"
  aria-label="View interfaces for ${escapeHtml(device.name)}"
>
    <td>
      <span class="device-name-link">${escapeHtml(device.name)}</span>
    </td>

    <td>${escapeHtml(device.ip_address)}</td>

    <td>${escapeHtml(device.type)}</td>

    <td class="${statusClass}">
        ${escapeHtml(device.status)}
    </td>

    <td>${escapeHtml(device.cpu_usage ?? "N/A")} %</td>

    <td>${escapeHtml(device.uptime)}</td>

    <td>
        ${escapeHtml(device.interfaces_up)}
        /
        ${escapeHtml(device.interface_count)}
    </td>

    <td>${escapeHtml(device.interfaces_down)}</td>

    <td>${escapeHtml(device.packet_loss)}%</td>
</tr>
`;
      })
      .join("");

    table.querySelectorAll(".device-row").forEach(row => {
      const openSelectedDevice = () => {
        loadDeviceInterfaces(
          Number(row.dataset.deviceId),
          row.dataset.deviceName,
          row.dataset.deviceIp
        );
      };

      row.addEventListener("click", openSelectedDevice);

      row.addEventListener("keydown", event => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openSelectedDevice();
        }
      });
    });
  } catch (error) {
    document.getElementById("onlineCount").textContent = "—";
    document.getElementById("offlineCount").textContent = "—";

    table.innerHTML = `
      <tr>
        <td colspan="9" class="error-state">
          ${escapeHtml(error.message)}
        </td>
      </tr>
    `;
  }
}


function closeInterfaces() {
  const section = document.getElementById("interfacesSection");

  selectedDeviceId = null;
  section.hidden = true;

  document.querySelectorAll(".device-row").forEach(row => {
    row.classList.remove("device-row-selected");
  });
}


async function loadDeviceInterfaces(deviceId, deviceName, ipAddress) {
  const section = document.getElementById("interfacesSection");
  const heading = document.getElementById("interfaceDeviceName");
  const meta = document.getElementById("interfaceDeviceMeta");
  const content = document.getElementById("interfaceContent");

  selectedDeviceId = deviceId;

  document.querySelectorAll(".device-row").forEach(row => {
    row.classList.toggle(
      "device-row-selected",
      Number(row.dataset.deviceId) === deviceId
    );
  });

  section.hidden = false;
  heading.textContent = `${deviceName} Interfaces`;
  meta.textContent = `${ipAddress} • Live SNMP interface status`;

  content.innerHTML = `
    <div class="interface-loading">
      <div class="interface-spinner" aria-hidden="true"></div>
      <p>Loading live interface data...</p>
    </div>
  `;

  section.scrollIntoView({
    behavior: "smooth",
    block: "start",
  });

  try {
    const interfaces = await fetchJson(
      `/devices/${deviceId}/interfaces`
    );

    if (selectedDeviceId !== deviceId) {
      return;
    }

    if (!Array.isArray(interfaces) || interfaces.length === 0) {
      content.innerHTML = `
        <p class="empty-state">
          No interface information was returned for this device.
        </p>
      `;
      return;
    }

    const interfacesUp = interfaces.filter(
      networkInterface => networkInterface.oper_status === "UP"
    ).length;

    const interfacesDown = interfaces.length - interfacesUp;

    content.innerHTML = `
      <div class="interface-summary">
        <span>
          Total
          <strong>${escapeHtml(interfaces.length)}</strong>
        </span>

        <span class="interface-summary-up">
          Up
          <strong>${escapeHtml(interfacesUp)}</strong>
        </span>

        <span class="interface-summary-down">
          Down
          <strong>${escapeHtml(interfacesDown)}</strong>
        </span>
      </div>

      <div class="table-wrapper interface-table-wrapper">
        <table class="interface-table">
          <thead>
            <tr>
              <th scope="col">Index</th>
              <th scope="col">Interface</th>
              <th scope="col">Description</th>
              <th scope="col">Admin Status</th>
              <th scope="col">Operational Status</th>
            </tr>
          </thead>

          <tbody>
            ${interfaces
              .map(networkInterface => {
                const adminUp =
                  networkInterface.admin_status === "UP";
                const operUp =
                  networkInterface.oper_status === "UP";

                return `
                  <tr>
                    <td>${escapeHtml(networkInterface.index)}</td>

                    <td>
                      <span class="interface-name">
                        <span
                          class="interface-dot ${
                            operUp
                              ? "interface-dot-up"
                              : "interface-dot-down"
                          }"
                          aria-hidden="true"
                        ></span>

                        ${escapeHtml(networkInterface.name)}
                      </span>
                    </td>

                    <td>${escapeHtml(networkInterface.description)}</td>

                    <td>
                      <span class="interface-status ${
                        adminUp
                          ? "interface-status-up"
                          : "interface-status-down"
                      }">
                        ${escapeHtml(networkInterface.admin_status)}
                      </span>
                    </td>

                    <td>
                      <span class="interface-status ${
                        operUp
                          ? "interface-status-up"
                          : "interface-status-down"
                      }">
                        ${escapeHtml(networkInterface.oper_status)}
                      </span>
                    </td>
                  </tr>
                `;
              })
              .join("")}
          </tbody>
        </table>
      </div>
    `;
  } catch (error) {
    if (selectedDeviceId !== deviceId) {
      return;
    }

    content.innerHTML = `
      <div class="error-state">
        <strong>Interface data could not be loaded.</strong>
        <p>${escapeHtml(error.message)}</p>
      </div>
    `;
  }
}


async function loadAlerts() {
  const alertBox = document.getElementById("alerts");

  try {
    const alerts = await fetchJson("/alerts");

    const criticalAlerts = alerts.filter(
      alert => alert.severity === "CRITICAL"
    ).length;

    document.getElementById("alertCount").textContent = alerts.length;
    document.getElementById("criticalCount").textContent = criticalAlerts;

    alertBox.innerHTML = "";

    if (alerts.length === 0) {
      alertBox.innerHTML = `
        <p class="empty-state">
          No open alerts. The network is healthy.
        </p>
      `;
      return;
    }

    alerts.forEach(alert => {
      const alertButton = document.createElement("button");

      alertButton.type = "button";
      alertButton.className = "alert-item";

      alertButton.innerHTML = `
        <h3>
          ${escapeHtml(alert.device_name)}
          —
          ${escapeHtml(alert.alert_type)}
        </h3>

        <p>${escapeHtml(alert.description)}</p>

        <p>
          Severity:
          <span class="${escapeHtml(alert.severity.toLowerCase())}">
            ${escapeHtml(alert.severity)}
          </span>
        </p>

        <p>Created: ${escapeHtml(alert.created_at)}</p>
      `;

      alertButton.addEventListener(
        "click",
        () => explainAlert(alert.id)
      );

      alertBox.appendChild(alertButton);
    });
  } catch (error) {
    document.getElementById("alertCount").textContent = "—";
    document.getElementById("criticalCount").textContent = "—";

    alertBox.innerHTML = `
      <p class="error-state">${escapeHtml(error.message)}</p>
    `;
  }
}


async function simulateAlert() {
  const button = document.getElementById("simulateButton");

  setButtonBusy(button, true, "Simulating...");

  try {
    await fetchJson("/simulate-alert", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({}),
    });

    await Promise.all([
      loadDevices(),
      loadAlerts(),
    ]);
  } catch (error) {
    document.getElementById("alerts").innerHTML = `
      <p class="error-state">${escapeHtml(error.message)}</p>
    `;
  } finally {
    setButtonBusy(button, false);
  }
}


async function explainAlert(alertId) {
  const aiBox = document.getElementById("aiBox");

  // A slower, older request cannot overwrite a newer alert selection.
  const requestId = ++activeAiRequest;

  aiBox.innerHTML = `
    <div class="ai-loading-container">
      <div class="ai-loader" aria-hidden="true">
        <div class="ai-loader-ring"></div>

        <div class="ai-loader-core">
          <img
            src="images/nocpilot-icon.png"
            alt=""
            class="ai-loader-logo"
          />
        </div>
      </div>

      <h3>NOCPilot is analyzing the alert</h3>

      <p class="ai-loading-text">
        Retrieving relevant documentation and generating live
        troubleshooting guidance from the LLM.
      </p>

      <div class="loading-steps" aria-hidden="true">
        <span>Searching knowledge base</span>
        <span>Analyzing network event</span>
        <span>Preparing recommended actions</span>
      </div>
    </div>
  `;

  try {
    const data = await fetchJson(`/ai-explain/${alertId}`);

    if (requestId !== activeAiRequest) {
      return;
    }

    const alert = data.alert || {};

    aiBox.innerHTML = `
      <div class="ai-alert-header">
        <div>
          <h3>${escapeHtml(alert.device_name)}</h3>
          <p>${escapeHtml(alert.alert_type)}</p>
        </div>

        <div class="ai-header-badges">
          <span class="ai-source-badge">Live AI + RAG</span>

          <span
            class="severity-badge ${escapeHtml(
              String(alert.severity || "").toLowerCase()
            )}"
          >
            ${escapeHtml(alert.severity)}
          </span>
        </div>
      </div>

      <div class="ai-grid">
        <section class="ai-card">
          <h4>AI Summary</h4>
          <p>${escapeHtml(data.ai_summary)}</p>
        </section>

        <section class="ai-card">
          <h4>Possible Causes</h4>
          <ul>${renderList(data.possible_causes)}</ul>
        </section>

        <section class="ai-card">
          <h4>Recommended Actions</h4>
          <ul>${renderList(data.next_steps)}</ul>
        </section>

        <section class="ai-card">
          <h4>Ticket Note</h4>

          <div class="ticket-note" id="ticketNote">
            ${escapeHtml(data.ticket_note)}
          </div>

          <button
            type="button"
            class="copy-btn"
            id="copyTicketButton"
          >
            Copy Ticket Note
          </button>

          <p
            id="copyMessage"
            class="copy-message"
            aria-live="polite"
          ></p>
        </section>
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
      <div class="error-state">
        <strong>AI analysis could not be generated.</strong>
        <p>${escapeHtml(error.message)}</p>
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

    message.textContent = "✓ Ticket note copied successfully";
    message.style.color = "#22c55e";
    message.style.opacity = "1";
  } catch {
    message.textContent = "Unable to copy the ticket note.";
    message.style.color = "#f87171";
    message.style.opacity = "1";
  }

  window.setTimeout(() => {
    message.style.opacity = "0";
  }, 2500);
}


async function resetSystem() {
  const button = document.getElementById("resetButton");

  setButtonBusy(button, true, "Resetting...");

  try {
    await fetchJson("/reset", {
      method: "POST",
    });

    activeAiRequest += 1;

    document.getElementById("aiBox").innerHTML = `
      <p class="empty-state">
        Select an alert to generate AI troubleshooting guidance.
      </p>
    `;

    await Promise.all([
      loadDevices(),
      loadAlerts(),
    ]);
  } catch (error) {
    document.getElementById("aiBox").innerHTML = `
      <p class="error-state">${escapeHtml(error.message)}</p>
    `;
  } finally {
    setButtonBusy(button, false);
  }
}


function logout() {
  localStorage.removeItem("isLoggedIn");
}


function initializeDashboard() {
  document
    .getElementById("simulateButton")
    .addEventListener("click", simulateAlert);

  document
    .getElementById("resetButton")
    .addEventListener("click", resetSystem);

  document
    .getElementById("logoutLink")
    .addEventListener("click", logout);

  document
    .getElementById("closeInterfacesButton")
    .addEventListener("click", closeInterfaces);

  loadDevices();
  loadAlerts();
}


document.addEventListener("DOMContentLoaded", initializeDashboard);