import type { EquipmentImageMetadata } from "@/data/refrigeration";

import type { LayoutPlacement } from "./layout-editor";
import {
  draftEtag,
  requestFailed,
  type LayoutRepositoryError,
  type PublishedLayoutRevision,
  type RefrigerationLayoutDraft,
  type RefrigerationLayoutRepository,
  type RepositoryResult,
  type RestoreLayoutRevisionInput,
  type SaveLayoutDraftInput,
  type UploadEquipmentImageInput,
  type PublishLayoutDraftInput,
} from "./layout-repository";

const DEFAULT_TIMEOUT_MS = 12_000;

export type HttpRefrigerationLayoutRepositoryOptions = {
  apiBaseUrl: string;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
};

type JsonRecord = Record<string, unknown>;

type TransportResult =
  | { ok: true; response: Response; payload: unknown }
  | { ok: false; error: LayoutRepositoryError };

export class HttpRefrigerationLayoutRepository
  implements RefrigerationLayoutRepository
{
  private readonly apiBaseUrl: string;
  private readonly fetchImpl: typeof fetch;
  private readonly timeoutMs: number;

  constructor(options: HttpRefrigerationLayoutRepositoryOptions) {
    this.apiBaseUrl = normalizeBaseUrl(options.apiBaseUrl);
    this.fetchImpl = options.fetchImpl ?? fetch;
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  }

  async getDraft(
    equipmentId: string,
  ): Promise<RepositoryResult<RefrigerationLayoutDraft>> {
    const result = await this.send(
      equipmentId,
      `/api/v1/equipment/${encodeURIComponent(equipmentId)}/layout/draft`,
    );
    if (!result.ok) return result;

    return parseDraftResult(equipmentId, result.response, result.payload);
  }

  async getPublished(
    equipmentId: string,
  ): Promise<RepositoryResult<PublishedLayoutRevision | null>> {
    const result = await this.send(
      equipmentId,
      `/api/v1/equipment/${encodeURIComponent(equipmentId)}/layout/published`,
      undefined,
      true,
    );
    if (!result.ok) return result;

    if (result.response.status === 404) {
      const detail = readErrorDetail(result.payload);
      if (detail?.code === "layout_not_published") {
        return { ok: true, value: null };
      }
      return requestFailed(
        equipmentId,
        detail?.message ?? "Опубліковану схему не знайдено.",
      );
    }

    return parseRevisionResult(equipmentId, result.payload);
  }

  async saveDraft(
    input: SaveLayoutDraftInput,
  ): Promise<RepositoryResult<RefrigerationLayoutDraft>> {
    const result = await this.send(
      input.equipmentId,
      `/api/v1/equipment/${encodeURIComponent(input.equipmentId)}/layout/draft`,
      {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          "If-Match": draftEtag(input.expectedVersion),
        },
        body: JSON.stringify({
          image_id: input.imageId,
          placements: input.placements.map((placement: LayoutPlacement) => ({
            sensor_id: placement.sensorId,
            x: placement.x,
            y: placement.y,
          })),
        }),
      },
    );
    if (!result.ok) return result;

    return parseDraftResult(input.equipmentId, result.response, result.payload);
  }

  async publishDraft(
    input: PublishLayoutDraftInput,
  ): Promise<
    RepositoryResult<{
      draft: RefrigerationLayoutDraft;
      published: PublishedLayoutRevision;
    }>
  > {
    const result = await this.send(
      input.equipmentId,
      `/api/v1/equipment/${encodeURIComponent(input.equipmentId)}/layout/publish`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "If-Match": draftEtag(input.expectedVersion),
        },
        body: JSON.stringify({
          actor_id: input.actorId?.trim() || "dashboard-operator",
        }),
      },
    );
    if (!result.ok) return result;

    const record = asRecord(result.payload);
    if (!record) {
      return invalidResponse(
        input.equipmentId,
        "Publish response must be an object.",
      );
    }

    const draft = parseDraftResult(
      input.equipmentId,
      result.response,
      record.draft,
    );
    if (!draft.ok) return draft;

    const published = parseRevisionResult(
      input.equipmentId,
      record.published,
    );
    if (!published.ok || published.value === null) {
      return invalidResponse(
        input.equipmentId,
        "Publish response has no published revision.",
      );
    }

    return {
      ok: true,
      value: { draft: draft.value, published: published.value },
    };
  }

  async listHistory(
    equipmentId: string,
  ): Promise<RepositoryResult<PublishedLayoutRevision[]>> {
    const result = await this.send(
      equipmentId,
      `/api/v1/equipment/${encodeURIComponent(equipmentId)}/layout/history`,
    );
    if (!result.ok) return result;

    const record = asRecord(result.payload);
    if (!record || !Array.isArray(record.items)) {
      return invalidResponse(
        equipmentId,
        "History response has no items array.",
      );
    }

    const items: PublishedLayoutRevision[] = [];
    for (const item of record.items) {
      const parsed = parseRevisionResult(equipmentId, item);
      if (!parsed.ok) return parsed;
      if (parsed.value === null) {
        return invalidResponse(
          equipmentId,
          "History response contains an empty revision.",
        );
      }
      items.push(parsed.value);
    }

    return {
      ok: true,
      value: items.sort(
        (first, second) => second.revision - first.revision,
      ),
    };
  }

  async restoreRevision(
    input: RestoreLayoutRevisionInput,
  ): Promise<RepositoryResult<RefrigerationLayoutDraft>> {
    const result = await this.send(
      input.equipmentId,
      `/api/v1/equipment/${encodeURIComponent(input.equipmentId)}/layout/history/${encodeURIComponent(input.revisionId)}/restore`,
      {
        method: "POST",
        headers: { "If-Match": draftEtag(input.expectedVersion) },
      },
    );
    if (!result.ok) return result;

    return parseDraftResult(input.equipmentId, result.response, result.payload);
  }

  async uploadImage(
    input: UploadEquipmentImageInput,
  ): Promise<RepositoryResult<EquipmentImageMetadata>> {
    const form = new FormData();
    form.append("file", input.file, input.file.name);

    const result = await this.send(
      input.equipmentId,
      `/api/v1/equipment/${encodeURIComponent(input.equipmentId)}/images`,
      {
        method: "POST",
        headers: { "X-Actor-Id": input.actorId },
        body: form,
      },
    );
    if (!result.ok) return result;

    const image = parseImage(result.payload, input.equipmentId);
    return image
      ? { ok: true, value: image }
      : invalidResponse(
          input.equipmentId,
          "Image upload response is invalid.",
        );
  }

  private async send(
    equipmentId: string,
    path: string,
    init?: RequestInit,
    allowNotFound = false,
  ): Promise<TransportResult> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);

    try {
      const response = await this.fetchImpl(`${this.apiBaseUrl}${path}`, {
        ...init,
        signal: controller.signal,
      });
      const payload = await readJson(response);

      if (!response.ok && !(allowNotFound && response.status === 404)) {
        return {
          ok: false,
          error: mapHttpError(equipmentId, payload, response.status),
        };
      }

      return { ok: true, response, payload };
    } catch (error) {
      const message =
        error instanceof DOMException && error.name === "AbortError"
          ? "Перевищено час очікування відповіді сервера схем."
          : "Не вдалося з’єднатися із сервером схем обладнання.";
      return {
        ok: false,
        error: {
          code: "LAYOUT_VALIDATION_FAILED",
          equipmentId,
          issues: [{ code: "REQUEST_FAILED", message }],
        },
      };
    } finally {
      clearTimeout(timeout);
    }
  }
}

function parseDraftResult(
  equipmentId: string,
  response: Response,
  payload: unknown,
): RepositoryResult<RefrigerationLayoutDraft> {
  const record = asRecord(payload);
  if (!record) {
    return invalidResponse(equipmentId, "Draft response must be an object.");
  }

  const id = readString(record.id);
  const responseEquipmentId = readString(record.equipment_id);
  const version = readPositiveInteger(record.version);
  const createdAt = readString(record.created_at);
  const updatedAt = readString(record.updated_at);
  const placements = parsePlacements(record.placements);
  const image =
    record.image === null ? null : parseImage(record.image, equipmentId);
  const etag = response.headers.get("ETag");

  if (
    !id ||
    responseEquipmentId !== equipmentId ||
    version === null ||
    !createdAt ||
    !updatedAt ||
    placements === null ||
    (record.image !== null && !image) ||
    etag !== draftEtag(version)
  ) {
    return invalidResponse(
      equipmentId,
      "Draft response or ETag does not match the API contract.",
    );
  }

  return {
    ok: true,
    value: {
      id,
      equipmentId,
      version,
      etag,
      imageId: image?.id ?? null,
      image,
      placements,
      createdAt,
      updatedAt,
    },
  };
}

function parseRevisionResult(
  equipmentId: string,
  payload: unknown,
): RepositoryResult<PublishedLayoutRevision | null> {
  const record = asRecord(payload);
  if (!record) {
    return invalidResponse(
      equipmentId,
      "Revision response must be an object.",
    );
  }

  const id = readString(record.id);
  const responseEquipmentId = readString(record.equipment_id);
  const revision = readPositiveInteger(record.revision);
  const sourceDraftVersion = readPositiveInteger(record.source_draft_version);
  const publishedBy = readString(record.published_by);
  const publishedAt = readString(record.published_at);
  const placements = parsePlacements(record.placements);
  const image = parseImage(record.image, equipmentId);

  if (
    !id ||
    responseEquipmentId !== equipmentId ||
    revision === null ||
    sourceDraftVersion === null ||
    !publishedBy ||
    !publishedAt ||
    placements === null ||
    !image
  ) {
    return invalidResponse(
      equipmentId,
      "Revision response does not match the API contract.",
    );
  }

  return {
    ok: true,
    value: {
      id,
      equipmentId,
      revision,
      sourceDraftVersion,
      imageId: image.id,
      image,
      placements,
      publishedBy,
      publishedAt,
    },
  };
}

function parseImage(
  payload: unknown,
  equipmentId: string,
): EquipmentImageMetadata | null {
  const record = asRecord(payload);
  if (!record) return null;

  const id = readString(record.id);
  const responseEquipmentId = readString(record.equipment_id);
  const fileName = readString(record.original_filename);
  const mimeType = readString(record.media_type);
  const widthPx = readPositiveInteger(record.width_px);
  const heightPx = readPositiveInteger(record.height_px);
  const sizeBytes = readNonNegativeInteger(record.size_bytes);
  const sourceUrl = readString(record.content_url);
  const createdAt = readString(record.created_at);

  if (
    !id ||
    responseEquipmentId !== equipmentId ||
    !fileName ||
    !isImageMimeType(mimeType) ||
    widthPx === null ||
    heightPx === null ||
    sizeBytes === null ||
    !sourceUrl ||
    !createdAt
  ) {
    return null;
  }

  return {
    id,
    fileName,
    mimeType,
    widthPx,
    heightPx,
    sizeBytes,
    sourceUrl,
    alt: `Фото обладнання ${equipmentId}`,
    updatedAt: createdAt,
  };
}

function parsePlacements(payload: unknown): LayoutPlacement[] | null {
  if (!Array.isArray(payload)) return null;

  const placements: LayoutPlacement[] = [];
  const sensorIds = new Set<string>();
  for (const item of payload) {
    const record = asRecord(item);
    const sensorId = record ? readString(record.sensor_id) : null;
    const x = record ? readNormalizedNumber(record.x) : null;
    const y = record ? readNormalizedNumber(record.y) : null;
    if (!sensorId || x === null || y === null || sensorIds.has(sensorId)) {
      return null;
    }
    sensorIds.add(sensorId);
    placements.push({ sensorId, x, y });
  }
  return placements;
}

function mapHttpError(
  equipmentId: string,
  payload: unknown,
  status: number,
): LayoutRepositoryError {
  const detail = readErrorDetail(payload);
  if (
    detail?.code === "layout_version_conflict" &&
    detail.expectedVersion !== null &&
    detail.actualVersion !== null
  ) {
    return {
      code: "LAYOUT_VERSION_CONFLICT",
      equipmentId,
      expectedVersion: detail.expectedVersion,
      actualVersion: detail.actualVersion,
    };
  }

  if (detail?.code === "layout_not_found") {
    return { code: "LAYOUT_NOT_FOUND", equipmentId };
  }

  if (detail?.code === "layout_revision_not_found") {
    return {
      code: "LAYOUT_REVISION_NOT_FOUND",
      equipmentId,
      revisionId: "unknown",
    };
  }

  return {
    code: "LAYOUT_VALIDATION_FAILED",
    equipmentId,
    issues: (
      detail?.issues?.length
        ? detail.issues
        : [
            detail?.message ??
              `Layout API request failed with HTTP ${status}.`,
          ]
    ).map((message) => ({
      code: status >= 500 ? "REQUEST_FAILED" : "SERVER_VALIDATION",
      message,
    })),
  };
}

function readErrorDetail(payload: unknown): {
  code: string | null;
  message: string | null;
  expectedVersion: number | null;
  actualVersion: number | null;
  issues: string[];
} | null {
  const root = asRecord(payload);
  const detail = root ? asRecord(root.detail) : null;
  if (!detail) return null;

  return {
    code: readString(detail.code),
    message: readString(detail.message),
    expectedVersion: readPositiveInteger(detail.expected_version),
    actualVersion: readPositiveInteger(detail.actual_version),
    issues: Array.isArray(detail.issues)
      ? detail.issues.filter(
          (issue): issue is string => typeof issue === "string",
        )
      : [],
  };
}

function invalidResponse<T>(
  equipmentId: string,
  message: string,
): RepositoryResult<T> {
  return requestFailed(equipmentId, message, "INVALID_RESPONSE");
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}

function normalizeBaseUrl(value: string): string {
  const parsed = new URL(value);
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("Refrigeration layout API URL must use HTTP or HTTPS.");
  }
  parsed.hash = "";
  parsed.search = "";
  return parsed.toString().replace(/\/$/, "");
}

function asRecord(value: unknown): JsonRecord | null {
  return value !== null &&
    typeof value === "object" &&
    !Array.isArray(value)
    ? (value as JsonRecord)
    : null;
}

function readString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function readPositiveInteger(value: unknown): number | null {
  return Number.isInteger(value) && Number(value) >= 1
    ? Number(value)
    : null;
}

function readNonNegativeInteger(value: unknown): number | null {
  return Number.isInteger(value) && Number(value) >= 0
    ? Number(value)
    : null;
}

function readNormalizedNumber(value: unknown): number | null {
  return typeof value === "number" &&
    Number.isFinite(value) &&
    value >= 0 &&
    value <= 1
    ? value
    : null;
}

function isImageMimeType(
  value: string | null,
): value is EquipmentImageMetadata["mimeType"] {
  return (
    value === "image/jpeg" || value === "image/png" || value === "image/webp"
  );
}
