#!/usr/bin/env bash
#
# scripts/check_attribution.sh — AI attribution policy, runnable anywhere.
#
# WHAT THIS ENFORCES
# ------------------
# No commit may carry AI-tool attribution. That means two separate things:
#
#   1. IDENTITY — the commit's author or committer name/email must not look
#      like an AI tool (claude / codex / agent, or an @anthropic.com /
#      @openai.com address).
#   2. TRAILER — the commit *message* must not carry an attribution trailer
#      such as "Co-Authored-By: Claude ..." or a "Claude-Session: ..." line.
#
# WHY THIS FILE EXISTS
# --------------------
# This logic previously lived only inside .github/workflows/, which meant the
# only way to run it was to spend a GitHub Actions runner. On a private repo
# those minutes are metered, so a policy check that costs nothing to compute
# was gating every push behind a billable job. The logic now lives here, in
# the repo, so that:
#
#   * .githooks/pre-push runs it locally on every push — free and instant;
#   * .github/workflows/block-ai-attribution.yml calls this same file, so CI
#     and local enforcement can never drift apart.
#
# USAGE
# -----
#   scripts/check_attribution.sh <git-rev-range-or-rev>
#
# The argument is passed straight to `git rev-list`, so both forms work:
#   scripts/check_attribution.sh origin/main..HEAD   # just the new commits
#   scripts/check_attribution.sh "$SHA"              # that commit and ancestors
#
# EXIT STATUS
#   0 — every inspected commit is clean
#   1 — at least one commit violates the policy (offenders printed to stderr)

set -euo pipefail

# `set -u` would abort on an unset $1, so check arity explicitly for a clearer
# error than "unbound variable".
if [[ $# -lt 1 ]]; then
  printf 'usage: %s <git-rev-range-or-rev>\n' "$0" >&2
  exit 2
fi

commit_range="$1"

# Matches an AI tool name as a WHOLE word, so ordinary English that merely
# contains these letters (e.g. "management" contains "agent") is not flagged.
# The surrounding groups stand in for word boundaries, which POSIX ERE lacks.
identity_pattern='(^|[^[:alnum:]_])(claude|codex|agent)([^[:alnum:]_]|$)|@(anthropic|openai)\.com'

# Matches attribution trailers at the start of a line: either a recognised
# trailer key whose value names an AI tool ("Co-Authored-By: Claude"), or a
# bare tool-name key ("Claude-Session:", "Codex:").
trailer_pattern='^[[:space:]]*((co-)?authored-by|author|committer)[[:space:]]*:.*(claude|codex|agent)|^[[:space:]]*(claude|codex|agent)(-session)?[[:space:]]*:'

failed=0
inspected=0

# Read commit SHAs from a process substitution rather than a pipe, so that the
# `failed` variable set inside the loop survives into the parent shell. A pipe
# would run the loop in a subshell and silently discard the result.
while IFS= read -r commit_sha; do
  inspected=$((inspected + 1))

  # Author and committer are checked separately from the message because a
  # commit can have a clean message but be *authored* by a tool identity.
  identities="$(git show -s --format='%an <%ae>%n%cn <%ce>' "$commit_sha")"
  message="$(git show -s --format='%B' "$commit_sha")"

  if printf '%s\n' "$identities" | grep -Eiq "$identity_pattern"; then
    printf 'Blocked commit %s: prohibited author or committer identity.\n' \
      "$commit_sha" >&2
    printf '  %s\n' "$identities" >&2
    failed=1
  fi

  if printf '%s\n' "$message" | grep -Eiq "$trailer_pattern"; then
    printf 'Blocked commit %s: prohibited attribution trailer or session metadata.\n' \
      "$commit_sha" >&2
    failed=1
  fi
done < <(git rev-list "$commit_range")

if [[ "$failed" -eq 0 ]]; then
  printf 'AI attribution policy: %d commit(s) inspected, all clean.\n' "$inspected"
fi

exit "$failed"
