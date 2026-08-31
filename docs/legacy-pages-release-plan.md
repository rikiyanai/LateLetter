# LateLetter legacy Pages safety release plan

Status: safety tag and GitHub release created on 2026-08-31; the production
Pages URL still serves the frozen legacy viewer while the root viewer remains a
candidate.

## Observed production identity

Checked 2026-08-31 from the live endpoint and GitHub Actions metadata:

- URL: `https://rikiworld.com/lateletter/`
- Pages workflow run: `30392909905`
- workflow head branch: `restore/pre-jul19-viewer`
- workflow head commit: `e55593aae1d34427b2d384e75244eeb45556f090`
- published entrypoint: `legacy/viewer-bnw.html` copied to the Pages artifact as `index.html`
- entrypoint SHA-256: `93d239576b94328c3164a9a2781bd8cf7ef1825f709b2b35dfa06b843af50faa`
- last-modified response header: `2026-07-28 19:40:08 GMT`

The live response is byte-identical to `legacy/viewer-bnw.html` in the retained
`restore/pre-jul19-viewer` tree and to the root `viewer-bnw.html` blob at both
`c1ab652` and the archived source commit `7b9389d`. The `legacy/` copy was
introduced by `d888f19` and is present unchanged in the deployed commit
`e55593a`. The deployment commit is the artifact identity; `c1ab652`/`7b9389d`
are the viewer-code lineage. They must not be collapsed into one claim.

GitHub now reports the annotated tag
`lateletter-legacy-pages-2026-07-28` and the release
`LateLetter legacy Pages snapshot — 2026-07-28`.

## Safe tag and release receipt

Root review was followed by these actions on 2026-08-31:

1. Created an annotated, immutable-in-practice safety tag named
   `lateletter-legacy-pages-2026-07-28` at the exact deployment commit
   `e55593aae1d34427b2d384e75244eeb45556f090`. The tag object is
   `5166cb9eeb2a7f766fb45b149d1373e3cf519988`.
2. Verified the tag resolves to that commit, the `legacy/viewer-bnw.html` blob
   has the SHA-256 above, and `scripts/prepare_legacy_site.py` reproduces the
   expected artifact layout without extra files.
3. Created a GitHub release from that tag titled
   `LateLetter legacy Pages snapshot — 2026-07-28`:
   `https://github.com/rikiyanai/lateletter/releases/tag/lateletter-legacy-pages-2026-07-28`.
   It is the production safety snapshot and contains the deployment-run
   reference, entrypoint hash, and pre-July-19 viewer lineage.
4. Keep the release as the rollback reference. Do not repoint Pages at the
   root viewer until its acceptance evidence and operator visual review are
   complete; a README GIF is evidence of motion only, not that acceptance.
5. If Pages must be rolled back, dispatch the existing workflow from the
   safety commit or restore the exact tagged tree, then recheck the live URL
   hash and response headers.

No Pages dispatch was performed during the release publication. Pages remains
on the legacy snapshot until an intentional deployment changes it and the live
URL hash is rechecked.

## Prepared About description

> A local-first, encrypted time-delayed letter tool: write messages for loved
> ones, seal them into `.lateletter` bundles, and deliver them through a living
> ASCII garden in the browser. GitHub Pages remains on the frozen legacy viewer
> while the newer root viewer completes acceptance.

This wording is prepared for the repository About field and has not been
applied remotely.

## README motion captures

README-facing browser-flow captures were regenerated on 2026-08-31. The root
candidate capture was made from `viewer-bnw.html`. The legacy capture was made
from the retained `legacy/viewer-bnw.html` route on the legacy branch before the
README-facing aliases were applied to `main`.

| Surface | README asset | SHA-256 | GIF checks |
|---|---|---|---|
| legacy recipient walkthrough | `docs/lateletter-legacy-recipient-clickthrough.gif` | `7051f8b7df126aed7ca1583c870056c088296a15025cf8b8b3da19c393512f5a` | 960×600, 10 frames, loop=0, recipient demo flow through welcome, garden, passphrase, archive, reading, and return |

The GIF-level mechanical checks pass. A person must still review the rendered
motion before calling either capture visual acceptance.
