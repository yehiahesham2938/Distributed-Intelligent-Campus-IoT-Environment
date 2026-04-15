// Minimal Node-RED settings for the Phase 2 floor gateways.
// No projects, no editor auth (dev-only), flow file baked in per container.
module.exports = {
    flowFile: "/data/flows.json",
    flowFilePretty: true,
    uiPort: process.env.PORT || 1880,
    logging: {
        console: {
            level: "info",
            metrics: false,
            audit: false
        }
    },
    editorTheme: {
        projects: { enabled: false }
    },
    functionGlobalContext: {
        floor: process.env.FLOOR || "01",
        building: process.env.BUILDING || "b01",
        hivemqHost: process.env.HIVEMQ_HOST || "hivemq",
        hivemqPort: parseInt(process.env.HIVEMQ_PORT || "1883", 10),
        coapBase: parseInt(process.env.COAP_BASE_PORT || "5683", 10),
        nodeHost: process.env.NODE_HOST || "app",
        coap: require("coap")   // expose CoAP client to function nodes
    },
    // Allow function nodes to require() this specific module.
    functionExternalModules: true
};
