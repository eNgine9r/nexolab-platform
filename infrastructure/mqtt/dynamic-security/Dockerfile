FROM eclipse-mosquitto:2.0.22

USER root

RUN set -eu; \
    plugin_path="$(find /usr -type f -name mosquitto_dynamic_security.so -print -quit)"; \
    test -n "$plugin_path"; \
    ln -s "$plugin_path" /usr/lib/mosquitto_dynamic_security.so

COPY mosquitto.conf /mosquitto/config/mosquitto.conf
COPY entrypoint.sh /usr/local/bin/nexolab-mqtt-entrypoint
COPY dynsec-admin.sh /usr/local/bin/nexolab-dynsec-admin

RUN chmod 0755 \
      /usr/local/bin/nexolab-mqtt-entrypoint \
      /usr/local/bin/nexolab-dynsec-admin \
    && mkdir -p /run/secrets /mosquitto/data \
    && chown -R mosquitto:mosquitto /mosquitto/data

ENTRYPOINT ["/usr/local/bin/nexolab-mqtt-entrypoint"]
CMD ["/usr/sbin/mosquitto", "-c", "/mosquitto/config/mosquitto.conf"]
