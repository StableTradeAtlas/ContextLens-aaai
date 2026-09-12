# Four-minute demonstration script

Use the same build, query spelling, data mode, and language in the paper, video,
and live demonstration. Run scripts/demo_report.py before recording and use its
actual counts. Do not narrate an unexecuted model feature as part of this interface.

| Time | Action | Point to explain |
|---|---|---|
| 0:00–0:30 | Enter 436 Avenue Joffre and 1934 | A historical address can have several dated names. |
| 0:30–1:10 | Open Identity, then Events | Alias resolution and dated evidence; dates do not imply universal query-year filtering. |
| 1:10–1:45 | Open Atlas | Historical scan and modern map are side by side; no precise house-number overlay is claimed. |
| 1:45–2:35 | Open Sources and a Source Passport | Follow an evidence ID to its source; distinguish curated cards from the full collection. |
| 2:35–3:00 | Download evidence JSON | The exported claim links match the displayed dossier. |
| 3:00–3:30 | Search Nanjing Road department store | Ambiguity remains visible for user confirmation. |
| 3:30–4:00 | Search 9999 Mars Road | Unsupported input returns unresolved. |

Local launch: python3 start.py, then open http://127.0.0.1:8765.
Hosted-parity preview: see VERCEL.md; port 8766.

README GIFs are annotated captures of real browser states. They supplement a
submission video; they are not a substitute for the call's requested demonstration
media. The optional model endpoint is a separate local research feature.
