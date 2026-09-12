# Reproduce the address demonstration

## Environment and one-command checks

Reference environment: Python 3.12, Node.js 24, npm dependencies pinned by
package-lock.json. The core Python runtime requires no third-party packages.
requirements-dev.txt pins pytest and the browser-capture tools.

Open a terminal in the extracted project folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
npm ci
npm run check
npm run build
python -m pytest -q
python scripts/demo_report.py
```

On Windows, activate with .venv\Scripts\activate instead.
Use Python 3.11 or newer for the original local app; Python 3.12 is the shared
reference version for CI and Vercel.

Run pytest rather than only executing tests/test_place_investigation.py: the
original file's main block does not call every defined test function. The original
suite contains 29 functions, and the serverless adapter adds 8 targeted tests.
Use the collected/passed count and tested commit in the CI output.

## Four acceptance cases

| Input | Expected behavior |
|---|---|
| 436 Avenue Joffre, 1934 | The browser translates this curated English example to 霞飞路436号; inspect its named-road history and source-linked dossier. |
| 20 The Bund, 1930s | The browser maps the curated example to 外滩20号; inspect its source-linked dossier. |
| Nanjing Road department store | Preserve multiple candidate roads for user selection. |
| 9999 Mars Road | Return unresolved without inventing a dossier. |

The Python report uses the corresponding Chinese canonical inputs directly.
It records candidate counts, timeline nodes, evidence-card counts, direct-claim
counts, distinct feature-source counts, per-case elapsed time, complete dossier
JSON, source commit, runtime, and SHA-256 hashes for the snapshot and relevant code.

reproducibility/demo-report.json is generated from an actual run. These four
curated examples are acceptance checks, not a held-out historical resolution
benchmark. Test pass counts are not accuracy estimates; measured timing is specific
to the recorded machine and data mode.

## Capture README GIFs from the actual interface

```bash
python scripts/prepare_vercel.py
python -m playwright install chromium
python scripts/capture_walkthrough.py
```

The script starts the stateless preview, runs real browser interactions, adds
explanatory captions, and saves three GIFs plus PNG fallbacks under docs/media/.
It also verifies that the evidence download contains actual claims and records.
The GIFs are sequences of captured interface states, not a continuous timing
measurement. External imagery may be unavailable in some recording environments.

The Reproduce demo workflow runs the same checks and packages the demo files.

## What is and is not reproduced

- The same curated alias/feature rules and claim gates run locally and on Vercel.
- The local research interface separately loads the 154-record library snapshot
  into SQLite. The main address route does not query all 154 records.
- Optional live calls and model interpretation are not part of the hosted demo.
- Dates are retained, but universal filtering by the query year is not implemented.
- The credential-free local evidence flow is available offline; external map
  images, basemap tiles, and original source pages require a network.
- The archived JSON preserves raw record objects and source-payload hash metadata,
  but not the complete set of 93 original HTTP response files.

## Preserve a verified version

Keep the tested source commit, query outputs, test results, and SHA-256 source
checksums together so the demonstration can be reproduced from the same version.
