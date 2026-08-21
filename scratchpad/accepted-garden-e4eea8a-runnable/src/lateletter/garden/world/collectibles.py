"""Four-family collectible catalog used by canonical world generation."""

from __future__ import annotations

from dataclasses import dataclass

from .model import CollectibleState, Vec2


@dataclass(frozen=True)
class CollectibleDefinition:
    catalog_id: str
    family: str
    provenance: str
    label: str
    description: str


COLLECTIBLE_FAMILIES = (
    "plant_species",
    "seasonal_natural_find",
    "animal_trace",
    "authored_keepsake",
)

COLLECTIBLE_CATALOG: dict[str, CollectibleDefinition] = {
    "oak_leaf": CollectibleDefinition("oak_leaf", "plant_species", "recipient-grown", "Oak leaf", "A leaf showing the oak's branching veins."),
    "lavender_sprig": CollectibleDefinition("lavender_sprig", "plant_species", "recipient-grown", "Lavender sprig", "A fragrant sprig from a tended lavender plant."),
    "first_snowflake": CollectibleDefinition("first_snowflake", "seasonal_natural_find", "procedural", "First snowflake", "A remembered trace of the season's first snow."),
    "fallen_acorn": CollectibleDefinition("fallen_acorn", "seasonal_natural_find", "procedural", "Fallen acorn", "A small autumn find beneath the trees."),
    "rabbit_track": CollectibleDefinition("rabbit_track", "animal_trace", "animal-given", "Rabbit track", "A soft print where a rabbit paused."),
    "bird_feather": CollectibleDefinition("bird_feather", "animal_trace", "animal-given", "Bird feather", "A feather left near a favorite perch."),
    "pressed_flower": CollectibleDefinition("pressed_flower", "authored_keepsake", "author-authored", "Pressed flower", "A flower preserved with an authored memory."),
    "small_key": CollectibleDefinition("small_key", "authored_keepsake", "author-authored", "Small key", "A keepsake key waiting without expiry."),
}


def create_collectible(
    collectible_id: str,
    catalog_id: str,
    position: Vec2,
) -> CollectibleState:
    definition = COLLECTIBLE_CATALOG[catalog_id]
    return CollectibleState(
        collectible_id=collectible_id,
        family=definition.family,
        provenance=definition.provenance,
        label=definition.label,
        description=definition.description,
        position=position,
        authored=definition.family == "authored_keepsake",
    )
