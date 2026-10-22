from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.validate_skill import SKILL_DIR, parse_frontmatter, validate_links, validate_skill


class SkillValidationTests(unittest.TestCase):
    def test_repository_skill_is_valid(self) -> None:
        self.assertEqual(validate_skill(), [])

    def test_frontmatter_name_and_description(self) -> None:
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        metadata = parse_frontmatter(text)
        self.assertEqual(metadata["name"], "aevum-emotional-performance-director")
        self.assertIn("narrative", metadata["description"].lower())

    def test_all_manifest_links_resolve(self) -> None:
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        self.assertEqual(validate_links(SKILL_DIR, text), [])

    def test_missing_reference_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "SKILL.md").write_text("See [missing](references/missing.md).", encoding="utf-8")
            self.assertTrue(validate_links(root, (root / "SKILL.md").read_text()))

    def test_path_traversal_link_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "SKILL.md").write_text("See [outside](../outside.md).", encoding="utf-8")
            self.assertIn("escapes skill directory", validate_links(root, (root / "SKILL.md").read_text())[0])


if __name__ == "__main__":
    unittest.main()
