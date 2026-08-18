import { createHash, timingSafeEqual } from "node:crypto";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

import { toNodeHandler } from "@modelcontextprotocol/node";
import { createMcpHandler } from "@modelcontextprotocol/server";

import { NexoLabBackend } from "./backend.js";
import { loadConfig } from "./config.js";
import { buildMcpServer } from "./server.js";

const config = loadConfig();
const backend = new NexoLabBackend(config);
const mcpHandler = createMcpHandler(() => buildMcpServer(backend, config));
const nodeMcpHandler = toNodeHandler(mcpHandler, {
  onerror: (error) => log("error", "mcp_transport_error", { message: safeError(error) }),
});

function log(level: "info" | "warn" | "error", event: string, fields: Record<string, unknown> = {}): void {
  const line = JSON.stringify({
    ts: new Date().toISOString(),
    level,
    service: "nexolab-mcp",
    event,
    ...fields,
  });
  (level === "error" ? console.error : level === "warn" ? console.warn : console.info)(line);
}

function safeError(error: unknown): string {
  return error instanceof Error ? error.message : "Unknown error";
}

function writeJson(res: ServerResponse, status: number, body: Record<string, unknown>): void {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.end(JSON.stringify(body));
}

function requestPath(req: IncomingMessage): string {
  try {
    return new URL(req.url ?? "/", "http://localhost").pathname;
  } catch {
    return "/";
  }
}

function parseHost(raw: string | undefined): string | null {
  if (!raw || /[@\s/\\]/.test(raw)) return null;
  const value = raw.toLowerCase();
  if (value.startsWith("[")) {
    const closing = value.indexOf("]");
    if (closing <= 1) return null;
    const suffix = value.slice(closing + 1);
    if (suffix && !/^:\d{1,5}$/.test(suffix)) return null;
    return value.slice(1, closing);
  }
  const parts = value.split(":");
  if (parts.length > 2 || (parts[1] && !/^\d{1,5}$/.test(parts[1]))) return null;
  return parts[0] || null;
}

function hostAllowed(req: IncomingMessage): boolean {
  const host = parseHost(req.headers.host);
  return host !== null && config.allowedHosts.includes(host);
}

function originAllowed(req: IncomingMessage): boolean {
  const raw = req.headers.origin;
  if (!raw) return true;
  try {
    const origin = new URL(raw);
    if (origin.username || origin.password) return false;
    const hostname = origin.hostname.toLowerCase();
    const allowed = config.allowedOrigins.length > 0 ? config.allowedOrigins : config.allowedHosts;
    return allowed.includes(hostname);
  } catch {
    return false;
  }
}

function constantTimeEqual(left: string, right: string): boolean {
  const leftDigest = createHash("sha256").update(left).digest();
  const rightDigest = createHash("sha256").update(right).digest();
  return timingSafeEqual(leftDigest, rightDigest);
}

function bearerAllowed(req: IncomingMessage): boolean {
  if (!config.mcpBearerToken) return true;
  const header = req.headers.authorization;
  if (!header?.startsWith("Bearer ")) return false;
  const supplied = header.slice("Bearer ".length).trim();
  return supplied.length > 0 && constantTimeEqual(supplied, config.mcpBearerToken);
}

const httpServer = createServer((req, res) => {
  const path = requestPath(req);

  if (path === "/healthz" && req.method === "GET") {
    writeJson(res, 200, { status: "ok", service: "nexolab-mcp", version: "0.1.0" });
    return;
  }

  if (path !== "/mcp") {
    writeJson(res, 404, { error: "not_found" });
    return;
  }

  if (!hostAllowed(req)) {
    log("warn", "request_rejected", { reason: "host", remote: req.socket.remoteAddress ?? null });
    writeJson(res, 403, { error: "forbidden" });
    return;
  }

  if (!originAllowed(req)) {
    log("warn", "request_rejected", { reason: "origin", remote: req.socket.remoteAddress ?? null });
    writeJson(res, 403, { error: "forbidden" });
    return;
  }

  if (!bearerAllowed(req)) {
    res.setHeader("WWW-Authenticate", 'Bearer realm="nexolab-mcp"');
    writeJson(res, 401, { error: "unauthorized" });
    return;
  }

  void nodeMcpHandler(req, res);
});

httpServer.requestTimeout = 30_000;
httpServer.headersTimeout = 15_000;
httpServer.keepAliveTimeout = 5_000;
httpServer.maxRequestsPerSocket = 100;

httpServer.listen(config.port, config.host, () => {
  log("info", "server_started", {
    host: config.host,
    port: config.port,
    endpoint: "/mcp",
    authenticated: Boolean(config.mcpBearerToken),
  });
});

function shutdown(signal: string): void {
  log("info", "shutdown_requested", { signal });
  httpServer.close((error) => {
    if (error) {
      log("error", "shutdown_failed", { message: safeError(error) });
      process.exitCode = 1;
    }
    void mcpHandler.close().finally(() => process.exit());
  });
  setTimeout(() => process.exit(1), 10_000).unref();
}

process.once("SIGTERM", () => shutdown("SIGTERM"));
process.once("SIGINT", () => shutdown("SIGINT"));
