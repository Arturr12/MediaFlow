import unittest
from pathlib import Path
from unittest.mock import patch

import update_core


class UpdateCoreTests(unittest.TestCase):
    def test_version_tuple(self):
        self.assertEqual(update_core.version_tuple("v0.4.4"), (0, 4, 4, 0))
        self.assertTrue(update_core.is_newer_version("0.4.4", "0.4.3"))
        self.assertFalse(update_core.is_newer_version("0.4.3", "0.4.3"))

    def test_repository_validation(self):
        self.assertTrue(update_core.validate_repository_name("owner/MediaFlow"))
        self.assertFalse(update_core.validate_repository_name("https://github.com/owner/MediaFlow"))
        self.assertFalse(update_core.validate_repository_name("owner"))
        self.assertFalse(update_core.validate_repository_name("owner/../repo"))

    def test_manifest_asset_version_and_checksum_validation(self):
        sha = "a" * 64
        release = {
            "tag_name": "v0.5.0",
            "draft": False,
            "prerelease": False,
            "html_url": "https://github.com/owner/MediaFlow/releases/tag/v0.5.0",
            "body": "Novedades de prueba",
            "assets": [
                {"name": "mediaflow-update.json", "browser_download_url": "https://github.com/owner/MediaFlow/releases/download/v0.5.0/mediaflow-update.json"},
                {"name": "MediaFlow-Setup-0.5.0.exe", "browser_download_url": "https://github.com/owner/MediaFlow/releases/download/v0.5.0/MediaFlow-Setup-0.5.0.exe", "size": 1024},
            ],
        }
        manifest = {
            "product": "MediaFlow",
            "version": "0.5.0",
            "installer_asset": "MediaFlow-Setup-0.5.0.exe",
            "sha256": sha,
        }
        with patch.object(update_core, "_json_request", return_value=release), patch.object(update_core, "_download_small_json", return_value=manifest):
            info = update_core.fetch_latest_update("owner/MediaFlow", "0.4.4")
        self.assertIsNotNone(info)
        self.assertEqual(info.version, "0.5.0")
        self.assertEqual(info.sha256, sha)

    def test_no_new_release(self):
        release = {"tag_name": "v0.4.4", "draft": False, "prerelease": False}
        with patch.object(update_core, "_json_request", return_value=release):
            self.assertIsNone(update_core.fetch_latest_update("owner/MediaFlow", "0.4.4"))


if __name__ == "__main__":
    unittest.main()

class DownloadVerificationTests(unittest.TestCase):
    def test_download_verifies_sha256_before_finalizing(self):
        import hashlib
        import io
        from unittest.mock import patch

        payload = b"M" * (1024 * 1024 + 37)
        expected = hashlib.sha256(payload).hexdigest()

        class FakeResponse:
            headers = {"Content-Length": str(len(payload))}

            def __enter__(self):
                self._stream = io.BytesIO(payload)
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self, size=-1):
                return self._stream.read(size)

            def geturl(self):
                return "https://release-assets.githubusercontent.com/mediaflow-setup.exe"

        info = {
            "installer_name": "MediaFlow-Setup-0.5.0.exe",
            "installer_url": "https://github.com/owner/MediaFlow/releases/download/v0.5.0/MediaFlow-Setup-0.5.0.exe",
            "sha256": expected,
            "installer_size": len(payload),
        }
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp_dir, patch("update_core.urllib.request.urlopen", return_value=FakeResponse()):
            result = update_core.download_verified_installer(info, Path(temp_dir))
            self.assertTrue(result.is_file())
            self.assertEqual(result.read_bytes(), payload)

    def test_download_rejects_wrong_sha_and_removes_partial_file(self):
        import io
        from unittest.mock import patch
        from tempfile import TemporaryDirectory

        payload = b"X" * (1024 * 1024 + 5)

        class FakeResponse:
            headers = {"Content-Length": str(len(payload))}
            def __enter__(self):
                self._stream = io.BytesIO(payload)
                return self
            def __exit__(self, exc_type, exc, tb):
                return False
            def read(self, size=-1):
                return self._stream.read(size)
            def geturl(self):
                return "https://release-assets.githubusercontent.com/mediaflow-setup.exe"

        info = {
            "installer_name": "MediaFlow-Setup-0.5.0.exe",
            "installer_url": "https://github.com/owner/MediaFlow/releases/download/v0.5.0/MediaFlow-Setup-0.5.0.exe",
            "sha256": "0" * 64,
            "installer_size": len(payload),
        }
        with TemporaryDirectory() as temp_dir, patch("update_core.urllib.request.urlopen", return_value=FakeResponse()):
            with self.assertRaises(RuntimeError):
                update_core.download_verified_installer(info, Path(temp_dir))
            self.assertFalse((Path(temp_dir) / "MediaFlow-Setup-0.5.0.exe.part").exists())
