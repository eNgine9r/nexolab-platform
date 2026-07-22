# NEXOLAB Edge bootstrap

Цей контур є першим вертикальним зрізом NEXOLAB: симулятор температури → локальна SQLite-черга → MQTT → health endpoint.

## Локальний запуск

```bash
cp infrastructure/compose/.env.edge.example infrastructure/compose/.env
cd infrastructure/compose
docker compose -f compose.edge.yaml -f compose.dev.yaml up --build
```

Перевірка:

```bash
curl http://127.0.0.1:8081/health
docker compose -f compose.edge.yaml logs -f device-agent
```

Health endpoint повертає стан MQTT, кількість локально накопичених пакетів, час останнього вимірювання та останню помилку.

## Raspberry Pi 5

Рекомендована база:

- Raspberry Pi OS Lite 64-bit;
- NVMe як системний диск;
- hostname `nexolab-edge-01`;
- SSH лише за ключами;
- Tailscale для приватного доступу;
- часова зона `Europe/Uzhgorod` і синхронізація часу через Chrony.

### Підготовка inventory

```bash
cp infrastructure/ansible/inventory/hosts.example.ini \
  infrastructure/ansible/inventory/hosts.ini
```

Замініть `ansible_host` на Tailscale IP Raspberry Pi. Далі з робочого комп'ютера:

```bash
ansible-playbook \
  -i infrastructure/ansible/inventory/hosts.ini \
  infrastructure/ansible/provision-edge.yml
```

Playbook не перезаписує `/opt/nexolab/compose/.env`, тому локальні ідентифікатори вузла та секрети не губляться при повторному запуску.

## Оновлення застосунку

Workflow `Edge image` збирає `linux/amd64` і `linux/arm64` образи. Після merge у `main` публікується:

```text
ghcr.io/engine9r/nexolab-device-agent:edge
```

На вузлі:

```bash
cd /opt/nexolab/compose
docker compose pull
docker compose up -d --remove-orphans
curl --fail http://127.0.0.1:8081/health
```

Автоматичний deployment через Tailscale буде додано після прив'язки першого Pi та створення GitHub Environment `edge-01`.

## Наступний адаптер

Після перевірки offline-черги додаємо перший Modbus RTU драйвер. Для старту рекомендовано LE-01MP або Dixell XJP60D через ізольований USB–RS485 адаптер. Апаратний порт потрібно вказувати через `/dev/serial/by-id/...`, а не `/dev/ttyUSB0`.
