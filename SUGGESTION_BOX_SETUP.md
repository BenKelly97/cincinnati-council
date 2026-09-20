# Suggestion box — how it's wired

This describes the current, live setup (not a checklist to redo). Useful if the Google Form or Sheet ever need to be recreated, or if the question set changes again.

## The Google Form

Live at the "Council Site — Title Suggestion" form. Visitors never see it — `suggest.js` posts to it directly in the background (`formResponse` endpoint, `mode: 'no-cors'`).

Questions, in the order they were created (this is *not* the order the Sheet's columns end up in — see below):

1. **File Number** — Short answer
2. **Current Title** — Paragraph
3. **Legistar URL** — Short answer
4. **Type** — Short answer (visitors never see this — it's filled in by the widget's dropdown)
5. **Suggested Title** — Paragraph (holds the suggested replacement text for *either* a title or a description change)
6. **Comment** — Paragraph
7. **Source Page** — Short answer
8. **Current Description** — Paragraph (added 2026-09-20, for the title/description feature)
9. **Field** — Short answer (added 2026-09-20; holds `"Title"` or `"Description"` — which one the visitor chose to suggest a change to)

"Collect email addresses" and "Limit to 1 response" are both off — unauthenticated public widget, not a login form.

**Important, learned the hard way:** a new question added to an existing Form is appended as a new column at the **end** of the linked Sheet, regardless of where it's positioned in the Form's own question order. Always verify the actual column order by opening the Sheet (or its published CSV) directly — don't assume it from the Form layout. The current, verified order is:

`Timestamp, File Number, Current Title, Legistar URL, Type, Suggested Title, Comment, Source Page, Current Description, Field`

— which is exactly what `COLS` in `review.html` expects. If you add another question later, it'll land as an 11th column at the end; add it to `COLS` (and read it in `review.html`) accordingly, don't try to reorder.

## Entry IDs (`suggest.js`)

Found via the live Form's `window.FB_PUBLIC_LOAD_DATA_` (not by viewing page source / hand-parsing — that global has the entry ID keyed to each question cleanly). Current mapping, in `SUGGEST_ENTRY`:

- fileNumber: `entry.2126325988`
- currentTitle: `entry.699636265`
- legistarUrl: `entry.918148672`
- suggestionType: `entry.1423495741`
- suggestedTitle: `entry.1576642602`
- comment: `entry.82458550`
- sourcePage: `entry.1327166660`
- currentDescription: `entry.1514592241`
- field: `entry.1602425915`

`SUGGEST_FORM_ACTION` is the Form's `viewform` URL with `viewform` swapped for `formResponse`.

## The response Sheet (for `review.html`)

The Form's linked response spreadsheet is published as CSV: Sheet → **File → Share → Publish to web** → pick the specific tab (not "Entire document") → format **Comma-separated values (.csv)**. That published URL is `SHEET_CSV_URL` at the top of `review.html`. Reads don't need a token (the repo and the published CSV are both public); this is a *read-only* published link — editing it doesn't affect the live Sheet.

## Apply / Dismiss (writes)

`review.html` writes directly to the GitHub repo via the Contents API, gated behind a password prompt (SHA-256 hash comparison, client-side only — see `CHANGELOG.md` for when that was added) and a personal-access-token the admin pastes in once (stored in that browser's `localStorage`, sent only to GitHub's API).

- **Apply title** → writes into `title_overrides.json`.
- **Apply description** → writes into `summary_overrides.json`.
- Either way, the row is also logged in `suggestion_status.json` so it drops off the pending list.
- **Dismiss** just logs the row as handled, no data change.

`update_pipeline.py` reads both override files on its next scheduled run, bakes any pending entries into the CSV (`clean_title` for titles, `summary` for descriptions), and clears the ones it applied. The weekly GitHub Action (`weekly_update.yml`) commits both files if they changed.

## Search

Both `title_overrides.json` and `summary_overrides.json` are also fetched and merged client-side by `index.html`, `alternative.html`, and `members.html` at page load — so an applied fix shows up (and is searchable, since search matches against title + summary) immediately, not just after the next scheduled pipeline run.

## Deploying a change to any of this

Commit the changed file(s) and push — same as always. `review.html` isn't linked from the public nav on purpose; bookmark `benkelly97.github.io/cincinnati-council/review.html` directly. It's unauthenticated beyond the password gate (client-side only, GitHub Pages can't do real server-side auth) — acceptable for now, but worth revisiting (e.g. Cloudflare Access in front of just that page) if the bar needs to be higher.
