import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from app import safe_output_stem, unique_output_path


class SafeOutputPathTests(unittest.TestCase):
    def test_replaces_windows_invalid_filename_characters(self):
        value = safe_output_stem('A:B/C\\\\D?E*F|"G"<H>')
        self.assertFalse(any(char in value for char in '<>:"/\\\\|?*'))
        self.assertNotIn("\\x00", value)

    def test_handles_reserved_windows_device_names(self):
        self.assertTrue(safe_output_stem("CON").startswith("_"))
        self.assertTrue(safe_output_stem("LPT1.txt").startswith("_"))

    def test_unique_output_path_uses_safe_title_and_extension(self):
        with TemporaryDirectory() as folder:
            path = unique_output_path(Path(folder), 'Video: "prueba"?', "MP3")
            self.assertEqual(path.suffix, ".mp3")
            self.assertNotIn(":", path.name)
            self.assertNotIn("?", path.name)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
