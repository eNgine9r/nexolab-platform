import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ComponentProps } from "react";
import type { LaboratorySession } from "@/lib/sessions/types";
import { SessionReportAction } from "./session-report-action";

const mock = vi.hoisted(() => ({
  permissions: ["reports.read", "reports.generate"],
  organizationId: "org-a",
  operationPending: false,
}));
vi.mock("next/link", () => ({ default: (props: ComponentProps<"a">) => <a {...props} /> }));
vi.mock("@/components/dashboard/platform-account-boundary", () => ({
  usePlatformAccount: () => ({
    operationPending: mock.operationPending,
    security: {
      membership: { organizationId: mock.organizationId },
      session: { memberships: [{ organizationId: mock.organizationId, permissions: mock.permissions }] },
    },
  }),
}));
const session = {
  id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
  organization_id: "org-a",
  state: "completed",
} as LaboratorySession;
beforeEach(() => {
  mock.permissions = ["reports.read", "reports.generate"];
  mock.organizationId = "org-a";
  mock.operationPending = false;
});
describe("SessionReportAction", () => {
  it.each(["completed", "archived"] as const)("offers exact report context for %s", (state) => {
    render(<SessionReportAction session={{ ...session, state }} pending={false} />);
    expect(screen.getByRole("link", { name: "Сформувати звіт" })).toHaveAttribute(
      "href",
      `/reports?session=${session.id}`,
    );
  });
  it.each(["draft", "ready", "running", "paused", "cancelled"] as const)(
    "does not offer generation for %s",
    (state) => {
      render(<SessionReportAction session={{ ...session, state }} pending={false} />);
      expect(screen.queryByRole("link")).not.toBeInTheDocument();
    },
  );
  it("offers viewing for a report reader", () => {
    mock.permissions = ["reports.read"];
    render(<SessionReportAction session={session} pending={false} />);
    expect(screen.getByRole("link", { name: "Переглянути звіти" })).toBeVisible();
  });
  it("hides the action without report access", () => {
    mock.permissions = [];
    render(<SessionReportAction session={session} pending={false} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
  it("does not carry another organization's context", () => {
    mock.organizationId = "org-b";
    render(<SessionReportAction session={session} pending={false} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
  it.each([false, true])("blocks navigation during a pending operation (%s)", (operationPending) => {
    mock.operationPending = operationPending;
    render(<SessionReportAction session={session} pending={!operationPending} />);
    expect(screen.getByRole("button", { name: "Сформувати звіт" })).toBeDisabled();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
