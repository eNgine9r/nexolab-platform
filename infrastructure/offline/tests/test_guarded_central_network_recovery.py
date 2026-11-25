"""Hermetic #1462 tests: never calls Docker, systemctl, hardware or network writes."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "guarded-central-network-recovery.py"
GUARD = Path(__file__).resolve().parents[1] / "inspect-packaged-boot-network.py"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


module = load("nexolab_guarded_recovery", SOURCE)
boot = load("nexolab_boot_for_guard", GUARD)
DIGESTS = {
    role: frozenset({"sha256:" + format(i, "064x")})
    for i, role in enumerate(
        ("mqtt", "postgres", "object-storage", "telemetry-service", "dashboard", "device-agent"), 1
    )
}
BUNDLE = "site-validated-bundle-001"
SHA = "f" * 40


def fixture():
    d = {}
    for role, name in boot.CONTAINER_NAMES.items():
        source = boot.IMAGE_ROLES[role]
        port = {"dashboard": "3000/tcp", "mqtt": "1883/tcp",
                "minio": "9000/tcp", "telemetry-service": "8082/tcp"}.get(role)
        binding = [{"HostIp": "192.0.2.11", "HostPort": port.split("/")[0]}] if port else []
        d[name] = {
            "Image": next(iter(DIGESTS[source])),
            "Config": {"Labels": {"com.docker.compose.project":
                                     "nexolab-edge" if role == "device-agent" else "nexolab-central",
                                 "com.docker.compose.service": role}},
            "State": {"Running": True, "Health": {"Status": "healthy"}},
            "Mounts": (
                [{"Type": "volume", "Name": v} for v in boot.EXPECTED_VOLUMES.get(role, set())]
                + ([{"Type": "bind", "Destination": dest, "RW": False}
                    for dest in sorted(module.PROTECTED_AUTH_MOUNTS)]
                   if role == "telemetry-service" else [])
            ),
            "HostConfig": {"PortBindings": {port: binding} if port else {}},
            "NetworkSettings": {"Networks": {n: {} for n in boot.NETWORK_REQUIREMENTS[role]},
                                "Ports": {port: binding} if port else {}},
        }
    for names in boot.EXPECTED_VOLUMES.values():
        for name in names:
            d[name] = {"Name": name}
    for network in module.BOUNDED_NETWORKS:
        d[network] = {"Name": network, "Driver": "bridge",
                      "IPAM": {"Config": [{"Subnet": "172.19.0.0/16" if network == "nexolab-central"
                                            else "172.21.0.0/16"}]}}
    return d


def detached(objects, roles=("mqtt", "telemetry-service", "dashboard", "minio")):
    for role in roles:
        o = objects[boot.CONTAINER_NAMES[role]]
        o["NetworkSettings"]["Networks"] = {}
        o["NetworkSettings"]["Ports"] = {}


class ProtectedRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for n in ("worker.lock", "update-plane.lock"):
            (self.root / n).touch()
        (self.root / "current.json").write_text(json.dumps({
            "bundle_id": BUNDLE, "source_commit": SHA,
        }))
        self.o = fixture()
        self.actions: list[list[str]] = []
        self.approval = {"approval_bundle": BUNDLE, "approval_source": SHA, "is_root": lambda: True}
        self.cidrs = patch.object(boot, "inspect_host_cidr", return_value=None)
        self.authority = patch.object(boot, "validate_authority", return_value=DIGESTS)
        self.updatelocks = patch.object(boot, "check_update_locks", return_value=None)
        for mock in (self.cidrs, self.authority, self.updatelocks):
            mock.start()
            self.addCleanup(mock.stop)

    def inspect(self, name, kind="container"):
        return self.o[name]

    def reconnect(self, argv):
        self.actions.append(list(argv))
        name = argv[-1]
        network = argv[-2]
        obj = self.o[name]
        obj["NetworkSettings"]["Networks"][network] = {}
        expected = obj["HostConfig"]["PortBindings"]
        obj["NetworkSettings"]["Ports"].update(expected)

    def call(self, *, execute=False, **kw):
        return module.recover(
            self.root, mod=boot, inspect=self.inspect,
            connect=self.reconnect, enable=execute, **kw,
        )

    def test_healthy_returns_clean_without_any_docker_write(self):
        result = self.call()
        self.assertEqual(result["status"], "clean")
        self.assertEqual(self.actions, [])

    def test_reproduction_of_lost_four_networks_is_dry_run_only(self):
        detached(self.o)
        result = self.call()
        self.assertEqual(result["status"], "dry_run_only")
        self.assertFalse(result["mutation_performed"])
        self.assertEqual([x["role"] for x in result["planned"]],
                         ["mqtt", "mqtt", "telemetry-service", "telemetry-service",
                          "dashboard", "minio"])
        self.assertEqual(self.actions, [])

    def test_owner_approved_exact_release_reconnects_only_expected_networks(self):
        detached(self.o)
        result = self.call(execute=True, **self.approval)
        self.assertEqual(result["status"], "connection_restore_attempted")
        self.assertEqual(result["operation_count"], 6)
        self.assertEqual(len(self.actions), 6)
        self.assertTrue(all(x[:3] == ["docker", "network", "connect"] for x in self.actions))
        self.assertTrue(all(x[-2] in module.BOUNDED_NETWORKS for x in self.actions))
        self.assertTrue(all(x[-1] not in (boot.CONTAINER_NAMES["postgres"],
                                          boot.CONTAINER_NAMES["device-agent"]) for x in self.actions))
        self.assertEqual(module.create_plan(
            {**boot.diagnose_containers(DIGESTS, self.inspect), "status": "ready"},
            self.inspect, boot), [])

    def test_missing_explicit_authorization_does_not_write(self):
        detached(self.o)
        for kw in (
            {},
            {"approval_bundle": BUNDLE, "approval_source": SHA},
            {"approval_bundle": "wrong-approved-bundle", "approval_source": SHA, "is_root": lambda: True},
            {"approval_bundle": BUNDLE, "approval_source": "a" * 40, "is_root": lambda: True},
            {"approval_bundle": BUNDLE, "approval_source": SHA, "is_root": lambda: False},
        ):
            with self.subTest(kw=kw):
                r = self.call(execute=True, **kw)
                self.assertEqual(r["status"], "blocked")
                self.assertEqual(self.actions, [])

    def test_untrusted_image_stops_before_any_connect(self):
        detached(self.o)
        self.o[boot.CONTAINER_NAMES["mqtt"]]["Image"] = "sha256:" + "0" * 64
        r = self.call(execute=True, **self.approval)
        self.assertEqual(r["status"], "blocked")
        self.assertEqual(self.actions, [])

    def test_hardware_unhealthy_always_requires_manual_intervention(self):
        detached(self.o, roles=("dashboard",))
        self.o[boot.CONTAINER_NAMES["device-agent"]]["State"]["Health"]["Status"] = "unhealthy"
        r = self.call(execute=True, **self.approval)
        self.assertEqual(r["status"], "blocked")
        self.assertEqual(self.actions, [])

    def test_unknown_extra_network_cannot_be_manipulated(self):
        detached(self.o, roles=("dashboard",))
        self.o[boot.CONTAINER_NAMES["dashboard"]]["NetworkSettings"]["Networks"] = {"third-party": {}}
        r = self.call(execute=True, **self.approval)
        self.assertEqual(r["status"], "blocked")
        self.assertEqual(self.actions, [])

    def test_network_port_drift_without_missing_network_never_restarts_service(self):
        self.o[boot.CONTAINER_NAMES["dashboard"]]["NetworkSettings"]["Ports"] = {}
        r = self.call(execute=True, **self.approval)
        self.assertEqual(r["status"], "blocked")
        self.assertEqual(self.actions, [])

    def test_missing_or_writable_local_auth_key_mounts_fail_closed(self):
        detached(self.o, roles=("telemetry-service",))
        obj = self.o[boot.CONTAINER_NAMES["telemetry-service"]]
        binds = [m for m in obj["Mounts"] if m.get("Type") == "bind"]
        assert binds
        for changed in ("removed", "writable"):
            with self.subTest(changed=changed):
                original = list(obj["Mounts"])
                if changed == "removed":
                    obj["Mounts"] = [m for m in original if m is not binds[0]]
                else:
                    binds[0]["RW"] = True
                r = self.call(execute=True, **self.approval)
                self.assertEqual(r["status"], "blocked")
                self.assertEqual(self.actions, [])
                obj["Mounts"] = original
                binds[0]["RW"] = False

    def test_missing_volume_blocks_all(self):
        detached(self.o)
        self.o[boot.CONTAINER_NAMES["minio"]]["Mounts"] = []
        r = self.call(execute=True, **self.approval)
        self.assertEqual(r["status"], "blocked")
        self.assertEqual(self.actions, [])

    def test_unknown_docker_network_driver_blocks(self):
        detached(self.o, roles=("dashboard",))
        self.o["nexolab-central"]["Driver"] = "overlay"
        r = self.call(execute=True, **self.approval)
        self.assertEqual(r["status"], "blocked")
        self.assertEqual(self.actions, [])

    def test_network_cidr_guard_blocks_even_authorized_release(self):
        detached(self.o)
        self.cidrs.stop()
        with patch.object(boot, "inspect_host_cidr",
                          side_effect=boot.BootGuardError("physical_docker_cidr_not_safe")):
            r = self.call(execute=True, **self.approval)
        self.assertEqual(r["status"], "blocked")
        self.assertEqual(self.actions, [])

    def test_real_file_locks_do_not_self_deadlock_on_rechecked_preflight(self):
        # Do NOT mock check_update_locks: this covers real Linux flock
        # behavior with two separately opened file descriptions.
        detached(self.o, roles=("dashboard",))
        self.updatelocks.stop()
        r = self.call(execute=True, **self.approval)
        self.assertEqual(r["status"], "connection_restore_attempted", r)
        self.assertEqual(r["operation_count"], 1)
        self.assertEqual(len(self.actions), 1)
        self.assertEqual(self.actions[0][-2:], ["nexolab-central", "nexolab-central-dashboard-1"])

    def test_protected_lock_already_held_blocks_execution(self):
        import fcntl
        detached(self.o, roles=("dashboard",))
        with (self.root / "worker.lock").open("rb") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            r = self.call(execute=True, **self.approval)
        self.assertEqual(r["status"], "blocked")
        self.assertEqual(self.actions, [])

    def test_partial_mutation_is_never_reported_as_no_mutation(self):
        detached(self.o, roles=("mqtt", "dashboard"))
        def fail_after_first(argv):
            if len(self.actions) >= 1:
                raise module.RecoveryBlocked("synthetic_second_operation_failed")
            self.reconnect(argv)
        r = module.recover(
            self.root, mod=boot, inspect=self.inspect, connect=fail_after_first,
            enable=True, **self.approval,
        )
        self.assertEqual(r["status"], "blocked_partial_mutation")
        self.assertTrue(r["mutation_performed"])
        self.assertEqual(r["operations_completed"], 1)

    def test_disallowed_docker_subcommands_rejected(self):
        for cmd in (
            ["docker", "compose", "down"],
            ["docker", "network", "rm", "nexolab-central"],
            ["docker", "container", "restart", "postgres"],
        ):
            with self.assertRaises(module.RecoveryBlocked):
                module.execute_docker(cmd)


if __name__ == "__main__":
    unittest.main()
