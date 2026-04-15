#!/bin/bash
# Phase 2 Campus IoT — one-command launcher.
#
# Brings up the full stack end-to-end:
#   1. Regenerates secrets if missing
#   2. Renders gateway flows if missing
#   3. Starts HiveMQ + Postgres + ThingsBoard
#   4. Waits for ThingsBoard to be ready
#   5. Runs the provisioner (idempotent)
#   6. Starts the engine + 10 Node-RED gateways
#   7. Starts the HiveMQ->ThingsBoard bridge so all 200 devices go Active
#
# After it finishes, open http://localhost:9090 (tenant@thingsboard.org / tenant).
#
# Usage: ./run_all.sh [--down|--logs|--status]

set -e
cd "$(dirname "$0")"

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

step() { echo -e "${BLUE}==>${NC} $1"; }
ok()   { echo -e "${GREEN}  ok${NC} $1"; }
warn() { echo -e "${YELLOW}  !!${NC} $1"; }
err()  { echo -e "${RED}  ERR${NC} $1" >&2; }

case "${1:-up}" in
    down)
        step "Stopping HiveMQ->TB bridge"
        pkill -f "bridge_hivemq_to_tb" 2>/dev/null || true
        step "Stopping all containers"
        docker compose --profile setup down
        ok "stack down"
        exit 0
        ;;
    logs)
        docker compose logs -f --tail=20 "${@:2}"
        exit 0
        ;;
    status)
        docker compose ps
        echo ""
        pgrep -af "bridge_hivemq_to_tb" || echo "(bridge not running)"
        exit 0
        ;;
    up|"")
        ;;
    *)
        echo "usage: $0 [up|down|logs|status]"; exit 1
        ;;
esac

# ----- 1. Secrets -------------------------------------------------------
step "Secrets"
if [ ! -f secrets/ca.crt ]; then
    sh secrets/generate_certs.sh
    ok "certs generated"
else
    ok "certs already exist"
fi
if [ ! -f secrets/coap_psk.json ]; then
    venv/bin/python secrets/generate_psk.py
fi
if [ ! -f secrets/mqtt_credentials.csv ]; then
    venv/bin/python secrets/generate_mqtt_creds.py
fi
ok "secrets ready"

# ----- 2. Gateway flows -------------------------------------------------
step "Gateway flows"
if [ ! -f gateways/floor_01/flows.json ]; then
    venv/bin/python gateways/render_flows.py
fi
ok "10 floor flow files ready"

# ----- 3. Backbone ------------------------------------------------------
step "Starting backbone (hivemq, postgres, thingsboard)"
docker compose up -d hivemq thingsboard-postgres thingsboard
ok "backbone containers started"

# ----- 4. Wait for ThingsBoard ------------------------------------------
step "Waiting for ThingsBoard to finish booting (up to 3 minutes)"
READY=0
for i in $(seq 1 36); do
    if docker compose logs thingsboard 2>&1 | grep -q "Started ThingsboardServerApplication"; then
        READY=1
        break
    fi
    printf "."
    sleep 5
done
echo ""
if [ "$READY" = "0" ]; then
    err "ThingsBoard did not report ready — check: docker compose logs thingsboard"
    exit 1
fi
ok "ThingsBoard ready"

# ----- 5. Provisioner ---------------------------------------------------
step "Provisioning ThingsBoard (200 devices, 211 assets, dashboard)"
TB_URL=http://localhost:9090 \
TB_USERNAME=tenant@thingsboard.org \
TB_PASSWORD=tenant \
    venv/bin/python scripts/provision_thingsboard.py 2>&1 | tail -5
ok "provisioning complete"

# ----- 6. Engine + gateways ---------------------------------------------
step "Starting engine + 10 floor gateways"
docker compose up -d app \
    gateway-floor-01 gateway-floor-02 gateway-floor-03 gateway-floor-04 gateway-floor-05 \
    gateway-floor-06 gateway-floor-07 gateway-floor-08 gateway-floor-09 gateway-floor-10
ok "engine + gateways up"

# ----- 7. HiveMQ -> ThingsBoard bridge ----------------------------------
step "Starting HiveMQ -> ThingsBoard bridge"
# Kill any previous bridge
pkill -f "bridge_hivemq_to_tb" 2>/dev/null || true
mkdir -p data
nohup venv/bin/python scripts/bridge_hivemq_to_tb.py > data/bridge.log 2>&1 &
BRIDGE_PID=$!
sleep 2
if kill -0 $BRIDGE_PID 2>/dev/null; then
    ok "bridge running as pid $BRIDGE_PID, log: data/bridge.log"
else
    err "bridge failed to start — check data/bridge.log"
    tail -20 data/bridge.log
    exit 1
fi

echo ""
echo -e "${GREEN}===========================================${NC}"
echo -e "${GREEN}   Campus IoT Phase 2 stack is LIVE${NC}"
echo -e "${GREEN}===========================================${NC}"
echo ""
echo "  ThingsBoard UI:  http://localhost:9090"
echo "    login:         tenant@thingsboard.org / tenant"
echo ""
echo "  HiveMQ MQTT:     localhost:1883 (plain)"
echo "  TB MQTT:         localhost:1884 (device auth)"
echo ""
echo "  Useful commands:"
echo "    ./run_all.sh status         container + bridge state"
echo "    ./run_all.sh logs app       tail engine logs"
echo "    ./run_all.sh logs hivemq    tail broker logs"
echo "    ./run_all.sh down           stop everything"
echo ""
echo "  Live bridge metrics: tail -f data/bridge.log"
echo "  Live telemetry tap:  mosquitto_sub -h localhost -p 1883 -t 'campus/#' -v"
