import { expect, test, type Browser, type BrowserContext } from "@playwright/test";

const organizationId = requiredEnvironment("NEXOLAB_DASHBOARD_ORGANIZATION_ID");
const sessionCredential = requiredEnvironment("NEXOLAB_DASHBOARD_VIEWER_TOKEN");
const apiBaseUrl = requiredEnvironment("NEXT_PUBLIC_NEXOLAB_API_BASE_URL");

interface RoutedSocket {
  close(options?: { code?: number; reason?: string }): Promise<void>;
}

interface RoutedSocketState {
  healthyServer: RoutedSocket | null;
}

async function authenticatedContext(browser: Browser): Promise<BrowserContext> {
  const context = await browser.newContext();
  await context.addInitScript(
    ({ accessToken, organization }) => {
      if (window.location.protocol === "about:") return;
      window.sessionStorage.setItem("nexolab.acceptance.access-token", accessToken);
      window.sessionStorage.setItem("nexolab.acceptance.organization-id", organization);
    },
    { accessToken: sessionCredential, organization: organizationId },
  );
  return context;
}

async function websocketClientCount(): Promise<number> {
  const response = await fetch(`${apiBaseUrl}/health/ready`);
  if (!response.ok) throw new Error(`Telemetry readiness returned HTTP ${response.status}`);
  const payload = (await response.json()) as { websocket_clients?: number };
  if (typeof payload.websocket_clients !== "number") {
    throw new Error("Telemetry readiness did not expose websocket_clients");
  }
  return payload.websocket_clients;
}

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`Missing required environment variable ${name}`);
  return value;
}

test("Live Data Retry restarts one terminal shared WebSocket transport", async ({ browser }) => {
  const context = await authenticatedContext(browser);
  let outage = false;
  let routedSocketCount = 0;
  const routedSocketState: RoutedSocketState = { healthyServer: null };

  await context.routeWebSocket(/\/api\/v1\/telemetry\/live(?:\?|$)/, async (socket) => {
    routedSocketCount += 1;
    if (outage) {
      await socket.close({ code: 1012, reason: "issue-493-terminal-outage" });
      return;
    }

    routedSocketState.healthyServer = socket.connectToServer();
  });

  const page = await context.newPage();
  const inventoryChannel = page.getByTestId("live-inventory-panel").getByRole("cell", {
    name: "106-03",
    exact: true,
  });

  try {
    await page.goto("/live?workspace=explorer", { waitUntil: "domcontentloaded" });
    await expect(page.getByText("Живий потік підключено", { exact: true })).toBeVisible();
    await expect(inventoryChannel).toBeVisible();
    await expect.poll(websocketClientCount).toBe(1);
    expect(routedSocketCount).toBe(1);

    const baselineServer = routedSocketState.healthyServer;
    if (!baselineServer) throw new Error("Initial routed server WebSocket was not captured");

    outage = true;
    await baselineServer.close({ code: 1012, reason: "issue-493-terminal-outage" });

    await expect(page.getByText("Live-потік офлайн", { exact: true })).toBeVisible({ timeout: 35_000 });
    await expect(inventoryChannel).toBeVisible();
    await expect.poll(websocketClientCount).toBe(0);

    const attemptsAtOffline = routedSocketCount;
    expect(attemptsAtOffline).toBeGreaterThan(1);

    outage = false;
    await page.waitForTimeout(1_500);
    expect(routedSocketCount).toBe(attemptsAtOffline);
    await expect.poll(websocketClientCount).toBe(0);

    await page.getByRole("button", { name: "Повторити", exact: true }).click();

    await expect(page.getByText("Живий потік підключено", { exact: true })).toBeVisible({ timeout: 20_000 });
    await expect.poll(websocketClientCount).toBe(1);
    await page.waitForTimeout(1_000);
    expect(routedSocketCount).toBe(attemptsAtOffline + 1);
  } finally {
    await context.close();
  }
});
