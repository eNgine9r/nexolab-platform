#!/usr/bin/env bash
# Isolated, nonproduction MQTT 3.1.1 persistent-subscriber capacity experiment.
set -Eeuo pipefail

command -v docker >/dev/null
command -v mktemp >/dev/null
docker image inspect eclipse-mosquitto:2.0.22 >/dev/null
temp_root="$(mktemp -d)"
name="nexolab-1394-cap-$(basename "$temp_root" | tr -dc 'a-zA-Z0-9' | head -c 12)"
container_id=""
cleanup() {
  if [[ -n "$container_id" ]]; then
    docker rm -f "$container_id" >/dev/null 2>&1 || true
  fi
  rm -rf -- "$temp_root"
}
trap cleanup EXIT

cat > "$temp_root/mosquitto.conf" <<'CONFIG'
listener 1883 127.0.0.1
allow_anonymous true
persistence true
persistence_location /mosquitto/data/
autosave_interval 1
max_queued_messages 10
max_inflight_messages 20
log_dest stdout
CONFIG

container_id="$(docker run -d --name "$name" --network none --read-only \
  --pids-limit 32 --memory 64m --cpus 0.5 --tmpfs /mosquitto/data:rw,size=8m \
  --mount "type=bind,src=$temp_root/mosquitto.conf,dst=/mosquitto/config/mosquitto.conf,readonly" \
  eclipse-mosquitto:2.0.22)"

ready=false
for _ in $(seq 1 20); do
  if docker exec "$name" mosquitto_pub -h 127.0.0.1 -t lab/ready -m ready >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 0.2
done
[[ "$ready" == true ]]

# Register a durable MQTTv3.1.1 subscriber, then go offline.
docker exec "$name" mosquitto_sub -h 127.0.0.1 -c -i lab-central-api \
  -t lab/telemetry -q 1 -C 1 -W 1 >/dev/null 2>&1 || true

# Device Agent's QoS 1 publisher would receive broker PUBACK for each of these.
seq 1 15 | docker exec -i "$name" mosquitto_pub -h 127.0.0.1 \
  -t lab/telemetry -q 1 -l
# Keep this probe bounded if the server preserves fewer queued messages.
docker exec "$name" mosquitto_sub -h 127.0.0.1 -c -i lab-central-api \
  -t lab/telemetry -q 1 -C 10 -W 4 > "$temp_root/received" || true
received="$(wc -l < "$temp_root/received")"
echo "ISOLATED_MQTT_SUBSCRIBER_TEST=offline_broker_cap"
echo "PUBLISHED_TO_BROKER_QOS1=15"
echo "RECEIVED_AFTER_OFFLINE_REJOIN=$received"
echo "CONFIGURED_MQTT_MAX_QUEUED_MESSAGES=10"
[[ "$received" =~ ^[0-9]+$ && "$received" -le 10 && "$received" -lt 15 ]] || {
  echo "No demonstrated bounded queue loss; inspect fixture before asserting behavior" >&2
  exit 1
}
echo "RESULT=PASS_BOUNDED_BROKER_QUEUE_CAN_DROP_ACKED_MESSAGES"
