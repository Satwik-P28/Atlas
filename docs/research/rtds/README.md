# Real-world revision study

What is in this folder, and how to read it:

| file | what it is |
|---|---|
| `PREREGISTRATION.md` | the protocol, written before the confirmatory run; §9 records the amendments |
| `REPORT.md` | the paper draft: data, design, results, threats, references |
| `NOVELTY.md` | targeted literature positioning and what is/isn't new |
| `../../artifacts/research/rtds/dataset.json` | the event archive: 392 decision/audit pairs with per-input values, vintages and digests |
| `../../artifacts/research/rtds/dataset.md` | generated summary of the archive |
| `../../artifacts/research/rtds/results.json` | per-event results and all statistics |
| `../../artifacts/research/rtds/tables.md` | every table in the paper, generated from the JSON |

Scripts: `scripts/research/rtds_build.py` (fetch and build), `rtds_study.py` (decisions, certificates,
baselines, statistics), `rtds_tables.py` (render tables).

Headline, in one paragraph: across 2,347 ALFRED vintage responses and 152 confirmatory
decision/audit pairs,
47–63% of authentic revisions move the optimal decision by more than the declared tolerance; a
certificate computed from the original decision proves immateriality for 29–42% of events, never
certifies a material revision as immaterial, and selects exactly the events a classical active-set test
already selects; revision size does not predict materiality (AUC 0.49–0.61) while decision geometry
does (AUC 0.88–0.94).
