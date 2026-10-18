# Changelog

Notable changes to the Cincinnati City Council transparency site, most recent first. Each entry names the files touched and the live GitHub commit.

## 2026-10-18 — Meetings page: vote counts, pass/fail from Legistar, search across all years

**Agenda data (`update_pipeline.py`).** Year files now carry, per agenda line, Legistar's pass/fail flag (`pf`: "Pass", "Fail" or blank), the roll call count from `votes_api.json` (`votes`: yes, no, abstain, absent, excused) when that vote was taken at this full Council meeting, and the site's neighborhood value (`g`) for matters on the site. Legistar's tally field is empty for Cincinnati, so counts come from the site's own vote file; committee meetings show no count. Year files carry `format: 2`; older files were re-read in full once by run #86 ([d4412d8](https://github.com/BenKelly97/cincinnati-council/commit/d4412d8805f3f733660d7ab1a7d32004a73afec5), about 17 minutes). The first version also attached Council roll calls to a committee meeting held the same day (for example Budget, Finance & Governance on 2021-02-01); fixed in 8d8c59b and rebuilt by run #87 ([3e84eb5](https://github.com/BenKelly97/cincinnati-council/commit/3e84eb57aaa0d59f773b068f665fbdc876c7cdba)). Legistar has no pass/fail flags on 2018 and 2019 lines and the site has no roll calls before June 2020.

**Meetings page (`agenda.html`).** Council items show the count, for example "Vote 9–0", with abstain, absent or excused counts when present. A step Legistar marks as failed is labeled "(failed)", for example "Adopt; Referred to CM for a Report (failed)"; lines without a flag fall back to the action wording. Legistar item numbers with typing errors ("f41.", ",6.", "`1.") display as the number. The year menu has "All years (2018–2026)", which searches every year by title, file number or neighborhood; it shows nothing until text is entered. Checked live: 2026-10-14 Council items show "Vote 9–0"; an all-years search for "walnut hills" returns 154 meetings.

Files: `update_pipeline.py`, `agenda.html`. Commits: [2e15369](https://github.com/BenKelly97/cincinnati-council/commit/2e15369addf2062341c7c50e2695b25f08e6a3e0), [8d8c59b](https://github.com/BenKelly97/cincinnati-council/commit/8d8c59b58c3544c973179e150b478c2a2c74851d) (`update_pipeline.py`), [1885926](https://github.com/BenKelly97/cincinnati-council/commit/1885926b613eb1f6328a9ab9b9f2f45b51ce8916) (`agenda.html`).

## 2026-10-18 — Meetings page: one numbered line per matter

**Agenda items (`agenda.html`).** Legistar lists each action on a matter as its own agenda line; a Council ordinance appeared up to three times (suspension of the three readings, emergency clause to remain, passed emergency), and full Council agendas had no item numbers on the vote lines. The page now shows each matter once, at the position of its numbered agenda line, in agenda-number order, with its final action: vetoed, then failed or postponed, then passed emergency or adopted as amended, then passed, adopted, confirmed, filed or approved, then held, referred or recommended. A procedural step that failed (for example "Suspension of three readings failed") is shown after the final action. Items without Legistar numbers are numbered in order. The data files are unchanged and keep every step. Checked on the 2026-10-14 Council meeting: 65 lines became 38 matters numbered 1 to 38. The three matters since 2018 with both a referral motion and passage were checked against Legistar history; each referral failed and the matter passed, which is what the page shows. A few Legistar numbers carry typing errors ("f41.", ",6.") and are shown as Legistar has them.

Files: `agenda.html`. Commits: [0f54495](https://github.com/BenKelly97/cincinnati-council/commit/0f5449517620e393a847aa6f85788e17e493e86d), [faf8b7a](https://github.com/BenKelly97/cincinnati-council/commit/faf8b7a1580dbbbc90d1d7d23f6085ad55751002).

## 2026-10-16 — Cancelled meetings marked on the Meetings page

**Meeting notes (`update_pipeline.py`, `agenda.html`).** Legistar records cancellations in the meeting's comment field ("NOTICE OF CANCELLATION", with variants such as "CANCELLATION" and "Cancelled"); the same field holds notes such as "SPECIAL MEETING", "PUBLIC HEARING" and "Rescheduled Meeting". The pipeline now stores this as `comment` on each meeting; year files written before the change got it from one Legistar events request per year, without re-reading items. The page marks a meeting whose comment contains "cancel" with a red Cancelled label, strikes through its date and body, and shows "Meeting cancelled."; other notes show as a grey label. Past meetings with no items now read "No agenda items in Legistar." instead of "No agenda items posted yet." Run #83 ([1c1cb2f](https://github.com/BenKelly97/cincinnati-council/commit/1c1cb2f1a34db11150c4144cc5127985acf5be46)): 214 cancelled meetings marked (2020 40, 2021 44, 2022 22, 2023 32, 2024 28, 2025 34, 2026 14). Legistar has no comments on 2018 and 2019 meetings, so cancellations in those years are not marked.

Files: `update_pipeline.py`, `agenda.html`. Commits: [6439a30](https://github.com/BenKelly97/cincinnati-council/commit/6439a30522616a2070bbdaee84f2d0ffcba2888c) (`update_pipeline.py`), [f303503](https://github.com/BenKelly97/cincinnati-council/commit/f303503b2ccdbc8360ba5b55f06cd43cc93e23f2) (`agenda.html`).

## 2026-10-16 — Meetings archive since 2018

**Meetings by year (`update_pipeline.py`, `agenda.html`, `.github/workflows/weekly_update.yml`).** Meetings are now kept in one file per year, `agenda_2018.json` through the current year, with `agenda_index.json` listing the years and counts. A missing year file is read from Legistar in full once (one-time backfill); after that each run re-reads only meetings from 45 days back to 30 days ahead, because actions are posted after a meeting. `agenda.json` (the Upcoming/Recent view) is built from the same data. The Meetings page has a By year tab with a year picker and a search box over item titles and file numbers; the body filter applies to it. Items not on the site are labeled "Not on this site". Measured before the change: 2025 has 189 meetings and 3,204 items.

Files: `update_pipeline.py`, `agenda.html`, `.github/workflows/weekly_update.yml`. Commits: [3ec3b1d](https://github.com/BenKelly97/cincinnati-council/commit/3ec3b1db4176bacfcd34fa010206212fd61fc04e) (`update_pipeline.py`), [8b87633](https://github.com/BenKelly97/cincinnati-council/commit/8b876331a46bfa23b6e01f711b6378399358afc0) (`weekly_update.yml`), [cfc1b29](https://github.com/BenKelly97/cincinnati-council/commit/cfc1b2902b5a768d4033b224902012e4a8b86fce) (`agenda.html`). Backfill: run #82 ([50ea46b](https://github.com/BenKelly97/cincinnati-council/commit/50ea46b0ac379ecc40371cceb7f1eb288ef50680)), about 22 minutes: 2018 196 meetings/754 items, 2019 29/140, 2020 208/2,008, 2021 237/4,729, 2022 197/3,227, 2023 202/3,404, 2024 195/3,545, 2025 189/3,204, 2026 160/3,009 (to date plus 30 days ahead). Year files are 41 KB to 1.3 MB. Legistar lists only 29 meetings for 2019, which matches the low 2019 record count on the site (open item).

## 2026-10-16 — Meetings page, About page, neighborhoods from addresses, record cleanup, mayor removed from votes

**Meetings page (`agenda.html`, `update_pipeline.py`, `.github/workflows/weekly_update.yml`).** New page listing Council and committee meetings from Legistar, 14 days back and 30 days ahead, with each meeting's agenda items linked to Legistar. Upcoming and Recent tabs and a filter by body; recent meetings show the action taken on each item. The pipeline writes `agenda.json` on every run (Legistar events and eventitems endpoints); items not tied to a matter (roll call, prayer) are left out. A failure leaves the previous file in place. The workflow commits `agenda.json`.

**About page (`about.html`).** New page: sources, update schedule, which fields are AI-generated, how neighborhoods and votes are set, how values are grouped, known gaps, how to suggest corrections, and that the site is not an official City page. Linked from the main page and the roll call page.

**Neighborhoods from addresses (`update_pipeline.py`, `.github/workflows/weekly_update.yml`).** A spot check of 80 addressed records found 26 of 77 AI neighborhood tags (about 34%) wrong (for example 2709 Erie Avenue tagged Over-the-Rhine; it is in Hyde Park). When a Legistar title contains a street address, the published neighborhood now comes from (1) the title, when it says the matter is "in" a neighborhood ("644 Crown Street in Walnut Hills"), else (2) the Census Bureau batch geocoder plus City Planning's 2020 Statistical Neighborhood Approximations map (CAGIS). Three SNA areas cover two neighborhoods each; an address there gets both names unless the AI tag named one. Unmatched addresses, addresses outside the city, records without an address, and Legislative Agent registrations keep the AI tag. Geocoder results are cached in `geocode_cache.json` (1,343 addresses, 1,221 matched); the boundary file is kept as `neighborhoods_sna2020.geojson`. The CSV keeps the AI tags. Result: `g` changed on 737 records. Business names ("OTR Holdings") and street names ("Linwood Avenue") are not read as neighborhoods.

**Record cleanup (`exclude_matter_ids.json`).** Added 8 matter ids. Deleted from Legistar (API returns 404, no other matter has the file number): 48704 (201900123), 3106 (202100576), 53197 (202602273). Same matter entered twice in Legistar; the copy without history removed: 3859 (kept 39395), 7067 (kept 27628), 7070 (kept 26605), 3883 (kept 45534), 46856 (kept 2226). 53588 (202602811), listed as site-only on 10-14, is now in Legistar and stays.

**Mayor removed from vote lists (`scrape_votes_api.py`).** Legistar lists Mayor John Cranley in 23 roll calls from 2020 and 2021 (22 Yes, 1 No). Mayors (Cranley, Pureval) are now removed from every vote list on each run, for existing and new records; `total_votes` and `vote_values` are adjusted on the records changed.

**Vote lists and update time (`index.html`, `alternative.html`, `members.html`).** Vote lists on main-page cards and on the roll call page show full names. The roll call page and the member page show the data update time in Eastern time. The main page header links to Meetings and About and wraps on phones instead of running off the screen.

**Daily run timing (no change).** Scheduled runs #77 and #78 started about 4 hours after the 11:37 UTC schedule (15:42 and 15:29 UTC). GitHub delays scheduled runs under load; the About page says so.

Files: `agenda.html`, `about.html`, `index.html`, `alternative.html`, `members.html`, `update_pipeline.py`, `scrape_votes_api.py`, `.github/workflows/weekly_update.yml`, `exclude_matter_ids.json`. Starting commit: [ffe9dae](https://github.com/BenKelly97/cincinnati-council/commit/ffe9dae1c31c2aed26ebb22d6594b80859ae3748). Commits: [e7a0f8b](https://github.com/BenKelly97/cincinnati-council/commit/e7a0f8b02f89b59f0a0e7077a96f6515f73bbf01) (`index.html`), [d23e2b5](https://github.com/BenKelly97/cincinnati-council/commit/d23e2b5d1d762ca988b111fb02f08a62eec8814f) (`alternative.html`), [d04e6b9](https://github.com/BenKelly97/cincinnati-council/commit/d04e6b935f80d1e2fce1d985347ee63709bd9d4e) (`members.html`), [3bd8b85](https://github.com/BenKelly97/cincinnati-council/commit/3bd8b8553ea4d96d50a1fd4bf45b25a61f0def85), [7d0d579](https://github.com/BenKelly97/cincinnati-council/commit/7d0d579f3c3a220b1e2a099b66a1e6ff3565cd49), [0641236](https://github.com/BenKelly97/cincinnati-council/commit/0641236ade940dd16efe7335770d8475791f771f) (`about.html`), [c20ffba](https://github.com/BenKelly97/cincinnati-council/commit/c20ffbacabf8bf13206e86ddb752244b12ec4232) (`agenda.html`), [68e3ef1](https://github.com/BenKelly97/cincinnati-council/commit/68e3ef11e31c8592357d36f8dc02fce293f6f723), [c5ecebb](https://github.com/BenKelly97/cincinnati-council/commit/c5ecebb243a96d63909f8e0189e4e7ef55761d9b), [5cadf65](https://github.com/BenKelly97/cincinnati-council/commit/5cadf65ca5bbc652bd01a74d5e9a2533f23551e4) (`update_pipeline.py`), [88df594](https://github.com/BenKelly97/cincinnati-council/commit/88df594854ce8e58fc998d667a6fc9f6e72529a0) (`scrape_votes_api.py`), [5b75504](https://github.com/BenKelly97/cincinnati-council/commit/5b75504d5199f2875b538bfe01eeb2a60483a524) (`weekly_update.yml`), [4234636](https://github.com/BenKelly97/cincinnati-council/commit/4234636b8bafdd636d1982edc8fffb0b22190880) (`exclude_matter_ids.json`). Data rebuilt by runs #79 ([95d2ebb](https://github.com/BenKelly97/cincinnati-council/commit/95d2ebb2edce98dfbedff1fa67d8fe771a8c8f59)), #80 ([78ac735](https://github.com/BenKelly97/cincinnati-council/commit/78ac73538a63cd8deb3fb782061321f4e3e48347)) and #81 ([2eeda2d](https://github.com/BenKelly97/cincinnati-council/commit/2eeda2d4530af1662a3dec9911a2d7850deb5e7b)): 13,093 records (8 removed, 4 new matters), `g` changed on 737 records, Cranley removed from 23 vote records.

Tarbell: field names unchanged. council_data.json lost 8 records and 737 `g` values changed; vote_yes/vote_no lost "Cranley" on 23 records. votes_api.json lost the Cranley entries on the same 23 records. New files agenda.json, geocode_cache.json, neighborhoods_sna2020.geojson.

## 2026-10-14 — Data cleanup, daily updates, filter and display fixes

**Votes on shared file numbers (`update_pipeline.py`, `scrape_votes_api.py`).** Votes are keyed by file number, so when two records share a file number both received the same votes. File 201901809 is on matter 2226 (2020 motion) and matter 46856 (2019 ordinance, status "Historical"); Legistar's history shows the 2020-09-15 vote belongs to 2226, but 46856 also displayed it. `build_json()` now attaches a vote to one record per file number: the record with the vote's Legistar matter id when present, otherwise the record introduced on or before the meeting date whose status is not "Historical". `scrape_votes_api.py` now stores `matter_id` (Legistar EventItemMatterId) on each new vote record; older records match by the date rule. Records sharing a file number also no longer share the scraped Legistar link; each uses its own matter link. Offline rebuild of the e68d6bd data: 46856 lost the 2020 vote; no other record's votes changed.

**Malformed file numbers (no change to values).** Nine records have a blank or non-standard file number ("", "20", "0023-2021", "20230002", "20901542", "2014900102"). Checked each against the Legistar API by matter id: Legistar stores these exact values, so the site keeps them. Vote matching and links no longer depend on them.

**Neighborhoods (`update_pipeline.py`).** The published geography values now follow City Planning's 2020 Statistical Neighborhood Approximations list (51 neighborhoods) plus "citywide". "Mount X" becomes "Mt. X", "Fairview" becomes "CUF", "Roll Hill" becomes "Villages at Roll Hill", "Winton Place" becomes "Spring Grove Village". Values not on the list are dropped from the published record: other municipalities (Amberley, Delhi, Montgomery, Norwood, Silverton), umbrella areas (Price Hill, Uptown, Western Hills), and Losantiville, Mohawk and "Werkgeek" (one record each). The filter goes from 63 values to 50. 217 records changed; 11 now have no neighborhood. The CSV keeps the original tags.

**Topics (`update_pipeline.py`).** Six rare tags are merged: energy and "energy and sustainability" into "environment and sustainability"; "public health" into health; "finance policy" into budget; history into "arts and culture"; sports into "parks and recreation". 28 topics become 22; 8 records changed. The CSV keeps the original tags.

**Sponsor filter committees (`index.html`).** The sponsor filter split the requester field on commas, which broke committee names such as "Budget, Finance & Governance Committee", and lumped every non-member into "Committees and other". The panel now has an Offices group (Mayor, City Manager, Clerk of Council) and a "Committees and other bodies" group listing each committee by name (19 entries). Requesters such as "City Manager, Wendell Young" now count for both.

**Daily runs (`.github/workflows/weekly_update.yml`).** Schedule changed from Monday, Wednesday and Friday at 21:00 UTC to daily at 11:37 UTC (7:37 AM EDT, 6:37 AM EST). The old 21:00 UTC runs started as late as 02:16 UTC because GitHub delays scheduled runs at busy times; the new minute avoids the top of the hour. Commit message changed from "Weekly data update" to "Data update ... UTC".

**Runner and actions (`.github/workflows/weekly_update.yml`).** `runs-on` pinned to `ubuntu-24.04` (ubuntu-latest moves to Ubuntu 26 from 2026-10-19). `actions/checkout` v4 to v5 and `actions/setup-python` v5 to v6, which run on Node 24.

**Update time (`index.html`, `update_pipeline.py`).** The header showed the UTC time with no label ("Updated 2026-10-13 20:17"). The page now shows Eastern time ("Updated Oct 14, 2026, 3:43 PM ET"). The pipeline writes `last_updated` in UTC explicitly; the value format is unchanged.

**Main page (`index.html`).** Search now covers file numbers. The card badge shows Legistar's matter type, matching the Type filter, instead of the AI action type (still shown in the expanded card). The count reads "1 result" instead of "1 results".

**Member page (`members.html`).** Member cards show full names ("Anna Albi") instead of surnames.

Files: `update_pipeline.py`, `scrape_votes_api.py`, `.github/workflows/weekly_update.yml`, `index.html`, `members.html`. Starting commit: [400fe3d](https://github.com/BenKelly97/cincinnati-council/commit/400fe3dcc5beea9b4fa9cb798731e75f21b1c231). Commits: [c3275ef](https://github.com/BenKelly97/cincinnati-council/commit/c3275efc4ca1c4ecb6b06d091222d3beffc9fc7a) (`update_pipeline.py`), [723c021](https://github.com/BenKelly97/cincinnati-council/commit/723c021ce8a0a5f269307d682d436259630dbace) (`scrape_votes_api.py`), [1f2e6f3](https://github.com/BenKelly97/cincinnati-council/commit/1f2e6f3327e7563778746879e18b6d388c16b0ed) (`weekly_update.yml`), [b472f6b](https://github.com/BenKelly97/cincinnati-council/commit/b472f6bf4d473854600fb4601aa3b207afe3b2bf) (`index.html`), [5c67b83](https://github.com/BenKelly97/cincinnati-council/commit/5c67b83c3483c38b07e931693807066dcc458981) (`members.html`). Data rebuilt by run #76 ([24f5945](https://github.com/BenKelly97/cincinnati-council/commit/24f5945)): 13,096 records, 50 neighborhood values, 22 topics; matter 46856 no longer carries the 2020 vote; 87 vote records re-read in the 45-day window now carry `matter_id`.

Tarbell: field names in council_data.json and votes_api.json are unchanged. Values of `g` and `tp` changed as above, one record lost its votes, and votes_api.json records gain a `matter_id` field.

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
