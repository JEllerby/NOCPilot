"""
NOCPilot FastAPI backend.

This application:
- Serves the dashboard frontend
- Collects live device data through Amir's SNMP monitoring module
- Starts Amir's UDP syslog listener for real network alerts
- Provides dashboard summary, device, interface, alert, and health endpoints
- Provides live RAG + LLM troubleshooting responses

Run from the project root:

    uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

Then open:

    http://127.0.0.1:8000
"""

import asyncio
import copy
import re
import threading
import time

from contextlib import asynccontextmanager
from datetime import datetime
from itertools import count
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.monitoring.snmp import (
    collect_all_devices,
    collect_device_interfaces,
)
from backend.monitoring.syslog import (
    SYSLOG_PORT,
    start_syslog_listener,
)


# =========================================================
# PATHS AND SETTINGS
# =========================================================

BACKEND_DIRECTORY = Path(__file__).resolve().parent
PROJECT_DIRECTORY = BACKEND_DIRECTORY.parent
FRONTEND_DIRECTORY = PROJECT_DIRECTORY / "frontend"

# Avoid polling every device twice when the frontend requests /devices and
# /summary almost at the same time.
SNMP_CACHE_SECONDS = 5.0

# Limit in-memory syslog alerts so the list does not grow forever.
MAX_ALERTS = 200


# =========================================================
# LIVE MONITORING STATE
# =========================================================

monitoring_state: dict[str, Any] = {
    "running": False,
    "last_attempt": None,
    "last_success": None,
    "last_error": None,
}

snmp_poll_lock = asyncio.Lock()
alert_lock = threading.Lock()
alert_id_counter = count(1)

cached_devices: list[dict[str, Any]] = []
cache_updated_monotonic = 0.0

# Syslog alerts exist in memory while FastAPI is running.
alerts: list[dict[str, Any]] = []


# =========================================================
# ALERT HELPERS
# =========================================================

def create_alert(
    device_name: str,
    alert_type: str,
    severity: str,
    description: str,
) -> dict[str, Any]:
    """
    Create an alert from a received syslog event.

    This function is passed directly to monitoring/syslog.py.
    """

    alert = {
        "id": next(alert_id_counter),
        "device_name": device_name,
        "alert_type": alert_type,
        "severity": severity.upper(),
        "description": description,
        "status": "OPEN",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    with alert_lock:
        alerts.insert(0, alert)
        del alerts[MAX_ALERTS:]

    return alert


def get_alert_snapshot() -> list[dict[str, Any]]:
    """Return a safe copy of the current in-memory alerts."""

    with alert_lock:
        return copy.deepcopy(alerts)


# =========================================================
# SNMP DEVICE COLLECTION
# =========================================================

def normalize_device(
    device: dict[str, Any],
    collected_at: str,
) -> dict[str, Any]:
    """
    Add compatibility fields used by the current dashboard.

    Amir's SNMP module remains unchanged. This function only reshapes its
    returned data so both the older and newer dashboard layouts can use it.
    """

    normalized = dict(device)

    status = str(normalized.get("status", "DOWN")).upper()
    interfaces_down = int(normalized.get("interfaces_down") or 0)
    interface_count = int(normalized.get("interface_count") or 0)

    if status != "UP":
        health = "DOWN"
    elif interfaces_down > 0:
        health = "DEGRADED"
    else:
        health = "HEALTHY"

    normalized.update(
        {
            "status": status,
            "health": health,
            "total_interfaces": interface_count,
            "interfaces_admin_down": 0,
            "software_version": normalized.get(
                "software_version",
                "N/A",
            ),
            "last_updated": collected_at,
            "latency_ms": normalized.get("latency_ms", 0),
            "packet_loss": normalized.get("packet_loss", 0),
            "tunnel_status": normalized.get("tunnel_status", "N/A"),
        }
    )

    return normalized


async def collect_live_devices(
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """
    Collect live SNMP data and briefly cache the result.

    The short cache prevents duplicate polling when several dashboard
    endpoints are requested at nearly the same time.
    """

    global cached_devices
    global cache_updated_monotonic

    now_monotonic = time.monotonic()

    if (
        not force_refresh
        and cached_devices
        and now_monotonic - cache_updated_monotonic < SNMP_CACHE_SECONDS
    ):
        return copy.deepcopy(cached_devices)

    async with snmp_poll_lock:
        now_monotonic = time.monotonic()

        if (
            not force_refresh
            and cached_devices
            and now_monotonic - cache_updated_monotonic < SNMP_CACHE_SECONDS
        ):
            return copy.deepcopy(cached_devices)

        monitoring_state["running"] = True
        monitoring_state["last_attempt"] = datetime.now().isoformat(
            timespec="seconds"
        )
        monitoring_state["last_error"] = None

        try:
            raw_devices = await collect_all_devices()
            collected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            normalized_devices = [
                normalize_device(device, collected_at)
                for device in raw_devices
            ]

            cached_devices = normalized_devices
            cache_updated_monotonic = time.monotonic()

            monitoring_state["last_success"] = datetime.now().isoformat(
                timespec="seconds"
            )

            return copy.deepcopy(normalized_devices)

        except Exception as error:
            monitoring_state["last_error"] = str(error)

            # Keep showing the last successful data if a later poll fails.
            if cached_devices:
                return copy.deepcopy(cached_devices)

            raise

        finally:
            monitoring_state["running"] = False


# =========================================================
# FASTAPI LIFESPAN
# =========================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start Amir's syslog listener when FastAPI starts."""

    syslog_thread = start_syslog_listener(create_alert)
    app.state.syslog_thread = syslog_thread

    yield


# =========================================================
# FASTAPI CONFIGURATION
# =========================================================

app = FastAPI(
    title="NOCPilot API",
    version="4.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# LLM RESPONSE PARSING
# =========================================================

def label_pattern(label: str) -> str:
    """Build a regex for plain or Markdown section headings."""

    escaped_label = re.escape(label)

    return (
        rf"(?:\#{{1,6}}\s*)?"
        rf"(?:\*\*)?"
        rf"{escaped_label}"
        rf"(?:\*\*)?"
        rf"\s*:?"
    )


def extract_section(
    text: str,
    start_label: str,
    end_labels: list[str],
) -> str:
    """Extract one labeled section from the LLM response."""

    start = label_pattern(start_label)

    if end_labels:
        endings = "|".join(
            label_pattern(label)
            for label in end_labels
        )

        pattern = rf"{start}\s*(.*?)(?={endings}|$)"
    else:
        pattern = rf"{start}\s*(.*)$"

    match = re.search(
        pattern,
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    if not match:
        return ""

    return match.group(1).strip()


def clean_bullets(section_text: str) -> list[str]:
    """Convert LLM bullet points into a Python list."""

    cleaned_items: list[str] = []

    for line in section_text.splitlines():
        cleaned_line = line.strip()

        cleaned_line = re.sub(
            r"^(?:[-*•]|\d+[.)])\s*",
            "",
            cleaned_line,
        )

        cleaned_line = cleaned_line.replace("**", "").strip()

        if cleaned_line:
            cleaned_items.append(cleaned_line)

    return cleaned_items


def parse_ai_answer(answer: str) -> dict[str, Any]:
    """Convert the LLM response into the sections used by the dashboard."""

    summary = extract_section(
        answer,
        "Summary",
        [
            "Possible Causes",
            "Recommended Actions",
            "Ticket Note",
        ],
    )

    causes_text = extract_section(
        answer,
        "Possible Causes",
        [
            "Recommended Actions",
            "Ticket Note",
        ],
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

    missing_sections: list[str] = []

    if not summary:
        missing_sections.append("Summary")

    if not causes_text:
        missing_sections.append("Possible Causes")

    if not actions_text:
        missing_sections.append("Recommended Actions")

    if not ticket_note:
        missing_sections.append("Ticket Note")

    if missing_sections:
        raise ValueError(
            "The LLM response was missing required section(s): "
            + ", ".join(missing_sections)
        )

    return {
        "ai_summary": summary,
        "possible_causes": clean_bullets(causes_text),
        "next_steps": clean_bullets(actions_text),
        "ticket_note": ticket_note,
    }


def get_live_ai_response(
    alert: dict[str, Any],
) -> dict[str, Any]:
    """Retrieve RAG context and generate a live LLM response."""

    from .llm_contact import generate_explanation
    from .retrieval import query_docs

    query_text = (
        f"The network device {alert['device_name']} reported "
        f"{alert['alert_type']}. "
        f"Description: {alert['description']}"
    )

    retrieval_result = query_docs(query_text)

    llm_result = generate_explanation(
        query_text=retrieval_result["query"],
        retrieved_context=retrieval_result["context"],
    )

    answer = str(llm_result.get("answer", "")).strip()

    if not answer:
        raise RuntimeError("The LLM returned an empty response.")

    if answer.lower().startswith(
        "the llm model is not loaded or could not be contacted"
    ):
        raise RuntimeError(answer)

    parsed_result = parse_ai_answer(answer)
    parsed_result["source"] = "live_ai_rag"

    return parsed_result


# =========================================================
# API ENDPOINTS
# =========================================================

@app.get("/health")
def health_check() -> dict[str, Any]:
    """Return API, SNMP, and syslog monitoring health information."""

    syslog_thread = getattr(app.state, "syslog_thread", None)

    return {
        "status": "healthy",
        "service": "NOCPilot API",
        "version": "4.0",
        "collector": monitoring_state,
        "poll_interval_seconds": None,
        "network_data_available": bool(cached_devices),
        "monitoring": {
            "snmp_mode": "live_on_request",
            "snmp_cache_seconds": SNMP_CACHE_SECONDS,
            "syslog_port": SYSLOG_PORT,
            "syslog_listener_alive": bool(
                syslog_thread and syslog_thread.is_alive()
            ),
        },
    }


@app.get("/collector-status")
def get_collector_status() -> dict[str, Any]:
    """Return current live SNMP monitoring status."""

    return {
        **monitoring_state,
        "mode": "live_on_request",
        "cache_seconds": SNMP_CACHE_SECONDS,
        "cached_device_count": len(cached_devices),
    }


@app.post("/refresh")
async def refresh_network_data() -> dict[str, Any]:
    """Force a fresh SNMP poll immediately."""

    try:
        devices = await collect_live_devices(
            force_refresh=True
        )
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail=f"SNMP refresh failed: {error}",
        ) from error

    return {
        "message": "Live SNMP data refreshed successfully.",
        "last_success": monitoring_state["last_success"],
        "device_count": len(devices),
    }


@app.get("/devices")
async def get_devices() -> list[dict[str, Any]]:
    """Return live SNMP device information."""

    try:
        return await collect_live_devices()
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail=f"Unable to collect SNMP device data: {error}",
        ) from error


@app.get("/devices/{device_id}/interfaces")
async def get_device_interfaces(
    device_id: int,
) -> list[dict[str, Any]]:
    """Return detailed live SNMP interfaces for one device."""

    try:
        interfaces = await collect_device_interfaces(device_id)
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail=f"Unable to collect interface data: {error}",
        ) from error

    if interfaces is None:
        raise HTTPException(
            status_code=404,
            detail="Device not found.",
        )

    return interfaces


@app.get("/alerts")
def get_alerts() -> list[dict[str, Any]]:
    """Return alerts received by Amir's syslog listener."""

    return get_alert_snapshot()


@app.get("/summary")
async def get_summary() -> dict[str, int]:
    """Return dashboard counts from live SNMP devices and syslog alerts."""

    try:
        devices = await collect_live_devices()
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail=f"Unable to collect dashboard summary: {error}",
        ) from error

    current_alerts = get_alert_snapshot()

    open_alerts = [
        alert
        for alert in current_alerts
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


@app.get("/ai-explain/{alert_id}")
def explain_alert(
    alert_id: int,
) -> dict[str, Any]:
    """Generate live RAG + LLM troubleshooting guidance for one alert."""

    current_alerts = get_alert_snapshot()

    alert = next(
        (
            current_alert
            for current_alert in current_alerts
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


# =========================================================
# FRONTEND
# =========================================================

@app.get("/", include_in_schema=False)
def serve_dashboard():
    """Serve the dashboard entry page."""

    index_file = FRONTEND_DIRECTORY / "index.html"

    if not index_file.exists():
        raise HTTPException(
            status_code=404,
            detail="frontend/index.html was not found.",
        )

    return FileResponse(index_file)


# Keep this mount after every API endpoint.
# It serves login.html, CSS, JavaScript, images, and other frontend assets.
if FRONTEND_DIRECTORY.exists():
    app.mount(
        "/",
        StaticFiles(
            directory=FRONTEND_DIRECTORY,
            html=True,
        ),
        name="frontend",
    )