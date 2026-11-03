import hashlib
from pathlib import Path
import tempfile
import unittest
from scripts.publish_slim_release import publish, verify_input


class Tests(unittest.TestCase):
    def test_split_and_digest_verified_without_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / "doom-ios-native-slim.tar.gz"
            bundle.write_bytes(bytes(range(256)) * 20)
            checksum = root / "doom-ios-native-slim.tar.gz.sha256"
            sha = hashlib.sha256(bundle.read_bytes()).hexdigest()
            checksum.write_text(f"{sha}  {bundle.name}\n")
            manifest = publish(bundle, checksum, "ram-labz/doom-native-builder",
                               "12345678", dry_run=True, part_bytes=1000)
            self.assertEqual(manifest["bundle_sha256"], sha)
            self.assertEqual(manifest["bundle_bytes"], 5120)
            self.assertEqual([p["size"] for p in manifest["parts"]], [1000]*5 + [120])
            self.assertEqual(manifest["pinned_native_revision"],
                             "bf20d1e7460fb08e5702514881d76cfa047caa00")

    def test_bad_digest_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "doom-ios-native-slim.tar.gz"
            bundle.write_bytes(b"hello")
            checksum = Path(tmp) / "digest.sha256"
            checksum.write_text("0"*64 + "  doom-ios-native-slim.tar.gz\n")
            with self.assertRaisesRegex(ValueError, "checksum"):
                verify_input(bundle, checksum)

    def test_bad_repo_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "doom-ios-native-slim.tar.gz"
            bundle.write_bytes(b"hello")
            checksum = Path(tmp) / "digest.sha256"
            checksum.write_text(hashlib.sha256(b"hello").hexdigest() + "  " + bundle.name)
            with self.assertRaisesRegex(ValueError, "repository"):
                publish(bundle, checksum, "something/else", "12345678", dry_run=True)
