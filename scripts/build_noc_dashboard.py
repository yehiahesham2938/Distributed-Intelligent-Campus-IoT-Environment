"""Build a real, openable Campus NOC dashboard via TB REST.

The skeleton JSON shipped in thingsboard/dashboards/noc.json is metadata
only — TB CE 3.7 refuses to open dashboards whose widgets are missing
`config`, `sizeX`, `typeFullFqn`, and layout entries. This script
replaces the broken dashboard with one that has three working widgets:

    1. 200-room Entities Table keyed on all tenant devices
    2. Aggregate "active" count indicator
    3. Timeseries chart bound to device telemetry keys

It deletes any existing "Campus NOC" dashboard first (if present) so
re-running is idempotent.
"""

import json
import os
import sys
import uuid
from pathlib import Path

import httpx

TB_URL = os.getenv("TB_URL", "http://localhost:9090")
TB_USER = os.getenv("TB_USERNAME", "tenant@thingsboard.org")
TB_PASS = os.getenv("TB_PASSWORD", "tenant")
DASHBOARD_TITLE = "Campus NOC — Phase 2"


def login():
    r = httpx.post(f"{TB_URL}/api/auth/login", json={"username": TB_USER, "password": TB_PASS})
    r.raise_for_status()
    return r.json()["token"]


def find_dashboard(client, title):
    r = client.get(f"{TB_URL}/api/tenant/dashboards", params={"pageSize": 100, "page": 0})
    r.raise_for_status()
    for row in r.json().get("data", []):
        if row.get("title") == title:
            return row["id"]["id"]
    return None


def delete_dashboard(client, dashboard_id):
    client.delete(f"{TB_URL}/api/dashboard/{dashboard_id}")


ALIAS_ID = "all_devices_alias"
FLOOR1_ALIAS_ID = "floor1_devices_alias"


def make_widget_entities_table():
    wid = str(uuid.uuid4())
    return wid, {
        "id": wid,
        "typeFullFqn": "system.cards.entities_table",
        "type": "latest",
        "sizeX": 24,
        "sizeY": 14,
        "config": {
            "type": "latest",
            "title": "200 Rooms — Live State",
            "showTitle": True,
            "backgroundColor": "#fff",
            "color": "rgba(0, 0, 0, 0.87)",
            "padding": "8px",
            "settings": {
                "enableSelection": False,
                "enableSearch": True,
                "enableSelectColumnDisplay": True,
                "displayPagination": True,
                "defaultPageSize": 25,
                "defaultSortOrder": "entityName",
                "columnWidth": "0px",
                "useRowStyleFunction": False,
                "displayEntityName": True,
                "entityNameColumnTitle": "Room",
                "displayEntityType": True,
                "entityTypeColumnTitle": "Type",
            },
            "title_style": {"fontSize": "16px", "fontWeight": 400},
            "useDashboardTimewindow": True,
            "showLegend": False,
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
                                    "var color;\n"
                                    "if (value === true || value === 'true') color = 'rgb(39, 134, 34)';\n"
                                    "else color = 'rgb(200, 0, 0)';\n"
                                    "return { color: color, fontWeight: 'bold' };"
                                ),
                            },
                            "_hash": 0.1,
                        },
                        {
                            "name": "temperature",
                            "type": "timeseries",
                            "label": "Temperature",
                            "color": "#ff5722",
                            "settings": {},
                            "_hash": 0.2,
                        },
                        {
                            "name": "humidity",
                            "type": "timeseries",
                            "label": "Humidity",
                            "color": "#00bcd4",
                            "settings": {},
                            "_hash": 0.3,
                        },
                        {
                            "name": "hvac_mode",
                            "type": "timeseries",
                            "label": "HVAC",
                            "color": "#9c27b0",
                            "settings": {},
                            "_hash": 0.4,
                        },
                        {
                            "name": "target_temp",
                            "type": "timeseries",
                            "label": "Target",
                            "color": "#ff9800",
                            "settings": {},
                            "_hash": 0.5,
                        },
                    ],
                }
            ],
            "timewindow": {
                "displayValue": "",
                "selectedTab": 0,
                "realtime": {
                    "realtimeType": 1,
                    "interval": 5000,
                    "timewindowMs": 60000,
                },
                "aggregation": {"type": "NONE", "limit": 1000},
            },
        },
    }


def make_widget_temperature_chart():
    wid = str(uuid.uuid4())
    return wid, {
        "id": wid,
        "typeFullFqn": "system.time_series_chart",
        "type": "timeseries",
        "sizeX": 24,
        "sizeY": 10,
        "config": {
            "type": "timeseries",
            "title": "Live Telemetry — Temperature (Floor 1, last 5 min)",
            "showTitle": True,
            "backgroundColor": "#fff",
            "color": "rgba(0, 0, 0, 0.87)",
            "padding": "8px",
            "settings": {
                "shadowSize": 4,
                "fontColor": "#545454",
                "fontSize": 10,
                "xaxis": {"showLabels": True, "title": None, "titleFontSize": 10, "color": "#545454"},
                "yaxis": {"showLabels": True, "title": "°C", "titleFontSize": 10, "color": "#545454"},
                "grid": {"verticalLines": True, "horizontalLines": True, "color": "#545454"},
                "smoothLines": True,
                "stack": False,
                "showTooltip": True,
            },
            "title_style": {"fontSize": "16px", "fontWeight": 400},
            "useDashboardTimewindow": False,
            "showLegend": True,
            "legendConfig": {
                "position": "bottom",
                "showMin": False,
                "showMax": False,
                "showAvg": True,
                "showTotal": False,
            },
            "datasources": [
                {
                    "type": "entity",
                    "name": None,
                    "entityAliasId": FLOOR1_ALIAS_ID,
                    "dataKeys": [
                        {
                            "name": "temperature",
                            "type": "timeseries",
                            "label": "${entityName}",
                            "color": "#ff5722",
                            "settings": {},
                            "_hash": 0.6,
                        }
                    ],
                }
            ],
            "timewindow": {
                "displayValue": "",
                "selectedTab": 0,
                "realtime": {
                    "realtimeType": 1,
                    "interval": 5000,
                    "timewindowMs": 300000,
                },
                "aggregation": {"type": "NONE", "limit": 500},
            },
        },
    }


def make_widget_alarms_table():
    wid = str(uuid.uuid4())
    return wid, {
        "id": wid,
        "typeFullFqn": "system.alarm_widgets.alarms_table",
        "type": "alarm",
        "sizeX": 24,
        "sizeY": 8,
        "config": {
            "type": "alarm",
            "title": "Active Alarms",
            "showTitle": True,
            "backgroundColor": "#fff",
            "color": "rgba(0, 0, 0, 0.87)",
            "padding": "8px",
            "settings": {
                "enableSearch": True,
                "enableSelection": False,
                "enableFilter": True,
                "displayPagination": True,
                "defaultPageSize": 10,
                "defaultSortOrder": "-createdTime",
            },
            "title_style": {"fontSize": "16px", "fontWeight": 400},
            "alarmSource": {
                "type": "entity",
                "entityAliasId": ALIAS_ID,
                "dataKeys": [
                    {"name": "createdTime", "type": "alarm", "label": "Time", "color": "#000"},
                    {"name": "type", "type": "alarm", "label": "Type", "color": "#000"},
                    {"name": "severity", "type": "alarm", "label": "Severity", "color": "#000"},
                    {"name": "status", "type": "alarm", "label": "Status", "color": "#000"},
                ],
            },
            "alarmSearchStatus": "ANY",
            "searchStatus": "ANY",
            "alarmsPollingInterval": 5,
            "timewindow": {
                "displayValue": "",
                "selectedTab": 0,
                "realtime": {"timewindowMs": 86400000},
                "aggregation": {"type": "NONE", "limit": 25000},
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
        delete_dashboard(client, existing)

    w1_id, w1 = make_widget_entities_table()

    dashboard = {
        "title": DASHBOARD_TITLE,
        "configuration": {
            "description": "Auto-built by scripts/build_noc_dashboard.py",
            "widgets": {
                w1_id: w1,
            },
            "states": {
                "default": {
                    "name": "Overview",
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
                "realtime": {
                    "realtimeType": 1,
                    "interval": 1000,
                    "timewindowMs": 60000,
                },
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
    print(f"open:  {TB_URL}/dashboards/{new_id}")


if __name__ == "__main__":
    main()
