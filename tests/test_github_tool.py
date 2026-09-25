import unittest

from repo_agent.github_tool import choose_source_files, parse_github_url


class GitHubToolTests(unittest.TestCase):
    def test_parse_valid_urls(self):
        self.assertEqual(parse_github_url("https://github.com/pallets/flask"), ("pallets", "flask"))
        self.assertEqual(parse_github_url("git@github.com:psf/requests.git"), ("psf", "requests"))
        self.assertEqual(parse_github_url("Analyze https://github.com/octocat/Hello-World."), ("octocat", "Hello-World"))

    def test_parse_invalid_url(self):
        with self.assertRaises(ValueError):
            parse_github_url("https://example.com/not/github")

    def test_choose_source_files_prefers_source_code(self):
        tree = [
            {"path": "README.md", "type": "blob", "size": 200},
            {"path": "src/app.py", "type": "blob", "size": 1000},
            {"path": "node_modules/pkg/index.js", "type": "blob", "size": 1000},
            {"path": "tests/test_app.py", "type": "blob", "size": 800},
        ]
        self.assertEqual(choose_source_files(tree, max_files=2), ["src/app.py", "tests/test_app.py"])

    def test_choose_source_files_skips_oversized(self):
        tree = [
            {"path": "huge.py", "type": "blob", "size": 200_000},
            {"path": "normal.py", "type": "blob", "size": 1000},
        ]
        result = choose_source_files(tree, max_files=5)
        self.assertNotIn("huge.py", result)
        self.assertIn("normal.py", result)

    def test_choose_source_files_skips_vendor_dirs(self):
        tree = [
            {"path": "vendor/lib.py", "type": "blob", "size": 500},
            {"path": "app.py", "type": "blob", "size": 500},
        ]
        result = choose_source_files(tree, max_files=5)
        self.assertNotIn("vendor/lib.py", result)
        self.assertIn("app.py", result)


if __name__ == "__main__":
    unittest.main()
