export type CommissionedChannel = {
  nodeId: string;
  equipmentId: string;
  channelId: string;
  controllerLabel: string;
  inputNumber: number;
  displayName: string;
  customName: string | null;
};

export type CommissionedChannelInventory = {
  state: "available" | "unavailable";
  nodeId: string | null;
  items: CommissionedChannel[];
};

export interface ChannelNameRepository {
  list(signal?: AbortSignal): Promise<CommissionedChannelInventory>;
  setName(nodeId: string, channelId: string, displayName: string | null): Promise<CommissionedChannel>;
}

export class HttpChannelNameRepository implements ChannelNameRepository {
  constructor(
    private readonly baseUrl: string,
    private readonly fetchImpl: typeof fetch,
  ) {}

  async list(signal?: AbortSignal): Promise<CommissionedChannelInventory> {
    const response = await this.fetchImpl(`${this.baseUrl}/api/v1/equipment/commissioned-channels`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal,
    });
    if (!response.ok) throw new Error("Не вдалося завантажити активний реєстр Dixell.");
    const data: unknown = await response.json();
    if (
      !isRecord(data) ||
      !Array.isArray(data.items) ||
      (data.state !== "available" && data.state !== "unavailable")
    ) {
      throw new Error("Некоректна відповідь реєстру каналів.");
    }
    return {
      state: data.state,
      nodeId: typeof data.node_id === "string" ? data.node_id : null,
      items: data.items.map(parseChannel),
    };
  }

  async setName(nodeId: string, channelId: string, displayName: string | null): Promise<CommissionedChannel> {
    const response = await this.fetchImpl(
      `${this.baseUrl}/api/v1/equipment/commissioned-channels/${encodeURIComponent(channelId)}/display-name`,
      {
        method: "PUT",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ node_id: nodeId, display_name: displayName }),
      },
    );
    if (!response.ok) throw new Error("Не вдалося зберегти назву каналу. Перевірте доступ та стан вузла.");
    return parseChannel(await response.json());
  }
}

function isRecord(data: unknown): data is Record<string, unknown> {
  return data !== null && typeof data === "object" && !Array.isArray(data);
}

function parseChannel(data: unknown): CommissionedChannel {
  if (
    !isRecord(data) ||
    typeof data.node_id !== "string" ||
    typeof data.equipment_id !== "string" ||
    typeof data.channel_id !== "string" ||
    typeof data.controller_label !== "string" ||
    typeof data.input_number !== "number" ||
    !Number.isInteger(data.input_number) ||
    data.input_number < 1 ||
    data.input_number > 6 ||
    typeof data.display_name !== "string" ||
    (data.custom_name != null && typeof data.custom_name !== "string")
  ) {
    throw new Error("Некоректний канал у відповіді API.");
  }
  return {
    nodeId: data.node_id,
    equipmentId: data.equipment_id,
    channelId: data.channel_id,
    controllerLabel: data.controller_label,
    inputNumber: data.input_number,
    displayName: data.display_name,
    customName: data.custom_name ?? null,
  };
}
