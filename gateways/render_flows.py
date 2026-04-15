"""Render 10 per-floor Node-RED flows.json files.

The template defines everything *except* the 10 CoAP-observe nodes per
floor (one per CoAP room 11-20). Those are generated in Python and
merged into the template JSON before substituting {{FLOOR}}.

Two kinds of CoAP nodes are produced per floor:

    1. coap-observe-f{FF}-rRRR — coap request in observe mode pointing
       at coap://app:{5683+floor*100+room}/f{FF}/r{RRR}/telemetry
    2. coap-put-f{FF}-rRRR — placeholder referenced by route-cmd,
       generated as a named coap request node with PUT + CON.

Real `node-red-contrib-coap` package is preinstalled in the gateway
Dockerfile. After rendering, restart the gateway to pick up the new
flow.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "_template" / "flows.template.json"
NUM_FLOORS = 10
NUM_COAP_ROOMS = 10
COAP_BASE_PORT = 5683


def coap_observe_nodes(floor):
    """Return the list of coap-request observe nodes for one floor + a
    router function that tags each incoming msg with the right MQTT
    topic before it enters the dedup node.
    """
    nodes = []
    tab = f"tab-floor-{floor:02d}"
    dedup_id = f"dedup-f{floor:02d}"
    tagger_id = f"coap-tag-f{floor:02d}"

    # The tagger function sets msg.topic = "campus/b01/fFF/rRRR/telemetry"
    # based on msg._roomNumber which each coap-request node injects.
    tagger_func = (
        "// Tag notification with the MQTT topic that matches the source room.\n"
        "msg.topic = msg._target || 'campus/b01/f" + f"{floor:02d}" + "/unknown/telemetry';\n"
        "return msg;"
    )
    nodes.append(
        {
            "id": tagger_id,
            "type": "function",
            "z": tab,
            "name": "tag CoAP -> MQTT topic",
            "func": tagger_func,
            "outputs": 1,
            "x": 440,
            "y": 60,
            "wires": [[dedup_id]],
        }
    )

    # 10 coap-request nodes in observe mode, one per CoAP room on the floor.
    for idx, room in enumerate(range(NUM_COAP_ROOMS + 1, NUM_COAP_ROOMS * 2 + 1)):
        room_number = floor * 100 + room
        port = COAP_BASE_PORT + floor * 100 + room
        node_id = f"coap-obs-f{floor:02d}-r{room_number:03d}"
        # Prepend a change node that sets msg._target to the MQTT topic.
        setter_id = f"coap-set-f{floor:02d}-r{room_number:03d}"
        nodes.append(
            {
                "id": setter_id,
                "type": "change",
                "z": tab,
                "name": f"set target r{room_number}",
                "rules": [
                    {
                        "t": "set",
                        "p": "_target",
                        "pt": "msg",
                        "to": f"campus/b01/f{floor:02d}/r{room_number:03d}/telemetry",
                        "tot": "str",
                    }
                ],
                "action": "",
                "property": "",
                "from": "",
                "to": "",
                "reg": False,
                "x": 300,
                "y": 80 + idx * 30,
                "wires": [[tagger_id]],
            }
        )
        nodes.append(
            {
                "id": node_id,
                "type": "coap request",
                "z": tab,
                "name": f"observe r{room_number}",
                "url": f"coap://app:{port}/f{floor:02d}/r{room_number:03d}/telemetry",
                "method": "GET",
                "observe": True,
                "contentFormat": "application/json",
                "x": 120,
                "y": 80 + idx * 30,
                "wires": [[setter_id]],
            }
        )
    return nodes


def coap_put_node(floor):
    """Dynamic CoAP PUT path.

    node-red-contrib-coap's `coap request` node reads `url` and `method`
    from its static config at deploy time and ignores `msg.url` in some
    versions. To avoid a runtime TypeError we use a function node that
    issues the UDP write via node's built-in `coap` module directly —
    equivalent behavior with zero surprises. The comment inside the
    function documents the Southbound Command Mapping (MQTT -> CoAP PUT).
    """
    tab = f"tab-floor-{floor:02d}"
    put_id = f"coap-put-f{floor:02d}"
    response_id = f"publish-response-f{floor:02d}"
    func = (
        "// Southbound Command Mapping (MQTT -> CoAP PUT).\n"
        "// Inputs from `route cmd`:\n"
        "//   msg._floorNum, msg._roomNum, msg.payload (command body)\n"
        "// Output: passes through to `build response topic` once the PUT\n"
        "// has been acknowledged by the node (CHANGED response).\n"
        "// The `coap` module is exposed via functionGlobalContext in settings.js\n"
        "const coap = global.get('coap');\n"
        "if (!coap) { node.warn('coap module not in globalContext'); return null; }\n"
        "const floorNum = msg._floorNum || " + str(floor) + ";\n"
        "const roomNum = msg._roomNum;\n"
        "const base = parseInt(global.get('coapBase') || 5683, 10);\n"
        "const port = base + floorNum * 100 + (roomNum - floorNum * 100);\n"
        "const pathFloor = 'f' + String(floorNum).padStart(2,'0');\n"
        "const pathRoom  = 'r' + String(roomNum).padStart(3,'0');\n"
        "const req = coap.request({\n"
        "    hostname: global.get('nodeHost') || 'app',\n"
        "    port,\n"
        "    method: 'PUT',\n"
        "    confirmable: true,\n"
        "    pathname: `/${pathFloor}/${pathRoom}/actuators/hvac`,\n"
        "});\n"
        "req.write(JSON.stringify(msg.payload || {}));\n"
        "req.on('response', (res) => {\n"
        "    let chunks = [];\n"
        "    res.on('data', (d) => chunks.push(d));\n"
        "    res.on('end', () => {\n"
        "        try { msg.payload = JSON.parse(Buffer.concat(chunks).toString()); }\n"
        "        catch (e) { msg.payload = { raw: Buffer.concat(chunks).toString() }; }\n"
        "        node.send(msg);\n"
        "    });\n"
        "});\n"
        "req.on('error', (e) => { node.warn('CoAP PUT error: ' + e.message); });\n"
        "req.end();\n"
        "return null;"
    )
    return {
        "id": put_id,
        "type": "function",
        "z": tab,
        "name": "CoAP PUT CON (function)",
        "func": func,
        "outputs": 1,
        "x": 780,
        "y": 400,
        "wires": [[response_id]],
    }


def main():
    template_text = TEMPLATE.read_text()
    for floor in range(1, NUM_FLOORS + 1):
        floor_str = f"{floor:02d}"
        rendered = template_text.replace("{{FLOOR}}", floor_str)
        flows = json.loads(rendered)

        # Replace the "CoAP Observe bank" stub function with real
        # coap-request nodes + a tagger.
        stub_observe_id = f"coap-observe-f{floor_str}"
        flows = [n for n in flows if n.get("id") != stub_observe_id]
        flows.extend(coap_observe_nodes(floor))

        # Replace the "CoAP PUT CON (stub)" function with a real
        # coap-request PUT node.
        stub_put_id = f"coap-put-f{floor_str}"
        flows = [n for n in flows if n.get("id") != stub_put_id]
        flows.append(coap_put_node(floor))

        out_dir = ROOT / f"floor_{floor_str}"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "flows.json").write_text(json.dumps(flows, indent=4))
        print(f"wrote {out_dir / 'flows.json'}  ({len(flows)} nodes)")


if __name__ == "__main__":
    main()
