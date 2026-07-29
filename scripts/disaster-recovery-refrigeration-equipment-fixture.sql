\set ON_ERROR_STOP on

INSERT INTO refrigeration_equipment (
  id, organization_id, code, name, location, equipment_type, manufacturer,
  model, serial_number, temperature_class, installed_at, serviced_at, status,
  average_temperature_c, min_temperature_c, max_temperature_c, online_sensors,
  total_sensors, active_alarms, last_seen_at, version, created_by, created_at,
  updated_at, deleted_by, deleted_at
) VALUES (
  'K106',
  '00000000-0000-0000-0000-000000000099',
  'DR-K106',
  'DR refrigeration showcase K106',
  'Recovery laboratory · Zone A',
  'Холодильна вітрина',
  'NEXOLAB',
  'DR-1250',
  'DR-K106-0001',
  '3M1 (0…+5 °C)',
  '2026-07-01',
  '2026-07-20',
  'normal',
  2.4,
  1.8,
  3.2,
  2,
  48,
  0,
  '2026-07-28T08:00:00Z',
  1,
  'dr-engineer',
  '2026-07-28T06:49:00Z',
  '2026-07-28T08:00:00Z',
  NULL,
  NULL
);
