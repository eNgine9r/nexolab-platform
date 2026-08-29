from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "deploy-edge-sqlite-snapshot.py"
DEPLOY = ROOT / "scripts" / "deploy-current-head-raspberry-pi.sh"
SPEC = importlib.util.spec_from_file_location("edge_snapshot", HELPER)
assert SPEC and SPEC.loader
edge_snapshot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(edge_snapshot)

DEPLOYED = "a" * 40
TARGET = "b" * 40
EVIDENCE_ID = "20260829T210000Z"
DEVICE_AGENT_IMAGE_ID = "sha256:" + "d" * 64


def create_database(
    path: Path,
    *,
    revision: int = 18,
    queue_count: int = 2,
    telemetry_sequence: int = 42,
) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE acquisition_registry_state (
                singleton INTEGER PRIMARY KEY,
                revision INTEGER NOT NULL
            );
            CREATE TABLE outbound_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload TEXT NOT NULL
            );
            CREATE TABLE node_stream_sequences (
                stream TEXT PRIMARY KEY,
                last_sequence INTEGER NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO acquisition_registry_state(singleton, revision) VALUES (1, ?)",
            (revision,),
        )
        connection.executemany(
            "INSERT INTO outbound_queue(payload) VALUES (?)",
            [(f"payload-{index}",) for index in range(queue_count)],
        )
        connection.execute(
            "INSERT INTO node_stream_sequences(stream, last_sequence) VALUES ('telemetry', ?)",
            (telemetry_sequence,),
        )
        connection.commit()
    finally:
        connection.close()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class EdgeSQLiteSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "edge.db"
        self.snapshot = self.root / "edge-sqlite-pre-cutover.db"
        self.metadata = self.root / "edge-sqlite-pre-cutover.json"
        create_database(self.source)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def capture_args(self) -> argparse.Namespace:
        return argparse.Namespace(
            source=self.source,
            snapshot=self.snapshot,
            metadata=self.metadata,
            deployed_source=DEPLOYED,
            target_source=TARGET,
            deployment_evidence_id=EVIDENCE_ID,
            deployed_device_agent_image_id=DEVICE_AGENT_IMAGE_ID,
        )

    def restore_args(self, destination: Path, **overrides: str) -> argparse.Namespace:
        values = {
            "snapshot": self.snapshot,
            "metadata": self.metadata,
            "destination": destination,
            "expected_deployed_source": DEPLOYED,
            "expected_target_source": TARGET,
            "expected_deployment_evidence_id": EVIDENCE_ID,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_live_backup_is_consistent_and_records_sanitized_integrity_evidence(self) -> None:
        writer = sqlite3.connect(self.source, isolation_level=None)
        try:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("INSERT INTO outbound_queue(payload) VALUES ('uncommitted-secret')")
            document = edge_snapshot.capture(self.capture_args())
            writer.execute("ROLLBACK")
        finally:
            writer.close()

        self.assertEqual(document["source_quick_check"], "ok")
        self.assertEqual(document["snapshot_quick_check"], "ok")
        self.assertEqual(document["registry_revision"], 18)
        self.assertEqual(document["outbound_queue_count"], 2)
        self.assertEqual(document["outbound_queue_high_water"], 2)
        self.assertEqual(document["node_stream_sequences"], {"telemetry": 42})
        self.assertEqual(document["deployed_device_agent_image_id"], DEVICE_AGENT_IMAGE_ID)
        self.assertEqual(document["sha256"], sha256(self.snapshot))
        self.assertEqual(document["bytes"], self.snapshot.stat().st_size)
        self.assertNotIn("payload", json.dumps(document).lower())
        connection = sqlite3.connect(self.snapshot)
        try:
            self.assertEqual(connection.execute("PRAGMA quick_check").fetchone(), ("ok",))
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM outbound_queue").fetchone(), (2,))
        finally:
            connection.close()

    def test_corrupt_source_is_rejected_without_partial_evidence(self) -> None:
        self.source.write_bytes(b"not a sqlite database")
        with self.assertRaises(edge_snapshot.SnapshotError):
            edge_snapshot.capture(self.capture_args())
        self.assertFalse(self.snapshot.exists())
        self.assertFalse(self.metadata.exists())

    def test_corrupt_snapshot_is_rejected_before_destination_change(self) -> None:
        edge_snapshot.capture(self.capture_args())
        destination = self.root / "destination.db"
        create_database(destination, revision=99, queue_count=2)
        before = destination.read_bytes()
        self.snapshot.write_bytes(self.snapshot.read_bytes() + b"corruption")

        with self.assertRaisesRegex(edge_snapshot.SnapshotError, "byte size"):
            edge_snapshot.restore(self.restore_args(destination))
        self.assertEqual(destination.read_bytes(), before)

    def test_wrong_source_and_evidence_are_rejected(self) -> None:
        edge_snapshot.capture(self.capture_args())
        destination = self.root / "destination.db"
        create_database(destination, revision=99, queue_count=2)
        cases = (
            {"expected_deployed_source": "c" * 40},
            {"expected_target_source": "c" * 40},
            {"expected_deployment_evidence_id": "20260829T220000Z"},
        )
        for override in cases:
            with self.subTest(override=override):
                with self.assertRaises(edge_snapshot.SnapshotError):
                    edge_snapshot.restore(self.restore_args(destination, **override))

    def test_restore_is_atomic_exact_and_preserves_destination_ownership_contract(self) -> None:
        document = edge_snapshot.capture(self.capture_args())
        destination = self.root / "destination.db"
        create_database(destination, revision=99, queue_count=2)
        destination.chmod(0o640)
        old_inode = destination.stat().st_ino

        result = edge_snapshot.restore(self.restore_args(destination))

        self.assertNotEqual(destination.stat().st_ino, old_inode)
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o640)
        self.assertEqual(sha256(destination), document["sha256"])
        self.assertEqual(result["registry_revision"], 18)
        self.assertEqual(result["outbound_queue_count"], 2)
        self.assertEqual(result["kind"], "nexolab-edge-sqlite-restore-result")
        self.assertEqual(result["deployed_source"], DEPLOYED)
        connection = sqlite3.connect(destination)
        try:
            self.assertEqual(connection.execute("PRAGMA quick_check").fetchone(), ("ok",))
            self.assertEqual(
                connection.execute(
                    "SELECT revision FROM acquisition_registry_state WHERE singleton = 1"
                ).fetchone(),
                (18,),
            )
        finally:
            connection.close()
        for suffix in ("-wal", "-shm", "-journal"):
            self.assertFalse(destination.with_name(destination.name + suffix).exists())

    def test_restore_rejects_sidecars_instead_of_discarding_newer_state(self) -> None:
        edge_snapshot.capture(self.capture_args())
        destination = self.root / "destination.db"
        create_database(destination, revision=99, queue_count=2)
        sidecar = destination.with_name(destination.name + "-wal")
        sidecar.write_text("newer state", encoding="utf-8")
        before = destination.read_bytes()

        with self.assertRaisesRegex(edge_snapshot.SnapshotError, "refusing to discard newer state"):
            edge_snapshot.restore(self.restore_args(destination))
        self.assertEqual(destination.read_bytes(), before)
        self.assertEqual(sidecar.read_text(encoding="utf-8"), "newer state")

    def test_restore_rejects_advanced_queue_or_stream_sequence(self) -> None:
        edge_snapshot.capture(self.capture_args())
        for queue_count, sequence in ((3, 42), (2, 43)):
            destination = self.root / f"destination-{queue_count}-{sequence}.db"
            create_database(
                destination,
                revision=19,
                queue_count=queue_count,
                telemetry_sequence=sequence,
            )
            before = destination.read_bytes()

            with self.assertRaisesRegex(edge_snapshot.SnapshotError, "advanced after snapshot"):
                edge_snapshot.restore(self.restore_args(destination))
            self.assertEqual(destination.read_bytes(), before)

        destination = self.root / "destination-drained-queue.db"
        create_database(destination, revision=19, queue_count=2)
        connection = sqlite3.connect(destination)
        try:
            connection.execute("INSERT INTO outbound_queue(payload) VALUES ('newer')")
            connection.execute("DELETE FROM outbound_queue WHERE id = 3")
            connection.commit()
        finally:
            connection.close()
        before = destination.read_bytes()
        with self.assertRaisesRegex(edge_snapshot.SnapshotError, "advanced after snapshot"):
            edge_snapshot.restore(self.restore_args(destination))
        self.assertEqual(destination.read_bytes(), before)

    def test_restore_requires_an_existing_destination(self) -> None:
        edge_snapshot.capture(self.capture_args())
        with self.assertRaisesRegex(edge_snapshot.SnapshotError, "existing edge SQLite"):
            edge_snapshot.restore(self.restore_args(self.root / "missing.db"))


class EdgeSQLiteDeploymentContractTests(unittest.TestCase):
    def test_snapshot_precedes_runtime_mutation_and_restore_is_never_implicit(self) -> None:
        text = DEPLOY.read_text(encoding="utf-8")
        capture_call = text.index("capture_edge_sqlite_snapshot\n")
        mutation = text.index("printf 'source=%s\\nstarted_at=%s\\n'")
        restore_call = text.index("restore_edge_sqlite_snapshot\n")
        restore_mode = text.index('if [[ -n "$RESTORE_EDGE_SNAPSHOT_DIR" ]]')
        normal_deployment = text.index('FRONTEND_ARTIFACT_DIR=""')
        self.assertLess(capture_call, mutation)
        self.assertEqual(
            text[capture_call:mutation].strip(),
            "capture_edge_sqlite_snapshot",
        )
        self.assertLess(restore_mode, restore_call)
        self.assertLess(restore_call, normal_deployment)
        self.assertNotIn("restore_edge_sqlite_snapshot", text[normal_deployment:mutation])
        self.assertIn("Device Agent remains stopped", text)

    def test_existing_edge_resolves_deployed_source_for_normal_current_main_mode(self) -> None:
        text = DEPLOY.read_text(encoding="utf-8")
        start = text.index("capture_edge_sqlite_snapshot()")
        end = text.index("\ncapture_edge_sqlite_snapshot\n", start)
        capture = text[start:end]
        resolve = capture.index("resolve_latest_deployment_evidence")
        final_guard = capture.index("exact deployed source authority is required", resolve)
        self.assertLess(resolve, final_guard)
        self.assertIn('deployed_source="$VERIFIED_DEPLOYED_SOURCE"', capture)

    def test_helper_is_staged_before_historical_checkout(self) -> None:
        text = DEPLOY.read_text(encoding="utf-8")
        stage = text.index(
            'install -m 0500 "$SCRIPT_DIR/deploy-edge-sqlite-snapshot.py" '
            '"$EDGE_SNAPSHOT_HELPER"'
        )
        checkout = text.index('git switch --detach "$TARGET_HEAD"', stage)
        capture = text.index("/evidence/deploy-edge-sqlite-snapshot.py capture")
        self.assertLess(stage, checkout)
        self.assertLess(checkout, capture)

    def test_running_device_agent_is_rejected_before_docker_restore(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            evidence = repo / "runtime" / "deployments" / EVIDENCE_ID
            evidence.mkdir(parents=True)
            (evidence / "edge-sqlite-pre-cutover.db").write_bytes(b"fixture")
            (evidence / "edge-sqlite-pre-cutover.json").write_text("{}\n", encoding="utf-8")
            bin_dir = root / "bin"
            bin_dir.mkdir()
            calls = root / "docker-calls.txt"
            docker = bin_dir / "docker"
            docker.write_text(
                "#!/usr/bin/env bash\n"
                f"printf '%s\\n' \"$*\" >> {calls}\n"
                "if [[ \"$1 $2\" == 'ps -aq' ]]; then echo agent-1; exit 0; fi\n"
                "if [[ \"$1\" == inspect && \"$*\" == *State.Running* ]]; then echo true; exit 0; fi\n"
                "exit 1\n",
                encoding="utf-8",
            )
            docker.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["NEXOLAB_REPO"] = str(repo)
            env["XDG_RUNTIME_DIR"] = str(root)
            result = subprocess.run(
                [
                    "bash",
                    str(DEPLOY),
                    "--restore-edge-snapshot",
                    str(evidence),
                    "--expected-deployed-source",
                    DEPLOYED,
                    "--expected-target-source",
                    TARGET,
                ],
                cwd=ROOT,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must already be stopped", result.stderr)
            self.assertNotIn("run --rm", calls.read_text(encoding="utf-8"))

    def test_restore_selects_previous_image_only_after_database_replacement(self) -> None:
        text = DEPLOY.read_text(encoding="utf-8")
        start = text.index("restore_edge_sqlite_snapshot()")
        end = text.index('\nif [[ -n "$RESTORE_EDGE_SNAPSHOT_DIR" ]]', start)
        restore = text[start:end]
        tag = restore.index(
            'docker image tag "$deployed_device_agent_image_id" '
            "nexolab-device-agent:local"
        )
        replace = restore.index("docker run --rm --user 0:0")
        publish_result = restore.index('mv -- "$result_tmp" "$result_file"')
        self.assertLess(replace, tag)
        self.assertLess(tag, publish_result)

        runbook = (
            ROOT / "docs" / "operations" / "edge-sqlite-cutover-recovery.md"
        ).read_text(encoding="utf-8")
        self.assertIn("up -d --force-recreate device-agent", runbook)
        self.assertIn("deployed_device_agent_image_id", runbook)


if __name__ == "__main__":
    unittest.main()
