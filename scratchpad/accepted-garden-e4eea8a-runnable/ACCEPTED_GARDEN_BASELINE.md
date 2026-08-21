# Accepted Garden baseline

This directory is a complete archive of commit
`e4eea8a256af060fa4c22deba257f3f16995f54e`, with one functional repair:
`_preparedFont` is declared beside the other Pretext cache state in
`viewer-bnw.html`.

The repair prevents `teardownResize()` from throwing when the standalone
Garden is entered. It does not change the Garden composition or artwork.

Run it from this directory or from the parent repository:

```sh
./run-garden.sh
```

Pass another port when `8878` is occupied:

```sh
./run-garden.sh 8890
```

The launcher serves this directory, opens the standalone viewer in Google
Chrome, and stays attached to the server until interrupted with Ctrl-C.

Verify that no baseline file has changed:

```sh
./verify-baseline.sh
```

See `baseline-receipt.json` for source, patch, and verification identity.
