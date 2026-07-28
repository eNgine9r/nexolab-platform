#!/usr/bin/env bash
set -Eeuo pipefail

SECRETS_DIR=${1:?secrets directory is required}
EVIDENCE_DIR=${2:?evidence directory is required}
SERVER_DIR=${MQTT_TLS_SERVER_DIR:?MQTT_TLS_SERVER_DIR is required}

command -v openssl >/dev/null 2>&1 || {
  echo "openssl is required for MQTT TLS acceptance." >&2
  exit 1
}

rm -rf "$SERVER_DIR"
mkdir -p "$SECRETS_DIR" "$EVIDENCE_DIR" "$SERVER_DIR"
umask 077

WORK_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT INT TERM

cat >"$WORK_DIR/ca.cnf" <<'EOF'
[req]
prompt=no
distinguished_name=distinguished_name
x509_extensions=v3_ca

[distinguished_name]
CN=NEXOLAB MQTT Acceptance CA

[v3_ca]
basicConstraints=critical,CA:TRUE,pathlen:0
keyUsage=critical,keyCertSign,cRLSign
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid:always,issuer
EOF

cat >"$WORK_DIR/wrong-ca.cnf" <<'EOF'
[req]
prompt=no
distinguished_name=distinguished_name
x509_extensions=v3_ca

[distinguished_name]
CN=NEXOLAB Untrusted Acceptance CA

[v3_ca]
basicConstraints=critical,CA:TRUE,pathlen:0
keyUsage=critical,keyCertSign,cRLSign
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid:always,issuer
EOF

cat >"$WORK_DIR/server-ext.cnf" <<'EOF'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
subjectAltName=DNS:mqtt
EOF

openssl genpkey \
  -algorithm RSA \
  -pkeyopt rsa_keygen_bits:2048 \
  -out "$WORK_DIR/ca.key" \
  >/dev/null 2>&1
openssl req \
  -x509 \
  -new \
  -sha256 \
  -days 2 \
  -key "$WORK_DIR/ca.key" \
  -config "$WORK_DIR/ca.cnf" \
  -out "$SECRETS_DIR/mqtt-ca.pem" \
  >/dev/null 2>&1

openssl genpkey \
  -algorithm RSA \
  -pkeyopt rsa_keygen_bits:2048 \
  -out "$SERVER_DIR/mqtt-server.key" \
  >/dev/null 2>&1
openssl req \
  -new \
  -sha256 \
  -key "$SERVER_DIR/mqtt-server.key" \
  -subj '/CN=mqtt' \
  -out "$WORK_DIR/mqtt-server.csr" \
  >/dev/null 2>&1
openssl x509 \
  -req \
  -sha256 \
  -days 2 \
  -in "$WORK_DIR/mqtt-server.csr" \
  -CA "$SECRETS_DIR/mqtt-ca.pem" \
  -CAkey "$WORK_DIR/ca.key" \
  -CAcreateserial \
  -extfile "$WORK_DIR/server-ext.cnf" \
  -out "$SERVER_DIR/mqtt-server.pem" \
  >/dev/null 2>&1

openssl genpkey \
  -algorithm RSA \
  -pkeyopt rsa_keygen_bits:2048 \
  -out "$WORK_DIR/wrong-ca.key" \
  >/dev/null 2>&1
openssl req \
  -x509 \
  -new \
  -sha256 \
  -days 2 \
  -key "$WORK_DIR/wrong-ca.key" \
  -config "$WORK_DIR/wrong-ca.cnf" \
  -out "$SECRETS_DIR/mqtt-wrong-ca.pem" \
  >/dev/null 2>&1

chmod 0444 \
  "$SECRETS_DIR/mqtt-ca.pem" \
  "$SECRETS_DIR/mqtt-wrong-ca.pem" \
  "$SERVER_DIR/mqtt-server.pem" \
  "$SERVER_DIR/mqtt-server.key"

openssl verify \
  -CAfile "$SECRETS_DIR/mqtt-ca.pem" \
  -verify_hostname mqtt \
  "$SERVER_DIR/mqtt-server.pem" \
  >/dev/null
if openssl verify \
  -CAfile "$SECRETS_DIR/mqtt-ca.pem" \
  -verify_hostname mqtt-wrong-host \
  "$SERVER_DIR/mqtt-server.pem" \
  >/dev/null 2>&1; then
  echo "Generated MQTT server certificate unexpectedly accepts wrong hostname." >&2
  exit 1
fi

CA_TEXT="$(openssl x509 -in "$SECRETS_DIR/mqtt-ca.pem" -noout -text)"
printf '%s\n' "$CA_TEXT" | grep -Fq 'CA:TRUE'
printf '%s\n' "$CA_TEXT" | grep -Fq 'Certificate Sign'

{
  printf 'ca_sha256='
  openssl x509 -in "$SECRETS_DIR/mqtt-ca.pem" -noout -fingerprint -sha256 \
    | cut -d= -f2
  printf 'server_sha256='
  openssl x509 -in "$SERVER_DIR/mqtt-server.pem" -noout -fingerprint -sha256 \
    | cut -d= -f2
  printf '%s\n' \
    'ca_basic_constraints=CA:TRUE' \
    'ca_key_usage=keyCertSign' \
    'server_san=DNS:mqtt' \
    'wrong_hostname_preflight=rejected' \
    'private_key_in_evidence=false'
} >"$EVIDENCE_DIR/mqtt-certificate-evidence.txt"
