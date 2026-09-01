"""
Cincinnati Legistar — Weekly Update Pipeline
=============================================
Pulls new agenda items from the past two weeks, tags them with Claude,
deduplicates against the existing CSV, and appends new records only.
Also runs scrape_links to get Legistar URLs for new items.
Then rebuilds council_data.json ready to upload to GitHub.

REQUIREMENTS:
    pip install requests anthropic beautifulsoup4

FILES NEEDED IN SAME FOLDER:
    cincinnati_agenda_items_complete.csv  (your existing archive)
    council_data.json                     (your existing site data)

OUTPUT:
    cincinnati_agenda_items_complete.csv  (updated with new records appended)
    council_data.json                     (rebuilt, ready for GitHub upload)

USAGE:
    python3 update_pipeline.py
"""

import csv, re, time, json, requests
import xml.etree.ElementTree as ET
import anthropic
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

# ─── NETWORK ─────────────────────────────────────────────────────────────────

def legistar_get(url, headers=None, timeout=30, max_retries=4):
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError) as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"  [retry {attempt+1}/{max_retries-1}] {type(e).__name__} — waiting {wait}s...")
                time.sleep(wait)
            else:
                raise
        except requests.exceptions.HTTPError:
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"  [retry {attempt+1}/{max_retries-1}] HTTP {resp.status_code} — waiting {wait}s...")
                time.sleep(wait)
            else:
                raise

# ─── CONFIG ──────────────────────────────────────────────────────────────────

import os
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "YOUR_API_KEY_HERE")

EXISTING_CSV  = "cincinnati_agenda_items_complete.csv"
OUTPUT_CSV    = "cincinnati_agenda_items_complete.csv"
OUTPUT_JSON   = "council_data.json"
VOTES_FILE    = "votes_api.json"

# Cutoff: pull items introduced in the last N days
LOOKBACK_DAYS = 14

# Cutoff for scraping meeting agenda pages to recover Legistar detail links.
# Every run only looks at meetings since this many days ago; the link_map is
# loaded from the existing JSON and accumulated across runs, so this does NOT
# need to cover full history on every run — see FULL_LINK_BACKFILL below for
# a one-time pass that seeds every meeting since the site's earliest data.
LINKS_LOOKBACK_DAYS = 14

# Set env var FULL_LINK_BACKFILL=1 (or pass --full-link-backfill) to scrape
# every Council/committee meeting since LINK_BACKFILL_START instead of just
# the last LINKS_LOOKBACK_DAYS. Only items that actually appeared on a
# meeting agenda can get a link this way — Registrations, Statements,
# Reports, Communications, and Presentations are typically filed with the
# Clerk directly and never appear on a meeting agenda, so Legistar's website
# never exposes a direct detail link for them; they will keep showing
# without the "View on Legistar" button even after a full backfill.
LINK_BACKFILL_START = "2018-01-01"

PAGE_SIZE          = 1000
DELAY_BETWEEN_ITEMS = 0.3
DELAY_BETWEEN_PAGES = 1.0
DELAY_HTML         = 0.4

# ─── TAXONOMY ────────────────────────────────────────────────────────────────

TOPIC_TAGS = [
    "zoning", "budget", "infrastructure", "public safety", "housing",
    "parks and recreation", "economic development", "human services",
    "environment and sustainability", "transportation", "education",
    "health", "arts and culture", "technology", "labor and workforce",
    "elections and governance", "utilities", "tax policy", "legal and litigation"
]

ACTION_TYPES = [
    "ordinance", "emergency ordinance", "resolution", "motion",
    "presentation", "report", "appointment", "referral", "other"
]

GEOGRAPHY_TAGS = [
    "citywide", "Avondale", "Bond Hill", "California", "Camp Washington",
    "Carthage", "Clifton", "College Hill", "Columbia Tusculum", "Corryville",
    "East End", "East Price Hill", "East Walnut Hills", "Evanston", "Fairview",
    "Hartwell", "Hyde Park", "Kennedy Heights", "Linwood", "Lower Price Hill",
    "Madisonville", "Millvale", "Mount Adams", "Mount Auburn", "Mount Lookout",
    "Mount Washington", "North Avondale", "North Fairmount", "Northside",
    "Over-the-Rhine", "Paddock Hills", "Pendleton", "Pleasant Ridge",
    "Queensgate", "Riverside", "Roselawn", "Sayler Park", "Sedamsville",
    "South Cumminsville", "South Fairmount", "Westwood", "West Price Hill",
    "Winton Hills", "Winton Place", "Downtown"
]

REGISTRATION_TYPES = {'Registration', 'Registration-Update', 'Termination', 'Successor'}
STATEMENT_TYPES    = {'Statement'}

def rule_based_summary(raw_title):
    """Generate a short, human-readable summary for Statement/Registration
    items without calling the AI, based on known Legistar title patterns."""
    t = (raw_title or "").strip()

    m = re.search(r'Financial Disclosure Statement\s+(?:for\s+)?(.+?)\s*$', t)
    if m:
        body = m.group(1).strip().rstrip('.')
        body = re.sub(r'\s*\(ETHICS\)\s*$', '', body, flags=re.IGNORECASE).strip().rstrip('.')
        pm = re.match(r'^(.+?)\s*\(([^()]+)\)\s*$', body)
        if pm:
            return f"Financial disclosure statement filed for {pm.group(1).strip().rstrip('/').strip()} ({pm.group(2).strip()})"
        if ',' in body:
            name, title = body.split(',', 1)
            return f"Financial disclosure statement filed for {name.strip()} ({title.strip()})"
        if '/' in body:
            parts = [p.strip() for p in body.split('/')]
            name = parts[0]
            title = '/'.join(parts[1:])
            return f"Financial disclosure statement filed for {name} ({title})"
        return f"Financial disclosure statement filed for {body}"

    m = re.search(r'Legislative Agent ((?:\([A-Za-z.\-]+\)\s*)?[A-Za-z.\- ]+?),\s*(.+)$', t)
    if m:
        name = re.sub(r'\s+', ' ', m.group(1)).strip()
        rest = m.group(2).strip().rstrip('.')
        org_m = re.search(r'\(([^()]+)\)\s*$', rest)
        if org_m:
            org = org_m.group(1).strip()
            return f"Lobbyist registration for {name} representing {org}"
        role = rest.split(',')[0].strip()
        return f"Lobbyist registration for {name} ({role})"

    if t.upper().startswith('SUCCESSOR'):
        return "Successor designation certificates received by Clerk of Council"

    if len(t) > 160:
        cut = t[:160].rsplit(' ', 1)[0]
        return cut + '…'
    return t

def rule_based_title(raw_title, matter_type):
    """Generate a short, complete-sentence title for Statement/Registration
    items, avoiding mid-word truncation of the raw Legistar boilerplate."""
    t = (raw_title or "").strip()

    m = re.search(r'Financial Disclosure Statement\s+(?:for\s+)?(.+?)\s*$', t)
    if m:
        body = m.group(1).strip().rstrip('.')
        body = re.sub(r'\s*\(ETHICS\)\s*$', '', body, flags=re.IGNORECASE).strip().rstrip('.')
        name = re.split(r'[,/(]', body)[0].strip()
        if name:
            return f"Financial Disclosure Statement — {name}"

    m = re.search(r'filing a copy of the ([A-Z][a-zA-Z.\' ]+?)/', t)
    if m:
        name = m.group(1).strip()
        return f"Financial Disclosure Statement — {name}"

    m = re.search(r'(?:Legislative Agent|from)\s+(?:Legislative\s+)?((?:\([A-Za-z.\-]+\)\s*)?[A-Za-z.\- ]+?),', t)
    if m and 'REGISTRATION' in t.upper():
        name = re.sub(r'\s+', ' ', m.group(1)).strip()
        if name and name.lower() not in ('the clerk of council', 'clerk of council'):
            return f"Lobbyist Registration — {name}"

    if t.upper().startswith('SUCCESSOR'):
        return "Successor Designation Certificates Filed"

    if matter_type == 'Termination':
        return "Lobbyist Registration Terminated"

    m = re.search(r'^STATEMENT,\s*\(([^)]+)\)', t, re.IGNORECASE)
    if m:
        label = m.group(1).strip().title()
        return f"Statement — {label}"

    m = re.search(r'^STATEMENT,\s*(?:dated [\d/]+,\s*)?submitted by ([^,]+),', t, re.IGNORECASE)
    if m:
        submitter = m.group(1).strip()
        return f"Statement — {submitter}"

    if matter_type in ('Registration', 'Registration-Update'):
        return "Lobbyist Registration"

    return "Council Statement"

COUNCILMEMBERS = {
    'Jan-Michele Kearney', 'Meeka Owens', 'Mark Jeffreys', 'Greg Landsman',
    'Reggie Harris', 'Scotty Johnson', 'Chris Seelbach', 'Jeff Cramerding',
    'David Mann', 'Liz Keating', 'Christopher Smitherman', 'Betsy Sundermann',
    'Steve Goodin', 'P.G. Sittenfeld', 'Seth Walsh', 'Victoria Parks',
    'Wendell Young', 'Evan Nolan', 'Jeff Pastor', 'Ryan James',
    'Anna Alarcon', 'Liz Keating', 'Tom Kaszubski'
}

MAYOR_CUTOFF = '2022-01-06'

FIELDNAMES = [
    "matter_id", "file_number", "intro_date", "agenda_date", "passed_date",
    "body", "matter_type", "status", "requester", "enactment_number",
    "action_type_ai", "clean_title", "summary", "topic_tags", "geography",
    "raw_title", "notes", "tag_status"
]

# ─── LEGISTAR API FETCH ───────────────────────────────────────────────────────

NS = "http://schemas.datacontract.org/2004/07/LegistarWebAPI.Models.v1"

def ns(tag):
    return f"{{{NS}}}{tag}"

def get_text(element, tag):
    child = element.find(ns(tag))
    if child is None or child.text is None:
        return ""
    return child.text.strip()

def strip_rtf(text):
    if not text or not text.startswith("{\\rtf"):
        return text
    text = re.sub(r'\{[^{}]*\}', '', text)
    text = re.sub(r'\\[a-z]+[-]?\d*\s?', '', text)
    text = re.sub(r'[{}]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def fetch_page(cutoff_date, skip=0):
    date_str = cutoff_date.strftime('%Y-%m-%dT00:00:00')
    url = f"https://webapi.legistar.com/v1/cincinnatioh/matters?$top={PAGE_SIZE}&$skip={skip}&$filter=MatterIntroDate+ge+datetime'{date_str}'"
    headers = {"Accept": "application/xml"}
    resp = legistar_get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.text

def parse_page(xml_text):
    root = ET.fromstring(xml_text)
    matters = []
    for m in root.findall(ns("GranicusMatter")):
        title = get_text(m, "MatterTitle")
        notes = strip_rtf(get_text(m, "MatterNotes"))
        matter = {
            "matter_id":        get_text(m, "MatterId"),
            "file_number":      get_text(m, "MatterFile"),
            "matter_type":      get_text(m, "MatterTypeName"),
            "body":             get_text(m, "MatterBodyName"),
            "status":           get_text(m, "MatterStatusName"),
            "requester":        get_text(m, "MatterRequester"),
            "intro_date":       get_text(m, "MatterIntroDate")[:10],
            "agenda_date":      get_text(m, "MatterAgendaDate")[:10],
            "passed_date":      get_text(m, "MatterPassedDate")[:10],
            "enactment_number": get_text(m, "MatterEnactmentNumber"),
            "raw_title":        title,
            "notes":            notes[:500] if notes else "",
        }
        matters.append(matter)
    return matters

# ─── AI TAGGING ───────────────────────────────────────────────────────────────

# Skip types that don't need AI tagging
SKIP_TAG_TYPES = {'Registration', 'Registration-Update', 'Termination', 'Successor',
                  'Statement', 'Oath of Office', 'FYI Memo', 'Memo', 'Notice',
                  'Receipt', 'Request', 'Resignation'}

# Compact tag lists for prompt (saves tokens)
TOPIC_STR = ",".join(TOPIC_TAGS)
ACTION_STR = ",".join(ACTION_TYPES)
GEO_STR   = ",".join(GEOGRAPHY_TAGS)

BATCH_SIZE = 15  # items per API call

# Haiku pricing (per million tokens)
HAIKU_INPUT_COST  = 0.80   # $0.80 per million input tokens
HAIKU_OUTPUT_COST = 4.00   # $4.00 per million output tokens

def tag_batch(client, items):
    """Tag multiple items in a single API call. Returns (results, input_tokens, output_tokens)."""
    lines = []
    for i, item in enumerate(items):
        lines.append(f"{i}|{item['raw_title']}|{item['matter_type']}|{item['body']}|{item['requester']}")
    batch_text = "\n".join(lines)

    prompt = f"""Tag Cincinnati City Council agenda items. Return a JSON array, one object per line.
Each object: {{"i":index,"t":"plain title ≤12 words","tp":["topic1"],"a":"action_type","g":["geo"],"s":"summary ≤20 words"}}
Topics: {TOPIC_STR}
Actions: {ACTION_STR}
Geo: {GEO_STR} (citywide if broad, [] if unclear)
Items (index|title|type|body|requester):
{batch_text}
JSON array only, no markdown."""

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"): raw = raw[4:]
            raw = raw.strip()
        usage = resp.usage
        return json.loads(raw), usage.input_tokens, usage.output_tokens
    except Exception as e:
        return [{"i": i, "error": str(e)} for i in range(len(items))], 0, 0

def tag_item(client, item):
    """Tag a single item (used for fallback)."""
    mt = item['matter_type']
    if mt in REGISTRATION_TYPES:
        item.update({"clean_title": rule_based_title(item['raw_title'], mt), "topic_tags": "registrations and terminations",
                     "action_type_ai": "registration", "geography": "", "summary": rule_based_summary(item['raw_title']), "tag_status": "success"})
        return item
    if mt in STATEMENT_TYPES:
        item.update({"clean_title": rule_based_title(item['raw_title'], mt), "topic_tags": "financial statements",
                     "action_type_ai": "statement", "geography": "", "summary": rule_based_summary(item['raw_title']), "tag_status": "success"})
        return item

    try:
        results, _, __ = tag_batch(client, [item])
        p = results[0] if results and isinstance(results, list) and len(results) > 0 else None
        if p and isinstance(p, dict) and "error" not in p:
            topic_tags = "|".join(p.get("tp", [])).replace("energy and sustainability", "environment and sustainability")
            item.update({
                "clean_title":    p.get("t", ""),
                "topic_tags":     topic_tags,
                "action_type_ai": p.get("a", ""),
                "geography":      "|".join(p.get("g", [])),
                "summary":        p.get("s", ""),
                "tag_status":     "success"
            })
        else:
            err = p.get("error", "unknown") if p and isinstance(p, dict) else "no result"
            item.update({"clean_title": "", "topic_tags": "", "action_type_ai": "",
                         "geography": "", "summary": "", "tag_status": f"error: {err}"})
    except Exception as e:
        item.update({"clean_title": "", "topic_tags": "", "action_type_ai": "",
                     "geography": "", "summary": "", "tag_status": f"error: {e}"})
    return item

# ─── SPONSOR NORMALIZATION ────────────────────────────────────────────────────

def normalize_requester(rq, date_str):
    if rq in ('Mayor', 'Mayor John Cranley', 'John Cranley', 'Mayor Aftab Pureval'):
        if date_str and date_str >= MAYOR_CUTOFF:
            return 'Mayor Aftab Pureval'
        else:
            return 'Mayor John Cranley'
    if rq in COUNCILMEMBERS or rq == 'City Manager':
        return rq
    return rq  # preserve original, filter handles display

# ─── SCRAPE LEGISTAR LINKS ────────────────────────────────────────────────────

def fetch_recent_event_urls(cutoff_date):
    events = []
    skip = 0
    date_str = cutoff_date.strftime('%Y-%m-%dT00:00:00')
    while True:
        url = f"https://webapi.legistar.com/v1/cincinnatioh/events?$top={PAGE_SIZE}&$skip={skip}&$filter=EventDate+ge+datetime'{date_str}'"
        resp = legistar_get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            break
        for e in data:
            site_url = e.get("EventInSiteURL", "")
            if site_url:
                events.append(site_url)
        if len(data) < PAGE_SIZE:
            break
        skip += PAGE_SIZE
        time.sleep(1.0)
    return events

def scrape_meeting(url):
    try:
        resp = legistar_get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
    except:
        return {}
    soup = BeautifulSoup(resp.text, "html.parser")
    links = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "LegislationDetail.aspx" in href and "ID=" in href and "GUID=" in href:
            file_num = a.get_text(strip=True)
            if file_num and file_num.isdigit() and len(file_num) == 9:
                links[file_num] = "https://cincinnatioh.legistar.com/" + href.lstrip("/")
    return links

# ─── JSON REBUILD ─────────────────────────────────────────────────────────────

def build_json(csv_rows, legistar_links, vote_lookup=None):
    if vote_lookup is None:
        vote_lookup = {}
    out = []
    for r in csv_rows:
        rq = normalize_requester(r.get('requester',''), r.get('intro_date',''))
        fn = r["file_number"]
        rec = {
            "t":           r["clean_title"],
            "rt":          r["raw_title"] if r.get("raw_title") and r["raw_title"] != r["clean_title"] else None,
            "tp":          r["topic_tags"],
            "a":           r["action_type_ai"],
            "g":           r["geography"],
            "d":           r["intro_date"][:10],
            "y":           r["intro_date"][:4],
            "rq":          rq,
            "st":          r["status"],
            "sm":          r["summary"],
            "f":           fn,
            "mt":          r["matter_type"],
            "id":          r["matter_id"],
            "legistar_url": legistar_links.get(fn, ""),
        }
        if fn in vote_lookup:
            v = vote_lookup[fn]
            rec["vote_yes"]     = v.get("yes_votes", [])
            rec["vote_no"]      = v.get("no_votes", [])
            rec["vote_abstain"] = v.get("abstain_votes", [])
            rec["vote_absent"]  = v.get("absent_votes", [])
            rec["vote_excused"] = v.get("excused_votes", [])
        out.append(rec)
    return out

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    import sys
    full_backfill = os.environ.get("FULL_LINK_BACKFILL", "") == "1" or "--full-link-backfill" in sys.argv

    cutoff = datetime.today() - timedelta(days=LOOKBACK_DAYS)
    print(f"Cutoff date: {cutoff.strftime('%Y-%m-%d')} ({LOOKBACK_DAYS} days ago)")

    if full_backfill:
        links_cutoff = datetime.strptime(LINK_BACKFILL_START, "%Y-%m-%d")
        print(f"FULL_LINK_BACKFILL enabled — will scrape every meeting since {LINK_BACKFILL_START}.")
    else:
        links_cutoff = datetime.today() - timedelta(days=LINKS_LOOKBACK_DAYS)

    # Load existing CSV
    print(f"\nLoading {EXISTING_CSV}...")
    with open(EXISTING_CSV, newline="", encoding="utf-8") as f:
        existing_rows = list(csv.DictReader(f))
    existing_ids = {r["matter_id"] for r in existing_rows}
    existing_files = {r["file_number"] for r in existing_rows}
    print(f"Existing records: {len(existing_rows)}")

    # Fetch new records from API
    print(f"\nFetching records from Legistar API since {cutoff.strftime('%Y-%m-%d')}...")
    new_matters = []
    skip = 0
    page = 1
    while True:
        print(f"  Page {page}...")
        try:
            xml_text = fetch_page(cutoff, skip)
            page_items = parse_page(xml_text)
        except Exception as e:
            print(f"  ERROR: {e}")
            break
        if not page_items:
            break
        print(f"  -> {len(page_items)} records")
        new_matters.extend(page_items)
        if len(page_items) < PAGE_SIZE:
            break
        skip += PAGE_SIZE
        page += 1
        time.sleep(DELAY_BETWEEN_PAGES)

    # Deduplicate
    truly_new = [m for m in new_matters if m["matter_id"] not in existing_ids]
    duplicates = len(new_matters) - len(truly_new)
    print(f"\nFetched: {len(new_matters)} | Duplicates skipped: {duplicates} | New: {len(truly_new)}")

    if not truly_new:
        print("No new records to add.")
        all_rows = existing_rows
    else:
        # Tag new items — skip low-value types, batch the rest
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        
        # Pre-classify: skip types that don't need AI
        to_tag = []
        for item in truly_new:
            if item['matter_type'] in SKIP_TAG_TYPES:
                mt = item['matter_type']
                if mt in REGISTRATION_TYPES:
                    item.update({"clean_title": rule_based_title(item['raw_title'], mt), "topic_tags": "registrations and terminations",
                                 "action_type_ai": "registration", "geography": "", "summary": rule_based_summary(item['raw_title']), "tag_status": "success"})
                elif mt in STATEMENT_TYPES:
                    item.update({"clean_title": rule_based_title(item['raw_title'], mt), "topic_tags": "financial statements",
                                 "action_type_ai": "statement", "geography": "", "summary": rule_based_summary(item['raw_title']), "tag_status": "success"})
                else:
                    item.update({"clean_title": item['raw_title'][:80], "topic_tags": "elections and governance",
                                 "action_type_ai": "other", "geography": "", "summary": "", "tag_status": "success"})
            else:
                to_tag.append(item)

        skipped = len(truly_new) - len(to_tag)
        print(f"\nTagging {len(to_tag)} items with Claude (skipping {skipped} low-value types)...")

        # Process in batches
        total_input_tokens = 0
        total_output_tokens = 0
        total_batches = (len(to_tag) + BATCH_SIZE - 1) // BATCH_SIZE
        for batch_start in range(0, len(to_tag), BATCH_SIZE):
            batch = to_tag[batch_start:batch_start + BATCH_SIZE]
            batch_num = batch_start // BATCH_SIZE
            print(f"  Batch {batch_num + 1}/{total_batches}: {len(batch)} items...", end="", flush=True)
            results, in_tok, out_tok = tag_batch(client, batch)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            cost_so_far = (total_input_tokens/1_000_000*HAIKU_INPUT_COST) + (total_output_tokens/1_000_000*HAIKU_OUTPUT_COST)
            print(f" ${cost_so_far:.3f} spent so far")
            for j, item in enumerate(batch):
                p = next((r for r in results if isinstance(r, dict) and r.get("i") == j), None) if isinstance(results, list) else None
                if p and "error" not in p:
                    topic_tags = "|".join(p.get("tp", [])).replace("energy and sustainability", "environment and sustainability")
                    mt = item['matter_type']
                    if mt in REGISTRATION_TYPES:
                        topic_tags = "registrations and terminations"
                        action_type = "registration"
                    elif mt in STATEMENT_TYPES:
                        topic_tags = "financial statements"
                        action_type = "statement"
                    else:
                        action_type = p.get("a", "")
                    item.update({
                        "clean_title":    p.get("t", ""),
                        "topic_tags":     topic_tags,
                        "action_type_ai": action_type,
                        "geography":      "|".join(p.get("g", [])),
                        "summary":        p.get("s", ""),
                        "tag_status":     "success"
                    })
                else:
                    # Fallback to single-item tagging
                    tag_item(client, item)
            time.sleep(DELAY_BETWEEN_ITEMS)

        # Append to CSV (full version stays local)
        all_rows = existing_rows + truly_new
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(all_rows)
        success = sum(1 for m in truly_new if m.get("tag_status") == "success")
        print(f"\nCSV updated. {success}/{len(truly_new)} new items tagged successfully.")

        # Write tagged-only CSV for GitHub (keeps file size small)
        tagged_rows = [r for r in all_rows if r.get("tag_status") == "success"]
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(tagged_rows)
        size_mb = os.path.getsize(OUTPUT_CSV) / 1024 / 1024
        print(f"Tagged-only CSV: {len(tagged_rows)} rows, {size_mb:.1f} MB")

    # Scrape Legistar links for recent (or, in backfill mode, all historical) meetings
    print(f"\nFetching meeting URLs from API since {links_cutoff.strftime('%Y-%m-%d')}...")
    event_urls = fetch_recent_event_urls(links_cutoff)
    print(f"Found {len(event_urls)} meetings. Scraping for legislation links...")

    # Load existing link map from JSON
    link_map = {}
    try:
        with open(OUTPUT_JSON) as f:
            existing_json = json.load(f)
        for r in existing_json:
            if not r.get('_meta') and r.get('f') and r.get('legistar_url'):
                link_map[r['f']] = r['legistar_url']
        print(f"Loaded {len(link_map)} existing Legistar links.")
    except:
        print("No existing JSON found, starting fresh.")

    # In backfill mode this loop can run for hundreds of meetings, so keep a
    # checkpoint (scraped meeting URLs + links found so far) that a rerun can
    # resume from if the job gets interrupted partway through.
    LINK_CHECKPOINT_FILE = "link_backfill_checkpoint.json"
    scraped_urls = set()
    if full_backfill:
        try:
            with open(LINK_CHECKPOINT_FILE) as f:
                ckpt = json.load(f)
            scraped_urls = set(ckpt.get("scraped_urls", []))
            link_map.update(ckpt.get("link_map", {}))
            print(f"Resuming backfill: {len(scraped_urls)} meetings already scraped in a prior run.")
        except FileNotFoundError:
            pass

    remaining = [u for u in event_urls if u not in scraped_urls]
    if full_backfill and len(remaining) < len(event_urls):
        print(f"Skipping {len(event_urls) - len(remaining)} already-scraped meetings, {len(remaining)} left.")

    for i, url in enumerate(remaining):
        print(f"  [{i+1}/{len(remaining)}] Scraping...", end="", flush=True)
        links = scrape_meeting(url)
        link_map.update(links)
        scraped_urls.add(url)
        print(f" {len(links)} links")
        time.sleep(DELAY_HTML)

        if full_backfill and (i + 1) % 50 == 0:
            with open(LINK_CHECKPOINT_FILE, "w") as f:
                json.dump({"scraped_urls": sorted(scraped_urls), "link_map": link_map}, f)
            print(f"  [checkpoint saved: {len(scraped_urls)} meetings, {len(link_map)} links]")

    if full_backfill:
        with open(LINK_CHECKPOINT_FILE, "w") as f:
            json.dump({"scraped_urls": sorted(scraped_urls), "link_map": link_map}, f)

    # Print tagging cost if any tagging happened
    try:
        actual_cost = (total_input_tokens/1_000_000*HAIKU_INPUT_COST) + (total_output_tokens/1_000_000*HAIKU_OUTPUT_COST)
        print(f"Tagging cost this run: ${actual_cost:.3f} ({total_input_tokens:,} input tokens, {total_output_tokens:,} output tokens)")
    except:
        pass

    # Load vote data
    vote_lookup = {}
    try:
        with open(VOTES_FILE) as f:
            votes_data = json.load(f)
        vote_lookup = {k: v for k, v in votes_data.items() if not k.startswith("_")}
        print(f"Loaded {len(vote_lookup)} vote records from {VOTES_FILE}")
    except:
        print(f"No {VOTES_FILE} found — votes will not be included")

    # Rebuild JSON from tagged rows only
    print(f"\nRebuilding {OUTPUT_JSON}...")
    with open(OUTPUT_CSV, newline="", encoding="utf-8") as f:
        final_rows = [r for r in csv.DictReader(f) if r.get("tag_status") == "success"]

    json_records = build_json(final_rows, link_map, vote_lookup)
    meta = {'_meta': True, 'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M')}
    output = [meta] + json_records

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, separators=(",", ":"))

    size = len(json.dumps(output, separators=(",", ":"))) / 1024
    print(f"Done. {OUTPUT_JSON} written ({size:.0f} KB)")
    print(f"\nNext step: upload {OUTPUT_JSON} to GitHub.")

if __name__ == "__main__":
    main()
