# LateLetter — Canonical Project Specification

> A local-first program for the terminally ill. Compose messages for the people you love.
> They will find them — on birthdays, anniversaries, ordinary Tuesdays — inside a living garden.

---

## 1. Vision

LateLetter is a local-first application with two distinct modes and a
browser-led product surface. The terminal Garden remains a development and
diagnostic adapter; it is not a second authoring or presentation owner:

- **Author mode** — a guided, intimate interview process. The author answers curated questions (offline) or LLM-driven questions (with API key) over many sessions. Completed messages are encrypted and exported as a `.lateletter` bundle file.
- **Recipient mode** — the normal garden experience. When opened with a `.lateletter` file, the garden runs as usual. On days when a message is waiting, a small bird appears carrying a letter. The recipient presses `e` to unlock and read.

The garden is both the delivery mechanism and a complete cozy idle garden in its own right. Without a bundle, it must sustain observation, tending, collecting, decorating, plant growth, and animal relationships. With a bundle, author-directed letters and world events join that same simulation rather than replacing it with a reader backdrop. The message arrives as naturally as a bird landing on a branch.

**Product bar:** “The renderer contains garden code” is not completion. A production recipient must be able to discover and operate the feature through touch, pointer, and keyboard on the browser product surface; standalone mode must remain worthwhile when no letter is due; and authored events must be previewable and deterministic. §7.8 is the controlling contract.

---

## 2. Modes at a Glance

| Mode | How to enter | Purpose |
|------|-------------|---------|
| Recipient (default) | `python garden.py [file.lateletter]` | Garden TUI; `e` unlocks the bundle, bird appears after auth if a message is due; `i` examines garden items; `l` opens letter archive |
| Author | `lateletter-author` | Loopback browser questionnaire + canonical service validation/encryption/export |

If no `.lateletter` file is passed, the garden runs as a standalone experience (original behavior). No hint or prompt about `.lateletter` files is shown — the garden is a complete experience on its own.

`lateletter-author` is the canonical local author-server entrypoint. Bundle
construction belongs only to `src/lateletter/author_service.py`; the browser is
an adapter to that module. The packaged recipient release described later in
this spec must expose recipient behavior without requiring terminal command
entry.

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
  "garden_program": {
    "version": 1,
    "ciphertext": "...",
    "salt": "...",
    "nonce": "...",
    "kdf_params": null
  },
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
- `garden_gifts` — legacy v1 compatibility surface for simple single-trigger gifts. New authoring must compile into `garden_program`; readers migrate legacy gifts into equivalent one-shot program events in memory.
- `garden_program` — optional encrypted author-directed world program defined in §7.8.10. The outer envelope exposes only its format version and cryptographic fields. Animal names, inscriptions, event labels, authored choreography, and other narrative-bearing garden content remain inside its ciphertext.
- **Format-version gate:** Do not emit `garden_program` in a `version: 1` bundle until both readers explicitly support that authenticated field. The implementation must either introduce bundle `version: 2` or document/test a backward-compatible v1 extension rule. Existing v1 `garden_gifts` bundles remain readable in either case.
- `kdf_params` — optional per-message KDF parameter override. When `null`, the v1 defaults apply (time_cost=3, memory_cost=65536, parallelism=1, hash_len=32). Future appended messages may use updated parameters without re-encrypting existing messages. This field is cheap to add now and expensive to introduce later (would require a format version bump).
- `ciphertext` — the message body **and label**, encrypted per-message with a unique salt derived from the shared passphrase. The label (e.g., "Her 30th birthday") is inside the ciphertext, not exposed in the outer structure.
- `notification` — optional. Contains `email` (recipient delivery email address) and `method` (`"self-hosted"` or `null`). This field is plaintext — anyone with the file can see the email address. The author is warned about this during the export flow (§5.4). Can be `null` if the author declines email notifications. **Privacy note:** the recipient's email address is PII. Unlike names and dates (cosmetic metadata), an email address is a contact channel. The export flow warns: *"The recipient's email address will be visible to anyone who has this file."*
- `checksum` — SHA-256 hash over the canonical JSON of the visible bundle payload (`version`, `bundle_id`, `author_name`, `passphrase_hint`, `bundle_auth_salt`, `garden_seed`, `messages`, `garden_gifts`, `garden_program`, `notification`). Computed without any secret key. Used at launch for structural integrity checking (detects corruption only — not tamper-resistant, since an attacker can recompute it).
- `hmac` — HMAC-SHA256 over the same canonical visible bundle payload using a key derived from the passphrase and `bundle_auth_salt`. Verified only after passphrase entry. Detects authenticated tampering by an adversary who knows the file format but not the passphrase.

### What is NOT in the file

- The passphrase itself (never stored).
- The plaintext of any message or message label.
- Any server-side identifiers.

### Privacy note

The `date` field is plaintext (required for date-lock checking). Anyone with the file can see *when* messages are scheduled but not *what* they are about. The `author_name` is also plaintext for UX convenience. The message `label` is encrypted alongside the message body so it is only revealed after passphrase entry.

---

## 4. Encryption Model

> **Architecture status (2026-07-21):** The shipped interoperable primitive is
> bounded PBKDF2-HMAC-SHA256 key derivation plus AES-256-GCM, with HMAC-SHA256
> authenticating the canonical visible bundle before plaintext promotion.
> Python and native WebCrypto use the recorded versioned profiles. Explicit
> development fixtures are capability-gated and are not accepted as normal
> sealed bundles.

**Conceptual model (settled):** Passphrase-based symmetric encryption. Author seals; recipient unlocks. Local file only — no server, no account, no network dependency. Tamper-evident (HMAC over metadata). File must remain readable 20–30 years from now without infrastructure.

**Current spec:** PBKDF2-HMAC-SHA256 key derivation + AES-256-GCM per encrypted
message, gift sentiment, and Garden program.

### Author side (write phase)
1. Author sets a **passphrase** during intake — a phrase the recipient already knows or will be told privately (e.g., "the name of our first dog").
2. A bundle-wide 16-byte `bundle_auth_salt` is generated once when the bundle is created.
3. For each message, a unique 16-byte message salt is generated.
4. Message key = `PBKDF2-HMAC-SHA256(passphrase, message_salt,
   iterations)` → 32 bytes. The exact profile is recorded and validated before
   derivation; current bounds are 600,000–2,000,000 iterations and the canonical
   writer emits 600,000. Derived keys and the passphrase are transaction-local,
   not session caches.
5. Message body encrypted with AES-256-GCM. Nonce stored alongside ciphertext.
6. Salt + nonce + ciphertext written into the bundle.
7. On every bundle rewrite, derive `bundle_hmac_key =
   PBKDF2-HMAC-SHA256(passphrase, bundle_auth_salt, recorded_profile)` and
   compute HMAC-SHA256 over the canonical visible bundle payload (everything
   except `checksum` and `hmac`). All HMAC comparisons use constant-time
   comparison.

### Recipient side (read phase)
1. Recipient enters the passphrase at the authentication gate. It is used only
   for bounded derivation and is then discarded; the browser clears the form
   immediately and retains no passphrase global. A nonsecret authenticated flag
   and secret-derived persistence binding may live for the authenticated page or
   terminal process. Browser history-cache purge requires reauthentication.
2. The app first derives the bundle HMAC key from `bundle_auth_salt` and verifies the bundle `hmac`. Until this check passes, the app treats the bundle as sealed and does not announce whether any message is due.
3. If the HMAC passes, the app computes due messages from authenticated dates (`date.today() >= message["date"]` and no read receipt).
4. During the authenticated transaction, the app derives each required message
   key from that message's salt/profile and decrypts its nonce/ciphertext. No
   plaintext or persistent state is promoted until the whole transaction
   validates and materializes successfully.
5. On authentication failure:
   - The overlay shows "Incorrect passphrase, or this file has been modified." below the input field. The field clears.
   - Unlimited retries. No lockout; the validated PBKDF2 work factor supplies
     the passphrase-guessing cost without permitting attacker-selected extremes.
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

### Encryption primitive decision record

The following table records the alternatives considered before implementation.
The current interoperable release profile is PBKDF2-HMAC-SHA256 + AES-256-GCM;
changing primitives requires a new versioned migration and browser/terminal
interop evidence.

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| **Custom Argon2id + AES-GCM** *(not selected for the current profile)* | Roll the key derivation and encryption using `argon2-cffi` + PyCA `cryptography` | Full control over UX (passphrase hints, per-message salts, label layout). | More surface area to get wrong. Requires a separate JS/WASM port and new versioned migration. |
| **PBKDF2-HMAC-SHA256 + AES-GCM** *(implemented)* | Native Python/WebCrypto derivation with recorded, bounded profiles | Offline browser interoperability, explicit versioning, no WASM dependency | Any future work-factor/profile change must remain readable through the versioned compatibility path. |
| **`age` encryption** | [age-encryption.org](https://age-encryption.org/) — modern, simple, battle-tested. Passphrase-based mode wraps Argon2id (scrypt actually) + AES-256-GCM. Python: `pyage`; JS: `age-encryption` npm package. | Widely reviewed, minimal API, native passphrase support. Same primitive in Python and JS — parity is built-in. | Less control over KDF parameters and layout. Passphrase hint not native to the format (would live in plaintext metadata only). Adds external format dependency. |
| **Account/database** | Letters stored server-side; recipient authenticates with account credentials | Simpler UX for recipients; no file management | **Rejected for primary storage.** Server lifetime problem — if LateLetter shuts down, letters are permanently lost. Incompatible with the use case (author is often dying; letters must outlast any company). Privacy: server sees metadata. Post-v1 managed service (§21) uses this model as an *optional layer on top*, never as the sole storage. |
| **Blockchain/distributed** | IPFS, Ethereum, etc. | Decentralised | **Rejected.** Date-lock remains app-enforced regardless. Gas fees, chain longevity risk, terrible UX for grieving non-technical recipients. Does not solve any problem that the file format doesn't already solve with far less complexity. |

**Decision:** PBKDF2-HMAC-SHA256 + AES-256-GCM is the current release
profile. `age` and Argon2id remain historical alternatives, not runtime claims.

The file format (`.lateletter` JSON bundle) is not in question — that stays regardless of which crypto primitive is used.

### Dependencies
- `cryptography` (PyCA) — for AES-256-GCM via `cryptography.hazmat.primitives.ciphers.aead.AESGCM`. Pin version in `pyproject.toml`. Wrap hazmat usage in a tested encryption module with round-trip integration tests.
- `argon2-cffi` remains declared for compatibility/research but is not the
  current sealed-bundle KDF. Any activation requires a versioned format and
  browser/terminal migration evidence.

---

## 5. Author Mode — Full Flow

**Ownership lock (2026-08-10):** The former `lateletter --write` workflow and
`src/lateletter/author.py` direct bundle writer are deleted. They must not be
restored or wrapped. `author_service.py` is the only module that validates,
constructs, seals and writes author-produced bundles; `lateletter-author` and
the browser questionnaire are adapters. The bundled question banks, selector,
Q&A persistence, session resumption, draft editing and authored answers remain
independent domain content. Their retention does not retain terminal export
authority. Until `web/author-app.mjs` lands and passes the E2E author path,
author control is BLOCKED rather than satisfied by the service alone.

### 5.1 First launch (consent and intake)

Before any letter writing begins, the author completes a combined **intake and wishes form**. The steward designation and wishes fields are integrated into the intake form (not a separate gate), because the wishes have no automation backing them in v1 — they are advisory records for the steward's guidance, not automated behaviors. The "release unfinished on date" option has no enforcement mechanism; the steward must manually act on it.

**These choices are editable.** The author can return to the intake screen from the message list at any time to update steward, wishes, or other intake fields. A terminally ill author whose steward dies or whose prognosis changes must be able to revise without starting over.

The **intake form** follows. Default presentation is the responsive browser
questionnaire served from loopback. It uses ordinary labeled HTML controls,
keyboard navigation, screen-reader semantics and autosave; there is no
terminal author fallback. Fields:

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
- The first end-to-end offline author prototype may use a smaller reviewed **seed bank** stored as the packaged resource `src/lateletter/data/question_bank_seed.v0.json`.
- That temporary seed bank is only for Phase 1 / early Phase 2 implementation and research validation. It must still be separate from source code and still use the canonical entry shape wherever practical.
- The seed bank is not the release artifact and must not become an ad hoc permanent format. Before v1 ship work proceeds past the prototype stage, it is replaced by the bundled canonical bank file and editorial release workflow described above.
- During the prototype stage, any derived selector state, asked-question logs, or temporary scoring metadata remain user-local under `~/.lateletter/author/`; no runtime process writes back into the seed bank file.

### 5.4 Encryption and export

**Incremental export:** Each message is encrypted and appended to the bundle as soon as the author finalizes it (not batch-all-at-end). The `checksum` and `hmac` are recomputed and the bundle file rewritten after each message finalization, ensuring the on-disk file is always a valid, verifiable bundle. This means that if the author loses capacity unexpectedly, all completed messages are already safe.

**Incremental handoff:** Every time the bundle is rewritten (message finalized),
the target handoff folder contains the current `.lateletter` file, the verified
static viewer closure rooted at `viewer-bnw.html`, and a stub `README.txt`.
This ensures the delivery artifact (not just the crypto artifact) stays current.
If the author loses capacity before the formal "Export bundle" flow, the steward
can find a complete handoff folder at the bundle's location. The formal action
adds notification setup, backup guidance, and session wipe.

Export flow:
1. Author triggers "Export bundle".
2. Any remaining unencrypted messages are encrypted independently (see §4). The checksum and HMAC are recomputed over the canonical visible bundle payload.
3. A `.lateletter` file is written to the author's chosen path using temp-file + `fsync` + atomic rename on the same filesystem. If the atomic replace cannot be completed, the previous valid bundle remains untouched and the app shows an export failure.
4. **Handoff package generation:** The app creates the handoff folder (§15.1)
   at the author's chosen path. This includes the `.lateletter` file, verified
   static viewer closure, `README.txt` (auto-generated from intake data), and
   optionally `notify.py` and `LateLetter.app`. The folder is created via a
   temporary directory plus atomic rename.
5. **Email notification setup (optional):** If the author wants due-date email notifications (§13.3), the app prompts for the recipient's email address and SMTP configuration. This metadata is stored in the bundle's plaintext `notification` field. The `notify.py` script is configured and included in the handoff folder. The author or steward is instructed to set up a cron job on any always-on machine.
6. **Passphrase warning screen:** *"Important: If Maya cannot remember the passphrase, these letters are lost forever. There is no recovery. Consider writing the passphrase down and leaving it with someone you trust."*
7. **Backup guidance screen:** *"This folder contains all of your letters. There is no backup and no recovery. We strongly recommend saving a copy to a second location — a USB drive, cloud storage, or with someone you trust. Note: your letters are encrypted, but the delivery dates, your name, and any notification email are visible to anyone with the file."*
8. **Session wipe prompt:** *"Completed drafts and notes are still on this computer. Would you like to delete them securely? [Delete completed drafts / Keep everything for later]"*
   - **Delete completed drafts:** Overwrites finalized `drafts/*.txt` with random bytes, then deletes them. `session.json` is compacted: intake context, steward information, pending message slots, and unfinished-message notes remain; Q&A content for already-encrypted messages is removed. `questions_asked.json` is retained for dedup.
   - If unfinished-message notes exist, a second prompt appears: *"Keep unfinished notes so you or your steward can continue later? [Y/n]"*. Default is keep.
   - **Keep everything for later:** All files retained. Warning shown on next launch: *"Unencrypted drafts exist in ~/.lateletter/. Return to the author desk to review or delete them."* The maintenance-only `lateletter --wipe-session` command remains available for an explicit full local wipe.
9. Final screen: *"Give this folder to Maya. Tell her the passphrase when the time feels right — or leave it with someone you trust."*

**Default is Delete completed drafts** — the secure option should not require opt-in, but unfinished notes are preserved by default because they are still part of the incapacitation/handoff path.

### 5.5 Adding messages later

The author can reopen the browser author desk, select an existing
`.lateletter`, and add new message slots. On reopening, the author must supply
the original passphrase; the service verifies it by recomputing the bundle HMAC
before allowing additions. The passphrase is retained only for the active
export transaction and discarded afterwards. It is used for encrypting new
messages and recomputing the HMAC.

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
3. **Session file as handoff artifact:** `session.json` contains intake context and Q&A history but **never the passphrase**. The steward must already know the passphrase (or the author must communicate it separately). The steward opens the local browser author desk with the existing bundle and enters the passphrase to continue.
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

2. **Authentication:** Recipient enters the passphrase and sees a neutral
   *"Verifying…"* indicator while bounded PBKDF2 derivation runs. The input and
   passphrase string are cleared after derivation. The authenticated process may
   reuse already decrypted transaction output, but it does not retain the
   passphrase; a browser purge/history restore requires a fresh authentication.

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

6. When the recipient opens a due message, the label is decrypted and shown ("For your 30th birthday"), then the full message renders in the overlay with word-wrap. For long messages, `↑/↓` or `j/k` scrolls within the overlay. A soft indicator at the bottom shows scroll position (*"↓ scroll for more"* or *"end of letter"*). Full-screen interactive TUI screens require a minimum terminal size of **80 columns x 24 rows**; below that, the app shows a resize-required screen and directs the recipient to the browser viewer instead of rendering a truncated interface. Pressing `p` attempts to print if a supported printer backend is available; otherwise it offers save-to-text-file for manual printing.

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

The garden is not just a delivery mechanism — it is a place the recipient tends. Over time,
the recipient's care creates a living relationship with the composed garden: plants whose
development they influenced, animals that recognize them, and small authored memories
discovered in the landscape. The progression layer is stored independently from the
bundle's `garden_seed`—the seed-based garden is the author's gift; the recipient contributes
a persistent history of nurturing rather than changing its composition.

#### 6.8.1 Design principles (research-informed)

Derived from prior art analysis of passive care games, virtual pets, adaptive companion
agents, constrained world generation and long-term human-robot interaction. The 2026-07-30
source notes are tracked in `tracked/LateLetterResearch/`.

1. **Cumulative, varied investment—not streaks.** Relationship depth is gated by varied
   interactions and shared rituals, not consecutive daily visits or one repeated verb. A
   recipient who misses three months picks up where they left off.
2. **Gentle visual change, immediate recovery.** A plant may enter seasonal rest or show a
   recoverable dry state, and an animal continues its autonomous routine. Absence never
   removes the animal, lowers bond, creates sickness, or generates care debt. One appropriate
   action restores any care-responsive plant presentation.
3. **Evidence of elapsed life, not punishment.** On return, the recipient may find footprints,
   a feather, a new resting place, a bloom, or another bounded discovery. The garden changed
   while they were away; it did not suffer to compel their return.
4. **Automatic nudges, not menus.** Interactions surface via status bar callouts ("a stray cat lingers at the edge…") rather than action menus. The recipient presses a single key to respond. One action at a time — grief reduces decision-making capacity.
5. **The garden and letters must reinforce one another.** In standalone mode the garden is the primary experience. In authored-bundle mode the letters remain emotionally first-class, but tending, collecting, animal behavior, and authored world changes continue between deliveries. Neither side may reduce the other to an interruption or a decorative backdrop.
6. **No unsolicited notifications tied to the deceased.** The garden never pushes notifications referencing the author by name in a guilt context. All engagement is pull-based.
7. **Natural ceiling.** The progression system has a finite depth — the garden reaches a state of fullness, not an infinite treadmill.

#### 6.8.2 Animals

Animals are the primary relationship mechanic. The v1 starter set is **four animals: bird, cat, rabbit, and turtle**.

**Bond tiers:** §7.8.7 owns the scoring, memory and behavioral contract. Tiers are cumulative
and non-decaying, but full bond additionally requires interaction variety.

| Bond tier | Behavior |
|-----------|----------|
| 0 — Stranger | Animal watches from safety, explores edges, and avoids direct approach. |
| 1 — Familiar | Animal approaches after a pause, accepts care, and uses a nearby fixture. |
| 2 — Bonded | Animal initiates play, follows briefly, rests nearby, and recalls preferences. |
| 3 — Full bond | Animal greets on return, brings discoveries, seeks shared spaces, and may perform authored delivery. |

**Per-animal details:**
- **Cat:** Multi-line ASCII art. Sits, walks, tail-flick, naps. Can have a colored collar and nametag — author-assigned during garden direction (§6.8.5) or recipient-chosen. The cat's name is part of the relationship.
- **Bird (relationship bird):** Distinct from the ambient sky birds (§7.1) and the letter-bird. Species variety (robin, sparrow, cardinal). Perches on trees, hops on ground near food.
- **Rabbit:** Ground-level, shy. Hops near flowers. Tucks up when startled. Most visible at trust tier 1–2; at tier 3 it naps curled near a flower bed. ASCII art (two rows):
  ```
  (\ /)
  . .
  ```
  Unicode variants are welcome in the browser atlas profile; the terminal atlas
  profile admits only validated one-column grapheme clusters for safe curses
  width tracking.
- **Turtle:** Slow, reliable, always eventually arrives. Deliberate ground movement. Never startles. Stays longer than any other animal at each tier — the tortoise of the garden. At trust tier 3 it has a favorite rock it always returns to. ASCII art TBD during implementation (two-line shell silhouette).

**Absence and recovery:** Bond does not decrease on absence. Evidence of autonomous life may
appear—footprints, feathers, a newly favored perch or claw marks on a tree—but the animal
does not withhold its relationship until a care debt is paid. Its presence follows its
species/personality routine and authored scenes.

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

> **Scope correction (2026-07-21):** The catalog picker below is the minimum approachable surface, not the full author contract. §7.8.10 additionally requires a fatigue-aware timeline with compound conditions, recurrence/missed-event behavior, plant and fixture transformations, animal personality/routines/choreography, sky/scene direction, deterministic preview, trace explanations, conflict handling, and export-blocking validation. Authors must be able to control narrative and temporal world events without editing JSON.

After letter writing (Phase 1 authoring — intake, Q&A, drafts, encryption), the author may optionally enter a **garden direction** session. This session is entirely skippable — the garden runs a complete, beautiful experience without any authored garden elements. The progression layer's animal relationships and recipient-initiated interactions work regardless.

**Catalog (v1 — finite starter set):**

| Category | Options | Author specifies… |
|----------|---------|-------------------|
| Plants | Sapling, willow, rosebush, sunflower, herb garden | Which plant, placement hint ("near the big tree," "by the edge"), trigger |
| Animals | Cat, bird, rabbit, turtle | Which animal, optional name, optional collar color (cat), trigger for first appearance |
| Items | 15 curated ASCII objects — see §6.8.3 catalog | Which item, sentiment text (1–2 sentences), trigger |
| Landmarks | Carved rock, small bench, birdhouse, wind chime, lantern | What it is, optional inscription text, trigger |
| Task nudges | Author-written gentle prompts | The prompt text ("Water the lavender if you feel like it," "Sit with the cat for a minute"), trigger |

**Author UX:** Rich but optional. Presented as a guided flow after letter completion: *"Would you like to leave something in the garden too?"* The author picks from the catalog, writes sentiment/inscription text, and assigns a trigger. One item at a time, fatigue-aware, auto-saved. Matches the existing intake style (§5.1). The session can be entered and exited freely — partial garden direction is saved and resumable.

**Task nudges:** Author-written prompts that appear as gentle status bar messages on their
trigger date or visit count. They are suggestions, not obligations: *"Water the lavender if
you feel like it."* *"Watch the sunset."* *"Sit near the cat for a minute."* The recipient
can ignore them. They are the author reaching forward in time to share a moment, not assign
homework or grant placement agency.

#### 6.8.6 Bundle schema addition

The `garden_gifts` shape below is the **legacy v1 compatibility representation**, not the target authoring model. It can express only one entity and one scalar trigger at a time. The release authoring model is the encrypted, versioned `garden_program` in §7.8.10, which supports compound conditions, schedules, recurrence, missed-event policy, deterministic effects, plants, fixtures, animal choreography, and previewable narrative arcs. Existing readers must continue to migrate `garden_gifts` into equivalent one-shot program events.

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

Progression state is stored as the versioned canonical `WorldState`, separate from the
sealed bundle and namespaced by the authenticated bundle binding. Terminal storage uses
the recipient state directory; HTML uses IndexedDB. Both serialize the same canonical
fields and reducer receipts rather than renderer-specific progression records. A simplified
shape is:

```json
{
  "<bundle_id>": {
    "total_visits": 42,
    "last_visit": "2027-08-15",
    "world_state_version": 1,
    "animals": [{"animal_id":"animal.cat","species_id":"cat","bond_points":40,"bond_tier":3}],
    "plants": [{"plant_id":"plant.sapling","species_id":"oak","growth_age":3600}],
    "inventory": ["<collectible_id>"],
    "milestone_receipts": ["<canonical_receipt_id>"],
    "program_state": {"applied_occurrences": ["<occurrence_id>"]}
  }
}
```

If persistence is unavailable, letters remain readable and the Garden may run ephemerally;
the renderer never becomes a fallback progression owner.

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

Verify: Use canonical fixture worlds and a normal sealed recipient flow to observe every
species/tier transition through real `observe`, `feed`, and `play` commands. Is each tier
visually distinct from the last? Does tier 3 feel like something the garden chose to give?

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

> **Subordinate to §7.10 (noted 2026-08-02).** This section carries no attribution and no date,
> and a blanket approval cannot override a dated per-asset verdict. Where §7.1 lists an
> animation that §7.10 or `docs/garden-presentation-recipes.json` records as `rejected` — the
> sky clouds and distant birds, rejected 2026-08-01 — the dated rejection governs. §7.1
> describes the prototype library; it does not license anything into a live frame.

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

The Garden has one authoritative versioned `WorldState`, reducer, clock, camera,
topology, object/action model, and projection. Terminal and HTML renderers are read-only
consumers of the same projection. They may differ in disposable presentation detail, but
neither may generate or persist gameplay positions, collision, targets, growth, animal
decisions, schedule results, inventory, milestones, or author-program effects.

| Presentation plane | Projection inputs | Renderer-owned output | Forbidden ownership |
|---|---|---|---|
| Scene | season, weather, civil time, sky mode | palette, sky/ground cells, moon/star glyphs | season/time/weather state |
| Objects | exact IDs, positions, depth, topology, footprints, hotspots, actions, semantic state | atlas glyphs, bounded LOD, color, wind/pose frames | placement, collision, hit identity, actions |
| Effects | accepted exact target ID, semantic object surfaces, motion policy | bounded rain/snow/leaves, hover/click/feed feedback, one-cell ambience | world mutation or target selection |
| Recipient UI | canonical focus, journal/inventory, letter/program facts | named buttons, status prose, accessible summary | duplicate focus/progression state |

HTML may deterministically pack projected art within a responsive 4–22-row band to avoid
glyph overlap. A projection-owned connected group moves as one disposable unit; its relative
anchors remain exact. Pointer targets originate from projected hotspots through that same
transform/offset and may only be enlarged to the 44px accessibility minimum.

**Surface models:** Visible organs and fixture render cells come from canonical projection.
Disposable snow/rain/leaf reactions may read those surfaces, but cannot register a second
collision map or overwrite projected object art.

#### 7.2.1 Visual source chains and the identity criterion

Added 2026-08-02 under the operator route step 1. The table above says *what* the renderer
may own. It did not say how a drawing acquires a reviewable identity, and that gap is what let
a location-based rule delete approved art three times: ground cover, then butterflies and
fireflies, then sky decoration — each removed for being renderer-local, which this section has
always permitted.

Two chains produce an emitted cell. They are **not** tiers and they do not rank; they are
different provenance routes with different review requirements.

```
canonical object    ->  atlas asset          ->  emitted cell     (visual_source_kind 'atlas')
projection/viewport/time  ->  presentation recipe  ->  emitted cell  (visual_source_kind 'recipe')
```

Every emitted nonblank primitive carries a `visual_source_id`. The word that matters is
**carries**: the emitted thing holds the id, not merely the call that drew it. **How that is
established is §7.2.2, and it is established at runtime.**

Withdrawn 2026-08-02. This clause previously spelled out a three-part static test over the
renderer's source — that a writer accept an identity parameter, hand it down into its callee's
identity argument on every emitting branch, and store it into an allocated per-cell plane — and a
checker read the JavaScript to decide it. Eight rounds of audit each shut one way of writing an
invocation and produced another: a receiver that is not named, a receiver that is not a name at
all, an invoked subscript, an optional invocation, a reflective `call`, an extracted reference, a
right-hand side that mentions the identity and stores null. Whether a run of text will put an
identity in a particular cell is a property of **execution**, and the ways to spell an invocation
are not an enumerable set; a gate built on reading the text was converging on a second, worse
JavaScript interpreter. The requirement is unchanged and is now stated where it can be measured:
compose a frame through the public interface and read the primitives back.

**`visual_source_kind` is derived, not stored:** the two identity spaces are disjoint and a test enforces that, so the id alone
determines the chain — an `asset_id` means `atlas`, a `recipe_id` means `recipe`. Storing it
alongside would create a second copy of a fact already implied by the first, and the two could
then disagree; a cell claiming kind `atlas` under a `recipe_id` would have to be adjudicated,
and there is no honest way to decide which half is the lie. Amended 2026-08-02 after an audit
found the checker enforcing only the id: the contract was stating a field nothing produced or
read, which is prose that cannot fail a build.

| | atlas chain | recipe chain |
|---|---|---|
| `visual_source_id` | an `asset_id` in `docs/garden-asset-acceptance.json` | a `recipe_id` in `docs/garden-presentation-recipes.json` |
| `object_id` | **may** carry one, inherited **only** from canonical projection | **must not** carry one |
| owns | the drawing of a gameplay object | the visible language: glyph sets, colour-ramp shape, motion law, density law, cadence |
| review | per-asset operator verdict (§7.10) | per-recipe verdict in the recipe register |

A record on the recipe chain may be `kind: "paint"` (emits cells) or `kind: "law"` (decides
what the painters are given — population density, wind, cadence, painter order, palette,
measured cell size, animal state). A law emits no cells of its own but changes every cell
downstream of it, so it needs identity for the same reason.

**A law is never a cell's visual source.** A painted cell is produced by its recipe *and* by
every law in force when it was painted, which one `visual_source_id` cannot express. The
dependency is an explicit edge instead: a paint record declares `law_refs`, and each law
declares its `dependents`. Both directions are checked, so a law that quietly loses a dependent
fails rather than drifting. Naming a law as a cell's source is anonymity with a respectable id
attached, and blocks a release.

Recipe-chain state — particle lists, accumulation depth, animation phase — is presentation-local.
It may **read** canonical surfaces (top surfaces, canopy cells, footprints) and may never write
them, enter layout, enter command dispatch, register a second collision map, overwrite projected
object art, or be persisted.

**Release criterion — identity, not location.** Renderer-local paint is permitted; anonymous
paint is not. A root-product release is blocked while any nonblank emitted cell carries no
`visual_source_id`, any cited id names no record in either register, or any reachable source
carries a verdict other than `accepted` / `accepted_as_deployed`. The two identity spaces are
disjoint: a `recipe_id` may never equal an `asset_id`, and a recipe verdict may never confer
acceptance on an atlas asset.

**Two enforcers, and the boundary between them does not move.**

- `scripts/validate_presentation_identity.py` validates the REGISTERS: that every id is declared,
  that verdicts, presence requirements, `law_refs` and `dependents` edges are coherent, that the
  two identity spaces stay disjoint, and that every provenance range and decision quotation is
  true of the artifact and the operator record it cites. Checking that a claim about a file is
  true is a decidable question about that file. **It may never infer JavaScript dataflow**, and it
  may never decide whether a drawing carries identity by reading the renderer's source.
- The composed FRAME answers whether a primitive carries identity, by being composed and read
  (§7.2.2). This is the release criterion.

The static writer-graph criterion that used to live in the first bullet is frozen at its extent of
2026-08-02 and is not extended. It is withdrawn in the same patch that installs the runtime
invariant, so the gap is never unmeasured and the two never both claim authority.

Provenance is recorded per primitive where the primitive is emitted, and must survive
serialisation. Serialising rows (`line`, `latticeHtml`) never assigns identity: a row routinely
holds primitives from several sources, so no single id could truthfully describe one.

Permanent policy and computed blockers are recorded separately. `release_policy` states what
makes a release unacceptable and never empties; `active_release_blockers` are computed and must
all clear before cutover. Asserting a list that mixes both is empty is unfalsifiable, not strict.

**Verdicts.** `accepted_as_deployed` records the operator grant of 2026-08-01 over the art
serving rikiworld.com/lateletter, and attaches to the exact characters, colours, constants and
laws in blob `59dc49a820d07d1b6a1741e17aafe6d075f6c99d`. A migration reproducing them retains
approval; a divergent reimplementation does not, and is recorded `candidate_status: different`
so it cannot claim the verdict. The vocabulary is `accepted_as_deployed` / `accepted` /
`not_reviewed` / `rejected`, and it is the same in the SPEC, the policy, the register and the
validator.

**Acceptance and presence are separate fields.** Whether the operator asked for a thing
(`presence_requirement: required`) is not a verdict on any drawing of it. Held in one field,
"the operator asked for birds" acted as approval of an unreviewed bird. A required presentation
whose implementation is absent or rejected blocks a release exactly as a rejected drawing does —
there the defect *is* the absence, so no amount of correct drawing elsewhere clears it.

A source-code reference is provenance, not approval; only a `decision_ref` is evidence of that.
The reference must also be *verifiable*: every cited range is checked against the immutable blob,
every anchor must resolve to a real heading in `docs/operator-decision-record.md`, and every
quoted operator statement must appear verbatim in the section it cites. Checking that a citation
merely exists is what allowed eighteen ranges pointing at unrelated code and three anchors
pointing at no heading to stand as evidence.

**Performance budget:** Presentation targets a responsive 20 FPS ceiling when motion is
visible. Row diffs compare glyph and color HTML; cell metrics cache until resize; the RAF
sleeps when the Garden is hidden, paused, or reduced-motion suppresses animation. If the
budget is exceeded, reduce disposable effect density/LOD before dropping semantic objects.

**Portability:** Terminal renders the versioned ASCII/Unicode atlas directly. HTML may add
projection-only storybook detail, but semantic labels, focus, coordinates, targets, and
actions remain portable and renderer-independent.

#### 7.2.2 The GardenPresentation interface contract

Added 2026-08-02, superseding the static-source criterion withdrawn in §7.2.1. That criterion
failed as a METHOD, not as an implementation: it tried to decide a property of running code by
reading its text. This section states the same requirement as a contract on an INTERFACE, so it is
settled by composing a frame and looking at what comes back.

**GardenPresentation is two functions, and painting is a separate step.** The earlier
`composePresentationFrame(input)` shape is withdrawn because it could not represent pointer hover
or click feedback without hidden state. Presentation state is advanced explicitly from events, then
the frame is composed from that state:

```
advancePresentationState(previousState, presentationEvents, tick) -> presentationState
composePresentationFrame(projection, presentationState, context) -> PresentationFrame
paintPresentationFrame(frame, surface) -> void
```

`presentationEvents` is the only way pointer movement, pointer leave, click feedback and focus
changes enter the presentation layer. The resulting state is disposable and unpersisted, but it is
not derivable from `(world_id, frame, viewport)` alone: hover depends on the current pointer
position, and bursts depend on prior click events. A composer that reads pointer state, browser
events or hidden module variables directly violates this contract.

The split is the whole point. A composer that returns a value runs in Node, in Python, in a test,
with no browser and no DOM, and every clause below becomes an assertion about the returned value. A
composer that paints as it goes can only be inspected by reading its source, which is the approach
this section replaces. `paintPresentationFrame` may not decide anything: if it can add a primitive,
choose a colour, measure a run, resolve an accepted source, choose a painter order or place a hit
region, the frame is not the truth about the picture.

**State advance input — an exhaustive list.**

| Input | What it carries |
|---|---|
| `previousState` | prior disposable presentation state, or absent for the first frame |
| `presentationEvents` | pointer move cell/pixel, pointer leave, click feedback event, canonical focus change, reduced-motion transition; no command dispatch |
| `tick` | presentation tick/frame index and elapsed presentation time |

`advancePresentationState` may update hover emphasis, burst age, particle lists, accumulation
depth and animation phase. It may not write canonical world state, persist anything, choose a
command target or read the hostname.

**Composition input — an exhaustive list.** The composer reads `projection`, `presentationState`
and `context`, and nothing else:

| Input | What it carries |
|---|---|
| `projection` | the canonical projection, read-only: exact object IDs, positions, depth, topology, footprints, hotspots, declared actions, semantic state, season, weather, civil time, sky mode |
| `presentationState` | the disposable state returned by `advancePresentationState` |
| `context.viewport` | pixel extent and logical cell extent |
| `context.profile` | `browser-proportional` or `ascii-safe`; browser and terminal profiles are explicit inputs, not inferred from runtime |
| `context.presentationGeometry` | immutable measurement table: bundled font identity/version/hash, cell geometry, world-to-pixel transform, asset-local prefix widths, row/run measurements and cache identity needed by §7.9 |
| `context.acceptedManifest` | build-generated accepted-paint manifest bound to this release artifact by identity/hash |
| `context.environment` | reduced-motion preference, theme, reader region and other non-authority presentation facts |

Not inputs, and so not readable during composition: the wall clock, unseeded randomness, persisted
storage, the world state behind the projection, the hostname, the DOM, Canvas, PreText, live font
objects, or a global measurement cache. Contract P is implemented by passing the measurement table
in `context.presentationGeometry`; a composer that secretly consults PreText/Canvas/DOM is not a
pure composer. **The hostname is not an input**: paint authority arrives only as the build-bound
accepted manifest, so accepted paint composes on every host and unreviewed ink composes on none.

**Accepted manifest authority.** `acceptedManifest` is not caller-minted policy. A release manifest
is generated at build time from the validated atlas and recipe registers, records the register
hashes and artifact identity it was built against, and is included in the release artifact. A
runtime caller may select among build-produced manifests only by artifact identity. Tests may inject
manifests only through an explicit test adapter whose name makes the authority substitution visible.

**Output — a `PresentationFrame` the caller can read.** It carries:

| Field | Required content |
|---|---|
| `attempted_primitives` | every attempted draw in painter order, including overwritten/occluded primitives |
| `visible_primitives` | final-visible primitives after overwrite/occlusion; this is the painting truth |
| `background` | gradient/solid/background bands, with units and palette roles |
| `interaction_regions` | transformed regions keyed by projected `object_id`; geometry, units, accessibility expansion and source asset/state mask |
| `diagnostics` | density, counts, timings and review aids only; diagnostics never grant acceptance |

Every primitive states its unit system (`cell`, `pixel`, or both), glyph/run content, position,
dimensions, anchor, palette role/colour token, painter order, source_id, optional object_id,
profile, and measured proportional run data when profile is `browser-proportional`. A primitive
that is attempted and then hidden remains in `attempted_primitives`; only `visible_primitives`
drive the final painted picture. With this structure, `paintPresentationFrame` copies a decided
frame to a surface and cannot choose content, colour, position, order, measurement, background or
hit geometry.

**The contract must be executable.** The public runtime-frame check is over this
`PresentationFrame`, not over renderer source. A reference composer must satisfy every clause and
emit real ink; each clause must also be broken deliberately and caught. The existing
`web/garden-presentation-contract.mjs` / `tests/garden_adapters/test_presentation_contract.mjs`
draft predates the six blocking findings of 2026-08-02 and is not authoritative until updated to
this section.

**1. Runtime emitted-primitive identity.** Every nonblank primitive in a composed frame carries:

- `source_id`, non-null, naming a record in `docs/garden-asset-acceptance.json` or
  `docs/garden-presentation-recipes.json`. A `kind: "law"` record is never a `source_id` (§7.2.1);
- `object_id`, present only on the atlas chain and inherited **only** from the projection. A
  recipe-chain primitive carries none.

Verified by composing an actual frame through the public interface and reading the primitives
back: the invariant is over emitted values, not over the code that emitted them. It cannot be
satisfied by adding an argument nothing reads, because nothing about the calling convention is
inspected.

**2. Presentation-only state travels through the public state advance, not behind it.** Particle
lists, accumulation depth, animation phase, hover emphasis and burst age belong to the presentation
layer. They are produced by `advancePresentationState`, consumed by `composePresentationFrame`, and
returned as ordinary values; the composer keeps nothing of its own between calls. The checkable
consequence is exact: **advancing state and composing twice from the same prior state, events, tick,
projection and context returns the same cells, the same regions and the same next state**, and the
composed picture does not change when the hostname underneath it changes. This state is never
persisted, never written back to the world, never enters canonical layout or command dispatch,
never registers a second collision map, and never overwrites projected object art. It may READ
canonical surfaces — top surfaces, canopy cells, footprints.

**3. Canonical-object interaction-region ownership.** The split is exact:

- Projection owns `object_id`, selected `asset_id`/`state_id`, hotspot anchor and declared primary
  action.
- Atlas owns the asset-state-local interaction mask.
- Composer transforms the atlas mask through the same presentation transform and binds the region
  to the projected `object_id`.
- Input adapters map a selected `object_id` back to the projection action and dispatch it through
  the canonical command path.

The composer may enlarge a transformed region to the 44px accessibility minimum
(`MINIMUM_TARGET_PX`, `web/garden-geometry.mjs`). It may not invent a region, move one, drop one,
derive one from what it happened to paint, or dispatch an action. On the composed frame:

- every region is keyed by an `object_id` that exists in the projection;
- every declared-interactive object that emitted visible ink has a region;
- every region names the `asset_id`/`state_id` mask it came from;
- hover changes the picture only — no label, tooltip, card, button, list or action sheet
  (§7.8.3).

An unowned region and unreachable interactive ink are both defects, and both are visible in the
frame without a browser.

**4. The validation boundary.** Registry validation validates IDs and provenance and never infers
JavaScript dataflow (§7.2.1). Identity is a runtime question answered by a composed frame. The
static writer graph, `unresolvable_paint_call_forms`, `writers_that_cannot_record_identity`, and
the synthetic internal-Raster authority are frozen diagnostics only until the public runtime-frame
check lands. They must be deleted in the same patch that installs that runtime check; they must not
survive as a parallel policy owner.

**Not yet true, recorded so the contract is not mistaken for a description.** As of 2026-08-02
`CanonicalGardenRenderer.render(projection)` (`web/garden-renderer.mjs:2186`) composes and paints
in one pass; its `Raster` is not exported; no per-primitive plane stores identity;
`allowUnacceptedArt` still defaults to true; interaction regions are recovered by hit-testing
painted output (`_layoutCandidatesAt`) rather than transported from the projection; and the
terminal composer `GardenRenderer.render_lines(world)`
(`src/lateletter/garden/renderer.py:67`) takes the world rather than a projection, so the two
renderers do not yet share one composition input. The executed contract test records this by name:
the live renderer exposes no composer, so there is no frame to apply the contract to, and the test
fails the day one appears — which forces the gate and the code to move together rather than one
quietly outrunning the other. Under the operator route of 2026-08-02 the accepted-paint manifest
lands with the removal of `allowUnacceptedArt`, and the projection-owned interaction masks with the
hover/click reconciliation that follows it.

### 7.3 Procedural generation philosophy

The garden uses a **hybrid authored/procedural scene model**. Procedural systems provide variation and growth; a versioned atlas provides recognizable fixtures, collectibles, animal key poses, and narrative landmarks. Both resolve into the same authoritative world objects before rendering. This means:

- **Plants** are assembled from parameterized templates: trunk height, canopy shape, branch structure, flower pattern. The seed determines which parameters are chosen for each plant in the garden, making each recipient's garden unique but deterministic.
- **Fixtures, collectibles, and animal key poses** are pre-authored atlas assets with stable anchors, collision masks, interaction hotspots, semantic labels, animation states, and ASCII fallbacks. Procedural placement may select and compose these assets but may not redraw their authoritative geometry at render time.
- **Relationship animals** use canonical deterministic AI, position, memory, needs, intent,
  bond tier, and choreography. **Ambient insects/glints** may vary as disposable one-cell
  trajectories and must never impersonate a relationship animal.
- **Weather** intensity and particle density are season-driven with seed-based variation in timing and placement.
- The prototypes in `ascii-animations/` establish the **visual vocabulary** (what a butterfly looks like, how rain falls). The integration work translates these into parameterized generators that produce variety from the seed.

**Seeded-generation contract:**

- A seed selects among **legal** candidates; it never makes an illegal position, disconnected
  plant organ, broken room dependency, or unreachable interaction acceptable.
- Generation runs in stable passes: room/terrain regions → required fixtures and connected
  paths → large plants → small plants → animal home/routine anchors → collectibles →
  authored initial-state additions. A later pass may depend on an earlier successful
  placement but may not silently invent a missing dependency.
- Every candidate declares allowed regions/surfaces, footprint and clearance, required and
  forbidden adjacency, dependency IDs/tags, maximum instances, and an optional
  `exclusion_group`. Mutually exclusive candidates compete within that group; deterministic
  priority and a seeded tie-break select at most the declared capacity.
- Candidate positions are deterministically ordered, validated, and either accepted or
  rejected with a traceable reason. Exhaustion produces an explicit omitted/blocked result;
  the generator does not retry indefinitely or silently degrade a semantic placement such
  as `near_bench` into an unrelated random location.
- PRNG streams are derived independently from the world seed and stable purpose/object keys,
  for example `hash(garden_seed, generator_version, "plants", plant_id)`. Adding a lantern
  must not reshuffle every plant, and adding a plant must not rewrite animal temperament.
- Reproducibility is scoped to the same generator/schema version, catalog, seed, author
  program, and inputs. A generator change requires a version bump and an explicit
  migration/legacy-regeneration policy.

**What "procedural" means concretely for each element type:**

- **Plant generators** take `(seed, generator_version, position, species, growth state)` and
  return one persistent canonical topology plus named presentation states. The generator uses
  constrained species parameters (height ranges, branch tiers/counts, attachment zones,
  angles, canopy envelope and density). Two gardens with different seeds must produce visibly
  different legal arrangements; the same complete generation input reproduces the same
  topology and placement.
- **Fixture-room generation** selects only atlas-authored legal variants and persists the
  choices before projection. The seeded water-room axes are pond radius/loop silhouette,
  stepping-stone side (left or right), stone size/count, and a bounded bench position above
  and facing the pond; planter variation selects an authored blossom-count/state. The
  renderer may animate the selected pond's water state but may not synthesize a new bank,
  stone, bench anchor, or planter drawing. Each axis has its own derived PRNG stream so one
  change does not reshuffle the other room relationships.
- **Ambient presentation** takes `(world_id, projected scene, presentation frame)` and derives
  bounded one-cell trajectories without persistence.
- **Weather presentation** takes projected weather/season and semantic surfaces. Any lasting
  world change is reducer state; disposable flakes, drops, and caps are not persisted.

**Extending the garden with new animations:** To add a new animation type:
1. Prototype it as a standalone curses script in `ascii-animations/` to find the visual language.
2. Define its procedural parameters (what varies, what's fixed, what ranges).
3. Decide explicitly whether it is canonical world state or disposable presentation.
4. Canonical features enter the world/reducer/projection first; disposable features consume
   projection only and register in the relevant renderer portability profile.

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

#### 7.3.1 Canonical layout algorithm

Layout is world generation, not responsive renderer packing. It operates in canonical world
coordinates before either renderer runs.

1. Resolve authored room regions, reserved visibility areas, terrain/surface tags, safe
   walkable corridors, and connected path/water masks.
2. Materialize required room dependencies transactionally. For example, a water-garden room
   may require pond → bridge → water lily; failure of a required predecessor blocks its
   dependants and reports the room incomplete.
3. For each remaining pass, derive a purpose-specific PRNG stream and deterministically
   shuffle the bounded candidate set.
4. Validate hard rules first: region/surface, dependency, footprint, clearance, path
   reachability, attachment, exclusion group and author reservation.
5. Score valid candidates for composition goals such as room cohesion, silhouette
   separation, fixture affinity and intentional negative space. Seeded variation breaks
   equivalent scores; it does not replace the score or legality checks.
6. Commit the accepted candidate and update occupancy/affordance indices. If none is valid,
   emit a stable omission with rejection reasons. Required omissions block export or initial
   world acceptance.

The renderer may apply a bounded, reversible display transform for a viewport, but it cannot
change the canonical placement, relationships, occupancy, or hit identity.

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

### 7.5 Time of day and sky

Derived from system time or `--time day/dusk/night`:
- **Day**: Default palette, full color.
- **Dusk/Evening**: Palette warms (amber sky gradient), fireflies spawn, moon not yet visible.
- **Night**: Dark sky gradient, location/time-aware bright stars and moon when a real sky mode is active, with bounded one-cell fireflies where seasonally appropriate. The renderer never invents an ambient bird that could be mistaken for a relationship animal. A clearly labeled storybook fallback is available without location permission. See §7.8.9.

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

**Trigger:** Derived by the canonical civil clock from calendar month. Transitions happen on
the first observed visit in the new season range. Existing world objects, positions, growth,
and persistence remain intact; the new projected scene changes palette, weather, and eligible
routines without re-seeding the Garden.

**State machine:**
```
     Dec–Feb          Mar–May          Jun–Aug          Sep–Nov
winter ──────► spring ──────► summer ──────► autumn ──────► winter
         Jan 1           Mar 1           Jun 1           Sep 1
```

**Visual signature per season:**

| State | Sky | Plants | Weather | Creatures |
|-------|-----|--------|---------|-----------|
| spring | Cream (#f9f8f5) | Flowers dominant, bright greens | Light rain (`|`) | Butterflies |
| summer | Cream | Full palette | Calm | Butterflies, fireflies (evening/night) |
| autumn | Cream → warming | Yellows/reds/browns, dead trees | Heavy rain, falling leaves | Fewer butterflies |
| winter | Cream → cooler | Conifers, bare oaks | Snow accumulation | One-cell glints; no butterflies |

**User flow (season):**
```
[Visit page] → derive season from date
    → canonical clock/reducer projects scene season and weather
    → renderer chooses palette and plant silhouettes from projected scene/object facts
    → disposable weather and one-cell ambience use the same projected scene/surfaces
    → no season, plant, creature, or collision state is written by the renderer
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
| night | #0b0e16 / #13181e (near-black) | Catalog projection or labeled fallback | Yes, from selected sky clock | No | No |

**Moon phases (night only):**
The current eight-glyph vocabulary remains available, but phase and horizon placement come from the selected `reader_live`, `author_fixed`, `author_clock`, or `story_event` sky clock (§7.8.9), using the same trusted astronomy implementation as star projection. A date-division shortcut is prototype evidence only and cannot ship as the accuracy owner.
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
    → if night: set dark sky gradient, project selected sky, place moon glyph
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
[Each presentation frame] → consume projected scene weather + semantic object surfaces
    → derive bounded deterministic particle identities/trajectories
    → draw rain/snow/leaves without overwriting projected object art
    → clear disposable particles when paused/reduced-motion; persist nothing
```

---

#### 7.7.4 Animal trust subsystem

The deterministic hybrid animal AI, varied interactions, personality, memory, routines,
and non-punitive bonding rules in §7.8.7 are the authoritative contract.

**States:** `absent` | tier 0 (stranger) | tier 1 (familiar) | tier 2 (bonded) | tier 3 (full bond)

`absent` = no authored animal has arrived. Tier 0–3 is projected from canonical
`bond_points` plus interaction diversity.

**Thresholds:** tier 1 at 8 points; tier 2 at 20 points with at least two interaction
types; tier 3 at 40 points with all three interaction types (`observe`, `feed`, `play`).
Repeated same-session actions have diminishing gain and never punish absence.

**State machine:**
```
absent ──[authored arrival]──► tier 0 (stranger)
  tier 0 ──[8 points]──► tier 1 (familiar)
  tier 1 ──[20 points + 2 interaction types]──► tier 2 (bonded)
  tier 2 ──[40 points + observe/feed/play]──► tier 3 (full bond)
```
Bond points, interaction counts, memories, needs, intent, and tier persist in canonical
world state in both terminal and HTML.

**Visual signature per tier (all animals share the pattern; art varies):**

| Tier | Position | Behavior | User cue |
|------|----------|----------|----------|
| 0 | Canonical projected position | Safety/routine intent families; stranger tier mark | HUD may describe a stray animal |
| 1 | Canonical projected position | Familiar routines and tier-1 mark | Named exact-target actions |
| 2 | Canonical projected position | Broader social/play repertoire and tier-2 mark | Named exact-target actions |
| 3 | Canonical projected position/choreography | Full repertoire, authored delivery eligible, tier-3 mark | Bonded delivery/choreography may activate |

**Feed interaction (`f` key):**
- Guard: authenticated + an exact focused/authored canonical animal target + bond tier < 3
- Effect: dispatch `feed` with that canonical object ID; the world reducer updates bond points,
  interaction counts, tier, memories, and persistence before emitting a new projection
- Visual response: bounded species-aware feedback is attached to the same accepted canonical
  object ID; an ambiguous multi-animal generic action fails closed

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
    → authenticated author program materializes the relationship-animal roster
    → canonical world projection supplies exact ID, species, tier, intent, and actions
    → renderer consumes that projection without mutable animal state
[f key pressed] → resolve the focused or uniquely authored canonical animal
    → dispatch semantic `feed` with its exact object ID
    → reducer updates bond state and persistence → project → render
    → HUD and delivery choreography consume the new projected tier
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

**Trigger:** The canonical author program/milestone conditions for completion are satisfied
after recipient-visible letter and gift events.

**State machine:**
```
normal ──[all messages read + all gifts seen]──► post-complete (permanent)
```
Completion persists as canonical milestone/program receipts in the same authenticated
world state as every other Garden change.

**Visual signature (post-complete):**
- Authored memorial/rose entities and world changes appear through canonical projection.
- A bonded tier-3 animal may perform authored delivery or completion choreography.
- The renderer invents no generic perch bird or local completion entity.

**User flow (post-completion):**
```
[After reading a letter] → check: all read? all gifts seen?
    → if yes: record the canonical completion milestone/program occurrence
    → reducer persists it and projects the resulting world changes
    → renderer consumes only the projected rose/animal/choreography state
```

---

#### 7.7.7 State composition table

At any moment the presentation is derived from canonical scene state, projected animal bond
tiers, and canonical milestone/program state. Weather and gift changes are deterministic world
outputs, not renderer-local variables.

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
- Any time + any: only canonical projected animals may use multi-cell animal art; the renderer does not invent ambient birds

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

### 7.8 Canonical Garden Contract: Recipient Nurturing, Standalone Sandbox, and Author Direction

This section is the canonical release contract created from the 2026-07-21 research pass. It supersedes narrower prototype claims elsewhere in §6–§7 when they conflict. The research sources establish interaction, representation, scheduling, accessibility, simulation, and privacy constraints; the concrete counts and feature minimums below are LateLetter product decisions.

The three agency contracts are distinct even though they share one world model:

- **Bundle recipient:** nurtures existing plants and animals through watering, plant
  interaction and animal interaction. No placement, movement or rotation controls exist.
- **Standalone sandbox:** may additionally place/move/undo recipient-owned fixtures and
  plants because there is no author-directed memorial composition to preserve.
- **Author:** composes the opening garden and schedules later changes through the authoring
  surface and encrypted program. Authoring controls never appear in the recipient viewer.

#### 7.8.1 One world model, two renderers

The garden has one authoritative, deterministic world model:

```text
author program + garden clock + recipient actions + stable seeds
    → event evaluator
    → world state / scene graph
    → browser renderer + browser input adapter
    → terminal renderer + terminal input adapter
```

- Every plant, organ, animal, fixture, collectible, authored event, sky object, hotspot, and camera layer has a stable ID and canonical state.
- World coordinates, anchors, depth, collision, occlusion, affordances, and interaction hotspots live in the world model or versioned atlas, never only in browser DOM nodes or terminal render cells.
- Renderers may interpolate, substitute glyphs, quantize positions, and select a supported atlas profile. They may not own growth, rewards, bonding, event eligibility, or object placement.
- Input adapters dispatch semantic commands into the same command handler. They may not maintain modality-specific gameplay state.
- An authored animal scene acquires an explicit choreography lock from the animal controller, completes idempotently, and releases it back to normal AI. The old AI path must yield; dual ownership is forbidden.
- Given the same schema versions, seeds, elapsed effective time, prior state, and command sequence, browser and terminal produce the same semantic state and event trace even when the displayed glyphs differ.

#### 7.8.2 Nurturing loops and humane idle progression

Standalone mode and the bundle recipient experience must provide three useful session depths
without requiring a due letter. The verbs differ only where the agency split above says so:

| Session | Target duration | Required agency |
|---|---:|---|
| Glance | 10–20 seconds | Notice weather/sky, a plant change, animal behavior, or a new discovery; inspect at least one thing |
| Tend | About 2 minutes | Perform one care action, interact with an animal, and collect or journal one observation |
| Dwell | 10+ minutes | Tend multiple plants, follow an animal routine, review collections, or pan through the garden; standalone may additionally arrange recipient-owned objects |

The core loop is `notice → choose a gentle action → see a persistent response → collect/arrange/remember → leave freely`.

Required systems:

- **Plant care:** the bundle recipient may observe, water and interact with an existing plant,
  including author-permitted pruning/training, and allow seasonal rest. Standalone may also
  transplant/place recipient-owned plants. Tending changes growth topology, bloom timing,
  visitor attraction, collectible yield, or authored-event eligibility; it cannot be a
  particle-only button.
- **Spatial expression:** author mode and standalone sandbox may place, move, rotate where
  supported, and undo owned fixtures/plants. Dragging is optional convenience, never the sole
  placement method. The bundle recipient has no placement/move/rotate action or hidden
  production control.
- **Collections:** at least four families—plant species/phenotypes, seasonal natural finds, animal traces/mementos, and authored keepsakes. First discovery automatically enters the journal with semantic name, source, date/season, and accessible description.
- **Observation:** benches, clocks, sky, weather, ponds, and animal routines create non-resource interactions such as sit, watch, listen/read description, or wait for a short vignette.
- **Bounded offline progress:** return processing computes aggregate deterministic milestones instead of replaying missed ticks. A welcome-back summary shows at most three notable changes and never blocks immediate play.

Humane-progression rules are non-negotiable:

- Plants do not die, animals do not become sick or permanently leave, bond does not decay, authored gifts do not expire, and absence cannot erase inventory or progress.
- There are no streaks, missed-day counts, countdown pressure, guilt copy, paid random rewards, hidden narrative odds, or punitive resource decay.
- Repetition has diminishing *bonding* value within a session so feeding cannot brute-force attachment, but the repeated action remains available for play.
- Random narrative-required discoveries have a declared deterministic pity/fallback threshold.
- Clock rollback clamps elapsed time to zero; it never reverses growth, duplicates rewards, or locks the player out.
- A recipient may leave after one action without losing an opportunity.

#### 7.8.3 Picture-owned interaction; no visible action chrome

The shared world may continue to declare primary actions, opportunities and secondary
commands. Those records are gameplay data; they do **not** authorize a renderer to print
their labels as product UI.

**Operator decision, 2026-08-01.** The browser Garden is the picture. It must not paint
buttons, cards, hover instructions, object names, object lists, spawned-opportunity labels,
or a “More actions” sheet on or beside the scene. Review and diagnostic query parameters do
not relax this rule. The deployed Garden at `https://rikiworld.com/lateletter/` is the visual
baseline while the canonical renderer is rebuilt; a local review mode is not permission to
invent a second interaction surface.

- Click or tap on visible object ink performs that object's single safe primary action as
  declared by the canonical projection. The viewer dispatches the declaration verbatim and
  derives no gameplay behavior from the glyph, catalog id, name or kind.
- Hover may change the picture itself (for example, rustle or emphasis) but may not reveal a
  textual instruction, tooltip, card or label.
- Browser keyboard may move canonical focus with the existing spatial/object navigation and
  Enter may perform the focused object's declared primary action. A physical key is not an
  acceptable hidden route to a browser-only menu.
- Opportunities and secondary actions remain canonical world capabilities, but the browser
  does not expose them until the operator approves a picture-native, non-label interaction
  language. The rejected opportunity-card, object-list and action-sheet model must not be
  retained behind a gate or as unreachable dead code.
- Terminal commands may remain textual because the terminal is itself a textual control
  surface. That does not license equivalent labels over the browser picture.
- Author/diagnostic controls remain outside the product Garden, locally gated, and absent
  from recipient mode.

The prior §7.8.3.1–§7.8.3.3 contract—direct primary plus beside-object opportunity controls
plus an overflow action sheet—is withdrawn. Its implementation was visually rejected after
live comparison with the deployed Garden. Browser keyboard and screen-reader parity for
secondary actions is therefore **OPEN**, not satisfied by reinstating the rejected labels.

#### 7.8.4 Hybrid world composition and content inventory

The world combines procedural vegetation with authored atlas fixtures in one scene graph. The ship-blocking minimum is:

- **Terrain:** soil, grass, long grass, paths, water, mud, snow, fallen leaves, and shadows.
- **Procedural vegetation:** at least 12 distinct grammars across trees, shrubs, vines, grasses, herbs, flowers, and aquatic plants.
- **Functional fixtures:** bench, connected fence/gate, clock or sundial, trellis, birdbath, lantern, pond, mailbox or memory shrine, stepping-stone/path set, bridge, planter, and table/chair set.
- **Supporting fixtures:** well, arbor/pergola, wind chime, shed edge, tool rack, watering can, compost, basket, sign, and memorial stone may be included in the same atlas and are required before calling the catalog complete.
- **Connected tiles:** all 16 orthogonal adjacency cases for fences, hedges, paths, pond edges, and walls; gate/bridge overlays preserve collision and connectivity.
- **Ambience:** water ripples, smoke, lamp glow, cloud shadows, petals, leaves, snow, rain impacts, fireflies, moths, and birds.

Each required fixture has at least one direct interaction and one systemic or narrative affordance:

| Fixture | Direct interaction | Affordance examples |
|---|---|---|
| Bench | Sit / observe | Calm vignette; animal may rest nearby; author socket under/beside seat |
| Fence / gate | Open, close, inspect | Route/habitat boundary; animal perch/patrol; vine support |
| Clock / sundial | Inspect time | Shows garden/story time; may anchor an authored beat |
| Trellis | Train plant | Changes vine topology and bloom surface |
| Birdbath | Refill / observe | Drink/bathe affordance; raises bird behavior eligibility |
| Lantern | Light / extinguish | Evening behavior and moth affordance; never changes real celestial positions |
| Pond | Observe / tend | Ripples, aquatic plants, water visitors, seasonal freeze |
| Mailbox / shrine | Open / examine | Authored keepsakes, inscriptions, and memory discovery |

Fixture placement cannot trap animals, hide required actions, break connected paths, or make collectibles unreachable. Undo and reset-to-safe-layout are mandatory.

Presentation-native planting and ground cover may surround canonical objects but may not
overpaint or visually crowd their final composed ink. The exclusion room is derived from the
canonical object's post-layout screen rectangle; it may cull a disposable backdrop candidate,
but it may never move the canonical object or become a second layout authority. Authored
connected rooms such as pond plus stepping stones may waive the extra padding so their edges
meet, while direct cell overlap remains forbidden.

An exact operator-authored picture may declare semantic part roles (for example bloom, stem
and vessel) for palette resolution. A picture declared sealed replaces renderer-local topology
and centre-glyph decoration: the renderer may colour the declared parts but may not infer or
paint additional organs over the approved bytes.

**Catalog completeness is not scene composition (operator decision, 2026-07-31).** The lists
above say what the product must be able to draw. They do not say what a new garden opens
with, and the two must not be conflated: a scene that shows everything the catalog can do is
a showroom, not a place someone lives.

The **default starter scene is exactly six fixtures** — pond, stepping stones, mailbox,
bench, lantern, planter — held in `STARTER_FIXTURES` in both implementations. The pond,
stepping stones and bench form one water/sitting room: stones approach the pond from one
side and visually meet its bank, the bench sits generally above it, and the pond's sparse
interior ripples oscillate laterally by a perceptible distance at the product lattice and
cadence. The street lantern belongs to the far transition
band near that room, rather than sharing the pond's near surface.
Those relationships are canonical generator data, never renderer packing. An accepted fixture
drawing is an approved **catalog asset**, available to authored programs, progression, and
later compositions; acceptance never obliges it to appear at the start.

Everything under `REVIEW_PENDING_*` — unaccepted starter plants, the cat, the starter collectible —
stays **absent from the default scene** until each drawing is separately accepted under
§7.10. Composition arguments must be made against the six, not against every drawing that
has been approved.

#### 7.8.5 Stable procedural plant growth

Each plant is generated once into a persistent rooted topology graph. Every organ stores `node_id`, `parent_id`, kind, birth time, maturity time, final direction/length, glyph/style family, and optional bloom/fruit state.

- The topology is one rooted, connected, acyclic support graph. Every non-root organ reaches
  the root through its parent chain. Trees require an explicit main trunk/leader axis;
  arbitrary attachment to any earlier organ is not a species model.
- Species grammars define invariant form before seeded variation: trunk/stem axis, attachment
  zones, branch tier/count ranges, legal angles/directions, taper, crown envelope, and
  leaf/flower support rules. The seed chooses values inside those bounds.
- Willow terminal branches must be able to turn downward after outward/upward attachment;
  pine requires a central leader with lower branches wider than upper branches; oak begins
  major branching above its lower trunk and maintains a broad crown. A glyph-family label
  alone does not satisfy geometry.
- Generated topology must pass connectivity, root support, species silhouette, bounds,
  collision, growth-subset and renderer-parity validators before it is materialized.
- Growth reveals and interpolates the same topology. It does not rerun a random grammar at each stage; existing branches cannot teleport, change parents, or change root cells.
- Use parametric/stochastic L-systems for flowers, vines, grasses, and herbs; space-colonization skeletons for shrubs and trees; and hand-authored blueprints for narratively important plants. All implement the same age/growth interface.
- Every species has at least: `seed`, `germination`, `sprout`, `juvenile`, `mature`, `flowering_or_fruiting`, and `dormant` representations. Reduced-motion/static mode must communicate every stage.
- Stable seed derivation is versioned: `hash(bundle_id, plant_id, species_id, generator_version)`. Topology, leaves, flowering, ambient sway, and collectible drops use separate PRNG streams.
- `Math.random()` or any platform-selected RNG is forbidden for canonical simulation. A specified cross-language PRNG and seed derivation are part of the bundle/runtime version contract.
- Growth respects fixture exclusion masks, walkable paths, plant spacing, authored visibility reservations, and placement regions.
- Author controls include species/blueprint, seed override, planting time, growth curve, bloom/fruit windows, dormancy, exact placement or region, fixture affinity, pruning/revival beats, and topology lock.
- Recipient actions may shape a plant within author-declared bounds. For example, training a vine to a trellis changes later topology while preserving the plant's identity.

#### 7.8.6 Collectibles and journal

Every collectible has a stable ID, family, provenance (`procedural`, `recipient-grown`, `animal-given`, or `author-authored`), eligibility rule, world asset, inventory asset, semantic label, accessible description, and ASCII fallback.

- Standard seasonal finds recur on a declared cycle or have a catch-up route; changing the system clock is never required for completion.
- Authored keepsakes wait indefinitely after eligibility and can never be consumed, replaced, or overwritten by procedural duplicates.
- Duplicate standard finds may unlock art variants, decoration, or observations but may not gate core narrative behind high-volume grinding.
- The journal distinguishes observed, collected, authored, and still-hinted entries without exposing encrypted content before authentication.
- Animal traces include species-specific footprints, feathers/fur, favorite-place marks, gifts, and unlocked behavior observations—not generic currency drops.

#### 7.8.7 Animal AI and bonding

Release animals use a deterministic hybrid controller, not generative runtime AI and not feed-count-only progression:

1. High-level state machine: `absent`, `arriving`, `awake`, `resting`, `sleeping`, `authored_scene`.
2. Behavior-tree priority: safety/interruption → authored choreography → relationship response → routine → free roam.
3. A utility scorer chooses among valid routine/free-roam behaviors.
4. The animation controller communicates `orient/anticipate → perform → recover` for every action.

Persistent blackboard fields:

- bond points and tier; familiarity per interaction type; recent episodic memories (`kind`, target, timestamp, valence, salience);
- learned favorite fixtures, plants, foods, places, and play styles;
- personality: boldness, sociability, curiosity, playfulness, patience, routine strength, food motivation, and day/night preference;
- last visit/interaction, absence duration, interaction variety, authored preferences/prohibitions, routine windows, and milestone receipts.

Seeded identity and relationship history are separate:

- `AnimalIdentity` is immutable after creation: species, initial temperament weights,
  routine bias, favorite affordance categories, curiosity radius and presentation variants.
  It derives from an animal-specific PRNG stream, not the mutable relationship score.
- `AnimalRelationship` is produced by recipient experience: bond tier, per-interaction
  familiarity, shared rituals, learned favorites, and bounded episodic memories such as
  first meeting, recent interaction and a few salient/favorite events.
- `AuthorDirection` may name the animal, constrain personality/routines, reserve milestone
  scenes and add encrypted memories. It does not pre-script every free-roam choice or replace
  recipient-created relationship history.
- The seed determines who the animal initially is; it does not predetermine whether or how
  the recipient forms a relationship.

Session blackboard fields:

- energy, curiosity, social/play/rest appetite, current intent/target/path/pose, cooldowns, interruptions, nearby affordances, weather, season, time, and recipient focus.

Utility combines need pressure, personality, bond, environmental affordance, novelty,
cooldown, remembered preference, authored bias, and small seeded tie-breaking noise.
Candidate actions are filtered for legality before scoring. Hysteresis and minimum dwell
times prevent rapid behavior oscillation. Fixtures advertise affordances; for example, a
bench offers rest-near-recipient, a birdbath offers drink/bathe, a fence offers perch/patrol,
and tall plants offer hide/sniff.

Bonding rules:

- Bond grows through varied, spaced interactions: feed, play, observe, sit nearby, tend a favored plant/fixture, respond to an initiated behavior, and participate in authored scenes.
- Repeating one action has diminishing bond value per session. Feeding alone cannot reach full bond.
- Bond never decreases because of absence. Offline needs reconcile to a safe baseline.
- Animals never die, become sick, shame the recipient, permanently leave, or remove gifts because of neglect.
- An animal may decline or delay interaction but visibly communicates intent; `inspect animal` explains the readable state without exposing numeric meters.
- Return greetings are positive and species/personality-specific.
- Relationship progress is communicated primarily through changed behavior—approach
  distance, initiation, favorite-place use, learned rituals and recognition—not a
  recipient-facing maintenance meter.
- High-frequency repetition is never the optimal relationship strategy. Bond gain is bounded
  by novelty, preference match, contextual relevance and per-action cooldown.

| Bond tier | Minimum observable behavior contract |
|---|---|
| Stranger | Watches from safety, startles, explores edges, avoids direct approach |
| Familiar | Approaches after a pause, accepts care, and uses at least one nearby fixture |
| Bonded | Initiates play, follows briefly, rests nearby, and recalls preferred interactions |
| Full bond | Greets on return, brings authored/earned discoveries, seeks shared spaces, and performs a species-specific settled/delivery behavior |

Each of bird, cat, rabbit, and turtle requires species-specific locomotion, resting, play/care response, weather response, fixture affinities, gift behavior, and all four tier signatures. Relabeling shared art does not count.

#### 7.8.8 Parallax, camera, and scene continuity

The browser and terminal share a continuous canonical camera in world space. Presentation layers declare stable depth factors; recommended starting values are stars `0.02`, distant clouds/hills `0.10–0.25`, far fence/buildings `0.45–0.65`, interactive world `1.0`, and foreground foliage `1.10–1.25`.

- Browser rendering uses one timestamp-driven `requestAnimationFrame` loop and batched layer transforms. Refresh rate must not alter simulation speed.
- Terminal rendering quantizes camera offsets to cells, may use block/Braille phases for apparent subcell movement, damage-tracks changed cells, and must not clear/redraw the full screen every frame.
- The far terrain edge is one continuous Garden-authored contour aligned exactly with the sky→terrain colour boundary. A structural `---^/\\___...` sample from the Moon reference demonstrates continuity only and is not Garden grass art. Large legacy trees and selected far fixtures (the street lantern and, when present, trellis) root on that edge. Small legacy flowers, shrubs, grasses, mushrooms and ferns receive stable seeded depth coordinates across the receding terrain plane, excluding the far edge; they must not collapse into a single near row or be repacked as the camera moves.
- The composed frame owns one camera-projected terrain value containing the far edge, near edge, and span. Terrain ink, the CSS sky→terrain transition, visibility/culling, depth cohorts, cover bounds, and weather ground effects consume that value; no painter or viewer may retain a fixed viewport-row copy. Horizontal and vertical pan move the terrain and everything rooted in it through the same camera law at the layer's declared depth.
- Every plant, fixture, and other multi-cell drawable is a billboard/card with a stable full-frame footprint, a ground baseline, depth, and stable identity. All cards share one deterministic back-to-front order (`baseline`, then depth, then stable id); a renderer-local phase may not put every fixture above every plant. The full rectangle governs spacing and hit/layout clearance, while blank cells are transparent and only ink occludes. Lattice and measured-font painting implement the same transparency and order.
- Scenery wraps or has authored continuation; panning may not reveal blank/uninitialized columns.
- Presentation-native population membership and canonical visibility rooms are resolved in world/terrain space. Pan, drag, resize and parallax may change projection only; they may not add or remove scenery because two screen-space rectangles happen to cross.
- Presentation-native planting is admitted against a neutral, world-anchored projected card field with minimum card separation and a bounded regional cluster budget. The current camera/viewport may crop that stable population but never participates in deciding membership.
- Hit testing uses world coordinates and remains correct under pan, zoom/reflow, and different parallax offsets.
- Background-tab suspension pauses presentation only. On resume, canonical elapsed-time processing runs once without duplicating rewards or authored events.
- Reduced-motion mode freezes parallax, camera easing, weather travel, idle sway, and nonessential position animation while retaining immediate state changes, interactions, and discoveries.

#### 7.8.9 Astronomically plausible sky

The star layer uses a curated bright-star catalog with right ascension, declination, visual magnitude, optional color/name, catalog version, and license/provenance. A small naked-eye catalog such as the Bright Star Catalogue is appropriate; Gaia is an upstream authority, not a client payload.

Sky modes:

- `reader_live`: current reader time and opt-in rough location;
- `author_fixed`: authored date/time/location;
- `author_clock`: authored epoch and progression rate;
- `story_event`: sky changes only at authored beats;
- `storybook_fallback`: documented artistic sky when no real location is available.

Location modes are `reader_opt_in`, `reader_manual_region`, `author_location`, and `fictional`.

- Never request browser geolocation on load. Offer an explicit “use my rough location for the sky” action and explain the purpose.
- Request low accuracy with finite timeout/caching. Immediately quantize to a documented coarse grid (initial target: 1° latitude/longitude) and discard the raw result.
- Raw coordinates never enter a bundle, URL, analytics, logs, crash reports, or persistent storage. Persist the coarse region only after opt-in, with visible update/delete controls.
- Denial/offline fallback order: reader-selected city/region → author-specified location → storybook sky. Core play remains available in every case.
- At a low cadence (about once per minute), transform catalog RA/Dec to topocentric altitude/azimuth for the selected time/location, cull stars below the horizon, project visible stars to the sky layer, and map magnitude to tested glyph density/brightness.
- Celestial positions are not random parallax. Only clouds, haze, fireflies, and artistic twinkle are cosmetic.
- Non-live authored skies are labeled as authored/story time so they are not represented as the recipient's actual sky.
- Reduced motion stops twinkle/parallax but does not alter which stars are visible.

#### 7.8.10 Author narrative and temporal control

The simple `garden_gifts` list is migrated into the encrypted `garden_program` envelope shown in §3. After unlock, `garden_program.ciphertext` decrypts to this canonical inner payload:

```json
{
  "version": 1,
  "author_timezone": "America/New_York",
  "variables": {},
  "entities": [],
  "animals": [],
  "events": [
    {
      "id": "stable-uuid",
      "conditions": {
        "all": [
          {"fact": "letter.read", "op": "contains", "ref": "letter-id"},
          {"fact": "visit.total", "op": ">=", "value": 3}
        ]
      },
      "schedule": {
        "start": "2028-06-15T19:00:00",
        "timezone": "America/New_York",
        "recurrence": null,
        "exceptions": [],
        "missed": "deliver_on_next_visit"
      },
      "occurrence": "once",
      "priority": 100,
      "exclusive_group": null,
      "cooldown": null,
      "actions": []
    }
  ]
}
```

Supported condition facts include absolute/local time, date range, season, recurrence, visit count/nth visit, return after absence, session duration, letter due/read, gift revealed/examined, prior event completion, animal arrival/bond/interaction/memory, plant growth/bloom, fixture presence, and seeded bounded probability. Conditions support `all`, `any`, and `not`.

Supported actions include:

- unlock/present a letter;
- reveal, place, move, transform, or retire a gift, plant, fixture, or collectible;
- direct animal arrival/departure, authored behavior, routine, destination, delivery, or gift presentation;
- plant/grow/bloom/dormancy/prune/revive within declared bounds;
- apply bounded scene direction for weather, palette, story time, sky mode, ambience, and population;
- show an authored nudge, inscription, memory, caption, or observation;
- set/increment a variable and complete an event.

Execution semantics:

- Stable event/occurrence IDs and idempotent actions.
- Deterministic run-to-completion evaluation for identical state/time/input.
- Explicit priority and exclusive groups resolve simultaneous eligibility.
- Missed policy is `skip`, `deliver_on_next_visit`, or `summarize_then_current`.
- Recurrence declares `count`, `until`, or an intentional unbounded flag.
- Offline catch-up is bounded and summarized; it never replays every missed minute.
- No arbitrary JavaScript, Python, HTML, ANSI controls, remote URLs, or unknown commands in authored data.
- All narrative-bearing fields—including animal names, inscriptions, captions, event labels, and private choreography—remain encrypted. Plaintext exposes only the minimum unlock envelope.

The authoring experience is a fatigue-aware timeline/sequence editor, not raw JSON:

- beat cards pair plain-language “when/if” conditions with “what happens” actions;
- separate tracks for letters, animals, plants, fixtures, gifts, sky/season, and revisit beats;
- calendar, visit-count, and dependency views; reorder/priority controls; autosave and resumability;
- direct animal personality, routine, favorite-place, prohibited-behavior, gift, and milestone controls;
- scene preview at arbitrary date/time, visit count, read state, bond tier, season, location mode, and absence duration;
- a scrubbable trace explains why each event is eligible/blocked and shows before/after state;
- fast-forward covers days, years, seasons, daylight-saving changes, clock rollback, and long absence;
- preview and recipient runtime use the same evaluator.

Validation blocks export for missing references/catalog IDs, unreachable events, cycles, contradictory conditions, invalid ranges, unresolved equal-priority exclusivity, unbounded accidental recurrence, impossible letter dependencies, placement collisions, private strings in plaintext, unreachable animal/gift interactions, or branches that permanently block later authored content.

#### 7.8.11 Versioned Unicode/ASCII atlas

“Full Unicode atlas” means a complete manifest of every supported semantic tile and frame—not arbitrary Unicode assumed to be a stable terminal cell.

Rendering profiles:

- `ascii-safe`: printable ASCII only; mandatory universal fallback;
- `unicode-cell-safe`: curated grapheme clusters proven to occupy declared columns in the supported terminal matrix;
- `browser-font-locked`: broader curated Unicode rendered with a bundled/tested font;
- `browser-rich`: emoji/ZWJ/color-font decoration only, never collision-bearing geometry.

The atlas compiler normalizes NFC, segments extended grapheme clusters, measures declared cell width per profile, rejects illegal controls/bidi/private-use/malformed clusters and inconsistent frame boxes, pins its Unicode data version, and emits grapheme-cell arrays instead of indexing strings by code unit.

Default geometry excludes standalone combining marks, default-ignorable characters, unpaired surrogates, controls/ESC/bidi controls, emoji flags/skin tones/ZWJ sequences/VS16 color emoji, and East-Asian-Ambiguous characters in terminal-safe assets unless separate width-1/width-2 layouts exist.

Every asset manifest includes:

```json
{
  "id": "fixture.bench.oak.v1",
  "kind": "fixture",
  "profiles": {"browser": "browser-font-locked", "terminal": "unicode-cell-safe"},
  "cell_box": [7, 3],
  "anchor": [3, 2],
  "layers": ["shadow", "body", "effects", "interaction"],
  "states": ["idle", "occupied", "gift_present", "snow"],
  "animations": {"idle": [{"frame": 0, "ticks": 12}]},
  "collision_mask": [],
  "occlusion_mask": [],
  "hotspots": [{"id": "sit", "label": "Sit on the bench", "action": "sit"}],
  "reduced_motion_frame": "idle:0",
  "ascii_fallback": "fixture.bench.ascii.v1",
  "author_sockets": ["seat", "under_bench", "beside_left"],
  "tags": ["bench", "author_placeable"]
}
```

Art, collision, occlusion, and interaction are separate authoritative data. Cosmetic animation cannot silently move collision/hotspots. State-changing animation updates masks at one declared transition tick.

Approved creative techniques:

- glyph substitution for sway, growth, clock hands, animal poses, gates, flowers, and water;
- Box Drawing for connected stems/fences/trellises/fixtures;
- Block Elements, quadrants, Braille, and tested Symbols for Legacy Computing for subcell growth, stars, pollen, insects, rain, fireflies, and particles;
- `░▒▓` density cycles for glow, fog, shadow, rain, and water;
- palette-role cycles for dawn/dusk/seasons/lantern warmth;
- ordered dithering, alternating subcell masks, and layer-local animation;
- seeded assembly of authored stem, branch, leaf, blossom, scar, fruit, pot, and soil modules.

All frames have fixed tick durations and stable footprints. The same semantic state selects the same named frame in both runtimes, while each renderer may choose its supported profile/fallback.

#### 7.8.12 Accessibility, motion, privacy, and safety

- Honor `prefers-reduced-motion` and provide an explicit persistent pause/reduced-motion toggle. All automatic motion lasting over five seconds can be paused/stopped/hidden.
- Reduced motion freezes parallax, weather drift, idle sway, camera easing, and particle travel; it preserves immediate state changes and readable static poses.
- The browser's replacement nonvisual scene description is still open after the visible object-list model was withdrawn in §7.8.3. It must not be implemented as labels, cards or a list painted over the Garden.
- No state relies on color, animation, or glyph shape alone. At 200% zoom and 320 CSS-pixel width, all actions remain reachable; the browser may switch to a focused-object/list view.
- No essential action requires reaction timing. Pointer gestures and drag operations have single-pointer/button alternatives.
- Author data cannot inject executable content or terminal escapes. Unknown atlas assets/actions resolve to safe placeholders/errors without corrupting state.
- Geolocation is optional, purpose-limited, coarse, local-only, revocable, and unnecessary for core play.
- Authored content and relationships are not monetized. No mechanic may exploit grief, imply the deceased is disappointed, or make access contingent on compulsive engagement.

#### 7.8.13 Release acceptance gates

The garden is not “full,” “parity,” or “production-ready” until all gates pass against a normal sealed production bundle—not only a dev fixture:

1. **Production reachability:** Published synthetic bundle contains at least one animal arc, authored plant change, fixture reveal, collectible/keepsake, and multi-condition event. A recipient completes them from the visible production UI.
2. **Input parity:** Recipient plant/water/interact, animal/feed/play, inspect, collect,
   journal, pan, and pause pass through touch, mouse, keyboard, and terminal with identical
   state transitions. Author/standalone placement/move/rotate/undo pass separately; recipient
   surfaces prove those commands absent.
3. **Standalone value:** Human observation confirms useful glance, tend, and dwell sessions with no bundle and no letter due.
4. **Plant stability:** For 100 fixed seeds, browser/terminal topology hashes and stable IDs
   match; visible nodes at earlier age are a subset of later age except explicit authored
   pruning, dormancy or nonfatal revival beats.
5. **Layout safety:** Across 1,000 generated gardens, plants respect fixture masks/paths and every interactable remains reachable. All 16 connected-tile masks render correctly.
6. **Atlas portability:** Compiler rejects unsafe clusters/width drift; every enhanced asset has dimension-compatible ASCII and reduced-motion fallbacks; supported browser/terminal screenshot matrix has no tofu, overlap, or frame jitter.
7. **Animal behavior:** Four species show distinct four-tier repertoires; personality/needs/memory measurably affect choices; no rapid oscillation; seven-day and one-year absence cause no loss or shame.
8. **Author control:** The author tool expresses and previews “letter read → rabbit arrives → third revisit grows plant → bonded rabbit brings autumn gift” without editing JSON. Preview and runtime event traces match.
9. **Temporal correctness:** Simultaneous events, once-only idempotency, recurrence/DST, missed-event policy, year-long catch-up, and clock rollback pass deterministic tests.
10. **Parallax/performance:** Equal elapsed time yields equal positions at 60/120 Hz; ten-minute pans reveal no blank cells or broken hit tests; reference browser stays under 16.7 ms p95 desktop / 33 ms p95 target mobile; terminal uses partial diffs after initial paint.
11. **Sky accuracy/privacy:** No geolocation call precedes user activation; raw coordinates never persist or leave the device; denial paths work; 12 hemisphere/latitude/date fixtures agree with a trusted Alt/Az implementation within 0.25° before screen quantization.
12. **Accessibility:** Full play works with keyboard, VoiceOver/NVDA object controls, reduced motion, no color, 200% zoom, and narrow mobile layout. All target-size and pause-motion checks pass.
13. **Absence/ethics:** Simulated 1/7/30/365-day absences lose nothing; no prohibited urgency/guilt language or expiring authored content appears.
14. **Human acceptance:** Direct observation signs off the standalone cozy loop, touch discoverability, all animal bond tiers, authored world arc, item discovery, letter delivery, and post-completion memorial. Proxy code/fixture evidence cannot substitute.

#### 7.8.14 Research basis

The local provenance and transfer notes for the 2026-07-30 seed/nurturing/animal pass are
archived in `tracked/LateLetterResearch/INDEX.txt`.

Mechanics and humane engagement:

- [Official Neko Atsume — How to Play](https://www.nekoatsume.com/sp/en/about.html)
- [Official Tamagotchi Uni instruction manual](https://tamagotchi-official.com/manual/toy/uni/manual_02/Uni_WEB_IS_EN.pdf)
- [Bandai Original Tamagotchi manual](https://www.bandai.com/amfile/file/download/file/3642/product/1309530/)
- [Viridi — official Steam listing](https://store.steampowered.com/app/375950/Viridi/)
- [The Garden Path — official Nintendo listing](https://www.nintendo.com/en-ca/store/products/the-garden-path-switch/)
- [Kinder World — official game description](https://www.playkinderworld.com/game)
- [Garden Life: A Cozy Simulator](https://www.nintendo.com/en-ca/store/products/garden-life-a-cozy-simulator-switch/)
- [Animal Crossing: New Horizons — Explore](https://animalcrossing.nintendo.com/new-horizons/explore/)
- [Cozy Grove calendar/campaign-time model](https://support.spryfox.com/hc/en-us/articles/1500005307201-How-do-campaign-days-and-time-in-general-work-Cozy-Grove)
- [Cozy Grove control mappings](https://support.spryfox.com/hc/en-us/articles/1500003989661-What-are-the-controls-Cozy-Grove)
- [GDC — Designing for Presence Without Intrusion](https://gdcvault.com/play/1035099/Thriving-Players-Summit-Designing-for)
- [FTC — Bringing Dark Patterns to Light](https://www.ftc.gov/news-events/news/press-releases/2022/09/ftc-report-shows-rise-sophisticated-dark-patterns-designed-trick-trap-consumers)

Authoring, time, and animal behavior:

- [Failbetter — Echo Bazaar Narrative Structures](https://www.failbettergames.com/news/echo-bazaar-narrative-structures-part-two)
- [ink writing guide](https://github.com/inkle/ink/blob/master/Documentation/WritingWithInk.md) and [Inky editor](https://github.com/inkle/inky)
- [W3C SCXML](https://www.w3.org/TR/scxml/) and [RFC 5545 calendar recurrence](https://www.ietf.org/rfc/rfc5545)
- [CMU — Believable Agents and Interactive Drama](https://www.cs.cmu.edu/Groups/oz/papers/CMU-CS-97-156.html)
- [Sony aibo FAQ](https://direct.sony.com/aibo-faq/)
- [Sony aibo personality development guide](https://helpguide.sony.net/aibo/ers1000/v1/en-us/contents/TP0001970096.html)
- [Nintendo Nintendogs](https://www.nintendo.com/en-gb/Games/Nintendo-DS/Nintendogs-Labrador-Friends-272057.html)
- [Nintendo Nintendogs + Cats instruction manual](https://assets.nintendo.eu/image/upload/v1635394807/NAL/Support/Nintendogs_Cats_manual.pdf)
- [Peridot traits/archetypes](https://nianticspatial.helpshift.com/hc/en/4-peridot/faq/697-traits-and-archetypes/) and [bond levels](https://nianticspatial.helpshift.com/hc/en/4-peridot/faq/688-dot-levels/?l=en&p=web)
- [Grand, Cliff and Malhotra — Creatures: Artificial Life Autonomous Software Agents for Home Entertainment](https://doi.org/10.1145/267658.267663)
- [Melson et al. — Children's Behavior toward and Understanding of Robotic and Living Dogs](https://eric.ed.gov/?id=EJ830357)
- [Matheus et al. — Long-Term Interactions with Social Robots](https://doi.org/10.1145/3729539)
- [Companion-robot absence pilot study](https://www.frontiersin.org/journals/computer-science/articles/10.3389/fcomp.2023.1129506/full)
- [Unreal Engine Behavior Trees](https://dev.epicgames.com/documentation/en-us/unreal-engine/behavior-trees-in-unreal-engine)
- [Game AI Pro — Utility Theory](https://www.gameaipro.com/)

Procedural growth, Unicode, rendering, and sky:

- [Minecraft Creator — World Generation Overview](https://learn.microsoft.com/en-us/minecraft/creator/documents/world-generation?view=minecraft-bedrock-stable)
- [Minecraft Creator — Features Taxonomy](https://learn.microsoft.com/en-us/minecraft/creator/documents/featurestaxonomy?view=minecraft-bedrock-stable)
- [Minecraft Creator — Tree Feature](https://learn.microsoft.com/en-us/minecraft/creator/reference/content/featuresreference/examples/features/minecraft_tree_feature?view=minecraft-bedrock-experimental)
- [Official Terraria Wiki — World generation](https://terraria.wiki.gg/wiki/World_generation)
- [Minecraft Wiki — Seed and generator-version behavior](https://minecraft.wiki/w/Seed_%28world_generation%29)
- [Algorithmic Botany — Modeling plant development with L-systems](https://algorithmicbotany.org/papers/modeling-plant-development-with-l-systems.html), [Animation of Plant Development](https://www.algorithmicbotany.org/papers/animdev.sig93.pdf), and [Space Colonization](https://algorithmicbotany.org/papers/colonization.egwnp2007.html)
- [Unicode UAX #29 — Grapheme Clusters](https://unicode.org/reports/tr29/), [UAX #11 — East Asian Width](https://www.unicode.org/reports/tr11/), [UTS #51 — Emoji](https://www.unicode.org/reports/tr51/), and [Unicode charts](https://www.unicode.org/charts/)
- [W3C CSS Fonts 4](https://www.w3.org/TR/css-fonts-4/) and [Pointer Events](https://www.w3.org/TR/pointerevents/)
- [MDN requestAnimationFrame](https://developer.mozilla.org/en-US/docs/Web/API/Window/requestAnimationFrame) and [prefers-reduced-motion](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/At-rules/%40media/prefers-reduced-motion)
- [W3C Geolocation](https://www.w3.org/TR/geolocation/)
- [VizieR Bright Star Catalogue](https://vizier.cfa.harvard.edu/viz-bin/VizieR?-source=V%2F50%2Fcatalog), [ESA Gaia DR3](https://www.cosmos.esa.int/web/gaia/dr3), and [Astronomy Engine](https://github.com/cosinekitty/astronomy)
- [WCAG 2.2](https://www.w3.org/TR/WCAG22/), including keyboard access, pointer gestures, target size, animation-from-interactions, and pause/stop/hide requirements

---

### 7.9 Presentation geometry — proportional measured layout

**Decision, 2026-07-30 (operator).** The Garden's browser presentation moves from a uniform
character cell grid to **proportional glyph placement measured through PreText**. This section
is the contract for that move. It amends §7.2 and §7.8.11 where they assume a uniform cell.

#### 7.9.1 Why the cell grid is the wrong substrate

Object art is to be derived from the existing ASCII and Shift_JIS art traditions rather than
invented ad hoc. Shift_JIS art — the 2channel/AA tradition — is not merely "ASCII with more
characters." Its entire technique depends on **proportional** metrics: glyphs of differing
advance widths are chosen so that strokes align sub-cell, which is what produces curves and
diagonals that a monospace grid cannot express. Rendering that art in a uniform cell destroys
the thing that makes it art.

The current renderer assumes uniform cells throughout: `cellWidth = 8`, `cellHeight = 15`,
viewport extent computed as `clientWidth / cellWidth`, and inverse hit testing performed as
`floor((clientX − rect.left) / cellWidth)`. Every one of those is a division by a constant.

#### 7.9.2 What the world model keeps

**World coordinates remain integer and unchanged.** This is the load-bearing constraint. The
canonical world continues to place objects at integer `Vec2` positions with integer footprints,
collision masks, and hotspots. Proportional geometry is a **presentation transform applied after
projection**, exactly as §7.2 requires. Nothing about this decision moves placement, collision,
hit identity, growth, or any other gameplay concern into a renderer.

Concretely, the ownership boundary does not move:

| Layer | Owns | Units |
|---|---|---|
| World / reducer | position, footprint, occupancy, hotspot identity | integer world cells |
| Projection | which objects, which art token, which state | integer world cells |
| **Presentation transform** | world cell → device pixels | **fractional px** |
| Renderer | glyph runs, colour, motion | fractional px |

**The world-to-pixel transform is affine and content-independent.** An object's pixel anchor is
`origin + world_coordinate × lattice_spacing`, where the lattice spacing is a property of the font
alone, derived once from a constant reference probe. No asset, no glyph, and no measured text
appears in that expression.

This is stated explicitly because the natural way to write a proportional renderer is the wrong
way: accumulating each object's position from the widths of the text drawn before it. Such a
renderer looks correct on its first screenshot and is wrong from then on. Widening one glyph inside
one object would shove every object to its right sideways; placement would stop being a property of
the world and become a side effect of drawing; collision would disagree with what the player sees;
and the same seed would compose differently under different fonts. Proportional measurement is
therefore **asset-local** — it lays out one asset's own rows relative to that asset's own anchor,
and one asset's glyphs can never move another asset.

#### 7.9.3 The measured layout contract

PreText's `measurement.js` already exports everything required, and it is already vendored,
same-origin, and offline:

- `getMeasureContext()` — an `OffscreenCanvas` 2D context, falling back to a DOM canvas.
- `getSegmentMetrics(seg, cache)` — advance width plus a `containsCJK` flag.
- `getSegmentGraphemeWidths(...)` — per-grapheme advance widths.
- `getSegmentGraphemePrefixWidths(...)` — **cumulative** prefix widths.
- `getEngineProfile()` — per-engine epsilon and CJK carry behaviour, so Safari and Chromium
  agree on line fitting.
- `analysis.js` additionally exports `isCJK`, `kinsokuStart`, `kinsokuEnd` — the East-Asian
  width knowledge the Shift_JIS lineage requires.

Rules:

1. **Rows stay discrete; columns become continuous.** Line height remains uniform, because AA
   art itself assumes uniform leading. Horizontal position becomes a measured px offset. A
   presentation row is therefore `(row_index, [glyph runs with measured x])`.
2. **Art is stored as strings, not character matrices.** An asset frame is a list of row
   strings. Its geometry is derived by measurement at load time, never hand-counted. Column
   counting is no longer a meaningful validation.
3. **Canonical hotspot rectangles own hit identity, and measured ink never does.** A pointer
   event is dispatched by transforming each projected object's integer hotspot into a px rectangle
   and testing containment. The projection is already the authority here — every object carries a
   hotspot (`projection.py`, `garden-world.mjs`), and the renderer already refuses an object that
   lacks one. Adopting proportional geometry changes only the units of that rectangle, never who
   owns it.

   Visible glyph extents are **not** an action target. Art is permitted to overhang its declared
   footprint (rule 5), so if ink decided what was clicked, redrawing a picture would silently
   change the game's affordances and an artist could invent an action target by accident.

   Dispatch order, which must be deterministic because the same tap on the same scene has to do
   the same thing on every machine:

   1. An object whose **unexpanded** hotspot contains the point wins outright. Accessibility
      expansion must never take a click from an object the player actually touched.
   2. Otherwise, among objects whose **expanded** target contains the point, the nearest centre
      wins.
   3. Ties break on `object_id` by code point.

   The WCAG 2.2 target minimum of 44 px is applied in px directly rather than converted to a cell
   count, and expansion is symmetric about the rectangle's own centre so a grown target still
   points at the same object.
4. **Prefix-width binary search is asset-local and advisory.** Within one asset row, the grapheme
   under a horizontal offset is found by binary-searching that row's cumulative prefix-width array
   — exact rather than approximate, and O(log n), replacing division by a uniform cell width,
   which is only correct when every glyph is the same width. Its offsets are measured from the
   row's own left edge, not from the screen, and its results serve painting, hover highlighting
   and glyph diagnostics. It never decides which object was clicked; rule 3 does.
5. **Declared footprints stay integer.** An asset declares its footprint in world cells for
   collision and occupancy; the presentation measures its actual px extent for painting only.
   Where the two disagree, **collision follows the declared cell footprint** — a picture may
   visually overhang, but it may never silently occupy a cell it did not declare.
6. **Measurement is cached per font and invalidated on resize or font load**, using PreText's
   existing `clearMeasurementCaches()`. Fonts must be loaded and ready before first measurement;
   a fallback-font measurement that is later re-measured against the real font would move every
   glyph. Because a cache is only valid under the font and scale it was built with, the safest
   expression of this rule is that a font change, resize or zoom constructs a new presentation
   transform rather than mutating one in place — which removes stale-cache bugs by construction
   instead of managing them.

#### 7.9.4 Atlas profile

§7.8.11's profile list gains a fifth entry:

- `browser-proportional`: measured proportional glyph placement, permitted to use the curated
  CJK box/line/shading repertoire of the Shift_JIS tradition. Assets in this profile declare
  **row strings and an integer cell footprint**, not a column count.

The existing four profiles are unchanged and remain cell-based. `ascii-safe` remains the
mandatory universal fallback, and the terminal renders it.

#### 7.9.5 Terminal parity under proportional presentation

The terminal cannot do proportional layout, and this contract does not ask it to. Parity is
therefore restated precisely, amending §7.8.13 gate 6:

- **Semantic parity is required and unchanged.** Same world state, same objects, same hotspot
  identities, same actions, same event trace, same accessible descriptions.
- **Pictorial parity is explicitly not required.** The browser may present a proportional
  picture where the terminal presents its `ascii-safe` cell equivalent. This was already true
  in principle — §7.2 permits renderers to "differ in disposable presentation detail" — and is
  now stated as the intended outcome rather than a tolerated divergence.
- Every `browser-proportional` asset **must** have an `ascii-safe` counterpart carrying the
  same semantic token and the same declared cell footprint. An asset with no fallback is
  rejected by the atlas compiler.

#### 7.9.6 Migration cost

The 2026-07-30 cost estimate is historical, not the current inventory. Atlas v2 now contains ten
multi-row fixture drawings with paired `ascii-safe` and `browser-proportional` profiles. Their
browser rows are painted by the product-wired PreText geometry from asset-local cumulative prefix
widths; non-asset scene decoration remains on the affine world lattice. Plants, animals,
collectibles and several effects still have renderer-local drawing owners, so they remain release
blockers until those owners are deleted after atlas migration. `web/garden-atlas-art.mjs` is a
generated runtime derivative of `atlas.v2.json`, and byte-exact regeneration is a build invariant.

---

### 7.10 Per-asset visual acceptance

**Requirement, 2026-07-30 (operator).** Every feature, fixture, plant, and animal must be
**individually accepted by the operator on sight**. This is a distinct gate from §7.8.13 gate 14
and from §6.9, both of which review composed scenes and emotional moments rather than assets.

#### 7.10.1 The rule

- Scene-level acceptance **does not** confer asset-level acceptance, and asset-level acceptance
  does not confer scene acceptance. They are independent gates and both are required.
- An asset the operator has not accepted may not be described using any acceptance or
  completion vocabulary in any document, commit message, or status report. Its accurate status
  is **drafted**.
- Machine checks — uniqueness, glyph legality, footprint conformance, no-tofu, contrast — are
  **admission criteria for review**, not substitutes for it. An asset that satisfies every
  automated check and has not been looked at is still `not_reviewed`. This is the same
  substitution error recorded throughout `docs/FAILURE_LOG.md`, applied at asset granularity.
- Review is per asset **per state that changes its silhouette**: growth stages for plants, pose
  families for animals, and functional states for fixtures (lantern lit or dark, gate open or
  shut). A state that reuses an accepted silhouette needs no separate review.

#### 7.10.2 Registry

Acceptance is recorded per asset in a tracked file, not in prose:

```json
{
  "asset_id": "plant.willow",
  "profile": "browser-proportional",
  "states_reviewed": ["juvenile", "mature"],
  "verdict": "accepted",
  "reviewed_at": "2026-08-01",
  "art_lineage": "ASCII — after the drooping-form conventions of terminal tree art",
  "capture": "docs/visual-review/2026-08-01/plant-willow-mature.png"
}
```

`verdict` is one of `accepted`, `rejected`, or `not_reviewed`. Every asset in the atlas begins at
`not_reviewed`. The release gate is that **no released asset remains `not_reviewed` or
`rejected`**. `docs/garden-asset-acceptance.json` is the sole current verdict owner. An atlas may
retain a review receipt only as explicitly non-authoritative historical provenance pointing back
to that registry; it may not carry a second current `review` verdict.

`review_candidates` is not a fourth verdict. It identifies unaccepted drawings temporarily
licensed on localhost for review while the public workflow remains on the frozen legacy snapshot.
Every candidate must actually appear on that local surface; accepted catalog assets need not
appear in the default scene. A root deployment is forbidden while review candidates, unaccepted
reachable atlas assets, or renderer-local art owners remain.

#### 7.10.3 Current standing

As of 2026-08-01, **all ten drawn fixture assets carry an `accepted` verdict**. The operator marked
bench, trellis and birdbath `READS` in round 3, then opened the round-4 response with `approved`
and marked lantern, pond, mailbox, stepping stones, bridge, planter and arbor `READS`. The source
receipts are the 2026-07-31T05:05:55 and 2026-07-31T06:03:29 operator messages in
`docs/operator-decision-record.md`; Contract P did not withdraw them. The other sixteen atlas
assets remain `not_reviewed` placeholders. Exact legacy art currently serving
`rikiworld.com/lateletter` also carries the operator's standing art approval, but its current
renderer-local ownership still blocks a canonical root release until it is migrated with exact
provenance. Scene composition remains a separate, unaccepted gate. The public Pages workflow still
serves the byte-frozen legacy snapshot, and the canonical root product remains release-blocked.

#### 7.10.4 Sequencing

Asset review is gated on species form and art ownership moving into the canonical layer.
Reviewing browser-local art before that move would accept pictures the terminal cannot reproduce
and that the migration would then discard. The order is therefore:

1. Species form grammar and the blueprint/legality contract land (§7.3.1, §7.8.5).
2. Art ownership moves from `web/garden-renderer.mjs` into the versioned atlas, in the
   `browser-proportional` and `ascii-safe` profiles.
3. Assets are drawn against the ASCII/Shift_JIS lineage.
4. Each new or visually changed asset is reviewed and its verdict recorded. An exact,
   provenance-verified migration of operator-approved legacy art retains the existing approval;
   moving the same drawing or frame sequence into the atlas is not grounds to demand another
   sign-off. New drawings, altered frames, and invented states or poses require their own review.
5. Only then do scene composition, the motion package, and §6.9 emotional review proceed.

#### 7.10.5 Reference-transcription parity

Structural ASCII and Shift_JIS reference images are **research inputs**, not Garden assets.
Converting a raster reference to UTF-8 text is an evidence-preservation task with its own
acceptance gate. It does not accept an atlas asset, establish terminal/browser parity, or
license a direct copy into the Garden.

The current files in `/Users/r/Downloads/STRUCTURAL ASCII ART EXAMPLES ` are explicitly
pre-gate: the existing `.txt` files are `provisional`, and `character-dimensions.tsv` contains
inferred dimensions rather than accepted grid measurements. Neither may be cited as a faithful
transcription or used as an art source until it passes this section.

For every reference image, the tracked transcription record contains:

- the immutable source and normalized-PNG SHA-256 hashes, pixel dimensions, source licence or
  provenance, and any crop/background normalization;
- the source encoding and font/renderer when known; `unknown` is a valid value and must not be
  guessed from appearance;
- an explicit row-baseline model and horizontal origin/advance model. A single inferred
  `character_width × character_height` pair is insufficient unless the source is demonstrably
  uniform-cell. Proportional or mixed-width work records per-row prefix positions or the
  measurement procedure that derives them;
- the candidate and accepted UTF-8 transcripts, preserving literal leading/trailing spaces,
  blank rows, grapheme clusters, and line endings. No OCR cleanup, whitespace trim, glyph
  substitution, or Unicode normalization is implicit; any such transformation is named in the
  record; and
- the renderer, transform, diff artifacts, reviewer, verdict, and any exception used in the
  parity decision.

OCR or a vision model may produce a candidate only. It is never a parity oracle and cannot
promote its own output. Each row is transcribed against the recovered row baseline and x origin,
then re-rendered from the candidate text before it is accepted. This makes the common failures
observable rather than cosmetic: row merges/splits, one-row vertical shifts, wrong leading-space
count, drift from a wrong x origin or pitch, dropped punctuation, and a wrong glyph with the same
rough silhouette.

The geometry owner is raster-derived. `GeometryEvidenceBundle` measures foreground alternatives,
row/column projections, autocorrelation, row bands, baselines, fixed-lattice candidates,
shaped-run candidates, and glyph-free component evidence directly from the normalized source PNG.
`route_raster_geometry` may select exactly one concrete model or must reject ties and insufficient
evidence; caller-supplied proof scores, transcripts, visual-layout sidecars, and recognizer hints
are not geometry evidence. A selected fixed model records origin, advance, line height, rows,
columns, cell bounds, and the selected foreground-mask hash. A selected shaped model records row
bands, baselines, run IDs/bounds, direction/orientation candidates, and the same mask hash.
`RecognitionInputBuilder` reconstructs that mask from its pinned recipe, emits hash-bound run-strip
PNGs and binary masks, and re-extracts components from the identical mask. Components outside every
run, silently discarded pixels, or fixed/shaped claims over the same pixels reject before any
recognizer runs.

The fixed-cell ASCII decoder is not a universal Unicode recognizer. Sources containing Japanese
kana or Kanji (including partial/cropped ideographs), combining marks, Arabic joining or bidi,
fullwidth/halfwidth characters, emoji/variation selectors, ZWJ sequences, or any other non-ASCII
grapheme cluster use the tracked Unicode run-decoder boundary in
`tracked/LateLetterResearch/transcription-parity/unicode-run-decoder-design.md`. Its stages are
geometry-only segmentation, whole-run grapheme recognition, script-aware shaping, component
ownership, and profile-specific display-width validation. It normalizes to NFC and records the
UAX #29, UAX #9, UAX #11, UTS #51, Unicode-data, font, and shaper versions. A partial component
cannot name a code point by silhouette; visually indistinguishable Unicode sequences fail closed
instead of being guessed. The fixed-cell path records `non_ascii_policy:
defer_to_unicode_run_decoder` and must not grow per-glyph ASCII branches to absorb these sources.

Recognizer coverage is an ensemble contract, not a claim that one recognizer covers all Unicode.
A version-pinned offline proposal ensemble must cover every positive release fixture through an
explicit capability profile recording scripts, directions, grapheme/emoji coverage, model and
dictionary hashes, runtime versions, licensing, offline/network status, tested fixture families,
and unsupported cases. No recognizer is authoritative: proposals are compared and gated by the
same geometry, grapheme, shaping, ownership, width, and ambiguity evidence. If no installed profile
covers a run, the result is `recognizer_unsupported` and fails closed. Unicode representation is
universal, but pixels cannot guarantee recovery of visually indistinguishable non-equivalent
sequences; those remain unresolved rather than being guessed.

The release corpus is versioned independently from historical benchmark evidence. Corpus v1 and
benchmark v4 remain immutable historical records; they cannot support a current coverage claim.
Corpus v2 (`tests/fixtures/transcription-v2/corpus-v2.json`) admits a positive only after the
selected project-controlled font's cmap coverage is hash-verified. A fallback-box rendering is a
development `fail_closed` fixture with `unicode_visual_collision`, never a positive. For a proved
fixed lattice, recognition input is one complete source-width row strip per measured row, not a
set of isolated cell crops. The benchmark invokes every geometry-owned run and records its run
hashes. Tesseract proposals are separate pinned PSM/language profiles (`psm7-eng`, `psm13-eng`,
`psm7-jpn-cjk`, and `psm7-ara`); selecting only `runs[0]` is a contract violation. Benchmark v5
is the first evidence package under this contract. Per-run proposals are composed in measured row
order (runs within a row concatenate; rows join with literal newlines) before exact NFC coverage
is scored. It remains blocked until all release positives appear in the deterministic offline
top-k without false-unique negative resolutions.

The emoji proposal profile is atlas-matching, not sequence injection. It reads a pinned UTS #51
fully-qualified sequence file and pinned Noto Emoji bytes, shapes complete VS/ZWJ grapheme clusters,
renders them across a bounded measured-advance range, and compares the resulting alpha/color mask
against the geometry-owned run strip. It retains top-k residual evidence but rejects ties,
unconfigured sequences, partial clusters, and visually equivalent alternatives. A transcript,
fixture target, or caller-supplied emoji sequence is never an adapter input.

**The re-render is a PNG comparison surface, not a browser text preview.** It is produced at the
normalized source PNG's exact device-pixel width and height, using the recorded crop, background,
font, font size, line height, x origin, row baselines, and pixel ratio. The transcript is not
scaled independently to make it look close. If its measured ink would exceed the source canvas,
the candidate fails layout parity; changing zoom, CSS scaling, screenshot scaling, or the source
crop to hide that disagreement is forbidden. The review package presents source PNG and
re-rendered PNG at one device pixel per image pixel, plus a same-sized 50% overlay and a
difference/mask image. Zooming the *viewer* is allowed only when it zooms all four panels by the
same integer factor; it cannot alter either rendered image.

Parity has three independent checks, all retained in the record:

1. **Layout parity.** Compare the accepted transcript's row baselines and grapheme anchors with
   the source model. A known uniform-cell source must agree within one source pixel at every
   baseline and anchor. A proportional or unknown-font source records the measured anchors and
   requires a reviewer to inspect the alignment overlay; no estimated pitch may be silently used
   as a pass.
2. **Raster parity.** When the original font and renderer are available, render the accepted text
   into that exact-size PNG and compare normalized ink masks plus its transparent overlay/diff.
   The comparison is a forensic diagnostic, not the TXT acceptance owner: a different font,
   antialiasing model, or rasterizer may produce a nonzero pixel diff while preserving the same
   rows, columns, spaces, glyph identities, and structural strokes. If that renderer is
   unavailable, this check is `blocked`, never `passed`; the record carries the labelled source-
   font disclosure, and that disclosure does not block a structurally accepted TXT.
3. **Human visual parity.** The operator reviews the pixel-aligned source PNG, re-rendered PNG,
   overlay, and difference/mask together, including every row with nonblank ink. The reviewer
   records `accepted`, `rejected`, or `blocked` and names any disagreement in rows, spaces,
   glyph identity, ownership, or structural strokes. Machine similarity scores and font-only
   raster residuals are diagnostic only and cannot substitute for this verdict.

Only a record with accepted layout parity and human visual parity may be called a **verified
reference transcription**. `blocked` raster parity is disclosed beside that label; it never
becomes a claim of pixel-exact reconstruction. Candidates, including the present 26 TXT files,
remain non-authoritative until then.

Evidence lives under
`tracked/LateLetterResearch/transcription-parity/<reference-id>/`: `manifest.json`, immutable
source identity, `candidate.txt`, `accepted.txt` when accepted, rendered comparison, alignment
overlay/diff, and the durable review receipt. The manifest is the source of truth; a contact
sheet or browser-local checkbox is not.

After a reference transcription is verified, the asset workflow begins separately:

```
verified reference transcription
  → structural model (contours, attachments, voids, material and affordance facts)
  → atlas asset with one semantic token and declared integer footprint
  → browser-proportional + ascii-safe profiles
  → §7.9 runtime semantic-parity checks and §7.10 per-profile visual acceptance
```

The two profiles may use different glyphs and have different pictorial extents. They must retain
the same `asset_id`, structural-model/reference-transcript lineage, world anchor, declared
footprint, hotspot identity, actions, and state semantics. Browser review uses the actual
PreText-measured renderer; terminal review uses its real terminal renderer. A canonical world
projection/event trace compared across both runtimes verifies those semantic fields. Thus a
successful reference conversion supplies trustworthy design evidence, while §7.9.5 remains the
separate guarantee that a recipient receives the same Garden behaviour in either runtime.

#### 7.10.6 Monospace raster recovery execution order

For a source that is demonstrably monospaced, recovery proceeds in this order. This is an
execution contract, not a suggestion to manually repair OCR output.

**Joint hypothesis rule (applies before final geometry authority):** calibration produces a
source-derived table of defensible pitch/phase/origin candidates; it must not select one merely
because it is the first valid lattice. Every retained hypothesis is allowed to produce complete
row/run proposal evidence. A deterministic joint decoder then evaluates geometry, row-sequence
recognition, component ownership, logical order, and display-width alternatives together. This
is the only stage allowed to resolve a geometry ambiguity using text evidence. A hypothesis that
has not passed that joint gate remains proposal/review evidence, not canonical geometry; it may
never write `candidate.txt` or `accepted.txt`. Final authority requires complete source coverage,
exactly-once ownership, complete row alignment, a pinned winner margin over competing hypotheses,
and no unresolved width/Unicode collision. A blocked joint result may expose a labelled
`joint-review.json` candidate for operator inspection, while its canonical candidate field stays
null.

1. **Calibrate before recognizing.** Derive the background/ink mask, horizontal cell advance,
   row pitch, grid phase, crop, and baselines from the source raster. Store the measurements and
   calibration image in the manifest. A character count, a guessed font size, or a prior TXT may
   not supply this grid. For `bbbb-flowers`, the measured periods are 9 px horizontally and 19 px
   vertically; the former 9.266 px SF Mono advance is invalid for this reference.
2. **Segment the fixed lattice.** Create one image region per `(row, column)` including blank
   cells. Preserve its absolute grid index; do not trim leading or internal blanks. The resulting
   occupancy map is reviewed before any string is emitted.
3. **Recognize, do not hand-repair.** A line/character OCR engine may propose glyphs and bounding
   boxes, but an adapter maps those proposals to lattice cells and records per-cell confidence.
   Tesseract `makebox`/TSV or PaddleOCR boxes are candidate evidence only. Ambiguous cells remain
   `unknown` and block the transcript; no operator or agent fills them from a visual guess.
4. **Emit an immutable machine candidate.** The candidate carries the source hash, calibrator and
   recognizer versions/options, grid record, per-cell confidence, and every unresolved cell. A
   later run writes a new candidate ID; it never edits an earlier candidate in place.
5. **Re-render on the same lattice.** The comparison renderer uses the measured advance and row
   pitch explicitly, rather than the selected font's natural advance. It writes exact-canvas PNG,
   overlay, and difference artifacts using a readable standard monospace face when the source
   face is unknown. These artifacts are a font-independent structural review surface: they expose
   missing/extra rows, misplaced spaces, wrong glyph identities, and ownership errors, but a raw
   pixel diff is not itself a rejection.
6. **Fail closed.** Any nonblank `unknown` cell, low-confidence cell, grid mismatch, unresolved
   structural conflict, stale forced-blank state, or visually different structural stroke keeps
   the candidate `rejected`. Only after the operator accepts the row/column layout and human
   visual structure is its exact UTF-8 text copied to `accepted.txt`; a nonzero diff caused only
   by an unavailable source font/renderer is recorded as `blocked`, not used to reject the TXT.

The tracked plan and per-reference artifacts live in
`tracked/LateLetterResearch/transcription-parity/`; no other directory, Preview window, or
temporary OCR output is authoritative.

#### 7.10.7 End-to-end rendered-Unicode screenshot recovery

This section is the executor contract for the general pipeline. It applies to screenshots of
rendered text art, including fixed-cell ASCII, mixed ASCII/fullwidth art, kana, Kanji, Arabic,
combining sequences, bidi text, and emoji grapheme clusters. It does not authorize conversion of
arbitrary illustrations into plausible text art.

The authority chain is:

```
immutable source PNG
  -> raster-derived geometry evidence
  -> exactly one geometry hypothesis or unresolved
  -> geometry-owned row/run masks and components
  -> non-authoritative recognizer proposals
  -> logical-grapheme decoding and visual shaping evidence
  -> exactly-once component ownership and ambiguity gates
  -> immutable machine candidate and layout sidecar
  -> structural comparison package
  -> operator accept/reject receipt
  -> accepted.txt
```

An `aligned` row means only that its logical display width can be placed on the measured run. It
does **not** mean its glyph identities match the source. Likewise, zero unknown cells, a complete
proposal beam, a low renderer residual, or a zero source-stencil diff is not transcription
acceptance.

Execute in this order, stopping at the first failed exit gate:

0. **Freeze and inventory prior evidence.** Hash the normalized source, identify the next unused
   attempt ID, and read the reference `ATTEMPT_LOG.md` plus the relevant failure-log family. Never
   overwrite, rename, repair, or copy a rejected machine TXT into a successor. Record the failed
   hypothesis, intervention, result, falsifier, and spent lane before beginning its successor.
1. **Bind evaluation truth outside runtime.** A benchmark transcript requires source provenance,
   exact UTF-8 bytes, NFC policy, row count, whitespace policy, and an operator verdict. It is
   stored as evaluation-only evidence and its hash may be read by benchmark scoring only. Geometry,
   preprocessing, recognition, ranking, and ownership code may never read it. Until approved, it
   may support visual discussion but not exact automated coverage claims.
2. **Normalize pixels once.** Record source/crop/background/foreground recipes and hashes. Retain
   all defensible foreground alternatives until geometry resolves them. UI chrome, guide rails,
   clipping, antialiasing, and transparent/color glyph evidence remain explicit; preprocessing may
   not erase unexplained ink.
3. **Produce geometry candidates without glyph labels.** Measure row bands, baselines, pitch,
   phase, origin, fixed advances, shaped-run anchors, direction/orientation candidates, seams, and
   components directly from pixels. Emit a source-sized overlay and candidate table. Do not use a
   recognizer preference, provisional TXT, expected transcript, or font-template match to manufacture
   geometry proof.
4. **Route geometry exclusively.** Select a fixed lattice or shaped/variable-width run model only
   when its pinned proof criteria and margin pass. If pitch, phase, ownership, or model choice is
   unresolved, retain all candidates as proposal evidence and stop candidate emission. Both models
   may be compared diagnostically, but they may not author competing text over the same components.
5. **Build recognition inputs from the selected raster evidence.** Emit complete row/run strips,
   binary/RGBA masks, measured anchors, clipping metadata, component IDs, and hashes. Fixed sources
   use complete rows rather than isolated cells; mixed-width and shaped sources use complete runs.
   Every substantive source pixel must be present in at least one inspectable input.
6. **Generate proposals with pinned offline capability profiles.** Invoke every applicable
   recognizer on every owned run. Record adapter/model/dictionary hashes, versions, script and
   direction coverage, runtime options, resource use, top-k output, and unsupported reasons. The
   structural span lattice owns spacing and span composition; it is not a universal Unicode glyph
   oracle. A finite hand-authored glyph table may support structural ASCII evidence but may not be
   expanded into the claimed all-Unicode recognizer. Remote models, when explicitly enabled, remain
   quarantined proposal generators and pass through every later deterministic gate.
7. **Measure proposal coverage before ranking.** In benchmark mode only, produce a per-run matrix
   stating whether the approved expected logical sequence is absent or present and, when present,
   its rank and owning adapter. An absent expected sequence is a recognition-coverage failure;
   changing the final scorer cannot fix it. A present but losing sequence is a ranking failure;
   adding transcript-specific recognition rules is forbidden. Coverage metrics never enter runtime
   scoring.
8. **Decode logical graphemes.** Compose proposals through an incremental ownership-aware span DAG,
   preserving measured blank columns and one-to-many display-unit edges. Merge equivalent states by
   logical grapheme sequence plus owned component IDs. Preserve complete source-supported witnesses
   independently from report caps; do not materialize or truncate a Cartesian product. Keep
   visually colliding, canonically non-equivalent alternatives unresolved.
9. **Shape for comparison without rewriting TXT.** Normalize the logical candidate according to the
   pinned NFC policy, segment with the pinned UAX #29 implementation, calculate display width with
   pinned tables, and run pinned bidi/shaping/font fallback to create visual-order evidence. Arabic
   joining, bidi reordering, combining marks, emoji VS/ZWJ, and vertical text are recorded in the
   layout sidecar. TXT remains logical order.
10. **Prove component ownership and rank from source evidence.** Every substantive component must
    map exactly once to a grapheme/run or remain unresolved. Rank using measured anchors, direction,
    topology, component cardinality, width, clipping, and independent recognizer agreement. A
    comparison-font raster residual is advisory and bounded. Unknown ownership, multiply owned ink,
    unexplained ink, a Unicode collision, or an insufficient winner margin rejects.
11. **Emit one immutable machine bundle only after all machine gates pass.** The bundle contains the
    exact candidate UTF-8 bytes, layout sidecar, source/geometry/component/proposal/environment
    hashes, coverage and conflict counts, normalization/shaping receipts, and rejection/authority
    state. Proposal capture and diagnostic replay cannot write `candidate.txt`, `machine.txt`, or
    `accepted.txt`. A failed run receives no retroactive edits; its successor uses a new attempt ID.
12. **Render a structural review package.** Render without source pixels or stencils at the exact
    source canvas and measured anchors. Preserve source, candidate render, overlay, diff, row/run
    panels, unresolved alternatives, and receipt hashes. Pixel equality is required only when the
    original font and renderer are known; otherwise raster parity is disclosed as blocked while
    rows, spaces, glyph identities, ownership, and structural strokes remain reviewable.
13. **Accept, promote, and advance the queue.** The operator accepts or rejects without editing the
    machine candidate. Acceptance copies the candidate byte-for-byte to `accepted.txt` and records
    a hash-bound receipt. Rejection freezes the package and records the next falsifiable hypothesis.
    Only then may the next queued reference activate.

Release of the general converter requires all positive corpus families to appear in deterministic
offline top-k coverage, all expected-fail-closed fixtures to remain unresolved for their recorded
reason, repeat hashes to match, resource ceilings to pass, and at least one operator-approved live
reference from each enabled geometry/script profile. Test counts prove mechanics and regressions;
they do not substitute for those conversion outcomes.

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

The draft is presented in the browser author desk as a labeled multiline text
editor with visible save state, message label, word count and explicit continue
and discard actions. It autosaves through the loopback session endpoint; the
passphrase is never included in that draft request. Browser-native keyboard,
screen-reader and dictation/paste behavior are the required accessibility
surface. Plaintext drafts remain inside the private author session store and
are never written to world-readable temporary directories.

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

Phases are ordered by the **irreplaceable capability first** principle: the author is terminally ill and time is the scarcest resource. Authoring, encryption, and delivery remain the first capability path, but the production garden is not complete merely because its renderer boots. §7.8 is now a ship gate because the released product must also work as a standalone cozy garden and expose authored world events through normal controls.

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
- Browser intake form with validation, steward field, passphrase hint
- Temporary reviewed seed bank file for the first offline vertical slice (`src/lateletter/data/question_bank_seed.v0.json`) using the canonical question-entry shape where practical
- Offline question selector: universal base set + personalization layer + pacing/gating rules
- Reviewed question bank (80–120 questions covering all 16 domains, categorized, versioned, shipped read-only in app resources) — the primary question engine. The 500+ bank target is a post-v1 content milestone; 80–120 well-reviewed questions fully serve a 10-exchange session and the existing selector infrastructure.
- Q&A session loop (offline — questions drawn from the selector/bank system) with session resumption
- Browser draft editor (§8.4)
- Local session storage with secure lifecycle (§9)
- Author incapacitation design (§5.6)
- Accessibility: semantic browser form/editor, keyboard and screen-reader operation, and paste-first dictation support (§12a)

### Phase 2 — Recipient mode (delivery)
- `.lateletter` bundle loader and recipient UI against the canonical bundle schema (development fixtures may stub ciphertext before Phase 3, but the on-disk schema does not reintroduce plaintext labels)
- Bundle file loading, date detection, read-receipt tracking
- Letter-bird animation (distinct from ambient bird)
- Multi-message selection overlay
- Message display with scroll support and print option
- Structural corruption detection for locked bundles and development fixtures (checksum-based)
- Bundle reopen flow for author (§5.5)

### Phase 3 — Encryption and sealing
- **Implemented profile:** bounded PBKDF2-HMAC-SHA256 + AES-256-GCM, with
  Python/WebCrypto interoperability and versioned compatibility.
- Bundle-HMAC derivation, authenticated metadata boundaries, secret-derived
  persistence isolation, passphrase disposal, and generic wrong-passphrase
  behavior are covered by adversarial tests.
- The historical `age`/Argon2id alternatives remain recorded in §4; neither is
  a current runtime path.
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
- **Release-gate correction (2026-07-21):** Earlier completed checkmarks establish prototype renderer components only. They do not establish production reachability, standalone-game value, input parity, author program control, atlas portability, animal AI, parallax, or accurate sky behavior. All §7.8 acceptance gates are ship-blocking.
- **Research sub-phase (ASCII animation and motion language) — first pass done 2026-04-18, more animations needed later:**
  - ~~Prototype ASCII animation patterns for the ambient bird, letter-bird, butterfly, rain, snow, clouds, and seasonal effects~~ ✓ — prototypes in `ascii-animations/`, all approved
  - ~~Research terminal-animation constraints: redraw budgets, layering, flicker avoidance, glyph readability, color usage~~ ✓ — documented in `ANIMATION-RESEARCH.txt`
  - Produce a motion/style sheet with timing targets and procedural generation specs (partially captured in §7.2–7.3)
  - Second research pass (after integration): prototype additional animations (new plant types, bonus creatures, bloom/growth, wind interactions) once the core set is integrated and the rendering architecture is proven
- **Integration phase — core set done 2026-04-19:**
  - ~~Integrate approved prototype motion language into projection-only terminal/HTML renderers (§7.2)~~ ✓ — historical layer prototypes remain reference material, not runtime owners
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

**Required garden release bar:** §7.8 replaces the former “non-ship-blocking polish” classification. Time/sky presentation, stable plant growth, functional fixtures, animal AI, interaction parity, author-directed events, collection/journal, parallax/reduced-motion behavior, and a production sealed demo are required before the garden can be described as standalone or full parity.

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
- **Screen reader compatibility:** Every author task must use semantic browser controls that work with VoiceOver, NVDA and comparable tools. Avoid visual-only indicators; use programmatic labels, status announcements and ordinary text for all states.
- **Braille display support:** The browser author path must expose ordinary accessible text and labeled controls compatible with refreshable braille displays. Full-screen curses is not an authoring dependency.
- **Fatigue-aware UX:** All progress is auto-saved. The author can stop at any point and resume (§5.3 session resumption). No time pressure anywhere in the interface.

## 13. Delivery Channels

The `.lateletter` file is the single source of truth. It reaches the recipient through three channels, all shipping in v1. Each channel delivers the same letters with the same passphrase — they differ only in how the garden renders and how the recipient discovers that a letter is waiting.

### 13.1 macOS app (primary)

A signed and notarized `LateLetter.app` with a bundled Python runtime. The recipient double-clicks the app or a `.lateletter` file. The garden renders as an animated curses TUI in a terminal window managed by the app. This is the premium experience — full particle effects, real-time weather, creature AI, and the living garden described in §7.

This channel requires macOS 14+. See §15 for packaging details.

### 13.2 Browser viewer (cross-platform)

A closed static artifact rooted at `viewer-bnw.html` and its versioned local
JavaScript/JSON dependency graph. `scripts/prepare_pages_site.py` copies and
verifies that transitive graph for Pages; it executes no third-party runtime
code and requires no account or installation. The recipient opens the deployed
page (or a locally served copy), drops or selects their `.lateletter` file,
enters the passphrase, and reads their letters. Decryption happens entirely
client-side.

**Scope (updated 2026-07-22):** The original static illustration and later mutable
layered prototype are historical. The current browser backdrop is a DOM text projection of
the canonical world with bounded disposable motion; §7.2 defines the active ownership model.

**Rendering architecture — local HTML/CSS/JavaScript modules:**

The browser viewer is built on **four rendering layers**:

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Letter text | **Built-in DOM fallback layout** | Proportional text wraps into standard DOM elements without remote layout code. It remains selectable, printable, and accessible. |
| Garden | **Canonical DOM text projection** | `web/garden-renderer.mjs` consumes the shared semantic world projection and renders DOM rows plus an accessible object summary. This is renderer parity evidence only; §7.8.13 remains the authority for any full-parity claim. |
| UI chrome | **Pure HTML/CSS** | Passphrase overlay, inbox, navigation, status — standard web forms. No framework. All screens are translucent scrims over the live garden. |
| Crypto | **WebCrypto (main thread, async)** — PBKDF2-SHA256 + AES-256-GCM | Versioned bundles use bounded, profile-specific bundle HMAC verification before decryption. Python parity lives in `src/lateletter/sealed.py`; authoring uses the canonical bundle writer. Explicit trusted development fixtures are capability-gated and do not weaken the normal sealed path. |

**Why DOM (not canvas):** Canvas is invisible to screen readers and produces blurry output on browser zoom. DOM text renders at native resolution at any zoom level, is selectable, printable, and fully accessible. The garden uses fixed-width Courier New; the UI and letter text use Times New Roman — they coexist in the same page without conflict.

**Why built-in DOM layout for letter bodies:** Letter text uses ordinary DOM
wrapping, so the release artifact needs no remote layout dependency. The Garden
grid remains fixed-width monospace and uses its own measured-cell projection.

**Why not WASM for the garden:** A compiled renderer would add binary size,
memory pressure, and device compatibility risk. DOM text rendering provides the
current portable renderer surface; only the §7.8.13 gates can establish full
Garden parity.

**Viewer contents:**
- File input via drag-and-drop or `<input type="file">` for the `.lateletter` bundle.
- Bounded PBKDF2-SHA256 derivation and AES-256-GCM decryption through native
  WebCrypto after checksum and bundle-HMAC validation.
- The passphrase input and passphrase string are discarded immediately after
  derivation; later logic retains only nonsecret authenticated state.
- Read receipts via `IndexedDB` (fallback to `localStorage`), namespaced by a
  stable secret-derived bundle identity and message ID. Same-public-ID bundles
  with different authentication keys cannot share receipt or world state.
  Clearing browser storage causes already-read messages to reappear; this is
  disclosed in the viewer UX.
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
- **Animal relationships:** The authenticated author program owns the relationship-animal
  roster. Canonical projection supplies exact object ID, species, bond tier, intent,
  personality, memory, and actions; the renderer chooses disposable multi-line poses and
  tier marks from those fields. `f` feeds only the focused or uniquely authored canonical
  animal. IndexedDB persists canonical world bytes, never renderer-local trust.

**Dev fixture mode (isDevFixture — bundle has no HMAC):**

Dev fixture and explicit localhost `?garden_debug=1` sessions expose diagnostics for QA and
design review. They may inspect canonical state or issue normal semantic commands, but they
must not create a second mutable season, animal, progression, or collision owner. Production
bundles ignore the debug query.

| Keybinding | Action | Status |
|---|---|---|
| `,` / `.` | Presentation-only historical shortcut; must not satisfy season/time acceptance or mutate canonical state. | Diagnostic only |
| `Shift+B` | Cycle color/background mode: default → white-bg → full-grayscale → B&W+anim → default. | Implemented |
| `Shift+D` | Dump projection/runtime diagnostics without mutation. | Implemented |
| `Shift+G` | Toggle grid overlay: shows cols×rows, CW/CH, mouse position, FPS, and full keybinding list. | Implemented |
| `Shift+F` | Re-trigger first-run banner: resets `_frbDone`, shows "This garden was planted for you…" fade-in again. | Planned |
| `Shift+P` | Forbidden as a completion owner; use an authored canonical completion occurrence. | Removed |
| `Shift+V` | Simulate a visit: increments `visitCount`, re-evaluates cumulative_visits triggers. | Planned |
| `Shift+I` | Cycle gift item state: hidden → revealed → examined (for each gift in bundle). | Planned |
| `Shift+N` | Cycle time-of-day independently: day → evening → night (for firefly/moon testing without changing season). | Planned |

**Dev grid (Shift+G):** When active, toggles the presentation grid CSS only. Canonical state
inspection lives in the gated diagnostics drawer or projection-backed console dump; there is
no renderer reset method or persistent dev-overlay state owner.

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

All interactive channels deliver the same **semantic letter and garden experience**. Email remains notification-only:
- Same passphrase, same date-lock logic, same read-receipt semantics (per-device, no sync).
- Same letter archive (§6.6) — read letters can always be re-read.
- Same post-completion acknowledgment (§6.7) — "all letters delivered."
- Same first-run emotional sequence — warmth first, then recognition ("planted for you by [name]"), then passphrase.

Browser and terminal may use different atlas profiles and motion techniques, but must expose the same world objects, actions, progression, authored events, animal decisions, and event trace through §7.8's shared world model. Rendering components, dev shortcuts, or dormant code paths do not establish parity. Parity is open until the sealed-production input, persistence, determinism, accessibility, and human-observation gates in §7.8.13 pass. Email notification does not render the garden; it tells the recipient to open an interactive channel.

### 13.5 Dev tool fixture — garden QA harness

The dev fixture (a `.lateletter` file with `hmac=""` and base64 plaintext bodies) doubles as the primary garden QA tool. The following design principles govern what dev fixture mode must be able to show:

**Evidence boundary:** Dev controls are diagnostic conveniences only. A feature exercised only by `Shift+...`, a fixture-only shortcut, URL seeding, console mutation, or an empty-HMAC bundle is not recipient-reachable and cannot satisfy §7.8.13. Every ship claim requires the matching visible control and normal sealed production flow.

**Everything a recipient could ever see, exercisable in one session:**

| Feature | How to trigger in dev fixture |
|---|---|
| All 4 seasons | `Shift+S` cycles spring → summer → autumn → winter |
| All seasonal weather | Automatic per season: spring rain, autumn rain+leaves, winter snow, summer calm |
| All 4 animals, all 4 bond tiers | Deterministic canonical fixture worlds plus normal semantic `observe`/`feed`/`play` commands; no renderer-local cycle key |
| Animal delivery animation | Auto-plays at tiers 1–3 (when letter is read with bonded animal) |
| First-run banner | `Shift+F` re-triggers "This garden was planted for you…" |
| Post-complete state | A fixture author program whose real recipient-visible conditions materialize canonical memorial/choreography entities |
| Garden interactions | Click plants (leaf burst), hover (rustle), `f` key (feed animal) |
| Cumulative-visit triggers | `Shift+V` simulates a visit; trigger fires when visitCount threshold met |
| Date triggers | Use a test bundle with dates in the past |
| Post-letter triggers | Read a letter; trigger fires after read receipt saved |
| Memory modal | Appears in archive after trigger fires; click to show sentiment text |
| Archive states | Unread (opacity 1), read (opacity .28), locked (opacity .12) |
| Multi-letter select | Bundle with multiple due letters on same date |

**Dev status overlay (top-right corner, dev fixture only):**
```
[dev] summer · focus=animal.cat · v=3 · completion=applied
```
Format is projection/runtime diagnostic prose only; it never stores independent values.

**Test fixture format (`.lateletter` dev bundle):**
- `hmac: ""` — activates dev fixture mode
- `garden_gifts`: includes one of each gift type (date, cumulative_visits, post_letter, animal)
- `messages`: 3 letters — one past-due (readable), one future (locked), one read (already in receipts)
- `garden_seed`: fixed value for reproducible plant layout

The `test_fixture.lateletter` file in the repo should satisfy all of the above.

### 13.6 Post-v1 delivery extensions

These are NOT in v1 scope but should inform architecture:

- **Historical animated browser garden:** The 2026-04 five-layer `GardenDOM` was prototype
  evidence and was later removed. The current browser surface is the projection-only
  canonical compositor; the historical package is preserved under `archive/` for comparison,
  not as an active ownership model.
- **Hosted HTML garden:** A web-hosted version where the recipient visits a URL instead of opening a local file. This requires hosting, accounts, and operational infrastructure. The trust model changes (the server sees the encrypted file) and must be explicitly disclosed.
- **Managed email service:** A hosted notification service that handles cron scheduling, retry, and deliverability so the author/steward doesn't have to run a script. Requires long-lived infrastructure.
- **Mobile app:** A native iOS/Android app for recipients. Possible but not planned — the browser viewer covers mobile browsers.

---

## 14. Open Questions

| Question | Status | Notes |
|----------|--------|-------|
| Should `garden_seed` in the bundle be fixed (deterministic) or change per-day? | Decided: fixed | Fixed seed = always the same garden (personal). §3 describes this as the intended behavior. |
| Should the passphrase be per-file or per-message? | Decided: per-file | Simpler UX; author sets one passphrase for the whole bundle. The authenticated process may retain nonsecret session state, but the passphrase is discarded after derivation (§4). |
| What happens if the author dies before finishing all messages? | Decided: §5.6 | Incremental export + steward role. See §5.6 for full design. |
| Should the app support "ongoing" message type (no fixed date, appears after a set # of days)? | Future | Would require a counter stored in the receipt file. Not in v1 UI. |
| Offline mode: should question bank be embedded in the script or a separate data file? | Decided: separate bundled data file | Editorial updates and question review should not require code edits. The app bundle can still ship as a single recipient artifact while containing versioned internal data files. |
| How should the app handle timezone differences between author and recipient? | Decided: v1 accepts ±1 day drift | `date.today()` uses recipient's local system date. Consider storing dates in UTC internally for future web/email portability (§13). |
| What is the recipient software distribution strategy? | Decided: handoff package | v1.0 ships a handoff folder containing the macOS app, verified static viewer closure, `.lateletter` file, notification script, and README. See §15.1. |
| Should there be a maximum message count per bundle? | Decided: soft limit | No hard limit. Warn author above 100 messages (absurdly large threshold). |
| How should externally-edited files be handled? | Decided: drafts-only, never canonical | External editing is allowed only for unsealed drafts under `~/.lateletter/author/drafts/`. The encrypted `.lateletter` bundle is always the canonical artifact. External editor swap/backup files are warned about but not managed by the app. |
| What are the platform requirements? | Decided: macOS app + cross-platform browser viewer | v1.0 ships the macOS .app as the primary channel and a closed static browser artifact as the cross-platform channel. The browser viewer ensures recipients on Windows, Linux, and mobile can read letters. See §13. |
| LLM synthesis quality gate? | Decided: non-ship-blocking and human-reviewed | v1.0 can ship without LLM mode. If enabled, every LLM-generated draft must be manually reviewed and explicitly confirmed by the author before encryption/export. |

## 15. Release Profile

**Canonical v1.0 ship target:** macOS app + cross-platform browser viewer + self-hosted email notification.

- The **macOS app** is a signed and notarized `LateLetter.app` with a bundled Python runtime and bundled question-bank data.
- The **browser viewer** is a closed, versioned static artifact rooted at
  `viewer-bnw.html`; its local module/data closure is verified before Pages
  deployment and opens `.lateletter` bundles with client-side decryption.
- The **email notification script** is a standalone `notify.py` that the author/steward runs via cron to send due-date email prompts.
- The recipient is not expected to install Python, use `pip`, edit shell config, or invoke CLI commands manually.
- Author mode is served locally in a modern browser on macOS (primary) and Linux (development target, not release-blocking). Windows author support is out of scope for v1.0.

### 15.1 Handoff package

The export flow (§5.4) produces a **handoff folder** — this is what the author gives to the recipient or leaves for the steward to deliver:

```
LateLetter-for-Maya/
  LateLetter.app              macOS garden app (if author is on macOS)
  viewer-bnw.html             browser entrypoint (works on any platform)
  web/                        versioned local browser modules
  src/lateletter/garden/data/ canonical atlas/sky JSON used by the browser
  maya.lateletter             the encrypted letter bundle
  notify.py                   email notification script (optional)
  README.txt                  plain-text instructions for the recipient
```

**`README.txt` contents (auto-generated from intake data):**

```
This folder contains letters from [author_name] for [recipient_name].

To read them:
  • On a Mac: Open LateLetter.app, then open maya.lateletter
  • On any computer: Open the hosted viewer URL, or serve this folder locally
    and open viewer-bnw.html

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
- Accessible semantic-browser author path, including keyboard-only and screen-reader operation
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
- **Recipient terminal too small:** Full-screen Garden screens require at least **80 columns x 24 rows**. Below that threshold, show a resize-required screen and direct the recipient to the browser viewer instead of rendering truncated UI.
- **No printer backend available:** Offer save-to-text-file only; printer absence is not fatal to letter reading.
- **Unsupported terminal features or screen-reader conflict:** Direct the recipient to the accessible browser viewer. Authoring never depends on terminal capabilities.
- **Unexpected crash during reading:** No read receipt is written until the message overlay is successfully opened and the message is marked read on clean exit from that read flow.
- **Lost `.lateletter` file:** Irrecoverable — all letters are permanently lost. The export flow (§5.4) warns the author and recommends copies. The handoff README (§15.1) does not address this (avoid alarming the recipient); the backup responsibility is the author's.
- **Browser viewer: invalid or excessive KDF profile:** Reject unsupported or
  out-of-bound PBKDF2 parameters before derivation. During valid derivation the
  viewer shows a neutral progress state; it never silently reduces the recorded
  work factor.
- **Browser viewer: storage denied or cleared:** Read receipts are lost; previously read messages reappear as new. The viewer warns that read state will not persist. Letters are still readable.

## 18. Release Acceptance Criteria

The product is not shippable until all of the following are true:

- A first-time author can complete intake, write at least one message offline, export a handoff package, reopen later, and append another message without data loss.
- A first-time recipient on a clean macOS machine can open `LateLetter.app`, experience the first-run sequence (§6.5), unlock the bundle, read a due message, re-read it via the archive (§6.6), quit, relaunch, and see the read receipt honored.
- A first-time recipient on a non-macOS machine can open the deployed
  `viewer-bnw.html` artifact in a modern browser and complete the same flow
  (first-run, unlock, read, archive, re-read, receipt), with equivalent
  emotional pacing.
- After all letters are read, the post-completion state (§6.7) activates correctly in both the macOS app and the browser viewer.
- A tampered bundle, corrupted bundle, and wrong-passphrase attempt all fail safely without false delivery claims — in both channels.
- The secure-default export path deletes finalized plaintext drafts while preserving unfinished notes when the author chooses to keep them.
- The export flow generates a complete handoff package (§15.1) with README, the
  verified browser dependency closure, and optional notification script.
- The semantic browser author path can complete the full workflow with keyboard-only navigation and a screen reader, without requiring a terminal.
- The macOS release artifact installs and runs on a clean macOS 14+ machine with no developer tooling preinstalled.
- The browser viewer works in current versions of Safari, Chrome, and Firefox without plugins or extensions.
- The self-hosted email notification script sends a due-date email correctly when run via cron.
- The product can read bundles created by prior v1 builds used during the release cycle.

**Runtime audit correction (2026-08-10):** The July 21 terminal-author result is retained only as historical diagnostic evidence. Its direct writer duplicated the author-service boundary and has been deleted. The author service still passes real sealing/export tests and the question, Q&A, resume and draft domain components remain intact, but the author workflow is not release-complete until `web/author-app.mjs` drives that service through the full browser E2E. Browser viewer checksum validation and the real sealed-bundle demo remain separate recipient-side evidence; neither closes author control.

## 19. Test Matrix

Minimum pre-release coverage:

- **Clean-machine recipient test:** Fresh macOS machine, no Python installed, app bundle + `.lateletter` file only.
- **Offline authoring test:** Network disabled, full author flow using only the bundled question bank.
- **Append/update test:** Export a bundle, append later, confirm old receipts still map correctly by `bundle_id`.
- **Corruption/tamper fixtures:** Bad checksum, bad HMAC, truncated file, unknown future version, and altered message date.
- **Accessibility test:** Complete the browser author flow with keyboard-only navigation, a screen reader, and pasted dictation text.
- **Terminal constraints test:** Exactly 80x24, below 80x24, no-color/limited-color terminal, and resize while overlay is open.
- **Crash-safety test:** Kill the app during session save and during bundle export; confirm the previous canonical file remains valid.
- **Performance sanity test:** Startup, unlock, and long-letter scrolling remain acceptable with a realistically sized bundle.
- **Browser viewer test:** Open the deployed `viewer-bnw.html` artifact in
  Safari, Chrome, and Firefox. Load a `.lateletter` file via drag-and-drop.
  Complete the recipient flow: first-run, passphrase entry, read letter, re-read
  via archive, and verify the secret-derived receipt namespace persists across
  page reload while history-cache restore requires reauthentication.
- **Browser viewer mobile test:** Open the deployed artifact on iOS and Android.
  Verify usable layout, passphrase disposal after bounded PBKDF2 derivation, and
  readable letters.
- **Email notification test:** Run `notify.py` with a test bundle containing a due-date message. Verify email is sent, content contains no letter text, and duplicate sends are suppressed on re-run.
- **Handoff package test:** Export a handoff folder and verify it contains the
  expected files, README is correctly populated from intake data, and the
  viewer dependency closure passes offline verification without modification.

## 20. Security Review Checklist

- Dependency versions for crypto-related packages are pinned and reviewed before release.
- AES-GCM and PBKDF2 code paths have round-trip and negative tests using
  tampered ciphertext, wrong nonce, wrong salt/profile, and wrong passphrase.
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

This is the canonical execution order for the project. The critical path runs through steps 1→17→ship. Items marked **[parallel]** may run alongside the current critical-path step. The former **Garden Polish** classification is superseded: the standalone/author-directed contract in §7.8 is ship-blocking.

*Last updated: 2026-07-21 — four research lanes established the §7.8 standalone garden, input parity, author program, animal AI, Unicode atlas, procedural growth, parallax, and astronomical-sky contract. Existing renderer and fixture checkmarks are prototype evidence only until §7.8.13 passes.*

---

### Completed foundation

1. **[DONE]** Freeze the v1.0 release contract: macOS-first target, app-bundle packaging, bundle compatibility policy, and v1 ship/non-ship scope.
2. **[DONE — 2026-04-18]** Complete Phase 1 research for question-bank and interview design.
3. **[DONE (first pass) — 2026-04-18]** ASCII animation research and prototyping. First set of prototypes approved (birds, butterfly, fireflies, rain, snow, clouds, leaves, letter-bird, garden composition).

### Garden core (ship-blocking minimum)

4. **[IN PROGRESS — code complete 2026-04-19, human verification pending on 4c/4e/4g]** Integrate approved animations into the garden:

   **Process rule:** Each subphase below requires (1) a research pass studying reference implementations and prototypes, (2) implementation, and (3) human verification before the subphase is closed. No subphase is marked done without the author running the garden and confirming the visual result.

   **Current canonical implementation (historical 4a–4g prototypes are diagnostic provenance):**
   - ~~4a. Refactor world state/reducer/projection from renderer presentation (§7.2).~~ ✓ — terminal and HTML consume the same canonical projection.
   - ~~4b. Implement bounded disposable effects from projected semantic object surfaces.~~ ✓ — no renderer-local collision or persistent particle owner.
   - ~~4c. Integrate relationship-animal projection plus bounded ambient insects/glints.~~ ✓ — multi-cell animals are canonical objects; the renderer invents no ambient bird.
   - ~~4d. Integrate weather animations (first pass): rain, snow, clouds, lightning.~~ ✓ — first pass working. Rain refined in 4g.
   - ~~4e. Integrate falling leaves from projected plant surfaces.~~ ✓ (code done, awaiting human verification) — autumn-only disposable presentation.
   - ~~4f. Project canonical civil-time season + weather into renderer palettes/effects (§7.4).~~ ✓
   - ~~4g. Rain and wind refinement.~~ ✓ — denser rain (60 drops), gravity 0.08, diagonal `\` rendering, 3-fragment plant collision with reflection+damping (0.32), multi-particle ground splashes (3–5 fan, char aging `'`→`.`→`·`), wind modulates drop drift. Awaiting human verification.

**4P. [SHIP-BLOCKING, REOPENED 2026-07-21] Standalone garden and authored-world track.**

The earlier 4h–4l items remain useful visual work, but no longer define the release bar by themselves. They can proceed in parallel, and each follows the same research→implement→verify rule as steps 4a–4g.

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

   - **4m. Shared world model and semantic command layer (§7.8.1–§7.8.3).** Move canonical objects, interactions, camera, state transitions, and persistence out of renderer-local owners. Expose every core action through touch, mouse, keyboard, and terminal adapters.
   - **4n. Versioned atlas and hybrid scene content (§7.8.4, §7.8.11).** Build the atlas compiler, portability profiles, stable fixture manifests, connected tiles, ASCII fallbacks, and the minimum fixture/collectible inventory.
   - **4o. Stable plant growth and standalone loops (§7.8.2, §7.8.5–§7.8.6).** Implement persistent plant topology, tending consequences, journal/collections, placement/undo, bounded offline progress, and glance/tend/dwell play.
   - **4p. Deterministic animal AI (§7.8.7).** Replace feed-count-only ownership with the FSM/behavior-tree/utility/animation pipeline, persistent memory/personality, varied bonding actions, fixture affordances, and species-specific repertoires.
   - **4q. Encrypted author program and timeline (§7.8.10).** Implement compound conditions, scheduling/recurrence/missed policy, idempotent effects, privacy migration, timeline authoring, preview trace, validation, and runtime parity.
   - **4r. Parallax and astronomical sky (§7.8.8–§7.8.9).** Implement continuous world camera, renderer-specific parallax, pause/reduced motion, opt-in coarse location, bright-star projection, and privacy fallbacks.
   - **4s. Production acceptance (§7.8.13).** Publish a synthetic sealed bundle exercising the whole loop and pass the deterministic, modality, accessibility, performance, sky, absence, and human-observation gates. Dev-fixture-only evidence cannot close this step.

### Author mode

5. ~~Build the author-mode foundation~~ ✓
   - ~~Local storage model (session.json, questions_asked.json, atomic writes, permissions)~~ ✓
   - ~~`pyproject.toml` with declared dependencies (cryptography, argon2-cffi, pytest)~~ ✓
   - ~~Intake data model with validation (intake.py) — passphrase never persisted~~ ✓
   - Legacy TUI/line-mode intake and curses draft components are retained only as disconnected implementation material; they are not product authoring routes.
   - **[OPEN]** Browser intake form with validation, autosave and passphrase handling
   - **[OPEN]** Semantic browser accessibility path for consent, intake, Q&A and drafting
   - **[OPEN]** Browser draft editor (§8.4) with atomic draft saves
   - Maintenance CLI entry point retains `--garden` and `--wipe-session`; the duplicate `--write` and `--accessible` author routes were deleted on 2026-08-10.
6. **[REOPENED — 2026-08-10]** Build the offline browser author workflow
   - Research-informed seed banks remain bundled: the 30-question universal bank describes its prompts as reviewed but still labels itself a temporary prototype, while the 101-question conditional bank explicitly says draft/not editorially reviewed. Item-level evidence lineage and canonical approval remain open for both.
   - ~~Offline question selector (universal base set + personalization + gating)~~ ✓
   - ~~Q&A session loop with autosave~~ ✓
   - ~~Session resumption with split-state healing~~ ✓
   - ~~Incapacitation/steward handling (§5.6) — steward info, handoff summary, session compaction~~ ✓
   - The terminal E2E owner was deleted; `author_service.py` remains the sole tested seal/export owner.
   - **[BLOCKED]** Browser E2E integration (message list → Q&A → draft → export / append-later) requires `web/author-app.mjs`.

### Recipient experience and delivery

7. **[REOPENED — 2026-07-21] Design and verify the recipient's daily experience.** §6.8 is the first-pass progression concept; §7.8 is the controlling researched contract.

   **Prototype decisions retained for migration, but not sufficient for release:**
   - ✓ Normal-day contract: the garden is a place the recipient *tends*, not just watches.
     Progression uses varied cumulative animal relationships, author-programmed memory
     capsules, nonfatal plant change, and evidence of elapsed life without care debt.
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

10. **[IN PROGRESS — core viewer and checksum/auth parity done; cross-browser human QA pending]** Build the browser viewer (`viewer-bnw.html`) — B&W Times New Roman aesthetic with a canonical semantic Garden projection; §7.8.13 controls full-parity status:
    - ~~Pure local HTML/CSS/JavaScript with built-in DOM fallback letter layout~~ ✓ — no remote runtime layout dependency; proportional TNR wrapping and responsive reflow
    - ~~Projection-only DOM text compositor consuming canonical world objects, hotspots,
      scene, animal state, topology, and actions; disposable palette, LOD, weather,
      particles, and one-cell ambience own no gameplay state~~ ✓
    - ~~Seasonal weather: spring rain, autumn rain+leaves, winter snow, summer calm; wind-based rain char (`\`/`|`/`/`); plant collision → fragments; ground hit → splashes; char aging `'`→`.`→`·`~~ ✓
    - ~~File input: drag-and-drop or `<input type="file">` for `.lateletter` bundle~~ ✓
    - ~~Dev-fixture Web Worker (base64 plaintext passthrough); real crypto wired in step 13~~ ✓
    - ~~Full recipient flow: passphrase entry, letter reading with scroll, archive/inbox (§6.6), save-to-text, read receipts via IndexedDB + localStorage fallback~~ ✓
    - ~~Inbox replaces HUD: post-auth inbox floats over live garden; letters read/unread/locked at varying opacity; memories section; no symbols~~ ✓
    - ~~B&W palette: cream paper sky, earthy plant colors, monochrome UI at opacity hierarchy~~ ✓
    - ~~**TODO 10a — Garden always visible:**~~ ✓ `#g.dim` CSS class removed; `classList.toggle('dim')` removed from `showScreen()`; scrim opacity .76, blur 10px; stale `class="dim"` attr cleaned. Needs browser QA across seasonal backgrounds.
    - **TODO 10b — Cursor interaction:** Rustle effect on hover (char substitution near cursor, radius 5 cells — implemented, needs browser QA) and leaf-burst particle spawn on click (implemented, needs browser QA). Confirm both work on touch (mobile tap = click event).
    - ~~**TODO 10c — Animal presentation and delivery:**~~ ✓ Four species and four bond tiers use canonical atlas delivery/presentation assets. Animal state, authenticated triggers, and visible feed/play actions run only after successful bundle authentication and persist in the secret-derived bundle namespace; development shortcuts remain fixture-only evidence.
    - ~~**TODO 10d — First-run sequence:**~~ ✓ The first-run banner is read and written only after authenticated commit, using the same secret-derived bundle namespace. Wrong, corrupt, and pre-auth loads perform no onboarding writes.
    - ~~**TODO 10e — HTML grid-fidelity gap:**~~ ✓ `_measure()` now appends test span/div inside `#g` (not `document.body`) for exact font-rendering context; CH measured from real `div` inheriting `height:15px` from CSS rule. `getSeason()` checks `?season=` URL param first. `_arcSeed()` added for `?arc=` browser demo seeding. **Pending:** browser QA pass (Safari/Chrome/Firefox at 100% + 150% zoom) — human verification needed.
    - **Audit update (2026-07-21):** The browser recomputes the canonical visible-payload checksum before unlock, validates bounded versioned authentication profiles, and passed valid/tampered automated paths plus the real interactive sealed-demo flow. Safari/Chrome/Firefox human QA remains open.
    - ~~Native WebCrypto PBKDF2-SHA256 + AES-256-GCM, with bundle HMAC before plaintext promotion~~ ✓
    - ~~Package and verify one closed static HTML/module/JSON dependency graph with no remote runtime code~~ ✓ — `scripts/prepare_pages_site.py`
    - Test in Safari, Chrome, Firefox (desktop and mobile)

11. **[DONE — 2026-04-20]** Build the email notification script (`notify.py`):
    - Standalone script, no app dependency — reads `.lateletter` bundle plaintext metadata only (dates, bundle_id)
    - Checks `date.today()` against message dates, sends email via SMTP for newly due messages
    - Local sent-log to suppress duplicate notifications on re-run
    - Configurable SMTP (any provider: Gmail, Mailgun, Fastmail, etc.)
    - Never reads or decrypts letter content, never stores passphrase
    - Generates cron/launchd instructions for the author/steward
    - Include in handoff package (§15.1)

11a. **[Parts A/B/C done; Part D pending human observation]** Demo harnesses and emotional verification — the next critical-path cluster. These steps make the emotional arc (§6.9) evaluable as a lived experience rather than a code review. All three parts must complete before step 13 (encryption), because the emotional bar must be set before the product is sealed.

   ~~**Part A — HTML grid-fidelity gap**~~ ✓ *(tied to TODO 10e above)*
   - ~~Measure true glyph metrics for the chosen monospace font at 1× zoom; lock in matching CW/CH constants~~ ✓ `_measure()` appends to `#g`, CH from real div
   - ~~Add `?season=autumn|winter|spring|summer` URL param to `getSeason()`~~ ✓
   - Browser QA pass: open the garden in Safari, Chrome, and Firefox at 100% and 150% zoom — **pending human verification**

   ~~**Part B — Full recipient e2e demo harness**~~ ✓ *(compressed timeline simulation)*
   - ~~Extend or replace `demo_recipient.py`~~ ✓ `--arc [waiting|delivery|trust1|trust2|trust3|postcomplete|item]` flags; seeds RecipientStore state; launches real recipient module
   - ~~`--browser` flag~~ ✓ generates dev fixture `.lateletter` per arc + prints `?season=`+`?arc=` URL
   - ~~`docs/DEMO_SCRIPT.md`~~ ✓ produced

   ~~**Part C — Author e2e demo**~~ ✓ *(pre-seeded fixture walkthrough)*
   - `demo_author.py` stages the consent→intake→Q&A→draft→export narrative and now emits real sealed messages/gifts through `seal_bundle()` plus the canonical `write_bundle()` path. Checksum, HMAC, Python decryption, and an automated interactive HTML unlock/read check passed on 2026-07-21.

   **Part D — Emotional arc verification pass**
   - Run the recipient demo harness (Part B) as a human observer, not a developer
   - For each of the five §6.9 moments: write a one-paragraph field note (what worked, what felt off, what needs adjustment)
   - If any moment fails its §6.9 criterion, file it as a bug and fix before proceeding to step 13
   - This pass may surface UI timing issues (delivery pacing), visual issues (bird animation weight), or copy issues (memory overlay tone)
   - **Ship gate:** All five §6.9 moments must pass before encryption (step 13) is wired — sealing a product that hasn't been emotionally verified is the wrong order

12. **[parallel with steps 9–11a, editorial]** Expand the seed bank to a reviewed 80–120 question bank covering all 16 domains. Apply the two-human review process (§5.3) to this smaller set. The 500+ bank target is post-v1 content work.

### Security and sealing

13. Build the encryption/sealing layer:
    - ~~Choose and version the interoperable primitive~~ ✓ — bounded
      PBKDF2-HMAC-SHA256 + AES-256-GCM in Python and native WebCrypto
    - ~~Round-trip and adversarial cross-renderer crypto vectors~~ ✓
    - ~~Discard passphrase/form state after derivation; retain only nonsecret
      authenticated state and a secret-derived persistence binding~~ ✓
    - Bundle HMAC derivation and verification using `bundle_auth_salt`
    - Label encryption (label inside ciphertext, not exposed in outer structure)
    - Replace dev fixture stubs from step 8 with real encrypted bundles
    - Wire crypto into browser viewer (step 10) — same parameters Python and JS, verified interop
    - Incremental export with checksum + HMAC recomputation (§5.4)
    - Handoff package generation (§15.1) including the verified static viewer
      closure, README.txt, and optional notify.py
    - Append-later flow: reopen bundle, verify passphrase, add messages (§5.5)
    - Session wipe flow and `--wipe-session` CLI flag (§5.4)

14. Failure-mode and security validation:
    - Corruption fixtures: bad checksum, truncated file, unknown version — in both macOS app and browser viewer
    - Tamper fixtures: bad HMAC, altered message date, modified ciphertext — in both channels
    - Wrong-passphrase handling (generic error, no leakage) — in both channels
    - Crash-safety: kill during session save and bundle export; verify prior valid file survives
    - Canonical-file durability: temp-file + fsync + atomic rename verification
    - Terminal constraints: 80×24, below 80×24, no-color, resize during overlay
    - Browser constraints: mobile viewport, bounded PBKDF2, storage denied,
      history-cache purge, and cross-browser compatibility
    - Email notification: duplicate suppression, SMTP failure handling, sent-log integrity
    - Performance sanity with realistic bundle — targets: app startup < 3s,
      bounded-profile passphrase unlock, letter scroll < 50ms/frame, and Garden
      render within the measured frame budget
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
    - Semantic browser author mode end-to-end verification
    - Recipient-side accessible reading path (screen-reader-compatible letter display, non-curses fallback for overlays)
    - Browser viewer accessibility: keyboard navigation, screen-reader-compatible HTML, sufficient contrast
    - Braille display compatibility audit
    - Bundle backward-compatibility testing across v1 builds
    - `--wipe-session` non-interactive secure deletion
    - Recipient Garden minimum terminal size handling (80×24 gate with browser-viewer handoff)

17. Release acceptance: run the full §18 matrix and §19 test matrix. Ship v1.0 only after every required criterion passes.

### Post-v1

18. **[parallel after step 17]** Research the optional LLM path: prompt/evaluation design, privacy disclosure, quality gates, and regression fixtures.
19. Implement optional LLM mode only after the offline/local-first v1 path is stable and already shippable.
20. **[parallel after step 17]** Research hosted delivery extensions (§21): hosted HTML garden custody model, managed email service operations, cost/lifetime analysis.
21. Build hosted extensions only after the trust-model changes are explicit and the self-contained v1 channels are stable.
