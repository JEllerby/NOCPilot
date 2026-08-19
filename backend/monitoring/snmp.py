from __future__ import annotations

import asyncio
from typing import Any

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    get_cmd,
)

from .config import DEVICES

SNMP_ENGINE = SnmpEngine()
SNMP_SEMAPHORE = asyncio.Semaphore(4)

# Standard system OIDs
SYS_NAME_OID = "1.3.6.1.2.1.1.5.0"
SYS_UPTIME_OID = "1.3.6.1.2.1.1.3.0"
IF_NUMBER_OID = "1.3.6.1.2.1.2.1.0"

# IF-MIB interface OIDs
IF_DESCR_BASE_OID = "1.3.6.1.2.1.2.2.1.2"
IF_ADMIN_STATUS_BASE_OID = "1.3.6.1.2.1.2.2.1.7"
IF_OPER_STATUS_BASE_OID = "1.3.6.1.2.1.2.2.1.8"

# IF-MIB ifName. Some older Cisco images may not support this.
IF_NAME_BASE_OID = "1.3.6.1.2.1.31.1.1.1.1"

# Cisco CPU OIDs. Different Cisco images may support different ones.
CPU_OIDS = [
    "1.3.6.1.4.1.9.9.109.1.1.1.1.8.1",
    "1.3.6.1.4.1.9.9.109.1.1.1.1.5.1",
    "1.3.6.1.4.1.9.2.1.56.0",
]


async def snmp_get(
    ip_address: str,
    community: str,
    oid: str,
) -> str | None:
    """Retrieve one SNMP value."""

    try:
        async with SNMP_SEMAPHORE:
            error_indication, error_status, error_index, var_binds = await get_cmd(
                SNMP_ENGINE,
                CommunityData(community, mpModel=1),
                await UdpTransportTarget.create(
                    (ip_address, 161),
                    timeout=5,
                retries=1,
            ),
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
            lookupMib=False,
        )

        if error_indication:
            print(
                f"SNMP error from {ip_address} for OID {oid}: "
                f"{error_indication}"
            )
            return None

        if error_status:
            print(
                f"SNMP error from {ip_address} for OID {oid}: "
                f"{error_status.prettyPrint()} at index {error_index}"
            )
            return None

        if not var_binds:
            return None

        value = var_binds[0][1].prettyPrint()

        unsupported_values = {
            "No Such Object currently exists at this OID",
            "No Such Instance currently exists at this OID",
        }

        if value in unsupported_values:
            return None

        return value

    except Exception as error:
        print(f"SNMP exception from {ip_address} for OID {oid}: {error}")
        return None


def format_uptime(raw_uptime: str | None) -> str:
    """Convert SNMP TimeTicks into a readable duration."""

    if raw_uptime is None:
        return "Unavailable"

    try:
        total_seconds = int(raw_uptime) // 100

        days, remaining = divmod(total_seconds, 86400)
        hours, remaining = divmod(remaining, 3600)
        minutes, seconds = divmod(remaining, 60)

        return f"{days}d {hours}h {minutes}m {seconds}s"

    except (TypeError, ValueError):
        return raw_uptime


def format_admin_status(raw_status: str | None) -> str:
    """Convert IF-MIB ifAdminStatus into readable text."""

    status_map = {
        "1": "UP",
        "2": "DOWN",
        "3": "TESTING",
    }

    return status_map.get(raw_status, "UNKNOWN")


def format_oper_status(raw_status: str | None) -> str:
    """Convert IF-MIB ifOperStatus into readable text."""

    status_map = {
        "1": "UP",
        "2": "DOWN",
        "3": "TESTING",
        "4": "UNKNOWN",
        "5": "DORMANT",
        "6": "NOT PRESENT",
        "7": "LOWER LAYER DOWN",
    }

    return status_map.get(raw_status, "UNKNOWN")


async def get_cpu_usage(
    ip_address: str,
    community: str,
) -> int | None:
    """Try several Cisco CPU OIDs and return the first supported value."""

    for oid in CPU_OIDS:
        value = await snmp_get(ip_address, community, oid)

        if value is None:
            continue

        try:
            return int(value)
        except ValueError:
            continue

    return None


async def get_interface_metrics(
    ip_address: str,
    community: str,
) -> dict[str, int]:
    """Retrieve the number of interfaces and their operational states."""

    interface_count_value = await snmp_get(
        ip_address,
        community,
        IF_NUMBER_OID,
    )

    if interface_count_value is None:
        return {
            "interface_count": 0,
            "interfaces_up": 0,
            "interfaces_down": 0,
        }

    try:
        interface_count = int(interface_count_value)
    except ValueError:
        return {
            "interface_count": 0,
            "interfaces_up": 0,
            "interfaces_down": 0,
        }

    status_tasks = [
        snmp_get(
            ip_address,
            community,
            f"{IF_OPER_STATUS_BASE_OID}.{interface_index}",
        )
        for interface_index in range(1, interface_count + 1)
    ]

    statuses = await asyncio.gather(*status_tasks)

    interfaces_up = sum(status == "1" for status in statuses)
    interfaces_down = sum(
        status is not None and status != "1"
        for status in statuses
    )

    return {
        "interface_count": interface_count,
        "interfaces_up": interfaces_up,
        "interfaces_down": interfaces_down,
    }


async def get_device_interfaces(
    ip_address: str,
    community: str,
) -> list[dict[str, Any]]:
    """Retrieve detailed interface information from one device."""

    interface_count_value = await snmp_get(
        ip_address,
        community,
        IF_NUMBER_OID,
    )

    if interface_count_value is None:
        return []

    try:
        interface_count = int(interface_count_value)
    except ValueError:
        return []

    interface_tasks = []

    for interface_index in range(1, interface_count + 1):
        interface_tasks.append(
            asyncio.gather(
                snmp_get(
                    ip_address,
                    community,
                    f"{IF_NAME_BASE_OID}.{interface_index}",
                ),
                snmp_get(
                    ip_address,
                    community,
                    f"{IF_DESCR_BASE_OID}.{interface_index}",
                ),
                snmp_get(
                    ip_address,
                    community,
                    f"{IF_ADMIN_STATUS_BASE_OID}.{interface_index}",
                ),
                snmp_get(
                    ip_address,
                    community,
                    f"{IF_OPER_STATUS_BASE_OID}.{interface_index}",
                ),
            )
        )

    interface_results = await asyncio.gather(*interface_tasks)

    interfaces: list[dict[str, Any]] = []

    for interface_index, result in enumerate(
        interface_results,
        start=1,
    ):
        interface_name, description, admin_status, oper_status = result

        display_name = (
            interface_name
            or description
            or f"Interface {interface_index}"
        )

        interfaces.append(
            {
                "index": interface_index,
                "name": display_name,
                "description": description or display_name,
                "admin_status": format_admin_status(admin_status),
                "oper_status": format_oper_status(oper_status),
            }
        )

    return interfaces


async def collect_device(device: dict[str, Any]) -> dict[str, Any]:
    """Collect live SNMP metrics for one configured device."""

    ip_address = device["ip_address"]
    community = device["community"]

    sys_name, sys_uptime = await asyncio.gather(
        snmp_get(ip_address, community, SYS_NAME_OID),
        snmp_get(ip_address, community, SYS_UPTIME_OID),
    )

    is_up = sys_name is not None

    if not is_up:
        return {
            "id": device["id"],
            "name": device["name"],
            "ip_address": ip_address,
            "type": device["type"],
            "status": "DOWN",
            "latency_ms": 0,
            "packet_loss": 100,
            "tunnel_status": "N/A",
            "uptime": "Unavailable",
            "cpu_usage": None,
            "interface_count": 0,
            "interfaces_up": 0,
            "interfaces_down": 0,
        }

    cpu_usage, interface_metrics = await asyncio.gather(
        get_cpu_usage(ip_address, community),
        get_interface_metrics(ip_address, community),
    )

    return {
        "id": device["id"],
        "name": sys_name or device["name"],
        "ip_address": ip_address,
        "type": device["type"],
        "status": "UP",
        "latency_ms": 0,
        "packet_loss": 0,
        "tunnel_status": "N/A",
        "uptime": format_uptime(sys_uptime),
        "cpu_usage": cpu_usage,
        **interface_metrics,
    }


async def collect_all_devices() -> list[dict[str, Any]]:
    """Collect live SNMP information from every configured device."""

    tasks = [
        collect_device(device)
        for device in DEVICES
    ]

    return await asyncio.gather(*tasks)


async def collect_device_interfaces(
    device_id: int,
) -> list[dict[str, Any]] | None:
    """Collect detailed interfaces for one configured device."""

    device = next(
        (
            configured_device
            for configured_device in DEVICES
            if configured_device["id"] == device_id
        ),
        None,
    )

    if device is None:
        return None

    return await get_device_interfaces(
        device["ip_address"],
        device["community"],
    )
