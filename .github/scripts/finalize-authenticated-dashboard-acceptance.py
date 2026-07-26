from pathlib import Path

# One-shot branch finalizer. The workflow removes this file after formatting.
root = Path(__file__).resolve().parents[2]

e2e_path = root / "e2e/authenticated-dashboard.production.e2e.ts"
e2e = e2e_path.read_text()
marker = '''        )}\n`,
      );
    } finally {
'''
replacement = '''        )}\n`,
      );

      await page.getByRole("button", { name: "Вийти з NEXOLAB" }).click();
      await expect(page).toHaveURL(/\\/login$/);
      const clearedCredentials = await page.evaluate(() => ({
        accessToken: window.sessionStorage.getItem("nexolab.acceptance.access-token"),
        organizationId: window.sessionStorage.getItem("nexolab.acceptance.organization-id"),
        selectedOrganizationId: window.localStorage.getItem("nexolab.selectedOrganizationId"),
      }));
      expect(clearedCredentials).toEqual({
        accessToken: null,
        organizationId: null,
        selectedOrganizationId: null,
      });
      writeFileSync(
        path.join(evidenceDirectory, "logout-state.json"),
        `${JSON.stringify(clearedCredentials, null, 2)}\\n`,
      );
    } finally {
'''
if marker not in e2e:
    raise SystemExit("dashboard acceptance logout insertion marker not found")
e2e_path.write_text(e2e.replace(marker, replacement, 1))

docs_path = root / "docs/authenticated-live-telemetry.md"
docs = docs_path.read_text()
section = '''
## Controlled browser acceptance

The `Authenticated Dashboard Acceptance` workflow builds the production Next.js application and starts an isolated FastAPI, PostgreSQL, MinIO and Mosquitto stack. It seeds a verified viewer membership plus real telemetry records, then proves anonymous blocking, authenticated latest/history REST requests, API-derived inventory, first-message WebSocket authentication, a live MQTT update, one-hour range switching, cross-organization denial and logout credential cleanup.

Evidence contains only sanitized origins, request-header presence flags, WebSocket message key names, PostgreSQL rows, screenshots and traces. JWT values are never written to URLs or evidence files.
'''
if "## Controlled browser acceptance" not in docs:
    docs_path.write_text(docs.rstrip() + "\n" + section)
