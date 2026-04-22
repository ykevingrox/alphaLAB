# Handoff

This file is the compact working-memory handoff for Codex, Cursor, or any other
agent editing this repository. Keep it current and short.

## Fixed Switch Prompt

Copy this when switching between tools:

```text
先读 docs/HANDOFF.md，然后检查 git status 和最近 diff。
不要重做已经完成的事，评估当前状态后继续 Next Best Action。
```

## Current Goal

Make the HK biotech single-company MVP reliable:

```text
company name or ticker in -> one-command report out
```

The near-term priority is still HK biotech. Future compatibility with other
markets and sectors should influence design choices, but should not distract
from getting the MVP stable.

## Last Completed

- `company-report --auto-inputs` can resolve HKEX annual-results sources,
  download the source PDF, extract text, generate draft pipeline and financial
  inputs, validate them, and run the report.
- Cursor/Codex follow-up work added a conference-catalyst input layer:
  `conference-template`, `conference-validate`,
  `research --conference-catalysts`, and auto-drafted conference catalysts from
  HKEX annual-results text.
- Report summaries and saved manifests now include a `quality_gate`.
- `watchlist-rank` can filter entries by minimum quality gate.
- Manual curated inputs still override generated inputs.
- Auto-input generation is resilient: one-command reporting should continue
  even if auto input generation fails.
- Suggested rerun commands preserve `--auto-inputs` when the current run used
  automatic input generation.
- Auto-input source metadata can enrich company identity with HKEX stock-name
  aliases, so Chinese company input can still search English registry terms.
- Network-free fixture tests cover the `generate_auto_inputs` orchestration
  path.
- Generated pipeline extraction recognizes more oncology/immunology targets,
  richer phase strings, and filters payload-only mentions such as `P1021`.
- Generated pipeline extraction also avoids partial hyphen-code matches such as
  `C9074` from `BG-C9074`, and combination partner assets such as `BNT116`.
- Repeated asset mentions now enrich missing fields, so later detailed sections
  can fill phase or indication fields from earlier summary mentions.

## Current Repo State

- Branch: `main`
- Remote: `origin https://github.com/ykevingrox/alphaLAB.git`
- Check `git log --oneline -1` for the latest committed baseline.
- Expected steady state after a handoff checkpoint is a clean working tree
  except for ignored generated runtime outputs.
- Generated runtime outputs are intentionally ignored by git:
  `data/raw/`, `data/input/generated/`, `data/processed/`, and `data/memos/`.

## Latest Validation

Last validated on 2026-04-22:

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m compileall -q src tests
git diff --check
awk 'length($0) > 88 { print FILENAME ":" FNR ":" length($0) }' \
  $(rg --files -g '*.py' -g '*.md' -g '*.toml')
```

Latest result:

- 80 unit tests passed.
- Compile check passed.
- `git diff --check` passed.
- 88-character scan passed.

Latest smoke command:

```bash
.venv/bin/python -m biotech_alpha.cli company-report \
  --company "映恩生物" \
  --ticker "09606.HK" \
  --auto-inputs \
  --limit 3
```

Latest smoke result:

- HKEX annual-results source was found.
- `identity.search_term` was enriched to `DUALITYBIO`.
- Draft `pipeline_assets`, `financials`, and `conference_catalysts` were
  generated.
- Report ran successfully.
- Suggested rerun command preserved `--auto-inputs`.
- Generated pipeline validation warnings fell to 1 in the latest smoke run.
- Quality gate was `research_ready_with_review`.
- Remaining missing inputs were `competitors`, `valuation`, and
  `target_price_assumptions`.

## Next Best Action

1. Commit the current validated local changes as a small checkpoint.
2. Continue tightening generated pipeline extraction for remaining source-backed
   missing indication cases such as `DB-1312`.
3. Improve HKEX source discovery robustness and retry behavior.
4. Add auto valuation drafts once source-backed market data is available.
5. Add auto competitor drafts only after pipeline extraction is more reliable.

## Do Not Break

- `company-report` must accept either `--company` or `--ticker`.
- Manual input files in `data/input/` must override generated drafts in
  `data/input/generated/`.
- Generated input files are drafts and should remain human-review flagged.
- The one-command report should not fail just because auto-input generation
  fails.
- Saved reports should remain auditable through source links, manifests, and
  validation warnings.
- Do not commit generated PDFs, processed report outputs, memos, virtualenvs, or
  cache files.
