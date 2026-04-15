"""TLS SSLContext builder for gmqtt clients.

When MQTT_TLS_ENABLED=1, returns an SSLContext that pins to the CA at
MQTT_CA_CERT (default secrets/ca.crt). Otherwise returns None and the
caller must connect in plaintext — intended for unit tests only.
"""

import logging
import os
import ssl

logger = logging.getLogger("security.tls")


def tls_enabled():
    return os.getenv("MQTT_TLS_ENABLED", "0") == "1"


def client_context():
    if not tls_enabled():
        return None
    ca_path = os.getenv("MQTT_CA_CERT", "secrets/ca.crt")
    ctx = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH, cafile=ca_path)
    ctx.check_hostname = os.getenv("MQTT_TLS_CHECK_HOSTNAME", "1") == "1"
    ctx.verify_mode = ssl.CERT_REQUIRED
    logger.info("Built TLS context pinned to CA %s", ca_path)
    return ctx
