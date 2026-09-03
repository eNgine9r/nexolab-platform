import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const MAX_REQUEST_BYTES = 20 * 1024;
const MAX_INIT_DATA_LENGTH = 16 * 1024;
const MAX_START_HINT_LENGTH = 128;
const GATEWAY_PATH = "/miniapp/report";
const ALLOWED_GATEWAY_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]", "telegram-gateway"]);

function gatewayBaseUrl(): URL {
  const value = process.env.NEXOLAB_TELEGRAM_GATEWAY_BASE_URL?.trim() || "http://127.0.0.1:8090";
  const url = new URL(value);
  const effectivePort = url.port || (url.protocol === "http:" ? "80" : "");
  if (
    url.protocol !== "http:" ||
    !ALLOWED_GATEWAY_HOSTS.has(url.hostname) ||
    effectivePort !== "8090" ||
    url.username ||
    url.password ||
    (url.pathname !== "/" && url.pathname !== "") ||
    url.search ||
    url.hash
  ) {
    throw new Error("Telegram Gateway endpoint must be an exact trusted HTTP endpoint on port 8090");
  }
  url.pathname = "/";
  return url;
}

function errorResponse(status: number, code: string, message: string): NextResponse {
  return NextResponse.json(
    { detail: { code, message } },
    { status, headers: { "Cache-Control": "no-store" } },
  );
}

function parseRequestBody(raw: string): { init_data: string; start_hint?: string } | null {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  const allowedKeys = new Set(["init_data", "start_hint"]);
  if (Object.keys(record).some((key) => !allowedKeys.has(key))) return null;
  if (
    typeof record.init_data !== "string" ||
    record.init_data.length === 0 ||
    record.init_data.length > MAX_INIT_DATA_LENGTH
  ) {
    return null;
  }
  if (
    record.start_hint !== undefined &&
    (typeof record.start_hint !== "string" || record.start_hint.length > MAX_START_HINT_LENGTH)
  ) {
    return null;
  }
  return record.start_hint === undefined
    ? { init_data: record.init_data }
    : { init_data: record.init_data, start_hint: record.start_hint as string };
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const contentLength = Number(request.headers.get("content-length") || "0");
  if (Number.isFinite(contentLength) && contentLength > MAX_REQUEST_BYTES) {
    return errorResponse(413, "miniapp_request_too_large", "Запит Telegram Mini App завеликий.");
  }

  let body: string;
  try {
    body = await request.text();
  } catch {
    return errorResponse(400, "miniapp_request_invalid", "Не вдалося прочитати запит Mini App.");
  }
  if (!body || Buffer.byteLength(body, "utf8") > MAX_REQUEST_BYTES) {
    return errorResponse(413, "miniapp_request_too_large", "Запит Telegram Mini App завеликий.");
  }
  const parsed = parseRequestBody(body);
  if (!parsed) {
    return errorResponse(400, "miniapp_request_invalid", "Некоректний запит Telegram Mini App.");
  }

  let target: URL;
  try {
    target = new URL(GATEWAY_PATH, gatewayBaseUrl());
  } catch {
    return errorResponse(503, "miniapp_gateway_configuration_invalid", "Mini App тимчасово недоступний.");
  }
  try {
    const response = await fetch(target, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(parsed),
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    const text = await response.text();
    const headers = new Headers({ "Cache-Control": "no-store" });
    const contentType = response.headers.get("content-type");
    if (contentType) headers.set("Content-Type", contentType);
    return new NextResponse(text || null, { status: response.status, headers });
  } catch {
    return errorResponse(503, "miniapp_gateway_unavailable", "Mini App тимчасово недоступний.");
  }
}
