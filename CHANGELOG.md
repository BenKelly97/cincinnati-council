# Changelog

Notable changes to the Cincinnati City Council transparency site, most recent first. Each entry names the files touched and the live GitHub commit.

## 2026-10-14 — Member page: year range order and data note

**Year range (`members.html`).** The heading read "Voting Record 2026–2020". The code took the first and last dates in file order as the start and end, and the file is sorted newest first. It now builds a sorted list of years and reads the range earliest first: "Voting Record 2020–2026". A year counts only if at least 5% of its records carry a roll call. Without that rule the range would start at 2019, because of one 2019 record (file 201901809) that shares its file number with a 2020 matter and picks up that matter's votes. 2019 has 1 such record out of 393; 2020 has 346 out of 1,532.

**Note text (`members.html`).** "Data is fairly complete from 2020 onward. Records from before 2020 may be incomplete." is replaced with "Roll call votes are available for matters introduced from June 2020 onward. Earlier matters have no recorded votes on this site." The month and year are computed from the earliest voted record in the range (2020-06-19).

Files: `members.html`. Starting commit: [f90fb0c](https://github.com/BenKelly97/cincinnati-council/commit/f90fb0c2b87dd01d3e9de3b08400759308fa05ec). Commit: [14c324d](https://github.com/BenKelly97/cincinnati-council/commit/14c324d5d88b070fb48d523633d0e26f525cbf80).

## 2026-10-14 — Roll call page: member lists split current/former; Voted-by filter fixed

**Split (`alternative.html`).** The Sponsor checkbox panel and the Voted-by dropdown listed all 21 councilmembers in one alphabetical list. Both are now split into "Current members" (Albi, Cramerding, James, Jeffreys, Johnson, Kearney, Nolan, Owens, Walsh) and "Former members" (the other 12). The Sponsor panel uses group headings; the Voted-by dropdown uses option groups. A new `CURRENT_MEMBERS` list sets the split; every other name in `MEMBER_CANONICAL` is treated as former.

**Voted-by fix (`alternative.html`).** The Voted-by filter returned 0 results for every member. The vote arrays in council_data.json hold surnames ("Cramerding"), and the filter compared them with the full names in the dropdown ("Jeff Cramerding"). It now passes each surname through `canonicalSponsor()` before comparing. Checked against direct counts from the data: Cramerding any vote 3,177, Cramerding No 36, Landsman any vote 1,752, all equal. Mayor Cranley's 23 recorded votes have no entry in `MEMBER_CANONICAL` and stay out of the filter, as before.

Files: `alternative.html`. Starting commit: [0e36aca](https://github.com/BenKelly97/cincinnati-council/commit/0e36aca7252e1ea5fc839978c1166db1653b2f7a). Commit: [a450cfa](https://github.com/BenKelly97/cincinnati-council/commit/a450cfa878f9d52bc55098d41b6eebe5e5b12258).

## 2026-10-14 — Link to the roll call page from the main page

Added a "Roll Call Votes →" link to `alternative.html` in the `index.html` header, next to "Member Records →". Both links now sit in their own `header-nav` element. Before, the Member Records link was inside the header meta text, which is hidden below 600px wide, so phones had no link to either page. Both links now show at every width. Below 600px the "/ Legislative Record" subtitle is hidden to keep the header to two lines.

Files: `index.html`. Starting commit: [e68d6bd](https://github.com/BenKelly97/cincinnati-council/commit/e68d6bd519ae63baf9af5f0ede81a5ec7ccef2e4). Commit: [f8824a8](https://github.com/BenKelly97/cincinnati-council/commit/f8824a8c45a209d0676ee251b2d0c4b506e32bae).

## 2026-10-13 — Removed the stat strip from the main page

Removed the four boxes above the search bar on `index.html` (Total items, Passed, Years covered, Topic categories): the HTML, their CSS, and `populateStats()`. The search bar is now the first element under the header. The header line still shows the item count and year range (now set by `populateHeader()`). No other page has the strip.

Files: `index.html`. Starting commit: [6f50018](https://github.com/BenKelly97/cincinnati-council/commit/6f50018834be9071f6476b1e2ca42e6919830a28). Commit: [759d58a](https://github.com/BenKelly97/cincinnati-council/commit/759d58a46978c1ec8f50ad72fd5c9f80c9340d7a).

## 2026-10-13 — Status filter groups duplicate Legistar statuses

The "All statuses" dropdown on `index.html` listed 37 raw Legistar status values, several of them the same outcome under two labels (committee recommendation "Pass" and council action "Passed", "File" and "Filed", "Adopt" and "Adopted") and seven of them committee names that Legistar stores in the status field on older matters. Added `statusGroup()`, which maps each raw status to one of 18 groups:

- Adopted (Adopt, Adopted); Approved & Filed (Approve & File, Approved & Filed); Confirmed (Confirm, Confirmed); Failed (Failed, Failed of Adoption); Filed (File, Filed, Filed & Advised); Held (Held, Hold, Held one week pursuant to rule of Council); Indefinitely Postponed (Indefinitely Postpone, Indefinitely Postponed); Passed (Pass, Passed); Passed Emergency (Pass Emergency, Passed Emergency); Sunset (Filed/Sunset, Sunset).
- Referred to Committee: "Referred to Committee" and every committee name in the status field (BUDGET AND FINANCE COMMITTEE, MAJOR PROJECTS & SMART GOVERNMENT, and five others; 190 records).
- Unchanged: Agenda Ready, City Manager For Report, Disapproved & Filed, First Reading, Second Reading, Historical, Withdrawn. Any status not in the map passes through as is.

The filter and the card badge use the group. The expanded card shows the raw value, relabeled "Legistar status". The "Passed" stat now counts the Passed, Passed Emergency, Adopted and Confirmed groups, so it includes Pass/Adopt/Confirm records it previously missed: 5,531 before, 5,739 after. Data files are unchanged.

Files: `index.html`. Starting commit: [22968ae](https://github.com/BenKelly97/cincinnati-council/commit/22968ae90fc497d2d277167088105caf1720fd53). Commit: [3c758a6](https://github.com/BenKelly97/cincinnati-council/commit/3c758a6f8d75f0bb53fbb035f3de26e6c03f4701).

## 2026-10-13 — Type filter uses Legistar's types, multi-select sponsor filter, pre-2018 matters blocked

**Type filter (`index.html`).** The "All action types" dropdown listed the AI-assigned action categories (`a` field). It now lists Legistar's own matter types (`mt` field, Legistar's MatterTypeName), labeled "All types": the same 24 entries as the Type dropdown on cincinnatioh.legistar.com, Appointment through Termination. Cards still show the AI action type.

**Sponsor filter (`index.html`).** The dropdown listed every distinct value of the requester field, 494 entries, most of them comma-joined combinations of names. It is now a panel with one checkbox per person, grouped as current councilmembers (9), former councilmembers (12), and offices and committees (Mayor, City Manager, Clerk of Council, Committees and other). It has a name search box, an Any selected / All selected switch, an item count next to each name, and a Clear button. A record matches a councilmember when that name appears in its comma-separated requester list. Checked against an independent count from council_data.json: Cramerding 216, Cramerding or Albi 332, Cramerding and Albi 60, all equal.

**Header range (`index.html`).** The header said "2020–2026" regardless of the data. It now shows the first and last year present.

**Pre-2018 matters (`update_pipeline.py`).** Matter 201201557 (Park Board Rules communication, introduced 2012-11-20) appeared on the site and added 2012 to the year filter. Legistar modified the matter on 2026-10-07, and the pipeline's modified-date pull (last 21 days) adds any matter it does not already have, with no check on introduction date. Added `SITE_START` (2018-01-01, same as the full-sync start): matters introduced earlier are skipped when fetched, and any already in the CSV are removed on the next run. Tested offline on the CSV at e4f470e with that matter injected into the modified pull: it was skipped, the existing row was removed, and the rebuilt JSON covers 2018 to 2026 only (13,096 records).

Files: `index.html`, `update_pipeline.py`. Starting commit: [e4f470e](https://github.com/BenKelly97/cincinnati-council/commit/e4f470ecbd5d2642c9d0187af06d6839c9c46cf6). Commits: [25446bb](https://github.com/BenKelly97/cincinnati-council/commit/25446bba2b3a64e16a4f50f1937087dd4a1ce29a) (`update_pipeline.py`), [f0413ad](https://github.com/BenKelly97/cincinnati-council/commit/f0413ad0f3dff606d03b235645afa3e279c3eaf6) (`index.html`).

Not logged here: the 2026-10-08 to 2026-10-10 pipeline changes (retag_untagged, full-length titles, tag_batch parsing). No CHANGELOG entry was written for them at the time.

## 2026-09-25 — Sponsor filter returned 0 results for members whose Legistar requester field was blank

The Sponsor filter on `alternative.html` reads the `requester` field, which came straight from Legistar's `MatterRequester` with no fallback. That field is frequently null or set to a committee name even when the item's title plainly names the sponsor (e.g. "submitted by Councilmember Albi") — caught because Anna Albi's Sponsor filter returned 0 results despite her having sponsored dozens of items. 3,511 of 12,913 records had a blank requester for this reason.

Added a parser to `update_pipeline.py` that reads the sponsor(s) out of the title's "submitted by ..." clause (matching known councilmember surnames and full names, stopping before the drafter/operative clause) whenever `MatterRequester` is blank or not a recognized individual, and unions it with an already-valid single name so co-sponsors aren't dropped either. Tested against the full dataset with zero false positives — every remaining blank is a legitimate City Manager/Mayor/Clerk of Council filing with no councilmember sponsor. 2,021 rows updated (1,788 newly filled, 233 gained a co-sponsor); Anna Albi now shows 172 sponsored items under the site's own filter logic. Backfilled the existing CSV with the same logic, not just future pipeline runs. `raw_title` is untouched — this only corrects the derived `requester` column.

- Changed: `update_pipeline.py`, `cincinnati_agenda_items_complete.csv`, `council_data.json`
- Commit: [`61f703b`](https://github.com/BenKelly97/cincinnati-council/commit/61f703b)

## 2026-09-24 — Merged duplicate agenda cards, then recovered 470 records a mistake during that fix had dropped

Legistar occasionally issues two different `matter_id` records under the same `file_number` — most commonly for 2018-2020 items that moved from committee to Council. Since `update_pipeline.py` only dedupes incoming fetches on `matter_id`, 135 of those pairs were rendering as duplicate cards on the site (134 real matter_id collisions plus one unrelated group of 5 rows sharing a blank `file_number`). Merged 131 of those groups, keeping the row with a real terminal status (e.g. `Passed`, `Filed`) and discarding the placeholder row (status `Historical` or a bare committee name), while leaving 3 genuinely ambiguous cases (`201901809`, `201801306`, `201801416`) and the blank-`file_number` group untouched for manual review. A full audit of every discarded row's original content was kept locally.

That first push was built from a stale local copy of the data and, without meaning to, overwrote an automated weekly pipeline run that had landed in between, dropping roughly 470 real, already-tagged agenda items (mostly 2025-2026 items with statuses like `Agenda Ready`, `Filed`, `Passed Emergency`) from the site for three days. Rebuilt the file list against the correct baseline, restored exactly those 470 rows, and re-ran the same merge logic on top — same 131 groups merged, same 3 flagged cases and blank-file_number group left alone, no new duplicates introduced.

- Changed: `cincinnati_agenda_items_complete.csv`, `council_data.json`
- Commits: [`873ea1f`](https://github.com/BenKelly97/cincinnati-council/commit/873ea1f) (CSV restore + dedup), [`cd1a5f1`](https://github.com/BenKelly97/cincinnati-council/commit/cd1a5f1) (council_data.json rebuild) — supersedes [`5a046bc`](https://github.com/BenKelly97/cincinnati-council/commit/5a046bc) and [`47ba6ca`](https://github.com/BenKelly97/cincinnati-council/commit/47ba6ca)

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
