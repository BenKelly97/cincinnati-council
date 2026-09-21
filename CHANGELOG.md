# Changelog

Notable changes to the Cincinnati City Council transparency site, most recent first. Each entry names the files touched and the live GitHub commit.

## 2026-09-21 — Vote scraper was skipping every committee-level vote

`scrape_votes_api.py` only ever queried events where `EventBodyName eq 'Cincinnati City Council'` — full floor sessions. Any item whose only recorded vote happened at a committee meeting (a "Failed of Adoption," an "Indefinitely Postponed," anything that never reached the floor) was invisible to `votes_api.json`, and so invisible to `members.html`'s per-member vote history, even though Legistar has the roll call on record. Dropped that filter — the scraper now walks every Council and committee event, and each vote record carries a new `meeting_body` field so it's clear which body cast it; when a matter gets both a committee vote and a later floor vote, the floor vote still wins.

Ran a one-time backfill from 2020-01-01 to pick up the historical committee votes this had missed (204 new/updated records, 2,830 procedural actions correctly skipped), then rebuilt `council_data.json` so the merged `vote_yes`/`vote_no` fields that `members.html` actually reads are current — the scraper fix alone doesn't reach the site until that merge runs.

- Changed: `scrape_votes_api.py`, `votes_api.json`, `council_data.json`
- Commits: [`e6ffe60`](https://github.com/BenKelly97/cincinnati-council/commit/e6ffe60) (scrape_votes_api.py), [`dffdde3`](https://github.com/BenKelly97/cincinnati-council/commit/dffdde3) (votes_api.json backfill), [`823b753`](https://github.com/BenKelly97/cincinnati-council/commit/823b753) (council_data.json rebuild)

## 2026-09-21 — Fixed 409 conflict on Apply/Dismiss in the review page

Clicking Apply or Dismiss on `review.html` could fail with `GitHub write to summary_overrides.json failed (HTTP 409): ... does not match ...` — a cached GET response was handing back a stale `sha` to the follow-up write, which GitHub's Contents API rejects as a conflict even though nothing had actually changed. Added `cache: 'no-store'` to the read, and a new `ghWriteJson` helper that retries once on a 409 by re-fetching the current `sha` and reapplying the same edit, instead of surfacing the conflict as a dead end.

- Changed: `review.html`
- Commit: [`19c1a01`](https://github.com/BenKelly97/cincinnati-council/commit/19c1a01)

## 2026-09-20 — Suggest description changes, not just titles

The suggestion widget's first question is now "What would you like to suggest a change to?" (Title or Description) instead of assuming every suggestion is about the title. Two new Form questions capture the current description and which field the visitor picked; the reply text field is now a textarea (descriptions run longer than titles) and its placeholder switches to match the chosen field.

`review.html` mirrors the split: a new Title/Description filter, and the Apply button now writes to `summary_overrides.json` when the suggestion is for a description (previously everything went to `title_overrides.json`), while still logging every row in `suggestion_status.json` the same as before.

`update_pipeline.py` now consolidates `summary_overrides.json` into the CSV's `summary` column on its scheduled run, the same way it already did for title overrides. `index.html`, `alternative.html`, and `members.html` each fetch and merge `summary_overrides.json` at page load too — so an applied description fix is live, and searchable (search already matches against title + summary), immediately rather than waiting on the next pipeline run.

- Added: `summary_overrides.json`, `SUGGESTION_BOX_SETUP.md`
- Changed: `suggest.js`, `index.html`, `alternative.html`, `members.html`, `review.html`, `update_pipeline.py`, `.github/workflows/weekly_update.yml`
- Commits: [`c79336b`](https://github.com/BenKelly97/cincinnati-council/commit/c79336b) (suggest.js), [`1b2713b`](https://github.com/BenKelly97/cincinnati-council/commit/1b2713b) (summary_overrides.json), [`16fed34`](https://github.com/BenKelly97/cincinnati-council/commit/16fed34) (index.html), [`360e296`](https://github.com/BenKelly97/cincinnati-council/commit/360e296) (alternative.html), [`d6f2104`](https://github.com/BenKelly97/cincinnati-council/commit/d6f2104) (members.html), [`a81b89b`](https://github.com/BenKelly97/cincinnati-council/commit/a81b89b) (review.html), [`09a7c26`](https://github.com/BenKelly97/cincinnati-council/commit/09a7c26) (update_pipeline.py), [`cf5d8db`](https://github.com/BenKelly97/cincinnati-council/commit/cf5d8db) (SUGGESTION_BOX_SETUP.md), [`2b97400`](https://github.com/BenKelly97/cincinnati-council/commit/2b97400) (weekly_update.yml)

## 2026-09-20 — Password gate on the review page

`review.html` now shows a password prompt before revealing anything — the pending-suggestions list, the token box, all of it stays hidden until the correct password is entered. The password itself is never stored in the page; only its SHA-256 hash is, computed client-side with the Web Crypto API and checked against the hash on submit. Once unlocked, it stays unlocked for that browser tab/session (`sessionStorage`) — closing the browser clears it.

This sits on top of the existing protections (page is `noindex`/`nofollow` and unlinked from the public site) rather than replacing them, and is separate from the GitHub token that's still required for Apply/Dismiss to actually write to the repo.

- Changed: `review.html`
- Commit: [`5682d59`](https://github.com/BenKelly97/cincinnati-council/commit/5682d59)

## 2026-09-20 — Weekly pipeline now commits title overrides

One-line fix to the scheduled GitHub Action: `title_overrides.json` was missing from the `git add` list in the Mon/Wed/Fri workflow, so any title fix queued through `review.html`'s Apply button would sit in the override file but never get consolidated into `cincinnati_agenda_items_complete.csv` on the next scheduled run. Added it to the commit step.

- Changed: `.github/workflows/weekly_update.yml`
- Commit: [`bc24677`](https://github.com/BenKelly97/cincinnati-council/commit/bc24677)

## 2026-09-20 — One-click Apply/Dismiss on the review page

Replaced the old manual workflow (hand-edit the pipeline, check off the row in the Google Sheet) with direct action buttons on `review.html`:

- **Apply title** writes the corrected title straight to `title_overrides.json` in the repo via the GitHub Contents API, so the fix shows up on the live site immediately (the site pages merge overrides over `council_data.json`'s title at render time), and logs the submission as handled in `suggestion_status.json`.
- **Dismiss** just logs the submission as handled without touching any data.
- Both require a GitHub personal access token, pasted once into the page and kept only in that browser's `localStorage` — never sent anywhere but GitHub's API.
- `update_pipeline.py` now reads `title_overrides.json` on its next scheduled run, bakes any pending overrides into the CSV's `clean_title` column, and clears the ones it applied — so the fix survives the full data rebuild instead of only living in the override file.
- `index.html`, `alternative.html`, and `members.html` each got a small snippet to fetch and merge `title_overrides.json` at page load.

- Changed: `review.html`, `update_pipeline.py`, `index.html`, `alternative.html`, `members.html`
- Added: `title_overrides.json`, `suggestion_status.json`
- Commit: [`014e5ad`](https://github.com/BenKelly97/cincinnati-council/commit/014e5ad)

## 2026-09-19 — Fixed card-collapse bug in the suggestion widget

Clicking inside the "suggest a better title / flag inaccurate" form (typing in a field, clicking a button) was bubbling up to the parent card's click handler and collapsing the card mid-submission. Added `stopPropagation()` on click/mousedown inside the form so interacting with it no longer closes the card.

- Changed: `suggest.js`
- Commit: [`e4d0bc5`](https://github.com/BenKelly97/cincinnati-council/commit/e4d0bc5)

## 2026-09-19 — Launched "suggest a better title / flag inaccurate" widget

Added the public-facing feedback widget to every agenda item card across the site: visitors can suggest a better title or flag one as inaccurate, which posts to a Google Form → Google Sheet. Added `review.html` as the (unauthenticated, unlinked, `noindex`) admin page for reading submissions from the published Sheet CSV.

- Added: `review.html`, `suggest.js`
- Changed: `index.html`, `alternative.html`, `members.html`
- Commit: [`3ba0a54`](https://github.com/BenKelly97/cincinnati-council/commit/3ba0a54)
