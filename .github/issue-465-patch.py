from __future__ import annotations

import subprocess

SOURCE_COMMIT = "e72ba8267658dc78484b991545fa9a20edf9cbbd"
WORKFLOW_PATH = ".github/workflows/issue-465-implementation.yml"
BASE_INDENT = "          "

workflow = subprocess.check_output(
    ["git", "show", f"{SOURCE_COMMIT}:{WORKFLOW_PATH}"],
    text=True,
)
start_marker = "          python - <<'PY'\n"
end_marker = "\n          PY\n"
start = workflow.index(start_marker) + len(start_marker)
end = workflow.index(end_marker, start)
block = workflow[start:end]
source = "\n".join(
    line[len(BASE_INDENT) :] if line.startswith(BASE_INDENT) else line
    for line in block.splitlines()
)
exec(compile(source, "issue-465-embedded-patch.py", "exec"))
