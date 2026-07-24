import { describe, expect, it, vi } from "vitest";

import { HttpRefrigerationLayoutRepository } from "./http-layout-repository";

const equipmentId = "showcase-106-01";

const imagePayload = {
  id: "image-1",
  equipment_id: equipmentId,
  original_filename: "showcase.webp",
  media_type: "image/webp",
  size_bytes: 1024,
  width_px: 1200,
  height_px: 800,
  checksum_sha256: "a".repeat(64),
  object_etag: '"etag"',
  created_by: "operator-1",
  created_at: "2026-07-25T10:00:00Z",
  content_url: "http://storage.local/equipment-images/image-1.webp?signature=1",
};

function draftPayload(version: number) {
  return {
    id: "draft-1",
    equipment_id: equipmentId,
    version,
    image: imagePayload,
    placements: [
      { sensor_id: "sensor-1", x: 0.25, y: 0.35 },
      { sensor_id: "sensor-2", x: 0.75, y: 0.65 },
    ],
    created_at: "2026-07-25T09:00:00Z",
    updated_at: "2026-07-25T10:00:00Z",
  };
}

function revisionPayload(revision: number) {
  return {
    id: `revision-${revision}`,
    equipment_id: equipmentId,
    revision,
    source_draft_version: revision,
    image: imagePayload,
    placements: draftPayload(1).placements,
    published_by: "operator-1",
    published_at: `2026-07-25T1${revision}:00:00Z`,
  };
}

function jsonResponse(
  payload: unknown,
  init: ResponseInit = {},
): Response {
  return new Response(JSON.stringify(payload), {
    status: init.status ?? 200,
    headers: {
      "Content-Type": "application/json",
      ...Object.fromEntries(new Headers(init.headers).entries()),
    },
  });
}

describe("HttpRefrigerationLayoutRepository", () => {
  it("loads a draft and validates the backend ETag", async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse(draftPayload(3), {
        headers: { ETag: 'W/"layout-draft-v3"' },
      }),
    );
    const repository = new HttpRefrigerationLayoutRepository({
      apiBaseUrl: "http://127.0.0.1:8082/",
      fetchImpl,
    });

    const result = await repository.getDraft(equipmentId);

    expect(result).toMatchObject({
      ok: true,
      value: {
        equipmentId,
        version: 3,
        etag: 'W/"layout-draft-v3"',
        imageId: "image-1",
        placements: [
          { sensorId: "sensor-1", x: 0.25, y: 0.35 },
          { sensorId: "sensor-2", x: 0.75, y: 0.65 },
        ],
      },
    });
    expect(fetchImpl).toHaveBeenCalledWith(
      `http://127.0.0.1:8082/api/v1/equipment/${equipmentId}/layout/draft`,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("sends If-Match and maps draft coordinates to the backend contract", async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse(draftPayload(4), {
        headers: { ETag: 'W/"layout-draft-v4"' },
      }),
    );
    const repository = new HttpRefrigerationLayoutRepository({
      apiBaseUrl: "http://api.local",
      fetchImpl,
    });

    const result = await repository.saveDraft({
      equipmentId,
      expectedVersion: 3,
      imageId: "image-1",
      placements: [{ sensorId: "sensor-1", x: 0.4, y: 0.5 }],
    });

    expect(result).toMatchObject({ ok: true, value: { version: 4 } });
    const [, init] = fetchImpl.mock.calls[0] ?? [];
    expect(init).toMatchObject({
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "If-Match": 'W/"layout-draft-v3"',
      },
    });
    expect(JSON.parse(String(init?.body))).toEqual({
      image_id: "image-1",
      placements: [{ sensor_id: "sensor-1", x: 0.4, y: 0.5 }],
    });
  });

  it("maps a stale write into the typed conflict without retrying", async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse(
        {
          detail: {
            code: "layout_version_conflict",
            message: "stale draft",
            expected_version: 2,
            actual_version: 5,
          },
        },
        { status: 409 },
      ),
    );
    const repository = new HttpRefrigerationLayoutRepository({
      apiBaseUrl: "http://api.local",
      fetchImpl,
    });

    const result = await repository.saveDraft({
      equipmentId,
      expectedVersion: 2,
      imageId: null,
      placements: [],
    });

    expect(result).toEqual({
      ok: false,
      error: {
        code: "LAYOUT_VERSION_CONFLICT",
        equipmentId,
        expectedVersion: 2,
        actualVersion: 5,
      },
    });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("publishes with actor identity and returns the advanced draft plus revision", async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse(
        {
          draft: draftPayload(4),
          published: revisionPayload(2),
        },
        { status: 201, headers: { ETag: 'W/"layout-draft-v4"' } },
      ),
    );
    const repository = new HttpRefrigerationLayoutRepository({
      apiBaseUrl: "http://api.local",
      fetchImpl,
    });

    const result = await repository.publishDraft({
      equipmentId,
      expectedVersion: 3,
      actorId: "operator-1",
    });

    expect(result).toMatchObject({
      ok: true,
      value: {
        draft: { version: 4 },
        published: { revision: 2, publishedBy: "operator-1" },
      },
    });
    const [, init] = fetchImpl.mock.calls[0] ?? [];
    expect(init).toMatchObject({
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "If-Match": 'W/"layout-draft-v3"',
      },
    });
    expect(JSON.parse(String(init?.body))).toEqual({ actor_id: "operator-1" });
  });

  it("returns null when no published revision exists", async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse(
        {
          detail: {
            code: "layout_not_published",
            message: "layout has no published revision",
          },
        },
        { status: 404 },
      ),
    );
    const repository = new HttpRefrigerationLayoutRepository({
      apiBaseUrl: "http://api.local",
      fetchImpl,
    });

    await expect(repository.getPublished(equipmentId)).resolves.toEqual({
      ok: true,
      value: null,
    });
  });

  it("sorts immutable history newest first and restores with If-Match", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ items: [revisionPayload(1), revisionPayload(3)] }),
      )
      .mockResolvedValueOnce(
        jsonResponse(draftPayload(7), {
          headers: { ETag: 'W/"layout-draft-v7"' },
        }),
      );
    const repository = new HttpRefrigerationLayoutRepository({
      apiBaseUrl: "http://api.local",
      fetchImpl,
    });

    const history = await repository.listHistory(equipmentId);
    expect(history).toMatchObject({
      ok: true,
      value: [{ revision: 3 }, { revision: 1 }],
    });

    const restored = await repository.restoreRevision({
      equipmentId,
      revisionId: "revision-1",
      expectedVersion: 6,
    });
    expect(restored).toMatchObject({ ok: true, value: { version: 7 } });
    const [, init] = fetchImpl.mock.calls[1] ?? [];
    expect(init).toMatchObject({
      method: "POST",
      headers: { "If-Match": 'W/"layout-draft-v6"' },
    });
  });

  it("uploads equipment photos as multipart with the operator header", async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(imagePayload, { status: 201 }));
    const repository = new HttpRefrigerationLayoutRepository({
      apiBaseUrl: "http://api.local",
      fetchImpl,
    });
    const file = new File(["image-bytes"], "showcase.webp", {
      type: "image/webp",
    });

    const result = await repository.uploadImage({
      equipmentId,
      file,
      actorId: "operator-1",
    });

    expect(result).toMatchObject({
      ok: true,
      value: {
        id: "image-1",
        fileName: "showcase.webp",
        sourceUrl: expect.stringContaining("storage.local"),
      },
    });
    const [, init] = fetchImpl.mock.calls[0] ?? [];
    expect(init).toMatchObject({
      method: "POST",
      headers: { "X-Actor-Id": "operator-1" },
      body: expect.any(FormData),
    });
    expect((init?.body as FormData).get("file")).toBe(file);
  });

  it("rejects a malformed draft response instead of accepting partial data", async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse(
        { ...draftPayload(2), placements: [{ sensor_id: "sensor-1", x: 2, y: 0.4 }] },
        { headers: { ETag: 'W/"layout-draft-v2"' } },
      ),
    );
    const repository = new HttpRefrigerationLayoutRepository({
      apiBaseUrl: "http://api.local",
      fetchImpl,
    });

    const result = await repository.getDraft(equipmentId);

    expect(result).toMatchObject({
      ok: false,
      error: {
        code: "LAYOUT_VALIDATION_FAILED",
        issues: [{ code: "INVALID_RESPONSE" }],
      },
    });
  });
});
