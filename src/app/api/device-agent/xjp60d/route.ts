import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const READ_PERMISSIONS = ["dashboard.read", "equipment.manage"] as const;
const MANAGE_PERMISSION = "equipment.manage";
const AGENT_CONFIGURATION_PATH = "/api/v1/xjp60d/configuration";
const AGENT_DISCOVERY_PATH = "/api/v1/xjp60d/discovery";

type SessionMembership = {
  organization_id?: unknown;
  permissions?: unknown;
};

type SessionPayload = {
  memberships?: unknown;
};

function apiBaseUrl(): URL {
  const value = process.env.NEXT_PUBLIC_NEXOLAB_API_BASE_URL?.trim();
  if (!value) throw new Error("NEXOLAB API base URL is not configured");
  return new URL(value);
}

function agentBaseUrl(): URL {
  const value = process.env.NEXOLAB_DEVICE_AGENT_BASE_URL?.trim() || "http://127.0.0.1:8081";
  const url = new URL(value);
  if (url.protocol !== "http:" || !["127.0.0.1", "localhost", "::1"].includes(url.hostname)) {
    throw new Error("Device Agent control endpoint must use loopback HTTP");
  }
  url.pathname = "/";
  url.search = "";
  url.hash = "";
  return url;
}

function forwardedHeaders(request: NextRequest): Headers {
  const headers = new Headers({ Accept: "application/json" });
  for (const name of ["authorization", "x-organization-id", "cookie", "user-agent"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  return headers;
}

async function authorize(
  request: NextRequest,
  requiredPermissions: readonly string[],
): Promise<NextResponse | null> {
  let response: Response;
  try {
    response = await fetch(new URL("/api/v1/auth/session", apiBaseUrl()), {
      method: "GET",
      headers: forwardedHeaders(request),
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
  } catch {
    return NextResponse.json(
      { detail: { code: "security_session_unavailable", message: "Не вдалося перевірити права доступу." } },
      { status: 503 },
    );
  }

  if (!response.ok) {
    return NextResponse.json(
      {
        detail: {
          code: response.status === 401 ? "authentication_required" : "access_denied",
          message:
            response.status === 401
              ? "Потрібна автентифікація оператора."
              : "Недостатньо прав для керування датчиками.",
        },
      },
      { status: response.status === 401 ? 401 : 403 },
    );
  }

  const payload = (await response.json()) as SessionPayload;
  const memberships = Array.isArray(payload.memberships) ? (payload.memberships as SessionMembership[]) : [];
  const requestedOrganization = request.headers.get("x-organization-id")?.trim() || null;
  const membership = requestedOrganization
    ? memberships.find((item) => item.organization_id === requestedOrganization)
    : memberships[0];
  const grantedPermissions =
    membership && Array.isArray(membership.permissions) ? membership.permissions : [];
  if (!membership || !requiredPermissions.some((permission) => grantedPermissions.includes(permission))) {
    return NextResponse.json(
      { detail: { code: "access_denied", message: "Недостатньо прав для керування датчиками." } },
      { status: 403 },
    );
  }
  return null;
}

async function relayAgent(
  request: NextRequest,
  path: string,
  options: { method: "GET" | "POST" | "PUT"; timeoutMs: number; body?: string },
): Promise<NextResponse> {
  let response: Response;
  try {
    response = await fetch(new URL(path, agentBaseUrl()), {
      method: options.method,
      headers: options.body
        ? { Accept: "application/json", "Content-Type": "application/json" }
        : { Accept: "application/json" },
      body: options.body,
      cache: "no-store",
      signal: AbortSignal.timeout(options.timeoutMs),
    });
  } catch {
    return NextResponse.json(
      {
        detail: {
          code: "device_agent_unavailable",
          message: "Локальний Device Agent недоступний або не завершив операцію вчасно.",
        },
      },
      { status: 503 },
    );
  }

  const text = await response.text();
  const headers = new Headers({ "Cache-Control": "no-store" });
  const contentType = response.headers.get("content-type");
  if (contentType) headers.set("Content-Type", contentType);
  return new NextResponse(text || null, { status: response.status, headers });
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  const denied = await authorize(request, READ_PERMISSIONS);
  if (denied) return denied;
  return relayAgent(request, AGENT_CONFIGURATION_PATH, { method: "GET", timeoutMs: 10_000 });
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const denied = await authorize(request, [MANAGE_PERMISSION]);
  if (denied) return denied;
  return relayAgent(request, AGENT_DISCOVERY_PATH, { method: "POST", timeoutMs: 180_000 });
}

export async function PUT(request: NextRequest): Promise<NextResponse> {
  const denied = await authorize(request, [MANAGE_PERMISSION]);
  if (denied) return denied;
  const body = await request.text();
  if (!body || body.length > 32 * 1024) {
    return NextResponse.json(
      { detail: { code: "invalid_request", message: "Некоректний розмір конфігурації датчиків." } },
      { status: 422 },
    );
  }
  return relayAgent(request, AGENT_CONFIGURATION_PATH, {
    method: "PUT",
    timeoutMs: 10_000,
    body,
  });
}
