"""Tests for the accessible line-mode intake form (§5.1, §12a)."""

from lateletter.intake import IntakeData, KeyDate, load_intake
from lateletter.intake_accessible import run_intake_accessible
from lateletter.session_store import SessionStore


def _seq(responses):
    """Input function that yields from a list, then raises EOFError."""
    it = iter(responses)
    return lambda prompt: next(it) if (v := next(it, _SENTINEL)) is not _SENTINEL else (_ for _ in ()).throw(EOFError)

_SENTINEL = object()

def _input_fn(responses):
    it = iter(responses)
    def _fn(prompt):
        try:
            return next(it)
        except StopIteration:
            raise EOFError
    return _fn

def _pwd_fn(responses):
    it = iter(responses)
    def _fn(prompt):
        try:
            return next(it)
        except StopIteration:
            raise EOFError
    return _fn

_NOOP = lambda text: None

# Minimal valid form inputs
_FIELDS = [
    "Robert", "Father", "Maya", "Daughter",
    "Birthday: June 15", "",       # key dates + done
    "dogs, hiking",                # tags
    "Sarah", "sarah@x.com",       # steward
    "1",                           # release choice
]
_PASS = ["correct horse battery staple"] * 2
_HINT = ["What we called our first dog"]


def _run(tmp_path, fields=_FIELDS, passwords=_PASS, hint=_HINT,
         existing=None, output_fn=_NOOP):
    store = SessionStore(base_dir=tmp_path)
    return run_intake_accessible(
        store, existing,
        input_fn=_input_fn(fields + hint),
        password_fn=_pwd_fn(passwords),
        output_fn=output_fn,
    ), store


class TestHappyPath:
    def test_complete_intake_and_save(self, tmp_path):
        (result, store) = _run(tmp_path)
        assert result is not None
        data, passphrase = result
        assert data.author_name == "Robert"
        assert data.recipient_name == "Maya"
        assert passphrase == "correct horse battery staple"
        # Saved to disk
        loaded = load_intake(store)
        assert loaded is not None and loaded.author_name == "Robert"
        # Passphrase never on disk
        session = store.load_session()
        for k in ("passphrase", "passphrase_confirm", "key", "secret", "password"):
            assert k not in session


class TestExit:
    def test_quit_returns_none(self, tmp_path):
        (result, _) = _run(tmp_path, fields=["quit"])
        assert result is None

    def test_eof_returns_none(self, tmp_path):
        (result, _) = _run(tmp_path, fields=[])
        assert result is None

    def test_quit_at_steward_contact(self, tmp_path):
        fields = [
            "Robert", "Father", "Maya", "Daughter",
            "Birthday: June 15", "",
            "dogs",
            "Sarah",      # steward name
            "quit",       # steward contact → should exit
        ]
        (result, _) = _run(tmp_path, fields=fields, hint=[])
        assert result is None


class TestPrePopulation:
    def test_enter_keeps_existing(self, tmp_path):
        existing = IntakeData(
            author_name="Robert", relationship="Father",
            recipient_name="Maya", recipient_relationship="Daughter",
            key_dates=[KeyDate("Birthday", "June 15")],
            memory_tags=["dogs"], steward_name="Sarah",
            steward_contact="sarah@x.com", passphrase_hint="first dog",
        )
        blanks = [""] * 9   # all blank = keep existing
        (result, _) = _run(tmp_path, fields=blanks, hint=[""],
                           existing=existing, passwords=["newpass", "newpass"])
        assert result is not None
        assert result[0].author_name == "Robert"


class TestValidation:
    def test_passphrase_mismatch_retries(self, tmp_path):
        passwords = ["first", "second", "correct", "correct"]
        (result, _) = _run(tmp_path, passwords=passwords)
        assert result is not None and result[1] == "correct"

    def test_empty_key_date_retry_loops(self, tmp_path):
        fields = [
            "Robert", "Father", "Maya", "Daughter",
            "",                       # blank key dates → triggers retry loop
            "",                       # still blank → loops
            "Birthday: June 15",     # valid entry
            "dogs", "", "1",         # rest of form (no steward)
        ]
        (result, _) = _run(tmp_path, fields=fields)
        assert result is not None
        assert result[0].key_dates[0].label == "Birthday"

    def test_release_unfinished_with_date(self, tmp_path):
        fields = [
            "Robert", "Father", "Maya", "Daughter",
            "Birthday: June 15", "",
            "dogs", "Sarah", "sarah@x.com",
            "2",              # release choice
            "2027-06-15",    # release date
        ]
        (result, _) = _run(tmp_path, fields=fields)
        assert result is not None
        assert result[0].release_unfinished is True
        assert result[0].release_date == "2027-06-15"


class TestWarnings:
    def test_strength_and_communication_warnings(self, tmp_path):
        output = []
        _run(tmp_path, passwords=["abc", "abc"], output_fn=output.append)
        text = "\n".join(output)
        assert "short" in text.lower()     # strength warning
        assert "lost forever" in text       # communication warning
        assert "Maya" in text
