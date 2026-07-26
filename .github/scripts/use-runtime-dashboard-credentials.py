from pathlib import Path

root = Path(__file__).resolve().parents[2]

for relative in (
    "src/hooks/use-dashboard-security.ts",
    "src/hooks/use-dashboard-telemetry.ts",
):
    path = root / relative
    content = path.read_text(encoding="utf-8")
    content = content.replace("createSupabaseCredentialProvider", "createRuntimeCredentialProvider")
    path.write_text(content, encoding="utf-8")

path = root / "src/hooks/use-dashboard-security.test.ts"
content = path.read_text(encoding="utf-8")
content = content.replace("createSupabaseCredentialProvider: () => authState.credentials", "createRuntimeCredentialProvider: () => authState.credentials")
path.write_text(content, encoding="utf-8")
