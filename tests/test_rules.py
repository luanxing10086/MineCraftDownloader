import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcd.rules import Context, allowed, maven_path, native_classifier  # noqa: E402


class RulesTest(unittest.TestCase):
    def setUp(self):
        self.win = Context(os_name="windows", arch="x86_64", os_version="10")
        self.linux = Context(os_name="linux", arch="x86_64", os_version="6.8")

    def test_no_rules_is_allowed(self):
        self.assertTrue(allowed({}, self.win))

    def test_allow_only_windows(self):
        lib = {"rules": [{"action": "allow", "os": {"name": "windows"}}]}
        self.assertTrue(allowed(lib, self.win))
        self.assertFalse(allowed(lib, self.linux))

    def test_disallow_osx(self):
        lib = {"rules": [{"action": "allow"}, {"action": "disallow", "os": {"name": "osx"}}]}
        self.assertTrue(allowed(lib, self.win))
        osx = Context(os_name="osx", arch="x86_64", os_version="14")
        self.assertFalse(allowed(lib, osx))

    def test_features_default_false(self):
        lib = {"rules": [{"action": "allow", "features": {"is_demo_user": True}}]}
        self.assertFalse(allowed(lib, self.win))
        demo = Context(os_name="windows", arch="x86_64", features={"is_demo_user": True})
        self.assertTrue(allowed(lib, demo))

    def test_native_classifier_replaces_arch(self):
        lib = {"natives": {"windows": "natives-windows-${arch}"}}
        self.assertEqual(native_classifier(lib, self.win), "natives-windows-64")
        thirty_two = Context(os_name="windows", arch="x86")
        self.assertEqual(native_classifier(lib, thirty_two), "natives-windows-32")

    def test_native_classifier_missing_platform(self):
        lib = {"natives": {"windows": "natives-windows"}}
        self.assertIsNone(native_classifier(lib, self.linux))

    def test_maven_path_plain(self):
        self.assertEqual(
            maven_path("net.fabricmc:fabric-loader:0.15.11"),
            "net/fabricmc/fabric-loader/0.15.11/fabric-loader-0.15.11.jar",
        )

    def test_maven_path_classifier_and_extension(self):
        self.assertEqual(
            maven_path("org.lwjgl:lwjgl:3.3.1:natives-windows"),
            "org/lwjgl/lwjgl/3.3.1/lwjgl-3.3.1-natives-windows.jar",
        )
        self.assertEqual(
            maven_path("net.minecraftforge:forge:1.20.1-47.2.0:universal@zip"),
            "net/minecraftforge/forge/1.20.1-47.2.0/forge-1.20.1-47.2.0-universal.zip",
        )

    def test_maven_path_rejects_garbage(self):
        with self.assertRaises(ValueError):
            maven_path("broken")


if __name__ == "__main__":
    unittest.main()
