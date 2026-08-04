/**
 * The ONE runtime validator of the accepted-paint authority manifest.
 *
 * WHAT PROBLEM THIS FILE SOLVES
 * -----------------------------
 * The manifest (`web/garden-accepted-paint.v1.json`) is authored by exactly
 * one writer -- `paint_authority()` in `scripts/prepare_pages_site.py` --
 * with a defined shape: `schema`, `purpose`, `registers` (both register
 * paths with their sha256 digests), four accepted-id lists, plus the separate
 * local-review list (`review_candidate_assets`). The 2026-08-04 claim
 * verification found three
 * separate hand-rolled checks (viewer, composer, renderer) that each
 * accepted a PARTIAL object carrying only three of the lists -- three schema
 * owners, all of them wrong, free to drift apart. This module replaces all
 * three: every consumer imports the same validator, so the runtime notion of
 * "a valid authority" has one owner that mirrors the generator.
 *
 * WHAT VALIDATION MEANS HERE
 * --------------------------
 * Structural truth, not register truth. The browser cannot re-derive the
 * registers, so it checks that the manifest IS the artifact the generator
 * writes: right schema version, all four lists present and made of strings,
 * register records present with their digest fields. Whether the digests
 * still MATCH the registers is the drift test's job at build time
 * (`verify_paint_manifest`), not the viewer's at boot.
 *
 * FAIL DISPOSITION
 * ----------------
 * `validatePaintAuthority` throws; composition and construction refuse.
 * `isValidPaintAuthority` answers a boolean for callers (the viewer's boot
 * path) that want to refuse with their own presentation instead of an
 * exception. Both run the same single check -- the boolean form simply
 * catches the throw, so the two can never disagree.
 */

// The four accepted-id lists the generator writes. `accepted_laws` is
// carried and validated even though laws are never legal paint sources:
// a manifest without it is not the generator's artifact, and the composer's
// own law-exclusion logic depends on knowing the list is really there.
export const PAINT_AUTHORITY_LISTS = Object.freeze([
  'accepted_assets',
  'review_candidate_assets',
  'accepted_recipes',
  'accepted_laws',
  'accepted_legacy_art',
]);

// The schema version this runtime understands. Bump ONLY together with the
// generator in scripts/prepare_pages_site.py.
export const PAINT_AUTHORITY_SCHEMA = 2;

/**
 * Validate a candidate manifest against the generator's shape.
 *
 * @param {unknown} manifest - whatever the fetch (or a test) produced
 * @returns {object} the same manifest, now known to be structurally valid
 * @throws {Error} naming the first defect found, prefixed so every refusal
 *   is greppable as "paint authority absent or invalid"
 */
export function validatePaintAuthority(manifest) {
  const refuse = reason => {
    throw new Error(
      `paint authority absent or invalid: composition refused (${reason}). ` +
      'Pass the build-derived accepted-paint manifest ' +
      '(web/garden-accepted-paint.v1.json).',
    );
  };
  if (!manifest || typeof manifest !== 'object' || Array.isArray(manifest)) {
    refuse('not a manifest object');
  }
  if (manifest.schema !== PAINT_AUTHORITY_SCHEMA) {
    refuse(`schema ${JSON.stringify(manifest.schema)} is not ${PAINT_AUTHORITY_SCHEMA}`);
  }
  for (const name of PAINT_AUTHORITY_LISTS) {
    if (!Array.isArray(manifest[name])) refuse(`${name} is not a list`);
    if (!manifest[name].every(item => typeof item === 'string')) {
      refuse(`${name} holds a non-string id`);
    }
  }
  const registers = manifest.registers;
  if (!registers || typeof registers !== 'object') refuse('registers record is missing');
  for (const register of ['asset_register', 'recipe_register']) {
    const record = registers[register];
    if (!record || typeof record !== 'object' ||
        typeof record.path !== 'string' || typeof record.sha256 !== 'string') {
      refuse(`${register} record is missing its path or sha256`);
    }
  }
  return manifest;
}

/**
 * The boolean form of the same single check, for refuse-with-presentation
 * callers like the viewer's boot path.
 *
 * @param {unknown} manifest - whatever the fetch produced
 * @returns {boolean} true exactly when `validatePaintAuthority` would return
 */
export function isValidPaintAuthority(manifest) {
  try {
    validatePaintAuthority(manifest);
    return true;
  } catch {
    return false;
  }
}
