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

# ─── CONFIG ──────────────────────────────────────────────────────────────────

import os
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "YOUR_API_KEY_HERE")

EXISTING_CSV  = "cincinnati_agenda_items_complete.csv"
OUTPUT_CSV    = "cincinnati_agenda_items_complete.csv"
OUTPUT_JSON   = "council_data.json"
VOTES_FILE    = "votes_api.json"

# Cutoff: pull items introduced in the last N days
LOOKBACK_DAYS = 14

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
    resp = requests.get(url, headers=headers, timeout=30)
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

def tag_item(client, item):
    prompt = f"""You are processing Cincinnati City Council agenda items for a civic data archive.
Return ONLY a valid JSON object with these fields:
- "clean_title": Plain-English title, max 15 words, no boilerplate like "ORDINANCE dated..." or "RE:"
- "topic_tags": 1-3 values from: {json.dumps(TOPIC_TAGS)}
- "action_type": One value from: {json.dumps(ACTION_TYPES)}
- "geography": 0-2 values from: {json.dumps(GEOGRAPHY_TAGS)}. Use "citywide" if broad. Empty list if unclear.
- "summary": One sentence, max 25 words, describing what this item does or proposes.

No preamble, no markdown fences. Valid JSON only.

Body: {item['body']}
Type: {item['matter_type']}
Status: {item['status']}
Requester: {item['requester']}
Date: {item['intro_date']}
Title: {item['raw_title']}
Notes: {item['notes']}"""

    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        p = json.loads(raw)

        mt = item['matter_type']
        if mt in REGISTRATION_TYPES:
            action_type = 'registration'
            topic_tags  = 'registrations and terminations'
        elif mt in STATEMENT_TYPES:
            action_type = 'statement'
            topic_tags  = 'financial statements'
        else:
            action_type = p.get("action_type", "")
            topic_tags  = "|".join(p.get("topic_tags", []))
            # remap stray tag
            topic_tags = topic_tags.replace("energy and sustainability", "environment and sustainability")

        item.update({
            "clean_title":    p.get("clean_title", ""),
            "topic_tags":     topic_tags,
            "action_type_ai": action_type,
            "geography":      "|".join(p.get("geography", [])),
            "summary":        p.get("summary", ""),
            "tag_status":     "success"
        })
    except Exception as e:
        item.update({
            "clean_title": "", "topic_tags": "", "action_type_ai": "",
            "geography": "", "summary": "", "tag_status": f"error: {e}"
        })
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
        resp = requests.get(url, timeout=30)
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
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
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
        out.append(rec)
    return out

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    cutoff = datetime.today() - timedelta(days=LOOKBACK_DAYS)
    print(f"Cutoff date: {cutoff.strftime('%Y-%m-%d')} ({LOOKBACK_DAYS} days ago)")

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
        # Tag new items
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        print(f"\nTagging {len(truly_new)} new items with Claude...")
        for i, item in enumerate(truly_new):
            print(f"  [{i+1}/{len(truly_new)}] {item['raw_title'][:80]}")
            truly_new[i] = tag_item(client, item)
            time.sleep(DELAY_BETWEEN_ITEMS)

        # Append to CSV
        all_rows = existing_rows + truly_new
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(all_rows)
        success = sum(1 for m in truly_new if m.get("tag_status") == "success")
        print(f"\nCSV updated. {success}/{len(truly_new)} new items tagged successfully.")

    # Scrape Legistar links for recent meetings
    print(f"\nFetching recent meeting URLs from API...")
    event_urls = fetch_recent_event_urls(cutoff)
    print(f"Found {len(event_urls)} recent meetings. Scraping for legislation links...")

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

    for i, url in enumerate(event_urls):
        print(f"  [{i+1}/{len(event_urls)}] Scraping...", end="", flush=True)
        links = scrape_meeting(url)
        link_map.update(links)
        print(f" {len(links)} links")
        time.sleep(DELAY_HTML)

    # Load vote data
    vote_lookup = {}
    try:
        with open(VOTES_FILE) as f:
            votes_data = json.load(f)
        vote_lookup = {k: v for k, v in votes_data.items() if not k.startswith("_")}
        print(f"Loaded {len(vote_lookup)} vote records from {VOTES_FILE}")
    except:
        print(f"No {VOTES_FILE} found — votes will not be included")

    # Rebuild JSON
    print(f"\nRebuilding {OUTPUT_JSON}...")
    with open(OUTPUT_CSV, newline="", encoding="utf-8") as f:
        final_rows = list(csv.DictReader(f))

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
