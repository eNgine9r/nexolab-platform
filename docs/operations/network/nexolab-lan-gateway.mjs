#!/usr/bin/env node
// NEXOLAB LOCAL_LAN gateway (#1734 WP2b).
//
// One LAN entry point bound to all interfaces, so the UI works over eth0 or
// wlan0 at any DHCP address or host name. It serves the dashboard and proxies
// the Telemetry API and its WebSocket on the SAME origin, which lets a
// `same-origin` frontend build (WP2a) run without any host IP compiled in.
//
//   /api/v1/...  (HTTP and WebSocket upgrade)  -> NEXOLAB_LAN_GATEWAY_API
//   everything else                            -> NEXOLAB_LAN_GATEWAY_DASHBOARD
//
// Upstreams must be loopback (or the exact private Compose service names);
// anything else fails closed at start. No dependencies beyond Node itself,
// no internet, no credentials: authentication stays end-to-end between the
// browser and the API/dashboard. Bounded: header/idle timeouts, a connection
// cap and a request-body cap protect the Pi.
import http from "node:http";
import net from "node:net";
import os from "node:os";
import { pathToFileURL } from "node:url";

const env = process.env;
const LISTEN_HOST = env.NEXOLAB_LAN_GATEWAY_HOST ?? "0.0.0.0";
const LISTEN_PORT = Number(env.NEXOLAB_LAN_GATEWAY_PORT ?? "3000");
const MAX_CONNECTIONS = Number(env.NEXOLAB_LAN_GATEWAY_MAX_CONNECTIONS ?? "512");
const MAX_BODY_BYTES = Number(env.NEXOLAB_LAN_GATEWAY_MAX_BODY_BYTES ?? String(32 * 1024 * 1024));
const IDLE_MS = Number(env.NEXOLAB_LAN_GATEWAY_IDLE_MS ?? "120000");
const ALLOWED_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]", "telemetry-service", "dashboard"]);
// Interim only (#1733 -> WP2c phase 3): the exact compatibility address may be allowed explicitly.
const COMPAT_UPSTREAM = env.NEXOLAB_LAN_GATEWAY_ALLOW_COMPAT ?? "";
if (COMPAT_UPSTREAM === "172.18.48.66") ALLOWED_HOSTS.add(COMPAT_UPSTREAM);
// `auto`: listen on the current IPv4 addresses of LAN interfaces only (never tailscale0,
// Docker bridges, veth or the compatibility dummy), re-scanned so DHCP changes and
// Ethernet <-> Wi-Fi switching need no configuration. A wildcard bind would collide with
// tailscaled's own :80 listener and would expose the gateway on the tailnet without OAuth.
const AUTO_INTERFACES = (env.NEXOLAB_LAN_GATEWAY_INTERFACES ?? "lo,eth*,en*,wlan*,wl*")
  .split(",")
  .map((p) => p.trim())
  .filter(Boolean);
const NEVER_INTERFACES = [
  "tailscale*",
  "docker*",
  "br-*",
  "veth*",
  "nxcompat*",
  "virbr*",
  "cni*",
  "flannel*",
  "zt*",
  "wg*",
  "tun*",
];
const RESCAN_MS = Number(env.NEXOLAB_LAN_GATEWAY_RESCAN_MS ?? "5000");
const API_PREFIX = "/api/v1";
const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

function globMatch(pattern, name) {
  return pattern.endsWith("*") ? name.startsWith(pattern.slice(0, -1)) : name === pattern;
}

/** IPv4 addresses the `auto` mode listens on, from an os.networkInterfaces()-shaped object. */
export function selectAddresses(interfaces, allow = AUTO_INTERFACES) {
  const result = [];
  for (const [name, entries] of Object.entries(interfaces ?? {})) {
    if (NEVER_INTERFACES.some((pattern) => globMatch(pattern, name))) continue;
    if (!allow.some((pattern) => globMatch(pattern, name))) continue;
    for (const entry of entries ?? []) {
      const v4 = entry.family === "IPv4" || entry.family === 4;
      if (!v4 || !entry.address || entry.address.startsWith("169.254.")) continue;
      if (name === "lo" && entry.address !== "127.0.0.1") continue;
      if (
        entry.address.startsWith("100.") &&
        Number(entry.address.split(".")[1]) >= 64 &&
        Number(entry.address.split(".")[1]) <= 127
      )
        continue; // CGNAT / Tailscale range
      result.push(entry.address);
    }
  }
  return [...new Set(result)].sort();
}

export function parseUpstream(value, name) {
  let url;
  try {
    url = new URL(value ?? "");
  } catch {
    throw new Error(`${name} must be an absolute http URL`);
  }
  if (
    url.protocol !== "http:" ||
    !url.port ||
    url.username ||
    url.password ||
    url.pathname !== "/" ||
    url.search ||
    url.hash
  ) {
    throw new Error(`${name} must be http://<host>:<port> without path or credentials`);
  }
  if (!ALLOWED_HOSTS.has(url.hostname)) {
    throw new Error(`${name} host ${url.hostname} is not a loopback or private service name`);
  }
  return { host: url.hostname.replace(/^\[|\]$/g, ""), port: Number(url.port), origin: url.origin };
}

export function routeFor(rawUrl) {
  const path = (rawUrl ?? "/").split("?")[0];
  if (path.includes("..") || path.includes("\\") || !path.startsWith("/")) return null;
  return path === API_PREFIX || path.startsWith(`${API_PREFIX}/`) ? "api" : "dashboard";
}

function forwardHeaders(req, upgrade) {
  const headers = {};
  for (const [key, value] of Object.entries(req.headers)) {
    if (!HOP_BY_HOP.has(key.toLowerCase())) headers[key] = value;
  }
  const remote = req.socket.remoteAddress ?? "";
  headers["x-forwarded-for"] = remote;
  headers["x-forwarded-proto"] = "http";
  if (req.headers.host) headers["x-forwarded-host"] = req.headers.host;
  if (upgrade) {
    headers.connection = "Upgrade";
    headers.upgrade = req.headers.upgrade;
  }
  return headers;
}

export function createGateway({ api, dashboard }) {
  const upstreams = { api, dashboard };
  const server = http.createServer((req, res) => {
    const route = routeFor(req.url);
    if (!route) {
      res.writeHead(400, { "content-type": "text/plain" }).end("bad request\n");
      return;
    }
    if (req.url === "/__nexolab_lan_gateway/health") {
      res.writeHead(200, { "content-type": "application/json", "cache-control": "no-store" });
      res.end(JSON.stringify({ status: "ok", service: "nexolab-lan-gateway" }));
      return;
    }
    const declared = Number(req.headers["content-length"] ?? "0");
    if (declared > MAX_BODY_BYTES) {
      res.writeHead(413, { "content-type": "text/plain" }).end("payload too large\n");
      return;
    }
    const target = upstreams[route];
    let seen = 0;
    const upstream = http.request(
      {
        host: target.host,
        port: target.port,
        method: req.method,
        path: req.url,
        headers: forwardHeaders(req, false),
      },
      (upRes) => {
        const headers = {};
        for (const [key, value] of Object.entries(upRes.headers)) {
          if (!HOP_BY_HOP.has(key.toLowerCase())) headers[key] = value;
        }
        res.writeHead(upRes.statusCode ?? 502, headers);
        upRes.pipe(res);
      },
    );
    upstream.setTimeout(IDLE_MS, () => upstream.destroy(new Error("upstream timeout")));
    upstream.on("error", () => {
      if (!res.headersSent) {
        res.writeHead(route === "api" ? 503 : 502, {
          "content-type": "text/plain",
          "cache-control": "no-store",
        });
        res.end(route === "api" ? "telemetry api unavailable\n" : "dashboard unavailable\n");
      } else {
        res.destroy();
      }
    });
    req.on("data", (chunk) => {
      seen += chunk.length;
      if (seen > MAX_BODY_BYTES) {
        upstream.destroy();
        req.destroy();
      }
    });
    req.pipe(upstream);
  });

  server.on("upgrade", (req, socket, head) => {
    const route = routeFor(req.url);
    if (route !== "api" || (req.headers.upgrade ?? "").toLowerCase() !== "websocket") {
      socket.end("HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n");
      return;
    }
    const target = upstreams.api;
    const upstream = net.connect(target.port, target.host, () => {
      const headers = forwardHeaders(req, true);
      const lines = [`${req.method} ${req.url} HTTP/1.1`];
      for (const [key, value] of Object.entries(headers)) {
        for (const item of Array.isArray(value) ? value : [value]) lines.push(`${key}: ${item}`);
      }
      upstream.write(`${lines.join("\r\n")}\r\n\r\n`);
      if (head?.length) upstream.write(head);
      upstream.pipe(socket);
      socket.pipe(upstream);
    });
    const close = () => {
      upstream.destroy();
      socket.destroy();
    };
    upstream.setTimeout(0);
    upstream.on("error", () => {
      if (socket.writable) socket.end("HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\n\r\n");
      close();
    });
    socket.on("error", close);
    socket.on("close", close);
    upstream.on("close", close);
  });

  server.headersTimeout = 20000;
  server.requestTimeout = 0;
  server.keepAliveTimeout = 5000;
  server.maxConnections = MAX_CONNECTIONS;
  server.on("clientError", (_err, socket) => socket.destroy());
  return server;
}

function startAuto(upstreams) {
  const listeners = new Map();
  const log = (event, extra) => console.log(JSON.stringify({ event, ...extra }));
  const scan = () => {
    const wanted = new Set(selectAddresses(os.networkInterfaces()));
    for (const [address, server] of listeners) {
      if (!wanted.has(address)) {
        server.close();
        listeners.delete(address);
        log("address_removed", { address });
      }
    }
    for (const address of wanted) {
      if (listeners.has(address)) continue;
      const server = createGateway(upstreams);
      listeners.set(address, server);
      server.once("error", (error) => {
        listeners.delete(address);
        log("listen_failed", { address, port: LISTEN_PORT, code: error.code });
      });
      server.listen(LISTEN_PORT, address, () => log("listening", { address, port: LISTEN_PORT }));
    }
  };
  scan();
  const timer = setInterval(scan, RESCAN_MS);
  return () => {
    clearInterval(timer);
    for (const server of listeners.values()) server.close();
  };
}

const isMain = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (isMain) {
  try {
    const api = parseUpstream(
      env.NEXOLAB_LAN_GATEWAY_API ?? "http://127.0.0.1:8082/",
      "NEXOLAB_LAN_GATEWAY_API",
    );
    const dashboard = parseUpstream(
      env.NEXOLAB_LAN_GATEWAY_DASHBOARD ?? "http://127.0.0.1:3010/",
      "NEXOLAB_LAN_GATEWAY_DASHBOARD",
    );
    if (!Number.isInteger(LISTEN_PORT) || LISTEN_PORT < 1 || LISTEN_PORT > 65535)
      throw new Error("invalid listen port");
    if (LISTEN_HOST === "auto") {
      const stopAuto = startAuto({ api, dashboard });
      console.log(
        JSON.stringify({
          event: "auto_mode",
          interfaces: AUTO_INTERFACES,
          never: NEVER_INTERFACES,
          api: api.origin,
          dashboard: dashboard.origin,
        }),
      );
      const stop = () => {
        stopAuto();
        setTimeout(() => process.exit(0), 200);
      };
      process.on("SIGTERM", stop);
      process.on("SIGINT", stop);
    } else {
      const server = createGateway({ api, dashboard });
      server.listen(LISTEN_PORT, LISTEN_HOST, () => {
        console.log(
          JSON.stringify({
            event: "listening",
            host: LISTEN_HOST,
            port: LISTEN_PORT,
            api: api.origin,
            dashboard: dashboard.origin,
          }),
        );
      });
      const stop = () => server.close(() => process.exit(0));
      process.on("SIGTERM", stop);
      process.on("SIGINT", stop);
    }
  } catch (error) {
    console.error(`NEXOLAB_LAN_GATEWAY_CONFIG_REFUSED ${error.message}`);
    process.exit(64);
  }
}
