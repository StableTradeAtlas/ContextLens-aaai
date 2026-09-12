# Data card

## Published snapshot

data/processed/shlibrary_official_snapshot.json contains 154 normalized records.
The metadata reports 93 source response files and generation on 2026-08-21.

| Data family | Records |
|---|---:|
| Historic architectures | 71 |
| Roads and place names | 45 |
| Yearbook organizations | 23 |
| Historical events | 10 |
| Person authority | 5 |
| Total | 154 |

Each record includes the raw record object, official URI, dataset, query term,
retrieval timestamp, source payload hash, evidence ID, and normalization label.
The complete 93 original HTTP-response files are not distributed separately.
Their hashes therefore cannot all be recomputed from this repository alone.
The snapshot itself can be byte-checked using scripts/demo_report.py.

## Which data the demonstration uses

The four-view address workflow uses source-linked curated road identities and
place features bundled in app/place_investigation.py, supplemented by live APIs
when configured locally. The separate legacy research interface indexes the
154-record JSON snapshot. The collection total is not the number of matches
returned for any query and is not a held-out evaluation set.

The old app/sample_data.py seed collection remains for legacy fallback behavior.
Normal ingestion removes those seed records when the official snapshot is present.
The hosted address adapter does not load seed records or call live/model services.

## Limits and reuse

Official provider provenance does not certify historical truth. Curated records,
date interpretations, aliases, and coordinates still need expert review. Not every
place card carries the full snapshot lineage. Confidence values are heuristic.

The Apache-2.0 license covers project code; underlying library records, maps, and
third-party assets retain their own rights and attribution requirements. Public
access to a source URI should not be interpreted as an unrestricted reuse license.
Review source-specific terms before redistributing further material.

Historical scans and modern map tiles are external assets. The bundled local
evidence flow works without library/model keys; fresh map imagery and original
source pages require network access.
