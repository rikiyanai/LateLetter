# Legacy Garden unique-viewer preservation

This directory preserves only the safe, unique browser viewer blob from the
orphan remote snapshot commit `7b9389de21edb67a15b261aae25b2350b53a49a9`.

The orphan snapshot also contains a plaintext passphrase-bearing source and
two related sealed bundles. Those sensitive artifacts are intentionally not
copied here. All other code in that snapshot is already reachable from the
current `main` history or superseded by the exact direct-parent package in
`archive/deleted-browser-garden-526ab9e/`.

This viewer is historical visual evidence only. Production must not import it
or restore its renderer-local gameplay, collision, persistence, or hit-testing
ownership.

Source blob: `59dc49a820d07d1b6a1741e17aafe6d075f6c99d`
