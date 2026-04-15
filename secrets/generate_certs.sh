#!/bin/sh
# generate_certs.sh — one-shot self-signed CA + server certs for HiveMQ
# and ThingsBoard. Idempotent: skips existing files unless FORCE=1.
#
# Run: docker compose --profile setup run --rm cert-gen
# Or locally: sh secrets/generate_certs.sh
#
# Output files (all under secrets/):
#   ca.key, ca.crt                — root CA (10y)
#   hivemq_server.key, .crt       — server cert with SAN hivemq,localhost
#   tb_server.key, .crt           — server cert with SAN thingsboard,localhost

set -eu

cd "$(dirname "$0")"

DAYS="${CERT_DAYS:-3650}"

regen() {
    if [ -f "$1" ] && [ -z "${FORCE:-}" ]; then
        echo "skip $1 (exists; set FORCE=1 to regenerate)"
        return 1
    fi
    return 0
}

if regen ca.crt; then
    openssl genrsa -out ca.key 4096
    openssl req -x509 -new -nodes -key ca.key -sha256 -days "$DAYS" \
        -subj "/CN=Campus IoT Dev CA" -out ca.crt
    echo "generated ca.crt"
fi

gen_server_cert() {
    NAME="$1"
    SAN="$2"
    if ! regen "${NAME}.crt"; then return 0; fi
    openssl genrsa -out "${NAME}.key" 2048
    openssl req -new -key "${NAME}.key" \
        -subj "/CN=${NAME}" \
        -out "${NAME}.csr"
    cat > "${NAME}.ext" <<EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = ${SAN}
EOF
    openssl x509 -req -in "${NAME}.csr" -CA ca.crt -CAkey ca.key -CAcreateserial \
        -out "${NAME}.crt" -days "$DAYS" -sha256 -extfile "${NAME}.ext"
    rm -f "${NAME}.csr" "${NAME}.ext"
    echo "generated ${NAME}.crt"
}

gen_server_cert hivemq_server "DNS:hivemq,DNS:localhost,IP:127.0.0.1"
gen_server_cert tb_server "DNS:thingsboard,DNS:localhost,IP:127.0.0.1"

echo "certs ready in secrets/"
