# Biotech Alpha Lab

Biotech Alpha Lab is an AI-assisted investment research workspace focused on
Hong Kong-listed innovative drug companies. The first version is deliberately
research-first: it helps collect evidence, structure pipeline data, track
clinical catalysts, compare competitors, and produce long-term investment
memos. It does not place trades.

## Initial Scope

- Market: Hong Kong equities first, with A-share and US references as needed.
- Sector: innovative drug and biotech companies, especially HKEX Chapter 18A
  issuers.
- Style: long-term portfolio research, not short-term automated trading.
- Workflow: single-company research before portfolio ranking.
- Decision mode: decision support only; no broker integration in MVP.

## Core Idea

Innovative drug companies cannot be evaluated only with classic cash-flow
metrics. The research object should be decomposed like this:

```text
Company -> Pipeline asset -> Target -> Indication -> Trial phase
        -> Competitive landscape -> Catalyst -> Probability-adjusted value
```

The system treats pipeline quality, clinical progress, competitive intensity,
cash runway, and upcoming catalysts as first-class data.

## Repository Layout

```text
docs/
  PRD.md              Product definition and MVP boundaries
  ARCHITECTURE.md     System architecture and data flow
  AGENTS.md           Agent roles and structured output contracts
  DATA_SOURCES.md     Data sources and access notes
  ROADMAP.md          Suggested implementation sequence
src/biotech_alpha/
  clinicaltrials.py   Minimal ClinicalTrials.gov API client
  models.py           Domain models for trials, pipeline assets, and memos
  agents.py           Agent interface sketches
  cli.py              Small command-line entry point
tests/
  test_clinicaltrials.py
```

## Quick Start

Run the test suite:

```bash
python3 -m unittest discover -s tests
```

Try the ClinicalTrials.gov client:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli clinical-trials Akeso --limit 3
```

## Current Data Reality

Free and official data is enough for a useful MVP:

- ClinicalTrials.gov provides a structured API for global clinical trials.
- China's drug clinical trial registration platform is useful for domestic
  trial disclosure.
- HKEX filings, annual reports, prospectuses, and announcements are critical
  for pipeline and capital market disclosures.

Professional coverage will eventually need paid or semi-paid data sources for
cleaner market data, drug databases, and full competitive landscape coverage.

## Guardrails

- Every conclusion should cite evidence.
- Each agent should return structured data, not only prose.
- The system should preserve data snapshots used for each memo.
- Backtests must avoid look-ahead bias.
- LLM output should support research decisions, not execute trades.
