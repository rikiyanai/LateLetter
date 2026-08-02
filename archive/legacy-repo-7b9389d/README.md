# Runnable legacy repository snapshot

This directory is the complete codebase state from Git commit
`7b9389de21edb67a15b261aae25b2350b53a49a9`, preserved without creating a
branch or worktree.

Four compromised artifacts from that commit are not republished:

- the original `README.md`;
- `letters/letter_source.example.json`;
- `public_letters/to-a-friend.lateletter`;
- `sealed_demo.lateletter`.

The three data/bundle paths are replaced by explicitly synthetic, compatible
v1 artifacts from safe commit `143ed5d`. The historical source and viewer code
remain byte-for-byte identical to `7b9389d`. See `PROVENANCE.json` for every
excluded and substituted Git blob.

## Local launch

From the current repository root, run:

```bash
python3 -m http.server 8876
```

Then open:

```text
http://127.0.0.1:8876/archive/legacy-repo-7b9389d/viewer-bnw.html
```

The **get demo letter** button loads the exact safe v1 development fixture.
The **get sealed letter** button loads a synthetic v1 sealed bundle; its demo
passphrase is `garden`.

This snapshot is a historical reproduction surface, not an accepted visual
baseline. Current production code must not import it.
