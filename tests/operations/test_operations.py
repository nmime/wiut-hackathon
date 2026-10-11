"""Failure-path tests for production backup publication, retention and identity."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

OPERATIONS = Path(__file__).resolve().parents[2] / "scripts" / "operations"
sys.path.insert(0, str(OPERATIONS))
import backup
import check_health
import common
import verify_backup


class ProductionOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.backups = self.root / "backups"
        self.state = self.root / "state"
        self.backups.mkdir()
        self.environment = self.root / ".env.production"
        self.environment.write_text(
            "DOMAIN=example.com\nPOSTGRES_PASSWORD=" + "a" * 64 + "\n"
        )
        self.environment.chmod(0o600)
        self.patches = [
            patch.object(common, "ROOT", self.root),
            patch.object(common, "ENVIRONMENT", self.environment),
            patch.object(backup, "ROOT", self.root),
            patch.object(backup, "BACKUPS", self.backups),
            patch.object(backup, "ENVIRONMENT", self.environment),
            patch.object(backup, "STATE", self.state),
            patch.object(check_health, "ROOT", self.root),
            patch.object(check_health, "STATE", self.state),
            patch.object(check_health, "BACKUPS", self.backups),
        ]
        for item in self.patches:
            item.start()
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(lambda: [item.stop() for item in reversed(self.patches)])

    def fake_run(self, arguments, *, stdout=None, stdin=None, timeout=60):
        if "pg_dump" in arguments:
            stdout.write(b"PGDMP-test-fixture")
        if "images" in arguments:
            return b"a" * 64 + b"\n"
        if arguments[:4] == ["docker", "volume", "ls", "--quiet"]:
            return b"flowcredit_ml-audit\nflowcredit_teammate-ml-audit\n"
        return b""

    def fake_snapshot(self, image, volume, target):
        row = b'{"event":"assessment_completed"}\n'
        target.write_bytes(row)
        return {
            "snapshot_size_bytes": len(row),
            "captured_bytes": len(row),
            "records": 1,
            "omitted_partial_tail_bytes": 0,
        }

    def old_archive(
        self, name="flowcredit-scheduled-20200101T000000Z-abcdef1234567890.tar.gz"
    ):
        path = self.backups / name
        path.write_bytes(b"old archive")
        old = time.time() - 30 * 86400
        os.utime(path, (old, old))
        return path

    def test_database_failure_never_snapshots_or_retains(self):
        old = self.old_archive()
        with (
            patch.object(
                backup, "run", side_effect=common.OperationError("dump failed")
            ),
            patch.object(backup, "snapshot_audit") as snapshot,
            patch.object(backup, "retain") as retention,
            self.assertRaises(common.OperationError),
        ):
            backup.create_backup(14)
        snapshot.assert_not_called()
        retention.assert_not_called()
        self.assertTrue(old.exists())
        self.assertEqual(list(self.backups.iterdir()), [old])

    def test_audit_failure_never_publishes_or_retains(self):
        old = self.old_archive()
        with (
            patch.object(backup, "run", side_effect=self.fake_run),
            patch.object(
                backup,
                "snapshot_audit",
                side_effect=common.OperationError("audit failed"),
            ),
            patch.object(backup, "retain") as retention,
            self.assertRaises(common.OperationError),
        ):
            backup.create_backup(14)
        retention.assert_not_called()
        self.assertEqual(list(self.backups.iterdir()), [old])

    def test_archive_verification_failure_preserves_existing_backups(self):
        old = self.old_archive()
        with (
            patch.object(backup, "run", side_effect=self.fake_run),
            patch.object(backup, "snapshot_audit", side_effect=self.fake_snapshot),
            patch.object(
                backup,
                "validate_archive",
                side_effect=common.OperationError("checksum failed"),
            ),
            patch.object(backup, "retain") as retention,
            self.assertRaises(common.OperationError),
        ):
            backup.create_backup(14)
        retention.assert_not_called()
        self.assertEqual(list(self.backups.iterdir()), [old])

    def test_success_hashes_both_audits_and_private_config_before_retention(self):
        old = self.old_archive()
        unrelated = self.old_archive("manual-important.dump")
        with (
            patch.object(backup, "run", side_effect=self.fake_run),
            patch.object(backup, "snapshot_audit", side_effect=self.fake_snapshot),
        ):
            archive = backup.create_backup(14)
        manifest = backup.validate_archive(archive)
        self.assertEqual(
            set(manifest["files"]),
            {
                "database.dump",
                ".env.production",
                "ml-audit.jsonl",
                "teammate-ml-audit.jsonl",
            },
        )
        self.assertEqual(
            manifest["files"][".env.production"], common.checksum(self.environment)
        )
        self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.backups.stat().st_mode & 0o777, 0o700)
        self.assertEqual(
            (self.state / "backup-status.json").stat().st_mode & 0o777, 0o600
        )
        self.assertFalse(old.exists())
        self.assertTrue(unrelated.exists())

    def test_retention_does_not_follow_or_remove_symlinks(self):
        target = self.old_archive("operator-file.dump")
        link = (
            self.backups
            / "flowcredit-scheduled-20200101T000000Z-abcdef1234567890.tar.gz"
        )
        link.symlink_to(target)
        self.assertEqual(backup.retain(self.backups, 14, time.time()), 0)
        self.assertTrue(link.is_symlink())
        self.assertTrue(target.exists())

    def test_snapshot_keeps_exact_complete_prefix_and_reports_partial_tail(self):
        path = self.root / "audit.jsonl"
        prefix = b'{"event":"one"}\n{"event":"two"}\n'
        path.write_bytes(prefix + b'{"event":"in-flight')
        code = backup.SNAPSHOT_CODE.replace(
            "'/snapshot/requests.jsonl'", repr(str(path))
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, check=True
        )
        self.assertEqual(result.stdout, prefix)
        metadata = json.loads(result.stderr)
        self.assertEqual(metadata["records"], 2)
        self.assertEqual(
            metadata["omitted_partial_tail_bytes"], len(b'{"event":"in-flight')
        )

    def test_snapshot_rejects_malformed_complete_records(self):
        path = self.root / "audit.jsonl"
        path.write_bytes(b'{"event":"one"}\nnot JSON\n')
        code = backup.SNAPSHOT_CODE.replace(
            "'/snapshot/requests.jsonl'", repr(str(path))
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, check=False
        )
        self.assertNotEqual(result.returncode, 0)

    def test_archive_rejects_links_or_unexpected_paths(self):
        archive = self.root / "bad.tar.gz"
        with tarfile.open(archive, "w:gz") as output:
            member = tarfile.TarInfo("../database.dump")
            member.mode = 0o600
            member.size = 1
            output.addfile(member, io.BytesIO(b"x"))
        with self.assertRaises(common.OperationError):
            backup.validate_archive(archive)

    def test_model_identity_change_is_detected_before_explicit_acceptance(self):
        self.state.mkdir()
        old = {"ml": {"model_version": "v1", "model_artifact_sha256": "a" * 64}}
        (self.state / "model-baseline.json").write_text(json.dumps({"models": old}))
        newest = self.old_archive()
        os.utime(newest, None)
        (self.state / "backup-status.json").write_text('{"status":"ok"}')
        current = {"model_version": "v2", "model_artifact_sha256": "b" * 64}

        def monitor_run(arguments, **kwargs):
            if "ps" in arguments:
                return b"" if arguments[-1] == "teammate-ml" else b"a" * 64
            if "inspect" in arguments:
                return b"running healthy"
            if "is-active" in arguments:
                return b"active"
            if "-checkhost" in arguments:
                return b"Hostname example.com does match certificate\n"
            return b""

        with (
            patch.object(check_health, "run", side_effect=monitor_run),
            patch.object(check_health, "model_health", return_value=current),
            patch.object(check_health, "database_health", return_value=True),
            patch.object(check_health, "http_status", return_value=(401, b"")),
            patch.object(
                check_health.shutil, "disk_usage", return_value=shutil_usage()
            ),
        ):
            observation = check_health.observe()
            self.assertEqual(observation["status"], "failed")
            self.assertEqual(observation["checks"]["scorer_baseline"], "failed")
            accepted = check_health.observe(accept_models=True)
            self.assertEqual(accepted["status"], "ok")
            self.assertEqual(
                json.loads((self.state / "model-baseline.json").read_text())["models"],
                {"ml": current},
            )

    def test_unchanged_health_refresh_is_quiet(self):
        observation = {"status": "ok", "checks": {"disk": "ok"}, "observed_at": "first"}
        with contextlib.redirect_stdout(io.StringIO()) as first:
            check_health.publish(observation)
        self.assertIn('"status": "ok"', first.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as second:
            check_health.publish({**observation, "observed_at": "second"})
        self.assertEqual(second.getvalue(), "")
        self.assertEqual(
            json.loads((self.state / "health-status.json").read_text())["observed_at"],
            "second",
        )

    def test_certificate_hostname_requires_positive_output_even_on_exit_zero(self):
        # common.run returns stdout when the subprocess exit status is zero.
        # Both positive and negative `openssl x509 -checkhost` responses can
        # reach this branch; a successful command alone does not prove a match.
        for output, expected in (
            (b"Hostname example.com does match certificate\n", True),
            (b"Hostname example.com does NOT match certificate\n", False),
            (b"Hostname other.example.com does match certificate\n", False),
            (b"", False),
        ):
            with (
                self.subTest(output=output),
                patch.object(check_health, "run", return_value=output),
            ):
                self.assertEqual(
                    check_health.certificate_hostname_matches(
                        "certificate.pem", "example.com"
                    ),
                    expected,
                )

    def test_model_health_preserves_only_actual_validated_identity_fields(self):
        health = {
            "status": "ok",
            "model_version": "teammate-v1",
            "model_artifact_sha256": "a" * 64,
            "source_archive_sha256": "b" * 64,
            "bridge_source_sha256": "c" * 64,
            "provenance": "No real borrower performance claim",
        }
        with patch.object(common, "run", return_value=json.dumps(health).encode()):
            identity = common.model_health("teammate-ml")
        self.assertEqual(
            set(identity),
            {
                "model_version",
                "model_artifact_sha256",
                "source_archive_sha256",
                "bridge_source_sha256",
            },
        )
        del health["source_archive_sha256"]
        del health["bridge_source_sha256"]
        with patch.object(common, "run", return_value=json.dumps(health).encode()):
            self.assertEqual(
                set(common.model_health("ml")),
                {"model_version", "model_artifact_sha256"},
            )
        health["bridge_source_sha256"] = "invalid"
        with (
            patch.object(common, "run", return_value=json.dumps(health).encode()),
            self.assertRaises(common.OperationError),
        ):
            common.model_health("teammate-ml")

    def test_restore_uses_generated_temporary_target_and_always_drops_it(self):
        calls = []
        fixture = self.root / "fixture.tar.gz"
        with tarfile.open(fixture, "w:gz") as archive:
            member = tarfile.TarInfo("database.dump")
            member.size = 5
            archive.addfile(member, io.BytesIO(b"dummy"))

        def restore_run(arguments, **kwargs):
            calls.append(arguments)
            if "pg_restore" in arguments:
                raise common.OperationError("restore failed")
            return b""

        with (
            patch.object(
                verify_backup, "validate_archive", return_value={"audit_snapshots": {}}
            ),
            patch.object(verify_backup, "run", side_effect=restore_run),
            self.assertRaises(common.OperationError),
        ):
            verify_backup.verify(fixture)
        create = next(call for call in calls if "createdb" in call)
        drop = next(call for call in calls if "dropdb" in call)
        self.assertRegex(create[-1], r"^flowcredit_restore_check_[a-f0-9]{16}$")
        self.assertEqual(create[-1], drop[-1])
        self.assertNotEqual(drop[-1], "wiut")


def shutil_usage():
    from collections import namedtuple

    usage = namedtuple("usage", "total used free")
    return usage(100 * 1024**3, 20 * 1024**3, 80 * 1024**3)


if __name__ == "__main__":
    unittest.main()
