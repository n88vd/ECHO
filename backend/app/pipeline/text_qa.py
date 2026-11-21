"""Transcript quality gate, credential redaction and trigger-phrase detection."""

import re
import unicodedata
from dataclasses import dataclass

FILLERS = {
    "hmm", "hm", "mm", "mhm", "uh", "um", "umm", "ah", "aah", "oh", "ok", "okay", "haan", "han", "ha", "achha", "acha",
    "accha", "ji", "yes", "no", "na", "nahi", "hello", "hi", "huh", "ya", "yeah", "haa", "हाँ", "हां", "हम्म", "अच्छा",
    "ओके", "जी", "ம்ம்", "சரி", "ಹೌದು", "అవును", "ശരി", "हो",
}
HALLUCINATIONS = [
    "thank you for watching", "thanks for watching", "please subscribe", "like and subscribe", "subtitles by",
    "transcribed by", "copyright", "www.", "music playing", "[music]", "(music)", "♪",
]
REMEMBER_PATTERNS = [
    r"\becho[,!. ]+\s*(please\s+)?remember (this|that)\b",
    r"\becho[,!. ]+\s*(isko|ise|ye|yeh)?\s*yaad rakh(na|o|iye|ना)?\b",
    r"\becho[,!. ]+\s*note (this|that)\b",
    r"(एको|इको|ईको|ऐको)[,!. ]*\s*(इसे|इसको|ये|यह)?\s*याद\s*रख",
    r"(எக்கோ|ஈகோ)[,!. ]*\s*.{0,20}(நினைவில் வை|ஞாபகம் வை)",
    r"(ఎకో|ఇకో)[,!. ]*\s*.{0,20}గుర్తు",
    r"(ಎಕೋ|ಇಕೋ)[,!. ]*\s*.{0,20}ನೆನಪಿ",
    r"\bremember this[, ]+echo\b",
]
_REMEMBER = [re.compile(p, re.I) for p in REMEMBER_PATTERNS]

_REDACTIONS = [
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[card]"),
    (re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"), "[aadhaar]"),
    (re.compile(r"\b(otp|one[- ]time password|pin|cvv)\b[^0-9]{0,20}(\d[\s-]?){4,8}", re.I), r"\1 [redacted]"),
    (re.compile(r"\b(password|passcode|pass word)\b\s*(is|:)?\s*\S+", re.I), r"\1 [redacted]"),
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "[pan]"),
]


@dataclass
class TextQuality:
    score: float
    reason: str


def _norm_words(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text.lower())
    return re.findall(r"[\w\u0900-\u0DFF']+", text)


def repetition_ratio(words: list[str], n: int = 3) -> float:
    if len(words) < n * 2:
        return 0.0
    grams = [tuple(words[i : i + n]) for i in range(len(words) - n + 1)]
    return 1 - len(set(grams)) / len(grams)


def assess(text: str, duration_s: float, lang_prob: float | None, snr_db: float | None, media: bool) -> TextQuality:
    words = _norm_words(text)
    if not words:
        return TextQuality(0.0, "empty")
    content = [w for w in words if w not in FILLERS]
    if not content:
        return TextQuality(0.1, "fillers_only")
    low = text.lower()
    if any(h in low for h in HALLUCINATIONS):
        return TextQuality(0.15, "hallucination_phrase")
    rep = repetition_ratio(words)
    if rep > 0.5:
        return TextQuality(0.2, "repetition")
    score = 0.9
    if duration_s > 0.5:
        cps = len(text.replace(" ", "")) / duration_s
        if cps > 35 or cps < 1.0:
            score -= 0.35
    if lang_prob is not None and lang_prob < 0.4:
        score -= 0.25 if (snr_db is not None and snr_db < 10) else 0.1
    if snr_db is not None and snr_db < 5:
        score -= 0.15
    if len(content) == 1:
        score -= 0.25
    if media:
        score -= 0.2
    score -= rep * 0.4
    return TextQuality(round(max(0.0, min(1.0, score)), 3), "ok")


def redact(text: str) -> tuple[str, bool]:
    out = text
    for pat, rep in _REDACTIONS:
        out = pat.sub(rep, out)
    return out, out != text


def has_remember_trigger(text: str) -> bool:
    return any(p.search(text) for p in _REMEMBER)
