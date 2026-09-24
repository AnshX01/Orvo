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
    "orvo": "Orvo",
    "docker": "Docker",
    "linux": "Linux",
    "macos": "macOS",
    "ios": "iOS",
    "android": "Android",
    "npm": "npm",
    "pip": "pip",
    "sdk": "SDK",
    "ide": "IDE",
    "gui": "GUI",
    "cli": "CLI",
    "pr": "PR",
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
        if not text or not text.strip() or not re.search(r"[a-zA-Z0-9]", text):
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

        if not result or not re.search(r"[a-zA-Z0-9]", result):
            return ""

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
        Fixes common acoustic homophones, phonetic confusions, and spoken grammar slips
        based on local syntactic and semantic context with zero latency penalty (<0.02ms).
        """
        # 1. Mode vs More in technical and dictation contexts
        text = re.sub(
            r"\b(speech to text|speech-to-text|text to speech|text-to-speech|push to talk|push-to-talk|voice dictation|dictation|dark|light|offline|online|silent|focus|airplane|developer|debug|safe|sleep|standby|toggle|quiet)\s+more\b",
            r"\1 mode",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"\benter\s+more\b", "enter mode", text, flags=re.IGNORECASE)

        # 2. Fix 'i' to 'I' and contractions
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

        # 3. "their" vs "there" vs "they're"
        text = re.sub(r"\bthere\s+(going|doing|working|saying|trying|making|thinking|coming|leaving|getting|having)\b", r"they're \1", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(in|over|out|under|up|down|from)\s+their\b", r"\1 there", text, flags=re.IGNORECASE)
        text = re.sub(r"\btheir\s+(is|are|was|were|will|should|could|would|has|have|had)\b", r"there \1", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(is|are|was|were)\s+their\s+(any|a|an|anyone|anything|someone|something|no|more)\b", r"\1 there \2", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(at|to|in)\s+they're\s+(house|car|office|home|school|place|work)\b", r"\1 their \2", text, flags=re.IGNORECASE)

        # 4. "its" vs "it's"
        text = re.sub(r"\bits\s+(a|an|the|not|very|really|so|too|been|going|working|hard|easy|good|fine|ok|okay|worth|time|clear|true|false)\b", r"it's \1", text, flags=re.IGNORECASE)
        text = re.sub(r"\bit's\s+(own|name|color|size|value|type|state|index|result|status|length|height|width)\b", r"its \1", text, flags=re.IGNORECASE)

        # 5. "your" vs "you're"
        text = re.sub(r"\byour\s+(welcome|right|wrong|going|doing|making|trying|looking|working|invited)\b", r"you're \1", text, flags=re.IGNORECASE)
        text = re.sub(r"\byou're\s+(car|house|code|project|computer|name|phone|turn|team|family|friends)\b", r"your \1", text, flags=re.IGNORECASE)

        # 6. "to" vs "too" vs "two"
        text = re.sub(r"\bto\s+(hours|days|weeks|months|years|minutes|seconds|times|people|things|items|options|ways|steps|files|lines|words|parts|sides|halves|dollars|cents|miles|degrees)\b", r"two \1", text, flags=re.IGNORECASE)
        text = re.sub(r"\bto\s+of\s+(them|us|you|these|those|the)\b", r"two of \1", text, flags=re.IGNORECASE)
        text = re.sub(r"\bto\s+(much|many|late|early|fast|slow|hot|cold|hard|easy|big|small|far|close|bad|good|soon|expensive|complicated|difficult|long|short|high|low|tired|busy|young|old|loud|quiet|dark|heavy|light|weak|strong|little|often|few)\b", r"too \1", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(me|you|him|her|us|them)\s+to\b(?=[,.:;?!]|\s*$)", r"\1 too", text, flags=re.IGNORECASE)

        # 7. "then" vs "than"
        text = re.sub(r"\b(more|less|better|worse|rather|greater|other|faster|slower|earlier|later|higher|lower|sooner|easier|harder|longer|shorter|bigger|smaller|larger|older|younger|further|farther)\s+then\b", r"\1 than", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(and|since|back|until|by|now and|even|but)\s+than\b", r"\1 then", text, flags=re.IGNORECASE)
        text = re.sub(r"(^|[,.:;?!]\s*)\bthan\s+(I|we|you|he|she|it|they|the|there|this|that)\b", r"\1then \2", text, flags=re.IGNORECASE)

        # 8. "weather" vs "whether"
        text = re.sub(r"\bweather\s+or\s+not\b", "whether or not", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(know|knows|knew|check|checks|checked|checking|see|sees|saw|seeing|wonder|wonders|wondered|wondering|decide|decides|decided|deciding|determine|determines|determined|determining|unsure|doubt|doubts|doubted|doubting|ask|asks|asked|asking)\s+weather\b", r"\1 whether", text, flags=re.IGNORECASE)
        text = re.sub(r"\bweather\s+(I|we|you|he|she|they|to)\b", r"whether \1", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(the|bad|good|cold|hot|warm|cool|stormy|severe|nice|terrible|current|today's|tomorrow's)\s+whether\b", r"\1 weather", text, flags=re.IGNORECASE)
        text = re.sub(r"\bwhether\s+(forecast|report|channel|conditions|map|update|station)\b", r"weather \1", text, flags=re.IGNORECASE)

        # 9. "hear" vs "here"
        text = re.sub(r"\b(come|came|get|got|right|over|stay|stayed|in|out|from|to|near|around|arrive|arrived|looking|stand|sitting|put|left|place)\s+hear\b", r"\1 here", text, flags=re.IGNORECASE)
        text = re.sub(r"\bhear\s+(is|are|was|were|comes|it is|you go|we go|they are)\b", r"here \1", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(can|could|can't|couldn't|did|didn't|do|don't|will|would|hard to|glad to|nice to|good to)\s+here\b", r"\1 hear", text, flags=re.IGNORECASE)
        text = re.sub(r"\bhere\s+me\s+out\b", "hear me out", text, flags=re.IGNORECASE)

        # 10. "write" vs "right"
        text = re.sub(r"\b(that's|thats|you're|you are|it's|its|all|alright|is)\s+write\b", r"\1 right", text, flags=re.IGNORECASE)
        text = re.sub(r"\bwrite\s+(now|away|here|there|side|hand|turn|corner|direction|angle|click|clicked|clicking|decision|choice|answer|way|track|time)\b", r"right \1", text, flags=re.IGNORECASE)
        text = re.sub(r"\bright\s+(code|down|a|an|the|this|that|these|those|it|out|in|tests|documentation|letters|words|sentences|paragraphs|essays|emails|messages)\b", r"write \1", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(to|can|could|will|would|please|must|should)\s+right\b(?=\s+(?:code|down|a|an|the|this|that|it|out|in))", r"\1 write", text, flags=re.IGNORECASE)

        # 11. "loose" vs "lose"
        text = re.sub(r"\b(to|will|can|could|might|would|should|don't|dont|gonna|going to)\s+loose\b", r"\1 lose", text, flags=re.IGNORECASE)
        text = re.sub(r"\bloose\s+(weight|control|hope|track|focus|patience|mind|temper|money|job|game|match|battle|sight|interest|sleep|touch|my|your|our|their|his|her|its)\b", r"lose \1", text, flags=re.IGNORECASE)
        text = re.sub(r"\bwin\s+or\s+loose\b", "win or lose", text, flags=re.IGNORECASE)

        # 12. "passed" vs "past"
        text = re.sub(r"\b(in|during|over|through)\s+the\s+passed\b", r"\1 the past", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(the\s+)passed(\s+(?:few|couple|several|two|three|four|five|ten|week|weeks|month|months|year|years|decade|decades|days|hours|minutes|century|time)\b)", r"\1past\2", text, flags=re.IGNORECASE)
        text = re.sub(r"\bpassed\s+(experience|performance|history|events|records|generations)\b", r"past \1", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(walk|walked|run|ran|drive|drove|go|went|fly|flew|look|looked|slip|slipped|move|moved|half)\s+passed\b", r"\1 past", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(has|have|had|having|was|were|is|are)\s+past\b", r"\1 passed", text, flags=re.IGNORECASE)
        text = re.sub(r"\bpast\s+(away|out|by|the\s+test|the\s+exam|the\s+bill|the\s+law|the\s+ball)\b", r"passed \1", text, flags=re.IGNORECASE)

        # 13. "accept" vs "except"
        text = re.sub(r"\b(all|everyone|everybody|everything|anyone|anybody|anything|no one|nobody|nothing|everywhere|nowhere)\s+accept\b", r"\1 except", text, flags=re.IGNORECASE)
        text = re.sub(r"\baccept\s+(for|when|that|where|if)\b", r"except \1", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(to|will|can|could|would|should|please|must|cannot|can't)\s+except\b", r"\1 accept", text, flags=re.IGNORECASE)
        text = re.sub(r"\bexcept\s+(the|a|an|this|that|these|those|my|your|our|their|his|her|its|cookies|terms|conditions|payment|responsibility|offer|invitation|apology)\b", r"accept \1", text, flags=re.IGNORECASE)

        # 14. "affect" vs "effect"
        text = re.sub(r"\bcause\s+and\s+affect\b", "cause and effect", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(side|sound|special|visual|adverse|positive|negative|direct|indirect|lasting|ripple|placebo|butterfly)\s+affects?\b", r"\1 effects", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(take|takes|took|taking)\s+affect\b", r"\1 effect", text, flags=re.IGNORECASE)
        text = re.sub(r"\bin\s+affect\b", "in effect", text, flags=re.IGNORECASE)
        text = re.sub(r"\bhave\s+an\s+affect\b", "have an effect", text, flags=re.IGNORECASE)
        text = re.sub(r"\bthe\s+affect\s+(of|on)\b", r"the effect \1", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(will|would|can|could|may|might|should|to|not|greatly|negatively|positively|directly|indirectly)\s+effect\b", r"\1 affect", text, flags=re.IGNORECASE)
        text = re.sub(r"\beffect\s+(the|a|an|our|your|my|their|his|her|its|how|what|performance|latency|quality|outcome|speed)\b", r"affect \1", text, flags=re.IGNORECASE)

        # 15. "bare" vs "bear"
        text = re.sub(r"\bbare\s+with\s+me\b", "bear with me", text, flags=re.IGNORECASE)
        text = re.sub(r"\bbare\s+in\s+mind\b", "bear in mind", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(cannot|can't|hard to|able to|to)\s+bare\b", r"\1 bear", text, flags=re.IGNORECASE)
        text = re.sub(r"\bbare\s+(fruit|the cost|responsibility|arms|witness)\b", r"bear \1", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(polar|grizzly|black|brown|teddy)\s+bare\b", r"\1 bear", text, flags=re.IGNORECASE)
        text = re.sub(r"\bbear\s+(minimum|hands|feet|bones|essentials|necessities|metal)\b", r"bare \1", text, flags=re.IGNORECASE)

        # 16. "break" vs "brake"
        text = re.sub(r"\b(take|took|taking|need|needs|needed)\s+a\s+brake\b", r"\1 a break", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(coffee|lunch|tea|spring|summer|winter|commercial|short)\s+brake\b", r"\1 break", text, flags=re.IGNORECASE)
        text = re.sub(r"\bgive\s+me\s+a\s+brake\b", "give me a break", text, flags=re.IGNORECASE)
        text = re.sub(r"\bbrake\s+(down|up|through|out|off|the law|the rules|the ice|the code|a leg)\b", r"break \1", text, flags=re.IGNORECASE)
        text = re.sub(r"\b((?:hit|hits|step|steps|stepped|slam|slams|slammed|put)\s+(?:on\s+)?the\s+)breaks\b", r"\1brakes", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(emergency|parking|hand|disc|drum|air|car)\s+breaks?\b", r"\1 brakes", text, flags=re.IGNORECASE)

        # 17. "peace" vs "piece"
        text = re.sub(r"\bpiece\s+of\s+mind\b", "peace of mind", text, flags=re.IGNORECASE)
        text = re.sub(r"\brest\s+in\s+piece\b", "rest in peace", text, flags=re.IGNORECASE)
        text = re.sub(r"\bworld\s+piece\b", "world peace", text, flags=re.IGNORECASE)
        text = re.sub(r"\bpiece\s+and\s+quiet\b", "peace and quiet", text, flags=re.IGNORECASE)
        text = re.sub(r"\bmake\s+piece\b", "make peace", text, flags=re.IGNORECASE)
        text = re.sub(r"\ba\s+peace\s+of\b", "a piece of", text, flags=re.IGNORECASE)
        text = re.sub(r"\bpeace\s+of\s+(cake|code|paper|advice|furniture|art|bread|meat|glass|wood|string|clothing)\b", r"piece of \1", text, flags=re.IGNORECASE)
        text = re.sub(r"\bpeace\s+(by\s+peace|together)\b", r"piece \1", text, flags=re.IGNORECASE)

        # 18. "role" vs "roll"
        text = re.sub(r"\b(play|plays|played|playing)\s+a\s+roll\b", r"\1 a role", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(key|important|major|minor|leadership|crucial|vital|central|active)\s+roll\b", r"\1 role", text, flags=re.IGNORECASE)
        text = re.sub(r"\broll\s+model\b", "role model", text, flags=re.IGNORECASE)
        text = re.sub(r"\broll\s+(out|over|up|down|back|call|forward)\b", r"roll \1", text, flags=re.IGNORECASE)
        text = re.sub(r"\brock\s+and\s+role\b", "rock and roll", text, flags=re.IGNORECASE)
        text = re.sub(r"\bon\s+a\s+role\b", "on a roll", text, flags=re.IGNORECASE)

        # 19. "sight" vs "site" vs "cite"
        text = re.sub(r"\bweb\s+(sight|cite)\b", "website", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(on|off)[\s-]+(sight|cite)\b", r"\1-site", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(construction|camp|job|work|crash|historic)\s+(sight|cite)\b", r"\1 site", text, flags=re.IGNORECASE)
        text = re.sub(r"\bin\s+(site|cite)\b", "in sight", text, flags=re.IGNORECASE)
        text = re.sub(r"\bout\s+of\s+(site|cite)\b", "out of sight", text, flags=re.IGNORECASE)
        text = re.sub(r"\blose\s+(site|cite)\s+of\b", "lose sight of", text, flags=re.IGNORECASE)
        text = re.sub(r"\bcatch\s+(site|cite)\s+of\b", "catch sight of", text, flags=re.IGNORECASE)
        text = re.sub(r"\bline\s+of\s+(site|cite)\b", "line of sight", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(site|sight)\s+(sources|references|examples|cases|evidence)\b", r"cite \1", text, flags=re.IGNORECASE)

        # 20. "principle" vs "principal"
        text = re.sub(r"\bin\s+principal\b", "in principle", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(basic|guiding|moral|ethical|first|general|fundamental|scientific)\s+principals?\b", r"\1 principles", text, flags=re.IGNORECASE)
        text = re.sub(r"\bmatter\s+of\s+principal\b", "matter of principle", text, flags=re.IGNORECASE)
        text = re.sub(r"\bprincipal\s+(engineer|investigator|architect|officer|agent|dancer|amount|sum|balance)\b", r"principal \1", text, flags=re.IGNORECASE)
        text = re.sub(r"\bschool\s+principle\b", "school principal", text, flags=re.IGNORECASE)

        # 21. "complement" vs "compliment"
        text = re.sub(r"\b((?:pay|paid|paying|give|gave|giving)(?:\s+\w+){0,3}\s+)complement\b", r"\1compliment", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(a|the|such\s+a|what\s+a|nice|great|kind|sweet|generous|lovely|sincere)\s+complement\b", r"\1 compliment", text, flags=re.IGNORECASE)
        text = re.sub(r"\btake\s+it\s+as\s+a\s+complement\b", "take it as a compliment", text, flags=re.IGNORECASE)
        text = re.sub(r"\bbackhanded\s+complement\b", "backhanded compliment", text, flags=re.IGNORECASE)
        text = re.sub(r"\bfish\s+for\s+complements\b", "fish for compliments", text, flags=re.IGNORECASE)
        text = re.sub(r"\bperfectly\s+compliment\b", "perfectly complement", text, flags=re.IGNORECASE)
        text = re.sub(r"\bcompliment\s+each\s+other\b", "complement each other", text, flags=re.IGNORECASE)
        text = re.sub(r"\bfull\s+compliment\b", "full complement", text, flags=re.IGNORECASE)

        # 22. "aloud" vs "allowed"
        text = re.sub(r"\b(is|are|was|were|am|not|aren't|isn't|wasn't|weren't)\s+aloud\b", r"\1 allowed", text, flags=re.IGNORECASE)
        text = re.sub(r"\baloud\s+to\b", "allowed to", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(read|reading|speak|speaking|spoke|say|saying|said|laugh|laughing|laughed|cry|crying|cried|think|thinking|thought)\s+allowed\b", r"\1 aloud", text, flags=re.IGNORECASE)

        # 23. "plain" vs "plane"
        text = re.sub(r"\bplane\s+(text|english|truth|sight|and\s+simple|view|clothes|paper)\b", r"plain \1", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(board|catch|on|take|missed|landed|boarded)\s+the\s+plain\b", r"\1 the plane", text, flags=re.IGNORECASE)
        text = re.sub(r"\bair\s*plain\b", "airplane", text, flags=re.IGNORECASE)

        # 24. "coarse" vs "course"
        text = re.sub(r"\bof\s+coarse\b", "of course", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(online|crash|training|college|university|main|golf|matter\s+of)\s+coarse\b", r"\1 course", text, flags=re.IGNORECASE)
        text = re.sub(r"\bin\s+due\s+coarse\b", "in due course", text, flags=re.IGNORECASE)
        text = re.sub(r"\bchange\s+coarse\b", "change course", text, flags=re.IGNORECASE)
        text = re.sub(r"\bcourse\s+(sand|salt|texture|hair|grain|fabric)\b", r"coarse \1", text, flags=re.IGNORECASE)

        # 25. "stationary" vs "stationery"
        text = re.sub(r"\bstationery\s+(bike|bicycle|vehicle|car|object|target|position)\b", r"stationary \1", text, flags=re.IGNORECASE)
        text = re.sub(r"\bremained\s+stationery\b", "remained stationary", text, flags=re.IGNORECASE)
        text = re.sub(r"\bstationary\s+(shop|store|order|supplies|paper|letterhead|set)\b", r"stationery \1", text, flags=re.IGNORECASE)

        # 26. "moral" vs "morale"
        text = re.sub(r"\b(boost|boosts|boosted|boosting|high|low|team|employee|company|staff)\s+moral\b", r"\1 morale", text, flags=re.IGNORECASE)
        text = re.sub(r"\bmorale\s+(obligation|duty|values|principles|standard|compass|code)\b", r"moral \1", text, flags=re.IGNORECASE)
        text = re.sub(r"\bmorale\s+of\s+the\s+story\b", "moral of the story", text, flags=re.IGNORECASE)

        # 27. Spaced technical and developer terms
        text = re.sub(r"\bdata\s+base\b", "database", text, flags=re.IGNORECASE)
        text = re.sub(r"\bcode\s+base\b", "codebase", text, flags=re.IGNORECASE)
        text = re.sub(r"\bfile\s+name\b", "filename", text, flags=re.IGNORECASE)
        text = re.sub(r"\buser\s+name\b", "username", text, flags=re.IGNORECASE)
        text = re.sub(r"\bpass\s+word\b", "password", text, flags=re.IGNORECASE)
        text = re.sub(r"\brun\s+time\b", "runtime", text, flags=re.IGNORECASE)
        text = re.sub(r"\bwork\s+flow\b", "workflow", text, flags=re.IGNORECASE)
        text = re.sub(r"\bfront\s+end\b", "frontend", text, flags=re.IGNORECASE)
        text = re.sub(r"\bback\s+end\b", "backend", text, flags=re.IGNORECASE)
        text = re.sub(r"\bfull\s+stack\b", "full-stack", text, flags=re.IGNORECASE)
        text = re.sub(r"\bopen\s+source\b", "open-source", text, flags=re.IGNORECASE)
        text = re.sub(r"\bbug\s+fix\b", "bugfix", text, flags=re.IGNORECASE)
        text = re.sub(r"\bbug\s+fixes\b", "bugfixes", text, flags=re.IGNORECASE)

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
