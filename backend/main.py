"""
NOCPilot FastAPI backend.

This prototype provides:
- An in-memory device inventory
- Simulated network alerts
- Dashboard summary endpoints
- Live RAG-assisted troubleshooting responses from the team's LLM

Run from the project root:
    uv run uvicorn backend.main:app --reload
"""

from datetime import datetime
import random
import re
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Application configuration
# ---------------------------------------------------------------------------

app = FastAPI(
    title="NOCPilot API",
    version="2.0",
)

# The frontend does not currently send cookies or authentication credentials,
# so credentials are disabled while local development origins are allowed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Temporary in-memory data
# ---------------------------------------------------------------------------

# These simulated devices will later be replaced or updated by live ping/SNMP
# monitoring data from the EVE-NG environment.
devices: list[dict[str, Any]] = [
    {
        "id": 1,
        "name": "BR-1",
        "ip_address": "10.10.1.1",
        "type": "Branch Router",
        "status": "UP",
        "latency_ms": 18,
        "packet_loss": 0,
        "tunnel_status": "UP",
    },
    {
        "id": 2,
        "name": "BR-2",
        "ip_address": "10.10.2.1",
        "type": "Branch Router",
        "status": "UP",
        "latency_ms": 22,
        "packet_loss": 0,
        "tunnel_status": "UP",
    },
    {
        "id": 3,
        "name": "FW-1",
        "ip_address": "10.20.1.1",
        "type": "Firewall",
        "status": "UP",
        "latency_ms": 8,
        "packet_loss": 0,
        "tunnel_status": "N/A",
    },
    {
        "id": 4,
        "name": "SW-1",
        "ip_address": "10.30.1.1",
        "type": "Switch",
        "status": "UP",
        "latency_ms": 3,
        "packet_loss": 0,
        "tunnel_status": "N/A",
    },
    {
        "id": 5,
        "name": "PLC-1",
        "ip_address": "10.64.43.36",
        "type": "PLC",
        "status": "UP",
        "latency_ms": 12,
        "packet_loss": 0,
        "tunnel_status": "N/A",
    },
    {
        "id": 6,
        "name": "SCADA-SERVER",
        "ip_address": "10.142.96.31",
        "type": "Server",
        "status": "UP",
        "latency_ms": 5,
        "packet_loss": 0,
        "tunnel_status": "N/A",
    },
]

# Alerts exist only while the backend process is running.
alerts: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class AlertRequest(BaseModel):
    """Optional request body for choosing a specific simulated scenario."""

    scenario: str | None = None


# ---------------------------------------------------------------------------
# Alert helpers
# ---------------------------------------------------------------------------

def create_alert(
    device_name: str,
    alert_type: str,
    severity: str,
    description: str,
) -> dict[str, Any]:
    """Create an alert and insert it first so the newest alert is shown first."""

    alert = {
        "id": len(alerts) + 1,
        "device_name": device_name,
        "alert_type": alert_type,
        "severity": severity,
        "description": description,
        "status": "OPEN",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    alerts.insert(0, alert)
    return alert


# ---------------------------------------------------------------------------
# LLM response parsing
# ---------------------------------------------------------------------------

def _label_pattern(label: str) -> str:
    """
    Build a regex that recognizes plain or Markdown headings.

    Examples matched:
        Summary:
        **Summary:**
        **Summary**:
    """

    escaped_label = re.escape(label)
    return rf"(?:\*\*)?{escaped_label}\s*:(?:\*\*)?"


def extract_section(
    text: str,
    start_label: str,
    end_labels: list[str],
) -> str:
    """Extract one named section from the LLM's formatted text response."""

    start_pattern = _label_pattern(start_label)

    if end_labels:
        ending_pattern = "|".join(
            _label_pattern(label)
            for label in end_labels
        )

        pattern = rf"{start_pattern}\s*(.*?)(?={ending_pattern}|$)"
    else:
        pattern = rf"{start_pattern}\s*(.*)$"

    match = re.search(
        pattern,
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    if not match:
        return ""

    return match.group(1).strip()


def clean_bullets(section_text: str) -> list[str]:
    """Convert the LLM's bulleted or numbered section into a Python list."""

    cleaned_items: list[str] = []

    for line in section_text.splitlines():
        cleaned_line = line.strip()

        # Remove common Markdown bullets and numbered-list prefixes.
        cleaned_line = re.sub(
            r"^(?:[-*•]|\d+[.)])\s*",
            "",
            cleaned_line,
        )

        # Remove Markdown bold markers that may wrap a complete item.
        cleaned_line = cleaned_line.replace("**", "").strip()

        if cleaned_line:
            cleaned_items.append(cleaned_line)

    return cleaned_items


def parse_ai_answer(answer: str) -> dict[str, Any]:
    """
    Convert the LLM text into the four sections expected by the dashboard.

    The system prompt in llm_contact.py should request these exact headings:
    Summary, Possible Causes, Recommended Actions, and Ticket Note.
    """

    summary = extract_section(
        answer,
        "Summary",
        ["Possible Causes", "Recommended Actions", "Ticket Note"],
    )

    causes_text = extract_section(
        answer,
        "Possible Causes",
        ["Recommended Actions", "Ticket Note"],
    )

    actions_text = extract_section(
        answer,
        "Recommended Actions",
        ["Ticket Note"],
    )

    ticket_note = extract_section(
        answer,
        "Ticket Note",
        [],
    )

    missing_sections = []

    if not summary:
        missing_sections.append("Summary")

    if not causes_text:
        missing_sections.append("Possible Causes")

    if not actions_text:
        missing_sections.append("Recommended Actions")

    if not ticket_note:
        missing_sections.append("Ticket Note")

    if missing_sections:
        missing = ", ".join(missing_sections)

        raise ValueError(
            f"The LLM response was missing required section(s): {missing}."
        )

    return {
        "ai_summary": summary,
        "possible_causes": clean_bullets(causes_text),
        "next_steps": clean_bullets(actions_text),
        "ticket_note": ticket_note,
    }


# ---------------------------------------------------------------------------
# Live RAG + LLM integration
# ---------------------------------------------------------------------------

def get_live_ai_response(alert: dict[str, Any]) -> dict[str, Any]:
    """
    Generate a live troubleshooting response.

    Flow:
        alert
        -> query ChromaDB for relevant documentation
        -> send alert and retrieved context to the remote LLM
        -> parse the formatted LLM response
    """

    # Importing inside the function lets the basic API start without loading
    # the embedding model until an AI explanation is actually requested.
    from .llm_contact import generate_explanation
    from .retrieval import query_docs

    query_text = (
        f"The device {alert['device_name']} has reported the alert "
        f"{alert['alert_type']}. Description: {alert['description']}"
    )

    retrieval_result = query_docs(query_text)

    llm_result = generate_explanation(
        query_text=retrieval_result["query"],
        retrieved_context=retrieval_result["context"],
    )

    answer = str(llm_result.get("answer", "")).strip()

    if not answer:
        raise RuntimeError("The LLM returned an empty response.")

    # llm_contact.py currently returns this message when its model call fails.
    if answer.lower().startswith(
        "the llm model is not loaded or could not be contacted"
    ):
        raise RuntimeError(answer)

    parsed_result = parse_ai_answer(answer)
    parsed_result["source"] = "live_ai_rag"

    return parsed_result


# ---------------------------------------------------------------------------
# Basic endpoints
# ---------------------------------------------------------------------------

@app.get("/")
def home() -> dict[str, str]:
    """Confirm that the API process is running."""

    return {"message": "NOCPilot API is running"}


@app.get("/health")
def health_check() -> dict[str, str]:
    """Return basic backend health information."""

    return {
        "status": "healthy",
        "service": "NOCPilot API",
        "version": "2.0",
    }


@app.get("/summary")
def get_summary() -> dict[str, int]:
    """Calculate the counts used by the dashboard summary cards."""

    open_alerts = [
        alert
        for alert in alerts
        if alert["status"] == "OPEN"
    ]

    return {
        "total_devices": len(devices),
        "online_devices": sum(
            device["status"] == "UP"
            for device in devices
        ),
        "offline_devices": sum(
            device["status"] != "UP"
            for device in devices
        ),
        "active_alerts": len(open_alerts),
        "critical_alerts": sum(
            alert["severity"] == "CRITICAL"
            for alert in open_alerts
        ),
    }


@app.get("/devices")
def get_devices() -> list[dict[str, Any]]:
    """Return the current device inventory."""

    return devices


@app.get("/alerts")
def get_alerts() -> list[dict[str, Any]]:
    """Return all current alerts, newest first."""

    return alerts


# ---------------------------------------------------------------------------
# Prototype controls
# ---------------------------------------------------------------------------

@app.post("/reset")
def reset_system() -> dict[str, str]:
    """Clear alerts and restore all simulated devices to a healthy state."""

    alerts.clear()

    for device in devices:
        device["status"] = "UP"
        device["packet_loss"] = 0
        device["latency_ms"] = random.randint(3, 25)

        if device["type"] == "Branch Router":
            device["tunnel_status"] = "UP"

    return {"message": "System reset successfully"}


@app.post("/simulate-alert")
def simulate_alert(request: AlertRequest) -> dict[str, Any]:
    """Simulate one chosen or randomly selected network incident."""

    scenario = request.scenario or random.choice(
        [
            "tunnel_flap",
            "device_down",
            "high_packet_loss",
            "plc_unreachable",
        ]
    )

    if scenario == "tunnel_flap":
        device = next(
            device
            for device in devices
            if device["name"] == "BR-1"
        )

        device["tunnel_status"] = "FLAPPING"
        device["latency_ms"] = 180
        device["packet_loss"] = 18

        return create_alert(
            device_name="BR-1",
            alert_type="Tunnel Flapping",
            severity="HIGH",
            description="Tunnel on BR-1 is repeatedly going up and down.",
        )

    if scenario == "device_down":
        device = next(
            device
            for device in devices
            if device["name"] == "SW-1"
        )

        device["status"] = "DOWN"
        device["latency_ms"] = 0
        device["packet_loss"] = 100

        return create_alert(
            device_name="SW-1",
            alert_type="Device Unreachable",
            severity="CRITICAL",
            description="SW-1 is not responding to monitoring checks.",
        )

    if scenario == "high_packet_loss":
        device = next(
            device
            for device in devices
            if device["name"] == "BR-2"
        )

        device["latency_ms"] = 260
        device["packet_loss"] = 35

        return create_alert(
            device_name="BR-2",
            alert_type="High Packet Loss",
            severity="MEDIUM",
            description=(
                "BR-2 is reachable but showing high latency and packet loss."
            ),
        )

    if scenario == "plc_unreachable":
        device = next(
            device
            for device in devices
            if device["name"] == "PLC-1"
        )

        device["status"] = "DOWN"
        device["latency_ms"] = 0
        device["packet_loss"] = 100

        return create_alert(
            device_name="PLC-1",
            alert_type="PLC Communication Failure",
            severity="HIGH",
            description=(
                "SCADA server cannot reliably communicate with PLC-1."
            ),
        )

    raise HTTPException(
        status_code=400,
        detail=f"Unknown simulation scenario: {scenario}",
    )


# ---------------------------------------------------------------------------
# AI endpoint
# ---------------------------------------------------------------------------

@app.get("/ai-explain/{alert_id}")
def ai_explain(alert_id: int) -> dict[str, Any]:
    """Generate a live RAG + LLM explanation for one selected alert."""

    alert = next(
        (
            current_alert
            for current_alert in alerts
            if current_alert["id"] == alert_id
        ),
        None,
    )

    if alert is None:
        raise HTTPException(
            status_code=404,
            detail="Alert not found.",
        )

    try:
        ai_result = get_live_ai_response(alert)

    except Exception as error:
        # There is intentionally no rule-based AI fallback. If retrieval or
        # the LLM fails, the frontend receives a clear service error.
        raise HTTPException(
            status_code=503,
            detail=f"AI analysis failed: {error}",
        ) from error

    return {
        "alert": alert,
        "ai_summary": ai_result["ai_summary"],
        "possible_causes": ai_result["possible_causes"],
        "next_steps": ai_result["next_steps"],
        "ticket_note": ai_result["ticket_note"],
        "source": ai_result["source"],
    }