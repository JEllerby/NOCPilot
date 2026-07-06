from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
from retrieval import query_docs       # Queries our Chromadb. Use Ex:  query = query_docs(question)
from llm_contact import generate_explanation
import random

app = FastAPI(title="NOCPilot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

devices = [
    {
        "id": 1,
        "name": "BR-1",
        "ip_address": "10.10.1.1",
        "type": "Branch Router",
        "status": "UP",
        "latency_ms": 18,
        "packet_loss": 0,
        "tunnel_status": "UP"
    },
    {
        "id": 2,
        "name": "BR-2",
        "ip_address": "10.10.2.1",
        "type": "Branch Router",
        "status": "UP",
        "latency_ms": 22,
        "packet_loss": 0,
        "tunnel_status": "UP"
    },
    {
        "id": 3,
        "name": "FW-1",
        "ip_address": "10.20.1.1",
        "type": "Firewall",
        "status": "UP",
        "latency_ms": 8,
        "packet_loss": 0,
        "tunnel_status": "N/A"
    },
    {
        "id": 4,
        "name": "SW-1",
        "ip_address": "10.30.1.1",
        "type": "Switch",
        "status": "UP",
        "latency_ms": 3,
        "packet_loss": 0,
        "tunnel_status": "N/A"
    },
    {
        "id": 5,
        "name": "PLC-1",
        "ip_address": "10.64.43.36",
        "type": "PLC",
        "status": "UP",
        "latency_ms": 12,
        "packet_loss": 0,
        "tunnel_status": "N/A"
    },
    {
        "id": 6,
        "name": "SCADA-SERVER",
        "ip_address": "10.142.96.31",
        "type": "Server",
        "status": "UP",
        "latency_ms": 5,
        "packet_loss": 0,
        "tunnel_status": "N/A"
    },
]

alerts = []

class AlertRequest(BaseModel):
    scenario: str | None = None

def create_alert(device_name, alert_type, severity, description):
    alert = {
        "id": len(alerts) + 1,
        "device_name": device_name,
        "alert_type": alert_type,
        "severity": severity,
        "description": description,
        "status": "OPEN",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    alerts.insert(0, alert)
    return alert


@app.get("/")
def home():
    return {"message": "NOCPilot API is running"}


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "NOCPilot API",
        "version": "1.0",
        "message": "Backend is running successfully"
    }


@app.get("/summary")
def get_summary():
    total_devices = len(devices)
    online_devices = len([d for d in devices if d["status"] == "UP"])
    offline_devices = len([d for d in devices if d["status"] == "DOWN"])
    active_alerts = len(alerts)
    critical_alerts = len([a for a in alerts if a["severity"] == "CRITICAL"])

    return {
        "total_devices": total_devices,
        "online_devices": online_devices,
        "offline_devices": offline_devices,
        "active_alerts": active_alerts,
        "critical_alerts": critical_alerts
    }

@app.get("/devices")
def get_devices():
    return devices

@app.get("/alerts")
def get_alerts():
    return alerts

@app.post("/reset")
def reset():
    alerts.clear()
    for device in devices:
        device["status"] = "UP"
        device["packet_loss"] = 0
        device["latency_ms"] = random.randint(3, 25)
        if device["type"] == "Branch Router":
            device["tunnel_status"] = "UP"
    return {"message": "System reset successfully"}

@app.post("/simulate-alert")
def simulate_alert(request: AlertRequest):
    scenario = request.scenario or random.choice([
        "tunnel_flap",
        "device_down",
        "high_packet_loss",
        "plc_unreachable"
    ])

    if scenario == "tunnel_flap":
        device = next(d for d in devices if d["name"] == "BR-1")
        device["tunnel_status"] = "FLAPPING"
        device["latency_ms"] = 180
        device["packet_loss"] = 18
        return create_alert(
            "BR-1",
            "Tunnel Flapping",
            "HIGH",
            "Tunnel on BR-1 is repeatedly going up and down."
        )

    if scenario == "device_down":
        device = next(d for d in devices if d["name"] == "SW-1")
        device["status"] = "DOWN"
        device["latency_ms"] = 0
        device["packet_loss"] = 100
        return create_alert(
            "SW-1",
            "Device Unreachable",
            "CRITICAL",
            "SW-1 is not responding to monitoring checks."
        )

    if scenario == "high_packet_loss":
        device = next(d for d in devices if d["name"] == "BR-2")
        device["latency_ms"] = 260
        device["packet_loss"] = 35
        return create_alert(
            "BR-2",
            "High Packet Loss",
            "MEDIUM",
            "BR-2 is reachable but showing high latency and packet loss."
        )

    if scenario == "plc_unreachable":
        device = next(d for d in devices if d["name"] == "PLC-1")
        device["status"] = "DOWN"
        device["latency_ms"] = 0
        device["packet_loss"] = 100
        return create_alert(
            "PLC-1",
            "PLC Communication Failure",
            "HIGH",
            "SCADA server cannot reliably communicate with PLC-1."
        )

    return {"error": "Unknown scenario"}

@app.get("/ai-explain/{alert_id}")
def ai_explain(alert_id: int):
    alert = next((a for a in alerts if a["id"] == alert_id), None)
    if not alert:
        return {"error": "Alert not found"}

    alert_type = alert["alert_type"]

    playbooks = {
        "Tunnel Flapping": {
            "summary": "The WAN tunnel is unstable and repeatedly changing state.",
            "possible_causes": [
                "ISP or carrier instability",
                "Packet loss on the WAN path",
                "Remote router or modem issue",
                "Power or environmental issue at the remote site"
            ],
            "next_steps": [
                "Check BR-1 WAN interface status and errors",
                "Ping the ISP next-hop",
                "Check tunnel logs for up/down timestamps",
                "Review packet loss and latency trend",
                "Escalate to ISP if WAN instability is confirmed"
            ]
        },
        "Device Unreachable": {
            "summary": "The device is not responding to monitoring checks.",
            "possible_causes": [
                "Device powered off",
                "Physical cable or fiber issue",
                "Switchport down",
                "Management IP unreachable",
                "Upstream path issue"
            ],
            "next_steps": [
                "Check last known interface status",
                "Ask field tech to verify power and cabling",
                "Check upstream switch MAC/ARP table",
                "Verify if neighboring devices are also down",
                "Escalate to field team if physical issue is suspected"
            ]
        },
        "High Packet Loss": {
            "summary": "The device is reachable but traffic quality is degraded.",
            "possible_causes": [
                "Congested WAN circuit",
                "ISP issue",
                "Interface errors",
                "Bad cable or failing modem",
                "Routing path instability"
            ],
            "next_steps": [
                "Run continuous ping to the device",
                "Check interface errors and utilization",
                "Compare latency from different monitoring points",
                "Check if packet loss affects multiple sites",
                "Escalate if packet loss remains above threshold"
            ]
        },
        "PLC Communication Failure": {
            "summary": "SCADA communication to the PLC is failing or unstable.",
            "possible_causes": [
                "PLC offline or frozen",
                "Access switch issue near PLC",
                "Industrial network path interruption",
                "Firewall/session timeout issue",
                "Bad cable or local power issue"
            ],
            "next_steps": [
                "Confirm SCADA server can reach other PLCs",
                "Check firewall logs for allowed/denied traffic",
                "Verify PLC switchport status",
                "Ask field tech to check PLC power and link light",
                "Escalate to OT/field team if network path is clean"
            ]
        }
    }

    result = playbooks.get(alert_type, {
        "summary": "This alert requires investigation.",
        "possible_causes": ["Unknown"],
        "next_steps": ["Check device status", "Review logs", "Escalate if needed"]
    })

    ticket_note = (
        f"{alert['device_name']} is reporting {alert['alert_type']}. "
        f"{result['summary']} Initial investigation should include: "
        f"{'; '.join(result['next_steps'][:3])}. "
        f"Further escalation may be required if the issue persists."
    )

    return {
        "alert": alert,
        "ai_summary": result["summary"],
        "possible_causes": result["possible_causes"],
        "next_steps": result["next_steps"],
        "ticket_note": ticket_note
    }