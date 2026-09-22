"""
Unit tests for SentenceFormer and contextual sentence reconstruction.
"""

import unittest
from src.sentence_former import SentenceFormer


class TestSentenceFormer(unittest.TestCase):
    """Test suite for SentenceFormer context and sentence restructuring engine."""

    def setUp(self):
        self.former = SentenceFormer()

    def test_stutter_removal(self):
        """Verify 1-word, 2-word, and 3-word speech stutters are removed."""
        text = "I I think the the problem is we we need to fix it"
        result = self.former.format(text)
        self.assertNotIn("I I", result)
        self.assertNotIn("the the", result)
        self.assertNotIn("we we", result)
        self.assertIn("I think the problem is we need to fix it.", result)

    def test_filler_removal(self):
        """Verify verbal hesitation fillers (um, uh, erm) are eliminated."""
        text = "um actually uh this is working erm pretty well"
        result = self.former.format(text)
        self.assertNotIn("um", result.lower().split())
        self.assertNotIn("uh", result.lower().split())
        self.assertNotIn("erm", result.lower().split())
        self.assertEqual(result, "Actually this is working pretty well.")

    def test_question_detection(self):
        """Verify questions automatically receive question marks."""
        self.assertEqual(self.former.format("can you review this pull request"), "Can you review this pull request?")
        self.assertEqual(self.former.format("why did the build fail"), "Why did the build fail?")
        self.assertEqual(self.former.format("how do we deploy to production"), "How do we deploy to production?")

    def test_statement_terminal_punctuation(self):
        """Verify standard statements end with periods."""
        self.assertEqual(self.former.format("the server is running smoothly"), "The server is running smoothly.")

    def test_discourse_connectors_and_clauses(self):
        """Verify connectors like however, therefore, also structure sentences cleanly."""
        text = "we started the server however it threw an error and also logged a warning"
        result = self.former.format(text)
        self.assertIn(". However, ", result)
        self.assertIn(". Also, ", result)

    def test_proper_nouns_capitalization(self):
        """Verify technical tools, languages, and platforms are properly capitalized."""
        text = "i am writing python code in vs code and committing to github"
        result = self.former.format(text)
        self.assertIn("Python", result)
        self.assertIn("VS Code", result)
        self.assertIn("GitHub", result)

    def test_homophone_and_grammar_fixes(self):
        """Verify contextual acoustic homophone and grammar fixes."""
        self.assertEqual(
            self.former.format("its working fine and there going to ship it"),
            "It's working fine and they're going to ship it."
        )
        self.assertEqual(
            self.former.format("i should of checked the logs"),
            "I should have checked the logs."
        )


if __name__ == "__main__":
    unittest.main()
