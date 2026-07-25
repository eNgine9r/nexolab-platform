import { authenticatedWebSocketProtocols } from "./auth-session";

export type AccessTokenProvider = () => string | null;

export function createAuthenticatedFetch(
  getAccessToken: AccessTokenProvider,
  fetchImpl: typeof fetch = fetch.bind(globalThis),
): typeof fetch {
  return async (input: RequestInfo | URL, init?: RequestInit) => {
    const headers = new Headers(init?.headers);
    const token = getAccessToken()?.trim();
    if (token && !headers.has("Authorization")) {
      headers.set("Authorization", `Bearer ${token}`);
    }
    return fetchImpl(input, { ...init, headers });
  };
}

export function createAuthenticatedWebSocketFactory(
  getAccessToken: AccessTokenProvider,
): (url: string) => WebSocket {
  return (url) => {
    const protocols = authenticatedWebSocketProtocols(getAccessToken());
    return protocols ? new WebSocket(url, protocols) : new WebSocket(url);
  };
}
