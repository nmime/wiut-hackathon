"""Exercise production-key upgrades without Docker, networks or real deployment."""

import json
import os
import re
import shutil
import subprocess
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
            "docker": """#!/usr/bin/env python3
import json,os,sys
with open(os.environ['TEST_DOCKER_CALLS'],'a') as stream:
    stream.write(json.dumps({'args':sys.argv[1:],'inherited_auth_key':'AUTH_ENCRYPTION_KEY' in os.environ})+'\\n')
sys.exit(1 if sys.argv[1:3]==['volume','inspect'] else 0)
""",
            "curl": """#!/usr/bin/env python3
import sys
if '--write-out' in sys.argv: print('403',end='')
""",
            "flock": "#!/usr/bin/env python3\n",
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

    def deploy(self):
        environment = os.environ.copy()
        environment.update(
            PATH=f"{self.bin}:{environment['PATH']}",
            TEST_DOCKER_CALLS=str(self.calls),
            AUTH_ENCRYPTION_KEY="f" * 64,
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


if __name__ == "__main__":
    unittest.main()
