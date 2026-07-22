---
title: "audit: execution canon vs live code"
type: audit
status: active
date: 2026-04-27
---

# audit: execution canon vs live code

Focused audit of the execution claims in `docs/SPEC.md` against source, tests, and runtime behavior on `master` at `2da47e4`.

## Verification commands

```bash
pytest -q
python3 demo_author.py --quiet --out /tmp/lateletter_audit_demo.lateletter
python3 - <<'PY'
from pathlib import Path
from src.lateletter.bundle import read_bundle, verify_checksum
p = Path('/tmp/lateletter_audit_demo.lateletter')
b = read_bundle(p)
print('checksum_field=', repr(b.checksum))
print('verify_checksum=', verify_checksum(b))
PY
```

Result:
- `pytest -q` passed: `314 passed`
- Demo-author output loaded structurally but `verify_checksum=False`

## Findings

### 1. Author workflow is component-complete, not execution-complete

Claim audited:
- `docs/SPEC.md` step 6 said the offline author workflow was done.

Code evidence:
- `src/lateletter/cli.py` returns immediately after intake and prints that message-list/Q&A integration is still pending.

Verdict:
- `not verified`

Required canon change:
- Downgrade step 6 to `IN PROGRESS`.
- Keep component bullets that are individually real.
- Add an explicit "end-to-end integration not done" item.

### 2. `demo_author.py` is not valid export evidence

Claim audited:
- `demo_author.py` and the execution sequence treated Part C as producing a ready-to-open demo bundle.

Code evidence:
- `demo_author.py` writes `bundle.to_dict()` directly.
- `src/lateletter/bundle.py` only computes checksum through `write_bundle()`.

Runtime evidence:
- Generated bundle had `checksum=''`.
- `verify_checksum()` returned `False`.

Verdict:
- `not verified`

Required canon change:
- Downgrade Part C from done to open.
- Mark the script as scaffolded, not proof.

### 3. Browser viewer does not yet meet the canon corruption gate

Claim audited:
- The spec requires launch-time checksum verification in both delivery channels.

Code evidence:
- `viewer-bnw.html` validates bundle shape/version/`bundle_id` only.
- No checksum recomputation/verification occurs before state is loaded.

Verdict:
- `not verified`

Required canon change:
- Keep the requirement.
- Mark browser integrity parity as still open in the execution sequence.

## Outcome

The audit is a docs/canon correction only. No code was changed in this pass. The corrected truth state after the audit is:

- Proven: recipient terminal path, bundle writer/reader primitives, and unit coverage around those components.
- Implemented but unproven/incomplete: browser integrity parity, end-to-end author integration, author Part C demo artifact.
- Still assumed false unless code changes: that `lateletter --write` completes the workflow, that browser mode enforces checksum corruption handling, and that `demo_author.py` emits a valid recipient artifact.
