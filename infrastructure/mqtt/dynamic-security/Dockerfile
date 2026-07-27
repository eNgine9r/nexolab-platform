FROM eclipse-mosquitto:2.0.22

USER root

RUN apk add --no-cache jq \
    && set -eu; \
    plugin_path="$(find /usr -type f -name mosquitto_dynamic_security.so -print -quit)"; \
    test -n "$plugin_path"; \
    mkdir -p /usr/local/lib/nexolab; \
    cp "$plugin_path" /usr/local/lib/nexolab/mosquitto_dynamic_security.so; \
    chmod 0755 /usr/local/lib/nexolab/mosquitto_dynamic_security.so

COPY mosquitto.conf /mosquitto/config/mosquitto.conf
COPY entrypoint.sh /usr/local/bin/nexolab-mqtt-entrypoint
COPY dynsec-admin.sh /usr/local/bin/nexolab-dynsec-admin
COPY mosquitto-pub-config-compat.sh /usr/local/bin/mosquitto_pub

RUN chmod 0755 \
      /usr/local/bin/nexolab-mqtt-entrypoint \
      /usr/local/bin/nexolab-dynsec-admin \
      /usr/local/bin/mosquitto_pub \
    && mkdir -p /run/secrets /mosquitto/data \
    && chown -R mosquitto:mosquitto /mosquitto/data

ENTRYPOINT ["/usr/local/bin/nexolab-mqtt-entrypoint"]
CMD ["/usr/sbin/mosquitto", "-c", "/mosquitto/config/mosquitto.conf"]
