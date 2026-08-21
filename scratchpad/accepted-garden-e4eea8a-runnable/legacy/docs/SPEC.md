# LateLetter — Canonical Project Specification

> A terminal program for the terminally ill. Compose messages for the people you love.
> They will find them — on birthdays, anniversaries, ordinary Tuesdays — inside a living garden.

---

## 1. Vision

LateLetter is a local-first, terminal-native application with two distinct modes:

- **Author mode** — a guided, intimate interview process. The author answers curated questions (offline) or LLM-driven questions (with API key) over many sessions. Completed messages are encrypted and exported as a `.lateletter` bundle file.
- **Recipient mode** — the normal garden experience. When opened with a `.lateletter` file, the garden runs as usual. On days when a message is waiting, a small bird appears carrying a letter. The recipient presses `e` to unlock and read.

The garden is the delivery mechanism — alive, ambient, unhurried. The message arrives as naturally as a bird landing on a branch.

---

## 2. Modes at a Glance

| Mode | How to enter | Purpose |
|------|-------------|---------|
| Recipient (default) | `python garden.py [file.lateletter]` | Garden TUI; `e` unlocks the bundle, bird appears after auth if a message is due; `i` examines garden items; `l` opens letter archive |
| Author | `python garden.py --write [file.lateletter]` | Intake wizard + LLM Q&A + encryption + export |

If no `.lateletter` file is passed, the garden runs as a standalone experience (original behavior). No hint or prompt about `.lateletter` files is shown — the garden is a complete experience on its own.

These commands are the canonical developer/operator entrypoints. The packaged recipient release described later in this spec must expose the same behavior without requiring terminal command entry.

---

## 3. The `.lateletter` File

A single portable file the author gives to the recipient. Format: **encrypted JSON bundle**.

### Outer structure (plaintext)

```json
{
  "version": 1,
  "bundle_id": "uuid4",
  "author_name": "Robert",
  "passphrase_hint": "The name of our first dog",
  "bundle_auth_salt": "...",
  "messages": [
    {
      "id": "uuid4",
      "date": "2027-06-15",
      "ciphertext": "...",
      "salt": "...",
      "nonce": "...",
      "kdf_params": null
    }
  ],
  "garden_seed": 42301,
  "garden_gifts": [
    {
      "id": "uuid4",
      "type": "item",
      "catalog_id": "plate_of_food",
      "sentiment_ciphertext": "...",
      "salt": "...",
      "nonce": "...",
      "trigger": { "type": "date", "value": "2028-06-15" },
      "placement_hint": "near_tallest_tree",
      "animal_name": null,
      "animal_collar_color": null
    }
  ],
  "notification": {
    "email": "maya@example.com",
    "method": "self-hosted"
  },
  "checksum": "...",
  "hmac": "..."
}
```

### Binary encoding

All binary fields (`bundle_auth_salt`, `salt`, `nonce`, `ciphertext`, `checksum`, `hmac`) are stored as **standard base64 strings with padding** (RFC 4648 §4). This applies to the JSON bundle only — in-memory and crypto operations use raw bytes.

### Canonical JSON

The `checksum` and `hmac` are computed over the **canonical JSON** of the visible bundle payload. Canonical JSON is defined as: **sorted keys (recursive), compact serialization (no whitespace), UTF-8 encoding** — equivalent to Python's `json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')`. The visible bundle payload includes all top-level fields except `checksum` and `hmac` themselves.

### Field definitions

- `bundle_id` — stable UUID generated at bundle creation; used by read receipts (survives file updates).
- `author_name` — plaintext author name for the reading overlay (displayed before passphrase entry).
- `passphrase_hint` — optional plaintext hint the author writes during intake. Not the passphrase itself — a reminder to help the recipient recall it. Can be null if the author declines to set one.
- `bundle_auth_salt` — 16-byte random salt generated once per bundle; used only to derive the bundle-wide HMAC key from the passphrase.
- `date` — ISO 8601. The message becomes available on or after this date.
- `garden_seed` — the garden seed embedded in the file; the recipient's garden is deterministic and personal.
- `kdf_params` — optional per-message KDF parameter override. When `null`, the v1 defaults apply (time_cost=3, memory_cost=65536, parallelism=1, hash_len=32). Future appended messages may use updated parameters without re-encrypting existing messages. This field is cheap to add now and expensive to introduce later (would require a format version bump).
- `ciphertext` — the message body **and label**, encrypted per-message with a unique salt derived from the shared passphrase. The label (e.g., "Her 30th birthday") is inside the ciphertext, not exposed in the outer structure.
- `notification` — optional. Contains `email` (recipient delivery email address) and `method` (`"self-hosted"` or `null`). This field is plaintext — anyone with the file can see the email address. The author is warned about this during the export flow (§5.4). Can be `null` if the author declines email notifications. **Privacy note:** the recipient's email address is PII. Unlike names and dates (cosmetic metadata), an email address is a contact channel. The export flow warns: *"The recipient's email address will be visible to anyone who has this file."*
- `checksum` — SHA-256 hash over the canonical JSON of the visible bundle payload (`version`, `bundle_id`, `author_name`, `passphrase_hint`, `bundle_auth_salt`, `garden_seed`, `messages`, `garden_gifts`, `notification`). Computed without any secret key. Used at launch for structural integrity checking (detects corruption only — not tamper-resistant, since an attacker can recompute it).
- `hmac` — HMAC-SHA256 over the same canonical visible bundle payload using a key derived from the passphrase and `bundle_auth_salt`. Verified only after passphrase entry. Detects authenticated tampering by an adversary who knows the file format but not the passphrase.

### What is NOT in the file

- The passphrase itself (never stored).
- The plaintext of any message or message label.
- Any server-side identifiers.

### Privacy note

The `date` field is plaintext (required for date-lock checking). Anyone with the file can see *when* messages are scheduled but not *what* they are about. The `author_name` is also plaintext for UX convenience. The message `label` is encrypted alongside the message body so it is only revealed after passphrase entry.

---

## 4. Encryption Model

> **Architecture status (2026-04-20):** The *conceptual model* is settled — passphrase-based symmetric encryption, local-first, no server dependency, tamper-evident. The *specific implementation primitive* (Argon2id+AES-256-GCM custom stack vs. `age` library vs. another well-audited tool) is under review and will be finalised during the Phase 3 research memo (§24 step 13). The dev-fixture system (base64 plaintext, `hmac=""`) provides a working MVP for all other phases in the meantime. See §4 "Encryption primitive options" below for the current decision frame.

**Conceptual model (settled):** Passphrase-based symmetric encryption. Author seals; recipient unlocks. Local file only — no server, no account, no network dependency. Tamper-evident (HMAC over metadata). File must remain readable 20–30 years from now without infrastructure.

**Current spec (subject to Phase 3 review):** Argon2id key derivation + AES-256-GCM per message.

### Author side (write phase)
1. Author sets a **passphrase** during intake — a phrase the recipient already knows or will be told privately (e.g., "the name of our first dog").
2. A bundle-wide 16-byte `bundle_auth_salt` is generated once when the bundle is created.
3. For each message, a unique 16-byte message salt is generated.
4. Message key = `Argon2id(passphrase, message_salt, time_cost=3, memory_cost=65536, parallelism=1, hash_len=32)` → 32-byte key. These parameters are fixed for v1; any future change would require re-encryption (likely infeasible in this context), so the initial choice matters. **Per-session key caching:** Derived per-message keys are cached in memory alongside the passphrase for the session duration. This avoids re-deriving when the recipient re-reads a letter or when the archive (§6.6) decrypts multiple labels. Without caching, opening the archive with 12 read messages would require 12 sequential Argon2id derivations (12–36 seconds). Labels should be decrypted lazily (on scroll/selection) with a progress indicator ("Decrypting letters… 3/12") if batch decryption is needed.
5. Message body encrypted with AES-256-GCM. Nonce stored alongside ciphertext.
6. Salt + nonce + ciphertext written into the bundle.
7. On every bundle rewrite, derive `bundle_hmac_key = Argon2id(passphrase, bundle_auth_salt, time_cost=3, memory_cost=65536, parallelism=1, hash_len=32)` and compute HMAC-SHA256 over the canonical visible bundle payload (everything except `checksum` and `hmac`). All HMAC comparisons must use constant-time comparison (`hmac.compare_digest()` in Python, equivalent in JS) to prevent timing oracles.

### Recipient side (read phase)
1. Recipient enters the passphrase **once per session** (the first time they press `e`). The passphrase is stored as a mutable `bytearray` (not a Python `str`) and cached in memory for the session duration. On app exit, the bytearray contents are explicitly overwritten with zeros before the reference is released. (Python strings are immutable and interned — only mutable bytearrays can be reliably zeroed.)
2. The app first derives the bundle HMAC key from `bundle_auth_salt` and verifies the bundle `hmac`. Until this check passes, the app treats the bundle as sealed and does not announce whether any message is due.
3. If the HMAC passes, the app computes due messages from authenticated dates (`date.today() >= message["date"]` and no read receipt).
4. When the recipient opens a specific due message, the app re-derives the key from that message's stored salt (each message requires independent key derivation due to unique salts — expect ~1-3 seconds per message on typical hardware), then decrypts with stored nonce + ciphertext.
5. On authentication failure:
   - The overlay shows "Incorrect passphrase, or this file has been modified." below the input field. The field clears.
   - Unlimited retries. No lockout (Argon2id's computational cost is the primary brute-force defense).
   - Pressing `esc` closes the overlay and returns to the garden. Any existing delivery state for the authenticated session remains visible.
6. If a passphrase hint exists in the bundle, it is always shown below the input field (before any attempt, not only on failure): *"Hint: The name of our first dog"*. A grieving recipient who hasn't thought about the passphrase in years deserves every available cue upfront.

### Date lock
- The app checks `date.today() >= message["date"]` AND `message_id NOT IN read_receipts` only **after** the bundle HMAC has been verified for the current session.
- Before authentication, recipient mode may show a neutral *"press `e` to unlock letters"* affordance, but it must not claim that a letter has arrived or reveal a count.
- Messages with future dates are invisible after authentication — the bird does not appear, the message is not listed.
- This is app-enforced, not cryptographically enforced. Motivated people can bypass it by editing system date. This is acceptable for v1; the author is trusted to set the right dates, and most recipients will not want to circumvent grief.

### Bundle integrity (two-layer)
1. **Launch-time corruption check (no passphrase needed):** The app verifies the `checksum` (unkeyed SHA-256) on launch. This is a **corruption detector only** — not tamper-resistant, since anyone can recompute the checksum after modifying the file. If it fails, the file is damaged (disk corruption, truncation, encoding error). The app shows: *"This file appears damaged. The letters inside may not be readable."* The garden still runs but the bundle remains locked and no unlock prompt or bird appears. The checksum-pass state must **not** imply that the file has not been tampered with.
2. **Post-passphrase check:** After the recipient enters the passphrase (first `e` press), the app verifies the `hmac` (passphrase-keyed HMAC-SHA256 derived using `bundle_auth_salt`). The HMAC covers the authenticated schedule metadata, including message dates. If the checksum passed but the HMAC fails, the file was modified or the passphrase is wrong. The app shows: *"Incorrect passphrase, or this file has been modified."* Normal delivery UI is suppressed for that session: no bird, no due count, no dated message list.

### Security philosophy
- **Anti-tampering is the primary concern.** Once a message is sealed, it must be detectable if anyone modifies it. The checksum + HMAC + AES-GCM authentication layers serve this goal.
- **No authenticated delivery claim before unlock.** The app does not say *"a letter has arrived"* until the bundle HMAC has been verified for the current session.
- **Anti-peeking is secondary.** If a tech-savvy recipient changes their system clock to read future messages early, that is their choice — the app should deter casual circumvention but not prevent a determined recipient from accessing their own letters. The date lock is a gentle boundary, not a vault.
- **Encryption deters normal hacking** but the spec does not aim for adversarial-grade resistance against a motivated attacker with the file. The emotional context is the primary access control.

### Passphrase loss
- **By design, a lost passphrase means permanent loss of all messages.** This is an intentional consequence of local-first encryption with no server recovery.
- The export flow (§5.4) explicitly warns the author about this and strongly encourages setting a passphrase hint and writing the passphrase down for a trusted person.
- The optional `passphrase_hint` field in the bundle helps the recipient recall the passphrase without storing it.

### Encryption primitive options (Phase 3 decision)

Three candidates. Decision deferred until after the UX MVP is proven and before Phase 3 implementation begins.

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| **Custom Argon2id + AES-GCM** *(current spec)* | Roll the key derivation and encryption using `argon2-cffi` + PyCA `cryptography` | Full control over UX (passphrase hints, per-message salts, label layout). Matches spec as written. | More surface area to get wrong. Requires separate JS/WASM port for browser viewer (argon2-browser). Two codebases to keep in parity. |
| **`age` encryption** | [age-encryption.org](https://age-encryption.org/) — modern, simple, battle-tested. Passphrase-based mode wraps Argon2id (scrypt actually) + AES-256-GCM. Python: `pyage`; JS: `age-encryption` npm package. | Widely reviewed, minimal API, native passphrase support. Same primitive in Python and JS — parity is built-in. | Less control over KDF parameters and layout. Passphrase hint not native to the format (would live in plaintext metadata only). Adds external format dependency. |
| **Account/database** | Letters stored server-side; recipient authenticates with account credentials | Simpler UX for recipients; no file management | **Rejected for primary storage.** Server lifetime problem — if LateLetter shuts down, letters are permanently lost. Incompatible with the use case (author is often dying; letters must outlast any company). Privacy: server sees metadata. Post-v1 managed service (§21) uses this model as an *optional layer on top*, never as the sole storage. |
| **Blockchain/distributed** | IPFS, Ethereum, etc. | Decentralised | **Rejected.** Date-lock remains app-enforced regardless. Gas fees, chain longevity risk, terrible UX for grieving non-technical recipients. Does not solve any problem that the file format doesn't already solve with far less complexity. |

**Current preference:** `age` — tentatively, for simplicity and Python/JS parity. Evaluate during Phase 3 research memo.

**Override rule:** If at any point `age`'s constraints create tension with the recipient or author UX (passphrase hint display, per-message key isolation, error messaging, browser performance, or any other experience detail), abandon `age` immediately and use the custom Argon2id + AES-256-GCM stack. The encryption library serves the experience — not the reverse. UX is never sacrificed to preserve a library choice.

The file format (`.lateletter` JSON bundle) is not in question — that stays regardless of which crypto primitive is used.

### Dependencies
- `cryptography` (PyCA) — for AES-256-GCM via `cryptography.hazmat.primitives.ciphers.aead.AESGCM`. Pin version in `pyproject.toml`. Wrap hazmat usage in a tested encryption module with round-trip integration tests.
- `argon2-cffi` — for Argon2id key derivation (matching the scheme above; scrypt is not used).
- *(or: `pyage` — pending Phase 3 decision)*

---

## 5. Author Mode — Full Flow

### 5.1 First launch (consent and intake)

Before any letter writing begins, the author completes a combined **intake and wishes form**. The steward designation and wishes fields are integrated into the intake form (not a separate gate), because the wishes have no automation backing them in v1 — they are advisory records for the steward's guidance, not automated behaviors. The "release unfinished on date" option has no enforcement mechanism; the steward must manually act on it.

**These choices are editable.** The author can return to the intake screen from the message list at any time to update steward, wishes, or other intake fields. A terminally ill author whose steward dies or whose prognosis changes must be able to revise without starting over.

The **intake form** follows. Default presentation is a quiet TUI form (curses, not a scrolling CLI). If the user enables `--accessible` or the terminal accessibility probe says full-screen curses is unsuitable, the app falls back to a plain line-oriented prompt flow with the same fields, validation, and autosave behavior. Fields:

```
Your name .............. [ Robert                    ]
Your relationship ....... [ Father                    ]
Recipient's name ........ [ Maya                      ]
Recipient's relationship  [ Daughter                  ]
Key dates (add many) .... [ Maya's birthday: June 15  ] [+ add]
Shared memories/tags .... [ dogs, hiking, her laugh   ]
Steward (optional) ...... [ Sarah Chen                ]
Steward contact ......... [ sarah@example.com         ]
If unable to finish ..... (•) Only deliver completed letters
                          ( ) Release all on: [____________]
Passphrase .............. [ **********************    ]
Confirm passphrase ...... [ **********************    ]
Passphrase hint ......... [ What we called our first dog ]
```

**Validation:**
- All fields except Shared memories/tags are required. **Passphrase hint is required** — a grieving recipient who hasn't thought about the passphrase in years deserves every available cue. The author can write anything, but the field cannot be left empty.
- Passphrase mismatch: inline error below the Confirm field (not a modal). Author cannot proceed until matched.
- Key dates: free text stored as label+date pairs. No format enforcement — the author knows their own dates.
- No minimum passphrase length enforced, but a **soft strength warning** is shown for short or common passphrases: *"This passphrase is short. Someone who finds this file could guess it."* The author can proceed — memorability is a valid priority — but the risk is surfaced.
- **Passphrase communication warning** is shown immediately after the passphrase is confirmed during intake (not deferred to export): *"Important: If [recipient_name] cannot remember this passphrase, these letters are lost forever. Consider writing it down for someone you trust."* This ensures the warning fires even if the author loses capacity before the formal export flow.
- Tab/Enter navigates between fields. `esc` exits intake (with confirmation if any field was filled).

Intake data is stored locally in a **session file** (`~/.lateletter/author/session.json`). The passphrase is **never** written to `session.json` — it is held in memory only during the active session and used to derive keys at encryption time. See §9 for session file security.

### 5.2 Message creation

After intake, author picks a message slot:

```
  + Add a new message
  ─────────────────────────────────────────────────
  [ Maya's 30th birthday    Jun 15, 2027  ✓ written ]
  [ Her wedding day         TBD           · pending  ]
  [ Just a Tuesday          Mar 10, 2028  · pending  ]
```

For each message, the author enters a label and a delivery date. "TBD" means the author intends to set a date later. **TBD-date messages cannot be exported** — the export flow prompts the author to set a date or discard any TBD messages before proceeding.

> **Note:** "Ongoing" message types (no fixed date, appears on a schedule) are a future feature — see §14. They are not shown in the v1 interface.

### 5.3 LLM-guided Q&A session

The Q&A session is the heart of author mode. It works like a gentle interview.

**Flow:**
1. LLM is seeded with the intake context (names, relationship, key dates, memory tags).
2. LLM generates an opening question relevant to this specific message (e.g., for "30th birthday": *"What do you hope Maya feels about herself at 30 that she might not believe about herself today?"*).
3. Author types a free-form answer. No character limit. No timer.
4. LLM reads the answer and generates a contextual follow-up (or pivots to a new dimension).
5. After N exchanges (author-configurable: default 10, range 5–30, set per-message at session start), the session is marked complete for that message.

**Session resumption:** If the author exits mid-Q&A (fatigue, medical interruption, terminal close), the in-progress Q&A state is preserved in `session.json`. On next launch, re-entering the message slot shows: *"Resume where you left off? [y/N]"*. On yes, prior exchanges are re-loaded and the session continues from question N+1. On no, prior answers are preserved as notes but a fresh question sequence begins. In offline mode, resume picks up at the next question in the bank after the last asked.
6. **If LLM mode:** LLM synthesizes all answers into a **composed message draft** in the author's voice (see §8.3). Author can edit freely in the draft editor (§8.4) before encrypting. **If offline mode:** The Q&A answers are presented as notes in the draft editor and the author composes the message manually. No automated synthesis in offline mode.

**Question categories (LLM-aware):**
- Memories and shared history
- Values and what you hope they carry forward
- Practical wisdom ("things I wish someone told me")
- Humor and lightness
- Grief — what you want them to know about loss
- Love — plainly said
- Future hopes ("I imagine you at 40...")
- Permission-giving ("you are allowed to be happy again")

**Uniqueness enforcement:**
- Each question asked is stored in `session.json` with its full text and a hash (hash used for efficient local dedup lookup).
- LLM prompt includes the actual prior question text: "Do not ask questions similar to these already asked: [list of prior questions]."
- A local question log (per recipient slot) prevents repeats across sessions.

**Question-bank editorial workflow (offline mode):**
- The offline bank lives in a versioned bundled data file, not inline in application code.
- New or revised questions require review by at least two humans before release: one content/editorial reviewer and one implementation/product reviewer.
- Each question entry is tagged with category, intensity level, and exclusion notes so harmful or mismatched prompts can be filtered rather than merely removed ad hoc.
- Rejected questions remain in an editorial archive with a short rejection reason to prevent churn and reintroduction of weak prompts.
- Release blockers for the question bank include: duplicate prompts, therapy-speak cliches, accidental guilt framing, manipulative pressure, or prompts that assume a happy family structure or a specific belief system.
- Each release of the bank must include a small gold-set review pass: representative questions from every category are spot-checked for tone, clarity, specificity, and emotional safety.

**Offline question-selection model:**
- The offline experience uses a **layered system**, not a flat random list. Every session draws from:
  1. a small universal base set that works for almost anyone,
  2. a domain-specific pool chosen from intake context and message type,
  3. a personalization layer based on prior answers, memory tags, and what has already been asked.
- The universal base set is mandatory and intentionally small: 20-40 reviewed prompts that establish voice, relationship, values, love, hope, and practical wisdom without assuming conflict, faith, parenthood, or unresolved trauma.
- A message session begins with 2-3 low-intensity universal questions before introducing more specific prompts. This gives the author a humane ramp instead of starting with highly personal or emotionally heavy material.
- After the grounding pass, the selector scores candidate questions by:
  - relevance to message occasion (`birthday`, `wedding`, `graduation`, `after my death`, `whenever you need this`)
  - relationship fit (`child`, `partner`, `friend`, `sibling`, `general loved one`)
  - intake memory tags and free-text context
  - coverage balance across domains not yet touched
  - intensity pacing rules
  - novelty, using `questions_asked.json` and the current session log to avoid repeats or near-repeats
- The selector must always prefer unanswered high-value universal domains before overfitting to niche personalization. Personalization is a second layer, not a replacement for the common human essentials.
- Heavy domains such as apology, fear, regret, and spiritual meaning are never selected first. They require either explicit author opt-in or prior progression through at least one lower-intensity pass in the session.
- The runtime should expose "skip", "ask something easier", and "ask something more specific" controls so the author can steer intensity without having to restart the session.

**Question-bank system design:**
- The long-term canonical bank is a **versioned read-only bundled data file** shipped inside the app resources, for example `LateLetter.app/Contents/Resources/question_bank.v1.json`.
- The app loads that file into memory at startup and never edits it in place. Editorial updates happen by shipping a new reviewed bank file with a new bank version, not by mutating user-local copies.
- Each question entry in the canonical bank includes at minimum:
  - stable `question_id`
  - prompt text
  - domain
  - intensity tier
  - relationship tags
  - occasion tags
  - exclusion flags
  - optional prerequisites or gating rules
  - optional follow-up hints for future selector refinement
- The runtime personalization state lives separately from the bank content. User-local state belongs in `session.json` and `questions_asked.json`; the canonical bank remains static.

**Temporary implementation storage before the full bank system exists:**
- The first end-to-end offline author prototype may use a smaller reviewed **seed bank** stored in a repository data file such as `data/question_bank_seed.v0.json`.
- That temporary seed bank is only for Phase 1 / early Phase 2 implementation and research validation. It must still be separate from source code and still use the canonical entry shape wherever practical.
- The seed bank is not the release artifact and must not become an ad hoc permanent format. Before v1 ship work proceeds past the prototype stage, it is replaced by the bundled canonical bank file and editorial release workflow described above.
- During the prototype stage, any derived selector state, asked-question logs, or temporary scoring metadata remain user-local under `~/.lateletter/author/`; no runtime process writes back into the seed bank file.

### 5.4 Encryption and export

**Incremental export:** Each message is encrypted and appended to the bundle as soon as the author finalizes it (not batch-all-at-end). The `checksum` and `hmac` are recomputed and the bundle file rewritten after each message finalization, ensuring the on-disk file is always a valid, verifiable bundle. This means that if the author loses capacity unexpectedly, all completed messages are already safe.

**Incremental handoff:** Every time the bundle is rewritten (message finalized), the app also regenerates a minimal handoff folder alongside it — at minimum, the current `.lateletter` file plus `viewer.html` plus a stub `README.txt`. This ensures the delivery artifact (not just the crypto artifact) is always up-to-date. If the author loses capacity before the formal "Export bundle" flow, the steward can find a complete handoff folder at the bundle's location. The formal "Export bundle" action adds email notification setup, backup guidance, and session wipe on top of this already-current handoff folder.

Export flow:
1. Author triggers "Export bundle".
2. Any remaining unencrypted messages are encrypted independently (see §4). The checksum and HMAC are recomputed over the canonical visible bundle payload.
3. A `.lateletter` file is written to the author's chosen path using temp-file + `fsync` + atomic rename on the same filesystem. If the atomic replace cannot be completed, the previous valid bundle remains untouched and the app shows an export failure.
4. **Handoff package generation:** The app creates the handoff folder (§15.1) at the author's chosen path. This includes the `.lateletter` file, `viewer.html`, `README.txt` (auto-generated from intake data), and optionally `notify.py` and `LateLetter.app`. The folder is created via temp-dir + atomic rename.
5. **Email notification setup (optional):** If the author wants due-date email notifications (§13.3), the app prompts for the recipient's email address and SMTP configuration. This metadata is stored in the bundle's plaintext `notification` field. The `notify.py` script is configured and included in the handoff folder. The author or steward is instructed to set up a cron job on any always-on machine.
6. **Passphrase warning screen:** *"Important: If Maya cannot remember the passphrase, these letters are lost forever. There is no recovery. Consider writing the passphrase down and leaving it with someone you trust."*
7. **Backup guidance screen:** *"This folder contains all of your letters. There is no backup and no recovery. We strongly recommend saving a copy to a second location — a USB drive, cloud storage, or with someone you trust. Note: your letters are encrypted, but the delivery dates, your name, and any notification email are visible to anyone with the file."*
8. **Session wipe prompt:** *"Completed drafts and notes are still on this computer. Would you like to delete them securely? [Delete completed drafts / Keep everything for later]"*
   - **Delete completed drafts:** Overwrites finalized `drafts/*.txt` with random bytes, then deletes them. `session.json` is compacted: intake context, steward information, pending message slots, and unfinished-message notes remain; Q&A content for already-encrypted messages is removed. `questions_asked.json` is retained for dedup.
   - If unfinished-message notes exist, a second prompt appears: *"Keep unfinished notes so you or your steward can continue later? [Y/n]"*. Default is keep.
   - **Keep everything for later:** All files retained. Warning shown on next launch: *"Unencrypted drafts exist in ~/.lateletter/. Run --wipe-session to delete them."*
9. Final screen: *"Give this folder to Maya. Tell her the passphrase when the time feels right — or leave it with someone you trust."*

**Default is Delete completed drafts** — the secure option should not require opt-in, but unfinished notes are preserved by default because they are still part of the incapacitation/handoff path.

### 5.5 Adding messages later

Author can reopen `--write file.lateletter` and add new message slots. On reopening, the author must supply the original passphrase; the app verifies it by recomputing the bundle HMAC before allowing additions. The passphrase is then cached for the rest of the session (same caching behavior as recipient mode — mutable bytearray, zeroed on exit). It is used for encrypting new messages and recomputing the HMAC.

**Reopen UX:**
- The message list shows existing encrypted messages by date only (labels are encrypted and not visible without decryption). After passphrase verification, labels are decrypted and shown.
- Existing messages are **read-only** in v1 — the author can view them but not edit. The author can only append new messages. Each new message is encrypted independently and the bundle HMAC is recomputed (§5.4 incremental export).
- Intake context is loaded from `~/.lateletter/author/session.json` if available. If the session file was deleted or the author is on a different machine, the intake form is re-presented.
- Existing messages are not re-encrypted (salts are independent). The file is rewritten with the new message appended and the HMAC recomputed.

### 5.6 Author incapacitation

The author dying or losing capacity before finishing is the **expected primary scenario**, not an edge case.

**Design mitigations:**
1. **Incremental export** (§5.4): Each message is encrypted into the bundle as soon as it is finalized. Partial progress is never lost — even one completed message produces a valid `.lateletter` file.
2. **Steward role:** The author can designate a trusted person (a "steward") during intake. The steward's name is recorded in `session.json` and included in the handoff package README (§15.1). During intake, the app optionally asks for the steward's contact information (phone or email) so the README can direct the recipient to them for help. If the author cannot continue, the steward can use the session file and the passphrase to complete remaining messages on the author's machine.
3. **Session file as handoff artifact:** `session.json` contains intake context and Q&A history but **never the passphrase**. The steward must already know the passphrase (or the author must communicate it separately). The steward launches `--write` with the existing bundle and enters the passphrase to continue.
4. **No unfinished-message exposure:** Messages that were started but not finalized remain only in `session.json` as Q&A notes — they are not exported to the bundle. The steward can review these notes and choose to complete or discard them. The default export wipe removes completed-message notes but keeps unfinished notes unless the author explicitly deletes them.

---

## 6. Recipient Mode — Full Flow

### 6.1 Normal operation

```
python garden.py maya.lateletter
```

Garden renders as usual. The embedded `garden_seed` is used, making Maya's garden deterministic and personal — always the same arrangement of plants, but with the normal wind animation.

### 6.2 Message detection

On launch:
1. App verifies the bundle `checksum` (unkeyed SHA-256 — see §4 Bundle integrity). If it fails, show corruption warning; garden runs but no bird.
2. If the checksum passes, the status bar may show a neutral unlock affordance (`e · unlock letters`) to indicate that a sealed bundle is present.
3. App does **not** announce due messages or inject the letter-bird yet.
4. When the recipient presses `e`, the app verifies the passphrase-keyed `hmac` (§6.4).
5. Only after HMAC verification succeeds does the app scan messages and mark due items from authenticated dates.
6. If any authenticated messages are due → inject a **letter-bird** into the garden scene.

### 6.3 The bird

The **letter-bird** is the default delivery creature — visually distinct from the ambient bird (§7.2), rendered as an animated ASCII bird carrying `[✉]` or a folded letter glyph, perching on a tree top or moving slowly across the upper garden. It only appears after the bundle has been authenticated for the current session and at least one message is due. **Progression override (§6.8.2):** If the recipient has a bonded animal (trust tier 3), that animal delivers the letter instead of the default bird — the cat carries the envelope in its mouth, the relationship bird carries it in talons. The letter-bird is the fallback when no animal relationship exists.

- Status bar changes from:
  ```
  seed=42301  q=quit
  ```
  (Note: the `r=new garden` key is disabled in recipient mode — the garden seed is fixed from the bundle.)

  to (bundle present but not yet unlocked):
  ```
  seed=42301  q=quit  · e · unlock letters
  ```

  then, after successful authentication, to (single message, one triggered item):
  ```
  seed=42301  q=quit  · e · a letter has arrived  ·  i · examine  ·  l · your letters
  ```
  or (multiple messages, no triggered items):
  ```
  seed=42301  q=quit  · e · 3 letters have arrived  ·  l · your letters
  ```
  Key summary: `e` = open/unlock delivery; `i` = examine triggered garden items (only shown when items exist); `l` = letter archive.
- **Multiple due messages:** A single letter-bird appears with a count indicator (e.g., `[✉3]`). The bird does not multiply — one bird, one count.

### 6.4 Reading a message

Pressing `e`:

**Reading flow:**
1. Garden dims. Full-screen overlay appears:
   ```
   ╔══════════════════════════════════════════════════╗
   ║  Letters from Robert                             ║
   ║  Unlock to check for due messages                ║
   ╠══════════════════════════════════════════════════╣
   ║  Passphrase: [                               ]   ║
   ║  Hint: The name of our first dog                  ║
   ╚══════════════════════════════════════════════════╝
   ```
   The author name comes from the plaintext `author_name` field. No date or label is shown yet — delivery state is still locked behind bundle authentication.

2. **First unlock in session:** Recipient enters passphrase. The passphrase field becomes read-only and a derivation indicator appears: *"Verifying…"* with a spinning ASCII indicator (`|`/`-`/`\`/`|`). Argon2id derivation takes 1–5 seconds; without this indicator, the UI appears frozen and a grieving first-time user will think the app has crashed. The passphrase is cached in memory for the rest of the session (see §4). **Subsequent `e` presses:** The cached passphrase is reused automatically — no re-prompting.

3. The app verifies the bundle `hmac` before announcing any delivery state. If HMAC verification fails, the overlay shows: *"Incorrect passphrase, or this file has been modified."* The app returns to the garden without showing a bird, message count, or dated message list.

4. If the HMAC passes, the app computes due messages from authenticated dates and local read receipts. If none are due, the overlay shows: *"No letters today."* and returns to the garden.

5. **If multiple messages are due**, a selection overlay appears:
   ```
     Letters waiting:
     ─────────────────────────────────
     1. June 15, 2027
     2. December 25, 2027
     3. March 10, 2028
     ─────────────────────────────────
     ↑/↓ select · enter to read · esc to return
   ```
   Messages are listed by date (ascending). Labels are not shown until after per-message decryption — only authenticated dates are visible in this list. If only one message is due, this selection is skipped.

6. When the recipient opens a due message, the label is decrypted and shown ("For your 30th birthday"), then the full message renders in the overlay with word-wrap. For long messages, `↑/↓` or `j/k` scrolls within the overlay. A soft indicator at the bottom shows scroll position (*"↓ scroll for more"* or *"end of letter"*). Full-screen interactive TUI screens require a minimum terminal size of **80 columns x 24 rows**; below that, the app shows a resize-required screen or offers the `--accessible` line-mode path instead of rendering a truncated interface. Pressing `p` attempts to print if a supported printer backend is available; otherwise it offers save-to-text-file for manual printing.

7. After reading, `q` or `esc` returns to the garden (or to the selection list if more messages are waiting). The status bar changes: `· message read ·`.

8. A local read-receipt file (`~/.lateletter/recipient/receipts.json`) stores which message IDs have been read (keyed by `bundle_id`), so the bird doesn't reappear on future launches for already-read messages. Using `bundle_id` (rather than file hash) ensures read state persists when the author appends new messages to the bundle.

### 6.5 First-run experience

The first time a recipient opens LateLetter — whether via the macOS app or the browser viewer — is the most emotionally important moment in the product. The recipient may be grieving, non-technical, and unprepared. The first-run sequence is the same across all delivery channels:

1. **The garden appears first.** No text, no prompts, no instructions. The garden renders for 3–5 seconds so the recipient's first impression is beauty, not UI. Weather moves, creatures drift, plants sway.
2. **A welcome line fades in** at the bottom of the garden or as a subtle overlay: *"This garden was planted for you by [author_name]."* This is the moment of recognition. The author's name comes from the plaintext `author_name` field in the bundle.
3. **The status bar appears:** `e · open letters · q · quit`. No jargon. No "unlock" or "authenticate."
4. **On first `e` press:** The passphrase overlay appears (§6.4). The hint is shown immediately — the recipient may not have thought about the passphrase in years.
5. **After successful auth, if letters are due:** The bird flies in, the letter flow begins. After the first letter is read, a brief guide appears: *"Letters will arrive here on special days. Come back anytime — this garden is yours."*
6. **After successful auth, if no letters are due yet:** *"No letters today. This garden is yours. Come back anytime."* The garden continues running. The recipient has been introduced to the space.

The first-run state is tracked locally (`~/.lateletter/recipient/first_run_complete` for the app, `localStorage` for the browser viewer) so this sequence only plays once per device.

### 6.6 Letter archive and re-reading

A grieving person will want to re-read their loved one's words. The read-receipt system (§6.4 step 8) controls bird behavior, not letter access. Once authenticated in a session, the recipient can always access previously read letters.

**Archive access:** Pressing `l` (for "letters") at any time after first successful authentication opens the letter archive:

```
  ╔═══════════════════════════════════════════════════╗
  ║  Letters from Robert                               ║
  ╠═══════════════════════════════════════════════════╣
  ║  ✓  June 15, 2027 — Her 30th birthday              ║
  ║  ✓  December 25, 2027 — That first Christmas        ║
  ║  ◻  March 10, 2028 — (not yet available)            ║
  ║                                                     ║
  ║  ↑/↓ select · enter to read · esc to return         ║
  ╚═══════════════════════════════════════════════════╝
```

- `✓` marks read letters. They can be re-read at any time by selecting them.
- `◻` marks future-dated letters. They are listed (date visible) but locked. Selecting a locked letter shows: *"This letter arrives on [date]."*
- Labels are decrypted and shown for read letters (the passphrase is cached). Unread-but-due letters show dates only (same as the §6.4 step 5 selection overlay). Future letters show only dates.
- The archive is available even when no new letters are due. The bird controls delivery excitement; the archive is the quiet bookshelf.
- The `e` key opens the delivery flow for new due letters. The `l` key opens the archive directly at any time.

**Re-read flow:** Selecting a read letter from the archive opens it in the same reading overlay as the first read (§6.4 step 6), with scroll, save-to-text, and the same soft indicators. No re-read event is logged — the read receipt is already recorded.

### 6.7 Post-completion state

When the last letter in the bundle has been read, the product's delivery mission is complete. The garden must acknowledge this without making the recipient feel abandoned.

**Detection:** After the recipient reads the final due letter (all message IDs in the bundle have corresponding read receipts), the post-completion state activates on the next garden launch.

**What changes:**
- A **memorial flower** appears in the garden — a small, distinct flower that was not present before, planted at the base of the tallest tree. It uses the existing plant layer and is visually distinct from other flowers (a unique color or shape reserved for this purpose). It should feel like something grew there naturally, not like a UI notification.
- The **letter-bird perches permanently** on a tree or branch. It no longer flies or departs. It is simply there, as if it chose to stay.
- The **status bar** changes from `e · open letters` to `l · your letters`. The `e` key is retired; the `l` key opens the archive directly.
- The **archive footer** shows: *"All letters delivered."*
- The garden **keeps running**. Weather changes, seasons turn, creatures visit. It is still the recipient's space.

**What does NOT change:**
- The garden seed and plant layout remain identical.
- Weather, creatures, and seasonal behavior are unaffected.
- No new letters can arrive (unless the author or steward appends to the bundle on a separate machine and provides an updated `.lateletter` file).

**Emotional intent:** The post-completion state is a memorial, not an ending. The garden becomes a place where the letters live permanently — a quiet room the recipient can always return to.

**Post-completion and progression:** See §6.8 for how the progression layer interacts with the post-completion state — bonded animals stay permanently, and any remaining unreleased author garden gifts are unlocked.

### 6.8 Garden Progression Layer

The garden is not just a delivery mechanism — it is a place the recipient tends. Over time, the recipient's care creates a living relationship with the garden: plants they grew, animals that trust them, small authored memories discovered in the landscape. The progression layer is stored independently from the bundle's `garden_seed` — the seed-based garden is the author's gift; the recipient's additions are their own contribution to the shared space.

#### 6.8.1 Design principles (research-informed)

Derived from prior art analysis of passive care games (Neko Atsume, Viridi, Stardew Valley, Tsuki Adventure, Animal Crossing) and grief-tech UX research (SafeBeyond, HereAfter AI, memorial space design). Full research notes archived in project history.

1. **Cumulative investment, not streaks.** Relationship depth is gated by total care actions (e.g., fed the cat 7 times), not consecutive daily visits. A recipient who misses three months picks up where they left off. Consecutive-streak mechanics create anxiety incompatible with grief (Animal Crossing anti-pattern: weeds + shaming on return).
2. **Gentle entropy, immediate recovery.** Plants droop if unwatered for weeks; the cat stops visiting if unfed for a long time. But recovery is instant on return — water the plant once, it perks up. No guilt, no shaming, no "where have you been?" commentary.
3. **Evidence of absence, not punishment.** When the recipient returns after a gap, they find traces: footprints where the cat checked for them, an empty food bowl, a wilted-but-alive plant. The garden noticed they were gone. It waited. (Tsuki Adventure model: "you witness what happened while you were away.")
4. **Automatic nudges, not menus.** Interactions surface via status bar callouts ("a stray cat lingers at the edge…") rather than action menus. The recipient presses a single key to respond. One action at a time — grief reduces decision-making capacity.
5. **The progression layer must not overshadow the letters.** If tending the garden becomes the primary experience and letters feel like interruptions, the design has failed. The garden serves the letters, not the reverse. (Viridi developer insight: scrapped unlock progression because "people would play just to unlock the next plant, which was antithetical to the spirit of the game.")
6. **No unsolicited notifications tied to the deceased.** The garden never pushes notifications referencing the author by name in a guilt context. All engagement is pull-based.
7. **Natural ceiling.** The progression system has a finite depth — the garden reaches a state of fullness, not an infinite treadmill.

#### 6.8.2 Animals

Animals are the primary relationship mechanic. The v1 starter set is **four animals: bird, cat, rabbit, and turtle**.

**Trust tiers (cumulative, not consecutive):**

| Trust tier | Cumulative actions | Behavior |
|-----------|-------------------|----------|
| 0 — Wild | 0 | Animal appears at garden edge occasionally. Status bar nudge: *"a stray cat lingers at the edge… press f to leave food"* (feed key is `f`; `i` is an acceptable alternative — decide during implementation) |
| 1 — Curious | ~3 | Animal enters the garden. Approaches but keeps distance. Food bowl or equivalent interaction point visible. |
| 2 — Familiar | ~7 | Animal is present when the garden opens. Sits in a consistent spot. Reacts visibly to recipient's presence (tail flick, head turn). |
| 3 — Bonded | ~14 | Animal has a "home" spot in the garden. Naps on warm rocks. **On letter delivery days, this animal delivers the letter instead of the default letter-bird** (see §6.3 cross-reference). |

**Per-animal details:**
- **Cat:** Multi-line ASCII art. Sits, walks, tail-flick, naps. Can have a colored collar and nametag — author-assigned during garden direction (§6.8.5) or recipient-chosen. The cat's name is part of the relationship.
- **Bird (relationship bird):** Distinct from the ambient sky birds (§7.1) and the letter-bird. Species variety (robin, sparrow, cardinal). Perches on trees, hops on ground near food.
- **Rabbit:** Ground-level, shy. Hops near flowers. Tucks up when startled. Most visible at trust tier 1–2; at tier 3 it naps curled near a flower bed. ASCII art (two rows):
  ```
  (\ /)
  . .
  ```
  Unicode variants welcome in the browser viewer (pretext handles full Unicode); terminal renderer uses 1-column-width characters only (safe for curses width tracking).
- **Turtle:** Slow, reliable, always eventually arrives. Deliberate ground movement. Never startles. Stays longer than any other animal at each tier — the tortoise of the garden. At trust tier 3 it has a favorite rock it always returns to. ASCII art TBD during implementation (two-line shell silhouette).

**Absence and recovery:** Trust does not decrease on absence. But evidence of the animal's visits appears: footprints in the ground row, feathers near the perch, claw marks on a tree trunk, an empty food bowl. The animal returns within 1–2 visits of resumed care — it was waiting.

**Letter delivery integration:** When the recipient has reached trust tier 3 (Bonded) with any animal, that animal delivers letters on due dates instead of the default letter-bird (§6.3). The cat carries the envelope in its mouth; the bird carries it in talons. If multiple animals are bonded, the most recently interacted-with delivers. This ties the recipient's care of the garden to the emotional climax of letter delivery. If no animal is bonded, the default letter-bird behavior (§6.3) is unchanged.

#### 6.8.3 Items (author-programmed memory capsules)

Items are small ASCII art objects (2–4 glyphs) placed in the garden by the author during garden direction (§6.8.5). When the recipient interacts with an item (approaches and presses enter), it reveals a short author-written sentiment — a tiny memory, not a full letter.

**Examples:**
- A plate of food → *"Blueberry muffin from Mary's bakery on 20th st."*
- A pair of shoes → *"Your first hiking boots. You refused to take them off for a week."*
- A coffee mug → *"Our Sunday morning ritual. Two sugars, always."*
- A small radio → *"That song we couldn't stop playing the summer of '09."*

Items appear in the garden based on their trigger (§6.8.4). Once revealed, the sentiment text displays as a soft overlay that fades after a few seconds or on keypress. Discovered items remain visible in the garden permanently — they become part of the landscape.

The item catalog is finite and curated. The v1 catalog is **15 objects** (finalized):

| ID | Display name | Art |
|----|-------------|-----|
| `coffee_mug` | A coffee mug | `( ~ )` |
| `teacup` | A teacup | `{ ~ }` |
| `plate_of_food` | A plate of food | `[o.o]` |
| `pair_of_shoes` | A pair of shoes | ` >,> ` |
| `book` | A book | ` [=] ` |
| `small_radio` | A small radio | `[~=~]` |
| `candle` | A candle | ` .*\| ` |
| `pocket_watch` | A pocket watch | ` (@) ` |
| `photo_frame` | A photo frame | ` [ ] ` |
| `pressed_flower` | A pressed flower | ` *·* ` |
| `fishing_rod` | A fishing rod | ` /~~ ` |
| `compass` | A compass | ` (^) ` |
| `old_key` | An old key | ` >-) ` |
| `small_stone` | A small stone | ` (.) ` |
| `ribbon` | A ribbon | ` ~o~ ` |

The author picks an object from the catalog and writes the sentiment text (1–2 sentences). The sentiment is encrypted alongside letter content in the bundle (same passphrase, same security model).

#### 6.8.4 Trigger types

Author-programmed garden elements (plants, animals, items, landmarks, task nudges) appear based on one of three trigger types:

| Trigger | How it works | Example |
|---------|-------------|---------|
| **Date-locked** | Appears on or after a specific date (same mechanism as letter delivery) | Rosebush appears on recipient's 31st birthday |
| **Cumulative-visit-locked** | Appears after N total garden visits | Birdhouse appears after the recipient's 10th visit |
| **Post-letter** | Appears after a specific letter is read (keyed by message ID and read receipt) | After the birthday letter is read, a carved bench appears with the author's initials |

Post-letter triggers tie the garden's evolution to the emotional arc of the letters. The garden grows in response to the recipient reading and absorbing the author's words. A rosebush that appears after the birthday letter creates a tangible trace of that moment in the garden's landscape.

#### 6.8.5 Author garden direction (Phase 2 authoring)

After letter writing (Phase 1 authoring — intake, Q&A, drafts, encryption), the author may optionally enter a **garden direction** session. This session is entirely skippable — the garden runs a complete, beautiful experience without any authored garden elements. The progression layer's animal relationships and recipient-initiated interactions work regardless.

**Catalog (v1 — finite starter set):**

| Category | Options | Author specifies… |
|----------|---------|-------------------|
| Plants | Sapling, willow, rosebush, sunflower, herb garden | Which plant, placement hint ("near the big tree," "by the edge"), trigger |
| Animals | Cat, bird, rabbit, turtle | Which animal, optional name, optional collar color (cat), trigger for first appearance |
| Items | 15 curated ASCII objects — see §6.8.3 catalog | Which item, sentiment text (1–2 sentences), trigger |
| Landmarks | Carved rock, small bench, birdhouse, wind chime, lantern | What it is, optional inscription text, trigger |
| Task nudges | Author-written gentle prompts | The prompt text ("Plant something new today," "Sit with the cat for a minute"), trigger |

**Author UX:** Rich but optional. Presented as a guided flow after letter completion: *"Would you like to leave something in the garden too?"* The author picks from the catalog, writes sentiment/inscription text, and assigns a trigger. One item at a time, fatigue-aware, auto-saved. Matches the existing intake style (§5.1). The session can be entered and exited freely — partial garden direction is saved and resumable.

**Task nudges:** Author-written prompts that appear as gentle status bar messages on their trigger date or visit count. They are suggestions, not obligations: *"Plant something new today."* *"Watch the sunset."* *"Look up — count the birds."* The recipient can ignore them. They are the author reaching forward in time to share a moment, not assign homework.

#### 6.8.6 Bundle schema addition

Garden direction data is stored in the `.lateletter` bundle as a new top-level field:

```json
{
  "garden_gifts": [
    {
      "id": "uuid4",
      "type": "item | plant | animal | landmark | nudge",
      "catalog_id": "plate_of_food",
      "sentiment": "<ciphertext>",
      "salt": "...",
      "nonce": "...",
      "trigger": {
        "type": "date | cumulative_visits | post_letter",
        "value": "2028-06-15 | 10 | <message_id>"
      },
      "placement_hint": "near_tallest_tree | by_edge | random",
      "animal_name": null,
      "animal_collar_color": null
    }
  ]
}
```

- `sentiment` is encrypted with the same passphrase and per-gift salt/nonce (same model as message ciphertext). Gift sentiments, animal names, and inscription text are private.
- `trigger.value` is plaintext for date-locked gifts (same privacy model as message dates — anyone can see *when*, not *what*). Cumulative-visit and post-letter trigger values are also plaintext (visit count is a number, post-letter is a message ID reference).
- `placement_hint` guides procedural placement relative to seed-based garden elements.
- `garden_gifts` is included in the `checksum` and `hmac` computation (added to the canonical visible payload field list alongside `messages`).

#### 6.8.7 Recipient state persistence

Progression state is stored in `~/.lateletter/recipient/garden_state.json`, separate from the bundle and from read receipts:

```json
{
  "<bundle_id>": {
    "total_visits": 42,
    "last_visit": "2027-08-15",
    "animals": {
      "cat": {
        "name": "Whiskers",
        "trust_actions": 12,
        "trust_tier": 3,
        "last_fed": "2027-08-15"
      }
    },
    "recipient_plants": [
      { "type": "sapling", "position": [12, 18], "planted_at": "2027-07-01", "growth_stage": 3 }
    ],
    "discovered_items": ["<gift_id>"],
    "completed_nudges": ["<gift_id>"]
  }
}
```

The browser viewer stores equivalent state in IndexedDB (namespaced `lateletter_v1_` prefix). If browser storage is unavailable, progression features are disabled but letters remain fully readable.

#### 6.8.8 Post-completion integration

When the last letter has been read (§6.7), the post-completion state incorporates the progression layer:

- If the recipient has a bonded animal (trust tier 3), it **perches permanently** — the cat naps in its home spot, the bird sits on its branch. It no longer leaves.
- The **memorial flower** from §6.7 still grows at the base of the tallest tree.
- Any remaining **unreleased garden gifts** (items, plants, landmarks with future triggers) are **unlocked immediately** — the author's full garden vision is revealed regardless of trigger conditions. Nothing is left hidden.
- The **archive footer** changes to: *"All letters delivered. This garden is yours."*
- The garden **keeps running** — the recipient can continue tending it indefinitely. The progression ceiling may have been reached, but the garden lives.

#### 6.8.9 Scope

| Scope | What's included |
|-------|----------------|
| **v1 (ship-blocking)** | Cumulative visit tracking. Up to one active animal relationship (author picks which of the four animals to include — bird, cat, rabbit, or turtle). Author garden direction with starter catalog. Items (15-object catalog) as memory capsules. All three trigger types. Post-letter delivery integration (bonded animal delivers). Footprints-on-absence. Post-completion gift release. |
| **v1.5 (post-ship)** | Multiple simultaneous animal relationships. Expanded plant catalog. Recipient-initiated planting. Deeper trust tiers beyond Bonded. Rare seasonal events. |

---

### 6.9 Emotional arc — experiential criteria and verification

The recipient mode is functionally complete as a set of features. It has not yet been verified as an *experience*. Five moments define the emotional arc of the product; each must be validated through direct observation before v1 ship. The demo harness (§24 step 11b) exists specifically to make this evaluation possible.

**The five moments:**

#### Moment 1 — The waiting

*The garden before any letter arrives.*

What must be true: A day with no due messages must feel like a place worth returning to — not an empty state, not a loading screen with a prompt. Weather moves, a creature visits, a plant sways in the wind. There is nothing that says "nothing is here." The ambient experience IS the experience. The garden is enough.

Verify: Open the demo bundle with all messages future-dated. Watch the garden for two minutes without pressing anything. Does it hold attention? Does it feel like someone made it for you?

Failure mode: The garden feels like a screensaver waiting for input. The recipient closes it.

#### Moment 2 — The delivery

*A letter arrives. The bird is here.*

What must be true: The letter-bird's appearance must feel like an event, not a UI state change. There is a beat — the bird arrives and waits — before the recipient acts. When they press `e`, the garden dims and there is a moment of anticipation before text appears. The letter should feel like it came from far away.

Verify: Open the demo bundle with one past-due message. Watch from launch to letter text on screen. Does the pacing create weight? Or does it feel like a dialog box?

Failure mode: The bird spawns, the recipient presses `e`, the overlay appears. It feels like an alert. No sense of occasion.

#### Moment 3 — The animal trust arc

*A relationship, built slowly.*

What must be true: Each tier transition must be perceptible and feel earned. Tier 0 (animal peeks from the garden edge, skittish) → tier 1 (visits but keeps distance) → tier 2 (approaches, can be fed) → tier 3 (bonded, stays). The recipient should feel the relationship deepening over time. No numeric progress bars — only visible behavioral change.

Verify: Use `Shift+A` to cycle all 16 animal states across all 4 animals. Is each tier visually distinct from the last? Does tier 3 feel like something the garden chose to give?

Failure mode: Tiers look nearly identical. The recipient never notices the animal is getting closer.

#### Moment 4 — Post-completion

*The last letter has been read.*

What must be true: When the delivery mission is complete, the garden must mark it without feeling like a "thank you" screen. The memorial flower grows, the bird stays permanently. The recipient must sense the garden has changed — and also that it hasn't ended. They still have a place to return to.

Verify: Mark all receipts as read in the dev fixture. Open the garden. Does it feel like a memorial — quiet, present, complete — or does it feel like an app that ran out of content?

Failure mode: Post-complete garden looks nearly identical to the normal garden. The moment passes unnoticed.

#### Moment 5 — Item discovery

*A gift, hidden in the garden.*

What must be true: When a triggered item appears, it must feel discovered, not delivered. The item is present in the garden scene; the status bar notes it quietly (`i · examine`). The memory overlay reads like a note left by the author in the soil — personal, unhurried, a little surprising. Not a push notification.

Verify: Trigger a date-locked item using the dev fixture. Read the memory overlay text aloud. Does it feel like the author speaking to the recipient, or like a game achievement?

Failure mode: The memory overlay text is generic or announcement-style. The item feels like a feature, not a gift.

---

**Verification gating:** Each of the five moments above must receive an explicit pass from a human observer (not just a code review) before v1 ship. The demo harness (§24 step 11b) is the tool; this section is the rubric. Document outcomes in a brief one-paragraph field note per moment — what worked, what didn't, what was adjusted.

---

## 7. Garden — Animation System

### 7.1 Approved animations

All animations prototyped in `ascii-animations/` are approved for integration into the garden. The prototypes define the visual language — integration must preserve the look and feel established there.

**Creatures:**

| Animation | Prototype | Description | Procedural generation |
|-----------|-----------|-------------|----------------------|
| Butterfly | `creatures/anim_butterfly.py` | `><`, `\|\|`, `\/` frame cycle; wanders left-right with sine-wave vertical drift and occasional up-dip | **Spawn**: random edge entry at intervals (season-weighted). **Path**: Perlin-noise or sine-composite wandering with altitude drift and occasional perch pauses. **Variety**: randomize wing-beat speed (±30%), flight altitude band, and drift amplitude per instance. |
| Bird (ambient) | `creatures/anim_birds.py` | Single-char `v`/`~` silhouettes flying across sky; visually distinct from multi-line letter-bird | **Spawn**: random entry from left or right edge at sky altitude. **Path**: linear traversal with slight sine wobble. **Variety**: randomize speed, altitude, direction, and character (`v`/`~`/`^`). Occasional 2-3 bird groups with staggered positions. |
| Letter-bird | `creatures/anim_letterbird.py` | Multi-line ASCII art carrying `[✉]`; flies in from edge, perches on tree. Phase 2 deliverable (§6.3), visual refinement here | Integration contract only — runtime appearance controlled by bundle auth state, not by the animation system. |
| Fireflies | `creatures/anim_fireflies.py` | `*`/`·` blink on/off in lower third; Photinus-style flash patterns (species-accurate timing) | **Spawn**: scatter N fireflies in lower 2/3 of garden at random positions. **Flash**: each firefly has independent phase offset and species-style flash duration (150-400ms on, 1-3s off). **Variety**: randomize flash interval, position drift (slow wander ±1 char), and brightness char (`*` vs `·`). Night/dusk only. |
| Lightning | `weather/anim_rain.py` | Jagged bolt walk with forks, char aging `#` → `+` → `*`, screen flash (DECSCNM reverse video) | **Spawn**: probabilistic during rain (1-5% chance per 2s interval). **Path**: top-down jagged random walk with fork probability at each step. **Variety**: randomize start x-position, fork count (0-3), bolt length, and flash duration. |

**Weather:**

| Animation | Prototype | Description | Procedural generation |
|-----------|-----------|-------------|----------------------|
| Rain | `weather/anim_rain.py` | Diagonal `\|`/`/` streaks falling with gravity; ground row splashes on impact | **Spawn**: continuous random x-positions across full width at density controlled by intensity param. **Physics**: constant fall speed + slight diagonal drift (wind-influenced). **Splashes**: on ground contact, spawn 1-3 frame splash chars (`.` → `·` → gone). **Variety**: randomize drop length (1-3 chars), drift angle, fall speed (±20%). |
| Snow | `weather/anim_snow.py` | Sparse `·`/`*` drifting downward; accumulates on ground and tree canopy | **Spawn**: random x-positions at low density. **Physics**: slow fall with sine-wave horizontal drift (wind). **Accumulation**: track snow depth per column on ground row and on plant collision surfaces; draw accumulated snow chars when depth > threshold. **Variety**: randomize drift frequency, fall speed, and flake char. |
| Clouds | `weather/anim_clouds.py` | `(~)`, `(~~~)`, multi-line shapes drifting slowly left at sky rows | **Spawn**: random entry from right edge at intervals (season-weighted density). **Path**: constant leftward drift at cloud-specific speed. **Variety**: procedurally generate cloud shape from width param (3-12 chars) using tilde/paren composition. Randomize altitude (top 3 rows), speed, and shape. |
| Falling leaves | `nature/anim_leaves.py` | `\`/`-`/`/` chars tumbling downward with wind-driven horizontal drift | **Spawn**: 70% detach from `canopyCells` (LEAF_CANOPY plants, dy ≥ 3); 30% originate from sky (rows 0–2) with wider initial vx. Dynamic cap: `Math.max(0, Math.min(60, Math.floor(canopyCells.size / 3)))`. **Physics**: gravity (`vy += 0.04`), wind-driven drift (`vx += wind * 0.04`, clamped ±0.8), rotation (`rotPhase` increments every 8 frames; char cycle: `\`→`-`→`/` loop). **Ground**: leaves reaching `groundY` transition to `leaf-rest` (char `-`, 40-frame rest, then removal). **Variety**: randomize initial vx/vy per spawn origin; colour from `AUTUMN_COLS`. Autumn only. |

**Plants (new types):**

| Plant | Notes | Procedural generation |
|-------|-------|----------------------|
| Willow | Wide drooping branches, tall; wind causes sway | **Generate**: trunk height (5-8), branch count (3-5 per side), branch droop angle. Sway: branch tips oscillate ±1-2 chars on wind timer. **Variety**: randomize trunk height, branch lengths, droop depth. |
| Cactus | 3–4 chars wide, desert feel, no sway | **Generate**: trunk height (3-6), arm count (0-2), arm side and height. **Variety**: randomize proportions; arms optional. |
| Bamboo | Tall, narrow, clustered | **Generate**: stalk count (2-5) in a cluster, height per stalk (6-12), node spacing. **Variety**: randomize heights within cluster, slight lean angles. |
| Lily | Short flower with wide head | **Generate**: stem height (2-3), head width (3-5 chars), petal pattern. **Variety**: randomize head shape from template set. |
| Sunflower (tall) | Single-stem, distinct from current small sunflower | **Generate**: stem height (5-8), head diameter (3-5 chars), leaf positions on stem. **Variety**: randomize height and head tilt (left/center/right). |
| Dead tree | Leafless branching silhouette — for autumn/winter seasons | **Generate**: trunk + recursive branching (depth 2-3), branch angle variety, no canopy fill. **Variety**: randomize branch structure via L-system-style rules or constrained random walk. |

### 7.2 Rendering architecture

The garden renderer uses a **5-layer compositing model**. Each layer updates independently at its own cadence and writes to a shared screen buffer. Layers are drawn back-to-front; later layers overwrite earlier ones at occupied cells.

| Layer | Contents | Update cadence | Notes |
|-------|----------|---------------|-------|
| 0 — Background | Sky gradient, ground row | On resize or season change | Static except for time-of-day palette shifts |
| 1 — Plants | Trees, flowers, new plant types with wind sway | 300–500ms | Procedurally placed by seed; sway frames cycle on wind timer |
| 2 — Particles | Rain, snow, falling leaves | 40–80ms (fast) | Particle system: spawn/update/kill per frame. Each particle has position, velocity, lifetime |
| 3 — Creatures | Birds, butterflies, fireflies | 100–200ms | Independent movement AI per creature. Spawn/despawn at screen edges |
| 4 — Special | Letter-bird, message overlays | Event-driven | Controlled by bundle auth state, not animation timer. Highest z-order |

**Shared particle API:** All particle-based animations (rain, snow, leaves, firefly flashes, splashes) use a common `Particle` type with: `x: float, y: float, vx: float, vy: float, char: str, lifetime: int, color_pair: int`. The particle system runs a single update loop per frame that iterates all active particles, applies per-type physics (gravity, wind, drift), handles collisions with plant surfaces, and kills expired particles.

**Plant collision surfaces:** Each plant registers its occupied cells as a collision map at placement time. Particles check this map for: snow accumulation (land on top surface), rain splashes (trigger splash on contact), leaf detachment points (spawn leaves from canopy cells).

**Performance budget:** Target 50ms frame time (20 FPS) on the composited garden. Individual layer updates must not exceed 10ms. If frame budget is exceeded, reduce particle density before dropping frames.

**Integration with `garden.py`:** The Phase 1 refactoring of `garden.py` (step 3 in §24) must produce a renderer module that supports this layer model. The current monolithic `garden.py` draws plants directly to the screen — the refactored renderer must separate plant placement from screen drawing so animation layers can composite between them.

**Tick cadence note:** The browser viewer (`viewer-bnw.html`) uses a unified ~50ms RAF tick for all layers. The per-layer cadences listed in the table above (plants 300–500ms, particles 40–80ms, creatures 100–200ms) describe the curses/TUI design intent. Both are conformant implementations of this rendering architecture.

**Canopy surface models:** The particle system uses two distinct collision surface models, each serving a different physical purpose:

- **`canopyCells`** — cells from LEAF_CANOPY plants (oak, willow) at `dy ≥ 3` above the plant base. Drives leaf spawn origin (70% of autumn leaf spawns detach from these cells). Pine is excluded — evergreens do not shed leaves.
- **`topSurfaces`** — per-column topmost occupied cell across *all* plant types (including pine). Drives snow accumulation in winter. This surface runs unconditionally with no plant-type gate.

The `dy ≥ 3` threshold excludes trunk rows (the bottom 1–2 rows above base) from the canopy set, preventing leaves from spawning at unnaturally low positions on the plant.

### 7.3 Procedural generation philosophy

All visual elements in the garden are **procedurally generated from the `garden_seed`**, not selected from a fixed library of pre-drawn ASCII art. This means:

- **Plants** are assembled from parameterized templates: trunk height, canopy shape, branch structure, flower pattern. The seed determines which parameters are chosen for each plant in the garden, making each recipient's garden unique but deterministic.
- **Creatures** have procedurally varied behavior: flight paths, speeds, flash patterns, spawn timing. The seed initializes the RNG that drives these variations.
- **Weather** intensity and particle density are season-driven with seed-based variation in timing and placement.
- The prototypes in `ascii-animations/` establish the **visual vocabulary** (what a butterfly looks like, how rain falls). The integration work translates these into parameterized generators that produce variety from the seed.

**What "procedural" means concretely for each element type:**

- **Plant generators** take `(seed, position, season)` and return a renderable plant with sway frames. The generator uses constrained random parameters (height ranges, branch counts, canopy density) seeded deterministically. Two gardens with different seeds produce visibly different arrangements; the same seed always produces the same garden.
- **Creature spawners** take `(seed, season, time_of_day)` and produce a schedule of spawn events. Each creature instance gets randomized movement parameters from the seed-derived RNG.
- **Weather systems** take `(season, wind_strength)` and spawn particles at procedurally varied rates. Snow accumulation state is persistent within a session (builds up over time).

**Extending the garden with new animations:** To add a new animation type:
1. Prototype it as a standalone curses script in `ascii-animations/` to find the visual language.
2. Define its procedural parameters (what varies, what's fixed, what ranges).
3. Implement it as a generator conforming to the layer/particle API.
4. Register it in the appropriate layer and season/time-of-day activation table.

**Foliage character vocabulary:** All plant and particle characters are drawn from the following canonical vocabulary. Future plant types must choose from this table or explicitly extend it with a new role entry.

| Role | Chars | Used by |
|------|-------|---------|
| Trunk / stem | `\|` | all plants |
| Deciduous foliage fill | `@ o 0 &` | oak, willow |
| Coniferous fill | `/ \ ^ *` | pine |
| Soft-edge / hedge fill | `~ u w v` | bush |
| Fern frond | `* ,` | fern |
| Grass tip | `/ \ \` '` | grass |
| Flower head | `O # @ ( ) "` | all flower types |
| Accent / particle | `* . , ' \`` | mushroom caps, falling leaves |

Note: `@` is intentionally shared between deciduous foliage fill and flower head — this is historical overlap between dense foliage and dense flower clusters. Existing rose code is correct. Within a single new plant type, chars should not mix roles from unrelated rows.

#### 7.3.1 Layout algorithm

The `genLayout` function places plants procedurally within the garden area using the following constants:

- **Attempt count:** `cols × 3` — the number of random placement attempts per generation pass
- **Collision padding:** `±2` columns beyond the plant's half-width, preventing overlap
- **Expected density:** ~1 plant per 10–15 columns at typical viewport widths (80–120 cols)
- **Sparse gardens:** At narrow viewports (< 60 cols), gardens may contain only 1–3 plants; this is correct by design — the layout algorithm does not force minimum density
- **No intentional clearings** in v1; the algorithm distributes plants uniformly across available space

### 7.4 Seasons

Derived from system date (or overridden with `--season spring/summer/autumn/winter`):

| Month range | Season | Active animations | Plant palette |
|-------------|--------|------------------|---------------|
| Dec–Feb | winter | Snow, bare trees, clouds | Conifers, dead oak, muted greens |
| Mar–May | spring | Butterflies, light rain, clouds | Flowers dominant, bright greens |
| Jun–Aug | summer | Fireflies at dusk, birds, clouds | Full palette |
| Sep–Nov | autumn | Falling leaves, rain, lightning | Warm colors (yellows/reds), dead trees |

Season affects:
- `_WEIGHTS` for plant types (e.g., dead trees weighted heavily in winter, flowers in spring)
- Color palette (yellows/reds dominant in autumn, muted greens in winter)
- Active ambient animations (see table above)
- Creature spawn rates (butterflies peak in spring, fireflies in summer)
- Weather intensity (rain heavier in autumn, snow only in winter)

**Wind model:** `state.wind = 0.5 * Math.sin(state.frame * 0.008)`. Range: ±0.5 (dimensionless coupling factor). Period: ~785 frames ≈ 39 seconds at 50ms/tick. Effect coupling coefficients:

| Effect | Formula | Notes |
|--------|---------|-------|
| Rain drift | `wind * 0.3` | Applied to rain vx each tick |
| Leaf drift | `wind * 0.04` | Accumulated into leaf vx (clamped ±0.8) |
| Rustle char | via `rustleChar` | Drives foliage character variation |

Moments of true calm (sin ≈ 0) are intentional pleasant pauses in the garden's rhythm.

**Plant classification:** Plants are organized into four classes that determine autumn behaviour and leaf-canopy membership.

| Class | Plants | Autumn recolor | Leaf canopy (LEAF_CANOPY) | Snow canopy (CANOPY) |
|-------|--------|---------------|--------------------------|---------------------|
| Deciduous | oak, bush, willow | Yes — foliage → `AUTUMN_COLS` | oak, willow | oak |
| Evergreen | pine, fern, grass, mushroom | No | — | pine |
| Flowering | flower (all types) | No | — | — |
| Dead/bare | dead tree *(planned)* | No (already brown) | — | — |

Additional planned plant types: cactus (evergreen), bamboo (evergreen), lily (flowering), sunflower (flowering). `CANOPY` (pine, oak) gates snow accumulation via `topSurfaces`; `LEAF_CANOPY` (oak, willow) gates leaf spawn via `canopyCells`. The two sets serve different physical purposes and must not be conflated.

### 7.5 Time of day (optional)

Derived from system time or `--time day/dusk/night`:
- **Day**: Default palette, full color.
- **Dusk/Evening**: Palette warms (amber sky gradient), fireflies spawn, moon not yet visible.
- **Night**: Dark sky gradient, stars, moon phase glyph, no fireflies, ambient birds cease.

---

### 7.6 Garden state dimensions

The garden has **six independent state dimensions** that compose multiplicatively. Each dimension has its own state machine, its own trigger sources, and its own visual output. They are not nested — they overlay. A garden is always in exactly one state per dimension simultaneously.

| Dimension | States | Trigger source | Layer(s) affected |
|-----------|--------|---------------|-------------------|
| Season | spring / summer / autumn / winter | System date (or dev `<`/`>`) | Plants (§0), Particles (§2), Creatures (§3) |
| Time of day | day / evening / night | System clock (or dev) | Background (§0), Creatures (§3) |
| Weather | calm / rain / snow / leaves | Season → probabilistic | Particles (§2) |
| Animal trust | 0 (stranger) / 1 (familiar) / 2 (bonded) / 3 (full bond) | Feed actions (`f`) | Creatures (§3), Special (§4) |
| Gift discovery | hidden / revealed / examined | Trigger type (date / visits / post-letter) | Special (§4), HUD |
| Completion state | normal / post-complete | All messages read + all gifts examined | Special (§4), Creatures (§3) |

**Composition rule:** Higher-numbered layers overwrite lower-numbered layers at occupied cells. The completion state (layer 4) always overrides creature positioning. Time-of-day overrides Background but does not override Plants. Season governs which weather particles are active but not their individual positions (those are frame-by-frame random).

---

### 7.7 Garden state machine architecture

*This is the canonical reference for all state transitions in the garden. Each subsystem has its own section with: states, transitions, triggers, visual signature, and user flow.*

---

#### 7.7.1 Season subsystem

**States:** `spring` | `summer` | `autumn` | `winter`

**Trigger:** Derived from calendar month. Transitions happen on the first visit of the month that falls in the new season range. No animation on transition — the garden re-seeds from the same `garden_seed` for a consistent but visually fresh layout.

**State machine:**
```
     Dec–Feb          Mar–May          Jun–Aug          Sep–Nov
winter ──────► spring ──────► summer ──────► autumn ──────► winter
         Jan 1           Mar 1           Jun 1           Sep 1
```

**Visual signature per season:**

| State | Sky | Plants | Weather | Creatures |
|-------|-----|--------|---------|-----------|
| spring | Cream (#f9f8f5) | Flowers dominant, bright greens | Light rain (`|`), butterflies | Butterflies, birds |
| summer | Cream | Full palette | Calm (occasional clouds) | Butterflies, birds, fireflies (evening) |
| autumn | Cream → warming | Yellows/reds/browns, dead trees | Heavy rain, falling leaves | Birds, fewer butterflies |
| winter | Cream → cooler | Conifers, bare oaks | Snow accumulation | Birds (rare), no butterflies |

**User flow (season):**
```
[Visit page] → derive season from date
    → regenerate PlantLayer from seed+season
    → activate season-appropriate ParticleLayer spawn rules
    → adjust CreatureLayer spawn weights
    → palette unchanged (B&W) but plant color distribution shifts
```

---

#### 7.7.2 Time-of-day subsystem

**States:** `day` | `evening` | `night`

**Trigger:** System clock hour. Day: 06:00–19:00. Evening: 19:00–22:00. Night: 22:00–06:00.
Dev override: `<`/`>` cycling includes `-night` suffix variants for each season; `evening` is a separate planned dev key.

**State machine:**
```
     06:00      19:00      22:00      06:00
day ──────► evening ──────► night ──────► day
```

**Visual signature:**

| State | Sky gradient | Stars | Moon | Fireflies | Ambient birds |
|-------|-------------|-------|------|-----------|---------------|
| day | C.sky / C.dim_green (cream) | No | No | No | Yes |
| evening | Amber shift (warm gradient) | No | No | Yes (summer) | Fewer |
| night | #0b0e16 / #13181e (near-black) | Yes (seeded scatter) | Yes (phase glyph) | No | No |

**Moon phases (night only):**
Moon phase index = `Math.floor(Date.now() / 86400000 / 3.69) % 8` — one phase step every ~3.7 days through 8 phases:
```
0: (absent — new moon)    4: O   (full)
1: )   (waxing crescent)  5: C   (waning gibbous)
2: D   (first quarter)    6: (   (last quarter)
3: (O  (waxing gibbous)   7: (   (waning crescent)
```
Moon is rendered as a 2–3 row ASCII glyph in the upper-right sky quadrant. It should be at minimum 4 chars wide for readability.

**User flow (time-of-day):**
```
[Visit page] → check clock hour → set timeOfDay state
    → if night: set dark sky gradient, scatter stars, place moon glyph
    → if evening: warm sky gradient, enable firefly spawn (summer only)
    → if day: default sky gradient, no stars/moon
    [Creatures] → fireflies only spawn if evening && season===summer
    [Ambient birds] → spawn rate halves at evening, zeroes at night
```

---

#### 7.7.3 Weather subsystem

**States:** `calm` | `rain-light` | `rain-heavy` | `snow` | `leaves`

Weather is not a discrete state machine — it is a **probabilistic spawn layer** driven by season. Multiple weather types can be active simultaneously (leaves + rain in autumn).

**Spawn rules per season:**

| Season | Active weather | Particle color |
|--------|---------------|----------------|
| spring | rain-light: `|` @ ~35% spawn rate | blue-gray (`rain` palette entry) |
| summer | calm; cloud sprites (planned) | — |
| autumn | rain-heavy: `\|/` @ ~50% rate + leaves from canopy | rain: blue-gray; leaves: yellow/red/brown |
| winter | snow: `.`/`*` drift + accumulation | bright_white |

**Rain particle color:** Use dedicated `rain` palette entry (`#4a6888`) — not `cyan`. Cyan reads as green on this palette. Splash/fragment particles inherit rain color.

**Clouds (planned):** `(~)` / `(~~~)` drifting left at rows 0–2 in all seasons at varying density. Not yet implemented.

**User flow (weather):**
```
[Each frame] → ParticleLayer._spawn(state)
    → check state.season + active particle counts
    → probabilistically push new particles into pool
    → update: apply per-type physics (gravity/wind/drift/accumulation)
    → render: buf.putAnim() so particles stay colored in mode 3
    → kill: particles past maxAge or past ground/surface collision
```

---

#### 7.7.4 Animal trust subsystem

**States:** `absent` | tier 0 (stranger) | tier 1 (familiar) | tier 2 (bonded) | tier 3 (full bond)

`absent` = no animal gift in bundle, or animal gift not yet triggered. `tier 0–3` = animal gift triggered, trust level derived from accumulated `trust_actions`.

**Thresholds:** 0–2 actions → tier 0; 3–6 → tier 1; 7–13 → tier 2; 14+ → tier 3.

**State machine:**
```
absent ──[gift trigger fires]──► tier 0 (stranger, right-edge peek)
  tier 0 ──[f × 3]──► tier 1 (familiar, home position, footprints if was absent)
  tier 1 ──[f × 4]──► tier 2 (bonded)
  tier 2 ──[f × 7]──► tier 3 (full bond — animal moves to perch at post-complete)
```
Trust actions persist across sessions in IndexedDB / localStorage.

**Visual signature per tier (all animals share the pattern; art varies):**

| Tier | Position | Behavior | User cue |
|------|----------|----------|----------|
| 0 | Right edge, partial peek | Appears/disappears on 6-frame interval | HUD: "a stray X lingers at the edge… [f] to leave food" |
| 1 | Home position (25% from left, groundY-4) | Static art, footprints on first arrival | HUD: "[f] · feed the X" |
| 2 | Home position | Static art, no footprints | HUD: "[f] · feed the X" |
| 3 | Home position (day); perch at post-complete | Static art; moves to flower perch when post-complete | HUD: silent |

**Feed interaction (`f` key):**
- Guard: authenticated (`cachedPassphrase !== null`) + animal triggered + tier < 3
- Effect: increment `trust_actions`, recompute tier, persist to storage, update garden
- Visual response (rabbit): carrot overlay `" / \/` appears at animal position for 1.5s
- Other animals: need their own feed-response art (planned — see item 5, this log)

**Per-animal behavioral signatures (to be designed per tier):**

| Animal | Tier 0 | Tier 1 | Tier 2 | Tier 3 |
|--------|--------|--------|--------|--------|
| Rabbit | Peeks from right | Sits, twitches (planned) | Hops (planned) | Grooms (planned) |
| Cat | Peeks from right | Sits, tail flick (planned) | Curls up (planned) | Purrs/kneads (planned) |
| Bird | Peeks from right | Perches, head-tilt (planned) | Hops on branch (planned) | Sings (planned) |
| Turtle | Peeks from right | Slow walk (planned) | Retracts/extends (planned) | Sunbathes (planned) |

**User flow (animal):**
```
[Bundle load] → find animal gift → check trigger → if triggered: load trust from storage
    → derive tier from trust_actions
    → garden.setAnimalData({type, tier, triggered, wasAbsent})
    → CreatureLayer renders at appropriate position+art
[f key pressed] → guard checks → feedAnimal()
    → increment trust_actions → recompute tier → persist
    → if rabbit: show carrot overlay 1.5s
    → garden.setAnimalData() → re-render
    → _updateAnimalHud()
```

---

#### 7.7.5 Gift discovery subsystem

**States:** `hidden` | `revealed` | `examined`

**Trigger types:** date (ISO date ≤ today), cumulative_visits (visitCount ≥ threshold), post_letter (letter read receipt saved).

**State machine:**
```
hidden ──[trigger fires on load]──► revealed (giftDiscovered[id]=true, stored)
revealed ──[user opens archive + clicks gift]──► examined (memory modal shown)
```
Gifts do not un-reveal. Examined state is visual/UX only — the underlying `giftDiscovered` flag is the same as revealed.

**Gift types:**

| Type | Visual form | Trigger | Examination |
|------|-------------|---------|-------------|
| animal | Creature appears in garden | date / cumulative_visits | N/A — animal, not a modal |
| item | Interactable object in garden | date / cumulative_visits / post_letter | Memory modal with sentiment text |
| nudge | Text appears in archive | date | Memory modal with message text |

**User flow (gift):**
```
[Bundle load] → for each gift: check trigger condition against today/visitCount/readIds
    → if trigger fires: giftDiscovered[id]=true, persist to storage
[Garden/archive view] → if gift revealed + type=item: render item in garden at placement_hint
[User clicks item in archive] → openMemory(gift) → modal shows sentiment/text
```

---

#### 7.7.6 Post-completion subsystem

**States:** `normal` | `post-complete`

**Trigger:** All messages have been read (`readIds.size === bundle.messages.length`) AND all gifts have been examined. Alternatively, force-set via dev `Shift+P`.

**State machine:**
```
normal ──[all messages read + all gifts seen]──► post-complete (permanent)
```
Post-complete state persists in IndexedDB under `kPostComplete(bundle_id)`.

**Visual signature (post-complete):**
- Red rose `(@)` / `@@@` appears at garden center (SpecialLayer)
- Ambient perch-bird (`v`) at top of rose disappears if bonded animal is at tier 3
- Bonded tier-3 animal relocates to perch position near rose (planned — currently static at home)

**User flow (post-completion):**
```
[After reading a letter] → check: all read? all gifts seen?
    → if yes: set postComplete=true, persist, garden.setPostComplete(true)
    → SpecialLayer renders rose + conditionally hides perch bird
    → if animal tier=3: animal moves to perch (planned)
```

---

#### 7.7.7 State composition table

At any moment the garden is described by a tuple: `(season, timeOfDay, animalTier, postComplete)`. Weather and gift states are deterministic from season and bundle state respectively and do not need to be tracked separately in this table.

Key intersections:

| Season | Time | Animal | Post? | What the garden looks like |
|--------|------|--------|-------|---------------------------|
| summer | evening | tier 2 | no | Full foliage, warm sky, fireflies, bonded rabbit at home |
| winter | night | tier 3 | yes | Snow, stars, moon, rose at center, bonded animal at perch |
| autumn | day | tier 0 | no | Warm leaves falling, rain, stranger rabbit peeking from right |
| spring | day | absent | no | Flowers, light rain, butterflies — no animal |
| any | any | any | yes | Rose always visible at garden center |

**Dimension independence:** Season changes do not affect animal tier. Time-of-day changes do not affect post-complete. Feeding the animal does not trigger weather changes. Each dimension is fully orthogonal except:
- Post-complete + tier-3 animal: animal position overrides home (moves to perch)
- Evening + summer: fireflies activate (both dimensions must be true simultaneously)
- Night + any: ambient birds cease (night gates birds off entirely)

---

#### 7.7.8 Planned: bird visual redesign

Current ambient bird (`v`/`~` single char) is visually underdeveloped. New design:
- **Distant bird:** `v` (single char, fast traversal, altitude rows 1–3)
- **Mid-range bird:** `>-` or `-<` depending on direction (2 chars, medium speed, rows 3–6)
- **Close bird:** 3-char two-frame cycle: `>o<`/`>O<` (slow, rows 4–8, rare)
- Frame cycle every 8 ticks; direction randomized at spawn
- Occasional 2–3 bird flocks: stagger spawn position and speed slightly
- Distinct from letter-bird (multi-line, carries envelope, event-driven)

---

## 8. LLM Integration

### 8.1 Provider and data privacy

**Default: Offline mode.** The bundled static question bank (~500 questions, categorized) is the primary question engine. It works without internet, without an API key, and without sending any data to a third party. The offline bank is a first-class experience — not a fallback.

**Optional: Claude API (`claude-sonnet-4-6`)** for contextual, adaptive questions. Requires `ANTHROPIC_API_KEY` in environment.

**Data handling disclosure:** When the LLM is active, the app transmits the author's name, recipient's name, relationship details, shared memories, and all Q&A answers to the Anthropic API. On first LLM-mode launch, the app shows:

> *"LLM mode sends your conversation to Anthropic's servers for question generation. Anthropic's API does not retain data from API calls for training by default. If you prefer to keep everything on your device, press `o` to switch to offline mode."*

The author can toggle between LLM and offline mode at any time during a session.

**API key guidance:** Store the key via OS keychain or a secrets manager rather than shell RC files. Do not place `.env` files in the project directory.

### 8.2 Prompt structure

```
System:
  You are a compassionate interview guide helping someone who is terminally ill compose 
  meaningful messages for their loved ones. Your role is to ask one thoughtful question 
  at a time — warm, specific, never clinical. The author is [Robert], writing to 
  [Maya, his daughter]. This message is for [her 30th birthday].
  
  Shared context: [dogs, hiking, her laugh, June birthdays, their trip to Vermont].
  
  Questions already asked (do not repeat or rephrase):
  [list of prior question text]
  
  Ask one question only. No preamble. No "Great answer!" responses.

User:
  [Author's previous answer, or "BEGIN" for first question]
```

### 8.3 Message synthesis

After Q&A session ends, a separate synthesis call:

```
System:
  You are a ghostwriter helping [Robert] write a heartfelt letter to [Maya] for her 
  30th birthday. Use only the material in the answers below — do not invent details.
  Write in a voice that matches the tone and rhythm of [Robert]'s own answers below.
  Output only the letter body. No subject line. No "Dear Maya" — the author will add salutation.

User:
  [Numbered list of Q&A pairs from the session]
```

The voice instruction derives from the author's actual Q&A answers — no voice descriptor is hardcoded or collected at intake. The LLM infers tone from the author's writing.

LLM synthesis is **assistive only**. A synthesized draft is never encrypted or exported automatically; the author must review it in the draft editor, make any desired changes, and explicitly confirm encryption.

### 8.4 Draft editor

The draft is presented in a **minimal curses editor** within the app by default:
- Arrow keys to navigate. Standard text editing (backspace, delete, enter for newlines).
- `Ctrl+S` to save and return to the message list.
- `Ctrl+X` to discard the draft and return (with confirmation: *"Discard this draft? [y/N]"*).
- After save, a lock confirmation: *"Encrypt this message? Once encrypted, it cannot be edited. [y/N]"*

If the environment variable `LATELETTER_EDITOR` is set, or if `--accessible` mode is active, the draft is written to a managed file inside `~/.lateletter/author/drafts/` (mode `0600`) and opened in that editor instead. On editor exit, the draft is read back into the app. The app does **not** use world-readable system temp directories for plaintext drafts. Any swap/backup files created by the external editor are outside the app's control, so the app warns about this before first use and recommends disabling editor backup artifacts when possible.

---

## 9. Local Storage

Author and recipient state are stored in separate directories to prevent cross-contamination (relevant when the same machine is used for both roles).

### 9.1 Author storage (`~/.lateletter/author/`)

```
~/.lateletter/author/
  session.json          # intake context + in-progress Q&A state
  questions_asked.json  # per-recipient hash+text log for question dedup
  selector_state.json   # optional local scoring/coverage cache for offline question selection
  drafts/
    <uuid>.txt          # unencrypted draft before encryption
```

**`session.json` schema (v1):**

```json
{
  "schema_version": 1,
  "author_name": "Robert",
  "relationship": "Father",
  "recipient_name": "Maya",
  "recipient_relationship": "Daughter",
  "key_dates": [
    { "label": "Maya's birthday", "date": "June 15" }
  ],
  "memory_tags": ["dogs", "hiking", "her laugh"],
  "steward_name": "Sarah Chen",
  "passphrase_hint": "What we called our first dog",
  "consent": {
    "release_unfinished": false,
    "default_release_date": null,
    "allow_steward_access": true
  },
  "messages": {
    "<uuid>": {
      "label": "Maya's 30th birthday",
      "date": "2027-06-15",
      "status": "pending | written | encrypted",
      "qa_exchange_target": 10,
      "qa_exchange_count": 4,
      "qa_draft_count": 2,
      "qa_complete": false,
      "qa_answers": [
        { "question_id": "u-001", "question": "...", "answer": "..." }
      ],
      "qa_answers_draft": [
        { "question_id": "u-005", "question": "...", "answer": "..." }
      ]
    }
  }
}
```

Field notes:
- `key_dates[].date` is free text (author's own format — no ISO 8601 enforcement).
- `consent` stores choices from the §5.1 consent/wishes form. `default_release_date` is ISO 8601 or null.
- `messages` is keyed by UUID. `status` is `"pending"` (slot created), `"written"` (draft finalized), or `"encrypted"` (sealed into bundle).
- `qa_answers` contains finalized Q&A pairs (merged on session completion). `qa_answers_draft` contains in-progress pairs from the active session. On session completion (`qa_complete: true`), draft is merged into `qa_answers` and `qa_answers_draft` is cleared. This split provides crash safety — an interrupted session preserves the last complete save without losing the prior finalized state.
- The **passphrase is never written to this file** (held in memory only). Fields named `passphrase`, `passphrase_confirm`, `key`, `secret`, or `password` are blocked from storage.
- **Compaction (§5.4):** On "Delete completed drafts," these fields survive: `schema_version`, `author_name`, `relationship`, `recipient_name`, `recipient_relationship`, `key_dates`, `memory_tags`, `steward_name`, `passphrase_hint`, `consent`, and any message entry with `status != "encrypted"`. For encrypted messages, the entire message sub-object is removed. `qa_exchange_target`/`qa_exchange_count`/`qa_draft_count` survive only for non-encrypted messages.

**`questions_asked.json` schema:**

```json
{
  "questions": [
    {
      "question_id": "u-001",
      "question_hash": "sha256-hex-prefix",
      "question_text": "How would you describe yourself...",
      "asked_at": "2026-04-18T14:30:00Z",
      "message_id": "<uuid>"
    }
  ]
}
```

This is the dedup log — one entry per question asked across all sessions. `message_id` tracks which message the question was asked for. The file is flat (not per-recipient) because v1 supports only one recipient per bundle.

**`receipts.json` schema (recipient-side, §9.2):**

```json
{
  "<bundle_id>": {
    "<message_id>": {
      "read_at": "2027-06-15T19:42:00Z"
    }
  }
}
```

Keyed by `bundle_id` then `message_id`. `read_at` records when the message was first opened. The bird does not reappear for messages present in this file.

**Security model:**
- `session.json` contains names, relationships, key dates, memory tags, and all Q&A answers — the most sensitive data in the system. The **passphrase is never written to this file** (held in memory only).
- `questions_asked.json` stores the local asked-question history and minimal metadata needed for dedup and pacing.
- `selector_state.json` is optional and disposable. If used, it stores only local runtime state such as domain coverage, personalization scores, and skipped-question markers. It must never contain the passphrase or become the sole source of truth for authored content.
- `drafts/*.txt` contain unencrypted message bodies before encryption.
- **Default lifecycle:** Finalized drafts are deleted (overwrite with random bytes, then unlink) after export (§5.4). `session.json` is retained for re-entry; Q&A answer content is removed for already-encrypted messages, while unfinished-message notes remain until the author explicitly wipes them or finishes those messages. `questions_asked.json` is retained for dedup across sessions.
- `selector_state.json`, if present, may be deleted and rebuilt from `session.json` plus `questions_asked.json`; losing it is recoverable and must not destroy authored progress.
- **Write durability:** `session.json`, `questions_asked.json`, `selector_state.json`, and bundle rewrites use temp-file + `fsync` + atomic rename semantics when the filesystem supports it. The app must never intentionally leave a truncated canonical file in place after a failed write.
- `--wipe-session` flag: Deletes all author storage including session.json.
- The app warns on launch if unencrypted drafts exist from a prior session.

**Filesystem caveat:** On SSDs with wear-leveling and copy-on-write filesystems (APFS on macOS, btrfs on Linux), overwrite-then-delete is best-effort — previous data may persist in unmapped blocks or filesystem snapshots. Full-disk encryption (FileVault, LUKS) is the only reliable mitigation and is outside the app's control. The app's deletion provides protection against casual inspection but not forensic recovery.

**File permissions:** `~/.lateletter/` and all subdirectories are created with mode `0700`. All files within are created with mode `0600`. These permissions are enforced at creation time and verified on launch.

### 9.2 Recipient storage (`~/.lateletter/recipient/`)

```
~/.lateletter/recipient/
  receipts.json         # read-receipt tracking keyed by bundle_id
  garden_state.json     # progression state: visits, animals, discovered items
```

- `receipts.json` stores message IDs that have been read, keyed by `bundle_id`. Machine-local — reading on a different computer will re-trigger birds for previously read messages. This is an acceptable tradeoff (and may be emotionally meaningful rather than a bug).
- `garden_state.json` stores progression state per bundle: `total_visits`, `last_visit`, `discovered_items`, `animals` (trust tiers, last fed), `recipient_plants`. See §6.8.7 for full schema. Both files use temp-file + fsync + atomic rename writes and mode `0600` permissions.

---

## 10. Phases and Milestones

Phases are ordered by the **irreplaceable capability first** principle: the author is terminally ill and time is the scarcest resource. The garden already exists and works — authoring, encryption, and delivery are the product's reason to exist.

Every research-heavy phase begins with a short **research sub-phase** whose deliverable is a written decision memo, concrete acceptance criteria, and testable examples before implementation starts.

Phase numbering reflects **implementation priority and critical path**, not "what could be researched first." Small discovery spikes may happen ahead of their implementation phase, but the canonical order remains: authoring first, recipient delivery second, sealing/security third, optional LLM work fourth, and visual garden expansion after the core letter workflow is trustworthy.

ASCII animation and motion language are therefore **not** one of the first few implementation phases. They can be prototyped earlier for taste and feasibility, but they stay in the later garden-expansion phase because they are not on the path to getting letters authored, sealed, and delivered safely.

### Phase 1 — Author mode (core experience)
- **Research sub-phase (question bank and interview design) — research pass completed 2026-04-18:**
  - **Validated framework anchors:** Five evidence-backed sources ground the offline question bank design:
    - *Dignity Therapy* (Chochinov, *JCO* 2005; *Dignity Therapy: Final Words for Final Days*, OUP 2012; *Lancet Oncology* RCT 2011): the primary empirical anchor. A 9-prompt structured life-review interview for terminally ill patients produces a "generativity document" — a legacy narrative for loved ones. Lancet RCT (n=441): 91% of participants found it satisfying; 86% reported increased sense of purpose; 76% of family members rated the document as important after the patient's death. The validated question protocol and Chochinov's "Dignity-Conserving Repertoire" model directly inform category structure and framing rules.
    - *Ethical will / tzavaah tradition* (Riemer & Stampfer, *Ethical Wills: A Modern Jewish Treasury*, 1983; Baines, *Ethical Wills: Putting Your Values on Paper*, Da Capo 2002): the historical closest analog to LateLetter's purpose — transmission of values, blessings, direct address to named recipients, apology, and love declarations. Provides content domains that clinical frameworks underweight: family lineage, explicit blessings, direct love statements.
    - *Ariadne Labs Serious Illness Conversation Guide* (Bernacki et al., *JAMA Internal Medicine* 2014; Paladino et al., *JAMA Oncology* 2019; cluster-RCT at DFCI/BWH): the best structural sequencing model for question ordering — values before logistics, emotion acknowledgment before cognitive content, strength-naming as counterweight after fear prompts.
    - *The Conversation Project Starter Kit* (IHI; free download — verify current URL at theconversationproject.org): accessibility and framing model — normalizing language, explicit permission-giving, values-first ordering, ~8th-grade reading level, no clinical terminology. Validated across multiple languages.
    - *VitalTalk / CAPC communication training* (Back, Arnold, Tulsky et al., multiple publications 2003–2015): eight editorial principles from clinician communication training, transferable to self-directed question design: avoid "why" framings; ask one question at a time; preserve agency; normalize incomplete answers; acknowledge emotion before cognitive content; avoid binary choices; name stakes simply without dramatizing; match question weight to where the writer is.
  - **Category structure (16 domains, synthesized across all five frameworks):** The offline question bank covers all of the following. Questions per domain are not evenly weighted; life story, values, and direct-address categories receive the most questions. The §5.3 runtime category list and the editorial domain list are reconciled during the decision-memo review pass before implementation.
    1. Life story and significant moments
    2. Roles and identities carried through life
    3. Accomplishments and what the author is proud of
    4. Values and guiding principles
    5. Lessons learned and life wisdom
    6. Gratitude and acknowledgment of people who shaped them
    7. Love declarations and direct address to the recipient
    8. Blessings for the recipient's future
    9. Hopes and dreams for loved ones
    10. Instructions and practical guidance
    11. Fears and what gives the author strength
    12. What matters most / core priorities
    13. Apologies and repair [optional; high-intensity; opt-in gated — not shown by default]
    14. Family history and lineage
    15. Spiritual and existential meaning [optional; belief-system-neutral framing required — cannot assume any faith tradition]
    16. Practical wishes and closing
  - **Editorial principles (from research synthesis, complementing §5.3):**
    - All prompts are open-ended; binary and closed framings are excluded.
    - "Why" questions are excluded — prefer "what" and "how" framings.
    - No question may presuppose a specific family structure, belief system, or relationship type.
    - Each question is one sentence only; compound questions are split into separate prompts.
    - Each question is tagged with domain, intensity level (1 = easy/positive, 2 = reflective, 3 = heavy: grief, apology, fear), and exclusion triggers.
    - High-intensity questions (level 3) are gated: appear only after at least one lower-intensity pass per session, or on explicit author opt-in.
    - No question telegraphs the "right" answer or implies a specific response is more enlightened or more loving.
    - Permission-giving language accompanies every section transition: the author may skip any question and return later.
    - Clinical and medical framing (illness, diagnosis, prognosis, treatment) is excluded from all prompts.
  - **Research deliverable:** A written decision memo produced before bank construction begins, containing: category structure finalized, intensity tier definitions, 10–15 sample questions per domain (with domain/intensity tags and exclusion notes), and 10–15 rejection examples covering each exclusion criterion. The memo undergoes the §5.3 two-human editorial review before implementation.
  - **Question-system design outcome required before implementation:** The research memo must also freeze the offline selector contract: universal base-set size, required metadata per question, gating rules, session steering controls, and what personalization signals may be used without making the experience feel algorithmically erratic.
  - **Study materials** (for question-bank designers and editorial reviewers; all prices approximate and unverified in-session — check current availability before purchasing):
    - *Free first:*
      - The Conversation Project Starter Kit — free PDF (theconversationproject.org — verify URL). Foundational framing and permission-giving model; plain-language question examples across values, medical preferences, and practical wishes.
      - Five Wishes (agingwithdignity.org / fivewishes.org — verify URL): the most widely used US plain-language advance directive; its five question domains map directly to LateLetter categories. Digital completion tool: free; print copy: ~$5 approximate (verify current price).
    - *Borrow/read first (wide public library availability via Libby/OverDrive):*
      - Gawande, *Being Mortal* (2014) — essential clinical narrative on what dying patients actually want; foundational framing for "what matters most" question design.
      - Callanan & Kelley, *Final Gifts* (1992) — hospice nurses documenting the symbolic and indirect communication of dying patients; directly informs prompt design for non-literal expression.
      - Mannix, *With the End in Mind* (2017) — palliative care vignettes; models how to elicit and honor dying people's own words. Library coverage moderate in US, wide in UK.
      - Butler, *The Art of Dying Well* (2019) — practical patient-centered preparation guide; models advance-planning conversation questions.
    - *Buy or access via academic/interlibrary loan:*
      - Chochinov, *Dignity Therapy: Final Words for Final Days* (OUP 2012, ~$35–55 approximate — verify current price): the canonical text for the primary empirical framework; public library copies sparse. The JCO 2005 paper (Chochinov et al., *Journal of Clinical Oncology* 23:24) includes the full validated question protocol — verify open-access status before purchase.
      - Baines, *Ethical Wills: Putting Your Values on Paper* (Da Capo 2002, used copies ~$5–15 approximate — verify current print status): closest secular analog to LateLetter's output format; verify whether a newer edition exists.
      - Riemer & Stampfer (eds.), *Ethical Wills: A Modern Jewish Treasury* (Schocken Books 1983) — the scholarly source for the ethical will tradition; available via library or ILL.
- Refactor `garden.py` into modular structure: separate renderer, state manager, CLI parser
- Create `pyproject.toml` with dependencies
- Consent and wishes form (living will-inspired — §5.1)
- TUI intake form (curses) with validation, steward field, passphrase hint
- Temporary reviewed seed bank file for the first offline vertical slice (`data/question_bank_seed.v0.json`) using the canonical question-entry shape where practical
- Offline question selector: universal base set + personalization layer + pacing/gating rules
- Reviewed question bank (80–120 questions covering all 16 domains, categorized, versioned, shipped read-only in app resources) — the primary question engine. The 500+ bank target is a post-v1 content milestone; 80–120 well-reviewed questions fully serve a 10-exchange session and the existing selector infrastructure.
- Q&A session loop (offline — questions drawn from the selector/bank system) with session resumption
- Minimal curses draft editor (§8.4)
- Local session storage with secure lifecycle (§9)
- Author incapacitation design (§5.6)
- Accessibility: `--accessible` line-mode author flow, paste-first dictation support, and external-editor path (§12a)

### Phase 2 — Recipient mode (delivery)
- `.lateletter` bundle loader and recipient UI against the canonical bundle schema (development fixtures may stub ciphertext before Phase 3, but the on-disk schema does not reintroduce plaintext labels)
- Bundle file loading, date detection, read-receipt tracking
- Letter-bird animation (distinct from ambient bird)
- Multi-message selection overlay
- Message display with scroll support and print option
- Structural corruption detection for locked bundles and development fixtures (checksum-based)
- Bundle reopen flow for author (§5.5)

### Phase 3 — Encryption and sealing
- **Research sub-phase (security and standard industry practices):**
- Evaluate `age` vs custom Argon2id+AES-GCM (see §4 "Encryption primitive options") — benchmark KDF timing on target hardware, validate Python/JS parity path, write decision memo
- Review standard industry practices for local encrypted archives, passphrase-based key derivation, authenticated metadata, passphrase caching, and secure-deletion caveats
- Confirm chosen primitive's parameters, bundle-HMAC derivation, plaintext metadata boundaries, and recipient/authentication UX against that research
- Produce implementation notes and negative test cases for tampering, wrong-passphrase handling, bundle updates, and data-lifecycle edge cases
- Chosen crypto primitive encryption module with round-trip integration tests
- Passphrase setup, per-session caching, wrong-passphrase states
- Label encryption (moved inside ciphertext)
- HMAC integrity (passphrase-keyed, verified post-entry)
- Incremental export with checksum + HMAC recomputation
- Session wipe flow
- Sealed state: once exported with encryption, the bundle is tamper-evident

### Phase 4 — LLM question engine
- **Research sub-phase (LLM prompt and evaluation design):**
- Review standard industry practices for privacy disclosures, prompt structure, evaluation, refusal handling, and quality control for emotionally sensitive writing tools
- Define acceptance criteria for adaptive questioning, synthesis quality, hallucination avoidance, and author-editability before API integration begins
- Create a small evaluation set of representative prompts, answers, and expected failure cases for regression testing
- Claude API integration with data privacy disclosure
- Contextual question generation with dedup
- Message synthesis (letter drafting) with voice derived from Q&A
- Seamless toggle between LLM and offline mode

### Phase 5 — Garden animation system
- **Research sub-phase (ASCII animation and motion language) — first pass done 2026-04-18, more animations needed later:**
  - ~~Prototype ASCII animation patterns for the ambient bird, letter-bird, butterfly, rain, snow, clouds, and seasonal effects~~ ✓ — prototypes in `ascii-animations/`, all approved
  - ~~Research terminal-animation constraints: redraw budgets, layering, flicker avoidance, glyph readability, color usage~~ ✓ — documented in `ANIMATION-RESEARCH.txt`
  - Produce a motion/style sheet with timing targets and procedural generation specs (partially captured in §7.2–7.3)
  - Second research pass (after integration): prototype additional animations (new plant types, bonus creatures, bloom/growth, wind interactions) once the core set is integrated and the rendering architecture is proven
- **Integration phase — core set done 2026-04-19:**
  - ~~Integrate approved prototype animations into the garden renderer using the 5-layer compositing model (§7.2)~~ ✓ — `src/lateletter/garden/` package (10 modules)
  - ~~Implement the shared particle API for rain, snow, leaves, splashes, firefly flashes~~ ✓ — `particles.py` with per-type physics dispatch and collision
  - ~~Implement plant collision surfaces for snow accumulation and rain splashes~~ ✓ — collision map, top surfaces, canopy cells registered at placement
  - Build procedural plant generators for new types: willow, cactus, bamboo, lily, sunflower (tall), dead tree (§7.1)
  - ~~Build procedural creature spawners for butterfly, ambient bird, fireflies with seed-based variety (§7.1)~~ ✓ — `creatures.py` with Photinus flash patterns, butterfly up-dip, bird flap
  - ~~Implement season detection + seasonal weights, colors, and animation activation (§7.4)~~ ✓ — `seasons.py` with system-date detection
  - ~~Implement rain and snow weather systems with procedural density and wind parameters~~ ✓ — rain with gravity+splashes, snow with drift+accumulation
  - ~~Implement cloud generation and drift~~ ✓ — procedural cloud shapes drifting left
  - ~~Lightning system (probabilistic spawn during rain)~~ ✓ — jagged bolt walk with fork, char aging #→+→*, screen flash
- **Additional animations (after core integration):**
  - Design and prototype new animation types not yet covered (cat, snail, bee — approved as bonus from research)
  - Plan procedural methods for each: spawn rules, movement AI, interaction with environment
  - Wind system: global sine-wave affecting plant sway, particle drift, creature flight
  - Bloom/growth animations for flowers (frames exist in research)
  - Time-of-day transitions (§7.5): dusk palette shift, night mode, moon glyph

### Phase 6 — Packaging, hardening, and ship

Expanded detail for all ship-blocking work lives in §24 steps 12–15. Summary:

- Recipient experience design: first-run flow, daily ambient experience, post-completion behavior (§24 step 7)
- macOS `.app` packaging: bundled runtime, code signing, notarization, `.lateletter` file association, Dock/app icon (§24 step 13)
- Failure-mode and security validation passes (§24 step 12)
- Accessibility end-to-end verification and braille display audit (§24 step 14)
- `--wipe-session` CLI flag for non-interactive secure deletion
- Release acceptance matrix (§18, §19) — ship only after all criteria pass

**Non-ship-blocking polish** (may ship with v1 or after):
- Time-of-day palette (day/dusk/night)
- Expanded plant types, additional creatures, bloom animations
- Wind system upgrade (Perlin-noise gusts)

---

## 11. Non-Goals (v1)

- No server, no cloud sync, no accounts. (The browser viewer and email notification script are local/self-hosted — no LateLetter-operated server.)
- No native mobile app (the browser viewer covers mobile browsers).
- No true cryptographic time-lock (app-enforced date is sufficient for v1).
- No video or audio attachments.
- No multi-recipient bundles (one `.lateletter` file = one recipient).
- No managed/hosted email notification service (v1 ships a self-hosted script only — see §13.3).

## 12a. Accessibility (required, not optional)

The primary author may be terminally ill with limited mobility, vision impairment, or fatigue. Accessibility is a core requirement:

- **Voice-to-text input:** Author mode must support dictation for Q&A answers and draft editing. On macOS, leverage system dictation (Fn-Fn). On other platforms, integrate with OS accessibility services. The app must always accept pasted text from external dictation tools at minimum.
- **Screen reader compatibility:** Every author task must have a screen-reader-safe path. Because full-screen curses is unreliable with VoiceOver (macOS) and similar tools, the app must ship a plain line-oriented `--accessible` mode and support external-editor drafting. Avoid visual-only indicators; use text labels for all states.
- **Braille display support:** The `--accessible` path should emit ordinary terminal output compatible with braille display hardware. Curses is optional in the accessibility path, not a requirement.
- **Fatigue-aware UX:** All progress is auto-saved. The author can stop at any point and resume (§5.3 session resumption). No time pressure anywhere in the interface.

## 13. Delivery Channels

The `.lateletter` file is the single source of truth. It reaches the recipient through three channels, all shipping in v1. Each channel delivers the same letters with the same passphrase — they differ only in how the garden renders and how the recipient discovers that a letter is waiting.

### 13.1 macOS app (primary)

A signed and notarized `LateLetter.app` with a bundled Python runtime. The recipient double-clicks the app or a `.lateletter` file. The garden renders as an animated curses TUI in a terminal window managed by the app. This is the premium experience — full particle effects, real-time weather, creature AI, and the living garden described in §7.

This channel requires macOS 14+. See §15 for packaging details.

### 13.2 Browser viewer (cross-platform)

A self-contained `viewer-bnw.html` file that runs in any modern browser. No server, no account, no installation. The recipient opens it, drops or selects their `.lateletter` file, enters the passphrase, and reads their letters. Decryption happens entirely client-side.

**Scope (updated 2026-04-20):** The original plan was a letter reader with static garden illustration. The live 5-layer animated garden (§7.2) was ported to JS ahead of schedule and is now the browser viewer's backdrop — DOM text rendering (not canvas), full particle physics, seasonal weather, and creature layer. The rendering architecture below reflects what was built.

**Rendering architecture — pure HTML/CSS/JS + pretext:**

The browser viewer is built on **four rendering layers**:

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Letter text | **pretext** (`@chenglou/pretext@0.0.4`) + DOM | Responsive proportional line breaking; `prepareWithSegments` + `layoutWithLines`; renders to standard DOM elements. Selectable, printable, accessible. |
| Garden | **DOM text renderer (GardenDOM)** | 5-layer composited garden (background, plants, particles, creatures, special) rendered as `<div>` rows of `<span style="color:...">` elements. Scales with browser zoom without blur. ~20 FPS via `requestAnimationFrame`. Full parity with TUI: rain gravity+wind, snow accumulation, leaf detachment, butterflies, birds, fireflies. |
| UI chrome | **Pure HTML/CSS** | Passphrase overlay, inbox, navigation, status — standard web forms. No framework. All screens are translucent scrims over the live garden. |
| Crypto | **WebCrypto (main thread, async)** — PBKDF2-SHA256 + AES-256-GCM | **v0 sealed path shipped 2026-07-19:** bundles whose messages carry `kdf_params: {name: "PBKDF2", hash: "SHA-256", iterations: 600000}` are verified (bundle HMAC gate first, per §4) and decrypted natively in the browser with zero dependencies. Python parity in `src/lateletter/sealed.py`; authoring via `make_letter.py`. Argon2id (`kdf_params: null`) remains the Phase 3 decision — it requires a WASM port and is not yet openable in the viewer. Dev fixtures (empty `hmac`) keep the base64 passthrough in a Web Worker. |

**Why DOM (not canvas):** Canvas is invisible to screen readers and produces blurry output on browser zoom. DOM text renders at native resolution at any zoom level, is selectable, printable, and fully accessible. The garden uses fixed-width Courier New; the UI and letter text use Times New Roman — they coexist in the same page without conflict.

**Why pretext for letter bodies:** Letter text needs proportional line breaking across devices without layout thrashing. pretext separates text measurement from layout; rendering is standard DOM. Garden grid uses fixed-width monospace and does not need pretext.

**Why not WASM for the garden:** The 64 MiB KDF OOM risk on mobile devices (§17) already pushes the limit of acceptable WASM usage. A compiled garden renderer would add binary size, memory pressure, and device compatibility risk — DOM text rendering achieves full parity without WASM.

**Viewer contents:**
- File input via drag-and-drop or `<input type="file">` for the `.lateletter` bundle.
- Argon2id in a Web Worker with progress indicator ("Unlocking…" with elapsed time). On devices with `navigator.deviceMemory < 2`, warn before attempting derivation. If derivation exceeds 30 seconds, show a timeout message with guidance.
- Per-session passphrase and per-message key caching (in-memory JS variables, cleared on page close).
- Read receipts via `IndexedDB` (fallback to `localStorage`), keyed by a `lateletter_v1_` namespace prefix plus `bundle_id` and message ID. Receipt state is per-browser/per-device. Clearing browser storage causes already-read messages to reappear; this is disclosed in the viewer UX.
- If browser storage is unavailable, the viewer runs statelessly and warns.
- The full recipient flow: first-run welcome (§6.5, adapted for browser — see below), letter reading with scroll, letter archive (§6.6), post-completion state (§6.7), save-to-text.

**Browser first-run adaptation (TODO 10d):** The "garden appears first" beat from §6.5 adapts for the browser context:
1. The viewer shows a warm welcome screen with a file-drop zone over the live animated garden: *"This is LateLetter. Drop your `.lateletter` file here."*
2. After the file is loaded, the garden seeds to `bundle.garden_seed` and runs. HUD shows: *"planted for you by [author_name]."*
3. A gentle delay (3s, per §6.5) lets the garden settle before the first prompt appears.
4. Button: *"open letters"* — leads to passphrase entry, then letter flow as §6.4.

**Progression layer in the browser viewer:**

The browser viewer supports the full progression layer alongside the live garden:

- **Item discovery:** Triggered items (date, cumulative-visit, post-letter) appear in the **Memories section** of the inbox — discovered items listed as `inbox-mem-btn`; undiscovered items are hidden until triggered. Clicking reveals the sentiment as a modal overlay. Discovery state persists in IndexedDB.
- **Post-letter triggers:** After a letter is read, any newly triggered items surface immediately in the archive.
- **Archive / inbox layout:** Transparent inbox floats over the live garden — read items at `.28` opacity, unread at `1.0`, locked at `.12`. No symbols. Memories section appears below letters when any item is discovered.
- **Animal relationships:** Animal ASCII art (`_ANIMAL_ART` — cat/bird/rabbit/turtle, 4 trust tiers) rendered in `CreatureLayer`. The bundle's assigned animal appears at the appropriate trust tier; `f` key feeds (authenticated, triggered, tier < 3); bonded animals (tier 3) suppress the generic perch bird in `SpecialLayer`. IndexedDB tracks trust + last-visit per bundle. In dev fixture, `Shift+A` cycles all 16 states (4 animals × 4 tiers) and auto-injects a cat at tier 0 if no animal gift is present in the bundle.

**Dev fixture mode (isDevFixture — bundle has no HMAC):**

Dev fixture unlocks a set of secret keybindings for QA and design review. These are only active when the loaded file has no HMAC (base64 plaintext passthrough — the dev-fixture format). Production bundles never activate these.

| Keybinding | Action | Status |
|---|---|---|
| `Shift+A` | Cycle animal: advances through all 16 states (4 animals × 4 tiers). Auto-injects a cat at tier 0 if no animal gift in bundle. | Implemented |
| `,` / `.` | Cycle season + time-of-day: spring → spring-night → summer → summer-night → autumn → autumn-night → winter → winter-night. Calls `garden._reset()`. | Implemented |
| `Shift+B` | Cycle color/background mode: default → white-bg → full-grayscale → B&W+anim → default. | Implemented |
| `Shift+D` | Dump state object to console: season, CW/CH, cols×rows, visitCount, animal, gifts, postComplete, dueIdxs, colorMode. | Implemented |
| `Shift+G` | Toggle grid overlay: shows cols×rows, CW/CH, mouse position, FPS, and full keybinding list. | Implemented |
| `Shift+F` | Re-trigger first-run banner: resets `_frbDone`, shows "This garden was planted for you…" fade-in again. | Planned |
| `Shift+P` | Toggle post-complete state: shows/hides the completion rose + bonded animal perch position. | Planned |
| `Shift+V` | Simulate a visit: increments `visitCount`, re-evaluates cumulative_visits triggers. | Planned |
| `Shift+I` | Cycle gift item state: hidden → revealed → examined (for each gift in bundle). | Planned |
| `Shift+N` | Cycle time-of-day independently: day → evening → night (for firefly/moon testing without changing season). | Planned |

**Dev overlay (Shift+G):** When active, shows live grid metrics, current state summary, and full keybinding reference in the top-left corner of `#g`. Must persist through `garden._reset()` calls (season/color changes). Grid-line background-image must recompute CW/CH after every reset.

**Dev status header format (top of overlay):**
```
NxM | CW=X.XX CH=Y | mouse(c,r) | FPS:N
season: summer-night  animal: rabbit/2  color: default
```

**What the browser viewer does NOT do:**
- No server communication of any kind.
- No upload of the `.lateletter` file to any remote service.
- No analytics, telemetry, or tracking.

### 13.3 Email notification (delivery prompt)

A lightweight mechanism that emails the recipient when a letter is due. **The email does not contain letter content** — it is a notification only.

**How it works:**
1. During the export flow (§5.4), the author optionally provides a delivery email address for the recipient and configures the notification method.
2. The notification method is one of:
   - **Self-hosted script:** A small standalone script (`notify.py` or similar) that the author, steward, or a trusted person runs via cron or launchd. It reads the `.lateletter` bundle (plaintext metadata only — dates and `bundle_id`), checks today's date against message dates, and sends an email via SMTP (any provider) when a letter becomes due. The script never decrypts letters and never stores the passphrase. The handoff package (§15.1) includes this script.
   - **Managed service (post-v1):** A hosted notification service that the author registers with — uploads only the delivery schedule (dates, no content), and receives email sends on due dates. This is the convenience path but changes the trust model and is NOT required for v1.
3. The email body is simple and warm:

   > *Subject: A letter is waiting for you*
   >
   > *[author_name] left a letter for you.*
   > *Open your LateLetter garden to read it.*
   >
   > *If you need help opening it, ask [steward_name].*

4. The email may include a link to the hosted HTML viewer (post-v1) or remind the recipient to open `viewer-bnw.html` or `LateLetter.app`.

**What email notification does NOT do:**
- Never sends letter content, labels, passphrase hints, or any encrypted data.
- Never requires the recipient to have an account or click a tracking link.
- The self-hosted script is fire-and-forget — it sends and exits. No daemon, no state beyond what's in the `.lateletter` file and a local sent-log to avoid duplicate notifications.

**Privacy note:** The delivery email address and notification preference are stored in the `.lateletter` bundle's plaintext metadata (new field: `notification`). Anyone with the file can see the recipient's email address. This is consistent with the existing privacy model (§3: dates and author name are already plaintext). The author is warned during setup that the email address will be visible in the file.

### 13.4 Channel parity principle

All three channels deliver the same **letter experience** — the letters are the content, the garden is the delivery mechanism:
- Same passphrase, same date-lock logic, same read-receipt semantics (per-device, no sync).
- Same letter archive (§6.6) — read letters can always be re-read.
- Same post-completion acknowledgment (§6.7) — "all letters delivered."
- Same first-run emotional sequence — warmth first, then recognition ("planted for you by [name]"), then passphrase.

Both the macOS app and the browser viewer have the full animated garden — particles, creatures, weather, the living space. The browser viewer gained full garden parity ahead of schedule (DOM text renderer, 5-layer compositor, ~20 FPS). Both channels treat the recipient with the same care. Email notification doesn't render anything — it tells the recipient to go look.

### 13.5 Dev tool fixture — garden QA harness

The dev fixture (a `.lateletter` file with `hmac=""` and base64 plaintext bodies) doubles as the primary garden QA tool. The following design principles govern what dev fixture mode must be able to show:

**Everything a recipient could ever see, exercisable in one session:**

| Feature | How to trigger in dev fixture |
|---|---|
| All 4 seasons | `Shift+S` cycles spring → summer → autumn → winter |
| All seasonal weather | Automatic per season: spring rain, autumn rain+leaves, winter snow, summer calm |
| All 4 animals, all 4 trust tiers | `Shift+A` cycles 16 states; footprints shown at tiers 1–3 when wasAbsent=true |
| Animal delivery animation | Auto-plays at tiers 1–3 (when letter is read with bonded animal) |
| First-run banner | `Shift+F` re-triggers "This garden was planted for you…" |
| Post-complete state | `Shift+P` toggles: rose appears, bonded animal moves to perch position |
| Garden interactions | Click plants (leaf burst), hover (rustle), `f` key (feed animal) |
| Cumulative-visit triggers | `Shift+V` simulates a visit; trigger fires when visitCount threshold met |
| Date triggers | Use a test bundle with dates in the past |
| Post-letter triggers | Read a letter; trigger fires after read receipt saved |
| Memory modal | Appears in archive after trigger fires; click to show sentiment text |
| Archive states | Unread (opacity 1), read (opacity .28), locked (opacity .12) |
| Multi-letter select | Bundle with multiple due letters on same date |

**Dev status overlay (top-right corner, dev fixture only):**
```
[dev] summer · cat/2 · v=3 · post
```
Format: `[dev] {season} · {animal}/{tier} · v={visitCount} · {post if postComplete}`

**Test fixture format (`.lateletter` dev bundle):**
- `hmac: ""` — activates dev fixture mode
- `garden_gifts`: includes one of each gift type (date, cumulative_visits, post_letter, animal)
- `messages`: 3 letters — one past-due (readable), one future (locked), one read (already in receipts)
- `garden_seed`: fixed value for reproducible plant layout

The `test_fixture.lateletter` file in the repo should satisfy all of the above.

### 13.6 Post-v1 delivery extensions

These are NOT in v1 scope but should inform architecture:

- ~~**Animated browser garden:**~~ **[DONE ahead of schedule — 2026-04-20]** DOM text renderer (GardenDOM) built in `viewer-bnw.html`. Full 5-layer compositor, ~20 FPS, scales with browser zoom. Remaining: cursor interaction QA (TODO 10b), animal art port (TODO 10c), first-run flow (TODO 10d).
- **Hosted HTML garden:** A web-hosted version where the recipient visits a URL instead of opening a local file. This requires hosting, accounts, and operational infrastructure. The trust model changes (the server sees the encrypted file) and must be explicitly disclosed.
- **Managed email service:** A hosted notification service that handles cron scheduling, retry, and deliverability so the author/steward doesn't have to run a script. Requires long-lived infrastructure.
- **Mobile app:** A native iOS/Android app for recipients. Possible but not planned — the browser viewer covers mobile browsers.

---

## 14. Open Questions

| Question | Status | Notes |
|----------|--------|-------|
| Should `garden_seed` in the bundle be fixed (deterministic) or change per-day? | Decided: fixed | Fixed seed = always the same garden (personal). §3 describes this as the intended behavior. |
| Should the passphrase be per-file or per-message? | Decided: per-file | Simpler UX; author sets one passphrase for the whole bundle. Cached in memory per-session (§4). |
| What happens if the author dies before finishing all messages? | Decided: §5.6 | Incremental export + steward role. See §5.6 for full design. |
| Should the app support "ongoing" message type (no fixed date, appears after a set # of days)? | Future | Would require a counter stored in the receipt file. Not in v1 UI. |
| Offline mode: should question bank be embedded in the script or a separate data file? | Decided: separate bundled data file | Editorial updates and question review should not require code edits. The app bundle can still ship as a single recipient artifact while containing versioned internal data files. |
| How should the app handle timezone differences between author and recipient? | Decided: v1 accepts ±1 day drift | `date.today()` uses recipient's local system date. Consider storing dates in UTC internally for future web/email portability (§13). |
| What is the recipient software distribution strategy? | Decided: handoff package | v1.0 ships a handoff folder containing the macOS .app, `viewer.html`, the `.lateletter` file, a notification script, and a README. See §15.1. |
| Should there be a maximum message count per bundle? | Decided: soft limit | No hard limit. Warn author above 100 messages (absurdly large threshold). |
| How should externally-edited files be handled? | Decided: drafts-only, never canonical | External editing is allowed only for unsealed drafts under `~/.lateletter/author/drafts/`. The encrypted `.lateletter` bundle is always the canonical artifact. External editor swap/backup files are warned about but not managed by the app. |
| What are the platform requirements? | Decided: macOS app + cross-platform browser viewer | v1.0 ships the macOS .app as the primary channel and a self-contained `viewer.html` as the cross-platform channel. The browser viewer ensures recipients on Windows, Linux, and mobile can read letters. See §13. |
| LLM synthesis quality gate? | Decided: non-ship-blocking and human-reviewed | v1.0 can ship without LLM mode. If enabled, every LLM-generated draft must be manually reviewed and explicitly confirmed by the author before encryption/export. |

## 15. Release Profile

**Canonical v1.0 ship target:** macOS app + cross-platform browser viewer + self-hosted email notification.

- The **macOS app** is a signed and notarized `LateLetter.app` with a bundled Python runtime and bundled question-bank data.
- The **browser viewer** is a self-contained `viewer.html` (single file, no dependencies) that opens `.lateletter` bundles in any modern browser with client-side decryption.
- The **email notification script** is a standalone `notify.py` that the author/steward runs via cron to send due-date email prompts.
- The recipient is not expected to install Python, use `pip`, edit shell config, or invoke CLI commands manually.
- Author mode runs on macOS (primary) and Linux (development target, not release-blocking). Windows author support is out of scope for v1.0.

### 15.1 Handoff package

The export flow (§5.4) produces a **handoff folder** — this is what the author gives to the recipient or leaves for the steward to deliver:

```
LateLetter-for-Maya/
  LateLetter.app              macOS garden app (if author is on macOS)
  viewer.html                 browser viewer (works on any platform)
  maya.lateletter             the encrypted letter bundle
  notify.py                   email notification script (optional)
  README.txt                  plain-text instructions for the recipient
```

**`README.txt` contents (auto-generated from intake data):**

```
This folder contains letters from [author_name] for [recipient_name].

To read them:
  • On a Mac: Open LateLetter.app, then open maya.lateletter
  • On any computer: Open viewer.html in your browser

You will need the passphrase that [author_name] set.
The app will show you a hint when you enter the passphrase.

If you need help, contact [steward_name].
```

The README is plaintext, not encrypted. It deliberately does **not** include the passphrase hint — the hint is shown within the app/viewer at unlock time, not in a plaintext file that could be found by anyone with physical access to the handoff package. The steward line appears only if a steward was designated during intake.

The author can customize the handoff folder path during export. The folder is created via temp-dir + atomic rename, same as the bundle itself.

### 15.2 Release requirements

**Required for v1.0 release:**

- Offline author mode with a reviewed static question bank
- Recipient unlock/read flow for due messages (macOS app and browser viewer — browser viewer is a letter reader, not animated garden)
- First-run experience (§6.5) in both channels
- Letter archive with re-read (§6.6) in both channels
- Post-completion state (§6.7) in both channels
- Authenticated bundle sealing and tamper handling
- Append-later author flow for adding new messages
- Accessible `--accessible` author path and external-editor path
- Atomic writes for canonical bundle/session data
- Self-hosted email notification script
- Handoff package generation during export

**Explicitly non-ship-blocking for v1.0:**

- Claude/LLM mode
- Direct printer integration beyond saving printable plain text
- Expanded seasonal animation set beyond the minimal garden needed for recipient mode
- Managed/hosted email notification service
- Hosted HTML garden
- Linux author-mode packaging polish

## 16. Versioning and Compatibility

- `version` in the `.lateletter` bundle is the on-disk format major version.
- All v1.x app releases must read bundles with `version: 1`.
- A v1 app may append messages to an existing v1 bundle, but it must not silently rewrite that bundle to a new major format.
- If the app encounters a bundle with an unknown newer major version, it shows an unsupported-version message and refuses write operations.
- Format-breaking changes require a new major `version` and an explicit migration plan; no implicit upgrade-in-place is allowed.
- Question-bank/editorial updates do not change bundle format version unless the on-disk bundle schema changes.

## 17. Failure Modes and Recovery

- **Corrupted bundle (`checksum` fails):** Show the damaged-file warning, suppress unlock/delivery UI, and allow only the standalone garden.
- **Authentication failure (`hmac` fails or wrong passphrase):** Show the generic authentication-failure message, reveal no due-message state, and keep the bundle sealed for that session.
- **Interrupted export or append:** Use temp-file + `fsync` + atomic rename. On failure, keep the previous valid bundle and report that export did not complete.
- **Interrupted session-data write:** Preserve the last valid `session.json`; if recovery data cannot be loaded, show a recovery warning and do not silently discard existing files.
- **Disk full / permission denied:** Show a blocking error naming the affected path and abort the write without deleting the prior canonical file.
- **Terminal too small:** Full-screen interactive TUI screens require at least **80 columns x 24 rows**. Below that threshold, show a resize-required screen or offer/auto-switch to the `--accessible` line-mode flow instead of rendering truncated UI.
- **No printer backend available:** Offer save-to-text-file only; printer absence is not fatal to letter reading.
- **Unsupported terminal features or screen-reader conflict:** Offer or automatically switch to `--accessible` line-mode author flow.
- **Unexpected crash during reading:** No read receipt is written until the message overlay is successfully opened and the message is marked read on clean exit from that read flow.
- **Lost `.lateletter` file:** Irrecoverable — all letters are permanently lost. The export flow (§5.4) warns the author and recommends copies. The handoff README (§15.1) does not address this (avoid alarming the recipient); the backup responsibility is the author's.
- **Browser viewer: Argon2id timeout or OOM:** On constrained devices, the 64MB Argon2id derivation may fail or take >15 seconds. The viewer shows a progress indicator and a timeout message if derivation exceeds 30 seconds. It does not reduce security parameters — the user can retry or use a more capable device.
- **Browser viewer: storage denied or cleared:** Read receipts are lost; previously read messages reappear as new. The viewer warns that read state will not persist. Letters are still readable.

## 18. Release Acceptance Criteria

The product is not shippable until all of the following are true:

- A first-time author can complete intake, write at least one message offline, export a handoff package, reopen later, and append another message without data loss.
- A first-time recipient on a clean macOS machine can open `LateLetter.app`, experience the first-run sequence (§6.5), unlock the bundle, read a due message, re-read it via the archive (§6.6), quit, relaunch, and see the read receipt honored.
- A first-time recipient on a non-macOS machine can open `viewer.html` in a modern browser, complete the same flow (first-run, unlock, read, archive, re-read, receipt), with equivalent emotional pacing.
- After all letters are read, the post-completion state (§6.7) activates correctly in both the macOS app and the browser viewer.
- A tampered bundle, corrupted bundle, and wrong-passphrase attempt all fail safely without false delivery claims — in both channels.
- The secure-default export path deletes finalized plaintext drafts while preserving unfinished notes when the author chooses to keep them.
- The export flow generates a complete handoff package (§15.1) with README, viewer.html, and optional notification script.
- The `--accessible` author path can complete the full author workflow without requiring full-screen curses.
- The macOS release artifact installs and runs on a clean macOS 14+ machine with no developer tooling preinstalled.
- The browser viewer works in current versions of Safari, Chrome, and Firefox without plugins or extensions.
- The self-hosted email notification script sends a due-date email correctly when run via cron.
- The product can read bundles created by prior v1 builds used during the release cycle.

**Audit note (2026-04-27):** These criteria remain open in live code. The current gaps confirmed by source and runtime checks are: (1) the `lateletter --write` path does not yet complete the end-to-end author workflow, (2) the browser viewer does not yet enforce launch-time checksum validation, and (3) `demo_author.py` is not yet valid evidence for the export path because it emits bundles without a computed checksum.

## 19. Test Matrix

Minimum pre-release coverage:

- **Clean-machine recipient test:** Fresh macOS machine, no Python installed, app bundle + `.lateletter` file only.
- **Offline authoring test:** Network disabled, full author flow using only the bundled question bank.
- **Append/update test:** Export a bundle, append later, confirm old receipts still map correctly by `bundle_id`.
- **Corruption/tamper fixtures:** Bad checksum, bad HMAC, truncated file, unknown future version, and altered message date.
- **Accessibility test:** Complete author flow in `--accessible` mode with keyboard-only navigation and pasted dictation text.
- **Terminal constraints test:** Exactly 80x24, below 80x24, no-color/limited-color terminal, and resize while overlay is open.
- **Crash-safety test:** Kill the app during session save and during bundle export; confirm the previous canonical file remains valid.
- **Performance sanity test:** Startup, unlock, and long-letter scrolling remain acceptable with a realistically sized bundle.
- **Browser viewer test:** Open `viewer.html` in Safari, Chrome, and Firefox. Load `.lateletter` file via drag-and-drop. Complete full recipient flow: first-run, passphrase entry, read letter, re-read via archive, verify read receipt persists across page reload.
- **Browser viewer mobile test:** Open `viewer.html` on an iOS and Android browser. Verify layout is usable, passphrase entry works, Argon2id completes within 30 seconds, and letters are readable.
- **Email notification test:** Run `notify.py` with a test bundle containing a due-date message. Verify email is sent, content contains no letter text, and duplicate sends are suppressed on re-run.
- **Handoff package test:** Export a handoff folder and verify it contains all expected files, README is correctly populated from intake data, and `viewer.html` works from the exported folder without modification.

## 20. Security Review Checklist

- Dependency versions for crypto-related packages are pinned and reviewed before release.
- AES-GCM and Argon2id code paths have round-trip tests and negative tests using tampered ciphertext, wrong nonce, wrong salt, and wrong passphrase.
- Bundle-HMAC derivation uses `bundle_auth_salt` exactly as specified and is covered by tests.
- Canonical-file writes use temp-file + `fsync` + atomic rename semantics where supported.
- Plaintext draft paths, permissions, and cleanup behavior are tested on the release platform.
- The app never logs passphrases, decrypted letter bodies, or full sensitive intake/session payloads.
- Read-receipt behavior does not leak future delivery state before authentication.
- Release review includes one manual adversarial pass focused on tampering, stale-draft leakage, and package/install integrity.

## 21. Post-v1 — Hosted Extensions

v1 ships self-contained delivery channels (§13): a local macOS app, a local browser viewer, and a self-hosted email notification script. Post-v1 work explores *hosted* and *managed* versions of these channels — trading the local-first trust model for convenience and reach.

### 21.1 Hosted HTML garden

- **Research:** Decide static-only vs. account-based vs. minimal trusted delivery service. Define data custody rules (what stays encrypted, what the server sees). Produce a cost/lifetime model for hosting, domain ownership, and maintenance burden. Assess whether the trust-model change is acceptable to the product's identity.
- **Build:** A web-hosted garden the recipient visits via URL instead of opening a local file. The server stores the encrypted bundle; decryption still happens client-side. Hosting introduces operational obligations (uptime, domain renewal, data custody) that must be explicitly disclosed.
- Clearly version the hosted format/API separately if it diverges from the local bundle model.

### 21.2 Managed email service

- **Research:** Review legal/operational requirements for scheduled email: deliverability, bounce handling, unsubscribe expectations, abuse prevention, account recovery. Produce a clear trust statement explaining how custodial email differs from the self-hosted script.
- **Build:** A hosted notification service that replaces the self-hosted `notify.py` with managed scheduling, retry, and deliverability. The author registers a delivery schedule (dates only, no letter content); the service sends notification emails on due dates.
- Treat this as a separate service surface, not as a silent extension of the local-only product.

## 24. Unified Sequence of Tasks

This is the canonical execution order for the project. The critical path runs through steps 1→17→ship. Items marked **[parallel]** may run alongside the current critical-path step. Items in the **Garden Polish** track (step 4P) are explicitly **non-ship-blocking** per §15.

*Last updated: 2026-04-27 — step 6 downgraded back to in progress after execution audit (`lateletter --write` still stops after intake); step 10 remains in progress with browser checksum/corruption parity still open; step 11 done (notify.py); step 11a Part C downgraded because `demo_author.py` currently emits bundles without a computed checksum; Part D still awaiting human observation pass*

---

### Completed foundation

1. **[DONE]** Freeze the v1.0 release contract: macOS-first target, app-bundle packaging, bundle compatibility policy, and v1 ship/non-ship scope.
2. **[DONE — 2026-04-18]** Complete Phase 1 research for question-bank and interview design.
3. **[DONE (first pass) — 2026-04-18]** ASCII animation research and prototyping. First set of prototypes approved (birds, butterfly, fireflies, rain, snow, clouds, leaves, letter-bird, garden composition).

### Garden core (ship-blocking minimum)

4. **[IN PROGRESS — code complete 2026-04-19, human verification pending on 4c/4e/4g]** Integrate approved animations into the garden:

   **Process rule:** Each subphase below requires (1) a research pass studying reference implementations and prototypes, (2) implementation, and (3) human verification before the subphase is closed. No subphase is marked done without the author running the garden and confirming the visual result.

   **Completed (4a–4g):**
   - ~~4a. Refactor `garden.py` into modular renderer with 5-layer compositing model (§7.2).~~ ✓ — `src/lateletter/garden/` package (10 modules). `garden.py` is now a thin CLI entry point with `--season` flag.
   - ~~4b. Implement shared particle API (`Particle` type, spawn/update/kill loop, collision with plant surfaces).~~ ✓ — per-type physics dispatch, plant collision map with top surfaces and canopy cells, splash generation on impact.
   - ~~4c. Integrate creature animations (first pass): butterfly, ambient bird, fireflies.~~ ✓ (code done, awaiting human verification) — butterfly (`><`/`||`/`\/` + up-dip), ambient bird (`v`/`~`), fireflies (3 Photinus species).
   - ~~4d. Integrate weather animations (first pass): rain, snow, clouds, lightning.~~ ✓ — first pass working. Rain refined in 4g.
   - ~~4e. Integrate falling leaves with tree-canopy detachment points.~~ ✓ (code done, awaiting human verification) — leaves from canopy_cells, sine-wave oscillation, tumble char rotation, autumn-only.
   - ~~4f. Implement season detection + seasonal weights, colors, and animation activation (§7.4).~~ ✓ — system-date detection, per-season weights, season→weather/creature activation.
   - ~~4g. Rain and wind refinement.~~ ✓ — denser rain (60 drops), gravity 0.08, diagonal `\` rendering, 3-fragment plant collision with reflection+damping (0.32), multi-particle ground splashes (3–5 fan, char aging `'`→`.`→`·`), wind modulates drop drift. Awaiting human verification.

**4P. [parallel, NON-SHIP-BLOCKING] Garden polish track.**

These subphases improve the garden's visual richness but are not required for v1.0 ship (per §15: "Expanded seasonal animation set beyond the minimal garden needed for recipient mode" is non-ship-blocking). They can proceed in parallel with the critical path at any time. Each follows the same research→implement→verify process rule as steps 4a–4g.

   - 4h. Time-of-day system.
     - **Research:** Review §7.5 spec. Study night-mode palette constraints for terminal (dim attrs, limited color pairs). Prototype dusk→night palette transition.
     - **Implement:** Dusk palette shift (warm orange, dimmed plants), night mode (very sparse, fireflies active, moon glyph in top corner, garden dims), `--time day/dusk/night` CLI flag.
     - **Verify:** Author runs all three time modes and confirms mood/atmosphere is distinct and readable.
   - 4i. Procedural plant generators for new types.
     - **Research:** Study §7.1 procedural generation specs for each type. Prototype standalone ASCII art for willow (drooping branches + sway), cactus (arms), bamboo (clustered stalks), lily (wide head), tall sunflower (single stem + large head), dead tree (L-system branching silhouette). Study `asciicker-Y9-2` engine for any relevant plant rendering techniques.
     - **Implement:** Parameterized generators for all 6 new types. Register in weight tables with seasonal variation (dead tree heavy in winter/autumn, lily/sunflower in spring/summer). Integrate sway for willow branches.
     - **Verify:** Author runs gardens with each season and confirms plant variety is visually rich and each new type is recognizable and attractive.
   - 4j. Wind system.
     - **Research:** Study `asciicker-Y9-2` engine `weather.cpp` Perlin-noise wind model (pn_time at 0.3× scale, ±2.0 intensity). Current garden has a simple sine-wave wind; needs gustiness and influence on all layers.
     - **Implement:** Replace simple sine with Perlin-noise or multi-sine wind with gusts. Wind affects: plant sway amplitude, rain/snow/leaf particle drift, creature flight resistance, cloud speed variation.
     - **Verify:** Author watches the garden for 30+ seconds and confirms wind feels organic — gusts visible across layers, not mechanical sine oscillation.
   - 4k. Additional creature animations: cat, snail, bee.
     - **Research:** Design ASCII art and movement AI for each. Cat: multi-line silhouette, sits/walks/tail-flick. Snail: ground-level slow crawl. Bee: small fast movement near flowers with occasional hover.
     - **Implement:** Procedural spawn rules, season gating, movement AI per type.
     - **Verify:** Author confirms each creature is charming and recognizable at terminal scale.
   - 4l. Bloom/growth animations for flowers.
     - **Research:** Design frame sequences for flower opening. Study existing flower head shapes in `plants.py` for compatible bloom stages.
     - **Implement:** Multi-frame growth from stem→bud→bloom on initial garden render or season transition.
     - **Verify:** Author confirms bloom animation is visible and adds life to the garden.

### Author mode

5. ~~Build the author-mode foundation~~ ✓
   - ~~Local storage model (session.json, questions_asked.json, atomic writes, permissions)~~ ✓
   - ~~`pyproject.toml` with declared dependencies (cryptography, argon2-cffi, pytest)~~ ✓
   - ~~Intake data model with validation (intake.py) — passphrase never persisted~~ ✓
   - ~~TUI intake form (curses) with field navigation, passphrase masking, inline errors~~ ✓
   - ~~`--accessible` line-mode path for consent + intake~~ ✓
   - ~~Minimal curses draft editor (§8.4) — arrow keys, Ctrl+S/X, atomic draft saves~~ ✓
   - ~~External-editor path via LATELETTER_EDITOR env var~~ ✓
   - ~~CLI entry point (`lateletter --write`, `--accessible`, `--garden`, `--wipe-session`)~~ ✓ — dispatcher exists, but `--write` still stops after intake pending step 6 integration
6. **[IN PROGRESS — audit downgrade 2026-04-27]** Build the offline author workflow
   - ~~Temporary reviewed seed bank (`data/question_bank_seed.v0.json`)~~ ✓
   - ~~Offline question selector (universal base set + personalization + gating)~~ ✓
   - ~~Q&A session loop with autosave~~ ✓
   - ~~Session resumption with split-state healing~~ ✓
   - ~~Incapacitation/steward handling (§5.6) — steward info, handoff summary, session compaction~~ ✓
   - End-to-end `lateletter --write` integration (message list → Q&A → draft → export / append-later) — **NOT DONE**. Current CLI still exits after intake.

### Recipient experience and delivery

7. **[DONE — 2026-04-20] Design the recipient's daily experience.** Design captured in §6.8 (Garden Progression Layer).

   **All design decisions finalized:**
   - ✓ Normal-day experience: the garden is a place the recipient *tends*, not just watches. Progression layer with cumulative-investment animal relationships, author-programmed memory capsules (items), and gentle entropy with evidence-of-absence.
   - ✓ Post-completion memorial: bonded animals perch permanently + memorial flower + all unreleased garden gifts unlocked (§6.8.8).
   - ✓ Progression mechanics: cumulative actions (not streaks) — research-informed from Neko Atsume, Stardew Valley, Tsuki Adventure, grief-tech UX (§6.8.1).
   - ✓ Author garden direction: rich-but-optional Phase 2 authoring session with finite catalog of plants, animals, items, landmarks, task nudges (§6.8.5).
   - ✓ Three trigger types: date-locked, cumulative-visit-locked, post-letter (§6.8.4).
   - ✓ Letter delivery integration: bonded animal delivers letters instead of default bird (§6.3, §6.8.2).
   - ✓ Bundle schema: `garden_gifts` field added to `.lateletter` format (§6.8.6).
   - ✓ Animals: four-animal v1 set — bird, cat, rabbit, turtle. Author picks one; up to one active relationship per bundle (§6.8.2).
   - ✓ Item catalog: 15 objects finalized (§6.8.3).
   - ✓ Browser progression layer: item discovery supported via archive Memories section + modal overlay; animal visuals deferred to post-v1 (§13.2).

8. **[DONE — 2026-04-20]** Build the `.lateletter` bundle format: `bundle.py` — `Bundle`, `Message`, `GardenGift`, `Trigger`, `Notification` dataclasses; `read_bundle()`, `write_bundle()`, `verify_checksum()`, `create_dev_fixture()`. Dev fixtures use `base64(plaintext)` in ciphertext fields with `hmac=""`. Full test suite in `tests/test_bundle.py`.

9. **[DONE — 2026-04-20]** Build the recipient mode (`src/lateletter/recipient.py`):
   - ~~Bundle loading and checksum verification (§6.2)~~ ✓
   - ~~Locked-state UX: neutral status bar (`e · unlock letters`), no delivery claims before auth~~ ✓
   - ~~Passphrase entry overlay (§6.4) with hint display~~ ✓
   - ~~Due-message detection from authenticated dates + read receipts~~ ✓
   - ~~Multi-message selection overlay (§6.4 step 5)~~ ✓
   - ~~Message reading overlay with scroll (§6.4 step 6)~~ ✓
   - ~~Letter re-read / archive flow (§6.6) — two-section archive (Letters + Memories)~~ ✓
   - ~~Read-receipt tracking (`~/.lateletter/recipient/receipts.json`)~~ ✓
   - ~~Disable `r` key in recipient mode (garden seed is fixed from bundle)~~ ✓
   - ~~First-run experience (§6.5) — welcome message, 3s delay before display~~ ✓
   - ~~Item discovery: triggered items rendered in garden scene + memory overlay + archive Memories section~~ ✓
   - ~~Visit tracking and garden state persistence (`~/.lateletter/recipient/garden_state.json`)~~ ✓
   - ~~All three trigger types: date, cumulative_visits, post_letter~~ ✓
   - ~~Key bindings: `e`=envelope/unlock, `i`=examine items, `l`=letter archive~~ ✓
   - ~~Save-to-text (`p` key): writes `letter_from_{author}_{date}.txt` to ~/Desktop~~ ✓
   - ~~Post-completion state (§6.7, §6.8.8): `_is_post_complete()`, memorial flower `✿` (magenta), permanent perched bird, all gifts unlocked, archive footer "All letters delivered. This garden is yours."~~ ✓
   - ~~Animal relationship system (§6.8.2): trust tiers (0–3, thresholds 3/7/14), `f` feed key, bonded-animal delivery, footprints-on-absence, `RecipientStore.feed_animal()` / `get_animal_state()` / `was_absent`~~ ✓

10. **[IN PROGRESS — 10a/10c/10d done; 10b QA pending; browser checksum/corruption parity still open]** Build the browser viewer (`viewer-bnw.html`) — B&W Times New Roman aesthetic with live animated garden (§13.6 accelerated — full garden ported ahead of schedule):
    - ~~Pure HTML/CSS/JS + `pretext` (pretextjs.dev) for letter body layout~~ ✓ — `layoutWithLines` + `prepareWithSegments`, proportional TNR rendering, ResizeObserver reflow
    - ~~DOM-based 5-layer garden renderer (GardenDOM) replacing canvas — scales with browser zoom, no blur artifact; BackgroundLayer, PlantLayer (7 types, rustle on hover), ParticleLayer (rain gravity+wind, snow accumulation, leaves, fragments, splashes), CreatureLayer (butterfly, ambient bird, firefly), SpecialLayer~~ ✓
    - ~~Seasonal weather: spring rain, autumn rain+leaves, winter snow, summer calm; wind-based rain char (`\`/`|`/`/`); plant collision → fragments; ground hit → splashes; char aging `'`→`.`→`·`~~ ✓
    - ~~File input: drag-and-drop or `<input type="file">` for `.lateletter` bundle~~ ✓
    - ~~Dev-fixture Web Worker (base64 plaintext passthrough); real crypto wired in step 13~~ ✓
    - ~~Full recipient flow: passphrase entry, letter reading with scroll, archive/inbox (§6.6), save-to-text, read receipts via IndexedDB + localStorage fallback~~ ✓
    - ~~Inbox replaces HUD: post-auth inbox floats over live garden; letters read/unread/locked at varying opacity; memories section; no symbols~~ ✓
    - ~~B&W palette: cream paper sky, earthy plant colors, monochrome UI at opacity hierarchy~~ ✓
    - ~~**TODO 10a — Garden always visible:**~~ ✓ `#g.dim` CSS class removed; `classList.toggle('dim')` removed from `showScreen()`; scrim opacity .76, blur 10px; stale `class="dim"` attr cleaned. Needs browser QA across seasonal backgrounds.
    - **TODO 10b — Cursor interaction:** Rustle effect on hover (char substitution near cursor, radius 5 cells — implemented, needs browser QA) and leaf-burst particle spawn on click (implemented, needs browser QA). Confirm both work on touch (mobile tap = click event).
    - ~~**TODO 10c — Animal dev fixture:**~~ ✓ `_ANIMAL_ART` (4 animals × 4 tiers), `_ANIMAL_DELIVERY_FRAMES`, `_ANIMAL_FOOTPRINTS` ported to JS. Animal renders in CreatureLayer at home position (tiers 1–3) or peeks from right edge (tier 0); footprints when absent; bonded perch in SpecialLayer post-complete. `f` key feeds (authenticated, triggered, tier < 3). `Shift+A` dev shortcut cycles all 16 animal states. Animal state persisted in IndexedDB per bundle. Eager trigger eval on bundle load (date + cumulative_visits fire without auth).
    - ~~**TODO 10d — First-run sequence:**~~ ✓ `#frb` banner fades in at 3s, auto-hides at 12s, shown once per session via `_frbDone` flag. Text: "This garden was planted for you by [author_name]." Tracked via existing `kFirst()` storage key.
    - ~~**TODO 10e — HTML grid-fidelity gap:**~~ ✓ `_measure()` now appends test span/div inside `#g` (not `document.body`) for exact font-rendering context; CH measured from real `div` inheriting `height:15px` from CSS rule. `getSeason()` checks `?season=` URL param first. `_arcSeed()` added for `?arc=` browser demo seeding. **Pending:** browser QA pass (Safari/Chrome/Firefox at 100% + 150% zoom) — human verification needed.
    - **Audit note (2026-04-27):** The browser viewer still does **not** recompute/verify the bundle checksum on load, so corruption-handling parity with the terminal recipient remains open even though most recipient UI/progression features are wired.
    - Crypto in a **Web Worker** using chosen Phase 3 primitive (`age-encryption` or `argon2-browser`) — wired in step 13
    - Package as a single self-contained HTML file (inline JS/CSS, no external WASM until step 13)
    - Test in Safari, Chrome, Firefox (desktop and mobile)

11. **[DONE — 2026-04-20]** Build the email notification script (`notify.py`):
    - Standalone script, no app dependency — reads `.lateletter` bundle plaintext metadata only (dates, bundle_id)
    - Checks `date.today()` against message dates, sends email via SMTP for newly due messages
    - Local sent-log to suppress duplicate notifications on re-run
    - Configurable SMTP (any provider: Gmail, Mailgun, Fastmail, etc.)
    - Never reads or decrypts letter content, never stores passphrase
    - Generates cron/launchd instructions for the author/steward
    - Include in handoff package (§15.1)

11a. **[Parts A/B done — 2026-04-21; Part C downgraded 2026-04-27; Part D pending human observation]** Demo harnesses and emotional verification — the next critical-path cluster. These steps make the emotional arc (§6.9) evaluable as a lived experience rather than a code review. All three parts must complete before step 13 (encryption), because the emotional bar must be set before the product is sealed.

   ~~**Part A — HTML grid-fidelity gap**~~ ✓ *(tied to TODO 10e above)*
   - ~~Measure true glyph metrics for the chosen monospace font at 1× zoom; lock in matching CW/CH constants~~ ✓ `_measure()` appends to `#g`, CH from real div
   - ~~Add `?season=autumn|winter|spring|summer` URL param to `getSeason()`~~ ✓
   - Browser QA pass: open the garden in Safari, Chrome, and Firefox at 100% and 150% zoom — **pending human verification**

   ~~**Part B — Full recipient e2e demo harness**~~ ✓ *(compressed timeline simulation)*
   - ~~Extend or replace `demo_recipient.py`~~ ✓ `--arc [waiting|delivery|trust1|trust2|trust3|postcomplete|item]` flags; seeds RecipientStore state; launches real recipient module
   - ~~`--browser` flag~~ ✓ generates dev fixture `.lateletter` per arc + prints `?season=`+`?arc=` URL
   - ~~`docs/DEMO_SCRIPT.md`~~ ✓ produced

   **Part C — Author e2e demo** *(pre-seeded fixture walkthrough; currently downgraded)*
   - `demo_author.py` exists and stages the intended consent→intake→Q&A→draft→export narrative, but its current output is **not yet a valid proof artifact** because it writes a bundle without computing the checksum. Treat Part C as open until the script uses the canonical bundle writer path.

   **Part D — Emotional arc verification pass**
   - Run the recipient demo harness (Part B) as a human observer, not a developer
   - For each of the five §6.9 moments: write a one-paragraph field note (what worked, what felt off, what needs adjustment)
   - If any moment fails its §6.9 criterion, file it as a bug and fix before proceeding to step 13
   - This pass may surface UI timing issues (delivery pacing), visual issues (bird animation weight), or copy issues (memory overlay tone)
   - **Ship gate:** All five §6.9 moments must pass before encryption (step 13) is wired — sealing a product that hasn't been emotionally verified is the wrong order

12. **[parallel with steps 9–11a, editorial]** Expand the seed bank to a reviewed 80–120 question bank covering all 16 domains. Apply the two-human review process (§5.3) to this smaller set. The 500+ bank target is post-v1 content work.

### Security and sealing

13. Build the encryption/sealing layer:
    - **Phase 3 research memo first:** Evaluate `age` vs custom Argon2id+AES-GCM (see §4 "Encryption primitive options"). Benchmark KDF on target hardware. Validate Python/JS parity path. Write memo, decide, then implement.
    - Chosen crypto primitive: key derivation + AES-256-GCM (or age equivalent) with round-trip tests
    - Per-session passphrase caching (mutable bytearray, zeroed on exit — §4)
    - Bundle HMAC derivation and verification using `bundle_auth_salt`
    - Label encryption (label inside ciphertext, not exposed in outer structure)
    - Replace dev fixture stubs from step 8 with real encrypted bundles
    - Wire crypto into browser viewer (step 10) — same parameters Python and JS, verified interop
    - Incremental export with checksum + HMAC recomputation (§5.4)
    - Handoff package generation (§15.1) including viewer.html, README.txt, and optional notify.py
    - Append-later flow: reopen bundle, verify passphrase, add messages (§5.5)
    - Session wipe flow and `--wipe-session` CLI flag (§5.4)

14. Failure-mode and security validation:
    - Corruption fixtures: bad checksum, truncated file, unknown version — in both macOS app and browser viewer
    - Tamper fixtures: bad HMAC, altered message date, modified ciphertext — in both channels
    - Wrong-passphrase handling (generic error, no leakage) — in both channels
    - Crash-safety: kill during session save and bundle export; verify prior valid file survives
    - Canonical-file durability: temp-file + fsync + atomic rename verification
    - Terminal constraints: 80×24, below 80×24, no-color, resize during overlay
    - Browser constraints: mobile viewport, slow Argon2id, storage denied, cross-browser compat
    - Email notification: duplicate suppression, SMTP failure handling, sent-log integrity
    - Performance sanity with realistic bundle — targets: app startup < 3s, passphrase unlock < 5s (Argon2id cost), letter scroll < 50ms/frame, garden render stays within 50ms frame budget, browser Argon2id < 30s
    - §20 security review checklist

### Packaging and ship

15. macOS `.app` packaging:
    - Bundle Python runtime (py2app, PyInstaller, or Nuitka — research and choose)
    - Code signing with Apple Developer certificate
    - Notarization via `notarytool`
    - `.lateletter` file association (UTI registration, `Info.plist` document types)
    - Dock icon and app icon design
    - First-run behavior: open via Finder double-click, drag-and-drop `.lateletter` file
    - Clean-machine install test on stock macOS 14+

16. Hardening and accessibility:
    - `--accessible` author mode end-to-end verification
    - Recipient-side accessible reading path (screen-reader-compatible letter display, non-curses fallback for overlays)
    - Browser viewer accessibility: keyboard navigation, screen-reader-compatible HTML, sufficient contrast
    - Braille display compatibility audit
    - Bundle backward-compatibility testing across v1 builds
    - `--wipe-session` non-interactive secure deletion
    - Minimum terminal size handling (80×24 gate or auto-switch to `--accessible`)

17. Release acceptance: run the full §18 matrix and §19 test matrix. Ship v1.0 only after every required criterion passes.

### Post-v1

18. **[parallel after step 17]** Research the optional LLM path: prompt/evaluation design, privacy disclosure, quality gates, and regression fixtures.
19. Implement optional LLM mode only after the offline/local-first v1 path is stable and already shippable.
20. **[parallel after step 17]** Research hosted delivery extensions (§21): hosted HTML garden custody model, managed email service operations, cost/lifetime analysis.
21. Build hosted extensions only after the trust-model changes are explicit and the self-contained v1 channels are stable.
