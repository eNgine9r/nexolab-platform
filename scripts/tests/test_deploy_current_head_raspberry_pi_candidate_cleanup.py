from __future__ import annotations

import os
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "scripts" / "deploy-current-head-raspberry-pi.sh"
LIVENESS = ROOT / "scripts" / "lib" / "frontend-candidate-liveness.sh"


def _extract_cleanup_function(text: str) -> str:
    start = text.index("cleanup_frontend_candidate() {")
    end = text.index("\non_exit() {", start)
    return text[start:end].rstrip()


class RaspberryPiCandidateCleanupTests(unittest.TestCase):
    def test_candidate_runs_in_dedicated_process_group_and_all_exits_cleanup(self) -> None:
        text = DEPLOY.read_text(encoding="utf-8")
        self.assertIn('FRONTEND_CANDIDATE_PID=""', text)
        self.assertIn('FRONTEND_CANDIDATE_PGID=""', text)
        self.assertIn('source "$SCRIPT_DIR/lib/frontend-candidate-liveness.sh"', text)
        self.assertIn('trap on_exit EXIT', text)
        self.assertIn('exec setsid env \\', text)
        self.assertIn('FRONTEND_CANDIDATE_ACTUAL_PGID="$(ps -o pgid=', text)
        self.assertIn('FRONTEND_CANDIDATE_PGID="$FRONTEND_CANDIDATE_ACTUAL_PGID"', text)
        self.assertNotIn('FRONTEND_CANDIDATE_PGID="$FRONTEND_CANDIDATE_PID"', text)
        self.assertIn('kill -TERM -- "-$pgid"', text)
        self.assertIn('kill -KILL -- "-$pgid"', text)
        self.assertIn('nexolab_frontend_candidate_group_has_live_processes "$pgid"', text)
        self.assertNotIn("pkill", text)

        handshake = text.index('FRONTEND_CANDIDATE_ACTUAL_PGID="$(ps -o pgid=')
        ready = text.index("FRONTEND_CANDIDATE_READY=false")
        self.assertLess(handshake, ready)

        cleanup = text.index("if ! cleanup_frontend_candidate; then")
        port_check = text.index(
            'fail "frontend candidate cleanup left verification port in use', cleanup
        )
        backend_start = text.index('log "Starting central backend, MinIO and observability"')
        self.assertLess(cleanup, port_check)
        self.assertLess(port_check, backend_start)

    def test_zombie_only_group_is_not_classified_as_live(self) -> None:
        helper = LIVENESS.read_text(encoding="utf-8")
        script = f"""
set -euo pipefail
{helper}
ps() {{
  cat <<'EOF'
 4242 Z
 4242 Z+
 4343 S
EOF
}}
if nexolab_frontend_candidate_group_has_live_processes 4242; then
  exit 1
fi
nexolab_frontend_candidate_group_has_live_processes 4343
"""
        result = subprocess.run(
            ["bash", "-c", script],
            cwd=ROOT,
            env=os.environ.copy(),
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cleanup_falls_back_to_exact_pid_before_group_handshake(self) -> None:
        text = DEPLOY.read_text(encoding="utf-8")
        cleanup_function = _extract_cleanup_function(text)
        helper = LIVENESS.read_text(encoding="utf-8")
        script = f"""
set -euo pipefail
log() {{ :; }}
{helper}
{cleanup_function}
production_pid=""
candidate_pid=""
cleanup_fixture() {{
  if [[ -n "$production_pid" ]]; then
    kill "$production_pid" >/dev/null 2>&1 || true
    wait "$production_pid" >/dev/null 2>&1 || true
  fi
  if [[ -n "$candidate_pid" ]]; then
    kill "$candidate_pid" >/dev/null 2>&1 || true
    wait "$candidate_pid" >/dev/null 2>&1 || true
  fi
}}
trap cleanup_fixture EXIT
python3 -c 'import time; time.sleep(30)' &
production_pid=$!
python3 -c 'import time; time.sleep(30)' &
candidate_pid=$!
FRONTEND_CANDIDATE_PID="$candidate_pid"
FRONTEND_CANDIDATE_PGID=""
cleanup_frontend_candidate
[[ -z "$FRONTEND_CANDIDATE_PID" ]]
[[ -z "$FRONTEND_CANDIDATE_PGID" ]]
! kill -0 "$candidate_pid" >/dev/null 2>&1
kill -0 "$production_pid" >/dev/null 2>&1
candidate_pid=""
"""
        result = subprocess.run(
            ["bash", "-c", script],
            cwd=ROOT,
            env=os.environ.copy(),
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_exact_candidate_process_group_cleanup_preserves_unrelated_process(self) -> None:
        text = DEPLOY.read_text(encoding="utf-8")
        cleanup_function = _extract_cleanup_function(text)
        helper = LIVENESS.read_text(encoding="utf-8")
        script = f"""
set -euo pipefail
log() {{ :; }}
{helper}
{cleanup_function}
production_pid=""
candidate_pid=""
cleanup_fixture() {{
  if [[ -n "$production_pid" ]]; then
    kill "$production_pid" >/dev/null 2>&1 || true
    wait "$production_pid" >/dev/null 2>&1 || true
  fi
  if [[ -n "$candidate_pid" ]]; then
    kill -KILL -- "-$candidate_pid" >/dev/null 2>&1 || true
    wait "$candidate_pid" >/dev/null 2>&1 || true
  fi
}}
trap cleanup_fixture EXIT
python3 -c 'import time; time.sleep(30)' &
production_pid=$!
setsid python3 -c 'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); time.sleep(30)' &
candidate_pid=$!
sleep 0.2
candidate_pgid="$(ps -o pgid= -p "$candidate_pid" | tr -d ' ')"
[[ "$candidate_pgid" == "$candidate_pid" ]]
FRONTEND_CANDIDATE_PID="$candidate_pid"
FRONTEND_CANDIDATE_PGID="$candidate_pgid"
cleanup_frontend_candidate
[[ -z "$FRONTEND_CANDIDATE_PID" ]]
[[ -z "$FRONTEND_CANDIDATE_PGID" ]]
if nexolab_frontend_candidate_group_has_live_processes "$candidate_pgid"; then
  exit 1
fi
kill -0 "$production_pid" >/dev/null 2>&1
cleanup_frontend_candidate
kill -0 "$production_pid" >/dev/null 2>&1
candidate_pid=""
"""
        result = subprocess.run(
            ["bash", "-c", script],
            cwd=ROOT,
            env=os.environ.copy(),
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
