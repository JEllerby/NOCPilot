"""
NOCPilot FastAPI backend.

This application:
- Serves the dashboard frontend
- Runs device_connections.py automatically
- Refreshes network_data.json continuously
- Converts collected network information into dashboard data
- Generates alerts from real network conditions
- Provides live RAG + LLM troubleshooting responses

Run from the project root:

    uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

Then open:

    http://127.0.0.1:8000
"""

import asyncio
import json
import os
import re
import sys

from contextlib import asynccontextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


# =========================================================
# FILE PATHS AND SETTINGS
# =========================================================

BACKEND_DIRECTORY = Path(__file__).resolve().parent
PROJECT_DIRECTORY = BACKEND_DIRECTORY.parent
FRONTEND_DIRECTORY = PROJECT_DIRECTORY / "frontend"

NETWORK_DATA_FILE = BACKEND_DIRECTORY / "network_data.json"
COLLECTOR_SCRIPT = BACKEND_DIRECTORY / "device_connections.py"

POLL_INTERVAL_SECONDS = int(
    os.getenv("NOCPILOT_POLL_INTERVAL_SECONDS", "30")
)


# =========================================================
# COLLECTOR STATE
# =========================================================

collector_state: dict[str, Any] = {
    "running": False,
    "last_attempt": None,
    "last_success": None,
    "last_error": None,
}

collector_lock = asyncio.Lock()

# Stores the latest successfully loaded JSON data.
# This prevents the dashboard from becoming empty if the JSON file is
# temporarily unavailable while being rewritten.
last_good_network_data: dict[str, Any] = {}


# =========================================================
# NETWORK DATA COLLECTION
# =========================================================

async def run_collector_once() -> None:
    """
    Run device_connections.py one time.

    The collector connects to the network devices and rewrites
    backend/network_data.json with the latest collected information.
    """

    async with collector_lock:
        collector_state["running"] = True
        collector_state["last_attempt"] = datetime.now().isoformat(
            timespec="seconds"
        )
        collector_state["last_error"] = None

        try:
            if not COLLECTOR_SCRIPT.exists():
                raise FileNotFoundError(
                    f"Collector script not found: {COLLECTOR_SCRIPT}"
                )

            process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(COLLECTOR_SCRIPT),
                cwd=str(BACKEND_DIRECTORY),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await process.communicate()

            except asyncio.CancelledError:
                process.terminate()

                with suppress(ProcessLookupError):
                    await process.wait()

                raise

            stdout_text = stdout.decode(
                errors="replace"
            ).strip()

            stderr_text = stderr.decode(
                errors="replace"
            ).strip()

            if process.returncode != 0:
                error_message = stderr_text or stdout_text

                if not error_message:
                    error_message = (
                        f"Collector exited with code "
                        f"{process.returncode}."
                    )

                raise RuntimeError(error_message)

            collector_state["last_success"] = datetime.now().isoformat(
                timespec="seconds"
            )

            print(
                "[NOCPilot] Network data collection completed successfully."
            )

        except Exception as error:
            collector_state["last_error"] = str(error)

            print(
                f"[NOCPilot] Network data collection failed: {error}"
            )

        finally:
            collector_state["running"] = False


async def collection_loop() -> None:
    """
    Continuously run the network collector.

    A collection starts immediately when FastAPI starts and repeats
    according to POLL_INTERVAL_SECONDS.
    """

    while True:
        await run_collector_once()
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


# =========================================================
# FASTAPI LIFESPAN
# =========================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Start the background collector with FastAPI and stop it cleanly
    when FastAPI shuts down.
    """

    collector_task = asyncio.create_task(
        collection_loop()
    )

    yield

    collector_task.cancel()

    with suppress(asyncio.CancelledError):
        await collector_task


# =========================================================
# FASTAPI CONFIGURATION
# =========================================================

app = FastAPI(
    title="NOCPilot API",
    version="3.0",
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
# JSON DATA LOADING
# =========================================================

def load_network_data() -> dict[str, Any]:
    """
    Load the latest successfully collected network information.

    If the file is temporarily unavailable or incomplete, the previous
    successfully loaded copy is returned.
    """

    global last_good_network_data

    if not NETWORK_DATA_FILE.exists():
        return last_good_network_data

    try:
        with NETWORK_DATA_FILE.open(
            "r",
            encoding="utf-8",
        ) as json_file:
            network_data = json.load(json_file)

        if not isinstance(network_data, dict):
            raise ValueError(
                "network_data.json must contain a JSON object."
            )

        last_good_network_data = network_data
        return network_data

    except (
        OSError,
        json.JSONDecodeError,
        ValueError,
    ) as error:
        print(
            f"[NOCPilot] Unable to read network_data.json: {error}"
        )

        return last_good_network_data


def get_data_timestamp() -> str:
    """Return the time when network_data.json was last updated."""

    if not NETWORK_DATA_FILE.exists():
        return "Unknown"

    modified_time = NETWORK_DATA_FILE.stat().st_mtime

    return datetime.fromtimestamp(
        modified_time
    ).strftime("%Y-%m-%d %H:%M:%S")


# =========================================================
# DEVICE DATA HELPERS
# =========================================================

def extract_management_ip(running_config: str) -> str:
    """
    Extract the first configured IPv4 address from a running configuration.

    This is used because the current network_data.json file does not include
    the device connection IP as its own field.
    """

    match = re.search(
        r"^\s*ip address\s+"
        r"(\d{1,3}(?:\.\d{1,3}){3})\s+"
        r"\d{1,3}(?:\.\d{1,3}){3}",
        running_config,
        flags=re.MULTILINE,
    )

    if not match:
        return "N/A"

    return match.group(1)


def infer_device_type(device_data: dict[str, Any]) -> str:
    """Infer whether the collected device is a switch or router."""

    version_data = device_data.get(
        "System Version",
        {},
    )

    if isinstance(version_data, dict):
        full_output = str(
            version_data.get("full_output", "")
        ).lower()
    else:
        full_output = str(version_data).lower()

    if (
        "vios_l2" in full_output
        or "iosvl2" in full_output
        or "switch" in full_output
    ):
        return "Switch"

    if (
        "iosv" in full_output
        or "router" in full_output
    ):
        return "Router"

    return "Network Device"


def is_administratively_down(interface: dict[str, Any]) -> bool:
    """Return True when an interface was intentionally shut down."""

    status = str(
        interface.get("status", "")
    ).strip().lower()

    return "admin" in status


def is_interface_up(interface: dict[str, Any]) -> bool:
    """Return True when both interface status and protocol are up."""

    status = str(
        interface.get("status", "")
    ).strip().lower()

    protocol = str(
        interface.get("protocol", "")
    ).strip().lower()

    return status == "up" and protocol == "up"


def device_has_collection_error(
    device_data: dict[str, Any],
) -> bool:
    """Detect connection or collection errors stored in the JSON."""

    error_keys = {
        "error",
        "connection error",
        "collection error",
    }

    return any(
        str(key).strip().lower() in error_keys
        for key in device_data
    )


def build_devices() -> list[dict[str, Any]]:
    """
    Convert network_data.json into the device format used by the dashboard.
    """

    network_data = load_network_data()
    updated_at = get_data_timestamp()

    dashboard_devices: list[dict[str, Any]] = []

    for device_id, (
        device_name,
        device_data,
    ) in enumerate(
        sorted(network_data.items()),
        start=1,
    ):
        if not isinstance(device_data, dict):
            continue

        interfaces = device_data.get(
            "Interface Description",
            [],
        )

        if not isinstance(interfaces, list):
            interfaces = []

        interfaces_up = sum(
            1
            for interface in interfaces
            if (
                isinstance(interface, dict)
                and is_interface_up(interface)
            )
        )

        interfaces_admin_down = sum(
            1
            for interface in interfaces
            if (
                isinstance(interface, dict)
                and is_administratively_down(interface)
            )
        )

        interfaces_down = sum(
            1
            for interface in interfaces
            if (
                isinstance(interface, dict)
                and not is_interface_up(interface)
                and not is_administratively_down(interface)
            )
        )

        uptime_data = device_data.get(
            "Device Uptime",
            {},
        )

        if isinstance(uptime_data, dict):
            uptime = uptime_data.get(
                "uptime",
                "Unknown",
            )
        else:
            uptime = str(uptime_data)

        version_data = device_data.get(
            "System Version",
            {},
        )

        if isinstance(version_data, dict):
            software_version = version_data.get(
                "version",
                "Unknown",
            )
        else:
            software_version = str(version_data)

        running_config = str(
            device_data.get("Run", "")
        )

        collection_failed = device_has_collection_error(
            device_data
        )

        device_status = (
            "DOWN"
            if collection_failed
            else "UP"
        )

        device_health = "DOWN"

        if not collection_failed:
            device_health = (
                "DEGRADED"
                if interfaces_down > 0
                else "HEALTHY"
            )

        dashboard_devices.append(
            {
                "id": device_id,
                "name": device_name,
                "ip_address": extract_management_ip(
                    running_config
                ),
                "type": infer_device_type(
                    device_data
                ),
                "status": device_status,
                "health": device_health,
                "uptime": uptime,
                "software_version": software_version,
                "interfaces_up": interfaces_up,
                "interfaces_down": interfaces_down,
                "interfaces_admin_down": interfaces_admin_down,
                "total_interfaces": len(interfaces),
                "interfaces": interfaces,
                "last_updated": updated_at,

                # Kept for compatibility with the earlier dashboard structure.
                "latency_ms": "N/A",
                "packet_loss": "N/A",
                "tunnel_status": "N/A",
            }
        )

    return dashboard_devices


# =========================================================
# ALERT GENERATION
# =========================================================

def build_alerts() -> list[dict[str, Any]]:
    """
    Generate current alerts from the latest network collection.

    Administratively disabled interfaces are ignored.
    """

    network_data = load_network_data()
    created_at = get_data_timestamp()

    generated_alerts: list[dict[str, Any]] = []
    alert_id = 1

    for device_name, device_data in sorted(
        network_data.items()
    ):
        if not isinstance(device_data, dict):
            continue

        if device_has_collection_error(device_data):
            generated_alerts.append(
                {
                    "id": alert_id,
                    "device_name": device_name,
                    "alert_type": "Device Unreachable",
                    "severity": "CRITICAL",
                    "description": (
                        f"NOCPilot could not collect data from "
                        f"{device_name}."
                    ),
                    "status": "OPEN",
                    "created_at": created_at,
                }
            )

            alert_id += 1
            continue

        interfaces = device_data.get(
            "Interface Description",
            [],
        )

        if not isinstance(interfaces, list):
            continue

        for interface in interfaces:
            if not isinstance(interface, dict):
                continue

            if is_administratively_down(interface):
                continue

            if is_interface_up(interface):
                continue

            interface_name = interface.get(
                "interface",
                "Unknown interface",
            )

            interface_status = interface.get(
                "status",
                "unknown",
            )

            protocol_status = interface.get(
                "protocol",
                "unknown",
            )

            generated_alerts.append(
                {
                    "id": alert_id,
                    "device_name": device_name,
                    "alert_type": "Interface Down",
                    "severity": "HIGH",
                    "description": (
                        f"{interface_name} on {device_name} is not "
                        f"fully operational. Interface status is "
                        f"{interface_status} and protocol status is "
                        f"{protocol_status}."
                    ),
                    "status": "OPEN",
                    "created_at": created_at,
                }
            )

            alert_id += 1

    return generated_alerts


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

        pattern = (
            rf"{start}\s*(.*?)"
            rf"(?={endings}|$)"
        )

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

        cleaned_line = cleaned_line.replace(
            "**",
            "",
        ).strip()

        if cleaned_line:
            cleaned_items.append(cleaned_line)

    return cleaned_items


def parse_ai_answer(answer: str) -> dict[str, Any]:
    """Convert the LLM response into dashboard sections."""

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
        "possible_causes": clean_bullets(
            causes_text
        ),
        "next_steps": clean_bullets(
            actions_text
        ),
        "ticket_note": ticket_note,
    }


def get_live_ai_response(
    alert: dict[str, Any],
) -> dict[str, Any]:
    """
    Retrieve documentation from ChromaDB and generate a live LLM response.
    """

    from .llm_contact import generate_explanation
    from .retrieval import query_docs

    query_text = (
        f"The network device {alert['device_name']} reported "
        f"{alert['alert_type']}. "
        f"Description: {alert['description']}"
    )

    retrieval_result = query_docs(
        query_text
    )

    llm_result = generate_explanation(
        query_text=retrieval_result["query"],
        retrieved_context=retrieval_result["context"],
    )

    answer = str(
        llm_result.get("answer", "")
    ).strip()

    if not answer:
        raise RuntimeError(
            "The LLM returned an empty response."
        )

    if answer.lower().startswith(
        "the llm model is not loaded or could not be contacted"
    ):
        raise RuntimeError(answer)

    parsed_result = parse_ai_answer(
        answer
    )

    parsed_result["source"] = "live_ai_rag"

    return parsed_result


# =========================================================
# API ENDPOINTS
# =========================================================

@app.get("/health")
def health_check() -> dict[str, Any]:
    """Return backend and collector health information."""

    return {
        "status": "healthy",
        "service": "NOCPilot API",
        "version": "3.0",
        "collector": collector_state,
        "poll_interval_seconds": POLL_INTERVAL_SECONDS,
        "network_data_available": NETWORK_DATA_FILE.exists(),
    }


@app.get("/collector-status")
def get_collector_status() -> dict[str, Any]:
    """Return the current background collector status."""

    return {
        **collector_state,
        "poll_interval_seconds": POLL_INTERVAL_SECONDS,
        "network_data_file": str(
            NETWORK_DATA_FILE
        ),
    }


@app.post("/refresh")
async def refresh_network_data() -> dict[str, Any]:
    """Manually run one network collection immediately."""

    await run_collector_once()

    if collector_state["last_error"]:
        raise HTTPException(
            status_code=503,
            detail=collector_state["last_error"],
        )

    return {
        "message": "Network data refreshed successfully.",
        "last_success": collector_state["last_success"],
    }


@app.get("/devices")
def get_devices() -> list[dict[str, Any]]:
    """Return devices created from network_data.json."""

    return build_devices()


@app.get("/alerts")
def get_alerts() -> list[dict[str, Any]]:
    """Return current alerts generated from real collected data."""

    return build_alerts()


@app.get("/summary")
def get_summary() -> dict[str, int]:
    """Return dashboard summary-card counts."""

    devices = build_devices()
    alerts = build_alerts()

    return {
        "total_devices": len(devices),
        "online_devices": sum(
            device["status"] == "UP"
            for device in devices
        ),
        "offline_devices": sum(
            device["status"] == "DOWN"
            for device in devices
        ),
        "active_alerts": len(alerts),
        "critical_alerts": sum(
            alert["severity"] == "CRITICAL"
            for alert in alerts
        ),
    }


@app.get("/ai-explain/{alert_id}")
def explain_alert(
    alert_id: int,
) -> dict[str, Any]:
    """Generate a live RAG + LLM explanation for a current alert."""

    alerts = build_alerts()

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
        ai_result = get_live_ai_response(
            alert
        )

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


# This mount must remain after all API endpoints.
# It serves login.html, script.js, CSS files, images, and other frontend assets.
if FRONTEND_DIRECTORY.exists():
    app.mount(
        "/",
        StaticFiles(
            directory=FRONTEND_DIRECTORY,
            html=True,
        ),
        name="frontend",
    )