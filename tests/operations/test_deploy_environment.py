"""Exercise production-key upgrades without Docker, networks or real deployment."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class DeploymentEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "scripts").mkdir()
        shutil.copyfile(ROOT / "scripts/deploy.sh", self.root / "scripts/deploy.sh")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.calls = self.root / "docker-calls.jsonl"
        scripts = {
            "docker": """#!/bin/bash
# The tested deploy command supplies only fixed, quote-free CLI arguments.
{
  printf '{"args":['
  comma=''
  for argument in "$@"; do
    printf '%s"%s"' "$comma" "$argument"
    comma=','
  done
  inherited=false
  [[ ${AUTH_ENCRYPTION_KEY+x} ]] && inherited=true
  printf '],"inherited_auth_key":%s}\\n' "$inherited"
} >> "$TEST_DOCKER_CALLS"
if [[ "$1" == volume && "$2" == inspect ]]; then
  [[ "$TEST_IMAGE_SCENARIO" == skip ]] && exit 0
  exit 1
fi
if [[ -n "$TEST_IMAGE_SCENARIO" ]]; then
  if [[ "$1" == compose && "$*" == *" ps --quiet "* ]]; then
    case "${!#}" in
      api) printf 'aaaaaaaaaaaa\\n';;
      web) printf 'bbbbbbbbbbbb\\n';;
      ml) printf 'cccccccccccc\\n';;
    esac
  elif [[ "$1" == inspect && "$2" == --format ]]; then
    case "${!#}" in
      aaaaaaaaaaaa) printf 'sha256:%064d\\n' 1;;
      bbbbbbbbbbbb) printf 'sha256:%064d\\n' 2;;
      cccccccccccc) printf 'sha256:%064d\\n' 3;;
    esac
  elif [[ "$1" == image && "$2" == inspect ]]; then
    [[ "$TEST_IMAGE_SCENARIO" == missing-api && "$3" == *0001 ]] && exit 1
    [[ "$TEST_IMAGE_SCENARIO" == missing-ml* && "$3" == *0003 ]] && exit 1
  elif [[ "$1" == inspect && "$2" == cccccccccccc ]]; then
    extra=''
    [[ "$TEST_IMAGE_SCENARIO" == missing-ml-secret ]] && extra=',"DATABASE_PASSWORD=do-not-snapshot"'
    printf '{"Config":{"User":"10001:10001","Env":["PATH=/app/.venv/bin:/usr/bin","ML_MODEL_PATH=/app/runtime/model.joblib","ML_AUDIT_PATH=/data/audit/requests.jsonl"%s]},"State":{"Running":true},"HostConfig":{"Privileged":false},"Mounts":[{"Type":"volume","Name":"flowcredit_ml-audit","Destination":"/data/audit"}]}' "$extra" | sed 's/^/[/;s/$/]/'
  elif [[ "$1" == commit ]]; then
    printf 'sha256:%064d\\n' 4
  fi
fi
exit 0
""",
            "curl": """#!/bin/bash
for argument in "$@"; do
  [[ "$argument" == --write-out ]] && printf '403'
done
exit 0
""",
            "flock": "#!/bin/bash\nexit 0\n",
            # Release publication is covered by the operations tests. Keep this
            # environment migration fixture isolated from real Git/model calls.
            "python3": f'#!/bin/bash\nif [[ "$1" == -c ]]; then exec "{sys.executable}" "$@"; fi\nexit 0\n',
        }
        for name, content in scripts.items():
            target = self.bin / name
            target.write_text(content)
            target.chmod(0o700)
        self.envfile = self.root / ".env.production"

    def existing(self, suffix=""):
        self.envfile.write_text(
            "DOMAIN=wiut-hackathon.dehqonhub.uz\n"
            f"POSTGRES_PASSWORD={'a' * 64}\n"
            "TRUSTED_PROXY_IP=172.30.84.1\n" + suffix
        )

    def deploy(self, image_scenario="", skip_rollback_images=""):
        environment = os.environ.copy()
        environment.update(
            PATH=f"{self.bin}:{environment['PATH']}",
            TEST_DOCKER_CALLS=str(self.calls),
            AUTH_ENCRYPTION_KEY="f" * 64,
            TEST_IMAGE_SCENARIO=image_scenario,
            FLOWCREDIT_SKIP_ROLLBACK_IMAGES=skip_rollback_images,
        )
        return subprocess.run(
            ["bash", str(self.root / "scripts/deploy.sh")],
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    def key(self):
        matches = re.findall(
            r"^AUTH_ENCRYPTION_KEY=(.*)$", self.envfile.read_text(), re.MULTILINE
        )
        self.assertEqual(len(matches), 1)
        self.assertRegex(matches[0], r"^[a-f0-9]{64}$")
        return matches[0]

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        key = self.key()
        self.assertNotIn(key, result.stdout + result.stderr)
        self.assertEqual(self.envfile.stat().st_mode & 0o777, 0o600)
        commands = [json.loads(row) for row in self.calls.read_text().splitlines()]
        composed = [
            row for row in commands if row["args"][:2] == ["compose", "--project-name"]
        ]
        self.assertTrue(composed)
        self.assertTrue(all(not row["inherited_auth_key"] for row in composed))
        return key

    def test_first_install_generates_distinct_keys_and_preserves_them(self):
        key = self.assert_success(self.deploy())
        password = re.search(
            r"^POSTGRES_PASSWORD=(.*)$", self.envfile.read_text(), re.MULTILINE
        )[1]
        self.assertNotEqual(key, password)
        before = self.envfile.read_bytes()
        self.assert_success(self.deploy())
        self.assertEqual(self.envfile.read_bytes(), before)

    def test_upgrade_adds_only_missing_key_and_preserves_other_values(self):
        self.existing("SESSION_TTL_HOURS=168\n")
        previous = self.envfile.read_text()
        key = self.assert_success(self.deploy())
        self.assertTrue(self.envfile.read_text().startswith(previous))
        self.assertNotEqual(key, "f" * 64)
        before = self.envfile.read_bytes()
        self.assert_success(self.deploy())
        self.assertEqual(self.envfile.read_bytes(), before)

    def test_existing_valid_key_is_never_rotated(self):
        self.existing(f"AUTH_ENCRYPTION_KEY={'b' * 64}\n")
        before = self.envfile.read_bytes()
        self.assertEqual(self.assert_success(self.deploy()), "b" * 64)
        self.assertEqual(self.envfile.read_bytes(), before)

    def test_historical_endpoint_does_not_start_a_second_production_scorer(self):
        self.existing(
            f"AUTH_ENCRYPTION_KEY={'b' * 64}\nML_SERVICE_URL=http://teammate-ml:8000\n"
        )
        before = self.envfile.read_bytes()
        self.assert_success(self.deploy())
        self.assertEqual(self.envfile.read_bytes(), before)
        commands = [
            json.loads(row)["args"] for row in self.calls.read_text().splitlines()
        ]
        self.assertFalse(any("teammate-ml" in command for command in commands))
        self.assertFalse(
            any("--volumes" in command or "-v" in command for command in commands)
        )

    def test_invalid_empty_or_duplicate_keys_stop_before_build(self):
        for suffix in (
            "AUTH_ENCRYPTION_KEY=\n",
            "AUTH_ENCRYPTION_KEY=invalid\n",
            f"AUTH_ENCRYPTION_KEY={'b' * 64}\nAUTH_ENCRYPTION_KEY={'c' * 64}\n",
        ):
            with self.subTest(suffix=suffix[:32]):
                self.existing(suffix)
                before = self.envfile.read_bytes()
                self.calls.unlink(missing_ok=True)
                result = self.deploy()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.envfile.read_bytes(), before)
                commands = [
                    json.loads(row)["args"]
                    for row in self.calls.read_text().splitlines()
                ]
                self.assertFalse(any("build" in row for row in commands))
                self.assertNotIn("b" * 64, result.stdout + result.stderr)

    def test_pruned_ml_image_recovers_snapshot_before_build(self):
        self.existing(f"AUTH_ENCRYPTION_KEY={'b' * 64}\n")
        self.assert_success(self.deploy("missing-ml"))
        commands = [
            json.loads(row)["args"] for row in self.calls.read_text().splitlines()
        ]
        snapshots = [
            index for index, command in enumerate(commands) if command[0] == "commit"
        ]
        self.assertEqual(len(snapshots), 1)
        snapshot = commands[snapshots[0]]
        self.assertEqual(snapshot[:3], ["commit", "--pause=false", "cccccccccccc"])
        self.assertTrue(snapshot[3].startswith("flowcredit-ml:rollback-"))
        build = next(
            index for index, command in enumerate(commands) if "build" in command
        )
        self.assertLess(snapshots[0], build)
        manifest = next(
            (self.root / "artifacts/production-backups").glob("images-*.txt")
        )
        self.assertIn(f"sha256:{4:064d}", manifest.read_text())

    def test_pruned_api_image_aborts_without_snapshot_or_build(self):
        self.existing(f"AUTH_ENCRYPTION_KEY={'b' * 64}\n")
        result = self.deploy("missing-api")
        self.assertNotEqual(result.returncode, 0)
        commands = [
            json.loads(row)["args"] for row in self.calls.read_text().splitlines()
        ]
        self.assertFalse(
            any(
                command[0] == "commit" or "build" in command or "stop" in command
                for command in commands
            )
        )

    def test_explicit_image_skip_still_builds_and_backs_up_database(self):
        self.existing(f"AUTH_ENCRYPTION_KEY={'b' * 64}\n")
        result = self.deploy("skip", "1")
        self.assert_success(result)
        commands = [
            json.loads(row)["args"] for row in self.calls.read_text().splitlines()
        ]
        self.assertFalse(
            any(
                command[0] in {"inspect", "commit"}
                or command[:2] in [["image", "inspect"], ["image", "tag"]]
                for command in commands
            )
        )
        self.assertTrue(any("build" in command for command in commands))
        self.assertTrue(any("pg_dump" in command for command in commands))
        self.assertTrue(any("stop" in command for command in commands))
        self.assertIn("skipping old image preservation", result.stdout)

    def test_pruned_ml_image_with_unexpected_secret_aborts_before_snapshot(self):
        self.existing(f"AUTH_ENCRYPTION_KEY={'b' * 64}\n")
        result = self.deploy("missing-ml-secret")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("do-not-snapshot", result.stdout + result.stderr)
        commands = [
            json.loads(row)["args"] for row in self.calls.read_text().splitlines()
        ]
        self.assertFalse(
            any(
                command[0] == "commit" or "build" in command or "stop" in command
                for command in commands
            )
        )


if __name__ == "__main__":
    unittest.main()
