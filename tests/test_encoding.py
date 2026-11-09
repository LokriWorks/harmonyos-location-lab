"""Protect source and packaged UI from lossy text transfer on Windows."""
from pathlib import Path
import unittest


class EncodingTests(unittest.TestCase):
    def test_utf8_sources_have_no_replacement_characters(self):
        root = Path(__file__).resolve().parents[1]
        for file in root.rglob('*'):
            if not file.is_file() or any(p in ('.git', '__pycache__', 'build', 'dist') for p in file.relative_to(root).parts):
                continue
            if file.suffix not in ('.py', '.md', '.yml', '.ps1', '.txt'):
                continue
            with self.subTest(path=str(file.relative_to(root))):
                self.assertNotIn(chr(0xfffd), file.read_text(encoding='utf-8'))

    def test_beginner_guide_keeps_chinese_connection_steps(self):
        text = (Path(__file__).resolve().parents[1] / 'README.md').read_text(encoding='utf-8')
        for phrase in ('\u6570\u636e\u7ebf', 'USB \u8c03\u8bd5', '\u4f20\u8f93\u6587\u4ef6',
                       '\u68c0\u6d4b\u8bbe\u5907', 'Connected', '\u505c\u6b62\u5e76\u6062\u590d\u5b9a\u4f4d'):
            self.assertIn(phrase, text)
