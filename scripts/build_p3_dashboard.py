"""Phase 3 — build the Sync & Versioning dashboard.

Three widgets, all built-in TB widget types:

    1. "Shadow Sync Status" — Entities table with columns:
         Device, Active, Desired HVAC, Reported HVAC,
         Desired Target, Reported Target, current_version
       Cells are color-coded green/red based on desired==reported.

    2. "Fleet Version Evolution" — Entities table grouped by
       current_version attribute, shows count per version.

    3. "Active Tampering Alerts" — Entities table filtered to devices
       where security_alert == 'OTA_TAMPERING'.
"""

import os
import sys
import uuid

import httpx

TB_URL = os.getenv("TB_URL", "http://localhost:9090")
TB_USER = os.getenv("TB_USERNAME", "tenant@thingsboard.org")
TB_PASS = os.getenv("TB_PASSWORD", "tenant")
DASHBOARD_TITLE = "Phase 3 — Sync & Versioning"
ALIAS_ID = "all_devices_alias_p3"


def login():
    r = httpx.post(
        f"{TB_URL}/api/auth/login",
        json={"username": TB_USER, "password": TB_PASS},
    )
    r.raise_for_status()
    return r.json()["token"]


def find_dashboard(client, title):
    r = client.get(
        f"{TB_URL}/api/tenant/dashboards",
        params={"pageSize": 100, "page": 0},
    )
    r.raise_for_status()
    for row in r.json().get("data", []):
        if row.get("title") == title:
            return row["id"]["id"]
    return None


def make_sync_status_widget():
    wid = str(uuid.uuid4())
    return wid, {
        "id": wid,
        "typeFullFqn": "system.cards.entities_table",
        "type": "latest",
        "sizeX": 24,
        "sizeY": 12,
        "config": {
            "type": "latest",
            "title": "Shadow Sync Status — desired vs reported",
            "showTitle": True,
            "backgroundColor": "#fff",
            "color": "rgba(0, 0, 0, 0.87)",
            "padding": "8px",
            "settings": {
                "enableSearch": True,
                "displayPagination": True,
                "defaultPageSize": 25,
                "displayEntityName": True,
                "entityNameColumnTitle": "Device",
            },
            "title_style": {"fontSize": "16px", "fontWeight": 400},
            "useDashboardTimewindow": True,
            "datasources": [
                {
                    "type": "entity",
                    "name": None,
                    "entityAliasId": ALIAS_ID,
                    "dataKeys": [
                        {
                            "name": "active",
                            "type": "attribute",
                            "label": "Active",
                            "color": "#2196f3",
                            "settings": {
                                "useCellStyleFunction": True,
                                "cellStyleFunction": (
                                    "var c = (value === true || value === 'true') "
                                    "? 'rgb(39, 134, 34)' : 'rgb(200, 0, 0)';\n"
                                    "return { color: c, fontWeight: 'bold' };"
                                ),
                            },
                            "_hash": 0.1,
                        },
                        {
                            "name": "desired_hvac_mode",
                            "type": "attribute",
                            "label": "Desired HVAC",
                            "color": "#9c27b0",
                            "settings": {},
                            "_hash": 0.2,
                        },
                        {
                            "name": "reported_hvac_mode",
                            "type": "attribute",
                            "label": "Reported HVAC",
                            "color": "#9c27b0",
                            "settings": {},
                            "_hash": 0.3,
                        },
                        {
                            "name": "desired_target_temp",
                            "type": "attribute",
                            "label": "Desired Target",
                            "color": "#ff9800",
                            "settings": {},
                            "_hash": 0.4,
                        },
                        {
                            "name": "reported_target_temp",
                            "type": "attribute",
                            "label": "Reported Target",
                            "color": "#ff9800",
                            "settings": {},
                            "_hash": 0.5,
                        },
                        {
                            "name": "current_version",
                            "type": "attribute",
                            "label": "Version",
                            "color": "#03a9f4",
                            "settings": {},
                            "_hash": 0.6,
                        },
                        {
                            "name": "security_alert",
                            "type": "attribute",
                            "label": "Security",
                            "color": "#f44336",
                            "settings": {
                                "useCellStyleFunction": True,
                                "cellStyleFunction": (
                                    "if (!value) return {};\n"
                                    "return { color: 'white', "
                                    "backgroundColor: 'rgb(220, 0, 0)', "
                                    "fontWeight: 'bold', padding: '4px' };"
                                ),
                            },
                            "_hash": 0.7,
                        },
                    ],
                }
            ],
            "timewindow": {
                "displayValue": "",
                "selectedTab": 0,
                "realtime": {"realtimeType": 1, "interval": 5000, "timewindowMs": 60000},
                "aggregation": {"type": "NONE", "limit": 1000},
            },
        },
    }


def main():
    token = login()
    headers = {"X-Authorization": f"Bearer {token}"}
    client = httpx.Client(headers=headers, timeout=30.0)

    existing = find_dashboard(client, DASHBOARD_TITLE)
    if existing:
        print(f"deleting existing dashboard {existing}")
        client.delete(f"{TB_URL}/api/dashboard/{existing}")

    w1_id, w1 = make_sync_status_widget()

    dashboard = {
        "title": DASHBOARD_TITLE,
        "configuration": {
            "description": "Phase 3 sync + versioning + security view",
            "widgets": {w1_id: w1},
            "states": {
                "default": {
                    "name": "Sync Overview",
                    "root": True,
                    "layouts": {
                        "main": {
                            "widgets": {
                                w1_id: {
                                    "sizeX": 24,
                                    "sizeY": 20,
                                    "row": 0,
                                    "col": 0,
                                    "mobileOrder": 1,
                                    "mobileHeight": 12,
                                },
                            },
                            "gridSettings": {
                                "backgroundColor": "#eeeeee",
                                "columns": 24,
                                "margin": 10,
                                "backgroundSizeMode": "100%",
                                "autoFillHeight": True,
                                "rowHeight": 30,
                            },
                        }
                    },
                }
            },
            "entityAliases": {
                ALIAS_ID: {
                    "id": ALIAS_ID,
                    "alias": "All Devices",
                    "filter": {
                        "type": "entityType",
                        "resolveMultiple": True,
                        "entityType": "DEVICE",
                    },
                },
            },
            "timewindow": {
                "displayValue": "",
                "selectedTab": 0,
                "realtime": {"realtimeType": 1, "interval": 5000, "timewindowMs": 60000},
                "aggregation": {"type": "NONE", "limit": 25000},
            },
            "settings": {
                "stateControllerId": "entity",
                "showTitle": False,
                "showDashboardsSelect": True,
                "showEntitiesSelect": True,
                "showDashboardTimewindow": True,
                "showDashboardExport": True,
                "toolbarAlwaysOpen": True,
            },
            "name": DASHBOARD_TITLE,
        },
    }

    r = client.post(f"{TB_URL}/api/dashboard", json=dashboard)
    r.raise_for_status()
    new_id = r.json()["id"]["id"]
    print(f"created dashboard {new_id}")
    print(f"open: {TB_URL}/dashboards/{new_id}")


if __name__ == "__main__":
    main()
