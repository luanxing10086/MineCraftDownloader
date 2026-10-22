import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcd import modpack  # noqa: E402


def build_mrpack(path, index, overrides=None, extra=None):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("modrinth.index.json", json.dumps(index))
        for name, data in (overrides or {}).items():
            archive.writestr(name, data)
        for name, data in (extra or {}).items():
            archive.writestr(name, data)


INDEX = {
    "formatVersion": 1,
    "game": "minecraft",
    "versionId": "1.0.0",
    "name": "Test Pack",
    "dependencies": {"minecraft": "1.20.1", "fabric-loader": "0.15.11"},
    "files": [
        {
            "path": "mods/example.jar",
            "hashes": {"sha1": "0" * 40, "sha512": "0" * 128},
            "env": {"client": "required", "server": "required"},
            "downloads": ["https://example.invalid/example.jar"],
            "fileSize": 1234,
        },
        {
            "path": "mods/serveronly.jar",
            "hashes": {},
            "env": {"client": "unsupported", "server": "required"},
            "downloads": ["https://example.invalid/serveronly.jar"],
            "fileSize": 10,
        },
    ],
}


class ModpackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.pack = os.path.join(self.root, "pack.mrpack")
        build_mrpack(
            self.pack,
            INDEX,
            overrides={
                "overrides/config/mod.toml": "a=1",
                "client-overrides/options.txt": "fov:90",
            },
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_index(self):
        index = modpack.read_index(self.pack)
        self.assertEqual(index["dependencies"]["minecraft"], "1.20.1")
        self.assertEqual(index["name"], "Test Pack")

    def test_loader_detection_order(self):
        self.assertEqual(modpack.loader_from_dependencies({"minecraft": "1.20.1", "forge": "47.2.0"}), ("forge", "47.2.0"))
        self.assertEqual(
            modpack.loader_from_dependencies({"minecraft": "1.21.1", "neoforge": "21.1.66"}),
            ("neoforge", "21.1.66"),
        )
        self.assertEqual(modpack.loader_from_dependencies({"minecraft": "1.20.1"}), (None, None))

    def test_extract_overrides(self):
        target = os.path.join(self.root, "instance")
        os.makedirs(target)
        count = modpack.extract_overrides(self.pack, target)
        self.assertEqual(count, 2)
        with open(os.path.join(target, "config", "mod.toml"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "a=1")
        self.assertTrue(os.path.exists(os.path.join(target, "options.txt")))

    def test_extract_rejects_zip_slip(self):
        evil = os.path.join(self.root, "evil.mrpack")
        build_mrpack(evil, INDEX, overrides={"overrides/../../escaped.txt": "boom"})
        target = os.path.join(self.root, "instance2")
        os.makedirs(target)
        with self.assertRaises(modpack.ModpackError):
            modpack.extract_overrides(evil, target)
        self.assertFalse(os.path.exists(os.path.join(self.root, "escaped.txt")))

    def test_curseforge_zip_message(self):
        cf = os.path.join(self.root, "cf.zip")
        with zipfile.ZipFile(cf, "w") as archive:
            archive.writestr("manifest.json", "{}")
        with self.assertRaises(modpack.ModpackError) as ctx:
            modpack.read_index(cf)
        self.assertIn("CurseForge", str(ctx.exception))

    def test_not_a_pack(self):
        plain = os.path.join(self.root, "plain.zip")
        with zipfile.ZipFile(plain, "w") as archive:
            archive.writestr("readme.txt", "hi")
        with self.assertRaises(modpack.ModpackError):
            modpack.read_index(plain)


if __name__ == "__main__":
    unittest.main()
