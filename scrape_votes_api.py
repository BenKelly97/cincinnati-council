"""
Cincinnati City Council — Vote Scraper (API-based)
====================================================
Pulls accurate vote data directly from the Legistar API.
Tracks Yes, No, Abstain, and Absent separately.
Only captures the PRIMARY passage vote per item, ignoring
procedural votes (referrals, emergency clauses, suspensions).
No AI, no PDFs, no cost.

REQUIREMENTS: pip install requests
OUTPUT: votes_api.json

USAGE:
    python3 scrape_votes_api.py
"""

import json
import time
import requests

OUTPUT_FILE = "votes_api.json"

# Action names that represent the primary passage vote
PRIMARY_ACTIONS = {
    'passed', 'passed emergency', 'failed', 'adopted', 'confirmed',
    'approved', 'denied', 'tabled', 'indefinitely postponed',
    'pass', 'fail', 'pass emergency', 'adopted emergency'
}

# Action names to skip — procedural votes
SKIP_ACTIONS = {
    'motion to refer', 'refer', 'referral', 'emergency clause',
    'suspension of the three readings', 'suspension of readings',
    'motion to reconsider', 'reconsider', 'lay on the table',
    'motion to table', 'second reading', 'first reading', 'third reading',
    'recommend passage', 'recommend', 'amended', 'amendment'
}

def is_primary_action(action_name):
    """Return True if this action represents the main passage vote."""
    if not action_name:
        return False
    a = action_name.lower().strip()
    # If it matches a skip pattern, definitely skip
    for skip in SKIP_ACTIONS:
        if skip in a:
            return False
    # If it matches a primary pattern, include it
    for primary in PRIMARY_ACTIONS:
        if primary in a:
            return True
    # Default: include if it has votes (better to include than miss)
    return True

def fetch_all_events(start_date="2020-01-01"):
    """Fetch every Council AND committee meeting event.

    This used to filter to EventBodyName eq 'Cincinnati City Council' —
    full-Council floor sessions only. That silently dropped every item
    whose only disposition was a committee-level vote (e.g. "Failed of
    Adoption" or "Indefinitely Postponed" straight out of committee,
    never reaching the floor): such an item never has a 'Cincinnati City
    Council' event, so its vote was never fetched at all, and it never
    showed up under any member's vote history even though Legistar has
    the roll call on record.

    Dropping the body filter pulls in every committee meeting too.
    Non-legislative or vote-less bodies just come back with no votes per
    item (fetch_votes returns []), so this is safe — it costs more API
    calls, not correctness.
    """
    events = []
    skip = 0
    while True:
        url = (
            "https://webapi.legistar.com/v1/cincinnatioh/events"
            f"?$top=1000&$skip={skip}"
            f"&$filter=EventDate+ge+datetime'{start_date}T00:00:00'"
            "&$orderby=EventDate+asc"
        )
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            break
        events.extend(data)
        print(f"  Fetched {len(events)} events...")
        if len(data) < 1000:
            break
        skip += 1000
        time.sleep(0.5)
    return events

def fetch_event_items(event_id):
    url = f"https://webapi.legistar.com/v1/cincinnatioh/events/{event_id}/eventitems"
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code != 200:
                return []
            return resp.json()
        except Exception:
            if attempt < 2:
                time.sleep(5)
            else:
                return []
    return []

def fetch_votes(event_item_id):
    url = f"https://webapi.legistar.com/v1/cincinnatioh/eventitems/{event_item_id}/votes"
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code != 200:
                return []
            return resp.json()
        except Exception:
            if attempt < 2:
                time.sleep(5)
            else:
                return []
    return []

def main():
    # Load existing votes if present — incremental mode
    all_votes = {}
    processed_events = set()
    start_date = "2020-01-01"

    import os
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE) as f:
            all_votes = json.load(f)
        processed_events = set(all_votes.pop("_processed_events", []))
        vote_records = {k: v for k, v in all_votes.items() if not k.startswith("_")}
        if vote_records:
            latest = max(v.get("meeting_date", "") for v in vote_records.values())
            start_date = latest  # re-fetch from latest date to catch any same-day additions
            print(f"Incremental mode — {len(vote_records)} existing records, fetching from {start_date}\n")
        else:
            print("Existing file found but empty — fetching all events\n")
    else:
        print("No existing file — fetching all events from 2020\n")

    print("Fetching Council and committee events...")
    events = fetch_all_events(start_date)
    print(f"Total events to process: {len(events)}")

    new_votes = 0
    skipped_procedural = 0

    for i, event in enumerate(events):
        eid = str(event.get("EventId"))
        date = (event.get("EventDate") or "")[:10]
        body_name = event.get("EventBodyName", "")

        if eid in processed_events:
            print(f"  [{i+1}/{len(events)}] {date} — skipping")
            continue

        print(f"  [{i+1}/{len(events)}] {date} ({body_name}) — fetching items...", end="", flush=True)
        items = fetch_event_items(eid)

        # Group items by file number — for each file, find the primary action
        # items can have multiple entries per file (one per action)
        file_items = {}
        for item in items:
            fn = item.get("EventItemMatterFile")
            if not fn:
                continue
            if fn not in file_items:
                file_items[fn] = []
            file_items[fn].append(item)

        vote_count = 0
        for fn, file_item_list in file_items.items():
            # Find the best item to use for this file number
            # Priority: primary action with votes > any item with votes
            best_item = None
            best_votes = []

            for item in file_item_list:
                action_name = item.get("EventItemActionName", "") or ""
                iid = item.get("EventItemId")

                # Skip procedural actions
                a = action_name.lower().strip()
                skip_this = any(skip in a for skip in SKIP_ACTIONS)
                if skip_this:
                    skipped_procedural += 1
                    continue

                votes = fetch_votes(iid)
                if not votes:
                    time.sleep(0.05)
                    continue

                # Is this a primary action?
                if is_primary_action(action_name):
                    best_item = item
                    best_votes = votes
                    break  # Take the first primary action with votes
                elif not best_item:
                    # Fallback: use first item with votes
                    best_item = item
                    best_votes = votes

                time.sleep(0.05)

            if not best_votes:
                continue

            # Parse votes
            yes_full     = [v["VotePersonName"] for v in best_votes if v.get("VoteValueName") == "Yes"]
            no_full      = [v["VotePersonName"] for v in best_votes if v.get("VoteValueName") == "No"]
            abstain_full = [v["VotePersonName"] for v in best_votes if v.get("VoteValueName") == "Abstain"]
            absent_full  = [v["VotePersonName"] for v in best_votes if v.get("VoteValueName") in ("Absent", "Remote")]
            excused_full = [v["VotePersonName"] for v in best_votes if v.get("VoteValueName") in ("Excused", "Recused")]

            yes_votes     = [n.split()[-1] for n in yes_full]
            no_votes      = [n.split()[-1] for n in no_full]
            abstain_votes = [n.split()[-1] for n in abstain_full]
            absent_votes  = [n.split()[-1] for n in absent_full]
            excused_votes = [n.split()[-1] for n in excused_full]

            action_used = best_item.get("EventItemActionName", "") if best_item else ""
            vote_values = list(set(v.get("VoteValueName", "") for v in best_votes))

            # Later events (chronologically) overwrite earlier ones for the
            # same file number, so if a matter gets a committee vote first
            # and then a full-Council floor vote later, the floor vote wins.
            # If it never reaches the floor, the committee vote — now
            # captured — is what stands, instead of nothing at all.
            all_votes[fn] = {
                "file_number":   fn,
                "meeting_date":  date,
                "meeting_body":  body_name,
                "action_used":   action_used,
                "yes_votes":     yes_votes,
                "no_votes":      no_votes,
                "abstain_votes": abstain_votes,
                "absent_votes":  absent_votes,
                "excused_votes": excused_votes,
                "yes_full":      yes_full,
                "no_full":       no_full,
                "abstain_full":  abstain_full,
                "absent_full":   absent_full,
                "excused_full":  excused_full,
                "vote_values":   vote_values,
                "total_votes":   len(best_votes)
            }
            vote_count += 1
            new_votes += 1
            time.sleep(0.1)

        print(f" {vote_count} voted items")
        processed_events.add(eid)

        if i % 10 == 0:
            all_votes["_processed_events"] = list(processed_events)
            with open(OUTPUT_FILE, "w") as f:
                json.dump(all_votes, f, indent=2)

    all_votes["_processed_events"] = list(processed_events)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(all_votes, f, indent=2)

    vote_records = {k: v for k, v in all_votes.items() if not k.startswith("_")}
    print(f"\nDone. {new_votes} vote records.")
    print(f"Procedural votes skipped: {skipped_procedural}")
    print(f"Output: {OUTPUT_FILE}")

    # Show sample of action names used
    from collections import Counter
    actions = Counter(r.get("action_used","") for r in vote_records.values())
    print("\nTop action names used:")
    for a, c in actions.most_common(10):
        print(f"  {c:4d}  {a}")

if __name__ == "__main__":
    main()
