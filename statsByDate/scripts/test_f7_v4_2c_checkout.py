"""F7 v4.2c: checkout policy regression checks."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]

class CheckoutTests(unittest.TestCase):
    def test_shallow_checkout_for_update(self):
        workflow = (ROOT / ".github/workflows/StatsByDate.yml").read_text()
        self.assertIn("fetch-depth: 1", workflow)
        self.assertNotIn("fetch-depth: 0", workflow)
        self.assertIn("persist-credentials: true", workflow)

    def test_publication_guard_retained(self):
        workflow = (ROOT / ".github/workflows/StatsByDate.yml").read_text()
        self.assertIn("git merge-base --is-ancestor", workflow)
        self.assertIn("published_sha:", workflow)
        self.assertIn("publishStatsByDate.py", workflow)

if __name__ == "__main__":
    unittest.main()
