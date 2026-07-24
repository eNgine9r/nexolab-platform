import type { LayoutPlacement } from "./layout-editor";

export type RefrigerationLayoutDraft = {
  id: string;
  equipmentId: string;
  version: number;
  imageId: string | null;
  placements: LayoutPlacement[];
  createdAt: string;
  updatedAt: string;
};

export type PublishedLayoutRevision = {
  id: string;
  equipmentId: string;
  revision: number;
  sourceDraftVersion: number;
  imageId: string;
  placements: LayoutPlacement[];
  publishedAt: string;
};

export type LayoutValidationIssue = {
  code:
    | "IMAGE_REQUIRED"
    | "PLACEMENTS_REQUIRED"
    | "DUPLICATE_SENSOR"
    | "INVALID_SENSOR_ID"
    | "INVALID_COORDINATE";
  message: string;
  sensorId?: string;
};

export type LayoutRepositoryError =
  | {
      code: "LAYOUT_NOT_FOUND";
      equipmentId: string;
    }
  | {
      code: "LAYOUT_VERSION_CONFLICT";
      equipmentId: string;
      expectedVersion: number;
      actualVersion: number;
    }
  | {
      code: "LAYOUT_VALIDATION_FAILED";
      equipmentId: string;
      issues: LayoutValidationIssue[];
    }
  | {
      code: "LAYOUT_REVISION_NOT_FOUND";
      equipmentId: string;
      revisionId: string;
    };

export type RepositoryResult<T> =
  | { ok: true; value: T }
  | { ok: false; error: LayoutRepositoryError };

export type SaveLayoutDraftInput = {
  equipmentId: string;
  expectedVersion: number;
  imageId: string | null;
  placements: readonly LayoutPlacement[];
};

export type PublishLayoutDraftInput = {
  equipmentId: string;
  expectedVersion: number;
};

export type RestoreLayoutRevisionInput = {
  equipmentId: string;
  revisionId: string;
  expectedVersion: number;
};

export interface RefrigerationLayoutRepository {
  getDraft(equipmentId: string): Promise<RepositoryResult<RefrigerationLayoutDraft>>;
  getPublished(equipmentId: string): Promise<RepositoryResult<PublishedLayoutRevision | null>>;
  saveDraft(input: SaveLayoutDraftInput): Promise<RepositoryResult<RefrigerationLayoutDraft>>;
  publishDraft(
    input: PublishLayoutDraftInput,
  ): Promise<RepositoryResult<{ draft: RefrigerationLayoutDraft; published: PublishedLayoutRevision }>>;
  listHistory(equipmentId: string): Promise<RepositoryResult<PublishedLayoutRevision[]>>;
  restoreRevision(input: RestoreLayoutRevisionInput): Promise<RepositoryResult<RefrigerationLayoutDraft>>;
}

type LayoutAggregate = {
  draft: RefrigerationLayoutDraft;
  activePublishedRevisionId: string | null;
  revisions: PublishedLayoutRevision[];
};

type InMemoryRepositoryOptions = {
  drafts?: readonly RefrigerationLayoutDraft[];
  now?: () => string;
  createId?: () => string;
};

export class InMemoryRefrigerationLayoutRepository implements RefrigerationLayoutRepository {
  private readonly aggregates = new Map<string, LayoutAggregate>();
  private readonly now: () => string;
  private readonly createId: () => string;

  constructor(options: InMemoryRepositoryOptions = {}) {
    this.now = options.now ?? (() => new Date().toISOString());
    this.createId = options.createId ?? (() => crypto.randomUUID());

    for (const draft of options.drafts ?? []) {
      this.aggregates.set(draft.equipmentId, {
        draft: cloneDraft(draft),
        activePublishedRevisionId: null,
        revisions: [],
      });
    }
  }

  async getDraft(equipmentId: string): Promise<RepositoryResult<RefrigerationLayoutDraft>> {
    const aggregate = this.aggregates.get(equipmentId);

    if (!aggregate) {
      return notFound(equipmentId);
    }

    return success(cloneDraft(aggregate.draft));
  }

  async getPublished(
    equipmentId: string,
  ): Promise<RepositoryResult<PublishedLayoutRevision | null>> {
    const aggregate = this.aggregates.get(equipmentId);

    if (!aggregate) {
      return notFound(equipmentId);
    }

    const published = aggregate.activePublishedRevisionId
      ? aggregate.revisions.find(
          (revision) => revision.id === aggregate.activePublishedRevisionId,
        ) ?? null
      : null;

    return success(published ? cloneRevision(published) : null);
  }

  async saveDraft(
    input: SaveLayoutDraftInput,
  ): Promise<RepositoryResult<RefrigerationLayoutDraft>> {
    const aggregate = this.aggregates.get(input.equipmentId);

    if (!aggregate) {
      return notFound(input.equipmentId);
    }

    const conflict = checkVersion(
      aggregate.draft,
      input.equipmentId,
      input.expectedVersion,
    );
    if (conflict) return conflict;

    const issues = validatePlacements(input.placements, false, input.imageId);
    if (issues.length > 0) {
      return validationFailed(input.equipmentId, issues);
    }

    const updatedAt = this.now();
    aggregate.draft = {
      ...aggregate.draft,
      version: aggregate.draft.version + 1,
      imageId: input.imageId,
      placements: clonePlacements(input.placements),
      updatedAt,
    };

    return success(cloneDraft(aggregate.draft));
  }

  async publishDraft(
    input: PublishLayoutDraftInput,
  ): Promise<
    RepositoryResult<{
      draft: RefrigerationLayoutDraft;
      published: PublishedLayoutRevision;
    }>
  > {
    const aggregate = this.aggregates.get(input.equipmentId);

    if (!aggregate) {
      return notFound(input.equipmentId);
    }

    const conflict = checkVersion(
      aggregate.draft,
      input.equipmentId,
      input.expectedVersion,
    );
    if (conflict) return conflict;

    const issues = validatePlacements(
      aggregate.draft.placements,
      true,
      aggregate.draft.imageId,
    );
    if (issues.length > 0) {
      return validationFailed(input.equipmentId, issues);
    }

    const publishedAt = this.now();
    const published: PublishedLayoutRevision = {
      id: this.createId(),
      equipmentId: input.equipmentId,
      revision: (aggregate.revisions.at(-1)?.revision ?? 0) + 1,
      sourceDraftVersion: aggregate.draft.version,
      imageId: aggregate.draft.imageId as string,
      placements: clonePlacements(aggregate.draft.placements),
      publishedAt,
    };

    aggregate.revisions.push(published);
    aggregate.activePublishedRevisionId = published.id;
    aggregate.draft = {
      ...aggregate.draft,
      version: aggregate.draft.version + 1,
      updatedAt: publishedAt,
    };

    return success({
      draft: cloneDraft(aggregate.draft),
      published: cloneRevision(published),
    });
  }

  async listHistory(
    equipmentId: string,
  ): Promise<RepositoryResult<PublishedLayoutRevision[]>> {
    const aggregate = this.aggregates.get(equipmentId);

    if (!aggregate) {
      return notFound(equipmentId);
    }

    return success(
      aggregate.revisions
        .map(cloneRevision)
        .sort((first, second) => second.revision - first.revision),
    );
  }

  async restoreRevision(
    input: RestoreLayoutRevisionInput,
  ): Promise<RepositoryResult<RefrigerationLayoutDraft>> {
    const aggregate = this.aggregates.get(input.equipmentId);

    if (!aggregate) {
      return notFound(input.equipmentId);
    }

    const conflict = checkVersion(
      aggregate.draft,
      input.equipmentId,
      input.expectedVersion,
    );
    if (conflict) return conflict;

    const revision = aggregate.revisions.find(
      (candidate) => candidate.id === input.revisionId,
    );

    if (!revision) {
      return {
        ok: false,
        error: {
          code: "LAYOUT_REVISION_NOT_FOUND",
          equipmentId: input.equipmentId,
          revisionId: input.revisionId,
        },
      };
    }

    aggregate.draft = {
      ...aggregate.draft,
      version: aggregate.draft.version + 1,
      imageId: revision.imageId,
      placements: clonePlacements(revision.placements),
      updatedAt: this.now(),
    };

    return success(cloneDraft(aggregate.draft));
  }
}

export function validatePlacements(
  placements: readonly LayoutPlacement[],
  requireImage: boolean,
  imageId: string | null,
): LayoutValidationIssue[] {
  const issues: LayoutValidationIssue[] = [];

  if (requireImage && !imageId?.trim()) {
    issues.push({
      code: "IMAGE_REQUIRED",
      message: "A published layout must reference an equipment image.",
    });
  }

  if (placements.length === 0) {
    issues.push({
      code: "PLACEMENTS_REQUIRED",
      message: "A layout must contain at least one sensor placement.",
    });
  }

  const seenSensorIds = new Set<string>();

  for (const placement of placements) {
    const sensorId = placement.sensorId.trim();

    if (!sensorId) {
      issues.push({
        code: "INVALID_SENSOR_ID",
        message: "Every placement must reference a sensor.",
      });
      continue;
    }

    if (seenSensorIds.has(sensorId)) {
      issues.push({
        code: "DUPLICATE_SENSOR",
        message: `Sensor ${sensorId} is placed more than once.`,
        sensorId,
      });
    }
    seenSensorIds.add(sensorId);

    if (!isNormalizedCoordinate(placement.x) || !isNormalizedCoordinate(placement.y)) {
      issues.push({
        code: "INVALID_COORDINATE",
        message: `Sensor ${sensorId} has coordinates outside the normalized range.`,
        sensorId,
      });
    }
  }

  return issues;
}

export function createLayoutDraft(input: {
  id: string;
  equipmentId: string;
  imageId?: string | null;
  placements: readonly LayoutPlacement[];
  createdAt: string;
}): RefrigerationLayoutDraft {
  return {
    id: input.id,
    equipmentId: input.equipmentId,
    version: 1,
    imageId: input.imageId ?? null,
    placements: clonePlacements(input.placements),
    createdAt: input.createdAt,
    updatedAt: input.createdAt,
  };
}

function isNormalizedCoordinate(value: number): boolean {
  return Number.isFinite(value) && value >= 0 && value <= 1;
}

function checkVersion(
  draft: RefrigerationLayoutDraft,
  equipmentId: string,
  expectedVersion: number,
): RepositoryResult<never> | null {
  if (draft.version === expectedVersion) return null;

  return {
    ok: false,
    error: {
      code: "LAYOUT_VERSION_CONFLICT",
      equipmentId,
      expectedVersion,
      actualVersion: draft.version,
    },
  };
}

function notFound<T>(equipmentId: string): RepositoryResult<T> {
  return {
    ok: false,
    error: { code: "LAYOUT_NOT_FOUND", equipmentId },
  };
}

function validationFailed<T>(
  equipmentId: string,
  issues: LayoutValidationIssue[],
): RepositoryResult<T> {
  return {
    ok: false,
    error: {
      code: "LAYOUT_VALIDATION_FAILED",
      equipmentId,
      issues,
    },
  };
}

function success<T>(value: T): RepositoryResult<T> {
  return { ok: true, value };
}

function cloneDraft(draft: RefrigerationLayoutDraft): RefrigerationLayoutDraft {
  return {
    ...draft,
    placements: clonePlacements(draft.placements),
  };
}

function cloneRevision(revision: PublishedLayoutRevision): PublishedLayoutRevision {
  return {
    ...revision,
    placements: clonePlacements(revision.placements),
  };
}

function clonePlacements(placements: readonly LayoutPlacement[]): LayoutPlacement[] {
  return placements.map((placement) => ({ ...placement }));
}
