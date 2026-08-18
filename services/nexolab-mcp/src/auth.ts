import { readFile } from "node:fs/promises";

import type { BackendAuthConfig } from "./config.js";

export type AuthFetch = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;
export type SecretReader = (path: string) => Promise<string>;

export interface BackendAccessTokenProvider {
  readonly refreshable: boolean;
  getAccessToken(): Promise<string | undefined>;
  invalidate(): void;
}

type TokenPair = {
  accessToken: string;
  refreshToken: string;
  accessExpiresAtMs: number;
};

type LocalProviderOptions = {
  fetch?: AuthFetch;
  readSecret?: SecretReader;
  now?: () => number;
  timeoutMs: number;
};

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parsePositiveSeconds(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    throw new Error(`Local auth response contains invalid ${field}.`);
  }
  return value;
}

function parseTokenPair(value: unknown, nowMs: number): TokenPair {
  if (!isObject(value)) throw new Error("Local auth response is not an object.");
  const accessToken = value.access_token;
  const refreshToken = value.refresh_token;
  if (typeof accessToken !== "string" || accessToken.length < 16) {
    throw new Error("Local auth response contains an invalid access token.");
  }
  if (typeof refreshToken !== "string" || refreshToken.length < 32) {
    throw new Error("Local auth response contains an invalid refresh token.");
  }
  const expiresIn = parsePositiveSeconds(value.expires_in, "expires_in");
  const refreshSkewMs = Math.min(30_000, Math.max(5_000, (expiresIn * 1_000) / 10));
  return {
    accessToken,
    refreshToken,
    accessExpiresAtMs: nowMs + expiresIn * 1_000 - refreshSkewMs,
  };
}

async function responseJson(response: Response, label: string): Promise<unknown> {
  if (!response.ok) throw new Error(`${label} returned HTTP ${response.status}.`);
  try {
    return (await response.json()) as unknown;
  } catch {
    throw new Error(`${label} returned invalid JSON.`);
  }
}

export class StaticAccessTokenProvider implements BackendAccessTokenProvider {
  readonly refreshable = false;

  constructor(private readonly token?: string) {}

  getAccessToken(): Promise<string | undefined> {
    return Promise.resolve(this.token);
  }

  invalidate(): void {}
}

export class LocalSessionAccessTokenProvider implements BackendAccessTokenProvider {
  readonly refreshable = true;
  private readonly fetchImpl: AuthFetch;
  private readonly readSecret: SecretReader;
  private readonly now: () => number;
  private tokenPair?: TokenPair;
  private inFlight: Promise<string> | undefined;

  constructor(
    private readonly apiBaseUrl: string,
    private readonly username: string,
    private readonly passwordFile: string,
    private readonly options: LocalProviderOptions,
  ) {
    this.fetchImpl = options.fetch ?? fetch.bind(globalThis);
    this.readSecret = options.readSecret ?? ((path) => readFile(path, "utf8"));
    this.now = options.now ?? Date.now;
  }

  async getAccessToken(): Promise<string> {
    if (this.tokenPair && this.now() < this.tokenPair.accessExpiresAtMs) {
      return this.tokenPair.accessToken;
    }
    if (!this.inFlight) {
      this.inFlight = this.acquireToken().finally(() => {
        this.inFlight = undefined;
      });
    }
    return this.inFlight;
  }

  invalidate(): void {
    if (this.tokenPair) this.tokenPair.accessExpiresAtMs = 0;
  }

  private async acquireToken(): Promise<string> {
    const pair = this.tokenPair?.refreshToken
      ? await this.refreshOrLogin(this.tokenPair.refreshToken)
      : await this.login();
    this.tokenPair = pair;
    return pair.accessToken;
  }

  private async refreshOrLogin(refreshToken: string): Promise<TokenPair> {
    try {
      return await this.postAuth("/api/v1/auth/local/refresh", { refresh_token: refreshToken }, "Local auth refresh");
    } catch {
      return this.login();
    }
  }

  private async login(): Promise<TokenPair> {
    const password = (await this.readSecret(this.passwordFile)).trimEnd();
    if (!password) throw new Error("NEXOLAB backend password secret is empty.");
    return this.postAuth(
      "/api/v1/auth/local/login",
      { username: this.username, password },
      "Local auth login",
    );
  }

  private async postAuth(path: string, body: Record<string, string>, label: string): Promise<TokenPair> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.options.timeoutMs);
    try {
      const response = await this.fetchImpl(`${this.apiBaseUrl}${path}`, {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      return parseTokenPair(await responseJson(response, label), this.now());
    } catch (error) {
      if (controller.signal.aborted) throw new Error(`${label} timed out.`);
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }
}

export function createBackendAccessTokenProvider(
  auth: BackendAuthConfig,
  apiBaseUrl: string,
  timeoutMs: number,
): BackendAccessTokenProvider {
  if (auth.mode === "bearer") return new StaticAccessTokenProvider(auth.bearerToken);
  if (auth.mode === "local") {
    return new LocalSessionAccessTokenProvider(apiBaseUrl, auth.username, auth.passwordFile, { timeoutMs });
  }
  return new StaticAccessTokenProvider();
}
