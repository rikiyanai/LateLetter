/**
 * GENERATED FILE -- DO NOT EDIT.
 *
 * Produced by `scripts/migrate_atlas_v2.py` from
 * `src/lateletter/garden/data/atlas.v2.json`. Edit the atlas and regenerate;
 * editing this file directly would recreate exactly the split art ownership
 * that moving to the atlas was meant to end.
 *
 * Contains every asset carrying the `browser-proportional` profile. Each entry
 * holds the asset's drawing anchor, its cell box, and its states as row strings.
 * Row strings are NOT cell matrices: their on-screen width is measured at
 * runtime by `web/garden-geometry.mjs`, so counting their characters means
 * nothing. See SPEC 7.9.3.
 *
 * Generator version: atlas-migrate-2
 * Atlas id: garden-atlas-2
 */

/** The font these row strings were drawn against and must be measured in. */
export const ATLAS_PROPORTIONAL_FONT = Object.freeze({
  "family": "LateLetter Garden",
  "size_px": 15,
  "line_height_px": 17,
  "weight": 400,
  "style": "normal",
  "letter_spacing": "normal",
  "resource": "web/fonts/lateletter-garden.woff",
  "resource_sha256": "f6be01765d77f1045d4a098e907219975536ae6403ee8b4dc9928e8f7bce1780"
});

/** Canonical proportional art, keyed by canonical asset id. */
export const ATLAS_PROPORTIONAL_ART = Object.freeze({
  "fixture.bench": {
    "anchor": [
      4,
      3
    ],
    "cell_box": [
      9,
      4
    ],
    "states": {
      "idle": [
        {
          "ticks": 1,
          "rows": [
            " |_|_|_| ",
            "_|_____|_",
            " |     | ",
            " '     ' "
          ]
        }
      ]
    }
  },
  "fixture.trellis": {
    "anchor": [
      4,
      4
    ],
    "cell_box": [
      10,
      5
    ],
    "states": {
      "idle": [
        {
          "ticks": 1,
          "rows": [
            " \\/\\/\\/\\/ ",
            " /\\/\\/\\/\\ ",
            " \\/\\/\\/\\/ ",
            " /\\/\\/\\/\\ ",
            " |      | "
          ]
        }
      ]
    }
  },
  "fixture.birdbath": {
    "anchor": [
      4,
      3
    ],
    "cell_box": [
      9,
      4
    ],
    "states": {
      "idle": [
        {
          "ticks": 1,
          "rows": [
            " \\~~~~~/ ",
            "  '-|-'  ",
            "   _|_   ",
            "  /___\\  "
          ]
        }
      ]
    }
  },
  "fixture.lantern": {
    "anchor": [
      3,
      6
    ],
    "cell_box": [
      7,
      7
    ],
    "states": {
      "idle": [
        {
          "ticks": 1,
          "rows": [
            "   _   ",
            "  (*)  ",
            "  |||  ",
            "  |||  ",
            "  |||  ",
            "  |||  ",
            " /___\\ "
          ]
        }
      ]
    }
  },
  "fixture.pond": {
    "anchor": [
      11,
      3
    ],
    "cell_box": [
      24,
      4
    ],
    "states": {
      "idle": [
        {
          "ticks": 10,
          "rows": [
            "  _,-~-.,_,-~-.,_,-~-.  ",
            "( ~~      ~~~      ~~  )",
            "(    ~~~      ~~      ~)",
            "  `-.,_,-~-.,_,-~-.,_-' "
          ]
        },
        {
          "ticks": 10,
          "rows": [
            "  _,-~-.,_,-~-.,_,-~-.  ",
            "(   ~~      ~~~      ~~)",
            "(  ~~~      ~~      ~~ )",
            "  `-.,_,-~-.,_,-~-.,_-' "
          ]
        },
        {
          "ticks": 10,
          "rows": [
            "  _,-~-.,_,-~-.,_,-~-.  ",
            "(     ~~      ~~~    ~ )",
            "(~~~      ~~      ~~   )",
            "  `-.,_,-~-.,_,-~-.,_-' "
          ]
        },
        {
          "ticks": 10,
          "rows": [
            "  _,-~-.,_,-~-.,_,-~-.  ",
            "(   ~~      ~~~      ~~)",
            "(  ~~~      ~~      ~~ )",
            "  `-.,_,-~-.,_,-~-.,_-' "
          ]
        }
      ]
    }
  },
  "fixture.mailbox": {
    "anchor": [
      3,
      3
    ],
    "cell_box": [
      7,
      4
    ],
    "states": {
      "idle": [
        {
          "ticks": 1,
          "rows": [
            "   7   ",
            " (__(_)",
            "   ||  ",
            "  _||_ "
          ],
          "accents": {
            "0,3": "signal"
          }
        }
      ]
    }
  },
  "fixture.stepping_stones": {
    "anchor": [
      5,
      1
    ],
    "cell_box": [
      12,
      2
    ],
    "states": {
      "idle": [
        {
          "ticks": 1,
          "rows": [
            " (=)  (=)   ",
            "    (=)  (=)"
          ]
        }
      ]
    }
  },
  "fixture.bridge": {
    "anchor": [
      5,
      2
    ],
    "cell_box": [
      11,
      3
    ],
    "states": {
      "idle": [
        {
          "ticks": 1,
          "rows": [
            " /=|=|=|=\\ ",
            "_|       |_",
            " '       ' "
          ]
        }
      ]
    }
  },
  "fixture.planter": {
    "anchor": [
      5,
      3
    ],
    "cell_box": [
      11,
      4
    ],
    "states": {
      "idle": [
        {
          "ticks": 1,
          "rows": [
            "   Y   Y   ",
            "  ,|   |,  ",
            " [_______] ",
            "  \\_|_|_/  "
          ]
        }
      ]
    }
  },
  "fixture.arbor": {
    "anchor": [
      5,
      3
    ],
    "cell_box": [
      11,
      4
    ],
    "states": {
      "idle": [
        {
          "ticks": 1,
          "rows": [
            "  ,~^~^~,  ",
            " ((     )) ",
            " ||     || ",
            " ||     || "
          ]
        }
      ]
    }
  },
  "fixture.planter_one": {
    "anchor": [
      5,
      3
    ],
    "cell_box": [
      11,
      4
    ],
    "states": {
      "idle": [
        {
          "ticks": 1,
          "rows": [
            "     Y     ",
            "    ,|     ",
            " [_______] ",
            "  \\_|_|_/  "
          ]
        }
      ]
    }
  },
  "fixture.planter_three": {
    "anchor": [
      6,
      3
    ],
    "cell_box": [
      13,
      4
    ],
    "states": {
      "idle": [
        {
          "ticks": 1,
          "rows": [
            "  Y   Y   Y  ",
            " ,|   |   |, ",
            " [_________] ",
            "  \\__|_|__/  "
          ]
        }
      ]
    }
  },
  "fixture.pond_compact": {
    "anchor": [
      9,
      3
    ],
    "cell_box": [
      20,
      4
    ],
    "states": {
      "idle": [
        {
          "ticks": 10,
          "rows": [
            "  _,-~-.,_,-~-.,_-. ",
            "(~~    ~~~    ~~   )",
            "(    ~~    ~~~    ~)",
            "  `-.,_,-~-.,_,-'   "
          ]
        },
        {
          "ticks": 10,
          "rows": [
            "  _,-~-.,_,-~-.,_-. ",
            "(  ~~    ~~~    ~~ )",
            "( ~~    ~~~    ~   )",
            "  `-.,_,-~-.,_,-'   "
          ]
        },
        {
          "ticks": 10,
          "rows": [
            "  _,-~-.,_,-~-.,_-. ",
            "(    ~~    ~~~   ~) ",
            "(~~~    ~~    ~~   )",
            "  `-.,_,-~-.,_,-'   "
          ]
        },
        {
          "ticks": 10,
          "rows": [
            "  _,-~-.,_,-~-.,_-. ",
            "(  ~~    ~~~    ~~ )",
            "( ~~    ~~~    ~   )",
            "  `-.,_,-~-.,_,-'   "
          ]
        }
      ]
    }
  },
  "fixture.pond_round": {
    "anchor": [
      10,
      5
    ],
    "cell_box": [
      22,
      6
    ],
    "states": {
      "idle": [
        {
          "ticks": 10,
          "rows": [
            "    _,-~-.,_,-~-.     ",
            "  ,'             `.   ",
            "( ~~    ~~~    ~~    )",
            "(    ~~    ~~~    ~~ )",
            "  `-.,_       _,-'    ",
            "      `-~-~-~-'       "
          ]
        },
        {
          "ticks": 10,
          "rows": [
            "    _,-~-.,_,-~-.     ",
            "  ,'             `.   ",
            "(   ~~    ~~~    ~~  )",
            "(  ~~    ~~~    ~~   )",
            "  `-.,_       _,-'    ",
            "      `-~-~-~-'       "
          ]
        },
        {
          "ticks": 10,
          "rows": [
            "    _,-~-.,_,-~-.     ",
            "  ,'             `.   ",
            "(     ~~    ~~~    ~ )",
            "(~~~    ~~    ~~~    )",
            "  `-.,_       _,-'    ",
            "      `-~-~-~-'       "
          ]
        },
        {
          "ticks": 10,
          "rows": [
            "    _,-~-.,_,-~-.     ",
            "  ,'             `.   ",
            "(   ~~    ~~~    ~~  )",
            "(  ~~    ~~~    ~~   )",
            "  `-.,_       _,-'    ",
            "      `-~-~-~-'       "
          ]
        }
      ]
    }
  },
  "fixture.stepping_stones_five": {
    "anchor": [
      7,
      2
    ],
    "cell_box": [
      16,
      3
    ],
    "states": {
      "idle": [
        {
          "ticks": 1,
          "rows": [
            " (=)       (=)  ",
            "    (=)         ",
            "       (=)  (=) "
          ]
        }
      ]
    }
  },
  "fixture.stepping_stones_three": {
    "anchor": [
      4,
      1
    ],
    "cell_box": [
      10,
      2
    ],
    "states": {
      "idle": [
        {
          "ticks": 1,
          "rows": [
            " (=)      ",
            "   (=) (=)"
          ]
        }
      ]
    }
  }
});

/**
 * Look up one frame of canonical art by asset id.
 *
 * @param {string} assetId - Canonical id, e.g. `fixture.bench`.
 * @param {string} [state] - Desired state; falls back to `idle`.
 * @returns {{rows: string[], compactRows: string[]|null, anchor: number[], accents: object|null}|null}
 *   The first frame of that state, or null when the atlas does not own this
 *   asset yet, which is how a caller distinguishes an unmigrated asset from one
 *   that genuinely has no art.
 *
 * The wording above is deliberate. The Pages bundler finds imports with a
 * regular expression that does not know about comments, so the word `from`
 * followed by a quoted phrase reads as a real import wherever it appears --
 * including inside prose. An earlier draft of this sentence failed the deploy
 * build on a module named "no art". See FAILURE_LOG.
 */
export function canonicalProportionalArt(assetId, state = 'idle', frame = 0) {
  const asset = ATLAS_PROPORTIONAL_ART[assetId];
  if (!asset) return null;
  const frames = asset.states[state] ?? asset.states.idle;
  if (!frames || frames.length === 0) return null;
  const cycle = frames.reduce((total, item) => total + Math.max(1, Number(item.ticks) || 1), 0);
  let cursor = ((Math.floor(Number(frame) || 0) % cycle) + cycle) % cycle;
  let selected = frames[0];
  for (const item of frames) {
    selected = item;
    cursor -= Math.max(1, Number(item.ticks) || 1);
    if (cursor < 0) break;
  }
  return {
    rows: selected.rows,
    // Null rather than a copy of `rows`, so the renderer can tell an authored
    // compact drawing from the absence of one and reduce accordingly.
    compactRows: selected.compact_rows ?? null,
    anchor: asset.anchor,
    accents: selected.accents ?? null,
  };
}
