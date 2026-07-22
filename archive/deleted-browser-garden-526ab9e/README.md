# Deleted browser Garden preservation package

This tracked directory preserves the complete runnable browser Garden package
from commit `526ab9e9a281d9505be467501ffc2abe74eca40b`, the direct parent of
`520f27ba78ae95f41661ba749ec22859d6d53ad8`.

It is evidence and a visual reference. Production must not import this package
or revive its `GardenVisualState` gameplay, layout, collision, persistence, or
hit-test ownership. The supported renderer must manually port the presentation
features while reading the current canonical projection.

## Contents

- `viewer-bnw.html` — complete rich browser viewer/Garden before deletion
- `web/` — the exact semantic input, program, runtime, and world dependencies
- `sealed_demo.lateletter` — exact tracked synthetic sealed demo at the source commit
- `test_fixture.lateletter` — exact tracked development fixture at the source commit

No personal Chloe source or recipient-specific bundle is included.

## Provenance

| Path | Source Git blob |
|---|---|
| `viewer-bnw.html` | `2703359f8750b14c95efd77007c2584ae88f5337` |
| `web/garden-input.mjs` | `4d45ba389b5618a7897b337e22a81c06f19bd367` |
| `web/garden-program.mjs` | `ef5d99638afe5a8e93bc072ae0d43cc4e3f9dee4` |
| `web/garden-runtime.mjs` | `0f94f69db1144be70ae7c1c2b1d46194ee254e8d` |
| `web/garden-world.mjs` | `654356a9bfff48b03f9db82640fe699db3b4e7a3` |
| `sealed_demo.lateletter` | `92a478d4ccd1c1bfceb1dedd0b6bffea0efd06a9` |
| `test_fixture.lateletter` | `d4358c57440803dbba437a3b2f04558094be9d58` |

The preservation check is:

```bash
git hash-object archive/deleted-browser-garden-526ab9e/viewer-bnw.html
```

and likewise for every listed file. Each result must equal the source blob.

## Local reference launch

From the repository root:

```bash
python3 -m http.server 8876
```

Then open:

```text
http://127.0.0.1:8876/archive/deleted-browser-garden-526ab9e/viewer-bnw.html
```

This launch is for visual comparison only. Recipient state is namespaced by
the archived code and must not be treated as current production evidence.
