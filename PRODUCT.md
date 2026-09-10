# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Static HTML artifact (single self-contained file, published via the Artifact tool). Delegated: no framework needed for a one-time results snapshot.

## Users

Actuaries and risk professionals at a UK life insurer, reviewing the state of an in-progress internal build: a unified ALM platform modelling MA-eligible annuity liabilities and their backing assets (replacing a fragmented Prophet + R codebase).

## Product Purpose

A one-time results snapshot/report surfacing the numbers produced by Astraea, the ALM engine built so far: the two-AER Matching Adjustment calculation, all five PRA matching tests (SS7/18 Appendix 1), a market/credit/longevity stress run, Risk Margin, and a Standard Formula SCR skeleton: all run against a small, hand-verifiable "golden" toy portfolio (a 10y level annuity liability backed by a gilt and/or an A2 corporate bond). The reader is deciding whether the methodology and numbers look right, not operating the system day to day.

## Positioning

Not a live operational dashboard: a snapshot report of a specific engine run, read once by people who will scrutinize the actuarial methodology (regulatory citations, formula derivations) as much as the headline figures.

## Operating Context

Read by an actuary/risk reviewer at a desk, likely alongside the actual codebase and the project's regulatory source material (SS7/18, IRPR, MA Rulebook). Numbers must be traceable to their source calculation, not just displayed.

## Capabilities and Constraints

- Single static HTML page (Artifact tool constraints: no backend, no live data connection needed for a one-time snapshot).
- Content is a fixed set of numbers already computed and verified in the codebase (26 passing tests): this page presents them, it does not recompute them live.
- Numbers to present: MA calc (gilt scenario 0.00bp exact; A2 corporate scenario 135.4464bp), PRA Tests 1–5 (pass/fail, ratios vs thresholds), 3 stress scenarios (rate shock, spread widening, longevity shock) with MA/own-funds deltas, Risk Margin (CoC 4%/λ0.9/floor 0.25), SF SCR (spread + longevity, correlation-aggregated).

## Evidence on Hand

All figures sourced from this session's actual test runs (alm/tests/*.py, 26/26 passing): no fabricated numbers. Paths: `alm/examples/golden_toy.py` (scenario definitions), `alm/tests/*.py` (assertions), `README.md` (narrative summary this dashboard visualizes).

## Product Principles

- Every number on the page must be traceable to a specific test/calculation in the codebase: no invented figures.
- Numbers and pass/fail status lead; methodology/citations are present but secondary (per explicit direction).
- This is a snapshot, not a living dashboard: no auto-refresh or "last updated" framing implying ongoing sync.

## Accessibility & Inclusion

No specific requirement established; follow standard WCAG-reasonable defaults (contrast, semantic structure) as good practice.
