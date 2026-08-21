# Slice 6 offline model cache

The `tesseract_best/` directory is a project-controlled, offline cache of the
seven required Tesseract trained-data files (`ara`, `jpn`, `jpn_vert`,
`chi_sim`, `chi_tra`, `eng`, and `osd`). `manifest.json` records the source URL,
Apache-2.0 license, byte size, and SHA-256 for every file. Runtime code must
verify this manifest before using a model and must not download implicitly.

Verify without network access:

```sh
python3 scripts/acquire_transcription_models.py \
  tracked/LateLetterResearch/transcription-model-cache
```

The optional PaddleOCR and EasyOCR/Surya adapters are profile-only until their
runtime and model bytes are separately pinned. They are never allowed to fetch
weights during recognition.

The `emoji/` directory pins Unicode 17.0 `emoji-test.txt` and the Noto Color
Emoji font. The emoji adapter enumerates fully-qualified sequences from that
file and matches shaped font masks against a geometry-owned run strip; it does
not accept a caller-supplied sequence list or transcript hint.

The `fonts/` directory pins the corpus-v2 renderer fonts: Noto Sans Mono
variable (fixed-cell ASCII), Noto Sans CJK JP (kana/Kanji/fullwidth), and Noto
Sans Arabic (joined Arabic). Each byte hash, source URL, and OFL-1.1 license is
recorded in `manifest.json`; corpus generation refuses an unverified or missing
font.

Primary sources and license notes are in `model-sources.txt`.
