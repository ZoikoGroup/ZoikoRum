"""Message abuse detection (Trust & Safety: off-platform circumvention and harassment). Advisory only.

A message is normalised before it is checked, so that common disguises do not slip through: Unicode compatibility
forms and full-width letters, zero-width characters, leetspeak (``1d10t``, ``p@ypal``), letters spaced or dotted apart
(``w h a t s a p p``), spelled-out addresses (``name at gmail dot com``) and phone numbers written in words or broken
up with separators. Matches only *flag* the message for Trust & Safety (MESSAGE_FLAGGED, a Level 0 review); nobody is
blocked or banned automatically, and the message is delivered unchanged.

Extra terms are configurable without a release: ZK_MESSAGING_ABUSE_TERMS (harassment) and
ZK_MESSAGING_CIRCUMVENTION_TERMS (taking contact or payment off the platform), JSON lists, matched after the same
normalisation.
"""

from __future__ import annotations

import re
import unicodedata

from zoikorum.config import get_settings

LEET = str.maketrans({"0": "o", "1": "i", "!": "i", "|": "i", "3": "e", "4": "a", "@": "a", "5": "s", "7": "t", "+": "t",
                      "8": "b", "9": "g"})
ZERO_WIDTH = re.compile("[​-‏⁠﻿­]")
NUMBER_WORDS = {"zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
                "eight": "8", "nine": "9"}

HARASSMENT = ("kill you", "hurt you", "idiot", "stupid", "fuck you", "moron", "retard", "piece of shit", "shut up",
              "i know where you live", "watch your back", "you will regret", "worthless")
CONTACT_APPS = ("whatsapp", "telegram", "signal app", "wechat", "skype", "discord", "viber", "snapchat", "kik", "line app")
CONTACT_PHRASES = ("text me", "call me on", "dm me", "message me on", "reach me on", "add me on", "my number is", "my email is",
                   "contact me directly", "email me at", "find me on")
OFF_PLATFORM_PAYMENT = ("paypal", "venmo", "zelle", "cash app", "cashapp", "western union", "moneygram", "wire it directly",
                        "bank transfer directly", "pay me directly", "pay outside", "outside the platform", "off platform",
                        "off the platform", "avoid the fee", "avoid the fees", "skip the fee", "skip the platform", "crypto wallet",
                        "bitcoin", "usdt", "iban")
PAYMENT_LINKS = re.compile(r"(?:paypal\.me|cash\.app|venmo\.com|buy\.stripe\.com|wise\.com|revolut\.me)/", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}", re.I)
SPELLED_EMAIL = re.compile(r"\b[\w.+-]{2,}\s*[\[(]?\s*at\s*[\])]?\s*[\w-]{2,}\s*[\[(]?\s*dot\s*[\])]?\s*(?:com|net|org|io|co|me|uk|in)\b")
PHONE = re.compile(r"(?<!\w)\+?\d[\d ()./-]{8,}\d(?!\w)")
SEPARATED = re.compile(r"\b(?:[a-z0-9][\s._*-]+){2,}[a-z0-9]\b")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[ t]\d{1,2})?")


def _fold(text: str) -> str:
    return ZERO_WIDTH.sub("", unicodedata.normalize("NFKC", text)).lower()


def _words(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text)).strip()


def _words_to_digits(text: str) -> str:
    """"five five five one two three four five six seven" -> "5551234567" when at least seven number words in a row."""
    tokens = re.split(r"(\s+|[-,.])", text)
    out: list[str] = []
    run: list[str] = []

    def flush():
        if len([t for t in run if t.strip(" -,.")]) >= 7:
            out.append("".join(NUMBER_WORDS.get(t, "") for t in run))
        else:
            out.extend(run)
        run.clear()
    for t in tokens:
        if t in NUMBER_WORDS or (run and not t.strip(" -,.")):
            run.append(t)
        else:
            flush()
            out.append(t)
    flush()
    return "".join(out)


def normalise(text: str) -> tuple[str, str, str]:
    """(folded, leet-decoded words, de-spaced words) views of the text. The last joins runs of single characters
    written apart ("w h a t s a p p", "p.a.y.p.a.l") back into words."""
    folded = _fold(text)
    leet = folded.translate(LEET)
    joined = SEPARATED.sub(lambda m: re.sub(r"[\s._*-]+", "", m.group(0)), leet)
    return folded, _words(leet), _words(joined)


def _has(terms, *views: str) -> bool:
    for term in terms:
        t = _words(_fold(term).translate(LEET))
        if t and any(f" {t} " in f" {v} " for v in views if v):
            return True
    return False


def _phone(text: str) -> bool:
    for m in PHONE.finditer(text):
        found = m.group(0).strip()
        if DATE.fullmatch(found):
            continue  # a date and time, not a number
        if sum(ch.isdigit() for ch in found) >= 9:
            return True
    return False


def signals(body: str) -> list[str]:
    """Reason codes for a message (advisory): CONTACT_EMAIL, CONTACT_PHONE, CONTACT_HANDLE, OFF_PLATFORM_PAYMENT,
    POSSIBLE_HARASSMENT."""
    s = get_settings()
    folded, words, joined = normalise(body)
    flags: list[str] = []
    email = EMAIL.search(folded)
    if email or SPELLED_EMAIL.search(re.sub(r"\s+", " ", folded)):
        flags.append("CONTACT_EMAIL")
    if _phone(folded) or _phone(_words_to_digits(re.sub(r"\s+", " ", folded))):
        flags.append("CONTACT_PHONE")
    handle = re.search(r"(?<![\w@.])@[a-z0-9_]{3,}\b", folded) and not email
    if _has(CONTACT_APPS, words, joined) or _has(CONTACT_PHRASES, words) or handle:
        flags.append("CONTACT_HANDLE")
    if PAYMENT_LINKS.search(folded) or _has((*OFF_PLATFORM_PAYMENT, *s.messaging_circumvention_terms), words, joined):
        flags.append("OFF_PLATFORM_PAYMENT")
    if _has((*HARASSMENT, *s.messaging_abuse_terms), words, joined):
        flags.append("POSSIBLE_HARASSMENT")
    return flags
