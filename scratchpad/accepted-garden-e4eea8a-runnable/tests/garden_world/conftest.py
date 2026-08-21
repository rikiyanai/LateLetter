from __future__ import annotations

from dataclasses import replace

import pytest

from lateletter.garden.world.model import (
    AnimalState,
    CollectibleState,
    FixtureState,
    PlantState,
    Vec2,
    new_world,
)


@pytest.fixture()
def world():
    state = new_world("world-test", "fixed-seed", world_width=40, world_height=30)
    return replace(
        state,
        plants=(PlantState("plant:rose", "rose", Vec2(4, 5)),),
        fixtures=(FixtureState("fixture:bench", "bench", Vec2(8, 5)),),
        animals=(AnimalState("animal:rabbit", "rabbit", Vec2(12, 5)),),
        collectibles=(
            CollectibleState(
                "collectible:feather",
                "animal_trace",
                "animal-given",
                "A small feather",
                "A soft feather left beside the path.",
                Vec2(16, 5),
            ),
        ),
    )
