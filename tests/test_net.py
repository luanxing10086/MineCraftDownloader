import hashlib
import os
import sys
import tempfile
import unittest
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcd import net  # noqa: E402


class NetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_human_size(self):
        self.assertEqual(net.human_size(512), "512.0 B")
        self.assertEqual(net.human_size(2048), "2.0 KB")
        self.assertEqual(net.human_size(5 * 1024 * 1024), "5.0 MB")

    def test_file_sha1(self):
        path = os.path.join(self.root, "a.bin")
        with open(path, "wb") as handle:
            handle.write(b"mcd")
        expected = hashlib.sha1(b"mcd").hexdigest()
        self.assertEqual(net.file_sha1(path), expected)

    def test_download_from_file_url_and_skip_cached(self):
        source = os.path.join(self.root, "source.bin")
        with open(source, "wb") as handle:
            handle.write(b"payload" * 1000)
        digest = net.file_sha1(source)
        dest = os.path.join(self.root, "out", "copy.bin")
        url = urllib.request.pathname2url(source)
        url = "file:" + url if not url.startswith("file:") else url

        written = net.download(dest, [url], sha1=digest)
        self.assertEqual(written, os.path.getsize(source))
        self.assertEqual(net.file_sha1(dest), digest)

        # 第二次应当直接跳过（返回 0）
        self.assertEqual(net.download(dest, [url], sha1=digest), 0)

    def test_download_rejects_bad_hash(self):
        source = os.path.join(self.root, "bad.bin")
        with open(source, "wb") as handle:
            handle.write(b"x" * 10)
        dest = os.path.join(self.root, "bad-copy.bin")
        url = "file:" + urllib.request.pathname2url(source)
        with self.assertRaises(net.DownloadError):
            net.download(dest, [url], sha1="0" * 40, retries=1)

    def test_download_many_collects_failures(self):
        good = os.path.join(self.root, "g.bin")
        with open(good, "wb") as handle:
            handle.write(b"ok")
        dest = os.path.join(self.root, "many", "g.bin")
        tasks = [
            {"dest": dest, "urls": ["file:" + urllib.request.pathname2url(good)], "sha1": net.file_sha1(good)},
            {"dest": os.path.join(self.root, "many", "missing.bin"), "urls": ["file:" + urllib.request.pathname2url(
                os.path.join(self.root, "nope.bin"))]},
        ]
        failures = net.download_many(tasks, threads=2)
        self.assertEqual(len(failures), 1)
        self.assertTrue(os.path.exists(dest))

    def test_reporter_counts(self):
        reporter = net.Reporter(enabled=False)
        reporter.start(2)
        reporter.done("a", 10)
        reporter.done("b", 20)
        self.assertEqual(reporter.done_files, 2)
        self.assertEqual(reporter.total_bytes, 30)
        self.assertEqual(reporter.total_files, 2)


if __name__ == "__main__":
    unittest.main()
