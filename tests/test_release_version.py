import json
import pathlib
import tomllib
import unittest

from anchorloop.version import VERSION


class ReleaseVersionTests(unittest.TestCase):
    def test_python_and_npm_packaging_use_the_canonical_version(self) -> None:
        root = pathlib.Path(__file__).resolve().parents[1]
        pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        package = json.loads((root / "package.json").read_text(encoding="utf-8"))

        self.assertNotIn("version", pyproject["project"])
        self.assertIn("version", pyproject["project"]["dynamic"])
        self.assertEqual(
            pyproject["tool"]["setuptools"]["dynamic"]["version"]["attr"],
            "anchorloop.version.VERSION",
        )
        self.assertEqual(package["version"], VERSION)
        self.assertIn("src/anchorloop/version.py", package["files"])


if __name__ == "__main__":
    unittest.main()
