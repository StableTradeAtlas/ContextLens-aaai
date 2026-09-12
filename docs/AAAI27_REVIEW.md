# Minimum revisions for the AAAI-27 demonstration submission

Review date: 2026-09-12. Reviewed the uploaded three-page paper
(two content pages and one references-only page), the two-page supplement,
the original repository at 3daa80acbe8db94914d77fa5d1e5c0e1c5f17b1d,
and the proposed reproducibility/deployment changes.

The demonstration is concrete and inspectable. Its main review risk is the gap
between the stated temporal/evidence guarantees and the implementation.
Keep the four-view scenario and existing limitations; revise the guarantees and
provide a reproducible artifact. A new user study is not needed to substantiate
the implementation claims made here.

## Conference fit

The official [AAAI-27 demonstration call](https://aaai.org/conference/aaai/aaai-27/demonstration-call/)
specifies two content pages plus one references-only page, a video of at most
five minutes, and permits either single-blind or double-blind submissions.
It emphasizes clarity, significance, AI relevance, and audience engagement;
the demo track does not require the reproducibility checklist.

The current page allocation fits. A supplement does not replace the demo video.
For this named public repository, single-blind submission is the smallest
consistent choice: restore the approved author block in both PDFs.
An anonymous submission requires appropriately anonymized linked artifacts.

## Paper: targeted replacements

### 1. Make the AI contribution and the demonstrated mode precise

The title's word "Agent" invites questions about autonomous planning or model
behavior that the four-view interface does not demonstrate. A lower-risk title is:

> ContextLens: Evidence-Grounded Historical Address Investigation

At the end of the design-rationale paragraph, use:

> ContextLens integrates candidate place resolution, rule-based evidence ranking,
> and explicit claim-to-source links in an interactive historical-address workflow.

Replace the broad model paragraph with:

> An optional backend endpoint supports model-assisted interpretation. The main
> four-view demonstration uses deterministic dossier answers. Model-returned
> evidence identifiers are checked against supplied identifiers; this check does
> not establish the factual entailment of generated prose.

The current model prompt includes evidence cards as well as relations and audit
states. The parser filters identifiers, but does not rewrite unsupported sentences.
Avoid asserting that the prompt contains only admitted evidence or that identifier
filtering validates all historical statements. The public hosted adapter uses no model.

### 2. Align Figure 1 and the data paragraph with the actual address path

The 154-record JSON snapshot is real. It feeds the separate indexed research
interface in app/agent.py. The main address route in app/place_investigation.py
uses bundled curated candidates and place features, with optional live enrichment locally.

Replace the snapshot paragraph's opening with:

> The address demonstration uses curated, source-linked road identities and place
> features bundled with the application. A separate indexed research interface
> uses a 154-record Shanghai Library snapshot spanning five data families.

In Figure 1, replace the retrieval subtitle with "curated source-linked records".
Use "source-linked" consistently where "verified" would imply historical truth.
Keep the exact 154-record breakdown and source checksums in the appendix/repository.

The curated and snapshot paths have different lineage detail. In the abstract,
describe the common fields as identifier, source URI, and available provenance;
do not promise every field on every card. Six dated road-name entries include
auxiliary public sources, so do not imply all six are independently verified
Shanghai Library attestations.

### 3. State the temporal behavior that is actually enforced

Replace "temporal constraint" with "era hint" where describing the current query.
The resolver matches aliases and preserves dated names; feature ranking has no
universal query-year filter. The 1934 query also returns context from 1927.

Suggested replacement for the first claim-gating sentences:

> The resolver matches aliases and house-number cues while preserving dated
> road-name entries. Rule-based gates use address matches, available dates, and
> source links to distinguish direct claims from context. Query-year compatibility
> is not universally enforced, so the timeline retains broader historical context.

This narrows the paper to the shipped behavior. Implementing stricter temporal
admission would require a separate change and revalidation of the examples.

### 4. Explain what the two direct claims count

Keep the measured counts: six road-name entries, three timeline nodes, four
evidence cards, and two entries labeled direct. The two direct entries are one
house-number-linked bookstore event and one road-level synthesis.

Suggested scenario sentence:

> The dossier presents three timeline nodes and four evidence cards. Its two
> direct-claim entries comprise the No. 436 bookstore event and a road-level
> synthesis; they do not represent two independent facts at No. 436 in 1934.

Three distinct feature-source URIs support the claim summary; the fourth card
provides the road identity. Distinct URIs alone do not establish independent
corroboration. Distinguish a 1934 founding date from the event record's broader
1934–1950 operating period.

### 5. Replace a redundant conclusion with reproducibility information

After adopting the tested deployment changes, use a compact paragraph:

> The repository provides a credential-free local launch and a stateless hosted
> deployment using the same bundled resolver and claim code. Python 3.12 and
> Node.js 24 are used for reproduction. All 29 existing tests and eight deployment
> tests pass. Versioned acceptance outputs cover two resolved addresses, an
> ambiguous query, and an unresolved query.

Cite the frozen tested commit and artifact link in the space saved by shortening
the conclusion. The report includes checksums and full outputs.
Use the current CI run and commit, not a mutable success count copied from an
earlier draft. These checks support implementation behavior, not retrieval
accuracy or historical correctness.

Narrow the offline sentence to:

> The local bundled-evidence flow runs offline; archival images, map tiles, and
> original source pages require network access.

Add the actual repository, video, and verified deployment URLs in the paper or
submission artifact fields, consistent with the chosen anonymity mode.
The PDFs have not been edited or recompiled; these are proposed replacement passages.

## Supplement: retain two pages, replace duplication with a reproducibility contract

1. **Figure A1:** show two entry points (local jobs and stateless hosted requests)
   sharing the same address core. Connect curated road/features to this core.
   Move the 154-record SQLite research path to a clearly separate optional block.
   Label the model endpoint as optional and separate from the demonstrated UI.
   Use the Mermaid topology in README.md as the implementation reference.
2. **Figure A2:** change temporal alignment to date preservation/context selection.
   Treat QuerySpec as a conceptual schema unless a concrete class is implemented.
   Separate operations from produced artifacts in the caption; do not label all
   seven existing boxes as operations or all as artifacts.
3. **Use the freed space for one compact table** with runtime versions, launch and
   test commands, snapshot checksum, four acceptance cases, and network/credential
   requirements. Link to full outputs rather than duplicating another architecture
   description. Preserve the distinction between record traceability and truth.

Suggested acceptance table:

| Input | Era | Expected bundled result |
|---|---|---|
| 436 Avenue Joffre | 1934 | One resolved candidate; six name entries; three timeline nodes; four evidence cards; two direct-claim entries with different scopes |
| 20 The Bund | 1930s | One resolved candidate; two timeline nodes; two evidence cards |
| Nanjing Road department store | 1930s | Two candidates requiring confirmation |
| 9999 Mars Road | 1934 | Unresolved; no invented dossier |

Use [reproducibility/demo-report.json](../reproducibility/demo-report.json) for
exact query normalization, evidence IDs, results, checksums, runtime version, and
tested source commit. Case timings are local bundled-Python measurements, not
hosted latency measurements.

## Minimum repository work in this proposal

- Correct Python minimum version, current data counts, mode boundaries, and data attribution.
- Add the Mermaid software architecture and three annotated GIF walkthroughs,
  generated from the running interface, with static fallbacks.
- Add pinned development dependencies, all-test discovery, four acceptance cases,
  exported results/checksums, and CI capture.
- Add the stateless Python API and compatible frontend response handling for Vercel.
- Preserve the packaged local launch and separate mutable runtime paths.
- Provide [Git-import deployment instructions](VERCEL.md) with no required secrets,
  paid model API, or database.

The frontend build, tests, acceptance outputs, and browser capture are verifiable
in GitHub Actions. The Vercel cloud deployment still needs to be created and
checked at its actual public URL. After reviewing and merging, freeze a release
commit and use that same version in the paper, appendix, and recorded video.
