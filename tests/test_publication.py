"""All fixtures are synthetic, created in temporary Git repositories."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("publication_gate", Path(__file__).resolve().parents[1] / "scripts/check_publication.py")
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)

class PublicationGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Synthetic Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "core.autocrlf", "false")
        self.put("README.md", "Synthetic public fixture\n")
        self.review()
    def git(self, *args):
        r = subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True)
        self.assertEqual(r.returncode, 0, "Synthetic Git operation failed")
        return r.stdout
    def put(self, name, text):
        p = self.repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    def review(self):
        self.git("add", "--", "README.md")
        raw = self.git("show", ":README.md")
        self.put(gate.MANIFEST, json.dumps({"schema_version": 1, "files": {"README.md": hashlib.sha256(raw).hexdigest()}}))
        self.git("add", "--", gate.MANIFEST)
    def test_clean_index_and_history(self):
        self.git("commit", "-qm", "Synthetic baseline")
        self.assertEqual(gate.audit(self.repo, True), [])
    def test_private_tracked_path_is_blocked(self):
        self.put("private/record.md", "Synthetic confidential fixture")
        self.git("add", "--", "private/record.md")
        self.assertTrue(gate.audit(self.repo))
    def test_staged_secret_not_hidden_by_clean_worktree(self):
        self.put("README.md", "sk-" + "a" * 32)
        self.review()
        self.put("README.md", "clean worktree")
        self.assertTrue(gate.audit(self.repo))
    def test_secret_value_not_in_messages(self):
        value = "ghp_" + "x" * 36
        self.put("README.md", value)
        self.review()
        issues = gate.audit(self.repo)
        self.assertTrue(issues)
        self.assertNotIn(value, str(issues))
    def test_unreviewed_edit_is_blocked(self):
        self.put("README.md", "Modified synthetic fixture")
        self.git("add", "--", "README.md")
        self.assertTrue(gate.audit(self.repo))
    def test_untracked_private_encoding_not_read(self):
        p = self.repo / "private"
        p.mkdir()
        (p / "record.json").write_bytes(b"\xff\xfeBAD")
        self.assertEqual(gate.audit(self.repo), [])
    def test_symlink_mode_is_blocked(self):
        oid = self.git("rev-parse", ":README.md").decode().strip()
        self.git("update-index", "--add", "--cacheinfo", "120000," + oid + ",linked")
        self.assertTrue(gate.audit(self.repo))
    def test_old_unreviewed_history_is_blocked(self):
        self.git("rm", "--cached", "--", gate.MANIFEST)
        self.git("commit", "-qm", "Synthetic historical unsafe boundary")
        self.review()
        self.git("commit", "-qm", "Synthetic new boundary")
        self.assertEqual(gate.audit(self.repo), [])
        self.assertTrue(gate.audit(self.repo, True))
    def test_arbitrary_manifest_fields_are_blocked(self):
        m=json.loads((self.repo/gate.MANIFEST).read_text(encoding="utf-8"))
        m["private_note"]="synthetic"
        self.put(gate.MANIFEST,json.dumps(m))
        self.git("add", "--", gate.MANIFEST)
        self.assertTrue(gate.audit(self.repo))
    def test_unsafe_manifest_path_is_rejected(self):
        for name in ["../outside", "private/x", "data/x", "C:/x", "workspace/x", ".env", "x.db"]:
            with self.subTest(name=name):
                self.assertFalse(gate.safe_path(name))
    def test_duplicate_manifest_keys_are_rejected(self):
        with self.assertRaises(gate.GateError):
            gate.parse_manifest(b'{"schema_version":1,"files":{},"files":{}}')
    def test_missing_manifest_is_blocked(self):
        self.git("rm", "--cached", "--", gate.MANIFEST)
        self.assertTrue(gate.audit(self.repo))

if __name__ == "__main__":
    unittest.main()
