from pathlib import Path

root = Path(__file__).resolve().parents[2]
path = root / "e2e/authenticated-dashboard.production.e2e.ts"
content = path.read_text()

old_init = '''    ({ accessToken, organization }) => {
      window.sessionStorage.setItem("nexolab.acceptance.access-token", accessToken);
'''
new_init = '''    ({ accessToken, organization }) => {
      if (window.location.protocol === "about:") return;
      window.sessionStorage.setItem("nexolab.acceptance.access-token", accessToken);
'''
if old_init not in content:
    raise SystemExit("dashboard acceptance init-script marker not found")
content = content.replace(old_init, new_init, 1)

old_expectation = '''      await expect(page.getByText("NEXOLAB Dashboard Acceptance", { exact: true })).toBeVisible();
'''
new_expectation = '''      await expect(page.getByLabel(/Організація/)).toHaveValue(organizationId);
'''
if old_expectation not in content:
    raise SystemExit("dashboard organization locator marker not found")
content = content.replace(old_expectation, new_expectation, 1)

path.write_text(content)
