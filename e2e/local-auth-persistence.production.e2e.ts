import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type APIRequestContext } from "@playwright/test";

const rootDirectory = process.cwd();
const apiBaseUrl = requiredEnvironment("NEXT_PUBLIC_NEXOLAB_API_BASE_URL");
const organizationId = requiredEnvironment("NEXOLAB_LOCAL_AUTH_ORGANIZATION_ID");
const administratorUsername = requiredEnvironment("NEXOLAB_LOCAL_AUTH_ADMIN_USERNAME");
const password = requiredEnvironment("NEXOLAB_LOCAL_AUTH_PASSWORD");
const composeProjectName = requiredEnvironment("COMPOSE_PROJECT_NAME");
const postgresVolumeName = requiredEnvironment("ACCEPTANCE_POSTGRES_VOLUME_NAME");
const postgresDatabase = requiredEnvironment("POSTGRES_DB");
const postgresUser = requiredEnvironment("POSTGRES_USER");
const evidenceDirectory =
  process.env.NEXOLAB_LOCAL_AUTH_EVIDENCE_DIR ?? "local-auth-acceptance-evidence";

const composeFiles = [
  "infrastructure/compose/compose.central.yaml",
  "infrastructure/compose/compose.local-auth.yaml",
  "infrastructure/compose/compose.local-auth-acceptance.yaml",
];

type TokenPair = {
  access_token: string;
  refresh_token: string;
};

function compose(arguments_: string[], input?: string): string {
  const fileArguments = composeFiles.flatMap((file) => ["--file", file]);
  return execFileSync(
    "docker",
    ["compose", "--project-name", composeProjectName, ...fileArguments, ...arguments_],
    {
      cwd: rootDirectory,
      env: process.env,
      encoding: "utf-8",
      input,
      stdio: ["pipe", "pipe", "pipe"],
    },
  );
}

function postgresStateSnapshot(): string {
  const sql = String.raw`
\pset tuples_only on
\pset format unaligned
SELECT 'accounts_count=' || count(*) FROM security_local_accounts;
SELECT 'accounts_fingerprint=' || md5(COALESCE(string_agg(
  concat_ws(':', id, identity_id, username, is_active::text),
  '|' ORDER BY username
), '')) FROM security_local_accounts;
SELECT 'membership_roles_count=' || count(*)
FROM security_organization_memberships memberships
JOIN security_membership_roles roles ON roles.membership_id = memberships.id;
SELECT 'membership_roles_fingerprint=' || md5(COALESCE(string_agg(
  concat_ws(':', memberships.id, memberships.identity_id, memberships.organization_id, roles.role),
  '|' ORDER BY memberships.id, roles.role
), ''))
FROM security_organization_memberships memberships
JOIN security_membership_roles roles ON roles.membership_id = memberships.id;
SELECT 'sessions_count=' || count(*) FROM security_local_sessions;
SELECT 'sessions_fingerprint=' || md5(COALESCE(string_agg(
  concat_ws(':', id, account_id, expires_at::text, (revoked_at IS NOT NULL)::text),
  '|' ORDER BY id
), '')) FROM security_local_sessions;
`;

  return compose(
    [
      "exec",
      "-T",
      "postgres",
      "psql",
      "-U",
      postgresUser,
      "-d",
      postgresDatabase,
      "-v",
      "ON_ERROR_STOP=1",
    ],
    sql,
  ).trim();
}

function postgresVolumeIdentity(): string {
  return execFileSync(
    "docker",
    ["volume", "inspect", postgresVolumeName, "--format", "{{.Name}}|{{.CreatedAt}}"],
    {
      cwd: rootDirectory,
      env: process.env,
      encoding: "utf-8",
      stdio: ["ignore", "pipe", "pipe"],
    },
  ).trim();
}

async function waitForReady(request: APIRequestContext): Promise<void> {
  await expect
    .poll(
      async () => {
        try {
          const response = await request.get(`${apiBaseUrl}/health/ready`, { timeout: 3_000 });
          return response.status();
        } catch {
          return 0;
        }
      },
      {
        timeout: 180_000,
        intervals: [1_000, 2_000, 3_000],
        message: "local-auth API did not recover after container recreation",
      },
    )
    .toBe(200);
}

async function assertAccessTokenActive(
  request: APIRequestContext,
  accessToken: string,
): Promise<void> {
  const response = await request.get(`${apiBaseUrl}/api/v1/auth/session`, {
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "X-Organization-ID": organizationId,
      Accept: "application/json",
    },
  });
  expect(response.status()).toBe(200);
}

async function recreateStack(request: APIRequestContext): Promise<void> {
  compose(["up", "--detach", "--no-build", "--force-recreate"]);
  await waitForReady(request);
}

test("preserves local accounts, memberships and refresh sessions through update and rollback recreation", async ({
  request,
}) => {
  mkdirSync(evidenceDirectory, { recursive: true });

  const loginResponse = await request.post(`${apiBaseUrl}/api/v1/auth/local/login`, {
    data: {
      username: administratorUsername,
      password,
    },
  });
  expect(loginResponse.status()).toBe(200);
  const tokens = (await loginResponse.json()) as TokenPair;
  expect(tokens.access_token).toBeTruthy();
  expect(tokens.refresh_token).toBeTruthy();

  await assertAccessTokenActive(request, tokens.access_token);

  const volumeBefore = postgresVolumeIdentity();
  const stateBefore = postgresStateSnapshot();
  expect(stateBefore).toContain("accounts_count=3");
  expect(stateBefore).toContain("membership_roles_count=3");
  expect(stateBefore).toMatch(/sessions_count=[1-9][0-9]*/);

  await recreateStack(request);
  const volumeAfterUpdate = postgresVolumeIdentity();
  const stateAfterUpdate = postgresStateSnapshot();
  expect(volumeAfterUpdate).toBe(volumeBefore);
  expect(stateAfterUpdate).toBe(stateBefore);
  await assertAccessTokenActive(request, tokens.access_token);

  await recreateStack(request);
  const volumeAfterRollback = postgresVolumeIdentity();
  const stateAfterRollback = postgresStateSnapshot();
  expect(volumeAfterRollback).toBe(volumeBefore);
  expect(stateAfterRollback).toBe(stateBefore);
  await assertAccessTokenActive(request, tokens.access_token);

  const logoutResponse = await request.post(`${apiBaseUrl}/api/v1/auth/local/logout`, {
    data: { refresh_token: tokens.refresh_token },
  });
  expect(logoutResponse.status()).toBe(204);

  const revokedResponse = await request.get(`${apiBaseUrl}/api/v1/auth/session`, {
    headers: {
      Authorization: `Bearer ${tokens.access_token}`,
      "X-Organization-ID": organizationId,
      Accept: "application/json",
    },
  });
  expect(revokedResponse.status()).toBe(401);

  writeFileSync(
    path.join(evidenceDirectory, "local-auth-persistence-evidence.json"),
    `${JSON.stringify(
      {
        postgres_volume_identity: volumeBefore,
        before: stateBefore.split("\n"),
        after_update_recreation: stateAfterUpdate.split("\n"),
        after_rollback_recreation: stateAfterRollback.split("\n"),
        access_session_survived_update: true,
        access_session_survived_rollback: true,
        post_logout_access_status: revokedResponse.status(),
      },
      null,
      2,
    )}\n`,
    { encoding: "utf-8", mode: 0o600 },
  );
});

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}
