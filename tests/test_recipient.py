"""
Tests for recipient mode — RecipientStore, trigger evaluation, and animal system.

Uses tmp_path so tests never touch real ~/.lateletter files.
"""

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from lateletter.bundle import Bundle, GardenGift, Trigger, create_dev_fixture
from lateletter.recipient import (
    RecipientStore,
    _ANIMAL_ART,
    _ANIMAL_DELIVERY_FRAMES,
    _ANIMAL_FOOTPRINTS,
    _find_animal_gift,
    _animal_home_pos,
    _trust_tier,
    is_gift_triggered,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def store(tmp_path, monkeypatch):
    """RecipientStore pointed at tmp_path, bundle id 'test-bundle'."""
    monkeypatch.setattr("lateletter.recipient._RECIPIENT_DIR", tmp_path)
    monkeypatch.setattr("lateletter.recipient._RECEIPTS_FILE",
                        tmp_path / "receipts.json")
    monkeypatch.setattr("lateletter.recipient._GARDEN_STATE_FILE",
                        tmp_path / "garden_state.json")
    return RecipientStore("test-bundle")


@pytest.fixture()
def dev_bundle():
    return create_dev_fixture()


# ---------------------------------------------------------------------------
# _trust_tier
# ---------------------------------------------------------------------------

class TestTrustTier:
    def test_zero_actions_is_wild(self):
        assert _trust_tier(0) == 0

    def test_below_first_threshold_is_wild(self):
        assert _trust_tier(2) == 0

    def test_at_first_threshold_is_curious(self):
        assert _trust_tier(3) == 1

    def test_between_tiers(self):
        assert _trust_tier(6) == 1

    def test_at_second_threshold_is_familiar(self):
        assert _trust_tier(7) == 2

    def test_at_bonded_threshold(self):
        assert _trust_tier(14) == 3

    def test_above_bonded_stays_three(self):
        assert _trust_tier(100) == 3


# ---------------------------------------------------------------------------
# _ANIMAL_ART completeness
# ---------------------------------------------------------------------------

class TestAnimalArt:
    @pytest.mark.parametrize("animal", ["cat", "bird", "rabbit", "turtle"])
    def test_all_four_tiers_defined(self, animal):
        art = _ANIMAL_ART[animal]
        for tier in range(4):
            assert tier in art, f"{animal} missing tier {tier}"
            assert len(art[tier]) >= 1, f"{animal} tier {tier} has no art lines"

    @pytest.mark.parametrize("animal", ["cat", "bird", "rabbit", "turtle"])
    def test_delivery_frames_defined(self, animal):
        assert animal in _ANIMAL_DELIVERY_FRAMES
        assert len(_ANIMAL_DELIVERY_FRAMES[animal]) >= 1

    @pytest.mark.parametrize("animal", ["cat", "bird", "rabbit", "turtle"])
    def test_footprints_defined(self, animal):
        assert animal in _ANIMAL_FOOTPRINTS
        assert len(_ANIMAL_FOOTPRINTS[animal]) >= 1


# ---------------------------------------------------------------------------
# _find_animal_gift
# ---------------------------------------------------------------------------

class TestFindAnimalGift:
    def test_finds_animal_in_dev_fixture(self, dev_bundle):
        ag = _find_animal_gift(dev_bundle)
        assert ag is not None
        assert ag.type == "animal"
        assert ag.catalog_id == "cat"

    def test_returns_none_when_no_animal(self):
        bundle = create_dev_fixture(include_gifts=False)
        assert _find_animal_gift(bundle) is None

    def test_returns_first_animal_only(self, dev_bundle):
        """Only one animal per v1 bundle; _find_animal_gift returns the first."""
        ag = _find_animal_gift(dev_bundle)
        assert ag is not None


# ---------------------------------------------------------------------------
# _animal_home_pos
# ---------------------------------------------------------------------------

class TestAnimalHomePos:
    def test_within_bounds(self):
        for animal in ("cat", "bird", "rabbit", "turtle"):
            row, col = _animal_home_pos(animal, 42301, 80, 24)
            assert 0 <= row < 24
            assert 0 <= col < 80

    def test_stable_across_calls(self):
        r1, c1 = _animal_home_pos("cat", 42301, 80, 24)
        r2, c2 = _animal_home_pos("cat", 42301, 80, 24)
        assert (r1, c1) == (r2, c2)

    def test_different_animals_may_differ(self):
        pos_cat = _animal_home_pos("cat", 42301, 80, 24)
        pos_bird = _animal_home_pos("bird", 42301, 80, 24)
        # Not guaranteed, but almost certainly distinct with different hash seeds
        # Just ensure both are valid
        for row, col in (pos_cat, pos_bird):
            assert 0 <= row < 24
            assert 0 <= col < 80


# ---------------------------------------------------------------------------
# is_gift_triggered
# ---------------------------------------------------------------------------

class TestIsGiftTriggered:
    def _gift(self, trigger_type, value):
        return GardenGift(
            id="test-id",
            type="item",
            catalog_id="candle",
            trigger=Trigger(type=trigger_type, value=value),
        )

    def test_date_trigger_before_date(self):
        gift = self._gift("date", "2099-01-01")
        assert not is_gift_triggered(gift, date.today(), 100, set())

    def test_date_trigger_on_date(self):
        gift = self._gift("date", date.today().isoformat())
        assert is_gift_triggered(gift, date.today(), 0, set())

    def test_date_trigger_past_date(self):
        gift = self._gift("date", "2020-01-01")
        assert is_gift_triggered(gift, date.today(), 0, set())

    def test_cumulative_visits_not_met(self):
        gift = self._gift("cumulative_visits", "10")
        assert not is_gift_triggered(gift, date.today(), 5, set())

    def test_cumulative_visits_met(self):
        gift = self._gift("cumulative_visits", "10")
        assert is_gift_triggered(gift, date.today(), 10, set())

    def test_cumulative_visits_exceeded(self):
        gift = self._gift("cumulative_visits", "10")
        assert is_gift_triggered(gift, date.today(), 99, set())

    def test_post_letter_not_read(self):
        gift = self._gift("post_letter", "msg-abc")
        assert not is_gift_triggered(gift, date.today(), 0, set())

    def test_post_letter_read(self):
        gift = self._gift("post_letter", "msg-abc")
        assert is_gift_triggered(gift, date.today(), 0, {"msg-abc"})

    def test_invalid_date_value_returns_false(self):
        gift = self._gift("date", "not-a-date")
        assert not is_gift_triggered(gift, date.today(), 0, set())

    def test_invalid_visits_value_returns_false(self):
        gift = self._gift("cumulative_visits", "banana")
        assert not is_gift_triggered(gift, date.today(), 99, set())


# ---------------------------------------------------------------------------
# RecipientStore — basic visit tracking
# ---------------------------------------------------------------------------

class TestRecipientStoreVisits:
    def test_initial_total_visits_zero(self, store):
        assert store.total_visits() == 0

    def test_increment_visit_increments(self, store):
        store.increment_visit()
        assert store.total_visits() == 1

    def test_multiple_increments(self, store):
        for _ in range(5):
            store.increment_visit()
        assert store.total_visits() == 5

    def test_was_absent_false_on_first_visit(self, store):
        store.increment_visit()
        assert store.was_absent is False

    def test_was_absent_false_same_day(self, store, tmp_path):
        store.increment_visit()
        store2 = RecipientStore.__new__(RecipientStore)
        store2.bundle_id = "test-bundle"
        store2.was_absent = False
        store2._receipts = store._receipts
        store2._state = store._state
        store2.increment_visit()
        assert store2.was_absent is False

    def test_was_absent_true_after_gap(self, store, monkeypatch):
        # Simulate last_visit two days ago
        yesterday = (date.today() - timedelta(days=2)).isoformat()
        store._state["test-bundle"]["last_visit"] = yesterday
        store.increment_visit()
        assert store.was_absent is True

    def test_persists_across_instances(self, store, tmp_path, monkeypatch):
        store.increment_visit()
        monkeypatch.setattr("lateletter.recipient._RECIPIENT_DIR", tmp_path)
        monkeypatch.setattr("lateletter.recipient._RECEIPTS_FILE",
                            tmp_path / "receipts.json")
        monkeypatch.setattr("lateletter.recipient._GARDEN_STATE_FILE",
                            tmp_path / "garden_state.json")
        store2 = RecipientStore("test-bundle")
        assert store2.total_visits() == 1


# ---------------------------------------------------------------------------
# RecipientStore — read receipts
# ---------------------------------------------------------------------------

class TestRecipientStoreReceipts:
    def test_not_read_initially(self, store):
        assert not store.is_read("msg-1")

    def test_mark_read(self, store):
        store.mark_read("msg-1")
        assert store.is_read("msg-1")

    def test_read_set(self, store):
        store.mark_read("msg-1")
        store.mark_read("msg-2")
        assert store.read_set() == {"msg-1", "msg-2"}

    def test_discovered_initially_false(self, store):
        assert not store.is_discovered("gift-1")

    def test_mark_discovered(self, store):
        store.mark_discovered("gift-1")
        assert store.is_discovered("gift-1")


# ---------------------------------------------------------------------------
# RecipientStore — animal system
# ---------------------------------------------------------------------------

class TestRecipientStoreAnimal:
    def test_get_animal_state_default(self, store):
        s = store.get_animal_state("cat")
        assert s["trust_actions"] == 0
        assert s["trust_tier"] == 0
        assert s["last_fed"] is None

    def test_feed_animal_increments_actions(self, store):
        store.feed_animal("cat")
        s = store.get_animal_state("cat")
        assert s["trust_actions"] == 1

    def test_feed_animal_returns_tier(self, store):
        for _ in range(2):
            store.feed_animal("cat")
        tier = store.feed_animal("cat")  # 3rd feed → tier 1
        assert tier == 1

    def test_feed_animal_tier_progression(self, store):
        # Reach tier 3 at exactly 14 actions
        for _ in range(13):
            store.feed_animal("cat")
        tier = store.feed_animal("cat")
        assert tier == 3

    def test_feed_animal_updates_last_fed(self, store):
        store.feed_animal("cat")
        s = store.get_animal_state("cat")
        assert s["last_fed"] == date.today().isoformat()

    def test_feed_different_animals_independent(self, store):
        store.feed_animal("cat")
        store.feed_animal("cat")
        store.feed_animal("cat")
        store.feed_animal("bird")
        assert store.get_animal_state("cat")["trust_actions"] == 3
        assert store.get_animal_state("bird")["trust_actions"] == 1

    def test_animal_state_persists(self, store, tmp_path, monkeypatch):
        for _ in range(7):
            store.feed_animal("cat")
        monkeypatch.setattr("lateletter.recipient._RECIPIENT_DIR", tmp_path)
        monkeypatch.setattr("lateletter.recipient._RECEIPTS_FILE",
                            tmp_path / "receipts.json")
        monkeypatch.setattr("lateletter.recipient._GARDEN_STATE_FILE",
                            tmp_path / "garden_state.json")
        store2 = RecipientStore("test-bundle")
        s = store2.get_animal_state("cat")
        assert s["trust_actions"] == 7
        assert s["trust_tier"] == 2

    def test_animals_slot_in_default_state(self, store):
        """New bundles get an empty animals dict in garden_state."""
        s = store._state["test-bundle"]
        assert "animals" in s
        assert s["animals"] == {}

    def test_tier_not_exceed_three(self, store):
        for _ in range(50):
            tier = store.feed_animal("cat")
        assert tier == 3
