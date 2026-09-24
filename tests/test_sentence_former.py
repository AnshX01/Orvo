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

    def test_mode_vs_more_disambiguation(self):
        """Verify 'more' is corrected to 'mode' in voice dictation contexts."""
        self.assertEqual(
            self.former.format("i want to make a speech to text more"),
            "I want to make a speech to text mode."
        )
        self.assertEqual(
            self.former.format("switch to toggle more please"),
            "Switch to toggle mode please."
        )
        self.assertEqual(
            self.former.format("push to talk more is enabled"),
            "Push to talk mode is enabled."
        )

    def test_acoustic_homophones(self):
        """Verify homophone resolution across all common phonetic pairs."""
        cases = [
            ("i have been working for to hours", "I have been working for two hours."),
            ("this is to much for me to handle", "This is too much for me to handle."),
            ("it is better then that", "It is better than that."),
            ("i do not know weather it will rain", "I do not know whether it will rain."),
            ("please come hear right now", "Please come here right now."),
            ("you are write about this", "You are right about this."),
            ("i need to right code today", "I need to write code today."),
            ("make sure not to loose your keys", "Make sure not to lose your keys."),
            ("the passed few weeks have been busy", "The past few weeks have been busy."),
            ("all accept one person came", "All except one person came."),
            ("this will effect the final results", "This will affect the final results."),
            ("bare with me for a moment", "Bear with me for a moment."),
            ("take a brake and relax", "Take a break and relax."),
            ("hit the breaks quickly", "Hit the brakes quickly."),
            ("rest in piece", "Rest in peace."),
            ("this is a peace of cake", "This is a piece of cake."),
            ("he played an important roll", "He played an important role."),
            ("check out our new web sight", "Check out our new website."),
            ("in principal this should work", "In principle this should work."),
            ("she gave me a nice complement", "She gave me a nice compliment."),
        ]
        for spoken, expected in cases:
            with self.subTest(spoken=spoken):
                self.assertEqual(self.former.format(spoken), expected)

    def test_technical_compound_words(self):
        """Verify split technical terms are consolidated properly."""
        self.assertEqual(
            self.former.format("connect to the data base and inspect the code base"),
            "Connect to the database and inspect the codebase."
        )
        self.assertEqual(
            self.former.format("this is an open source full stack app"),
            "This is an open-source full-stack app."
        )


if __name__ == "__main__":
    unittest.main()
