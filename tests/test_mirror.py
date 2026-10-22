import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcd.mirror import BMCLAPI_BASE, Mirror  # noqa: E402


class MirrorTest(unittest.TestCase):
    def test_official_passes_through(self):
        mirror = Mirror("official")
        url = "https://libraries.minecraft.net/com/google/guava/guava/32.0.0-jre/guava.jar"
        self.assertEqual(mirror.urls(url), [url])
        self.assertEqual(mirror.manifest_urls(), ["https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"])

    def test_assets_are_rewritten(self):
        mirror = Mirror("bmclapi")
        url = "https://resources.download.minecraft.net/ab/abcdef"
        self.assertEqual(mirror.urls(url), [BMCLAPI_BASE + "/assets/ab/abcdef", url])

    def test_libraries_are_rewritten(self):
        mirror = Mirror("bmclapi")
        url = "https://libraries.minecraft.net/com/google/guava/guava/32.0.0-jre/guava-32.0.0-jre.jar"
        self.assertEqual(
            mirror.urls(url),
            [BMCLAPI_BASE + "/maven/com/google/guava/guava/32.0.0-jre/guava-32.0.0-jre.jar", url],
        )

    def test_mod_mavens_are_rewritten(self):
        mirror = Mirror("bmclapi")
        for base in (
            "https://maven.minecraftforge.net/",
            "https://maven.neoforged.net/releases/",
            "https://maven.fabricmc.net/",
            "https://maven.quiltmc.org/repository/release/",
        ):
            self.assertTrue(mirror.rewrite(base + "a/b/c.jar").startswith(BMCLAPI_BASE + "/maven/a/b/c.jar"))

    def test_unknown_host_untouched(self):
        mirror = Mirror("bmclapi")
        url = "https://piston-meta.mojang.com/v1/packages/aa/1.json"
        self.assertEqual(mirror.rewrite(url), url)

    def test_version_endpoints(self):
        mirror = Mirror("bmclapi")
        self.assertEqual(
            mirror.version_json_urls("1.20.1", "https://piston-meta.mojang.com/x.json"),
            [BMCLAPI_BASE + "/version/1.20.1/json", "https://piston-meta.mojang.com/x.json"],
        )
        self.assertEqual(
            mirror.client_urls("1.20.1", "https://piston-data.mojang.com/client.jar"),
            [BMCLAPI_BASE + "/version/1.20.1/client", "https://piston-data.mojang.com/client.jar"],
        )

    def test_invalid_name(self):
        with self.assertRaises(ValueError):
            Mirror("curseforge")


if __name__ == "__main__":
    unittest.main()
