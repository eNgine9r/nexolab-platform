import { useRef, useState, type ReactNode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DashboardSecurityModel } from "@/hooks/use-dashboard-security";
import { usePlatformAccount } from "./platform-account-boundary";
import { SessionsShell } from "@/components/sessions/sessions-shell";
import { PlatformPlaceholderScreen } from "./platform-placeholder-screen";

const mock = vi.hoisted(() => ({
  security: null as DashboardSecurityModel | null,
  pathname: "/sessions",
  replace: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mock.replace }),
  usePathname: () => mock.pathname,
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));
vi.mock("@/hooks/use-dashboard-security", () => ({ useDashboardSecurity: () => mock.security }));
vi.mock("./sidebar", () => ({ Sidebar: () => null }));

function ready(organizationId = "org-a", manage = true): DashboardSecurityModel {
  const memberships = ["org-a", "org-b"].map((id) => ({
    organizationId: id,
    organizationSlug: id,
    organizationName: id,
    roles: ["operator" as const],
    permissions: manage
      ? ["dashboard.read" as const, "sessions.manage" as const]
      : ["dashboard.read" as const],
  }));
  return {
    mode: "live",
    state: "ready",
    session: {
      authenticated: true,
      identity: {
        id: "operator",
        provider: "local",
        subject: "operator",
        email: null,
        displayName: "Перевірений оператор",
      },
      memberships,
    },
    membership: memberships.find((item) => item.organizationId === organizationId)!,
    error: null,
    errorCode: null,
    diagnostics: null,
    selectOrganization: vi.fn(),
    signOut: vi.fn(async () => {}),
    retry: vi.fn(),
  };
}
function Draft() {
  const [draft, setDraft] = useState("");
  return (
    <input aria-label="Локальна чернетка" value={draft} onChange={(event) => setDraft(event.target.value)} />
  );
}
function Shell({ kind }: { kind: "sessions" | "lockers" }) {
  return kind === "sessions" ? (
    <SessionsShell>
      <Draft />
    </SessionsShell>
  ) : (
    <PlatformPlaceholderScreen title="Поштомати" eyebrow="Модуль" description="Контент поштоматів" />
  );
}
beforeEach(() => {
  mock.security = ready();
  mock.pathname = "/sessions";
  mock.replace.mockClear();
});
describe.each(["sessions", "lockers"] as const)("%s verified account shell", (kind) => {
  it.each(["loading", "unauthenticated", "forbidden", "error"] as const)(
    "gates live content for %s",
    (state) => {
      mock.security = { ...ready(), state, session: null, membership: null };
      render(<Shell kind={kind} />);
      expect(screen.queryByLabelText("Локальна чернетка")).not.toBeInTheDocument();
      expect(screen.queryByText("Контент поштоматів")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Вийти з NEXOLAB" })).not.toBeInTheDocument();
    },
  );
  it("shows the verified identity and accessible account actions", () => {
    render(<Shell kind={kind} />);
    expect(screen.getByText("Перевірений оператор")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Організація" })).toHaveValue("org-a");
    expect(screen.getByRole("button", { name: "Вийти з NEXOLAB" })).toBeInTheDocument();
  });
  it("waits for sign-out before navigating to login", async () => {
    let finish!: () => void;
    mock.security!.signOut = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    render(<Shell kind={kind} />);
    fireEvent.click(screen.getByRole("button", { name: "Вийти з NEXOLAB" }));
    expect(mock.security!.signOut).toHaveBeenCalledOnce();
    expect(mock.replace).not.toHaveBeenCalled();
    finish();
    await waitFor(() => expect(mock.replace).toHaveBeenCalledWith("/login"));
  });
  it("does not offer session creation without sessions.manage", () => {
    mock.security = ready("org-a", false);
    render(<Shell kind={kind} />);
    expect(screen.queryByRole("link", { name: "Нова сесія" })).not.toBeInTheDocument();
  });
  it("ignores same and unavailable organizations", () => {
    render(<Shell kind={kind} />);
    const select = screen.getByRole("combobox", { name: "Організація" });
    fireEvent.change(select, { target: { value: "org-a" } });
    fireEvent.change(select, { target: { value: "unavailable" } });
    expect(mock.security!.selectOrganization).not.toHaveBeenCalled();
    expect(mock.replace).not.toHaveBeenCalled();
  });
});
it.each(["/sessions/new", "/sessions/session-a"])(
  "holds %s children until list navigation and membership transition finish",
  (path) => {
    mock.pathname = path;
    const { rerender } = render(<Shell kind="sessions" />);
    fireEvent.change(screen.getByLabelText("Локальна чернетка"), { target: { value: "org-a draft" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Організація" }), { target: { value: "org-b" } });
    expect(mock.replace).toHaveBeenCalledWith("/sessions");
    expect(mock.security!.selectOrganization).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("Локальна чернетка")).not.toBeInTheDocument();
    mock.pathname = "/sessions";
    rerender(<Shell kind="sessions" />);
    expect(mock.security!.selectOrganization).toHaveBeenCalledWith("org-b");
    expect(screen.queryByLabelText("Локальна чернетка")).not.toBeInTheDocument();
    mock.security = ready("org-b");
    rerender(<Shell kind="sessions" />);
    expect(screen.getByLabelText("Локальна чернетка")).toHaveValue("");
    expect(screen.getByRole("combobox", { name: "Організація" })).toHaveValue("org-b");
  },
);
it("switches the session catalog without retaining its draft state", () => {
  const { rerender } = render(<Shell kind="sessions" />);
  fireEvent.change(screen.getByLabelText("Локальна чернетка"), { target: { value: "org-a search" } });
  fireEvent.change(screen.getByRole("combobox", { name: "Організація" }), { target: { value: "org-b" } });
  expect(mock.security!.selectOrganization).toHaveBeenCalledWith("org-b");
  mock.security = ready("org-b");
  rerender(<Shell kind="sessions" />);
  expect(screen.getByLabelText("Локальна чернетка")).toHaveValue("");
});
it("switches lockers within the verified memberships", () => {
  render(<Shell kind="lockers" />);
  fireEvent.change(screen.getByRole("combobox", { name: "Організація" }), { target: { value: "org-b" } });
  expect(mock.security!.selectOrganization).toHaveBeenCalledWith("org-b");
  expect(mock.replace).not.toHaveBeenCalled();
});

it("allows a failed sign-out to be retried without redirecting", async () => {
  mock.security!.signOut = vi
    .fn()
    .mockRejectedValueOnce(new Error("network"))
    .mockResolvedValueOnce(undefined);
  render(<Shell kind="sessions" />);
  fireEvent.click(screen.getByRole("button", { name: "Вийти з NEXOLAB" }));
  await screen.findByText("Не вдалося завершити вихід. Повторіть спробу.");
  expect(mock.replace).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: /Повторити/ }));
  await waitFor(() => expect(mock.replace).toHaveBeenCalledWith("/login"));
});

function PendingOperation() {
  const account = usePlatformAccount();
  const releases = useRef<Array<() => void>>([]);
  return (
    <>
      <button
        onClick={() => {
          const release = account?.beginOperation();
          if (release) releases.current.push(release);
        }}
      >
        Почати операцію
      </button>
      <button onClick={() => releases.current.pop()?.()}>Завершити операцію</button>
      <Draft />
    </>
  );
}
it("keeps session content mounted and blocks account transitions during an active submission", () => {
  render(
    <SessionsShell>
      <PendingOperation />
    </SessionsShell>,
  );
  fireEvent.change(screen.getByLabelText("Локальна чернетка"), { target: { value: "current draft" } });
  fireEvent.click(screen.getByRole("button", { name: "Почати операцію" }));
  const logout = screen.getByRole("button", { name: "Вийти з NEXOLAB" });
  const organizations = screen.getByRole("combobox", { name: "Організація" });
  expect(logout).toBeDisabled();
  expect(organizations).toBeDisabled();
  fireEvent.click(logout);
  fireEvent.change(organizations, { target: { value: "org-b" } });
  expect(mock.security!.signOut).not.toHaveBeenCalled();
  expect(mock.security!.selectOrganization).not.toHaveBeenCalled();
  expect(mock.replace).not.toHaveBeenCalled();
  expect(screen.getByLabelText("Локальна чернетка")).toHaveValue("current draft");
  expect(screen.getByRole("status")).toHaveTextContent("Операція з випробуванням триває");
  fireEvent.click(screen.getByRole("button", { name: "Завершити операцію" }));
  expect(logout).toBeEnabled();
  expect(organizations).toBeEnabled();
});

it("keeps account controls locked until every independent operation has finished", () => {
  render(
    <SessionsShell>
      <PendingOperation />
    </SessionsShell>,
  );
  const start = screen.getByRole("button", { name: "Почати операцію" });
  const finish = screen.getByRole("button", { name: "Завершити операцію" });
  const logout = screen.getByRole("button", { name: "Вийти з NEXOLAB" });
  fireEvent.click(start);
  fireEvent.click(start);
  fireEvent.click(finish);
  expect(logout).toBeDisabled();
  fireEvent.click(finish);
  expect(logout).toBeEnabled();
});
