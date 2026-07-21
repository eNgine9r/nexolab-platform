export type NodeState = "online" | "standby" | "warning";
export type AlarmSeverity = "critical" | "warning" | "info";

export interface EdgeNode {
  id: string;
  name: string;
  channels: string;
  cpu: number;
  ram: number;
  state: NodeState;
  spark: number[];
}

export interface Alarm {
  title: string;
  source: string;
  value: string;
  time: string;
  severity: AlarmSeverity;
}

export interface TestSession {
  name: string;
  stage: string;
  progress: number;
  remaining: string;
  accent: "cyan" | "green" | "amber" | "violet";
}

export const kpis = [
  {
    label: "Вузлів онлайн",
    value: "6 / 6",
    detail: "100% доступності",
    trend: "+0,4% за 7 днів",
    tone: "blue",
    icon: "network",
  },
  {
    label: "Активних датчиків",
    value: "342",
    detail: "+24 за сьогодні",
    trend: "99,8% quality",
    tone: "green",
    icon: "signal",
  },
  {
    label: "Активних сесій",
    value: "4",
    detail: "2 критичні етапи",
    trend: "1 завершується скоро",
    tone: "cyan",
    icon: "session",
  },
  {
    label: "Активних тривог",
    value: "12",
    detail: "3 критичні",
    trend: "−4 за останню годину",
    tone: "red",
    icon: "alarm",
  },
  {
    label: "Поточне споживання",
    value: "24.7 kW",
    detail: "▲ 8,3% до вчора",
    trend: "пік 28,3 kW",
    tone: "amber",
    icon: "energy",
  },
  {
    label: "Середня температура",
    value: "4.2 °C",
    detail: "У межах норми",
    trend: "Δ 0,7 °C / 24 год",
    tone: "blue",
    icon: "temperature",
  },
] as const;

export const edgeNodes: EdgeNode[] = [
  {
    id: "Pi-01",
    name: "Холодильні вітрини",
    channels: "42 канали",
    cpu: 42,
    ram: 55,
    state: "online",
    spark: [31, 33, 30, 34, 32, 41, 38, 47, 44, 56],
  },
  {
    id: "Pi-02",
    name: "Кліматична камера",
    channels: "18 каналів",
    cpu: 35,
    ram: 48,
    state: "online",
    spark: [28, 31, 30, 36, 33, 35, 41, 39, 44, 42],
  },
  {
    id: "Pi-03",
    name: "Поштомати",
    channels: "36 каналів",
    cpu: 48,
    ram: 62,
    state: "online",
    spark: [37, 42, 39, 44, 40, 46, 43, 52, 49, 55],
  },
  {
    id: "Pi-04",
    name: "Енергомоніторинг",
    channels: "12 каналів",
    cpu: 31,
    ram: 44,
    state: "online",
    spark: [24, 27, 25, 29, 28, 32, 31, 35, 34, 39],
  },
  {
    id: "Pi-05",
    name: "Камери та контроль",
    channels: "9 пристроїв",
    cpu: 37,
    ram: 50,
    state: "warning",
    spark: [30, 34, 32, 36, 35, 42, 39, 46, 43, 47],
  },
  {
    id: "Pi-06",
    name: "Резервний координатор",
    channels: "Standby",
    cpu: 22,
    ram: 35,
    state: "standby",
    spark: [18, 20, 19, 22, 21, 24, 23, 27, 25, 28],
  },
];

export const alarms: Alarm[] = [
  {
    title: "Температура вище норми",
    source: "Кліматична камера · TC-02",
    value: "12.2 °C",
    time: "10:04:45",
    severity: "critical",
  },
  {
    title: "Двері відчинено",
    source: "Вхідні двері · Лабораторія 1",
    value: "2 хв",
    time: "10:01:12",
    severity: "warning",
  },
  {
    title: "Рух виявлено",
    source: "CAM-01 · Зона складу",
    value: "Подія",
    time: "09:58:33",
    severity: "info",
  },
  {
    title: "Високе споживання",
    source: "LE-01MP · Лабораторія",
    value: "28.3 kW",
    time: "09:55:21",
    severity: "warning",
  },
];

export const sessions: TestSession[] = [
  {
    name: "ISO 23953 — Вітрина 1200",
    stage: "Стабілізація",
    progress: 65,
    remaining: "03:45:12",
    accent: "cyan",
  },
  {
    name: "Кліматичне випробування #45",
    stage: "Основний етап",
    progress: 42,
    remaining: "08:16:33",
    accent: "green",
  },
  {
    name: "Тестування поштомата #12",
    stage: "Підготовка",
    progress: 12,
    remaining: "11:22:07",
    accent: "amber",
  },
  {
    name: "Енергетичний тест #08",
    stage: "Збір даних",
    progress: 78,
    remaining: "02:33:44",
    accent: "violet",
  },
];

export const chartSeries = [
  {
    id: "TC-01",
    label: "Повітря в камері",
    color: "#00c6e0",
    value: "2.1 °C",
    points: [55, 57, 54, 60, 58, 63, 59, 62, 66, 61, 64, 67, 65, 70, 74, 69, 64, 66, 63, 68, 65, 71, 68, 70],
  },
  {
    id: "TC-02",
    label: "Продукт, центр",
    color: "#7ed321",
    value: "−1.8 °C",
    points: [36, 38, 35, 39, 34, 37, 40, 42, 41, 44, 46, 45, 48, 49, 47, 50, 39, 37, 41, 38, 42, 39, 43, 41],
  },
  {
    id: "TC-03",
    label: "Випарник",
    color: "#0077ff",
    value: "−18.7 °C",
    points: [47, 46, 48, 49, 47, 50, 51, 49, 52, 50, 53, 54, 52, 56, 58, 54, 51, 53, 50, 52, 54, 53, 55, 54],
  },
  {
    id: "TC-04",
    label: "Навколишнє середовище",
    color: "#a855f7",
    value: "22.4 °C",
    points: [22, 28, 27, 24, 25, 23, 21, 20, 22, 18, 19, 21, 20, 24, 29, 26, 21, 18, 16, 20, 19, 23, 21, 22],
  },
] as const;
