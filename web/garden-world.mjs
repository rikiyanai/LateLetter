/** Canonical, renderer-neutral Garden world model and reducer for browsers. */

import {
  canonicalJson,
  sha256Hex,
  stableId,
  validateGardenCommand,
} from './garden-input.mjs';


export const WORLD_SCHEMA_VERSION = 1;
export const ENGINE_VERSION = 'garden-world-internal-v1';

// Three versions, deliberately independent. `WORLD_SCHEMA_VERSION` above is the
// SHAPE of the stored document -- can it be parsed. `GENERATOR_VERSION` is the
// code that produced a world's initial content -- was it built by today's
// generator. `COMPOSITION_VERSION` identifies which CANDIDATE composition
// revision the population came from.
//
// `COMPOSITION_VERSION` carries NO approval and must never be read as one. An
// earlier draft described it as the population the operator approved, which
// made every generated world claim an approval nobody has granted for any
// composition. Acceptance is a separate, fingerprint-bound operator verdict in
// docs/garden-composition-acceptance.json.
//
// A stored world can be current in the first and stale in both others at once,
// which is why one number cannot carry them. The Python constants in
// src/lateletter/garden/world/model.py must match, and a contract test asserts
// they do.
export const GENERATOR_VERSION = 3;
export const COMPOSITION_VERSION = 3;

// How a world arrived in this process -- a different question from its lineage.
// A world can have perfect stamps and still have come out of storage after a
// hundred interactions. No stamp can record an event that happens at load time,
// so the runtime reports it separately.
export const LOAD_GENERATED = 'generated';
export const LOAD_STORED = 'loaded';
export const LOAD_SCHEMA_MIGRATED = 'schema_migrated';
// The whole set, so a caller cannot pass a value nobody defined. A guard that
// silently accepts an unrecognised origin can be switched off by a typo.
export const LOAD_ORIGINS = new Set([LOAD_GENERATED, LOAD_STORED, LOAD_SCHEMA_MIGRATED]);

// Transforms from an older stored shape to the next one, keyed by the schema
// they read. EMPTY, and honestly so: schema 1 is the only shape this project
// has ever written, so there is no historical document any transform could have
// been written against. Renumbering a document is not migrating it, so an
// unregistered old schema is refused rather than renumbered.
export const SCHEMA_MIGRATIONS = Object.freeze({});
export const PROCESSED_COMMAND_LIMIT = 512;
export const EVENT_TRACE_LIMIT = 512;
export const LIVE_TRACE_LIMIT = 120;
export const UNDO_STACK_LIMIT = 128;
export const MILESTONE_RECEIPT_LIMIT = 512;

function compactRecentStrings(values, limit) {
  const boundedLimit = Math.max(0, integer(limit));
  if (boundedLimit === 0) return [];
  const recent = new Map();
  for (const raw of values ?? []) {
    const value = String(raw);
    recent.delete(value);
    recent.set(value, true);
  }
  return [...recent.keys()].slice(-boundedLimit);
}

const PERSONALITY_FIELDS = Object.freeze([
  'boldness', 'sociability', 'curiosity', 'playfulness', 'patience',
  'routine_strength', 'food_motivation', 'day_preference',
]);

export const FIXTURE_CATALOG = Object.freeze({
  bench: { name: 'Garden bench', footprint: [2, 1], blocks_movement: true, affordances: ['sit', 'animal-rest', 'author-socket'], actions: ['inspect', 'primary_interact'] },
  fence: { name: 'Fence', footprint: [1, 1], blocks_movement: true, affordances: ['boundary', 'perch', 'vine-support'], actions: ['inspect'] },
  gate: { name: 'Garden gate', footprint: [1, 1], blocks_movement: false, affordances: ['open-close', 'route'], actions: ['inspect', 'primary_interact'] },
  sundial: { name: 'Sundial', footprint: [1, 1], blocks_movement: true, affordances: ['garden-time', 'authored-beat'], actions: ['inspect'] },
  trellis: { name: 'Trellis', footprint: [2, 1], blocks_movement: true, affordances: ['train-plant', 'animal-hide'], actions: ['inspect', 'tend'] },
  birdbath: { name: 'Birdbath', footprint: [1, 1], blocks_movement: true, affordances: ['refill', 'drink', 'bathe'], actions: ['inspect', 'tend'] },
  lantern: { name: 'Lantern', footprint: [1, 1], blocks_movement: true, affordances: ['light', 'moth-visit'], actions: ['inspect', 'primary_interact'] },
  pond: { name: 'Pond', footprint: [3, 2], blocks_movement: true, affordances: ['ripples', 'aquatic-plant', 'water-visitor'], actions: ['inspect', 'tend'] },
  memory_shrine: { name: 'Memory shrine', footprint: [2, 1], blocks_movement: true, affordances: ['keepsake', 'inscription', 'memory-discovery'], actions: ['inspect', 'open_journal'] },
  stepping_stone: { name: 'Stepping stone', footprint: [1, 1], blocks_movement: false, affordances: ['path'], actions: ['inspect'] },
  bridge: { name: 'Bridge', footprint: [3, 1], blocks_movement: false, affordances: ['cross-water', 'animal-route'], actions: ['inspect', 'primary_interact'] },
  planter: { name: 'Planter', footprint: [2, 1], blocks_movement: true, affordances: ['plant-container', 'transplant'], actions: ['inspect', 'tend'] },
  table: { name: 'Garden table', footprint: [2, 2], blocks_movement: true, affordances: ['place-keepsake', 'animal-sniff'], actions: ['inspect', 'primary_interact'] },
  chair: { name: 'Garden chair', footprint: [1, 1], blocks_movement: true, affordances: ['sit', 'observe'], actions: ['inspect', 'primary_interact'] },
  fence_gate: { name: 'Fence and gate', footprint: [1, 1], blocks_movement: false, affordances: ['open-close', 'route'], actions: ['inspect', 'primary_interact'] },
  mailbox: { name: 'Memory mailbox', footprint: [1, 1], blocks_movement: true, affordances: ['keepsake', 'memory-discovery'], actions: ['inspect', 'open_journal'] },
  stepping_stones: { name: 'Stepping stones', footprint: [1, 1], blocks_movement: false, affordances: ['path'], actions: ['inspect'] },
  table_chairs: { name: 'Garden table and chairs', footprint: [2, 2], blocks_movement: true, affordances: ['sit', 'shared-space', 'animal-sniff'], actions: ['inspect', 'primary_interact'] },
  well: { name: 'Garden well', footprint: [1, 1], blocks_movement: true, affordances: ['water-source', 'draw-water'], actions: ['inspect', 'tend'] },
  arbor: { name: 'Garden arbor', footprint: [2, 1], blocks_movement: true, affordances: ['plant-support', 'shade', 'animal-rest'], actions: ['inspect', 'primary_interact'] },
  wind_chime: { name: 'Wind chime', footprint: [1, 1], blocks_movement: false, affordances: ['ambience', 'listen'], actions: ['inspect', 'primary_interact'] },
  shed_edge: { name: 'Tool shed', footprint: [2, 1], blocks_movement: true, affordances: ['storage', 'shelter'], actions: ['inspect', 'primary_interact'] },
  tool_rack: { name: 'Tool rack', footprint: [1, 1], blocks_movement: true, affordances: ['storage', 'tending'], actions: ['inspect', 'primary_interact'] },
  watering_can: { name: 'Watering can', footprint: [1, 1], blocks_movement: false, affordances: ['water', 'tending'], actions: ['inspect', 'tend'] },
  compost: { name: 'Compost', footprint: [1, 1], blocks_movement: true, affordances: ['soil', 'tending'], actions: ['inspect', 'tend'] },
  basket: { name: 'Garden basket', footprint: [1, 1], blocks_movement: false, affordances: ['inventory', 'gather'], actions: ['inspect', 'primary_interact'] },
  sign: { name: 'Garden sign', footprint: [1, 1], blocks_movement: true, affordances: ['narrative', 'read'], actions: ['inspect', 'primary_interact'] },
  memorial_stone: { name: 'Memorial stone', footprint: [1, 1], blocks_movement: true, affordances: ['inscription', 'memory-discovery'], actions: ['inspect', 'open_journal'] },
});

const REQUIRED_FUNCTIONAL_FIXTURES = Object.freeze([
  'bench', 'fence_gate', 'sundial', 'trellis', 'birdbath', 'lantern', 'pond',
  'mailbox', 'stepping_stones', 'bridge', 'planter', 'table_chairs', 'well',
  'arbor', 'wind_chime', 'shed_edge', 'tool_rack', 'watering_can', 'compost',
  'basket', 'sign', 'memorial_stone',
]);
export const STARTER_FIXTURES = Object.freeze([
  'bench', 'mailbox', 'stepping_stones', 'planter', 'lantern',
]);

export const FIXTURE_VERBS = Object.freeze({
  bench: ['sit', 'observe'], fence: ['open', 'close'], gate: ['open', 'close'], sundial: ['read_time'],
  // `observe` was added to the lantern so it can have a safe primary action
  // (7.8.3.1) that is not one side of its lit/unlit state. Mirrored in
  // `FIXTURE_CATALOG['lantern'].interaction_verbs` on the Python side.
  trellis: ['train'], birdbath: ['refill', 'observe'], lantern: ['light', 'extinguish', 'observe'], pond: ['observe', 'tend'],
  memory_shrine: ['open', 'remember'], stepping_stone: ['walk'], bridge: ['cross', 'observe'],
  planter: ['transplant', 'tend'], table: ['arrange', 'sit'], chair: ['sit', 'observe'],
  fence_gate: ['open', 'close'], mailbox: ['open', 'remember'], stepping_stones: ['walk'],
  table_chairs: ['sit', 'arrange'], well: ['draw_water'], arbor: ['rest', 'observe'],
  wind_chime: ['listen'], shed_edge: ['open', 'organize'], tool_rack: ['organize'],
  watering_can: ['fill', 'water'], compost: ['turn'], basket: ['review_inventory', 'gather'],
  sign: ['read'], memorial_stone: ['remember', 'observe'],
});

/**
 * The single act a plain click, tap or Enter performs on each fixture.
 *
 * SPEC 7.8.3.1, and AUTHORED rather than inferred. Taking `FIXTURE_VERBS[id][0]`
 * would even be right for the bench, but then behaviour would be a side effect
 * of array order, and a fixture whose first verb happens to be consequential
 * would silently acquire a dangerous primary. Declaring it is what lets the
 * contract promise a primary action is always obvious, safe and choice-free.
 *
 * A missing entry means the fixture declares no primary action; it is then
 * inert to direct activation and its verbs are reached through "more actions",
 * which 7.8.3.1 explicitly allows. Only the five default-scene fixtures are
 * authored so far -- the rest await the same judgement. This does NOT change
 * dispatch, which still falls back to the first verb; it governs only what the
 * world OFFERS as a one-click act.
 *
 * Kept in step with `primary_verb`/`primary_label` on `FixtureDefinition` in
 * `src/lateletter/garden/world/fixtures.py`.
 */
export const FIXTURE_PRIMARY_ACTIONS = Object.freeze({
  bench: { verb: 'sit', label: 'Sit on the garden bench' },
  mailbox: { verb: 'open', label: 'Open the memory mailbox' },
  stepping_stones: { verb: 'walk', label: 'Walk the stepping stones' },
  // `tend`, not `transplant`: transplanting moves a living plant and is a
  // consequential choice, which 7.8.3.1 forbids as a primary action.
  planter: { verb: 'tend', label: 'Tend the planter' },
  // `observe`, NOT `light`. Lighting is state-dependent -- it means something
  // different depending on whether the lantern is already lit -- so it belongs
  // to the spawned-opportunity path in 7.8.3.2, where the world can offer
  // exactly the one that currently applies. Looking is always safe.
  lantern: { verb: 'observe', label: 'Look at the lantern' },
});

/**
 * Return the spawned opportunities a fixture is currently offering.
 *
 * SPEC 7.8.3.2. An opportunity is an act that only makes sense right now, given
 * world state -- lighting a lantern that is dark, putting out one that is
 * burning. It is offered as its own control beside the object rather than
 * buried in a menu, and it goes away when it stops applying rather than when a
 * timer runs out.
 *
 * Computed here, in the world model, for the reason the contract insists on:
 * the renderer must never decide what looks available. It draws what this
 * returns and nothing else, so the browser and the terminal necessarily offer
 * the same opportunities from the same state.
 *
 * @param fixture Fixture record whose state decides what is on offer.
 * @returns Records carrying `opportunity_id` (stable while the same
 *   opportunity stands, so the attract animation does not replay on every
 *   repaint), `verb` (an EXISTING canonical fixture verb -- opportunities add
 *   no commands and hold no state), and `label` (second-person imperative used
 *   as both accessible name and visible text). Ordered by `opportunity_id` so
 *   both implementations and every repaint agree; empty means nothing on offer.
 *
 * Mirrors `fixture_opportunities` in
 * `src/lateletter/garden/world/fixtures.py`.
 */
export function fixtureOpportunities(fixture) {
  const values = fixture.authored_state ?? {};
  const offers = [];
  if (fixture.catalog_id === 'lantern') {
    // Exactly one of these is ever on offer, because they are two sides of one
    // piece of state. Offering both would be offering a choice, and choices
    // are what the action sheet is for.
    offers.push(values.lit
      ? { verb: 'extinguish', label: 'Put out the lantern' }
      : { verb: 'light', label: 'Light the lantern' });
  }
  return offers
    .map(offer => ({
      opportunity_id: `${fixture.fixture_id}:${offer.verb}`,
      verb: offer.verb,
      label: offer.label,
    }))
    .sort((left, right) => compareCodePoints(left.opportunity_id, right.opportunity_id));
}
// The bond tier at which an animal stops being a stranger. Mirrors
// `ANIMAL_TRUST_TIER` in `src/lateletter/garden/world/animals.py`.
export const ANIMAL_TRUST_TIER = 3;

/** What to call this animal in a sentence addressed to the reader. */
export function animalDisplayName(animal) {
  return animal.display_name || String(animal.species_id).replaceAll('_', ' ');
}

/**
 * The single act a plain click, tap or Enter on this animal performs.
 *
 * SPEC 7.8.3.1. Interaction with a living thing is DIRECT: clicking the cat
 * does something to the cat rather than opening a menu about it. The verb is
 * `play` because it is this model's safe, resource-free animal interaction;
 * `pet` is not a canonical command, and inventing one so the label could match
 * the decision's example wording would mean dispatching something the world
 * does not implement.
 *
 * Mirrors `animal_primary_action` in `src/lateletter/garden/world/animals.py`.
 */
export function animalPrimaryAction(animal) {
  return { verb: 'play', label: `Play with the ${animalDisplayName(animal)}` };
}

/**
 * The spawned opportunities this animal is currently offering.
 *
 * SPEC 7.8.3.2. Feeding is state-dependent -- it means one thing to a stray and
 * another to a companion -- so it is an opportunity, not a primary action.
 * Eligibility is decided HERE rather than in the viewer, which is what stops
 * the browser and the terminal offering different things from the same state.
 *
 * Mirrors `animal_opportunities` in `src/lateletter/garden/world/animals.py`.
 */
export function animalOpportunities(animal) {
  const offers = [];
  if (Number(animal.bond_tier ?? 0) < ANIMAL_TRUST_TIER) {
    offers.push({ verb: 'feed', label: `Feed the ${animalDisplayName(animal)}` });
  }
  return offers
    .map(offer => ({
      opportunity_id: `${animal.animal_id}:${offer.verb}`,
      verb: offer.verb,
      label: offer.label,
    }))
    .sort((left, right) => compareCodePoints(left.opportunity_id, right.opportunity_id));
}

const FIXTURE_CONNECTED_GROUP = Object.freeze({
  fence: 'fence', gate: 'fence', fence_gate: 'fence',
  stepping_stone: 'path', stepping_stones: 'path', pond: 'pond_edge',
});

function fixturePresentationState(fixture) {
  const values = fixture.authored_state ?? {};
  if (['fence', 'gate', 'fence_gate', 'mailbox', 'memory_shrine', 'shed_edge'].includes(fixture.catalog_id)) {
    return values.open ? 'open' : 'closed';
  }
  if (fixture.catalog_id === 'lantern') return values.lit ? 'on' : 'off';
  if (['birdbath', 'watering_can'].includes(fixture.catalog_id)) {
    return integer(values.water_level) > 0 ? 'full' : 'empty';
  }
  if (fixture.catalog_id === 'compost') return integer(values.turned_count) > 0 ? 'turned' : 'idle';
  return fixture.interaction_count > 0 ? 'active' : 'idle';
}

function fixtureActiveAffordances(fixture) {
  const values = fixture.authored_state ?? {};
  const enabled = new Set(FIXTURE_CATALOG[fixture.catalog_id].affordances);
  if (['gate', 'fence_gate'].includes(fixture.catalog_id) && !values.open) enabled.delete('route');
  if (fixture.catalog_id === 'birdbath' && integer(values.water_level) <= 0) {
    enabled.delete('drink'); enabled.delete('bathe');
  }
  if (fixture.catalog_id === 'lantern' && !values.lit) enabled.delete('moth-visit');
  if (fixture.catalog_id === 'watering_can' && integer(values.water_level) <= 0) enabled.delete('water');
  return [...enabled].sort();
}

const TIER_REPERTOIRES = Object.freeze({
  bird: [['watch_from_branch', 'startle_flutter', 'explore_edge'], ['pause_approach', 'perch_nearby', 'bathe'], ['initiate_song_play', 'follow_overhead', 'rest_near', 'recall_perch'], ['return_greet', 'bring_feather', 'share_perch', 'deliver_song']],
  cat: [['watch_from_cover', 'startle_retreat', 'explore_edge'], ['pause_approach', 'sniff_nearby', 'use_bench'], ['initiate_string_play', 'follow_path', 'rest_near', 'recall_knead'], ['return_greet', 'bring_whisker', 'share_bench', 'settled_knead']],
  rabbit: [['watch_from_hide', 'startle_hop', 'explore_edge'], ['pause_approach', 'forage_nearby', 'use_trellis'], ['initiate_hop_play', 'follow_briefly', 'rest_near', 'recall_treat'], ['return_greet', 'bring_track', 'share_planter', 'settled_flop']],
  turtle: [['watch_from_water', 'withdraw_gently', 'explore_edge'], ['pause_approach', 'walk_nearby', 'use_pond'], ['initiate_follow', 'follow_briefly', 'rest_near', 'recall_sunspot'], ['return_greet', 'bring_scute', 'share_bridge', 'settled_sunbathe']],
});

const ANIMAL_GIFTS = Object.freeze({
  bird: ['bird_feather', 'Bird feather', 'A feather offered from a favorite perch.'],
  cat: ['cat_whisker', 'Cat whisker', 'A whisker found where a trusted cat settled nearby.'],
  rabbit: ['rabbit_track', 'Rabbit track', 'A soft print left beside a shared garden path.'],
  turtle: ['turtle_scute', 'Turtle scute', 'A naturally shed scute left by a familiar turtle.'],
});
const INTENT_AFFORDANCE_REQUIREMENTS = Object.freeze({
  bathe: ['bathe'], paddle: ['pond', 'water-visitor'], perch: ['perch'],
  perch_nearby: ['perch'], use_bench: ['bench', 'animal-rest'],
  share_bench: ['bench', 'animal-rest'], use_trellis: ['trellis', 'animal-hide'],
  share_planter: ['planter', 'plant-container'], use_pond: ['pond', 'water-visitor'],
  share_bridge: ['bridge', 'animal-route'], follow_path: ['path', 'route'],
});
const RECENT_MEMORY_LIMIT = 16;
const CARDINAL_STEPS = Object.freeze([[0, -1], [1, 0], [0, 1], [-1, 0]]);
const MOVING_INTENT_TOKENS = Object.freeze([
  'approach', 'bathe', 'bring', 'cross', 'explore', 'follow', 'forage',
  'greet', 'hop', 'paddle', 'patrol', 'play', 'sniff', 'walk',
]);
const MEMORY_INTENT_TOKENS = Object.freeze({
  feed: ['approach', 'bring', 'forage', 'greet', 'recall', 'sniff'],
  play: ['flop', 'follow', 'hop', 'knead', 'play', 'sing', 'song'],
  observe: ['groom', 'near', 'perch', 'rest', 'watch'],
});
const SEASON_INTENT_TOKENS = Object.freeze({
  spring: ['forage', 'greet', 'sing', 'song'],
  summer: ['bathe', 'paddle', 'play', 'sunbathe'],
  autumn: ['explore', 'forage', 'patrol', 'sniff'],
  winter: ['hide', 'nap', 'rest', 'settled'],
});
const PLANT_MATURITY_STAGES = Object.freeze([
  'emergent', 'sprouting', 'unfurling', 'juvenile', 'developing',
  'near_mature', 'mature',
]);

export const MINIMUM_WORLD_WIDTH = 64;
export const MINIMUM_WORLD_HEIGHT = 40;

const SPECIES_CATALOG = Object.freeze({
  oak: ['tree', 18, 30, 86400, ['trunk', 'branch', 'broadleaf']],
  pine: ['tree', 16, 26, 86400, ['trunk', 'conifer', 'needle']],
  willow: ['tree', 20, 32, 86400, ['trunk', 'branch', 'drooping-leaf']],
  rose: ['shrub', 10, 18, 64800, ['stem', 'thorn', 'rose-bloom']],
  hydrangea: ['shrub', 12, 20, 64800, ['stem', 'broadleaf', 'cluster-bloom']],
  ivy: ['vine', 12, 24, 43200, ['vine', 'ivy-leaf']],
  wisteria: ['vine', 14, 26, 43200, ['vine', 'drooping-bloom']],
  meadow_grass: ['grass', 8, 16, 21600, ['blade', 'seed-head']],
  lavender: ['herb', 9, 17, 32400, ['stem', 'narrow-leaf', 'lavender-bloom']],
  rosemary: ['herb', 9, 17, 32400, ['stem', 'needle-leaf', 'herb-bloom']],
  tulip: ['flower', 6, 10, 21600, ['stem', 'tulip-leaf', 'tulip-bloom']],
  sunflower: ['flower', 7, 12, 32400, ['stem', 'broadleaf', 'sunflower-bloom']],
  water_lily: ['aquatic', 7, 13, 43200, ['rhizome', 'lily-pad', 'water-bloom']],
});
// EMPTIED 2026-07-31, pending per-asset visual approval.
//
// The starter world used to place five plants, one cat and one collectible by
// default. The operator reviewed and accepted the ten fixtures; none of this
// content was ever submitted, and on seeing it in the scene they rejected it.
//
// The distinction that matters: this is not a capability removal. Every
// species above remains defined and placeable, and the catalogues below are
// untouched -- an author can still place any of them. What changes is that the
// DEFAULT scene no longer ships art nobody approved. Each entry returns here
// once its drawing has been through per-asset acceptance under SPEC 7.10.
//
// PARTIALLY REFILLED 2026-08-01 from the legacy art port. `oak` and `sunflower`
// are now drawn entirely from the archive the operator approved on that date --
// picture and wind sway both -- so they are approved art and stand in the
// default scene again. `hydrangea`, `meadow_grass` and `lavender` are not back:
// the archive does not draw them, so they would still be renderer-authored
// placeholders. The cat is not back because a resting cat would fall through to
// a renderer-authored sleeping pose, which the archive contains no version of.
//
// Must stay identical to `STARTER_*_SPECIES` in the Python generator; the world
// conformance tests hold both implementations to the same starter output.
export const STARTER_PLANT_SPECIES = Object.freeze(['rose']);
export const STARTER_ANIMAL_SPECIES = Object.freeze([]);
export const STARTER_COLLECTIBLES = Object.freeze([]);

// Exactly what the default scene carried until 2026-07-31, kept as a named set
// rather than deleted outright.
//
// Two reasons it earns a name. It records what was removed, so restoring an
// entry after its art is approved is a one-line move rather than an
// archaeological dig through history. And it gives the tests that exercise
// plant growth, animal behaviour and collectible pickup a way to ask for a
// populated world explicitly -- those features did not go away, only their
// unapproved presence in the DEFAULT scene did.
//
// Passing this to `generateInitialWorld` reproduces the pre-removal world
// exactly. It must never become the default again without per-asset approval.
// Keep in step with `REVIEW_PENDING_*` in the Python generator.
export const REVIEW_PENDING_PLANT_SPECIES = Object.freeze([
  'oak', 'hydrangea', 'meadow_grass', 'lavender', 'sunflower',
]);
export const REVIEW_PENDING_ANIMAL_SPECIES = Object.freeze(['cat']);
export const REVIEW_PENDING_COLLECTIBLES = Object.freeze(['fallen_acorn']);
// Canonical starter composition in thousandths of the world extent. Mirrors
// `STARTER_FIXTURE_ANCHORS` in the Python generator EXACTLY, including the
// authoritative starter row added on 2026-08-01; the reasoning for the shared
// depth and the even horizontal spacing is written out in full there. The five
// non-starter entries keep their original relationship anchors and are reached
// only through authored programs.
const STARTER_FIXTURE_ANCHORS = Object.freeze({
  pond: [180, 400], bridge: [180, 450], birdbath: [80, 720],
  trellis: [720, 450], arbor: [830, 700],
  // ── the authoritative starter row ──
  stepping_stones: [250, 650], bench: [375, 650], mailbox: [500, 650],
  lantern: [625, 650], planter: [750, 650],
});
// The exact operator-authored rose accepted 2026-08-03 is the canonical
// starter plant and owns the open left edge. See the Python generator for the
// rendered-overlap evidence and ownership reasoning.
const STARTER_PLANT_ANCHORS = Object.freeze({
  water_lily: [220, 420], oak: [150, 300], hydrangea: [360, 570],
  willow: [900, 180], rose: [60, 320], meadow_grass: [470, 590],
  lavender: [570, 760], sunflower: [850, 320],
});
const STARTER_ANIMAL_ANCHORS = Object.freeze({
  bird: [100, 680], cat: [350, 780], rabbit: [740, 520], turtle: [220, 500],
});
const STARTER_COLLECTIBLE_ANCHORS = Object.freeze({
  oak_leaf: [330, 290], lavender_sprig: [620, 650], fallen_acorn: [200, 790],
});

const ANIMAL_SPECIES = Object.freeze({
  bird: { affinities: ['fence', 'birdbath', 'trellis'],
    repertoire: ['perch', 'hop', 'sing', 'bathe', 'forage', 'greet'],
    dwell: { perch: 18, sing: 12, bathe: 15, hop: 8 } },
  cat: { affinities: ['bench', 'table', 'memory_shrine'],
    repertoire: ['patrol', 'sniff', 'nap', 'knead', 'play', 'greet'],
    dwell: { nap: 45, patrol: 20, knead: 14, play: 12 } },
  rabbit: { affinities: ['trellis', 'planter', 'bench'],
    repertoire: ['hop', 'forage', 'hide', 'groom', 'play', 'greet'],
    dwell: { groom: 20, hide: 30, hop: 10, play: 12 } },
  turtle: { affinities: ['pond', 'bridge', 'stepping_stone'],
    repertoire: ['walk', 'sunbathe', 'paddle', 'rest', 'forage', 'greet'],
    dwell: { sunbathe: 60, walk: 30, paddle: 35, rest: 45 } },
});

export function gardenCatalogHas(kind, value) {
  const catalogId = String(value ?? '').split('.').at(-1);
  if (kind === 'animal') return Object.hasOwn(ANIMAL_SPECIES, catalogId);
  if (kind === 'plant') return Object.hasOwn(SPECIES_CATALOG, catalogId);
  if (kind === 'fixture') return Object.hasOwn(FIXTURE_CATALOG, catalogId);
  return false;
}

const COLLECTIBLE_CATALOG = Object.freeze({
  oak_leaf: ['plant_species', 'recipient-grown', 'Oak leaf', "A leaf showing the oak's branching veins."],
  lavender_sprig: ['plant_species', 'recipient-grown', 'Lavender sprig', 'A fragrant sprig from a tended lavender plant.'],
  first_snowflake: ['seasonal_natural_find', 'procedural', 'First snowflake', "A remembered trace of the season's first snow."],
  fallen_acorn: ['seasonal_natural_find', 'procedural', 'Fallen acorn', 'A small autumn find beneath the trees.'],
  rabbit_track: ['animal_trace', 'animal-given', 'Rabbit track', 'A soft print where a rabbit paused.'],
  bird_feather: ['animal_trace', 'animal-given', 'Bird feather', 'A feather left near a favorite perch.'],
  pressed_flower: ['authored_keepsake', 'author-authored', 'Pressed flower', 'A flower preserved with an authored memory.'],
  small_key: ['authored_keepsake', 'author-authored', 'Small key', 'A keepsake key waiting without expiry.'],
});

const clone = value => globalThis.structuredClone
  ? globalThis.structuredClone(value)
  : JSON.parse(JSON.stringify(value));
/** Python-compatible Unicode scalar ordering for canonical semantic tie-breaks. */
export function compareCodePoints(leftValue, rightValue) {
  const left = Array.from(String(leftValue), character => character.codePointAt(0));
  const right = Array.from(String(rightValue), character => character.codePointAt(0));
  const count = Math.min(left.length, right.length);
  for (let index = 0; index < count; index += 1) {
    if (left[index] !== right[index]) return left[index] < right[index] ? -1 : 1;
  }
  return left.length === right.length ? 0 : left.length < right.length ? -1 : 1;
}
const integer = (value, fallback = 0) => {
  const parsed = Number(value ?? fallback);
  return Number.isFinite(parsed) ? Math.trunc(parsed) : Math.trunc(fallback);
};
const clamp = (value, low, high) => Math.max(low, Math.min(high, integer(value)));
const rotation = value => ((integer(value) % 360) + 360) % 360;
const optionalString = value => value ? String(value) : null;
const vec2 = (value = [0, 0]) => [integer(value[0]), integer(value[1])];
const uniqueSorted = values => [...new Set(values.map(String))].sort(compareCodePoints);
const sortBy = (values, field) => [...values].sort((left, right) =>
  compareCodePoints(left[field], right[field]));

function compactEventTrace(entries) {
  const liveIndexes = entries.map((entry, index) => entry.kind === 'live_tick' ? index : -1)
    .filter(index => index >= 0);
  const discarded = new Set(liveIndexes.slice(0, Math.max(0, liveIndexes.length - LIVE_TRACE_LIMIT)));
  return entries.filter((_, index) => !discarded.has(index)).slice(-EVENT_TRACE_LIMIT);
}

function normalizeOrgan(data) {
  return {
    node_id: String(data.node_id),
    parent_id: optionalString(data.parent_id),
    kind: String(data.kind),
    birth_time: integer(data.birth_time),
    maturity_time: integer(data.maturity_time),
    final_direction: vec2(data.final_direction),
    final_length: integer(data.final_length),
    glyph_family: String(data.glyph_family),
    bloom_state: optionalString(data.bloom_state),
  };
}

function normalizePlant(data) {
  return {
    plant_id: String(data.plant_id),
    species_id: String(data.species_id),
    position: vec2(data.position),
    topology: (data.topology ?? []).map(normalizeOrgan),
    growth_points: integer(data.growth_points, 0),
    tended_count: integer(data.tended_count, 0),
    last_tended_at: data.last_tended_at === null || data.last_tended_at === undefined
      ? null : integer(data.last_tended_at),
    growth_period_seconds: Math.max(1, integer(data.growth_period_seconds, 86400)),
    dormant: Boolean(data.dormant ?? false),
  };
}

function plantDetails(data) {
  const plant = normalizePlant(data);
  plant.topology = sortBy(plant.topology, 'node_id');
  return plant;
}

function normalizeFixture(data) {
  return {
    fixture_id: String(data.fixture_id),
    catalog_id: String(data.catalog_id),
    position: vec2(data.position),
    rotation: rotation(data.rotation ?? 0),
    authored: Boolean(data.authored ?? false),
    interaction_count: Math.max(0, integer(data.interaction_count, 0)),
    last_interaction: optionalString(data.last_interaction),
    authored_state: clone(data.authored_state ?? {}),
  };
}

function normalizePersonality(data = {}) {
  return Object.fromEntries(PERSONALITY_FIELDS.map(field => [
    field, clamp(data[field] ?? 50, 0, 100),
  ]));
}

function normalizeMemory(data) {
  return {
    memory_id: String(data.memory_id),
    kind: String(data.kind),
    target_id: optionalString(data.target_id),
    timestamp: integer(data.timestamp),
    valence: integer(data.valence, 0),
    salience: integer(data.salience, 0),
  };
}

function normalizeAnimal(data) {
  const counts = data.interaction_counts ?? {};
  const cooldowns = data.cooldowns ?? {};
  return {
    animal_id: String(data.animal_id),
    species_id: String(data.species_id),
    position: vec2(data.position),
    high_level_state: String(data.high_level_state ?? 'awake'),
    bond_points: Math.max(0, integer(data.bond_points, 0)),
    bond_tier: clamp(data.bond_tier ?? 0, 0, 3),
    interaction_counts: Object.fromEntries(
      Object.keys(counts).sort().map(key => [String(key), integer(counts[key])]),
    ),
    session_interactions: (data.session_interactions ?? []).map(String),
    recent_memories: (data.recent_memories ?? []).map(normalizeMemory),
    personality: normalizePersonality(data.personality),
    energy: clamp(data.energy ?? 60, 0, 100),
    social_appetite: clamp(data.social_appetite ?? 50, 0, 100),
    play_appetite: clamp(data.play_appetite ?? 50, 0, 100),
    rest_appetite: clamp(data.rest_appetite ?? 40, 0, 100),
    choreography_lock: optionalString(data.choreography_lock),
    current_intent: String(data.current_intent ?? 'idle'),
    intent_started_at: Math.max(0, integer(data.intent_started_at, 0)),
    minimum_dwell_until: Math.max(0, integer(data.minimum_dwell_until, 0)),
    decision_index: Math.max(0, integer(data.decision_index, 0)),
    cooldowns: Object.fromEntries(
      Object.keys(cooldowns).sort().map(key => [String(key), integer(cooldowns[key])]),
    ),
    favorite_fixture_ids: uniqueSorted(data.favorite_fixture_ids ?? []),
    authored_preferences: uniqueSorted(data.authored_preferences ?? []),
    authored_prohibitions: uniqueSorted(data.authored_prohibitions ?? []),
    display_name: optionalString(data.display_name),
    personality_note: optionalString(data.personality_note),
  };
}

function normalizeCollectible(data) {
  return {
    collectible_id: String(data.collectible_id),
    family: String(data.family),
    provenance: String(data.provenance),
    label: String(data.label),
    description: String(data.description),
    position: vec2(data.position),
    collected: Boolean(data.collected ?? false),
    authored: Boolean(data.authored ?? false),
  };
}

function normalizeJournal(data) {
  return {
    entry_id: String(data.entry_id),
    object_id: String(data.object_id),
    status: String(data.status),
    label: String(data.label),
    description: String(data.description),
    discovered_at: integer(data.discovered_at),
  };
}

function normalizeUi(data = {}) {
  return {
    focus_id: optionalString(data.focus_id),
    camera: vec2(data.camera ?? [0, 0]),
    actions_open_for: optionalString(data.actions_open_for),
    journal_open: Boolean(data.journal_open ?? false),
    motion_paused: Boolean(data.motion_paused ?? false),
  };
}

function normalizeUndo(data) {
  return {
    kind: String(data.kind),
    object_id: String(data.object_id),
    previous_position: data.previous_position ? vec2(data.previous_position) : null,
    previous_rotation: data.previous_rotation === null || data.previous_rotation === undefined
      ? null : integer(data.previous_rotation),
    created: Boolean(data.created ?? false),
  };
}

function normalizeTrace(data) {
  return {
    trace_id: String(data.trace_id),
    sequence: integer(data.sequence),
    kind: String(data.kind),
    target_id: optionalString(data.target_id),
    effective_time: integer(data.effective_time),
    summary: String(data.summary),
  };
}

/**
 * Read an integer that is allowed to be genuinely absent.
 *
 * `null` is preserved rather than coerced to a number, because for the version
 * stamps "not recorded" and "recorded as zero" are different facts about a
 * stored world and only one of them is true.
 *
 * @param {unknown} value - whatever the stored document held under the key
 * @returns {number|null} the integer, or null when absent or explicitly null
 */
function optionalInteger(value) {
  if (value === null || value === undefined) return null;
  return integer(value);
}

export function deserializeWorldState(raw) {
  const data = typeof raw === 'string' ? JSON.parse(raw) : raw;
  const schemaVersion = integer(data.schema_version, 0);
  if (schemaVersion !== WORLD_SCHEMA_VERSION) {
    throw new Error(`unsupported Garden world schema ${schemaVersion}`);
  }
  return {
    schema_version: schemaVersion,
    engine_version: String(data.engine_version ?? ENGINE_VERSION),
    // Absent stays absent. Defaulting these to the current constants would
    // make every world stored before they existed claim to be today's, which
    // is how a persisted 13/22/4/8 world came to be reviewed as the current
    // 8/10/4/3 starter. See src/lateletter/garden/world/provenance.py.
    generator_version: optionalInteger(data.generator_version),
    composition_version: optionalInteger(data.composition_version),
    composition_fingerprint:
      data.composition_fingerprint === null || data.composition_fingerprint === undefined
        ? null : String(data.composition_fingerprint),
    migrated_from_schema: optionalInteger(data.migrated_from_schema),
    world_id: String(data.world_id),
    seed: String(data.seed),
    world_width: Math.max(1, integer(data.world_width, 120)),
    world_height: Math.max(1, integer(data.world_height, 80)),
    effective_time: Math.max(0, integer(data.effective_time, 0)),
    last_observed_wall_time:
      data.last_observed_wall_time === null || data.last_observed_wall_time === undefined
        ? null : integer(data.last_observed_wall_time),
    command_sequence: Math.max(0, integer(data.command_sequence, 0)),
    plants: (data.plants ?? []).map(normalizePlant),
    fixtures: (data.fixtures ?? []).map(normalizeFixture),
    animals: (data.animals ?? []).map(normalizeAnimal),
    collectibles: (data.collectibles ?? []).map(normalizeCollectible),
    inventory: (data.inventory ?? []).map(String),
    journal: (data.journal ?? []).map(normalizeJournal),
    ui: normalizeUi(data.ui),
    undo_stack: (data.undo_stack ?? []).map(normalizeUndo).slice(-UNDO_STACK_LIMIT),
    milestone_receipts: compactRecentStrings(
      (data.milestone_receipts ?? []).map(String), MILESTONE_RECEIPT_LIMIT,
    ),
    program_state: clone(data.program_state ?? {}),
    processed_commands: (data.processed_commands ?? []).map(String)
      .slice(-PROCESSED_COMMAND_LIMIT),
    event_trace: compactEventTrace((data.event_trace ?? []).map(normalizeTrace)),
  };
}

export function serializeWorldState(state) {
  return {
    schema_version: integer(state.schema_version),
    engine_version: String(state.engine_version),
    generator_version: optionalInteger(state.generator_version),
    composition_version: optionalInteger(state.composition_version),
    composition_fingerprint:
      state.composition_fingerprint === null || state.composition_fingerprint === undefined
        ? null : String(state.composition_fingerprint),
    migrated_from_schema: optionalInteger(state.migrated_from_schema),
    world_id: String(state.world_id),
    seed: String(state.seed),
    world_width: integer(state.world_width),
    world_height: integer(state.world_height),
    effective_time: integer(state.effective_time),
    last_observed_wall_time: state.last_observed_wall_time === null
      ? null : integer(state.last_observed_wall_time),
    command_sequence: integer(state.command_sequence),
    plants: sortBy(state.plants.map(normalizePlant), 'plant_id').map(plant => ({
      ...plant,
      topology: sortBy(plant.topology, 'node_id'),
    })),
    fixtures: sortBy(state.fixtures.map(normalizeFixture), 'fixture_id'),
    animals: sortBy(state.animals.map(normalizeAnimal), 'animal_id'),
    collectibles: sortBy(state.collectibles.map(normalizeCollectible), 'collectible_id'),
    inventory: uniqueSorted(state.inventory),
    journal: sortBy(state.journal.map(normalizeJournal), 'entry_id'),
    ui: normalizeUi(state.ui),
    undo_stack: state.undo_stack.map(normalizeUndo).slice(-UNDO_STACK_LIMIT),
    milestone_receipts: compactRecentStrings(
      state.milestone_receipts, MILESTONE_RECEIPT_LIMIT,
    ),
    program_state: clone(state.program_state ?? {}),
    processed_commands: state.processed_commands.map(String).slice(-PROCESSED_COMMAND_LIMIT),
    event_trace: compactEventTrace(state.event_trace.map(normalizeTrace)),
  };
}

export function canonicalWorldJson(state) {
  return canonicalJson(serializeWorldState(state));
}

export function worldStateBytes(state) {
  return new TextEncoder().encode(canonicalWorldJson(state));
}

export async function newGardenWorld(
  worldId,
  seed,
  { world_width = 120, world_height = 80 } = {},
) {
  const seedDigest = await sha256Hex(canonicalJson(['world-seed', String(seed)]));
  return deserializeWorldState({
    schema_version: WORLD_SCHEMA_VERSION,
    engine_version: ENGINE_VERSION,
    // Deliberately UNSTAMPED. `newGardenWorld` returns an EMPTY world -- no
    // plants, fixtures, animals or collectibles -- and stamping it here
    // declared 0/0/0/0 to be a whole composition. The stamps belong at the end
    // of successful starter generation, where there is a population to
    // describe; see `generateInitialWorld`.
    world_id: String(worldId),
    seed: seedDigest,
    world_width: Math.max(1, integer(world_width)),
    world_height: Math.max(1, integer(world_height)),
  });
}

const ZERO_REPLACEMENT = 0x6d2b79f5;

async function deriveSeed(rootSeed, ...domain) {
  const digest = await sha256Hex(canonicalJson([
    'lateletter-garden-rng-v1', String(rootSeed), ...domain,
  ]));
  const value = Number.parseInt(digest.slice(0, 8), 16) >>> 0;
  return value || ZERO_REPLACEMENT;
}

class DeterministicRng {
  constructor(seed) { this.state = (Number(seed) >>> 0) || ZERO_REPLACEMENT; }
  nextU32() {
    let value = this.state >>> 0;
    value = (value ^ ((value << 13) >>> 0)) >>> 0;
    value = (value ^ (value >>> 17)) >>> 0;
    value = (value ^ ((value << 5) >>> 0)) >>> 0;
    this.state = value >>> 0;
    return this.state;
  }
  randbelow(stop) {
    if (!Number.isInteger(stop) || stop <= 0) throw new Error('stop must be positive');
    const limit = 0x100000000 - (0x100000000 % stop);
    for (;;) {
      const value = this.nextU32();
      if (value < limit) return value % stop;
    }
  }
  randint(start, stop) {
    if (stop < start) throw new Error('stop must be >= start');
    return start + this.randbelow(stop - start + 1);
  }
  choice(values) {
    if (!values.length) throw new Error('cannot choose from an empty sequence');
    return values[this.randbelow(values.length)];
  }
}

async function shuffled(values, rng) {
  const output = [...values];
  for (let index = output.length - 1; index > 0; index -= 1) {
    const swap = rng.randbelow(index + 1);
    [output[index], output[swap]] = [output[swap], output[index]];
  }
  return output;
}

function organKind(definition, index, total) {
  const [category, , , , glyphs] = definition;
  const progress = index / Math.max(1, total - 1);
  if (category === 'tree' || category === 'shrub') {
    if (progress < 0.28) return 'stem';
    if (progress < 0.68) return 'branch';
    return glyphs.at(-1).includes('bloom') ? 'bloom' : 'leaf';
  }
  if (category === 'vine') return index % 3 ? 'vine' : 'leaf';
  if (category === 'aquatic') return progress > 0.8 ? 'bloom' : 'leaf';
  if (progress < 0.45) return 'stem';
  return progress > 0.82 ? 'bloom' : 'leaf';
}

async function generateTopology(worldSeed, plantId, speciesId, plantedAt = 0) {
  const definition = SPECIES_CATALOG[speciesId];
  const structure = new DeterministicRng(await deriveSeed(
    worldSeed, 'plant', plantId, 'topology', 'structure',
  ));
  const timing = new DeterministicRng(await deriveSeed(
    worldSeed, 'plant', plantId, 'topology', 'timing',
  ));
  const styling = new DeterministicRng(await deriveSeed(
    worldSeed, 'plant', plantId, 'topology', 'style',
  ));
  const [, minimum, maximum, , glyphs] = definition;
  const total = structure.randint(minimum, maximum);
  const rootId = await stableId('organ', plantId, 'root');
  const nodes = [normalizeOrgan({
    node_id: rootId, parent_id: null, kind: 'root', birth_time: plantedAt,
    maturity_time: plantedAt, final_direction: [0, -1], final_length: 1,
    glyph_family: 'root', bloom_state: null,
  })];
  for (let index = 1; index < total; index += 1) {
    const kind = organKind(definition, index, total);
    const parentIndex = definition[0] === 'vine' || index < 4
      ? index - 1 : structure.randbelow(index);
    const parent = nodes[parentIndex];
    let direction = [structure.randint(-1, 1), -structure.randint(0, 1)];
    if (direction[0] === 0 && direction[1] === 0) direction = [0, -1];
    const birth = plantedAt + index * timing.randint(2700, 7200);
    const maturity = birth + timing.randint(3600, 14400);
    nodes.push(normalizeOrgan({
      node_id: await stableId('organ', plantId, index, kind, parent.node_id),
      parent_id: parent.node_id, kind, birth_time: birth, maturity_time: maturity,
      final_direction: direction, final_length: structure.randint(1, 4),
      glyph_family: styling.choice(glyphs),
      bloom_state: kind === 'bloom' ? 'bud' : null,
    }));
  }
  return nodes;
}

function advanceTopology(plant, effectiveTime, milestones) {
  const count = Math.max(0, integer(milestones));
  if (!count) return plant;
  const selected = new Set([...plant.topology]
    .filter(node => node.birth_time > effectiveTime)
    .sort((left, right) => left.birth_time - right.birth_time ||
      compareCodePoints(left.node_id, right.node_id))
    .slice(0, count).map(node => node.node_id));
  plant.topology = plant.topology.map(node => selected.has(node.node_id) ? {
    ...node,
    birth_time: effectiveTime,
    maturity_time: Math.max(effectiveTime, Math.min(node.maturity_time, effectiveTime + 3600)),
  } : node);
  return plant;
}

function careForPlant(plant, effectiveTime, care) {
  if (!['observe', 'water', 'prune', 'train', 'rest'].includes(care)) {
    throw new Error(`unsupported care action ${care}`);
  }
  if (care === 'observe') return plant;
  let gain = 0;
  let dormant = care === 'rest';
  if (care === 'water') {
    gain = 2; dormant = false; advanceTopology(plant, effectiveTime, gain);
  } else if (care === 'prune') {
    const candidates = plant.topology.filter(node =>
      node.birth_time <= effectiveTime && ['leaf', 'bloom', 'branch', 'vine'].includes(node.kind))
      .sort((left, right) => left.birth_time - right.birth_time || compareCodePoints(left.node_id, right.node_id));
    const chosen = candidates.at(-1);
    if (chosen && !chosen.glyph_family.startsWith('shaped-')) chosen.glyph_family = `shaped-${chosen.glyph_family}`;
    gain = 1; dormant = false;
  } else if (care === 'train') {
    const candidates = plant.topology.filter(node => node.parent_id !== null)
      .sort((left, right) => left.birth_time - right.birth_time || compareCodePoints(left.node_id, right.node_id));
    const chosen = candidates[Math.min(candidates.length - 1, plant.tended_count % candidates.length)];
    if (chosen) chosen.final_direction = [plant.tended_count % 2 === 0 ? 1 : -1, -1];
    gain = 2; dormant = false;
  }
  plant.growth_points += gain;
  plant.tended_count += 1;
  plant.last_tended_at = effectiveTime;
  plant.dormant = dormant;
  return plant;
}

async function freePosition(state, domain, occupied, margin = 2) {
  const rng = new DeterministicRng(await deriveSeed(state.seed, 'layout', ...domain));
  for (let attempt = 0; attempt < 512; attempt += 1) {
    const candidate = [
      rng.randint(margin, state.world_width - margin - 1),
      rng.randint(margin, state.world_height - margin - 1),
    ];
    if (!occupied.has(cellKey(candidate))) {
      occupied.add(cellKey(candidate));
      return candidate;
    }
  }
  throw new Error(`could not place ${canonicalJson(domain)} safely`);
}

function scaledStarterAnchor(state, anchor, margin = 2, footprint = [1, 1]) {
  const maxX = Math.max(margin, state.world_width - footprint[0] - margin);
  const maxY = Math.max(margin, state.world_height - footprint[1] - margin);
  const spanX = Math.max(0, maxX - margin);
  const spanY = Math.max(0, maxY - margin);
  return [
    margin + Math.floor((spanX * anchor[0] + 500) / 1000),
    margin + Math.floor((spanY * anchor[1] + 500) / 1000),
  ];
}

function nearStarterPosition(state, desired, occupied, margin = 2) {
  const maximumRadius = Math.max(state.world_width, state.world_height);
  for (let radius = 0; radius <= maximumRadius; radius += 1) {
    for (let dy = -radius; dy <= radius; dy += 1) {
      const dxAbs = radius - Math.abs(dy);
      const offsets = dxAbs === 0 ? [0] : [-dxAbs, dxAbs];
      for (const dx of offsets) {
        const candidate = [desired[0] + dx, desired[1] + dy];
        if (candidate[0] < margin || candidate[0] >= state.world_width - margin ||
          candidate[1] < margin || candidate[1] >= state.world_height - margin) continue;
        const key = cellKey(candidate);
        if (!occupied.has(key)) {
          occupied.add(key);
          return candidate;
        }
      }
    }
  }
  throw new Error(`could not place a starter object near ${canonicalJson(desired)}`);
}

/**
 * Reject a starter roster this generator cannot honour, before it is used.
 *
 * Three things go wrong quietly without this check, so each becomes a loud
 * error naming the offending id:
 *
 * - An UNKNOWN id used to surface as a `TypeError` reading a property of
 *   `undefined` from the anchor lookup further down -- a crash with no
 *   statement of what was actually wrong.
 * - An UNSUPPORTED id -- one that exists in its catalogue but has no canonical
 *   anchor here -- failed the same opaque way. Placement is not a free choice:
 *   every starter sits at an authored position expressing a relationship
 *   between objects, so a species with no anchor genuinely cannot be placed by
 *   this generator, and saying so is more honest than inventing a spot.
 * - A DUPLICATE id was accepted outright, and that is the dangerous one. Every
 *   object id here is `stableId(kind, worldId, speciesId)`, a pure function of
 *   the species -- so asking for a species twice produced two records SHARING
 *   one id. Anything keyed by object id afterwards (focus, dispatch,
 *   persistence) would then address an ambiguous target.
 *
 * @param kind Noun used in the error message, e.g. `'plant species'`.
 * @param requested The roster as asked for, already normalised to an array.
 * @param anchors Anchor table for this kind; its keys are the supported ids.
 * @returns `requested` unchanged, so callers can use this inline.
 * @throws {Error} On any unknown, unsupported or duplicated id.
 *
 * Kept textually in step with `_validated_roster` in
 * `src/lateletter/garden/world/generation.py`: both implementations must
 * refuse the same rosters for the same reasons.
 */
function validatedRoster(kind, requested, anchors) {
  const seen = new Set();
  const supported = Object.keys(anchors).sort();
  for (const identifier of requested) {
    if (seen.has(identifier)) {
      throw new Error(`duplicate ${kind} requested: '${identifier}'`);
    }
    seen.add(identifier);
    if (!Object.hasOwn(anchors, identifier)) {
      throw new Error(
        `unsupported ${kind} requested: '${identifier}' `
        + `(supported: ${supported.join(', ')})`,
      );
    }
  }
  return requested;
}

/** Generate the same canonical initial state as Python; viewport is never input. */
/**
 * Generate canonical world coordinates; viewport size is not an input.
 *
 * `plant_species`, `animal_species` and `collectibles` exist because the
 * default starter lists were emptied on 2026-07-31: their art had never been
 * through per-asset visual approval, and the operator rejected it on sight.
 * The CAPABILITY had to survive that removal -- plant growth, animal behaviour
 * and collectible pickup are still real features with real tests, and those
 * tests need a world that actually contains such things.
 *
 * So the default answers "what does a recipient see", which is currently only
 * approved fixtures, while a caller that needs populated content asks for it
 * explicitly. `null`/`undefined` means "use the default scene"; an explicit
 * empty array means "deliberately none", and the two stay distinguishable.
 *
 * Keep these options in step with `generate_initial_world` in
 * `src/lateletter/garden/world/generation.py`; the two implementations are
 * held to identical output by the world conformance tests.
 */
export async function generateInitialWorld(
  worldId, seed, {
    world_width = 120, world_height = 80,
    plant_species = null, animal_species = null, collectibles = null,
  } = {},
) {
  // Validated before anything is placed, so a bad roster fails with a clear
  // message instead of a partial world or a duplicated object id.
  const requestedPlants = validatedRoster('plant species',
    plant_species === null || plant_species === undefined
      ? STARTER_PLANT_SPECIES : [...plant_species], STARTER_PLANT_ANCHORS);
  const requestedAnimals = validatedRoster('animal species',
    animal_species === null || animal_species === undefined
      ? STARTER_ANIMAL_SPECIES : [...animal_species], STARTER_ANIMAL_ANCHORS);
  const requestedCollectibles = validatedRoster('collectible',
    collectibles === null || collectibles === undefined
      ? STARTER_COLLECTIBLES : [...collectibles], STARTER_COLLECTIBLE_ANCHORS);
  if (world_width < MINIMUM_WORLD_WIDTH || world_height < MINIMUM_WORLD_HEIGHT) {
    throw new Error(`canonical world must be at least ${MINIMUM_WORLD_WIDTH}x${MINIMUM_WORLD_HEIGHT}`);
  }
  const state = await newGardenWorld(worldId, seed, { world_width, world_height });
  const fixtureRng = new DeterministicRng(await deriveSeed(
    state.seed, 'layout', 'fixtures',
  ));
  state.fixtures = [];
  const fixtureCellsUsed = new Set();
  for (const catalogId of STARTER_FIXTURES) {
    const fixture = normalizeFixture({
      fixture_id: await stableId('fixture', state.world_id, catalogId),
      catalog_id: catalogId,
      position: scaledStarterAnchor(
        state, STARTER_FIXTURE_ANCHORS[catalogId], 2,
        FIXTURE_CATALOG[catalogId].footprint,
      ),
      rotation: fixtureRng.randbelow(4) * 90,
      authored: false,
    });
    const cells = fixtureCells(fixture).map(cellKey);
    if (cells.some(cell => fixtureCellsUsed.has(cell))) {
      throw new Error(`starter fixture anchors overlap: ${catalogId}`);
    }
    cells.forEach(cell => fixtureCellsUsed.add(cell));
    state.fixtures.push(fixture);
  }
  const occupied = new Set(state.fixtures.flatMap(fixtureCells).map(cellKey));
  const plantAgeRng = new DeterministicRng(await deriveSeed(
    state.seed, 'layout', 'plant-ages',
  ));
  for (const speciesId of requestedPlants) {
    const plantId = await stableId('plant', state.world_id, speciesId);
    const desired = scaledStarterAnchor(
      state, STARTER_PLANT_ANCHORS[speciesId], 3,
    );
    const position = nearStarterPosition(state, desired, occupied, 3);
    // Select age from the plant's own topology so every starter has at least
    // four visible organs and at least one unborn organ in both runtimes.
    const previewTopology = await generateTopology(state.seed, plantId, speciesId, 0);
    const birthTimes = [...new Set(previewTopology.map(node => node.birth_time))]
      .sort((left, right) => left - right);
    const minimumVisible = Math.max(
      4, Math.floor((previewTopology.length * 55 + 99) / 100),
    );
    const maximumVisible = Math.max(
      minimumVisible, Math.floor(previewTopology.length * 85 / 100),
    );
    const eligibleAges = birthTimes.filter(age => {
      const count = previewTopology.filter(node => node.birth_time <= age).length;
      return count >= minimumVisible && count <= maximumVisible;
    });
    if (!eligibleAges.length) throw new Error(
      `starter topology has no partial established age: ${plantId}`,
    );
    const plantedAt = -plantAgeRng.choice(eligibleAges);
    state.plants.push(normalizePlant({
      plant_id: plantId, species_id: speciesId, position,
      topology: await generateTopology(state.seed, plantId, speciesId, plantedAt),
      growth_period_seconds: SPECIES_CATALOG[speciesId][3],
    }));
  }
  const blocked = new Set([...occupied, ...state.plants.map(item => cellKey(item.position))]);
  for (const speciesId of requestedAnimals) {
    const animalId = await stableId('animal', state.world_id, speciesId);
    const desired = scaledStarterAnchor(
      state, STARTER_ANIMAL_ANCHORS[speciesId], 2,
    );
    const position = nearStarterPosition(state, desired, blocked, 2);
    const personalityRng = new DeterministicRng(await deriveSeed(
      state.seed, 'animal', animalId, 'personality',
    ));
    state.animals.push(normalizeAnimal({
      animal_id: animalId, species_id: speciesId, position,
      personality: Object.fromEntries(PERSONALITY_FIELDS.map(field => [
        field, personalityRng.randint(20, 80),
      ])),
    }));
  }
  for (const catalogId of requestedCollectibles) {
    const collectibleId = await stableId('collectible', state.world_id, catalogId);
    const desired = scaledStarterAnchor(
      state, STARTER_COLLECTIBLE_ANCHORS[catalogId], 2,
    );
    const position = nearStarterPosition(state, desired, blocked, 2);
    const [family, provenance, label, description] = COLLECTIBLE_CATALOG[catalogId];
    state.collectibles.push(normalizeCollectible({
      collectible_id: collectibleId, family, provenance, label, description,
      position, authored: family === 'authored_keepsake',
    }));
  }
  if (!layoutIsSafe(state)) throw new Error('generated Garden layout failed safety validation');
  state.ui.camera = scaledStarterAnchor(state, [500, 650], 0);

  // Stamp the composition ONLY here, at the end, after every placement has
  // succeeded and the layout has been validated. Every exit above this line is
  // a thrown error, so a partially generated world can never carry a stamp.
  // The fingerprint is what makes the version number evidence instead of an
  // assertion: a custom roster, or a world an author program later changes,
  // stops matching its own stamp.
  state.generator_version = GENERATOR_VERSION;
  // COMPOSITION_VERSION names ONE candidate composition -- the declared
  // starter. A world generated from a custom roster is a different
  // composition, so it gets null: it belongs to no named candidate. Without
  // this, every successful generation stamped the same revision, so a one-oak
  // roster read as the current composition and a fresh-composition review guard
  // would have accepted it. A number every roster receives identifies nothing.
  const isDeclaredStarter = (
    JSON.stringify([...requestedPlants]) === JSON.stringify([...STARTER_PLANT_SPECIES])
    && JSON.stringify([...requestedAnimals]) === JSON.stringify([...STARTER_ANIMAL_SPECIES])
    && JSON.stringify([...requestedCollectibles]) === JSON.stringify([...STARTER_COLLECTIBLES])
  );
  state.composition_version = isDeclaredStarter ? COMPOSITION_VERSION : null;
  // Recorded either way: a custom world should still be able to say its
  // contents have not changed since it was generated.
  state.composition_fingerprint = compositionFingerprint(state);
  return deserializeWorldState(serializeWorldState(state));
}

function objectIds(state) {
  return [
    ...state.plants.map(item => item.plant_id),
    ...state.fixtures.map(item => item.fixture_id),
    ...state.animals.map(item => item.animal_id),
    ...state.collectibles.filter(item => !item.collected).map(item => item.collectible_id),
  ].sort();
}

/**
 * Canonical position of any focusable object, or null if there is no such id.
 *
 * Focus moving "to the right" is a question about where things STAND, and
 * canonical coordinates are the only place that is defined. Kept beside
 * `objectIds` so the two stay in step: an object that can be focused must be
 * one this can locate.
 *
 * Mirrored by `_object_position` in `src/lateletter/garden/world/engine.py`.
 *
 * @param state canonical world state
 * @param objectId id of a plant, fixture, animal or uncollected collectible
 * @returns `[x, y]` or null
 */
function objectPosition(state, objectId) {
  for (const [items, key] of [
    [state.plants, 'plant_id'], [state.fixtures, 'fixture_id'],
    [state.animals, 'animal_id'], [state.collectibles, 'collectible_id'],
  ]) {
    const found = items.find(item => item[key] === objectId);
    if (found) return [Number(found.position[0]), Number(found.position[1])];
  }
  return null;
}

/**
 * The nearest focusable object in one compass direction, or null if none.
 *
 * SPATIAL FOCUS. `move_focus` has always accepted `left`, `right`, `up` and
 * `down`, and always treated them as aliases for previous/next over id order --
 * so "left" and "up" were the same operation, and neither had anything to do
 * with where the object was. The destination requires keyboard navigation to
 * move canonical focus spatially, and a command whose argument names a
 * direction should honour it.
 *
 * Candidates are objects strictly beyond the origin on the primary axis. The
 * winner minimises, in order: distance along that axis, then distance across
 * it, then object id. The third term is what makes this deterministic rather
 * than merely usually-agreeing, which matters because the browser and the
 * canonical Python engine are held to identical output.
 *
 * `next` and `previous` keep their ring behaviour: they are what `[`, `]` and
 * the terminal's cycle command mean, and a ring is the correct model for
 * "show me each thing in turn".
 *
 * Mirrored by `_spatial_focus` in `src/lateletter/garden/world/engine.py`.
 *
 * @param state canonical world state
 * @param ids focusable ids, already sorted
 * @param from id currently focused
 * @param direction one of left, right, up, down
 * @returns the id to focus, or null when nothing lies that way
 */
function spatialFocus(state, ids, from, direction) {
  const origin = objectPosition(state, from);
  if (!origin) return null;
  // Screen axes: x grows right, y grows down into the scene.
  const axis = direction === 'left' || direction === 'right' ? 0 : 1;
  const sign = direction === 'right' || direction === 'down' ? 1 : -1;
  let best = null, bestKey = null;
  for (const candidate of ids) {
    if (candidate === from) continue;
    const position = objectPosition(state, candidate);
    if (!position) continue;
    const along = (position[axis] - origin[axis]) * sign;
    if (along <= 0) continue;
    const across = Math.abs(position[1 - axis] - origin[1 - axis]);
    const key = [along, across, candidate];
    if (
      bestKey === null || key[0] < bestKey[0] ||
      (key[0] === bestKey[0] && key[1] < bestKey[1]) ||
      (key[0] === bestKey[0] && key[1] === bestKey[1] && key[2] < bestKey[2])
    ) {
      best = candidate; bestKey = key;
    }
  }
  return best;
}

function objectKind(state, objectId) {
  if (state.plants.some(item => item.plant_id === objectId)) return 'plant';
  if (state.fixtures.some(item => item.fixture_id === objectId)) return 'fixture';
  if (state.animals.some(item => item.animal_id === objectId)) return 'animal';
  if (state.collectibles.some(item => item.collectible_id === objectId)) return 'collectible';
  return null;
}

function availableActions(state, objectId) {
  const kind = objectKind(state, objectId);
  if (kind === 'plant') return ['inspect', 'observe', 'water', 'prune', 'train', 'transplant', 'rest'];
  if (kind === 'fixture') {
    const fixture = state.fixtures.find(item => item.fixture_id === objectId);
    return ['inspect', ...FIXTURE_VERBS[fixture.catalog_id], 'move', 'rotate'];
  }
  if (kind === 'animal') return ['inspect', 'feed', 'play'];
  if (kind === 'collectible') {
    const item = state.collectibles.find(candidate => candidate.collectible_id === objectId);
    return item.collected ? ['inspect'] : ['inspect', 'collect'];
  }
  return [];
}

function reject(reason) {
  return {
    accepted: false,
    changed: false,
    reason,
    summary: '',
    available_actions: [],
    details: null,
  };
}

async function animalUtility(state, animal, intent, context) {
  let score = 20;
  const personality = animal.personality;
  if (['play', 'hop', 'knead', 'flop'].some(token => intent.includes(token))) score += personality.playfulness + animal.play_appetite;
  if (['patrol', 'sniff', 'forage', 'walk', 'paddle', 'explore'].some(token => intent.includes(token))) score += personality.curiosity;
  if (['greet', 'song', 'sing', 'approach'].some(token => intent.includes(token))) score += personality.sociability + animal.bond_tier * 12;
  if (['rest', 'nap', 'sunbathe', 'perch', 'groom', 'hide', 'settled'].some(token => intent.includes(token))) score += animal.rest_appetite + Math.max(0, 60 - animal.energy);
  if (intent === 'forage') score += personality.food_motivation;
  if (animal.authored_preferences.includes(intent)) score += 60;
  const required = INTENT_AFFORDANCE_REQUIREMENTS[intent] ?? [];
  if (required.length && !required.some(value => context.nearby_affordances.includes(value))) score -= 2000;
  if (ANIMAL_SPECIES[animal.species_id].affinities.some(value =>
    context.nearby_affordances.includes(value))) score += 20;
  if ((animal.cooldowns[intent] ?? 0) > context.effective_time) score -= 1000;
  const recent = [...animal.recent_memories].sort((left, right) =>
    left.timestamp - right.timestamp || compareCodePoints(left.memory_id, right.memory_id))
    .slice(-RECENT_MEMORY_LIMIT);
  for (const memory of recent) {
    const tokens = MEMORY_INTENT_TOKENS[memory.kind] ?? [];
    if (tokens.length && tokens.some(token => intent.includes(token))) {
      const magnitude = 8 + Math.min(12, Math.floor(Math.max(0, memory.salience) / 10));
      score += memory.valence >= 0 ? magnitude : -magnitude;
    }
  }
  const weather = String(context.weather).toLocaleLowerCase('und');
  if (['rain', 'heavy_rain', 'storm'].includes(weather)) {
    if (['bathe', 'hide', 'nap', 'paddle', 'rest'].some(token => intent.includes(token))) score += 35;
    if (['play', 'sing', 'sunbathe'].some(token => intent.includes(token))) score -= 35;
  } else if (['clear', 'sunny'].includes(weather)) {
    if (['play', 'sing', 'sunbathe'].some(token => intent.includes(token))) score += 25;
  } else if (['cold', 'snow', 'blizzard'].includes(weather)) {
    if (['hide', 'nap', 'rest', 'settled'].some(token => intent.includes(token))) score += 40;
    if (['bathe', 'paddle', 'sunbathe'].some(token => intent.includes(token))) score -= 40;
  }
  const seasonTokens = SEASON_INTENT_TOKENS[String(context.season).toLocaleLowerCase('und')] ?? [];
  if (seasonTokens.some(token => intent.includes(token))) score += 30;
  const noise = new DeterministicRng(await deriveSeed(
    state.seed, 'animal', animal.animal_id, 'utility', animal.decision_index, intent,
  )).randint(0, 9);
  return score + noise;
}

function animalTargetCells(state, animal, intent) {
  const desired = new Set([
    ...(INTENT_AFFORDANCE_REQUIREMENTS[intent] ?? []),
    ...ANIMAL_SPECIES[animal.species_id].affinities,
  ]);
  const candidates = state.fixtures.filter(fixture => {
    const active = new Set([fixture.catalog_id, ...fixtureActiveAffordances(fixture)]);
    return [...desired].some(value => active.has(value));
  });
  if (!candidates.length) return [];
  candidates.sort((left, right) => {
    const leftDistance = Math.min(...fixtureCells(left).map(cell =>
      Math.abs(animal.position[0] - cell[0]) + Math.abs(animal.position[1] - cell[1])));
    const rightDistance = Math.min(...fixtureCells(right).map(cell =>
      Math.abs(animal.position[0] - cell[0]) + Math.abs(animal.position[1] - cell[1])));
    return leftDistance - rightDistance || compareCodePoints(left.fixture_id, right.fixture_id);
  });
  return fixtureCells(candidates[0]).sort((left, right) =>
    left[1] - right[1] || left[0] - right[0]);
}

async function moveGardenAnimal(state, animal, decision) {
  if (decision.high_level_state !== 'awake' ||
    !MOVING_INTENT_TOKENS.some(token => decision.intent.includes(token))) return animal;
  const rng = new DeterministicRng(await deriveSeed(
    state.seed, 'animal', animal.animal_id, 'locomotion', animal.decision_index, decision.intent,
  ));
  const rotationIndex = rng.randbelow(CARDINAL_STEPS.length);
  const steps = [...CARDINAL_STEPS.slice(rotationIndex), ...CARDINAL_STEPS.slice(0, rotationIndex)];
  const targets = animalTargetCells(state, animal, decision.intent);
  const blockers = blockedCells(state);
  const otherAnimals = new Set(state.animals.filter(item => item.animal_id !== animal.animal_id)
    .map(item => cellKey(item.position)));
  const ranked = [];
  steps.forEach((step, rank) => {
    const candidate = [animal.position[0] + step[0], animal.position[1] + step[1]];
    if (!insideWorld(state, candidate) || blockers.has(cellKey(candidate)) ||
      otherAnimals.has(cellKey(candidate))) return;
    const distance = targets.length ? Math.min(...targets.map(cell =>
      Math.abs(candidate[0] - cell[0]) + Math.abs(candidate[1] - cell[1]))) : 0;
    ranked.push([distance, rank, candidate]);
  });
  ranked.sort((left, right) => left[0] - right[0] || left[1] - right[1]);
  for (const [, , candidate] of ranked) {
    const trial = clone(state);
    trial.animals.find(item => item.animal_id === animal.animal_id).position = [...candidate];
    if (layoutIsSafe(trial)) {
      animal.position = [...candidate];
      return animal;
    }
  }
  return animal;
}

export async function stepGardenAnimals(
  state, returning = false, interruptedAnimalId = null,
) {
  if (!state.animals.length) return state;
  const scene = state.program_state?.scene ?? {};
  const hour = Math.floor(state.effective_time / 3600) % 24;
  const context = {
    effective_time: state.effective_time,
    time_of_day: hour < 6 || hour >= 20 ? 'night' : 'day',
    season: String(scene.season ?? 'spring'),
    weather: String(scene.weather ?? 'calm'),
    recipient_focus_id: state.ui.focus_id,
    nearby_affordances: uniqueSorted(state.fixtures.flatMap(fixture => [
      fixture.catalog_id, ...fixtureActiveAffordances(fixture),
    ])),
    interrupted_animal_id: interruptedAnimalId === null ? null : String(interruptedAnimalId),
  };
  const decisionRecords = {};
  for (const animal of state.animals) {
    let intent; let highLevel; let score; let priorityReason; let retainedByHysteresis = false;
    const normalizedWeather = context.weather.toLocaleLowerCase('und');
    const severeWeather = ['heavy_rain', 'storm', 'blizzard'].includes(normalizedWeather);
    const coldTurtle = animal.species_id === 'turtle' &&
      ['cold', 'snow', 'blizzard'].includes(normalizedWeather);
    if (context.interrupted_animal_id === animal.animal_id || animal.energy <= 15) {
      intent = 'rest'; highLevel = 'resting'; score = 9000; priorityReason = 'safety_or_interruption';
    } else if (severeWeather || coldTurtle) {
      intent = { bird: 'perch', cat: 'nap', rabbit: 'hide', turtle: 'rest' }[animal.species_id];
      highLevel = 'resting'; score = 9500; priorityReason = 'weather_safety';
    } else if (animal.choreography_lock) {
      intent = `choreography:${animal.choreography_lock}`; highLevel = 'authored_scene';
      score = 9000; priorityReason = 'authored_choreography';
    } else if (!['idle', 'recover'].includes(animal.current_intent) &&
      context.effective_time < animal.minimum_dwell_until) {
      intent = animal.current_intent; highLevel = animal.high_level_state;
      score = 0; priorityReason = 'minimum_dwell'; retainedByHysteresis = true;
    }
    else if (context.recipient_focus_id === animal.animal_id && animal.bond_tier >= 1) {
      intent = 'greet'; highLevel = 'awake'; score = 8000; priorityReason = 'relationship_response';
    } else if (returning) {
      intent = TIER_REPERTOIRES[animal.species_id][animal.bond_tier][0]; highLevel = 'awake';
      score = 7500; priorityReason = 'positive_return_greeting';
    } else if (context.time_of_day === 'night' && animal.personality.day_preference >= 65) {
      intent = 'rest'; highLevel = 'sleeping'; score = 7000; priorityReason = 'routine';
    } else {
      const candidates = [
        ...ANIMAL_SPECIES[animal.species_id].repertoire,
        ...TIER_REPERTOIRES[animal.species_id][animal.bond_tier],
      ].filter(value => !animal.authored_prohibitions.includes(value));
      const scored = [];
      for (const candidate of candidates) scored.push([
        await animalUtility(state, animal, candidate, context), candidate,
      ]);
      scored.sort((left, right) => right[0] - left[0] || compareCodePoints(right[1], left[1]));
      [score, intent] = scored[0]; priorityReason = 'utility';
      highLevel = ['rest', 'nap', 'sunbathe', 'perch', 'groom', 'hide', 'settled'].some(token => intent.includes(token))
        ? 'resting' : 'awake';
    }
    if (!retainedByHysteresis) {
      if (['safety_or_interruption', 'weather_safety'].includes(priorityReason)) {
        animal.choreography_lock = null;
      }
      const dwell = ANIMAL_SPECIES[animal.species_id].dwell[intent] ?? 12;
      animal.high_level_state = highLevel;
      animal.current_intent = intent;
      animal.intent_started_at = context.effective_time;
      animal.minimum_dwell_until = context.effective_time + dwell;
      animal.decision_index += 1;
      animal.cooldowns[intent] = context.effective_time + dwell;
    }
    const before = [...animal.position];
    await moveGardenAnimal(state, animal, {
      intent, high_level_state: highLevel,
    });
    decisionRecords[animal.animal_id] = {
      intent, priority_reason: priorityReason, score,
      retained_by_hysteresis: retainedByHysteresis,
      moved: animal.position[0] !== before[0] || animal.position[1] !== before[1],
      from_position: before, to_position: [...animal.position],
      weather: context.weather, season: context.season,
      memory_count: Math.min(RECENT_MEMORY_LIMIT, animal.recent_memories.length),
    };
  }
  state.program_state.animal_decisions = decisionRecords;
  return state;
}

async function finish(prior, updated, command, summary, {
  actions = [], details = null, interruptedAnimalId = null,
} = {}) {
  const final = clone(updated);
  final.command_sequence = command.sequence;
  final.processed_commands.push(command.command_id);
  final.processed_commands = final.processed_commands.slice(-PROCESSED_COMMAND_LIMIT);
  final.event_trace.push({
    trace_id: await stableId('trace', prior.world_id, command.command_id),
    sequence: command.sequence,
    kind: command.kind,
    target_id: command.target_id,
    effective_time: prior.effective_time,
    summary,
  });
  final.event_trace = compactEventTrace(final.event_trace);
  final.undo_stack = final.undo_stack.slice(-UNDO_STACK_LIMIT);
  await stepGardenAnimals(final, false, interruptedAnimalId);
  activateMemorial(final);
  return [final, {
    accepted: true,
    changed: true,
    reason: '',
    summary,
    available_actions: [...actions],
    details: details === null ? null : clone(details),
  }];
}

async function journalEntry(state, objectId, status, label, description) {
  const entry = {
    entry_id: await stableId('journal', state.world_id, objectId),
    object_id: objectId,
    status,
    label,
    description,
    discovered_at: state.effective_time,
  };
  return [
    ...state.journal.filter(item => item.object_id !== objectId),
    entry,
  ];
}

function animalTier(points, counts) {
  const diversity = Object.values(counts).filter(value => value > 0).length;
  if (points >= 40 && diversity >= 3) return 3;
  if (points >= 20 && diversity >= 2) return 2;
  if (points >= 8) return 1;
  return 0;
}

async function animalInteraction(state, source, kind) {
  const animal = clone(source);
  const sessionCount = animal.session_interactions.filter(item => item === kind).length;
  const base = { observe: 1, feed: 3, play: 4 }[kind];
  const gain = Math.max(0, base - sessionCount);
  animal.interaction_counts[kind] = (animal.interaction_counts[kind] ?? 0) + 1;
  animal.bond_points += gain;
  animal.bond_tier = animalTier(animal.bond_points, animal.interaction_counts);
  const memory = {
    memory_id: await stableId(
      'memory', state.world_id, animal.animal_id, kind,
      state.command_sequence + 1,
    ),
    kind,
    target_id: null,
    timestamp: state.effective_time,
    valence: 1,
    salience: Math.max(1, gain),
  };
  animal.session_interactions.push(kind);
  animal.recent_memories = [...animal.recent_memories, memory].slice(-16);
  if (kind === 'feed') animal.energy = Math.min(100, animal.energy + 8);
  else if (kind === 'play') {
    animal.energy = Math.max(0, animal.energy - 5);
    animal.play_appetite = Math.max(0, animal.play_appetite - 15);
  } else animal.social_appetite = Math.max(0, animal.social_appetite - 5);
  return animal;
}

function activateMemorial(state) {
  const completion = state.program_state?.completion ?? {};
  if (!(state.program_state?.story_complete || completion.story_complete)) return state;
  const existing = state.program_state.memorial ?? {};
  state.program_state.memorial = {
    active: true,
    completed_at: integer(existing.completed_at, state.effective_time),
    examined_gifts: state.journal.filter(item => item.status === 'examined')
      .map(item => item.object_id).sort(),
    lasting: true,
  };
  return state;
}

async function withBondGift(state, prior, animal) {
  if (animal.bond_tier < 3 || prior.bond_tier >= 3) return state;
  const [catalogId, label, description] = ANIMAL_GIFTS[animal.species_id];
  const collectibleId = await stableId('collectible', state.world_id, animal.animal_id, catalogId);
  if (state.collectibles.some(item => item.collectible_id === collectibleId)) return state;
  state.collectibles.push(normalizeCollectible({
    collectible_id: collectibleId, family: 'animal_trace', provenance: 'animal-given',
    label, description, position: animal.position,
  }));
  state.journal = await journalEntry(
    state, collectibleId, 'hinted', label,
    `${animal.display_name ?? animal.species_id} brought something to notice.`,
  );
  return state;
}

async function fixtureInteraction(state, fixtureId, requested = null) {
  const updated = clone(state);
  const fixture = updated.fixtures.find(item => item.fixture_id === fixtureId);
  if (!fixture) return null;
  const definition = FIXTURE_CATALOG[fixture.catalog_id];
  const verbs = FIXTURE_VERBS[fixture.catalog_id];
  const verb = String(requested ?? verbs[0]);
  if (!verbs.includes(verb)) return null;
  const values = fixture.authored_state;
  if (verb === 'open' || verb === 'close') values.open = verb === 'open';
  else if (verb === 'light' || verb === 'extinguish') values.lit = verb === 'light';
  else if (verb === 'refill') values.water_level = 3;
  else if (verb === 'draw_water') values.draw_count = integer(values.draw_count) + 1;
  else if (verb === 'turn') values.turned_count = integer(values.turned_count) + 1;
  else if (verb === 'fill') {
    values.water_level = 3; values.fill_count = integer(values.fill_count) + 1;
  } else if (verb === 'water' && fixture.catalog_id === 'watering_can') {
    if (integer(values.water_level) <= 0) return null;
    values.water_level = integer(values.water_level) - 1;
    values.water_count = integer(values.water_count) + 1;
  } else if (['organize', 'arrange', 'gather', 'water', 'tend', 'train', 'transplant'].includes(verb)) {
    values[`${verb}_count`] = integer(values[`${verb}_count`]) + 1;
  } else if (verb === 'read_time') values.last_read_hour = Math.floor(state.effective_time / 3600) % 24;
  else if (verb === 'review_inventory') values.last_inventory_count = state.inventory.length;
  else values[`${verb}_count`] = integer(values[`${verb}_count`]) + 1;

  const byDistance = position => (left, right) => {
    const leftDistance = Math.abs(left.position[0] - position[0]) + Math.abs(left.position[1] - position[1]);
    const rightDistance = Math.abs(right.position[0] - position[0]) + Math.abs(right.position[1] - position[1]);
    return leftDistance - rightDistance || compareCodePoints(
      left.plant_id ?? left.animal_id ?? left.collectible_id,
      right.plant_id ?? right.animal_id ?? right.collectible_id,
    );
  };
  const plantEffects = { train: 'train', transplant: 'train', tend: 'water',
    water: 'water', turn: 'water', organize: 'train' };
  const care = plantEffects[verb];
  if (care && updated.plants.length) {
    const plant = [...updated.plants].sort(byDistance(fixture.position))[0];
    careForPlant(plant, state.effective_time, care);
    values.linked_plant_id = plant.plant_id;
  }
  const resources = clone(updated.program_state.garden_resources ?? {});
  if (['refill', 'draw_water'].includes(verb)) {
    resources.water_units = integer(resources.water_units) + 3;
  } else if (verb === 'fill') {
    resources.water_units = Math.max(0, integer(resources.water_units) - 3);
  } else if (verb === 'water' && fixture.catalog_id === 'watering_can') {
    resources.watered_total = integer(resources.watered_total) + 1;
  } else if (verb === 'turn') resources.soil_units = integer(resources.soil_units) + 1;
  if (verb === 'organize') resources.tools_ready = true;
  if (Object.keys(resources).length) updated.program_state.garden_resources = resources;

  if (verb === 'gather') {
    const available = updated.collectibles.filter(item => !item.collected)
      .sort(byDistance(fixture.position));
    if (available.length) {
      available[0].collected = true;
      updated.inventory = uniqueSorted([...updated.inventory, available[0].collectible_id]);
      values.gathered_collectible_id = available[0].collectible_id;
    }
  } else if (verb === 'arrange' && updated.inventory.length) {
    const arrangedId = uniqueSorted(updated.inventory)[0];
    const arranged = updated.collectibles.find(item => item.collectible_id === arrangedId);
    if (arranged) arranged.position = [...fixture.position];
    values.arranged_collectible_id = arrangedId;
  }

  if (updated.animals.length) {
    const animal = [...updated.animals].sort(byDistance(fixture.position))[0];
    animal.current_intent = `fixture_${verb}`;
    animal.intent_started_at = state.effective_time;
    animal.minimum_dwell_until = state.effective_time + 5;
    animal.recent_memories = [...animal.recent_memories, {
      memory_id: await stableId('memory', state.world_id, animal.animal_id,
        'fixture', fixture.fixture_id, verb, state.command_sequence + 1),
      kind: `fixture:${verb}`, target_id: fixture.fixture_id,
      timestamp: state.effective_time, valence: 1, salience: 1,
    }].slice(-16);
  }
  updated.ui.focus_id = fixture.fixture_id;
  updated.ui.camera = [...fixture.position];
  if (['remember', 'read', 'review_inventory'].includes(verb)) updated.ui.journal_open = true;
  fixture.interaction_count += 1;
  fixture.last_interaction = verb;
  updated.journal = await journalEntry(
    state, fixture.fixture_id, 'observed', definition.name,
    `${definition.name}: ${verb.replaceAll('_', ' ')}.`,
  );
  const details = normalizeFixture(fixture);
  details.inventory = [...updated.inventory];
  return [updated, `Used ${verb.replaceAll('_', ' ')} at ${definition.name}.`, details];
}

async function inspect(state, targetId) {
  const updated = clone(state);
  const plant = updated.plants.find(item => item.plant_id === targetId);
  if (plant) {
    updated.journal = await journalEntry(
      state, targetId, 'observed', plant.species_id,
      'A living plant in the garden.',
    );
    return [updated, `Inspected ${plant.species_id}.`, plantDetails(plant)];
  }
  const fixture = updated.fixtures.find(item => item.fixture_id === targetId);
  if (fixture) {
    updated.journal = await journalEntry(
      state, targetId, 'observed', fixture.catalog_id,
      'A fixture that can shape garden routines.',
    );
    return [updated, `Inspected ${fixture.catalog_id}.`, normalizeFixture(fixture)];
  }
  const animalIndex = updated.animals.findIndex(item => item.animal_id === targetId);
  if (animalIndex >= 0) {
    const priorAnimal = clone(updated.animals[animalIndex]);
    const animal = await animalInteraction(state, updated.animals[animalIndex], 'observe');
    updated.animals[animalIndex] = animal;
    updated.journal = await journalEntry(
      state, targetId, 'observed', animal.species_id,
      `A ${animal.species_id} sharing the garden.`,
    );
    await withBondGift(updated, priorAnimal, animal);
    return [updated, `Observed ${animal.species_id}.`, normalizeAnimal(animal)];
  }
  const collectible = updated.collectibles.find(item => item.collectible_id === targetId);
  if (collectible) {
    updated.journal = await journalEntry(
      state, targetId, 'examined', collectible.label, collectible.description,
    );
    return [updated, `Examined ${collectible.label}.`, normalizeCollectible(collectible)];
  }
  return null;
}

async function collect(state, targetId) {
  const updated = clone(state);
  const item = updated.collectibles.find(candidate =>
    candidate.collectible_id === targetId);
  if (!item || item.collected) return null;
  item.collected = true;
  updated.inventory = uniqueSorted([...updated.inventory, targetId]);
  updated.journal = await journalEntry(
    state, targetId, 'collected', item.label, item.description,
  );
  return [updated, `Collected ${item.label}.`, normalizeCollectible(item)];
}

function insideWorld(state, position) {
  return position[0] >= 0 && position[0] < state.world_width &&
    position[1] >= 0 && position[1] < state.world_height;
}

function occupied(state, position, exceptId = null) {
  return [
    ...state.plants.map(item => [item.plant_id, item.position]),
    ...state.fixtures.map(item => [item.fixture_id, item.position]),
  ].some(([objectId, current]) => objectId !== exceptId &&
    current[0] === position[0] && current[1] === position[1]);
}

const cellKey = position => `${position[0]},${position[1]}`;

function fixtureCells(fixture) {
  const definition = FIXTURE_CATALOG[fixture.catalog_id];
  const cells = [];
  for (let dy = 0; dy < definition.footprint[1]; dy += 1) {
    for (let dx = 0; dx < definition.footprint[0]; dx += 1) {
      cells.push([fixture.position[0] + dx, fixture.position[1] + dy]);
    }
  }
  return cells;
}

function allFixtureCells(state, exceptId = null) {
  return new Set(state.fixtures
    .filter(item => item.fixture_id !== exceptId)
    .flatMap(fixtureCells)
    .map(cellKey));
}

function blockedCells(state) {
  const blocked = new Set(state.plants.map(item => cellKey(item.position)));
  for (const fixture of state.fixtures) {
    if (FIXTURE_CATALOG[fixture.catalog_id].blocks_movement) {
      for (const cell of fixtureCells(fixture)) blocked.add(cellKey(cell));
    }
  }
  return blocked;
}

function layoutIsSafe(state) {
  const occupiedCells = new Set();
  for (const fixture of state.fixtures) {
    if (!(fixture.catalog_id in FIXTURE_CATALOG)) return false;
    for (const cell of fixtureCells(fixture)) {
      if (!insideWorld(state, cell) || occupiedCells.has(cellKey(cell))) return false;
      occupiedCells.add(cellKey(cell));
    }
  }
  const blocked = blockedCells(state);
  const accessCells = (cells, blocking) => {
    const candidates = blocking ? [] : [...cells];
    for (const [x, y] of cells) candidates.push([x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]);
    return new Set(candidates.filter(cell => insideWorld(state, cell) && !blocked.has(cellKey(cell))).map(cellKey));
  };
  const accessGroups = [
    ...state.plants.map(item => accessCells([item.position], true)),
    ...state.fixtures.map(item => accessCells(
      fixtureCells(item), FIXTURE_CATALOG[item.catalog_id].blocks_movement,
    )),
    ...state.animals.map(item => accessCells([item.position], false)),
    ...state.collectibles.filter(item => !item.collected)
      .map(item => accessCells([item.position], false)),
  ];
  if (accessGroups.some(group => !group.size)) return false;
  let start = null;
  for (let y = 0; y < state.world_height && start === null; y += 1) {
    for (let x = 0; x < state.world_width; x += 1) {
      if (!blocked.has(cellKey([x, y]))) {
        start = [x, y];
        break;
      }
    }
  }
  if (start === null) return accessGroups.length === 0;
  const queue = [start];
  const reached = new Set([cellKey(start)]);
  for (let index = 0; index < queue.length; index += 1) {
    const current = queue[index];
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      const next = [current[0] + dx, current[1] + dy];
      const key = cellKey(next);
      if (!insideWorld(state, next) || blocked.has(key) || reached.has(key)) continue;
      reached.add(key);
      queue.push(next);
    }
  }
  return accessGroups.every(group => [...group].some(key => reached.has(key)));
}

function validateFixturePlacement(
  state, catalogId, position, { fixtureId = 'candidate', exceptId = null } = {},
) {
  if (!(catalogId in FIXTURE_CATALOG)) return ['unknown fixture catalog ID'];
  const candidate = normalizeFixture({
    fixture_id: fixtureId,
    catalog_id: catalogId,
    position,
  });
  const cells = fixtureCells(candidate);
  const errors = [];
  if (cells.some(cell => !insideWorld(state, cell))) {
    errors.push('fixture footprint is outside the world');
  }
  const fixtureOccupancy = allFixtureCells(state, exceptId);
  if (cells.some(cell => fixtureOccupancy.has(cellKey(cell)))) {
    errors.push('fixture footprint overlaps another fixture');
  }
  const plantOccupancy = new Set(state.plants.map(item => cellKey(item.position)));
  if (cells.some(cell => plantOccupancy.has(cellKey(cell)))) {
    errors.push('fixture footprint overlaps a plant');
  }
  if (errors.length) return errors;
  const candidateState = clone(state);
  candidateState.fixtures = [
    ...candidateState.fixtures.filter(item => item.fixture_id !== exceptId),
    candidate,
  ];
  if (!layoutIsSafe(candidateState)) {
    errors.push('fixture placement makes the world unsafe or unreachable');
  }
  return errors;
}

/** Apply one canonical command without touching rendering or persistence APIs. */
export async function dispatchGardenCommand(sourceState, command) {
  const state = clone(sourceState);
  if (state.processed_commands.includes(command.command_id)) {
    return [state, {
      accepted: true,
      changed: false,
      reason: 'already applied',
      summary: 'Command was already applied.',
      available_actions: [],
      details: null,
    }];
  }
  const errors = validateGardenCommand(command);
  if (errors.length) return [state, reject(errors.join('; '))];
  if (command.sequence !== state.command_sequence + 1) {
    return [state, reject(`expected sequence ${state.command_sequence + 1}`)];
  }

  const kind = command.kind;
  const target = command.target_id;

  if (kind === 'move_focus') {
    const ids = objectIds(state);
    if (!ids.length) return [state, reject('world has no focusable objects')];
    const requested = command.args.target_id || target;
    let focus;
    if (requested !== null && requested !== undefined) {
      if (!ids.includes(requested)) return [state, reject('focus target does not exist')];
      focus = String(requested);
    } else {
      const current = ids.includes(state.ui.focus_id) ? ids.indexOf(state.ui.focus_id) : -1;
      const direction = String(command.args.direction ?? 'next');
      if (['left', 'right', 'up', 'down'].includes(direction)) {
        // Spatial. With nothing focused there is no origin to move from, so
        // the first press enters the world at the first object rather than
        // rejecting -- the same thing `next` does, and the reader gets a focus
        // for their keypress either way.
        const moved = current < 0
          ? ids[0] : spatialFocus(state, ids, ids[current], direction);
        if (moved === null) {
          return [state, reject(`nothing lies ${direction} of the focused object`)];
        }
        focus = moved;
      } else {
        const delta = direction === 'previous' ? -1 : 1;
        focus = ids[(current + delta + ids.length) % ids.length];
      }
    }
    const updated = clone(state);
    updated.ui.focus_id = focus;
    updated.ui.actions_open_for = null;
    return finish(state, updated, command, `Focused ${focus}.`, {
      actions: availableActions(state, focus),
    });
  }

  if (kind === 'pan') {
    const updated = clone(state);
    updated.ui.camera = [
      clamp(state.ui.camera[0] + integer(command.args.dx, 0), 0, state.world_width - 1),
      clamp(state.ui.camera[1] + integer(command.args.dy, 0), 0, state.world_height - 1),
    ];
    return finish(
      state, updated, command,
      `Panned to ${updated.ui.camera[0]},${updated.ui.camera[1]}.`,
    );
  }

  if (kind === 'inspect' || kind === 'primary_interact') {
    const chosen = target || state.ui.focus_id;
    if (!chosen) return [state, reject('no interaction target')];
    const chosenKind = objectKind(state, chosen);
    let outcome;
    if (kind === 'primary_interact' && chosenKind === 'collectible') outcome = await collect(state, chosen);
    else if (kind === 'primary_interact' && chosenKind === 'fixture') {
      outcome = await fixtureInteraction(
        state, chosen, command.args.fixture_action ?? command.args.action ?? null,
      );
    } else outcome = await inspect(state, chosen);
    if (!outcome) return [state, reject('target is not available')];
    const [updated, summary, details] = outcome;
    return finish(state, updated, command, summary, {
      actions: availableActions(updated, chosen), details,
      interruptedAnimalId: chosenKind === 'animal' ? chosen : null,
    });
  }

  if (kind === 'open_actions') {
    const chosen = target || state.ui.focus_id;
    if (!chosen || !objectKind(state, chosen)) return [state, reject('no action target')];
    const updated = clone(state);
    updated.ui.focus_id = chosen;
    updated.ui.actions_open_for = chosen;
    updated.ui.journal_open = false;
    const actions = availableActions(state, chosen);
    return finish(state, updated, command, `Opened actions for ${chosen}.`, { actions });
  }

  if (kind === 'tend') {
    const updated = clone(state);
    const plant = updated.plants.find(item => item.plant_id === target);
    const fixture = updated.fixtures.find(item => item.fixture_id === target);
    if (!plant && !fixture) return [state, reject('tend target is not a plant or tending fixture')];
    const care = String(command.args.care_action ?? 'water');
    if (plant && !['observe', 'water', 'prune', 'train', 'transplant', 'rest'].includes(care)) return [state, reject('unsupported care action')];
    if (fixture) {
      const outcome = await fixtureInteraction(state, fixture.fixture_id, care);
      if (!outcome) return [state, reject('fixture does not support that action')];
      return finish(state, outcome[0], command, outcome[1], { details: outcome[2] });
    }
    if (care === 'transplant') {
      if (!Object.hasOwn(command.args, 'x') || !Object.hasOwn(command.args, 'y')) return [state, reject('transplant requires x and y')];
      const position = [integer(command.args.x), integer(command.args.y)];
      if (!insideWorld(state, position) || occupied(state, position, plant.plant_id)) return [state, reject('transplant position is unavailable')];
      updated.undo_stack.push({ kind: 'plant', object_id: plant.plant_id,
        previous_position: [...plant.position], previous_rotation: null, created: false });
      plant.position = position; plant.tended_count += 1;
      plant.last_tended_at = state.effective_time; plant.dormant = false;
      if (!layoutIsSafe(updated)) return [state, reject('transplant makes the world unsafe or unreachable')];
    } else careForPlant(plant, state.effective_time, care);
    updated.journal = await journalEntry(
      state, plant.plant_id, 'observed', plant.species_id,
      `A ${plant.species_id} tended with care.`,
    );
    return finish(state, updated, command, `Used ${care} on ${plant.species_id}.`, {
      details: plantDetails(plant),
    });
  }

  if (kind === 'feed' || kind === 'play') {
    const updated = clone(state);
    const index = updated.animals.findIndex(item => item.animal_id === target);
    if (index < 0) return [state, reject(`${kind} target is not an animal`)];
    const priorAnimal = clone(updated.animals[index]);
    const animal = await animalInteraction(state, updated.animals[index], kind);
    updated.animals[index] = animal;
    await withBondGift(updated, priorAnimal, animal);
    return finish(state, updated, command, `Shared ${kind} with ${animal.species_id}.`, {
      details: normalizeAnimal(animal), interruptedAnimalId: animal.animal_id,
    });
  }

  if (kind === 'collect') {
    const outcome = await collect(state, String(target));
    if (!outcome) return [state, reject('collectible is unavailable')];
    const [updated, summary, details] = outcome;
    return finish(state, updated, command, summary, { details });
  }

  if (kind === 'place') {
    const position = [integer(command.args.x), integer(command.args.y)];
    if (!insideWorld(state, position)) return [state, reject('placement is outside the world')];
    const objectKindValue = String(command.args.object_kind ?? 'fixture');
    const catalog = String(command.args.catalog_id);
    const objectId = String(command.args.object_id ?? await stableId(
      objectKindValue, state.world_id, command.command_id,
    ));
    if (objectIds(state).includes(objectId)) return [state, reject('object ID already exists')];
    const updated = clone(state);
    updated.undo_stack.push({
      kind: objectKindValue,
      object_id: objectId,
      previous_position: null,
      previous_rotation: null,
      created: true,
    });
    let details;
    if (objectKindValue === 'fixture') {
      const placementErrors = validateFixturePlacement(
        state, catalog, position, { fixtureId: objectId },
      );
      if (placementErrors.length) return [state, reject(placementErrors.join('; '))];
      details = normalizeFixture({
        fixture_id: objectId,
        catalog_id: catalog,
        position,
        rotation: command.args.rotation ?? 0,
      });
      updated.fixtures.push(details);
    } else {
      if (!(catalog in SPECIES_CATALOG)) return [state, reject('unknown plant catalog ID')];
      if (occupied(state, position)) return [state, reject('placement cell is occupied')];
      details = plantDetails({
        plant_id: objectId,
        species_id: catalog,
        position,
        topology: await generateTopology(state.seed, objectId, catalog, state.effective_time),
        growth_period_seconds: SPECIES_CATALOG[catalog][3],
      });
      updated.plants.push(details);
      if (!layoutIsSafe(updated)) return [state, reject('plant placement makes the world unsafe or unreachable')];
    }
    return finish(
      state, updated, command,
      `Placed ${catalog} at ${position[0]},${position[1]}.`, { details },
    );
  }

  if (kind === 'move_fixture') {
    const updated = clone(state);
    const fixture = updated.fixtures.find(item => item.fixture_id === target);
    const plant = updated.plants.find(item => item.plant_id === target);
    if (!fixture && !plant) return [state, reject('move target is not a fixture or plant')];
    const position = [integer(command.args.x), integer(command.args.y)];
    if (!insideWorld(state, position)) return [state, reject('move is outside the world')];
    if (plant) {
      if (occupied(state, position, plant.plant_id)) return [state, reject('move position is occupied')];
      updated.undo_stack.push({ kind: 'plant', object_id: plant.plant_id,
        previous_position: [...plant.position], previous_rotation: null, created: false });
      plant.position = position; plant.dormant = false;
      if (!layoutIsSafe(updated)) return [state, reject('plant move makes the world unsafe or unreachable')];
      return finish(state, updated, command,
        `Transplanted ${plant.species_id} to ${position[0]},${position[1]}.`,
        { details: plantDetails(plant) });
    }
    const placementErrors = validateFixturePlacement(
      state,
      fixture.catalog_id,
      position,
      { fixtureId: fixture.fixture_id, exceptId: fixture.fixture_id },
    );
    if (placementErrors.length) return [state, reject(placementErrors.join('; '))];
    updated.undo_stack.push({
      kind: 'fixture',
      object_id: fixture.fixture_id,
      previous_position: [...fixture.position],
      previous_rotation: fixture.rotation,
      created: false,
    });
    fixture.position = position;
    fixture.rotation = rotation(command.args.rotation ?? fixture.rotation);
    return finish(
      state, updated, command,
      `Moved ${fixture.catalog_id} to ${position[0]},${position[1]}.`,
      { details: normalizeFixture(fixture) },
    );
  }

  if (kind === 'undo') {
    if (!state.undo_stack.length) return [state, reject('nothing to undo')];
    const updated = clone(state);
    const undo = updated.undo_stack.at(-1);
    if (undo.created) {
      if (undo.kind === 'fixture') {
        updated.fixtures = updated.fixtures.filter(item => item.fixture_id !== undo.object_id);
      } else {
        updated.plants = updated.plants.filter(item => item.plant_id !== undo.object_id);
      }
    } else if (undo.kind === 'fixture' && undo.previous_position !== null) {
      const fixture = updated.fixtures.find(item => item.fixture_id === undo.object_id);
      if (fixture) {
        fixture.position = [...undo.previous_position];
        fixture.rotation = undo.previous_rotation || 0;
      }
    } else if (undo.kind === 'plant' && undo.previous_position !== null) {
      const plant = updated.plants.find(item => item.plant_id === undo.object_id);
      if (plant) plant.position = [...undo.previous_position];
    } else return [state, reject('undo record is invalid')];
    updated.undo_stack.pop();
    return finish(
      state, updated, command,
      `Undid ${undo.kind} change for ${undo.object_id}.`,
    );
  }

  if (kind === 'open_journal') {
    const updated = clone(state);
    updated.ui.journal_open = true;
    updated.ui.actions_open_for = null;
    return finish(
      state, updated, command,
      `Opened journal with ${state.journal.length} entries.`,
      { details: { entries: state.journal.map(normalizeJournal),
        inventory: [...state.inventory], absence_summary: [...(state.program_state.absence_summary ?? [])],
        memorial: clone(state.program_state.memorial ?? {}) } },
    );
  }

  if (kind === 'pause_motion') {
    const updated = clone(state);
    updated.ui.motion_paused = Boolean(
      command.args.paused ?? !state.ui.motion_paused,
    );
    return finish(
      state, updated, command,
      updated.ui.motion_paused ? 'Motion paused.' : 'Motion resumed.',
    );
  }

  if (kind === 'back') {
    const updated = clone(state);
    let summary;
    if (updated.ui.actions_open_for !== null) {
      updated.ui.actions_open_for = null;
      summary = 'Closed actions.';
    } else if (updated.ui.journal_open) {
      updated.ui.journal_open = false;
      summary = 'Closed journal.';
    } else if (updated.ui.focus_id !== null) {
      updated.ui.focus_id = null;
      summary = 'Cleared focus.';
    } else summary = 'Already at the garden.';
    return finish(state, updated, command, summary);
  }

  return [state, reject('unsupported command')];
}

async function topologyVisibilityHash(plant, effectiveTime) {
  // Persistence intentionally sorts topology by stable node ID, so the
  // semantic visibility hash is explicitly graph-order independent too.
  const visible = plant.topology
    .filter(node => node.birth_time <= effectiveTime)
    .sort((left, right) => compareCodePoints(left.node_id, right.node_id))
    .map(node => {
      const duration = Math.max(1, node.maturity_time - node.birth_time);
      const maturity = Math.max(0, Math.min(
        1000, Math.floor(((effectiveTime - node.birth_time) * 1000) / duration),
      ));
      return [node.node_id, maturity, node.bloom_state];
    });
  return sha256Hex(canonicalJson(visible));
}

function organMaturityProgress(node, effectiveTime) {
  if (node.maturity_time <= node.birth_time) return 1000;
  return Math.max(0, Math.min(1000, Math.floor(
    ((effectiveTime - node.birth_time) * 1000) /
    (node.maturity_time - node.birth_time),
  )));
}

function visibleOrganGeometry(plant, effectiveTime) {
  const visible = new Set(plant.topology.filter(node => node.birth_time <= effectiveTime)
    .map(node => node.node_id));
  const nodes = new Map(plant.topology.map(node => [node.node_id, node]));
  const offsetsMilli = new Map();
  const resolve = nodeId => {
    if (offsetsMilli.has(nodeId)) return offsetsMilli.get(nodeId);
    const node = nodes.get(nodeId);
    let offset;
    if (node.parent_id === null) offset = [0, 0];
    else {
      const parent = resolve(node.parent_id);
      const progress = organMaturityProgress(node, effectiveTime);
      offset = [
        parent[0] + node.final_direction[0] * node.final_length * progress,
        parent[1] + node.final_direction[1] * node.final_length * progress,
      ];
    }
    offsetsMilli.set(nodeId, offset);
    return offset;
  };
  const records = [];
  for (const node of sortBy(plant.topology, 'node_id')) {
    if (!visible.has(node.node_id)) continue;
    const maturityProgress = organMaturityProgress(node, effectiveTime);
    const maturityStageIndex = maturityProgress === 1000
      ? 6 : Math.min(5, Math.floor((maturityProgress * 6) / 1000));
    const offsetMilli = resolve(node.node_id);
    const offset = offsetMilli.map(value => Math.trunc(value / 1000));
    records.push({ node_id: node.node_id, parent_id: node.parent_id, kind: node.kind,
      offset, offset_milli: [...offsetMilli], maturity_progress: maturityProgress,
      maturity_stage_index: maturityStageIndex,
      maturity_stage: PLANT_MATURITY_STAGES[maturityStageIndex],
      glyph_family: node.glyph_family, bloom_state: node.bloom_state });
  }
  return records.sort((left, right) => compareCodePoints(left.node_id, right.node_id));
}

function fixtureConnectedMask(state, fixture) {
  const group = FIXTURE_CONNECTED_GROUP[fixture.catalog_id] ?? null;
  if (group === null) return 0;
  const otherCells = new Set(state.fixtures.filter(other =>
    other.fixture_id !== fixture.fixture_id && FIXTURE_CONNECTED_GROUP[other.catalog_id] === group)
    .flatMap(fixtureCells).map(cellKey));
  const own = fixtureCells(fixture);
  let mask = 0;
  [[0, -1], [1, 0], [0, 1], [-1, 0]].forEach(([dx, dy], bit) => {
    if (own.some(([x, y]) => otherCells.has(cellKey([x + dx, y + dy])))) mask |= 1 << bit;
  });
  return mask;
}

function fixtureRenderCells(state, fixture) {
  const group = FIXTURE_CONNECTED_GROUP[fixture.catalog_id] ?? null;
  const grouped = group === null ? new Set() : new Set(state.fixtures
    .filter(other => FIXTURE_CONNECTED_GROUP[other.catalog_id] === group)
    .flatMap(fixtureCells).map(cellKey));
  return fixtureCells(fixture).sort((left, right) => left[1] - right[1] || left[0] - right[0])
    .map(([x, y]) => {
      let mask = 0;
      if (group !== null) [[0, -1], [1, 0], [0, 1], [-1, 0]].forEach(([dx, dy], bit) => {
        if (grouped.has(cellKey([x + dx, y + dy]))) mask |= 1 << bit;
      });
      return { dx: x - fixture.position[0], dy: y - fixture.position[1], connected_mask: mask };
    });
}

function personalityEmphasis(personality) {
  return Object.entries(personality).sort((left, right) =>
    right[1] - left[1] || compareCodePoints(left[0], right[0]))[0]?.[0] ?? 'patient';
}

/** Build a read-only semantic projection; renderers may not mutate this state. */
/**
 * Count what a world actually contains.
 *
 * The version stamps say what a world CLAIMS to be; this says what it IS. The
 * persisted 13-plant / 22-fixture / 4-animal / 8-collectible world was found by
 * a person noticing the two disagreed with the 8/10/4/3 starter, so both belong
 * in one report rather than one being derivable on request.
 *
 * @param {object} state - a deserialized world
 * @returns {{plants: number, fixtures: number, animals: number, collectibles: number}}
 */
export function gardenWorldCensus(state) {
  return {
    plants: state.plants.length,
    fixtures: state.fixtures.length,
    animals: state.animals.length,
    collectibles: state.collectibles.length,
  };
}

/**
 * Describe the roster a world actually holds, as one comparable string.
 *
 * A version number on its own is an unverified assertion: a world can carry the
 * current number over an arbitrary population and nothing notices. This is the
 * evidence half -- computed at generation time and stored, recomputed whenever a
 * world is characterized. When the two disagree, the contents are no longer the
 * composition the stamp names, which is what makes a custom roster or an
 * author-program-modified world stop reading as the stamped composition.
 *
 * Readable rather than digested on purpose: a reviewer looking at a rejected
 * world benefits from seeing WHICH species differ. Identities, not positions,
 * because positions are seed-derived and two seeds give the same composition.
 *
 * Must produce byte-identical output to `composition_fingerprint` in
 * src/lateletter/garden/world/provenance.py.
 *
 * @param {object} state - a world (deserialized or mid-generation)
 * @returns {string} a canonical roster description
 */
export function compositionFingerprint(state) {
  // Each identity is written with the anchor it was authored against, so a
  // change to an anchor table changes the fingerprint. Roster names alone were
  // not enough: moving every anchor produces a visibly different garden out of
  // an identical species list, so a verdict bound to names would survive a
  // layout the operator had never seen. An identity with no anchor is written
  // `?`, which is itself a difference worth seeing.
  const entries = (identities, anchors) => [...identities].sort().map(identity => {
    const anchor = anchors[identity];
    return anchor ? `${identity}@${anchor[0]},${anchor[1]}` : `${identity}@?`;
  }).join(',');
  return [
    `plants=${entries(state.plants.map(item => item.species_id), STARTER_PLANT_ANCHORS)}`,
    `fixtures=${entries(state.fixtures.map(item => item.catalog_id), STARTER_FIXTURE_ANCHORS)}`,
    `animals=${entries(state.animals.map(item => item.species_id), STARTER_ANIMAL_ANCHORS)}`,
    `collectibles=${entries(state.collectibles.map(item => item.family), STARTER_COLLECTIBLE_ANCHORS)}`,
  ].join('|');
}

/**
 * Bring a stored DOCUMENT up to the current schema, and nothing else.
 *
 * Operates on the raw document because `deserializeWorldState` throws on any
 * schema but the current one -- by the time a world object exists, migrating is
 * already too late. It never touches the content stamps: a migration rewrites a
 * document, it does not rebuild the garden inside it, and stamping today's
 * generator onto what it upgraded would make an obsolete starter
 * indistinguishable from one built today.
 *
 * @param {object} data - a document as read from storage
 * @returns {{document: object, origin: string}} the document at the current
 *          schema, and how it arrived: 'loaded' or 'schema_migrated'
 * @throws {Error} when the document is from a newer build, or from an older
 *         schema with no registered transform
 */
export function migrateGardenWorldDocument(data) {
  const document = { ...data };
  let storedSchema = integer(document.schema_version, 0);
  const originalSchema = storedSchema;

  if (storedSchema > WORLD_SCHEMA_VERSION) {
    throw new Error(
      `world schema ${storedSchema} was written by a newer build than this one, `
      + `which understands ${WORLD_SCHEMA_VERSION}`,
    );
  }
  if (storedSchema === WORLD_SCHEMA_VERSION) {
    return { document, origin: LOAD_STORED };
  }

  while (storedSchema < WORLD_SCHEMA_VERSION) {
    const transform = SCHEMA_MIGRATIONS[storedSchema];
    if (!transform) {
      throw new Error(
        `no migration is registered from world schema ${storedSchema}; refusing to `
        + 'renumber a document written under a shape this build has never seen',
      );
    }
    Object.assign(document, transform(document));
    storedSchema += 1;
  }
  document.schema_version = WORLD_SCHEMA_VERSION;
  if (document.migrated_from_schema === null || document.migrated_from_schema === undefined) {
    document.migrated_from_schema = originalSchema;
  }
  return { document, origin: LOAD_SCHEMA_MIGRATED };
}

/**
 * Read a stored document, migrating its shape if it needs it.
 *
 * The pairing is the point: migrating without loading leaves a dict nobody
 * validated, and loading without migrating throws on any older world.
 *
 * @param {object|string} raw - a document as read from storage
 * @returns {{state: object, loadOrigin: string}} the world and how it arrived
 */
export function loadMigratedGardenWorld(raw) {
  const data = typeof raw === 'string' ? JSON.parse(raw) : raw;
  const { document, origin } = migrateGardenWorldDocument(data);
  return { state: deserializeWorldState(document), loadOrigin: origin };
}

/**
 * Refuse anything that is not a freshly generated composition.
 *
 * TWO conditions, because they are two different facts. The lineage must be
 * fresh -- every stamp current and the roster still matching -- AND the world
 * must have been generated in this process rather than loaded. A world with
 * perfect stamps that came out of storage after a hundred interactions has a
 * fresh lineage and is not a fresh composition, and no stamp could ever say so.
 *
 * @param {object} state - the world about to be reviewed or captured
 * @param {string} loadOrigin - 'generated' | 'loaded' | 'schema_migrated'
 * @returns {object} the characterization, when it is fresh
 * @throws {Error} when it is not, listing every reason
 */
export function requireFreshComposition(state, loadOrigin) {
  // MANDATORY and validated. An earlier draft defaulted this to 'generated', so
  // a caller who simply forgot the argument certified a loaded world as newly
  // generated: the permissive answer was the one you got by not thinking about
  // it, which is the worst possible default for a guard.
  if (!LOAD_ORIGINS.has(loadOrigin)) {
    throw new Error(
      `unknown load origin ${JSON.stringify(loadOrigin)}; expected one of `
      + [...LOAD_ORIGINS].sort().join(', '),
    );
  }
  const origin = characterizeGardenWorld(state);
  const reasons = [...origin.reasons];
  if (loadOrigin !== LOAD_GENERATED) {
    reasons.push(`this world was ${loadOrigin}, not generated in this process`);
  }
  if (reasons.length) {
    const error = new Error(`this world is not a fresh composition: ${reasons.join('; ')}`);
    error.origin = { ...origin, reasons };
    throw error;
  }
  return origin;
}

/**
 * Decide, from the world alone, whether it is a FRESH composition.
 *
 * Fresh is a statement about LINEAGE only: the shape is current, the content
 * came from today's generator, and the population still matches the composition
 * its own stamp describes. Each reason is listed separately rather than
 * summarised -- a world can be stale in several ways at once, and "stale" is not
 * actionable where "built by generator 1, current is 2" is.
 *
 * Fresh does NOT mean the operator approved anything: approval is a verdict a
 * person gives, held in docs/garden-composition-acceptance.json. It also does
 * not mean "newly generated" -- a world can have perfect stamps and still have
 * come out of storage, which is why load origin is carried separately.
 *
 * This mirrors `characterize_world` in
 * `src/lateletter/garden/world/provenance.py`; the two must agree, because a
 * review of the browser Garden and a review of the terminal Garden have to mean
 * the same thing by the word "fresh".
 *
 * @param {object} state - a deserialized world
 * @returns {{label: string, is_fresh: boolean, schema_version: number,
 *            generator_version: number|null, composition_version: number|null,
 *            migrated: boolean, census: object, reasons: string[]}}
 */
export function characterizeGardenWorld(state) {
  const reasons = [];

  if (state.schema_version !== WORLD_SCHEMA_VERSION) {
    reasons.push(`stored under schema ${state.schema_version}, current is ${WORLD_SCHEMA_VERSION}`);
  }

  // An absent stamp is reported as absent rather than as a mismatch: "made by
  // an unknown generator" and "made by generator 1 when 2 is current" are
  // different situations, and the first cannot even be compared.
  if (state.generator_version === null || state.generator_version === undefined) {
    reasons.push('no generator_version: this world predates version stamping');
  } else if (state.generator_version !== GENERATOR_VERSION) {
    reasons.push(`built by generator ${state.generator_version}, current is ${GENERATOR_VERSION}`);
  }

  if (state.composition_version === null || state.composition_version === undefined) {
    reasons.push('no composition_version: this world names no composition revision');
  } else if (state.composition_version !== COMPOSITION_VERSION) {
    reasons.push(
      `composition revision ${state.composition_version}, current is ${COMPOSITION_VERSION}`,
    );
  }

  // The stamp against the contents. "Never described" and "described, and the
  // description is now wrong" are reported separately: the second means
  // somebody changed the world after it was generated.
  const observed = compositionFingerprint(state);
  if (state.composition_fingerprint === null || state.composition_fingerprint === undefined) {
    reasons.push('no composition_fingerprint: the roster was never recorded');
  } else if (state.composition_fingerprint !== observed) {
    reasons.push(
      'contents no longer match the stamped composition: '
      + `stamped ${JSON.stringify(state.composition_fingerprint)}, holds ${JSON.stringify(observed)}`,
    );
  }

  const migrated = state.migrated_from_schema !== null && state.migrated_from_schema !== undefined;
  if (migrated) {
    reasons.push(`shape migrated from schema ${state.migrated_from_schema}`);
  }

  return {
    // "migrated" names an event that happened to this document; "restored"
    // names a world that is simply older than the stamps. Calling the second
    // one migrated would describe an event that never took place.
    label: reasons.length === 0 ? 'fresh' : (migrated ? 'migrated' : 'restored'),
    is_fresh: reasons.length === 0,
    schema_version: state.schema_version,
    generator_version: state.generator_version ?? null,
    composition_version: state.composition_version ?? null,
    composition_fingerprint: state.composition_fingerprint ?? null,
    observed_fingerprint: observed,
    migrated,
    census: gardenWorldCensus(state),
    reasons,
  };
}

export async function projectGardenScene(sourceState) {
  const state = deserializeWorldState(serializeWorldState(sourceState));
  const objects = [];
  for (const plant of state.plants) {
    const visible = plant.topology.filter(node => node.birth_time <= state.effective_time);
    objects.push({
      object_id: plant.plant_id, kind: 'plant',
      semantic_name: plant.species_id.replaceAll('_', ' '),
      position: [...plant.position], depth: 100, collision: true, occlusion: true,
      affordances: ['observe', 'water', 'prune', 'train', 'transplant'],
      actions: ['inspect', 'observe', 'water', 'prune', 'train', 'transplant', 'rest'],
      hotspot: { x: plant.position[0], y: plant.position[1], width: 1, height: 1 },
      semantic_state: {
        species_id: plant.species_id, visible_organ_count: visible.length,
        topology_hash: await topologyVisibilityHash(plant, state.effective_time),
        growth_points: plant.growth_points,
        dormant: plant.dormant,
        care_state: plant.dormant ? 'resting' : 'growing',
        presentation_state: plant.dormant ? 'dormant'
          : visible.some(node => node.bloom_state === 'bloom') ? 'blooming' : 'growing',
        semantic_description: `${plant.species_id.replaceAll('_', ' ')} at ${plant.position[0]},${plant.position[1]}; ${plant.dormant ? 'resting' : 'growing'}, ${visible.length} visible organs.`,
        visible_organs: visibleOrganGeometry(plant, state.effective_time),
      },
      // Plants declare no primary action and offer no opportunities yet. The
      // fields are still present so every projected object has one shape and a
      // renderer never has to test whether a key exists.
      primary_action: null,
      opportunities: [],
    });
  }
  for (const fixture of state.fixtures) {
    const definition = FIXTURE_CATALOG[fixture.catalog_id];
    objects.push({
      object_id: fixture.fixture_id, kind: 'fixture', semantic_name: definition.name,
      position: [...fixture.position], depth: 100,
      collision: definition.blocks_movement, occlusion: definition.blocks_movement,
      affordances: fixtureActiveAffordances(fixture), actions: ['inspect', ...FIXTURE_VERBS[fixture.catalog_id], 'move', 'rotate'],
      hotspot: {
        x: fixture.position[0], y: fixture.position[1],
        width: definition.footprint[0], height: definition.footprint[1],
      },
      semantic_state: { catalog_id: fixture.catalog_id, rotation: fixture.rotation,
        interaction_count: fixture.interaction_count,
        last_interaction: fixture.last_interaction,
        interaction_verbs: [...FIXTURE_VERBS[fixture.catalog_id]],
        connected_group: FIXTURE_CONNECTED_GROUP[fixture.catalog_id] ?? null,
        connected_mask: fixtureConnectedMask(state, fixture),
        render_cells: fixtureRenderCells(state, fixture),
        presentation_state: fixturePresentationState(fixture),
        semantic_description: `${definition.name} at ${fixture.position[0]},${fixture.position[1]}; ${fixturePresentationState(fixture)}.`,
        authored_state: clone(fixture.authored_state) },
      // Both of these dispatch the SAME canonical command the action sheet
      // would have dispatched -- `primary_interact` carrying a fixture verb.
      // Nothing new is invented for the point-and-click path; only the route
      // to it is shorter.
      primary_action: FIXTURE_PRIMARY_ACTIONS[fixture.catalog_id]
        ? {
          command: 'primary_interact',
          args: { fixture_action: FIXTURE_PRIMARY_ACTIONS[fixture.catalog_id].verb },
          label: FIXTURE_PRIMARY_ACTIONS[fixture.catalog_id].label,
        }
        : null,
      opportunities: fixtureOpportunities(fixture).map(offer => ({
        opportunity_id: offer.opportunity_id,
        command: 'primary_interact',
        args: { fixture_action: offer.verb },
        label: offer.label,
      })),
    });
  }
  for (const animal of state.animals) {
    const decision = state.program_state?.animal_decisions?.[animal.animal_id] ?? {};
    objects.push({
      object_id: animal.animal_id, kind: 'animal',
      semantic_name: animal.display_name ?? animal.species_id,
      position: [...animal.position], depth: 110, collision: false, occlusion: true,
      affordances: [...ANIMAL_SPECIES[animal.species_id].affinities],
      actions: ['inspect', 'feed', 'play'],
      hotspot: { x: animal.position[0], y: animal.position[1], width: 1, height: 1 },
      semantic_state: {
        species_id: animal.species_id, high_level_state: animal.high_level_state,
        intent: animal.current_intent, bond_tier: animal.bond_tier,
        choreography_locked: animal.choreography_lock !== null,
        display_name: animal.display_name,
        personality_note: animal.personality_note,
        personality: clone(animal.personality),
        recent_memories: animal.recent_memories.map(normalizeMemory),
        routine: animal.current_intent,
        choreography_phase: animal.choreography_lock !== null ? 'perform'
          : animal.current_intent === 'recover' ? 'recover' : 'orient',
        presentation_variant: `${animal.species_id}.tier${animal.bond_tier}.${animal.current_intent}.${animal.choreography_lock !== null ? 'perform' : 'routine'}`,
        personality_emphasis: personalityEmphasis(animal.personality),
        memory_count: animal.recent_memories.length,
        decision_reason: String(decision.priority_reason ?? 'not_yet_decided'),
        decision_score: integer(decision.score),
        decision_context: {
          weather: String(decision.weather ?? 'calm'),
          season: String(decision.season ?? 'spring'),
          memory_count: integer(decision.memory_count),
          moved: Boolean(decision.moved ?? false),
          from_position: [...(decision.from_position ?? animal.position)],
          to_position: [...(decision.to_position ?? animal.position)],
        },
        semantic_description: `${animal.display_name ?? animal.species_id}, ${animal.species_id}, bond tier ${animal.bond_tier}; ${animal.current_intent}; personality ${personalityEmphasis(animal.personality)}; ${animal.recent_memories.length} memories; decision ${decision.priority_reason ?? 'not_yet_decided'}.`,
      },
      // An animal's verb IS the canonical command -- `play` and `feed` are
      // top-level commands, unlike a fixture verb, which travels inside
      // `primary_interact`. The renderer dispatches whatever it is handed
      // either way and does not need to know the difference.
      primary_action: {
        command: animalPrimaryAction(animal).verb,
        args: {},
        label: animalPrimaryAction(animal).label,
      },
      opportunities: animalOpportunities(animal).map(offer => ({
        opportunity_id: offer.opportunity_id,
        command: offer.verb,
        args: {},
        label: offer.label,
      })),
    });
  }
  for (const item of state.collectibles.filter(candidate => !candidate.collected)) {
    objects.push({
      object_id: item.collectible_id, kind: 'collectible', semantic_name: item.label,
      position: [...item.position], depth: 120, collision: false, occlusion: false,
      affordances: ['discover', 'journal'], actions: ['inspect', 'collect'],
      hotspot: { x: item.position[0], y: item.position[1], width: 1, height: 1 },
      semantic_state: {
        family: item.family, provenance: item.provenance, authored: item.authored,
        semantic_description: `${item.label} at ${item.position[0]},${item.position[1]}; ${item.provenance}.`,
      },
      primary_action: null,
      opportunities: [],
    });
  }
  objects.sort((left, right) => left.depth - right.depth ||
    compareCodePoints(left.object_id, right.object_id));
  return {
    world_id: state.world_id, effective_time: state.effective_time,
    // The pause-aware simulation clock is not civil time. Renderers use this
    // separately projected observation watermark for sky/season presentation.
    observed_time: state.last_observed_wall_time,
    camera: [...state.ui.camera], motion_paused: state.ui.motion_paused,
    scene: { ...clone(state.program_state?.scene ?? {}),
      absence_summary: [...(state.program_state.absence_summary ?? [])],
      missed_event_summaries: Array.isArray(state.program_state.missed_event_summaries)
        ? state.program_state.missed_event_summaries.slice(0, 3).map(item => {
          if (!item || typeof item !== 'object' || Array.isArray(item)) return String(item);
          const count = Math.max(0, integer(item.missed_count));
          return `${String(item.event_id ?? 'event')}: ${count} missed occurrence${count === 1 ? '' : 's'}${item.catch_up_truncated ? '; catch-up truncated' : ''}.`;
        }) : [],
      absence_elapsed_seconds: integer(state.program_state.absence_elapsed_seconds),
      memorial: clone(state.program_state.memorial ?? {}), inventory: [...state.inventory],
      journal_entry_count: state.journal.length,
      journal_entries: state.journal.map(normalizeJournal) }, objects,
  };
}

export const LIVE_TICK_SECONDS = 5;

/** Advance the canonical dwell loop on fixed deterministic boundaries. */
export async function advanceGardenLive(sourceState, elapsedSeconds) {
  const state = deserializeWorldState(serializeWorldState(sourceState));
  const elapsed = Math.max(0, integer(elapsedSeconds));
  if (elapsed === 0) return state;
  const observed = state.last_observed_wall_time === null
    ? null : state.last_observed_wall_time + elapsed;
  if (state.ui.motion_paused) {
    state.last_observed_wall_time = observed;
    return state;
  }
  const start = state.effective_time;
  const end = start + elapsed;
  for (const plant of state.plants) {
    if (plant.dormant) continue;
    const period = Math.max(1, plant.growth_period_seconds);
    const milestones = Math.max(0, Math.floor(end / period) - Math.floor(start / period));
    if (milestones) {
      advanceTopology(plant, end, milestones);
      plant.growth_points += milestones;
    }
  }
  for (let boundary = (Math.floor(start / LIVE_TICK_SECONDS) + 1) * LIVE_TICK_SECONDS;
    boundary <= end; boundary += LIVE_TICK_SECONDS) {
    state.effective_time = boundary;
    await stepGardenAnimals(state);
    const traceId = await stableId('trace', state.world_id, 'live-tick', boundary);
    if (!state.event_trace.some(entry => entry.trace_id === traceId)) {
      state.event_trace.push({
        trace_id: traceId, sequence: state.command_sequence, kind: 'live_tick',
        target_id: null, effective_time: boundary,
        summary: state.animals.length
          ? state.animals.map(animal => `${animal.animal_id}:${animal.current_intent}`).join(', ')
          : 'Garden time advanced.',
      });
      state.event_trace = compactEventTrace(state.event_trace);
    }
  }
  state.effective_time = end;
  state.last_observed_wall_time = observed;
  activateMemorial(state);
  return deserializeWorldState(serializeWorldState(state));
}

/** Aggregate humane absence progress without replaying elapsed ticks. */
export async function reconcileGardenOffline(sourceState, observedWallTime, maxSummaries = 3) {
  const state = deserializeWorldState(serializeWorldState(sourceState));
  const observed = Math.max(0, integer(observedWallTime));
  const previous = state.last_observed_wall_time;
  if (previous === null) {
    state.last_observed_wall_time = observed;
    activateMemorial(state);
    return [state, { elapsed_seconds: 0, rollback_clamped: false, summaries: [], receipt_ids: [] }];
  }
  if (observed <= previous) {
    activateMemorial(state);
    return [state, {
      elapsed_seconds: 0, rollback_clamped: observed < previous,
      summaries: [], receipt_ids: [],
    }];
  }
  if (state.ui.motion_paused) {
    state.last_observed_wall_time = observed;
    activateMemorial(state);
    return [state, {
      elapsed_seconds: 0, rollback_clamped: false, summaries: [], receipt_ids: [],
    }];
  }
  const elapsed = observed - previous;
  const start = state.effective_time;
  const end = start + elapsed;
  const changes = [];
  const receipts = [];
  for (const plant of state.plants) {
    if (plant.dormant) continue;
    const milestones = Math.max(0,
      Math.floor(end / Math.max(1, plant.growth_period_seconds)) -
      Math.floor(start / Math.max(1, plant.growth_period_seconds)));
    if (milestones) {
      advanceTopology(plant, end, milestones);
      plant.growth_points += milestones;
      changes.push([plant.plant_id, milestones]);
      receipts.push(await stableId(
        'milestone', state.world_id, 'plant-growth', plant.plant_id, start, end,
      ));
    }
  }
  for (const animal of state.animals) {
    animal.session_interactions = [];
    animal.energy = Math.max(50, animal.energy);
    animal.social_appetite = 50;
    animal.play_appetite = 50;
    animal.rest_appetite = 40;
  }
  if (state.animals.length) {
    receipts.push(await stableId('milestone', state.world_id, 'animal-return', start, end));
  }
  const available = state.collectibles.filter(item => !item.collected);
  if (available.length) {
    receipts.push(await stableId('milestone', state.world_id, 'finds-waiting', start, end));
  }
  const candidates = [
    ...changes.map(([id, count]) => [10, id,
      `A plant changed while you were away (${count} growth milestone${count === 1 ? '' : 's'}).`]),
    ...state.animals.map(animal => [20, animal.animal_id,
      `Your ${animal.species_id} is glad to see you.`]),
  ];
  if (available.length) candidates.push([30, available[0].collectible_id,
    `${available.length} garden find${available.length === 1 ? ' is' : 's are'} waiting to be noticed.`]);
  candidates.sort((left, right) => left[0] - right[0] || compareCodePoints(left[1], right[1]));
  const summaries = candidates.slice(0, Math.max(0, maxSummaries)).map(item => item[2]);
  state.effective_time = end;
  state.last_observed_wall_time = observed;
  state.program_state.absence_summary = [...summaries];
  state.program_state.absence_elapsed_seconds = elapsed;
  state.program_state.offline_reconciliation_total =
    integer(state.program_state.offline_reconciliation_total) + 1;
  const priorReceipts = [...state.milestone_receipts];
  const novelReceipts = receipts.filter(receipt => !priorReceipts.includes(receipt));
  state.program_state.milestone_receipt_total = Math.max(
    priorReceipts.length, integer(state.program_state.milestone_receipt_total),
  ) + novelReceipts.length;
  state.milestone_receipts = compactRecentStrings(
    [...priorReceipts, ...novelReceipts], MILESTONE_RECEIPT_LIMIT,
  );
  state.event_trace.push({
    trace_id: await stableId('trace', state.world_id, 'offline', start, end),
    sequence: state.command_sequence, kind: 'offline_reconcile', target_id: null,
    effective_time: end, summary: `Reconciled ${elapsed} seconds in aggregate.`,
  });
  state.event_trace = compactEventTrace(state.event_trace);
  await stepGardenAnimals(state, true);
  activateMemorial(state);
  return [state, {
    elapsed_seconds: elapsed, rollback_clamped: false, summaries,
    receipt_ids: receipts,
  }];
}

function authoredCandidateIsSafe(state, target, kind, catalogId, candidate) {
  if (!Array.isArray(candidate) || candidate.length !== 2 ||
    !candidate.every(Number.isInteger)) return false;
  const cells = kind === 'fixture'
    ? fixtureCells(normalizeFixture({ fixture_id: target, catalog_id: catalogId, position: candidate }))
    : [candidate];
  if (cells.some(cell => !insideWorld(state, cell))) return false;
  const occupiedCells = new Set([
    ...state.fixtures.filter(item => item.fixture_id !== target).flatMap(fixtureCells),
    ...state.plants.filter(item => item.plant_id !== target).map(item => item.position),
    ...state.animals.filter(item => item.animal_id !== target).map(item => item.position),
    ...state.collectibles.filter(item => item.collectible_id !== target && !item.collected)
      .map(item => item.position),
  ].map(cellKey));
  if (cells.some(cell => occupiedCells.has(cellKey(cell)))) return false;
  const prospective = deserializeWorldState(serializeWorldState(state));
  prospective.fixtures = prospective.fixtures.filter(item => item.fixture_id !== target);
  prospective.plants = prospective.plants.filter(item => item.plant_id !== target);
  prospective.animals = prospective.animals.filter(item => item.animal_id !== target);
  prospective.collectibles = prospective.collectibles.filter(item => item.collectible_id !== target);
  if (kind === 'fixture') prospective.fixtures.push(normalizeFixture({
    fixture_id: target, catalog_id: catalogId, position: candidate, authored: true,
  }));
  else if (kind === 'plant') prospective.plants.push(normalizePlant({
    plant_id: target, species_id: catalogId, position: candidate,
  }));
  else if (kind === 'animal') prospective.animals.push(normalizeAnimal({
    animal_id: target, species_id: catalogId, position: candidate,
  }));
  else prospective.collectibles.push(normalizeCollectible({
    collectible_id: target, family: 'authored_keepsake', provenance: 'author-authored',
    label: target, description: 'An authored garden keepsake.', position: candidate,
  }));
  return layoutIsSafe(prospective);
}

async function authoredPosition(state, target, kind, catalogId, requested) {
  let hint = null; let candidate = null;
  if (typeof requested === 'string') {
    const hints = new Set(['random', 'authored', 'path', 'near_tallest_tree', 'near_bench', 'by_edge']);
    if (!hints.has(requested)) throw new Error(`invalid authored position for Garden object ${target}`);
    hint = requested;
  } else if (Array.isArray(requested) && requested.length === 2) candidate = requested;
  else if (requested && typeof requested === 'object' &&
    Object.hasOwn(requested, 'x') && Object.hasOwn(requested, 'y')) {
    candidate = [requested.x, requested.y];
  } else if (requested !== undefined && requested !== null) {
    throw new Error(`invalid authored position for Garden object ${target}`);
  }
  if (candidate) {
    if (authoredCandidateIsSafe(state, target, kind, catalogId, candidate)) return [...candidate];
    throw new Error(`unsafe authored position for Garden object ${target}`);
  }
  let anchors = [];
  if (hint === 'near_tallest_tree' && state.plants.length) anchors = [[...state.plants]
    .sort((left, right) => right.topology.length - left.topology.length ||
      compareCodePoints(left.plant_id, right.plant_id))[0].position];
  else if (hint === 'near_bench') anchors = [...state.fixtures]
    .sort((left, right) => compareCodePoints(left.fixture_id, right.fixture_id))
    .filter(item => item.catalog_id === 'bench').map(item => item.position);
  else if (hint === 'path') anchors = [...state.fixtures]
    .sort((left, right) => compareCodePoints(left.fixture_id, right.fixture_id))
    .filter(item => ['stepping_stone', 'stepping_stones'].includes(item.catalog_id))
    .map(item => item.position);
  const relative = [];
  for (const anchor of anchors) for (let radius = 1; radius <= 4; radius += 1) {
    for (let dy = -radius; dy <= radius; dy += 1) for (let dx = -radius; dx <= radius; dx += 1) {
      if (Math.max(Math.abs(dx), Math.abs(dy)) === radius) relative.push([anchor[0] + dx, anchor[1] + dy]);
    }
  }
  if (hint === 'by_edge') {
    const margin = 2;
    for (const y of [margin, state.world_height - margin - 1]) {
      for (let x = margin; x < state.world_width - margin; x += 1) relative.push([x, y]);
    }
    for (const x of [margin, state.world_width - margin - 1]) {
      for (let y = margin + 1; y < state.world_height - margin - 1; y += 1) relative.push([x, y]);
    }
  }
  for (const value of relative) {
    if (authoredCandidateIsSafe(state, target, kind, catalogId, value)) return value;
  }
  const rng = new DeterministicRng(await deriveSeed(
    state.seed, 'program', target, kind, 'position',
  ));
  for (let attempt = 0; attempt < 512; attempt += 1) {
    const value = [
      rng.randint(2, state.world_width - 3),
      rng.randint(2, state.world_height - 3),
    ];
    if (authoredCandidateIsSafe(state, target, kind, catalogId, value)) return value;
  }
  throw new Error(`could not place authored Garden object ${target}`);
}

function programDefinition(program, target) {
  return program.animals?.find(item => item.id === target)
    ?? program.entities?.find(item => item.id === target) ?? {};
}

function programDefinitions(program) {
  return [...(program.entities ?? []), ...(program.animals ?? [])]
    .filter(item => typeof item?.id === 'string')
    .sort((left, right) => compareCodePoints(left.id, right.id));
}

const catalogLeaf = value => {
  return String(value ?? '').split('.').at(-1);
};

function programKind(definition) {
  const catalogId = catalogLeaf(
    definition.catalog_id ?? definition.asset_id ?? definition.species,
  );
  const rawKind = String(definition.kind ?? '');
  if (definition.species || Object.hasOwn(ANIMAL_SPECIES, catalogId)) return ['animal', catalogId];
  if (rawKind === 'plant' || Object.hasOwn(SPECIES_CATALOG, catalogId)) return ['plant', catalogId];
  if (rawKind === 'fixture' || Object.hasOwn(FIXTURE_CATALOG, catalogId)) return ['fixture', catalogId];
  return ['collectible', catalogId || 'authored_keepsake'];
}

export function seedGardenProgramState(sourceState, program) {
  const state = deserializeWorldState(serializeWorldState(sourceState));
  // Once an authenticated author program is attached, its declarations own
  // the complete relationship-animal roster. Generated catalog animals are a
  // standalone sandbox concern and must not leak into a recipient's story.
  const authoredAnimalIds = new Set((program.animals ?? []).map(item => String(item.id)));
  const removedSandboxAnimals = state.animals.some(
    item => !authoredAnimalIds.has(item.animal_id),
  );
  state.animals = state.animals.filter(item => authoredAnimalIds.has(item.animal_id));
  const programState = clone(state.program_state ?? {});
  if (removedSandboxAnimals) programState.absence_summary = [];
  const variables = programState.variables ??= {};
  for (const [name, value] of Object.entries(program.variables ?? {})) {
    if (!Object.hasOwn(variables, name)) variables[name] = clone(value);
  }
  const entities = programState.entities ??= {};
  for (const definition of programDefinitions(program)) {
    const target = String(definition.id);
    const slot = entities[target] ??= { id: target };
    const initial = definition.initial_state;
    if (initial && typeof initial === 'object' && !Array.isArray(initial)) {
      for (const [name, value] of Object.entries(initial)) {
        if (!Object.hasOwn(slot, name)) slot[name] = clone(value);
      }
    }
  }
  programState.applied_occurrences ??= [];
  programState.exclusive_claims ??= {};
  state.program_state = programState;
  return state;
}

function initialProgramEffects(program) {
  const effects = [];
  for (const definition of programDefinitions(program)) {
    const initial = definition.initial_state;
    if (!initial || typeof initial !== 'object' || Array.isArray(initial)) continue;
    const [kind, catalogId] = programKind(definition);
    const params = {};
    const requested = definition.position ?? definition.placement;
    if (requested !== undefined) params.position = clone(requested);
    let type = null;
    if (kind === 'animal' && initial.present === true) {
      type = 'animal.arrive';
      if (definition.routine !== undefined) params.routine = clone(definition.routine);
    } else if (kind === 'plant' && initial.planted === true) {
      type = 'plant.plant'; params.species_id = catalogId;
    } else if (['fixture', 'collectible'].includes(kind) && initial.revealed === true) {
      type = 'entity.reveal';
    }
    if (type) {
      const effect = { type, event_id: 'program.initial', target: String(definition.id) };
      if (Object.keys(params).length) effect.params = params;
      effects.push(effect);
    }
  }
  return effects;
}

function animalWithAuthoredData(animal, definition, routine = undefined) {
  const output = clone(animal);
  if (definition.personality && typeof definition.personality === 'object' &&
    !Array.isArray(definition.personality)) output.personality = normalizePersonality(definition.personality);
  else if (typeof definition.personality === 'string') output.personality_note = definition.personality;
  if (typeof definition.name === 'string' && definition.name) output.display_name = definition.name;
  output.favorite_fixture_ids = uniqueSorted(definition.favorite_places ?? []);
  output.authored_prohibitions = uniqueSorted(definition.prohibited_behaviors ?? []);
  const value = routine !== undefined ? routine : definition.routine;
  output.authored_preferences = uniqueSorted(
    Array.isArray(value) ? value : value ? [value] : [],
  );
  return output;
}

async function programJournal(state, receipt, objectId, label, description, status = 'discovered') {
  const entryId = await stableId('journal', state.world_id, receipt);
  if (!state.journal.some(item => item.entry_id === entryId)) state.journal.push(normalizeJournal({
    entry_id: entryId, object_id: objectId, status, label, description,
    discovered_at: state.effective_time,
  }));
}

function pythonJson(value) {
  if (Array.isArray(value)) return `[${value.map(pythonJson).join(', ')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort(compareCodePoints).map(key =>
    `${JSON.stringify(key)}: ${pythonJson(value[key])}`).join(', ')}}`;
  return JSON.stringify(value);
}

async function revealProgramEntity(state, program, target, params = {}, catalogOverride = null) {
  const definition = programDefinition(program, target);
  const [kind, definitionCatalogId] = programKind(definition);
  const catalogId = catalogOverride ?? definitionCatalogId;
  const requested = params.position ?? definition.position ?? definition.placement;
  if (kind === 'fixture' && Object.hasOwn(FIXTURE_CATALOG, catalogId)) {
    const position = await authoredPosition(state, target, kind, catalogId, requested);
    state.fixtures = [...state.fixtures.filter(item => item.fixture_id !== target),
      normalizeFixture({ fixture_id: target, catalog_id: catalogId, position, authored: true,
        authored_state: params.state && typeof params.state === 'object'
          ? params.state : params.state === undefined ? {} : { value: params.state } })];
  } else if (kind === 'plant' && Object.hasOwn(SPECIES_CATALOG, catalogId)) {
    const position = await authoredPosition(state, target, kind, catalogId, requested);
    state.plants = [...state.plants.filter(item => item.plant_id !== target), normalizePlant({
      plant_id: target, species_id: catalogId, position,
      topology: await generateTopology(state.seed, target, catalogId, state.effective_time),
      growth_period_seconds: SPECIES_CATALOG[catalogId][3],
    })];
  } else {
    const position = await authoredPosition(state, target, 'collectible', catalogId, requested);
    const properties = definition.properties && typeof definition.properties === 'object'
      ? definition.properties : {};
    const label = String(properties.label ?? target);
    const rawDescription = params.state ?? properties.description ?? 'An authored garden keepsake.';
    const description = typeof rawDescription === 'string' ? rawDescription : String(rawDescription);
    state.collectibles = [...state.collectibles.filter(item => item.collectible_id !== target),
      normalizeCollectible({ collectible_id: target, family: 'authored_keepsake',
        provenance: 'author-authored', label, description, position, authored: true })];
  }
}

/**
 * Materialize evaluator effects into the authoritative WorldState.
 * The evaluator owns only occurrence/variable bookkeeping; it never becomes
 * a renderer-local gameplay state. Receipts make recurring/replayed results
 * idempotent and every change is visible in canonical persistence/projection.
 */
export async function materializeGardenProgramEffects(
  sourceState, program, evaluation,
) {
  const state = seedGardenProgramState(sourceState, program);
  const priorReceipts = [...state.milestone_receipts];
  state.program_state = clone(evaluation.state ?? {});
  const occurrences = { 'program.initial': 'definition', ...Object.fromEntries(evaluation.trace
    .filter(row => row.status === 'applied' && row.occurrence_id)
    .map(row => [String(row.event_id), String(row.occurrence_id)])) };
  const actionIndexes = {};
  const materialized = [];
  for (const effect of [...initialProgramEffects(program), ...evaluation.effects]) {
    const eventId = String(effect.event_id);
    const index = actionIndexes[eventId] ?? 0;
    actionIndexes[eventId] = index + 1;
    const receiptId = await stableId(
      'program-receipt', state.world_id, eventId,
      occurrences[eventId] ?? 'unscheduled', index, effect,
    );
    if (state.milestone_receipts.includes(receiptId)) continue;
    const target = effect.target === undefined || effect.target === null
      ? null : String(effect.target);
    const params = clone(effect.params ?? {});
    const definition = programDefinition(program, target);
    const [kind, definitionCatalogId] = programKind(definition);
    const catalogId = effect.type === 'entity.transform' && params.asset_id
      ? catalogLeaf(params.asset_id) : definitionCatalogId;
    const requested = params.position ?? definition.position ?? definition.placement;

    if (effect.type === 'animal.arrive') {
      const species = catalogLeaf(definition.species ?? definition.catalog_id ?? catalogId);
      if (Object.hasOwn(ANIMAL_SPECIES, species)) {
        const position = await authoredPosition(state, target, 'animal', species, requested);
        const personalityRng = new DeterministicRng(await deriveSeed(
          state.seed, 'animal', target, 'personality',
        ));
        let animal = normalizeAnimal({
          animal_id: target, species_id: species, position,
          personality: Object.fromEntries(PERSONALITY_FIELDS.map(field => [
            field, personalityRng.randint(20, 80),
          ])),
        });
        animal = animalWithAuthoredData(animal, definition, params.routine);
        state.animals = [...state.animals.filter(item => item.animal_id !== target), animal];
      }
    } else if (effect.type === 'animal.depart') {
      state.animals = state.animals.filter(item => item.animal_id !== target);
    } else if (effect.type.startsWith('animal.')) {
      const animal = state.animals.find(item => item.animal_id === target);
      if (animal && effect.type === 'animal.behave') {
        animal.current_intent = String(params.behavior ?? 'idle');
        animal.intent_started_at = state.effective_time;
        animal.minimum_dwell_until = state.effective_time + Math.max(0, integer(params.duration_ticks));
      } else if (animal && effect.type === 'animal.routine') {
        Object.assign(animal, animalWithAuthoredData(animal, definition, params.routine));
      } else if (animal && effect.type === 'animal.set_destination') {
        let destination;
        if (params.position !== undefined) {
          destination = await authoredPosition(
            state, target, 'animal', animal.species_id, params.position,
          );
        } else if (params.fixture_id) {
          const fixture = state.fixtures.find(item => item.fixture_id === params.fixture_id);
          if (!fixture) throw new Error(
            `animal destination fixture ${JSON.stringify(params.fixture_id)} is not present`,
          );
          const own = new Set(fixtureCells(fixture).map(cellKey));
          const candidates = new Map();
          for (const cell of fixtureCells(fixture)) for (const neighbor of [
            [cell[0] - 1, cell[1]], [cell[0] + 1, cell[1]],
            [cell[0], cell[1] - 1], [cell[0], cell[1] + 1],
          ]) if (!own.has(cellKey(neighbor))) candidates.set(cellKey(neighbor), neighbor);
          destination = [...candidates.values()]
            .sort((left, right) => left[1] - right[1] || left[0] - right[0])
            .find(candidate => authoredCandidateIsSafe(
              state, target, 'animal', animal.species_id, candidate,
            ));
          if (!destination) throw new Error(
            `fixture ${JSON.stringify(fixture.fixture_id)} has no safe adjacent animal destination`,
          );
        } else throw new Error('animal.set_destination requires position or fixture_id');
        animal.position = [...destination];
      } else if (animal && ['animal.deliver', 'animal.present_gift'].includes(effect.type)) {
        animal.choreography_lock = null;
        animal.current_intent = effect.type;
        animal.intent_started_at = state.effective_time;
        animal.minimum_dwell_until = state.effective_time;
      }
      if (['animal.deliver', 'animal.present_gift'].includes(effect.type)) {
        const referenceKey = effect.type === 'animal.deliver' ? 'entity_id' : 'gift_id';
        const deliveredId = params[referenceKey];
        if (typeof deliveredId === 'string' && deliveredId) {
          await revealProgramEntity(state, program, deliveredId);
        }
        await programJournal(
          state, receiptId, target,
          effect.type === 'animal.present_gift' ? 'Gift delivered' : 'Delivery complete',
          'An authored animal delivery was completed.',
        );
      }
    } else if (effect.type === 'plant.plant') {
      const species = catalogLeaf(params.species_id ?? catalogId);
      if (Object.hasOwn(SPECIES_CATALOG, species)) {
        const position = await authoredPosition(state, target, 'plant', species, requested);
        const plant = normalizePlant({
          plant_id: target, species_id: species, position,
          topology: await generateTopology(state.seed, target, species, state.effective_time),
          growth_period_seconds: SPECIES_CATALOG[species][3],
        });
        state.plants = [...state.plants.filter(item => item.plant_id !== target), plant];
      }
    } else if (effect.type.startsWith('plant.')) {
      const plant = state.plants.find(item => item.plant_id === target);
      if (plant && effect.type === 'plant.grow') {
        const value = params.amount ?? params.stage ?? 1;
        const amount = typeof value === 'number' && !Number.isNaN(value) ? integer(value) : 1;
        advanceTopology(plant, state.effective_time, Math.max(0, amount));
        plant.growth_points = Math.max(0, plant.growth_points + amount);
      } else if (plant && effect.type === 'plant.bloom') {
        plant.topology = plant.topology.map(node =>
          node.kind === 'bloom' ? { ...node, bloom_state: 'bloom' } : node);
      } else if (plant && effect.type === 'plant.dormancy') {
        plant.dormant = Boolean(params.dormant ?? true);
      } else if (plant && effect.type === 'plant.revive') {
        plant.dormant = false;
      } else if (plant && effect.type === 'plant.prune') {
        const removed = new Set((params.node_ids ?? []).map(String));
        let changed = true;
        while (changed) {
          const before = removed.size;
          for (const node of plant.topology) if (removed.has(node.parent_id)) removed.add(node.node_id);
          changed = removed.size !== before;
        }
        plant.topology = plant.topology.filter(node => !removed.has(node.node_id));
      }
    } else if (effect.type.startsWith('entity.')) {
      if (effect.type === 'entity.retire') {
        state.fixtures = state.fixtures.filter(item => item.fixture_id !== target);
        state.plants = state.plants.filter(item => item.plant_id !== target);
        state.collectibles = state.collectibles.filter(item => item.collectible_id !== target);
      } else {
        await revealProgramEntity(
          state, program, target, params,
          effect.type === 'entity.transform' && params.asset_id ? catalogId : null,
        );
      }
    } else if (['narrative.show', 'scene.set', 'letter.present'].includes(effect.type)) {
      if (effect.type === 'scene.set') {
        const scene = state.program_state.scene ??= {};
        for (const key of ['weather', 'palette', 'story_time', 'sky_mode', 'ambience', 'population', 'author_region']) {
          if (Object.hasOwn(params, key)) scene[key] = clone(params[key]);
        }
      } else if (effect.type === 'letter.present') {
        const presented = Array.isArray(state.program_state.presented_letters)
          ? state.program_state.presented_letters.filter(value => typeof value === 'string') : [];
        state.program_state.presented_letters = uniqueSorted([
          ...presented, String(params.letter_id),
        ]);
      }
      const labels = { 'scene.set': 'The Garden changed', 'letter.present': 'A letter is ready' };
      const label = String(params.label ?? labels[effect.type] ?? 'Garden memory');
      const description = String(params.text ?? pythonJson(params));
      const objectId = effect.type === 'letter.present'
        ? String(params.letter_id) : target ?? effect.type;
      await programJournal(state, receiptId, objectId, label, description);
    }
    state.milestone_receipts = compactRecentStrings(
      [...state.milestone_receipts, receiptId], MILESTONE_RECEIPT_LIMIT,
    );
    state.event_trace.push(normalizeTrace({
      trace_id: await stableId('trace', state.world_id, 'program', receiptId),
      sequence: state.command_sequence, kind: `program:${effect.type}`,
      target_id: target, effective_time: state.effective_time,
      summary: `Applied authored Garden event ${eventId}.`,
    }));
    state.event_trace = compactEventTrace(state.event_trace);
    materialized.push(receiptId);
  }
  state.program_state.milestone_receipt_total = Math.max(
    priorReceipts.length, integer(state.program_state.milestone_receipt_total),
  ) + materialized.length;
  return [deserializeWorldState(serializeWorldState(state)), materialized];
}
