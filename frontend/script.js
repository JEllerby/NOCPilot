if (localStorage.getItem("isLoggedIn") !== "true") {
  window.location.href = "login.html";
}

const API = "http://127.0.0.1:8000";

async function loadDevices() {
  const response = await fetch(`${API}/devices`);
  const devices = await response.json();
const onlineDevices =
  devices.filter(device => device.status === "UP").length;

const offlineDevices =
  devices.filter(device => device.status !== "UP").length;

document.getElementById("onlineCount").textContent =
  onlineDevices;

document.getElementById("offlineCount").textContent =
  offlineDevices;
  const table = document.getElementById("deviceTable");
  table.innerHTML = "";

  devices.forEach(device => {
    const row = document.createElement("tr");

    row.innerHTML = `
      <td>${device.name}</td>
      <td>${device.ip_address}</td>
      <td>${device.type}</td>
      <td class="${device.status === "UP" ? "status-up" : "status-down"}">${device.status}</td>
      <td>${device.latency_ms} ms</td>
      <td>${device.packet_loss}%</td>
      <td>${device.tunnel_status}</td>
    `;

    table.appendChild(row);
  });
}

async function loadAlerts() {
  const response = await fetch(`${API}/alerts`);
  const alerts = await response.json();
document.getElementById("alertCount").textContent =
  alerts.length;

const criticalAlerts =
  alerts.filter(alert => alert.severity === "CRITICAL").length;

document.getElementById("criticalCount").textContent =
  criticalAlerts;
  const alertBox = document.getElementById("alerts");
  alertBox.innerHTML = "";

  if (alerts.length === 0) {
    alertBox.innerHTML = "<p>No open alerts. Network is healthy.</p>";
    return;
  }

  alerts.forEach(alert => {
    const div = document.createElement("div");
    div.className = "alert-item";
    div.onclick = () => explainAlert(alert.id);

    div.innerHTML = `
      <h3>${alert.device_name} - ${alert.alert_type}</h3>
      <p>${alert.description}</p>
      <p>Severity: <span class="${alert.severity.toLowerCase()}">${alert.severity}</span></p>
      <p>Created: ${alert.created_at}</p>
    `;

    alertBox.appendChild(div);
  });
}

async function simulateAlert() {
  await fetch(`${API}/simulate-alert`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({})
  });

  await loadDevices();
  await loadAlerts();
}

async function explainAlert(alertId) {
  const response = await fetch(`${API}/ai-explain/${alertId}`);
  const data = await response.json();

  const aiBox = document.getElementById("aiBox");

  aiBox.innerHTML = `
    <h3>${data.alert.device_name}: ${data.alert.alert_type}</h3>

    <h4>Summary</h4>
    <p>${data.ai_summary}</p>

    <h4>Possible Causes</h4>
    <ul>
      ${data.possible_causes.map(item => `<li>${item}</li>`).join("")}
    </ul>

    <h4>Next Actions</h4>
    <ul>
      ${data.next_steps.map(item => `<li>${item}</li>`).join("")}
    </ul>

    <h4>Ticket Note</h4>
    <div class="ticket-note">${data.ticket_note}</div>
  `;
}

async function resetSystem() {
  await fetch(`${API}/reset`, { method: "POST" });
  document.getElementById("aiBox").innerHTML = "<p>Select an alert to view AI troubleshooting guidance.</p>";
  await loadDevices();
  await loadAlerts();
}

function logout() {
  localStorage.removeItem("isLoggedIn");
  window.location.href = "login.html";
}

loadDevices();
loadAlerts();