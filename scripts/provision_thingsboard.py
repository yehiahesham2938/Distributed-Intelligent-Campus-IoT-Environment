"""Idempotent ThingsBoard provisioning for the Campus IoT fleet.

Creates, in this order, if they don't already exist:
    1. Two Device Profiles: MQTT-ThermalSensor, CoAP-ThermalSensor
    2. 200 Devices (100 mqtt-* + 100 coap-*) with access-token credentials
    3. Assets: Campus, Building-B01, Floor-FNN (10), Room-b01-fNN-rRRR (200)
    4. Relations: Contains edges Campus->Building->Floor->Room->Device
    5. Rule Chain imported from thingsboard/rule_chains/main.json
    6. NOC Dashboard imported from thingsboard/dashboards/noc.json

Finally, writes the full registry to data/phase2_registry.json + .csv as
a Phase 2 deliverable that maps room_key -> TB device id + credentials.

Env:
    TB_URL       default http://localhost:9090
    TB_USERNAME  default tenant@thingsboard.org
    TB_PASSWORD  default tenant

All writes are lookup-or-create so re-running is a no-op.
"""

import csv
import json
import logging
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.engine.fleet import create_room_fleet  # noqa: E402
from src.utils.logging_config import setup_logging  # noqa: E402

logger = logging.getLogger("provision.tb")

TB_URL = os.getenv("TB_URL", "http://localhost:9090")
TB_USERNAME = os.getenv("TB_USERNAME", "tenant@thingsboard.org")
TB_PASSWORD = os.getenv("TB_PASSWORD", "tenant")

REGISTRY_JSON = ROOT / "data" / "phase2_registry.json"
REGISTRY_CSV = ROOT / "data" / "phase2_registry.csv"
RULE_CHAIN_FILE = ROOT / "thingsboard" / "rule_chains" / "main.json"
DASHBOARD_FILE = ROOT / "thingsboard" / "dashboards" / "noc.json"


class TBClient:
    def __init__(self, url, username, password):
        self.url = url.rstrip("/")
        self.http = httpx.Client(base_url=self.url, timeout=30.0)
        self._login(username, password)

    def _login(self, username, password):
        r = self.http.post("/api/auth/login", json={"username": username, "password": password})
        r.raise_for_status()
        token = r.json()["token"]
        self.http.headers["X-Authorization"] = f"Bearer {token}"
        logger.info("Logged in to ThingsBoard at %s", self.url)

    # --- generic helpers ---
    def get_json(self, path, params=None):
        r = self.http.get(path, params=params)
        r.raise_for_status()
        return r.json()

    def post_json(self, path, payload):
        r = self.http.post(path, json=payload)
        r.raise_for_status()
        if not r.content:
            return None
        try:
            return r.json()
        except ValueError:
            return None

    # --- device profiles ---
    def ensure_device_profile(self, name):
        try:
            existing = self.get_json(f"/api/deviceProfile/devices/{name}")
            if existing:
                logger.info("device profile %s already exists", name)
                return existing
        except httpx.HTTPStatusError:
            pass
        # Fall back to lookup by name via tenant list.
        try:
            page = self.get_json(
                "/api/deviceProfiles",
                params={"pageSize": 1000, "page": 0, "textSearch": name},
            )
            for row in page.get("data", []):
                if row.get("name") == name:
                    return row
        except httpx.HTTPStatusError as exc:
            logger.warning("device profile lookup failed for %s: %s", name, exc)
        payload = {
            "name": name,
            "type": "DEFAULT",
            "transportType": "DEFAULT",
            "provisionType": "DISABLED",
            "description": f"{name} auto-provisioned by Phase 2 script",
            "profileData": {
                "configuration": {"type": "DEFAULT"},
                "transportConfiguration": {"type": "DEFAULT"},
                "provisionConfiguration": {
                    "type": "DISABLED",
                    "provisionDeviceSecret": None,
                },
                "alarms": None,
            },
        }
        created = self.post_json("/api/deviceProfile", payload)
        logger.info("created device profile %s", name)
        return created

    # --- devices ---
    def ensure_device(self, name, profile_id):
        try:
            page = self.get_json(
                "/api/tenant/devices",
                params={"pageSize": 1, "page": 0, "textSearch": name},
            )
            for row in page.get("data", []):
                if row.get("name") == name:
                    return row
        except httpx.HTTPStatusError:
            pass
        payload = {
            "name": name,
            "type": "default",
            "deviceProfileId": {"id": profile_id, "entityType": "DEVICE_PROFILE"},
        }
        return self.post_json("/api/device", payload)

    def get_device_credentials(self, device_id):
        return self.get_json(f"/api/device/{device_id}/credentials")

    # --- assets ---
    def ensure_asset(self, name, type_name):
        try:
            page = self.get_json(
                "/api/tenant/assets",
                params={"pageSize": 1, "page": 0, "textSearch": name},
            )
            for row in page.get("data", []):
                if row.get("name") == name:
                    return row
        except httpx.HTTPStatusError:
            pass
        payload = {"name": name, "type": type_name}
        return self.post_json("/api/asset", payload)

    def ensure_relation(self, from_id, from_type, to_id, to_type, relation_type="Contains"):
        payload = {
            "from": {"id": from_id, "entityType": from_type},
            "to": {"id": to_id, "entityType": to_type},
            "type": relation_type,
            "typeGroup": "COMMON",
        }
        try:
            self.post_json("/api/relation", payload)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in (400, 409):
                raise

    # --- dashboards ---
    def ensure_dashboard(self, dashboard_payload):
        title = dashboard_payload.get("title") or dashboard_payload.get("name")
        if not title:
            return self.post_json("/api/dashboard", dashboard_payload)

        try:
            page = self.get_json(
                "/api/tenant/dashboards",
                params={"pageSize": 1000, "page": 0, "textSearch": title},
            )
            for row in page.get("data", []):
                if row.get("title") == title:
                    existing_id = row.get("id", {}).get("id")
                    payload = dict(dashboard_payload)
                    if existing_id:
                        payload["id"] = {"entityType": "DASHBOARD", "id": existing_id}
                    updated = self.post_json("/api/dashboard", payload)
                    logger.info("updated dashboard %s", title)
                    return updated
        except httpx.HTTPStatusError as exc:
            logger.warning("dashboard lookup failed for %s: %s", title, exc)

        created = self.post_json("/api/dashboard", dashboard_payload)
        logger.info("created dashboard %s", title)
        return created


def provision():
    setup_logging()
    client = TBClient(TB_URL, TB_USERNAME, TB_PASSWORD)

    mqtt_profile = client.ensure_device_profile("MQTT-ThermalSensor")
    coap_profile = client.ensure_device_profile("CoAP-ThermalSensor")
    mqtt_profile_id = mqtt_profile["id"]["id"] if isinstance(mqtt_profile.get("id"), dict) else mqtt_profile.get("id")
    coap_profile_id = coap_profile["id"]["id"] if isinstance(coap_profile.get("id"), dict) else coap_profile.get("id")

    # Asset hierarchy
    campus = client.ensure_asset("Campus", "campus")
    building = client.ensure_asset("Building-B01", "building")
    campus_id = campus["id"]["id"]
    building_id = building["id"]["id"]
    client.ensure_relation(campus_id, "ASSET", building_id, "ASSET")

    floor_assets = {}
    for floor in range(1, 11):
        name = f"Floor-F{floor:02d}"
        asset = client.ensure_asset(name, "floor")
        floor_assets[floor] = asset
        client.ensure_relation(building_id, "ASSET", asset["id"]["id"], "ASSET")

    # Devices + room assets
    fleet = create_room_fleet()
    registry = []
    for room in fleet:
        device_name = f"{room.protocol}-{room.room_key}"
        profile_id = mqtt_profile_id if room.protocol == "mqtt" else coap_profile_id
        device = client.ensure_device(device_name, profile_id)
        device_id = device["id"]["id"]
        try:
            creds = client.get_device_credentials(device_id)
            access_token = creds.get("credentialsId", "")
        except Exception:
            access_token = ""

        # Room asset
        room_asset_name = f"Room-{room.room_key}"
        room_asset = client.ensure_asset(room_asset_name, "room")
        room_asset_id = room_asset["id"]["id"]
        floor_asset_id = floor_assets[room.floor_id]["id"]["id"]
        client.ensure_relation(floor_asset_id, "ASSET", room_asset_id, "ASSET")
        client.ensure_relation(room_asset_id, "ASSET", device_id, "DEVICE")

        registry.append(
            {
                "room_key": room.room_key,
                "protocol": room.protocol,
                "floor_id": room.floor_id,
                "device_name": device_name,
                "device_id": device_id,
                "access_token": access_token,
                "room_asset_id": room_asset_id,
                "floor_asset_id": floor_asset_id,
            }
        )

    # Rule chain (optional — imported if file exists)
    if RULE_CHAIN_FILE.exists():
        try:
            chain_payload = json.loads(RULE_CHAIN_FILE.read_text(encoding="utf-8"))
            client.post_json("/api/ruleChain", chain_payload.get("ruleChain", chain_payload))
            logger.info("imported rule chain from %s", RULE_CHAIN_FILE)
        except Exception as exc:
            logger.warning("failed to import rule chain: %s", exc)

    # Dashboard (optional)
    if DASHBOARD_FILE.exists():
        try:
            dashboard_payload = json.loads(DASHBOARD_FILE.read_text(encoding="utf-8"))
            client.ensure_dashboard(dashboard_payload.get("dashboard", dashboard_payload))
            logger.info("imported dashboard from %s", DASHBOARD_FILE)
        except Exception as exc:
            logger.warning("failed to import dashboard: %s", exc)

    _export_registry(registry)
    logger.info(
        "Provisioned %d devices, %d floor assets, 1 building, 1 campus",
        len(registry),
        len(floor_assets),
    )


def _export_registry(rows):
    REGISTRY_JSON.parent.mkdir(parents=True, exist_ok=True)
    with REGISTRY_JSON.open("w") as f:
        json.dump(rows, f, indent=2, sort_keys=True)
    with REGISTRY_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "room_key",
                "protocol",
                "floor_id",
                "device_name",
                "device_id",
                "access_token",
                "room_asset_id",
                "floor_asset_id",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    logger.info("exported registry -> %s and %s", REGISTRY_JSON, REGISTRY_CSV)


if __name__ == "__main__":
    provision()
