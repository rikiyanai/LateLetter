# LateLetter legacy Pages safety release plan

Status: prepared for root review; no tag or GitHub release has been created.

## Observed production identity

Checked 2026-08-31 from the live endpoint and GitHub Actions metadata:

- URL: `https://rikiworld.com/lateletter/`
- Pages workflow run: `30392909905`
- workflow head branch: `restore/pre-jul19-viewer`
- workflow head commit: `e55593aae1d34427b2d384e75244eeb45556f090`
- published entrypoint: `legacy/viewer-bnw.html` copied to the Pages artifact as `index.html`
- entrypoint SHA-256: `93d239576b94328c3164a9a2781bd8cf7ef1825f709b2b35dfa06b843af50faa`
- last-modified response header: `2026-07-28 19:40:08 GMT`

The live response is byte-identical to the local `legacy/viewer-bnw.html` and
to the root `viewer-bnw.html` blob at both `c1ab652` and the archived source
commit `7b9389d`. The `legacy/` copy was introduced by `d888f19` and is present
unchanged in the deployed commit `e55593a`. The deployment commit is the
artifact identity; `c1ab652`/`7b9389d` are the viewer-code lineage. They must
not be collapsed into one claim.

GitHub currently reports no tags and no releases for this repository.

## Safe tag and release plan

After root review of the complete dirty-worktree boundary:

1. Create an annotated, immutable-in-practice safety tag named
   `lateletter-legacy-pages-2026-07-28` at the exact deployment commit
   `e55593aae1d34427b2d384e75244eeb45556f090`.
2. Verify the tag resolves to that commit, the `legacy/viewer-bnw.html` blob
   has the SHA-256 above, and `scripts/prepare_legacy_site.py` reproduces the
   expected artifact layout without extra files.
3. Create a GitHub release from that tag titled
   `LateLetter legacy Pages snapshot — 2026-07-28`. Describe it as the
   production safety snapshot, include the deployment-run URL, the entrypoint
   hash, and the fact that it contains the pre-July-19 viewer lineage.
4. Keep the release as the rollback reference. Do not repoint Pages at the
   root viewer until its acceptance evidence and operator visual review are
   complete; a README GIF is evidence of motion only, not that acceptance.
5. If Pages must be rolled back, dispatch the existing workflow from the
   safety commit or restore the exact tagged tree, then recheck the live URL
   hash and response headers.

This plan is documentation only. No tag, release, Pages dispatch, or remote
mutation was performed during this audit.

## Prepared About description

> A local-first, encrypted time-delayed letter tool: write messages for loved
> ones, seal them into `.lateletter` bundles, and deliver them through a living
> ASCII garden in the browser. GitHub Pages remains on the frozen legacy viewer
> while the newer root viewer completes acceptance.

This wording is prepared for the repository About field and has not been
applied remotely.

## README motion captures

Fresh candidate-only captures were made on 2026-08-31 through
`scripts/capture_html_garden_review.py` against the local root and frozen
legacy browser routes. The public README copies are:

| Surface | README asset | SHA-256 | GIF checks |
|---|---|---|---|
| current root candidate | `docs/lateletter-viewer-current.gif` | `7f644266a76badcdb09511892507a14c00cce262e5c2e1bba94a556be13d0a54` | 960×600, 10 fps, 100 frames, 10.0 s, loop=0, 60 unique frames |
| production legacy viewer | `docs/lateletter-viewer-legacy.gif` | `01017a3cbd3afdd7f54999f4a9c2ae06b5069e91f26a469d4c496f41889d6f46` | 960×600, 10 fps, 100 frames, 10.0 s, loop=0, 91 unique frames |

The complete harness packages, including WebM masters, stills, and receipts,
are under the ignored reproducible-review directory
`docs/visual-review/2026-08-31/lateletter-readme-system-chrome/`. The GIF-level
mechanical checks pass. The full receipts remain `candidate_only`: the legacy
surface does not expose the newer ARIA object-count summary, and the current
root capture sampled 2 unique desktop and 1 unique mobile DOM states against
the harness default of 5. A person must still review the rendered motion before
calling either capture visual acceptance.
