# Transcription corpus v2

This corpus is the verified-font successor to `tests/fixtures/transcription/corpus.json`.
Corpus v1 and `recognizer-benchmark-v4-geometry.json` remain historical evidence and are not
rewritten.

`build_corpus_v2.py` renders release positives only after cmap coverage succeeds against the
project-controlled, hash-pinned font cache. The former fallback-box examples are retained as
development `fail_closed` fixtures with `unicode_visual_collision`; they are never positive
recognition evidence.

Validate the corpus with:

```sh
PYTHONPATH=src python3 -c \
  'from lateletter.transcription.corpus import validate_corpus; print(validate_corpus("tests/fixtures/transcription-v2/corpus-v2.json"))'
```

Generate benchmark v5 with networking disabled:

```sh
PYTHONPATH=src python3 scripts/benchmark_transcription_recognizers.py \
  tests/fixtures/transcription-v2/corpus-v2.json \
  tracked/LateLetterResearch/transcription-model-cache \
  tests/fixtures/transcription-v2/recognizer-benchmark-v5.json \
  --emoji-max-sequences 1000
```

The benchmark consumes every geometry-owned run. Fixed-lattice sources provide complete
source-width row strips; Tesseract is evaluated through separate PSM/language profiles. The
benchmark remains blocked until all positive NFC targets appear in deterministic offline top-k.
