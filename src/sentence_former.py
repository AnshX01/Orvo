"""
Orvo Sentence Formation and Context Engine.
Intelligently connects sentences, fixes disfluencies, repairs broken fragments,
normalizes punctuation, and ensures dictation is coherent and grammatically structured.
"""

import re
import logging
from typing import Optional, List, Dict, Tuple

logger = logging.getLogger("Orvo.SentenceFormer")

# Common spoken fillers to clean
DEFAULT_FILLERS = {
    r"\buh\b", r"\bum\b", r"\berm\b", r"\bah\b", r"\buhm\b"
}

# Technical terms and proper nouns capitalization map
PROPER_NOUNS_MAP = {
    "vs code": "VS Code",
    "vscode": "VS Code",
    "github": "GitHub",
    "git": "Git",
    "python": "Python",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "windows": "Windows",
    "chrome": "Chrome",
    "discord": "Discord",
    "slack": "Slack",
    "notion": "Notion",
    "api": "API",
    "apis": "APIs",
    "ui": "UI",
    "ux": "UX",
    "json": "JSON",
    "html": "HTML",
    "css": "CSS",
    "sql": "SQL",
    "url": "URL",
    "urls": "URLs",
    "http": "HTTP",
    "https": "HTTPS",
    "cpu": "CPU",
    "gpu": "GPU",
    "ram": "RAM",
    "whisper": "Whisper",
    "groq": "Groq",
    "openai": "OpenAI",
}

# Discourse connectors that should typically be followed by a comma or start a sentence
DISCOURSE_CONNECTORS = [
    "however", "therefore", "furthermore", "moreover", "meanwhile",
    "nevertheless", "in addition", "for example", "for instance",
    "on the other hand", "as a result", "consequently", "in fact"
]


class SentenceFormer:
    """
    Sentence reconstruction and context engine.
    Ensures that raw speech-to-text output is transformed into coherent,
    well-formed sentences with natural transitions and correct grammar.
    """

    def __init__(
        self,
        enable_smart_formatting: bool = True,
        remove_fillers: bool = True,
        fix_disfluencies: bool = True,
        auto_capitalize: bool = True,
        auto_punctuate: bool = True,
    ):
        self.enable_smart_formatting = enable_smart_formatting
        self.remove_fillers = remove_fillers
        self.fix_disfluencies = fix_disfluencies
        self.auto_capitalize = auto_capitalize
        self.auto_punctuate = auto_punctuate

    def format(self, text: str) -> str:
        """
        Main pipeline to format, clean, and reconstruct sentences from raw transcribed text.
        """
        if not text or not text.strip():
            return ""

        result = text.strip()

        if not self.enable_smart_formatting:
            return result

        # 1. Remove verbal fillers (um, uh, ah)
        if self.remove_fillers:
            result = self._clean_fillers(result)

        # 2. Fix speech disfluencies (repeated words/phrases from hesitations)
        if self.fix_disfluencies:
            result = self._remove_stutters(result)

        # 3. Contextual homophone and grammar fixes
        result = self._fix_contextual_grammar(result)

        # 4. Standardize punctuation spacing
        result = self._clean_punctuation_spacing(result)

        # 5. Connect and structure sentences
        result = self._structure_sentences(result)

        # 6. Apply proper noun & tech capitalization
        result = self._capitalize_proper_nouns(result)

        # 7. Final capitalization & boundary punctuation
        if self.auto_capitalize:
            result = self._ensure_sentence_capitalization(result)

        if self.auto_punctuate:
            result = self._ensure_terminal_punctuation(result)

        return result.strip()

    def _clean_fillers(self, text: str) -> str:
        """Removes speech hesitation tokens (um, uh, erm)."""
        for pat in DEFAULT_FILLERS:
            text = re.sub(pat, "", text, flags=re.IGNORECASE)
        # Normalize double spaces
        return re.sub(r"\s+", " ", text).strip()

    def _remove_stutters(self, text: str) -> str:
        """
        Removes repeated hesitation words and short phrases:
        e.g. 'I I want to' -> 'I want to'
             'the the problem' -> 'the problem'
             'I want to I want to go' -> 'I want to go'
        """
        # 3-word stutter (e.g. "I want to I want to go")
        text = re.sub(r"\b([a-zA-Z]+\s+[a-zA-Z]+\s+[a-zA-Z]+)(?:\s+\1\b)+", r"\1", text, flags=re.IGNORECASE)

        # 2-word stutter (e.g. "I want I want to", "this is this is")
        text = re.sub(r"\b([a-zA-Z]+\s+[a-zA-Z]+)(?:\s+\1\b)+", r"\1", text, flags=re.IGNORECASE)

        # 1-word stutter (e.g. "it it is", "I I", "and and")
        text = re.sub(r"\b([a-zA-Z]+)(?:\s+\1\b)+", r"\1", text, flags=re.IGNORECASE)

        return text

    def _fix_contextual_grammar(self, text: str) -> str:
        """
        Fixes common acoustic homophones and common spoken grammar slips based on local context.
        """
        # Fix 'i' to 'I'
        text = re.sub(r"\bi\b", "I", text)
        text = re.sub(r"\bi'm\b", "I'm", text, flags=re.IGNORECASE)
        text = re.sub(r"\bi've\b", "I've", text, flags=re.IGNORECASE)
        text = re.sub(r"\bi'll\b", "I'll", text, flags=re.IGNORECASE)
        text = re.sub(r"\bi'd\b", "I'd", text, flags=re.IGNORECASE)

        # Fix "gonna" -> "going to", "wanna" -> "want to" if preceded by pronoun
        text = re.sub(r"\bI\s+gonna\b", "I am going to", text)
        text = re.sub(r"\bwe\s+gonna\b", "we are going to", text, flags=re.IGNORECASE)
        text = re.sub(r"\byou\s+gonna\b", "you are going to", text, flags=re.IGNORECASE)

        # "could of" / "should of" / "would of" -> "could have" / "should have" / "would have"
        text = re.sub(r"\b(could|should|would|must)\s+of\b", r"\1 have", text, flags=re.IGNORECASE)

        # "their" vs "there" vs "they're"
        text = re.sub(r"\bthere\s+(going|doing|working|saying|trying|making)\b", r"they're \1", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(in|over|out|under|up|down)\s+their\b", r"\1 there", text, flags=re.IGNORECASE)

        # "its" vs "it's"
        text = re.sub(r"\bits\s+(a|an|the|not|very|really|so|too|been|going|working|hard|easy|good|fine|ok|okay)\b", r"it's \1", text, flags=re.IGNORECASE)

        return text

    def _clean_punctuation_spacing(self, text: str) -> str:
        """Removes spaces before punctuation and ensures single space after."""
        # Remove whitespace before punctuation
        text = re.sub(r"\s+([,.:;?!])", r"\1", text)
        # Ensure single space after punctuation when followed by a letter/number
        text = re.sub(r"([,.:;?!])([A-Za-z0-9])", r"\1 \2", text)
        # Remove duplicate punctuation
        text = re.sub(r",+", ",", text)
        text = re.sub(r":+", ":", text)
        text = re.sub(r";+", ";", text)
        text = re.sub(r"\?+", "?", text)
        text = re.sub(r"!+", "!", text)
        # Normalize multiple spaces
        text = re.sub(r"[ \t]+", " ", text)
        return text

    def _structure_sentences(self, text: str) -> str:
        """
        Structures clauses and connects thoughts into clear sentences.
        Adds commas at natural conjunction pauses and splits run-on ideas.
        """
        # Ensure discourse connectors are preceded by a period and followed by comma + space
        for connector in DISCOURSE_CONNECTORS:
            pattern = re.compile(rf"(?<=[a-zA-Z0-9])\s*,?\s*\b({re.escape(connector)})\b\s*,?", re.IGNORECASE)
            def _repl(match):
                word = match.group(1)
                return f". {word.capitalize()}, "
            text = pattern.sub(_repl, text)

        # Break long run-on sentences connected by ", and then" or ", and so"
        text = re.sub(r",?\s*\band then\b\s*", ". Then ", text, flags=re.IGNORECASE)
        text = re.sub(r",?\s*\band also\b\s*", ". Also, ", text, flags=re.IGNORECASE)

        # Connect clauses: ensure comma before coordinate conjunctions when connecting two clauses
        text = re.sub(r"(?<=[a-zA-Z0-9])\s+\b(but|although|whereas)\b", r", \1", text, flags=re.IGNORECASE)

        # Clean up any generated ".. " or ",. "
        text = re.sub(r"\.\s*\.", ".", text)
        text = re.sub(r",\s*\.", ".", text)
        text = re.sub(r",\s*,", ",", text)
        text = re.sub(r"\s+", " ", text)

        return text

    def _capitalize_proper_nouns(self, text: str) -> str:
        """Capitalizes known technical terms, programming languages, and tools."""
        for term, proper in PROPER_NOUNS_MAP.items():
            pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
            text = pattern.sub(proper, text)
        return text

    def _ensure_sentence_capitalization(self, text: str) -> str:
        """Capitalizes the first character of each sentence."""
        if not text:
            return ""

        # Split by sentence end boundaries: (. / ? / ! / \n)
        def _cap_match(match):
            prefix = match.group(1)  # punctuation and whitespace
            char = match.group(2)    # letter to capitalize
            return prefix + char.upper()

        # Capitalize very first letter of text
        text = text[0].upper() + text[1:] if len(text) > 0 else text

        # Capitalize letters following [.?!]\s+ or newline
        text = re.sub(r"([.?!]\s+|\n\s*)([a-z])", _cap_match, text)

        return text

    def _ensure_terminal_punctuation(self, text: str) -> str:
        """Ensures the final sentence concludes with a valid terminal mark."""
        if not text:
            return ""

        # If it already ends with punctuation, return
        if text[-1] in {".", "?", "!", ":", ";", "\"", "'", "\n"}:
            return text

        # If it looks like a question (starts with What, Why, How, Is, Can, Could, etc.)
        lower_first = text.split()[0].lower() if text.split() else ""
        question_starters = {
            "what", "why", "how", "when", "where", "who", "which",
            "is", "are", "can", "could", "would", "should", "do", "does", "did"
        }
        if lower_first in question_starters:
            return text + "?"

        return text + "."
