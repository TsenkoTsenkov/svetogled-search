# SEO indexing baselines

Dated snapshots of how many pages Google has indexed, produced by
`scripts/gsc_seo.py coverage`. Compare a newer run against an older baseline to
see whether the internal-link SEO is working — the number should climb as
Google recrawls `/arhiv` and follows the links to the 282 episodes.

Each file summarizes one run: total indexed, a per-page-type breakdown
(episode / theme / hub / home), and the raw coverage-state counts.

To take a fresh snapshot (needs `gcloud auth application-default login` with the
`webmasters.readonly` scope, or the `GSC_SA_KEY` service account):

    python3 scripts/gsc_seo.py coverage --json /tmp/cov.json
    # then reduce /tmp/cov.json to a dated summary here

`2026-07-05.json` is the baseline: **2/331 indexed** (only homepage + `/arhiv`),
taken right after the SEO overhaul deployed and before Google recrawled. That is
the expected starting point, not a failure — watch it climb from here.
