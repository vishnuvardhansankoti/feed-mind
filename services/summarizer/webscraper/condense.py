"""Step one of two-step summarization: extractive filtering with spaCy.

The LLM writes a better summary when it is handed less text, so this module
scores every sentence by the frequency of the content words it contains and
keeps only the top slice. The LLM then rewrites that extract into prose.

    long article  --[this module]-->  top 25% of sentences  --[LLM]-->  summary

Scoring, in order:
    1. collect content words (PROPN, ADJ, NOUN, VERB), minus stop words
    2. count them, normalized against the most frequent one
    3. score each sentence as the sum of its word scores
    4. keep the highest-scoring `select_ratio` of sentences
    5. restore the original sentence order so the extract still reads

spaCy is an optional dependency, imported lazily:

    uv pip install --python .venv/bin/python spacy
    .venv/bin/python -m spacy download en_core_web_sm
"""

from __future__ import annotations

import math
from collections import Counter
from string import punctuation

from .errors import CondenseError

DEFAULT_SPACY_MODEL = "en_core_web_sm"
DEFAULT_SELECT_RATIO = 0.25

# Parts of speech that carry the meaning of a sentence.
CONTENT_POS = {"PROPN", "ADJ", "NOUN", "VERB"}

# Sentence scores are divided by sqrt(token count). Summing raw word scores
# rewards length for its own sake - a 60-word sentence has six times as many
# chances to accumulate points as a 10-word one - while dividing by the full
# count inverts the bias and floats keyword-dense fragments ("THE HISTORY OF
# THE WEB .") to the top. The square root damps the length advantage without
# reversing it.
LENGTH_NORMALIZER = math.sqrt

# Sentences shorter than this are headings, captions and citation titles.
MIN_SENTENCE_TOKENS = 8

# spaCy's default parser cap is 1,000,000 characters; stay well under it.
MAX_PARSE_CHARS = 200_000

_MODEL_CACHE = {}

INSTALL_HINT = (
    "spaCy is not installed - run: uv pip install spacy "
    "&& python -m spacy download en_core_web_sm"
)


def load_model(name=DEFAULT_SPACY_MODEL):
    """Load and cache a spaCy pipeline."""
    if name in _MODEL_CACHE:
        return _MODEL_CACHE[name]

    try:
        import spacy
    except ImportError as error:
        raise CondenseError(INSTALL_HINT) from error

    try:
        nlp = spacy.load(name)
    except OSError as error:
        raise CondenseError(
            f"spaCy model {name!r} is not installed - run: "
            f"python -m spacy download {name}"
        ) from error

    _MODEL_CACHE[name] = nlp
    return nlp


def word_frequencies(doc):
    """Normalized frequency of every content word in the document."""
    keywords = [
        token.text.lower()
        for token in doc
        if not token.is_stop
        and token.text not in punctuation
        and token.pos_ in CONTENT_POS
    ]
    counts = Counter(keywords)
    if not counts:
        return counts

    highest = max(counts.values())
    for word in counts:
        counts[word] /= highest
    return counts


def score_sentences(doc, frequencies):
    """Score each sentence by its word scores, damped for length.

    Sentences below MIN_SENTENCE_TOKENS are skipped outright - they are
    headings and citation titles, which are keyword-dense but say nothing.
    """
    scores = {}
    for sentence in doc.sents:
        tokens = [token for token in sentence if not token.is_space]
        if len(tokens) < MIN_SENTENCE_TOKENS:
            continue
        total = sum(
            frequencies[token.text.lower()]
            for token in tokens
            if token.text.lower() in frequencies
        )
        if total:
            scores[sentence] = total / LENGTH_NORMALIZER(len(tokens))
    return scores


def extractive_filter(text, select_ratio=DEFAULT_SELECT_RATIO,
                      model=DEFAULT_SPACY_MODEL):
    """Keep the top `select_ratio` of sentences, in their original order.

    Returns the text unchanged when it is too short to be worth filtering or
    holds nothing scoreable.
    """
    if not text.strip():
        return text
    if not 0 < select_ratio <= 1:
        raise CondenseError("select_ratio must be between 0 and 1.")

    doc = load_model(model)(text[:MAX_PARSE_CHARS])
    frequencies = word_frequencies(doc)
    if not frequencies:
        return text  # nothing scoreable - hand the original to the LLM

    scores = score_sentences(doc, frequencies)
    if not scores:
        return text  # every sentence was below MIN_SENTENCE_TOKENS

    sentences = list(doc.sents)
    keep = max(1, int(len(sentences) * select_ratio))
    if keep >= len(sentences):
        return text

    top = set(sorted(scores, key=scores.get, reverse=True)[:keep])
    return " ".join(
        sentence.text.strip() for sentence in sentences if sentence in top
    )


def compression_note(original, condensed, model=DEFAULT_SPACY_MODEL):
    """A one-line report of what the filter did, for stderr."""
    before, after = len(original), len(condensed)
    percent = (after / before * 100) if before else 100
    return (
        f"spaCy ({model}) condensed {before:,} -> {after:,} chars "
        f"({percent:.0f}% kept)"
    )
