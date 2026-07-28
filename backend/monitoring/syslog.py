from __future__ import annotations

import socket
import threading
from collections.abc import Callable
from typing import Any


SYSLOG_HOST = "0.0.0.0"
SYSLOG_PORT = 5514


def identify_device(source_ip: str) -> str:
    """Translate a source IP address into a friendly device name."""

    device_names = {
        "10.0.20.1": "RT1",
        "10.0.20.2": "SW1",
    }

    return device_names.get(source_ip, source_ip)


def classify_syslog_message(message: str) -> dict[str, str] | None:
    """Convert important Cisco Syslog messages into alert information."""

    normalized_message = message.upper()

    if (
        "LINK-3-UPDOWN" in normalized_message
        and "CHANGED STATE TO DOWN" in normalized_message
    ):
        return {
            "alert_type": "Interface Down",
            "severity": "CRITICAL",
            "description": message,
        }

    if (
        "LINEPROTO-5-UPDOWN" in normalized_message
        and "CHANGED STATE TO DOWN" in normalized_message
    ):
        return {
            "alert_type": "Line Protocol Down",
            "severity": "HIGH",
            "description": message,
        }

    if (
        "LINK-3-UPDOWN" in normalized_message
        and "CHANGED STATE TO UP" in normalized_message
    ):
        return {
            "alert_type": "Interface Restored",
            "severity": "INFO",
            "description": message,
        }

    if (
        "LINEPROTO-5-UPDOWN" in normalized_message
        and "CHANGED STATE TO UP" in normalized_message
    ):
        return {
            "alert_type": "Line Protocol Restored",
            "severity": "INFO",
            "description": message,
        }

    return None


def run_syslog_listener(
    alert_callback: Callable[..., dict[str, Any]],
) -> None:
    """Listen continuously for Cisco Syslog messages over UDP."""

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        sock.bind((SYSLOG_HOST, SYSLOG_PORT))
    except OSError as error:
        print(
            f"Unable to start Syslog listener on UDP {SYSLOG_PORT}: "
            f"{error}"
        )
        return

    print(f"Syslog listener active on UDP {SYSLOG_PORT}")

    while True:
        try:
            data, address = sock.recvfrom(8192)

            source_ip = address[0]
            message = data.decode("utf-8", errors="replace").strip()

            print(f"SYSLOG from {source_ip}: {message}")

            alert_details = classify_syslog_message(message)

            if alert_details is None:
                continue

            alert_callback(
                device_name=identify_device(source_ip),
                alert_type=alert_details["alert_type"],
                severity=alert_details["severity"],
                description=alert_details["description"],
            )

        except Exception as error:
            print(f"Syslog processing error: {error}")


def start_syslog_listener(
    alert_callback: Callable[..., dict[str, Any]],
) -> threading.Thread:
    """Start the Syslog listener in a background thread."""

    listener_thread = threading.Thread(
        target=run_syslog_listener,
        args=(alert_callback,),
        daemon=True,
        name="nocpilot-syslog-listener",
    )

    listener_thread.start()
    return listener_thread