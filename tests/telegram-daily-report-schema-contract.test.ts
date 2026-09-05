import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const CANONICAL_SCHEMA = "nexolab.daily-refrigeration-report.v1";

function source(path: string): string {
  return readFileSync(resolve(process.cwd(), path), "utf8");
}

describe("Telegram daily report schema contract", () => {
  it("keeps TG-01 authority, Mini App parser, and gateway fixtures aligned", () => {
    const telemetryDomain = source("services/telemetry-service/app/daily_reports/domain.py");
    const miniApp = source("src/components/telegram/telegram-miniapp-report.tsx");
    const gatewayFixture = source("services/telegram-gateway/tests/support.py");

    expect(telemetryDomain).toContain(`DAILY_REPORT_SCHEMA = "${CANONICAL_SCHEMA}"`);
    expect(miniApp).toContain(`payload.schema !== "${CANONICAL_SCHEMA}"`);
    expect(gatewayFixture).toContain(`"schema": "${CANONICAL_SCHEMA}"`);
  });
});
