import { refrigerationEquipment } from "@/data/refrigeration";
import {
  createAuthenticatedFetch,
  HttpSecuritySessionClient,
  type SecurityCredentialProvider,
} from "@/features/security/security-session";
import { createRuntimeCredentialProvider } from "@/features/security/supabase-auth";
import { getTelemetryRuntimeConfig } from "@/lib/telemetry/runtime-config";

import { HttpClimateCatalogRepository, type ClimateCatalogRepository } from "./climate-catalog-repository";
import {
  HttpEquipmentLifecycleRepository,
  type EquipmentLifecycleRepository,
} from "./equipment-lifecycle-repository";
import {
  HttpRefrigerationEquipmentRepository,
  InMemoryRefrigerationEquipmentRepository,
  type RefrigerationEquipmentRepository,
} from "./equipment-repository";
import { createCachedEquipmentLifecycleRepository } from "./refrigeration-structural-cache";

export type RefrigerationEquipmentRuntime = {
  mode: "demo" | "live";
  /** @deprecated Use equipmentRepository in new code. */
  repository: RefrigerationEquipmentRepository | null;
  equipmentRepository: RefrigerationEquipmentRepository | null;
  lifecycleRepository: EquipmentLifecycleRepository | null;
  /**
   * Explicit alias used by the atomic sensor configuration workspace. The
   * lifecycle repository owns the compatible binding/channel operations.
   */
  sensorConfigurationRepository: EquipmentLifecycleRepository | null;
  climateCatalogRepository?: ClimateCatalogRepository | null;
  sessionClient: HttpSecuritySessionClient | null;
  organizationId: string | null;
  error: string | null;
};

export type RefrigerationEquipmentRuntimeInput = {
  fetchImpl?: typeof fetch;
  credentialProvider?: SecurityCredentialProvider;
  organizationId?: string;
  mode?: string;
  apiBaseUrl?: string;
};

const demoRepository = new InMemoryRefrigerationEquipmentRepository(refrigerationEquipment);

export function createRefrigerationEquipmentRuntime(
  input: RefrigerationEquipmentRuntimeInput = {},
): RefrigerationEquipmentRuntime {
  try {
    const config = getRuntimeConfig(input);
    if (config.mode === "demo") {
      return {
        mode: "demo",
        repository: demoRepository,
        equipmentRepository: demoRepository,
        lifecycleRepository: null,
        sensorConfigurationRepository: null,
        climateCatalogRepository: null,
        sessionClient: null,
        organizationId: null,
        error: null,
      };
    }

    const organizationId = normalizeOrganizationId(
      input.organizationId ?? process.env.NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID,
    );
    const browserFetch = input.fetchImpl ?? fetch.bind(globalThis);
    const credentialProvider = input.credentialProvider ?? createRuntimeCredentialProvider(organizationId);
    const authenticatedFetch = createAuthenticatedFetch(browserFetch, credentialProvider);
    const equipmentRepository = new HttpRefrigerationEquipmentRepository({
      apiBaseUrl: config.apiBaseUrl,
      fetchImpl: authenticatedFetch,
    });
    const lifecycleRepository = createCachedEquipmentLifecycleRepository(
      new HttpEquipmentLifecycleRepository({
        apiBaseUrl: config.apiBaseUrl,
        fetchImpl: authenticatedFetch,
      }),
      `${config.apiBaseUrl}|${organizationId ?? "default"}`,
    );
    return {
      mode: "live",
      repository: equipmentRepository,
      equipmentRepository,
      lifecycleRepository,
      sensorConfigurationRepository: lifecycleRepository,
      climateCatalogRepository: new HttpClimateCatalogRepository({
        apiBaseUrl: config.apiBaseUrl,
        fetchImpl: authenticatedFetch,
      }),
      sessionClient: new HttpSecuritySessionClient({
        apiBaseUrl: config.apiBaseUrl,
        fetchImpl: authenticatedFetch,
      }),
      organizationId,
      error: null,
    };
  } catch (error) {
    return {
      mode: input.mode === "live" ? "live" : "demo",
      repository: null,
      equipmentRepository: null,
      lifecycleRepository: null,
      sensorConfigurationRepository: null,
      climateCatalogRepository: null,
      sessionClient: null,
      organizationId: null,
      error: error instanceof Error ? error.message : "Не вдалося налаштувати каталог обладнання.",
    };
  }
}

function getRuntimeConfig(
  input: RefrigerationEquipmentRuntimeInput,
): { mode: "demo"; apiBaseUrl: null } | { mode: "live"; apiBaseUrl: string } {
  if (input.mode !== undefined || input.apiBaseUrl !== undefined) {
    const mode = input.mode?.trim() || "demo";
    if (mode === "demo") return { mode: "demo", apiBaseUrl: null };
    if (mode !== "live") {
      throw new Error(`Unsupported refrigeration equipment mode: ${mode}`);
    }
    const apiBaseUrl = input.apiBaseUrl?.trim();
    if (!apiBaseUrl) {
      throw new Error("NEXOLAB API URL is required for live refrigeration equipment.");
    }
    return { mode: "live", apiBaseUrl };
  }

  const config = getTelemetryRuntimeConfig();
  if (config.mode === "live") {
    if (!config.apiBaseUrl) {
      throw new Error("NEXOLAB API URL is required for live refrigeration equipment.");
    }
    return { mode: "live", apiBaseUrl: config.apiBaseUrl };
  }
  return { mode: "demo", apiBaseUrl: null };
}

function normalizeOrganizationId(value: string | undefined): string | null {
  const normalized = value?.trim();
  return normalized ? normalized.slice(0, 128) : null;
}
