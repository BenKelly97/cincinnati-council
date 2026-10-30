"""
Cincinnati Legistar — Update Pipeline
======================================
Keeps the site data in step with Legistar:

  1. Pulls matters introduced in the last LOOKBACK_DAYS days.
  2. Pulls matters MODIFIED in the last MODIFIED_LOOKBACK_DAYS days. This
     catches matters entered late with an earlier introduction date, and
     status changes on older matters.
  3. Adds matters that are not in the CSV yet (tagged with Claude).
  4. Refreshes status, type, body, dates and enactment number on matters
     already in the CSV, so "Agenda Ready" rows move to their final status.
  5. Scrapes Legistar links for recent meetings.
  6. Rebuilds council_data.json.

REQUIREMENTS:
    pip install requests anthropic beautifulsoup4

FILES NEEDED IN SAME FOLDER:
    cincinnati_agenda_items_complete.csv  (your existing archive)
    council_data.json                     (your existing site data)

OUTPUT:
    cincinnati_agenda_items_complete.csv  (updated)
    council_data.json                     (rebuilt, ready for GitHub upload)

USAGE:
    python3 update_pipeline.py                  normal run
    python3 update_pipeline.py --dry-run        fetch and compare only; change nothing
    python3 update_pipeline.py --full-sync      compare every matter since 2018-01-01
    python3 update_pipeline.py --full-sync --since 2020-01-01
    python3 update_pipeline.py --modified-days 60

Each run that finds differences also writes sync_changes.csv (one row per
field changed) and, for --full-sync, sync_not_on_legistar.csv (CSV rows that
Legistar did not return; these are reported, never deleted).
"""

import argparse, csv, re, sys, time, json, requests
import xml.etree.ElementTree as ET
import anthropic
from bs4 import BeautifulSoup
import attachments as att
from datetime import datetime, timedelta, timezone
from collections import Counter, defaultdict

# ─── CONFIG ──────────────────────────────────────────────────────────────────

import os
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "YOUR_API_KEY_HERE")
# Attachment text for items whose Legistar title stops at "(BALANCE ON FILE...)".
# Loaded in main(); tag_batch reads it. See attachments.py.
ATT_CACHE = {}

EXISTING_CSV  = "cincinnati_agenda_items_complete.csv"
OUTPUT_CSV    = "cincinnati_agenda_items_complete.csv"
OUTPUT_JSON   = "council_data.json"
VOTES_FILE    = "votes_api.json"
TITLE_OVERRIDES_FILE = "title_overrides.json"
SUMMARY_OVERRIDES_FILE = "summary_overrides.json"
EXCLUDE_FILE = "exclude_matter_ids.json"   # matter ids to remove and never add (JSON list)
AGENDA_FILE  = "agenda.json"               # meetings in the window below, for agenda.html
AGENDA_PAST_DAYS = 14                      # meetings this many days back
AGENDA_AHEAD_DAYS = 30                     # and this many days ahead
AGENDA_RECHECK_DAYS = 45                   # meetings re-read from Legistar on every run
AGENDA_ARCHIVE_START_YEAR = 2018           # first year kept in agenda_YYYY.json
AGENDA_INDEX_FILE = "agenda_index.json"    # years and counts, for agenda.html
AGENDA_PENDING_DAYS = 365                  # past meetings without actions re-read this far back
AGENDA_FORMAT = 2                          # year files below this are re-read from Legistar

# Cutoff: pull items introduced in the last N days
LOOKBACK_DAYS = 14
# Also pull items MODIFIED in the last N days (late entries, status changes)
MODIFIED_LOOKBACK_DAYS = 21
# Default start for --full-sync
FULL_SYNC_SINCE = "2018-01-01"
# Earliest introduction date the site covers. Matters introduced before this
# are never added, and any already in the CSV are removed. The modified-date
# pull returns old matters whenever Legistar touches them (e.g. 201201557,
# introduced 2012, modified 2026-10-07), so this check is needed there.
SITE_START = FULL_SYNC_SINCE

API_BASE = os.environ.get("LEGISTAR_API_BASE", "https://webapi.legistar.com/v1/cincinnatioh").rstrip("/")

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

def http_get_text(url, headers=None, tries=3):
    """GET with retries; raises after the last attempt."""
    for attempt in range(1, tries + 1):
        try:
            resp = requests.get(url, headers=headers or {}, timeout=60)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            if attempt == tries:
                raise
            print(f"    request failed ({e}); retry {attempt}/{tries - 1}")
            time.sleep(5 * attempt)

def fetch_matters(flt, label):
    """Page through /matters with an OData filter.
    Returns (matters, complete). complete is False if a page failed after retries."""
    out, skip, page = [], 0, 1
    while True:
        url = (f"{API_BASE}/matters?$top={PAGE_SIZE}&$skip={skip}"
               f"&$filter={flt}&$orderby=MatterId")
        try:
            items = parse_page(http_get_text(url, {"Accept": "application/xml"}))
        except Exception as e:
            print(f"  ERROR ({label}, page {page}): {e}")
            return out, False
        print(f"  {label}: page {page}, {len(items)} records")
        out.extend(items)
        if len(items) < PAGE_SIZE:
            return out, True
        skip += PAGE_SIZE
        page += 1
        time.sleep(DELAY_BETWEEN_PAGES)

def odata_date(d):
    return d.strftime('%Y-%m-%dT00:00:00')

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
            "requester":        resolve_requester(get_text(m, "MatterRequester"), title),
            "intro_date":       get_text(m, "MatterIntroDate")[:10],
            "agenda_date":      get_text(m, "MatterAgendaDate")[:10],
            "passed_date":      get_text(m, "MatterPassedDate")[:10],
            "enactment_number": get_text(m, "MatterEnactmentNumber"),
            "raw_title":        title,
            "notes":            notes[:500] if notes else "",
            "modified_utc":     get_text(m, "MatterLastModifiedUtc"),
        }
        matters.append(matter)
    return matters

# ─── AI TAGGING ───────────────────────────────────────────────────────────────

# Filing types worded by filing_text() (see FILING WORDING) instead of the AI when
# their Legistar title is in a recognized form; in any other form they go to the AI
# like every other type. rewrite_text.py leaves these types alone. (Before
# 2026-10-30 Notice, Memo, FYI Memo, Receipt, Request, Oath of Office, Resignation
# and Termination items also skipped the AI and showed the first 80 characters of
# the Legistar title.)
SKIP_TAG_TYPES = {'Registration', 'Registration-Update', 'Statement', 'Successor'}

# Compact tag lists for prompt (saves tokens)
TOPIC_STR = ",".join(TOPIC_TAGS)
ACTION_STR = ",".join(ACTION_TYPES)
GEO_STR   = ",".join(GEOGRAPHY_TAGS)

BATCH_SIZE = 15  # items per API call

# Model for tagging and writing titles, with its pricing (dollars per million tokens)
TAG_MODEL = "claude-sonnet-5-5"
TAG_INPUT_COST  = 2.00
TAG_OUTPUT_COST = 10.00

# Writing rules for the title ("t") and description ("s"). Used by tag_batch for
# new items and by rewrite_text.py for the one-time rewrite of existing items.
STYLE_RULES = """Writing rules for "t" (title) and "s" (description):
- Write standard English as in the body of a newspaper story, not headline style.
- Articles: use "the", "a" and "an" wherever ordinary prose needs them, including before the names of programs, funds, districts, departments, committees, agreements and events ("the Black Family Reunion", "the Over-the-Rhine South Special Improvement District", "the City's yard waste program").
- Lists: no comma before the final "and" ("A, B and C").
- Capitalization: keep proper names capitalized as in the item text ("Human Service Fund", "Cincinnati Police Department"). Capitalize "City" when it means the City of Cincinnati. Do not capitalize ordinary terms such as "operating budget" or "capital budget".
- Motions: describe what the motion asks for ("Asks the Administration to...", "Asks Council to..."), never "Moves to...".
- Keep the term that names the kind of item when the item text uses it, in t or s: "grant", "appropriation", "Capital Improvement Program", "tax exemption", "special event", "liquor permit", and report names such as "Budget Status Report". People search for these words.
- t (title): at most 12 words and no ending period. For an action, start with the verb ("Authorize the transfer of $200,000 for special events"); for a presentation, report or communication, use a noun phrase ("Report on the Paul Clock Bell Tower").
- s (description): one complete sentence of at most 30 words, present tense, ending with a period ("Authorizes the City Manager to...", "Asks the Administration to..."). Say what the item does and give the key amount, place, organization or person.
- Spell out abbreviations: "Ordinance No. 36-2025", not "Ord. 36-2025"; "fiscal year 2028", not "FY 2028". Keep addresses and file numbers as written.
- Numbers: write every number as figures, never as words: "0.30%", "61 percent", "$200,000", "fiscal years 2028 and 2029", "Ordinance No. 36-2025", "30 days". This applies to the title as well.
- Keep the names of agreements, laws and organizations accurate. To shorten, leave words out; never merge two names into one.
- Use only facts in the item text; do not guess. Say "Legislative Agent", never "lobbyist".
- When an item includes [ATTACHED TEXT ...], it is the full text the title stops short of. Base t and s on what it asks for or does. Ignore letterheads, addresses, phone numbers, email addresses and signatures, and leave out any words or figures garbled by scanning.
- Never write that details are "on file" or that the item asks for "the following"; say what it actually asks for.
Example of the change wanted:
  wrong t: Street repairs contract Westwood Price Hill.
  wrong s: Authorize $2.1M contract for paving, sidewalk repair, curb replacement in Westwood, Price Hill
  right t: Authorize a $2.1 million street repair contract for Westwood and Price Hill
  right s: Authorizes a $2.1 million contract for paving, sidewalk repair and curb replacement in Westwood and Price Hill.
  wrong t: Request administration presentation on STARS crime reporting spike
  right t: Request a presentation from the Administration on the rise in reported rapes
  wrong s: Requires the program be funded at least zero point three percent of General Fund Budget in fiscal years twenty twenty-eight.
  right s: Asks for an ordinance funding the Access to Counsel Program at no less than 0.30% of the General Fund budget in fiscal years 2028 and 2029."""

def reply_text(resp):
    """Text of a Messages API reply. The reply can start with a thinking block, so
    the text blocks are joined rather than taking the first block."""
    return "".join(getattr(b, "text", "") for b in resp.content
                   if getattr(b, "type", "") == "text").strip()


def tag_batch(client, items):
    """Tag multiple items in a single API call. Returns (results, input_tokens, output_tokens)."""
    lines = []
    for i, item in enumerate(items):
        lines.append(f"{i}|{att.prompt_text(item, ATT_CACHE)}|{item['matter_type']}|{item['body']}|{item['requester']}")
    batch_text = "\n".join(lines)

    prompt = f"""Tag Cincinnati City Council agenda items. Return a JSON array, one object per line.
Each object: {{"i":index,"t":"title","tp":["topic1"],"a":"action_type","g":["geo"],"s":"description"}}
{STYLE_RULES}
Topics: {TOPIC_STR}
Actions: {ACTION_STR}
Geo: {GEO_STR} (citywide if broad, [] if unclear)
Items (index|title|type|body|requester):
{batch_text}
JSON array only, no markdown."""

    try:
        resp = client.messages.create(
            model=TAG_MODEL,
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = reply_text(resp)
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"): raw = raw[4:]
            raw = raw.strip()
        usage = resp.usage
        if getattr(resp, "stop_reason", "") == "max_tokens":
            raise ValueError("response cut off at max_tokens")
        # The model sometimes adds a sentence before the JSON, or returns one object instead of
        # an array when asked about a single item (that left long-title rows untagged as "no result").
        starts = [k for k in (raw.find("["), raw.find("{")) if k >= 0]
        if starts and min(starts) > 0:
            raw = raw[min(starts):]
        data = json.loads(raw)
        if isinstance(data, dict):
            data = data.get("items") or data.get("results") or [data]
        if not isinstance(data, list) or not data:
            raise ValueError("empty or unexpected response: " + raw[:120])
        return data, usage.input_tokens, usage.output_tokens
    except Exception as e:
        return [{"i": i, "error": str(e)} for i in range(len(items))], 0, 0

_FILING_NAMES = None

def fixed_wording(item):
    """Fill a filing in a recognized form (filing_text) without the AI and return True;
    return False for every other item, which then goes to the AI."""
    global _FILING_NAMES
    mt = item['matter_type']
    if mt not in SKIP_TAG_TYPES:
        return False
    if _FILING_NAMES is None:
        _FILING_NAMES = load_filing_names()
    res = filing_text(mt, item.get('raw_title', ''), _FILING_NAMES)
    if not res:
        return False
    tags = (("financial statements", "statement") if mt in STATEMENT_TYPES
            else ("registrations and terminations", "registration"))
    item.update({"clean_title": res[0], "summary": res[1], "topic_tags": tags[0],
                 "action_type_ai": tags[1], "geography": "", "tag_status": "success"})
    if FILING_MARK not in (item.get("notes") or ""):
        item["notes"] = ((item.get("notes") or "") + " " + FILING_MARK).strip()
    return True

def tag_item(client, item):
    """Tag a single item (used for fallback)."""
    if fixed_wording(item):
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

# ─── SPONSOR NAME PARSING (fallback for blank/committee MatterRequester) ──────
# Legistar's MatterRequester field is often blank or set to a committee name
# even when the matter title clearly names the sponsoring councilmember(s)
# (e.g. "submitted by Councilmember Albi"). When that happens, parse the
# sponsor(s) out of the title text instead, so items are still attributable
# on the site. Added 2026-09-24/25 after discovering the Sponsor filter
# returned 0 results for Anna Albi despite her having sponsored dozens of
# items — her MatterRequester was consistently null/a committee name.

SURNAME_TO_CANONICAL = {
    'albi': 'Anna Albi',
    'cramerding': 'Jeff Cramerding',
    'james': 'Ryan James',
    'jeffreys': 'Mark Jeffreys',
    'johnson': 'Scotty Johnson',
    'kearney': 'Jan-Michele Kearney',
    'nolan': 'Evan Nolan',
    'owens': 'Meeka Owens',
    'walsh': 'Seth Walsh',
    'parks': 'Victoria Parks',
    'landsman': 'Greg Landsman',
    'seelbach': 'Chris Seelbach',
    'sittenfeld': 'P.G. Sittenfeld',
    'mann': 'David Mann',
    'harris': 'Reggie Harris',
    'smitherman': 'Christopher Smitherman',
    'sundermann': 'Betsy Sundermann',
    'young': 'Wendell Young',
    'pastor': 'Jeff Pastor',
    'keating': 'Liz Keating',
    'goodin': 'Steve Goodin',
}
INDIVIDUALS = set(SURNAME_TO_CANONICAL.values()) | {'Mayor Aftab Pureval', 'Mayor John Cranley', 'City Manager'}

_ALL_VARIANTS = {}
for _surname_key, _canon in SURNAME_TO_CANONICAL.items():
    _ALL_VARIANTS[_surname_key] = _canon
    _ALL_VARIANTS[_canon.lower()] = _canon

_NAME_ALTERNATION = '|'.join(re.escape(v) for v in sorted(_ALL_VARIANTS.keys(), key=len, reverse=True))
_NAME_RE = re.compile(r'\b(' + _NAME_ALTERNATION + r')\b', re.IGNORECASE)

_TERMINATORS = [
    r',\s*from\s',
    r'\bfrom\s',
    r',\s*dated\s',
    r',?\s*WE MOVE\b',
    r'\(BALANCE',
    r'\(STATEMENT',
    r',\s*[A-Z]{4,}',
]

def parse_sponsors_from_title(title):
    if not title:
        return []
    m = re.search(r'submitted by\s+', title, re.IGNORECASE)
    if not m:
        return []
    tail = title[m.end():]
    cut = len(tail)
    for pat in _TERMINATORS:
        mm = re.search(pat, tail)
        if mm:
            cut = min(cut, mm.start())
    segment = tail[:cut]
    found = []
    for mm in _NAME_RE.finditer(segment):
        canon = _ALL_VARIANTS[mm.group(1).lower()]
        if canon not in found:
            found.append(canon)
    return found

def resolve_requester(existing_rq, raw_title):
    existing = (existing_rq or '').strip()
    parsed = parse_sponsors_from_title(raw_title)
    if not parsed:
        return existing
    if existing in INDIVIDUALS:
        combined = [existing] + [p for p in parsed if p != existing]
        return ', '.join(combined)
    return ', '.join(parsed)

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
        url = f"{API_BASE}/events?$top={PAGE_SIZE}&$skip={skip}&$filter=EventDate+ge+datetime'{date_str}'"
        data = json.loads(http_get_text(url))
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

LEGISTAR_SITE = "https://cincinnatioh.legistar.com"

def legistar_permalink(matter_id):
    """Public Legistar link for a matter, built from its matter id. Legistar
    redirects it to the matter's detail page. Used when the meeting-page scrape
    has not produced a direct link for the matter."""
    mid = str(matter_id or "").strip()
    if not mid.isdigit():
        return ""
    return f"{LEGISTAR_SITE}/gateway.aspx?m=l&id=/matter.aspx?key={mid}"

# Neighborhood names follow the City Planning Department's 2020 Statistical
# Neighborhood Approximations list (51 neighborhoods), plus "citywide".
# GEO_ALIASES maps other spellings to those names. Values not on the list
# after mapping (other municipalities, umbrella areas, unreadable values) are
# dropped from the published record; the CSV keeps the original tag.
CITY_NEIGHBORHOODS = {
    "Avondale", "Bond Hill", "California", "Camp Washington", "Carthage", "Clifton",
    "College Hill", "Columbia Tusculum", "Corryville", "CUF", "Downtown", "East End",
    "East Price Hill", "East Walnut Hills", "East Westwood", "English Woods", "Evanston",
    "Hartwell", "Hyde Park", "Kennedy Heights", "Linwood", "Lower Price Hill",
    "Madisonville", "Millvale", "Mt. Adams", "Mt. Airy", "Mt. Auburn", "Mt. Lookout",
    "Mt. Washington", "North Avondale", "North Fairmount", "Northside", "Oakley",
    "Over-the-Rhine", "Paddock Hills", "Pendleton", "Pleasant Ridge", "Queensgate",
    "Riverside", "Roselawn", "Sayler Park", "Sedamsville", "South Cumminsville",
    "South Fairmount", "Spring Grove Village", "Villages at Roll Hill", "Walnut Hills",
    "West End", "West Price Hill", "Westwood", "Winton Hills",
}
GEO_ALIASES = {
    "Mount Adams": "Mt. Adams", "Mount Airy": "Mt. Airy", "Mount Auburn": "Mt. Auburn",
    "Mount Lookout": "Mt. Lookout", "Mount Washington": "Mt. Washington",
    "Fairview": "CUF", "Clifton Heights": "CUF", "University Heights": "CUF",
    "Roll Hill": "Villages at Roll Hill", "Winton Place": "Spring Grove Village",
    "OTR": "Over-the-Rhine", "Over the Rhine": "Over-the-Rhine",
}

def normalize_geography(value):
    out = []
    for g in (value or "").split("|"):
        g = g.strip()
        if not g:
            continue
        if g.lower() == "citywide":
            g = "citywide"
        else:
            g = GEO_ALIASES.get(g, g)
            if g not in CITY_NEIGHBORHOODS:
                continue
        if g not in out:
            out.append(g)
    return "|".join(out)

# Topic tags merged into the main categories. The CSV keeps the original tag.
TOPIC_ALIASES = {
    "energy": "environment and sustainability",
    "energy and sustainability": "environment and sustainability",
    "public health": "health",
    "finance policy": "budget",
    "history": "arts and culture",
    "sports": "parks and recreation",
}

def normalize_topics(value):
    out = []
    for t in (value or "").split("|"):
        t = TOPIC_ALIASES.get(t.strip(), t.strip())
        if t and t not in out:
            out.append(t)
    return "|".join(out)

def valid_file_number(fn):
    return len(fn or "") == 9 and fn.isdigit()

def vote_target_rows(rows, vote):
    """Pick the CSV row(s) a vote record belongs to when several rows share a
    file number. Votes scraped after 2026-10-14 carry the Legistar matter id
    and are matched on it. Older records are matched to the row introduced on
    or before the meeting date, preferring a row whose status is not
    "Historical" (Legistar's label for superseded duplicate records)."""
    mid = str(vote.get("matter_id") or "")
    if mid:
        return [r for r in rows if r.get("matter_id") == mid]
    meeting = vote.get("meeting_date", "")
    cands = [r for r in rows if (r.get("intro_date") or "")[:10] <= meeting] or list(rows)
    current = [r for r in cands if (r.get("status") or "") != "Historical"] or cands
    return [max(current, key=lambda r: (r.get("intro_date") or ""))]

# ─── NEIGHBORHOODS FROM ADDRESSES ────────────────────────────────────────────
# When a matter's Legistar title contains a street address, the neighborhood is
# taken from the City's boundary map instead of the AI tag. Addresses are
# geocoded with the U.S. Census geocoder (free, public) and placed in the City
# Planning Department's 2020 Statistical Neighborhood Approximations (CAGIS).
# Any failure here leaves the AI tags in place.

GEOCODE_CACHE_FILE = "geocode_cache.json"            # {"address": [lon, lat] or null}
BOUNDARY_FILE = "neighborhoods_sna2020.geojson"      # downloaded once, then kept in the repo
BOUNDARY_URLS = [
    "https://hub.arcgis.com/api/v3/datasets/572561553c9e4d618d2d7939c5261d46_0/downloads/data"
    "?format=geojson&spatialRefId=4326&where=1%3D1",
    "https://opendata.arcgis.com/datasets/572561553c9e4d618d2d7939c5261d46_0.geojson",
]
CENSUS_BATCH_URL = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
CENSUS_BATCH_SIZE = 1000
# SNA areas whose names differ from the site's list. Three SNA areas cover two
# neighborhoods each; see address_geography().
SNA_NAMES = {
    "Roll Hill": ("Villages at Roll Hill",),
    "English Woods_North Fairmount": ("English Woods", "North Fairmount"),
    "Lower Price Hill_Queensgate": ("Lower Price Hill", "Queensgate"),
    "Riverside_Sedamsville": ("Riverside", "Sedamsville"),
}
# Records whose address is not the subject of the matter (a Legislative
# Agent's office address, for example) are not geocoded.
NO_GEOCODE_TYPES = {"Registration", "Registration-Update", "Termination", "Successor"}

STREET_SUFFIX = (r"(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Boulevard|Blvd|Lane|Ln|Court|Ct|Place|Pl|Pike|"
                 r"Parkway|Pkwy|Terrace|Ter|Circle|Cir|Highway|Hwy|Alley|Way|Row|Trail|Ridge|Plaza)")
ADDRESS_RE = re.compile(
    r"\b([1-9]\d{0,4})(?:\s*[-–&]\s*\d{1,5}[A-Za-z]?)?[A-Za-z]?\s+"
    r"((?:[NSEW]\.?\s+)?(?:[A-Za-z][A-Za-z\.'\-]*\s+){0,3}?" + STREET_SUFFIX +
    r"(?:\.?\s+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Place|Pl))?)\.?(?=[\s,;:)]|$)",
    re.I)
ADDRESS_BAD_FIRST = {"of", "and", "the", "to", "for", "in", "on", "at", "a", "an", "from", "with", "by",
                     "or", "per", "fy", "section", "sections", "units", "unit", "acres", "feet", "foot",
                     "sq", "square", "days", "years"}

def find_addresses(text):
    """Street addresses in a Legistar title, e.g. "3515 Madison Road". For a range
    such as 3628-3640 the first number is used."""
    out = []
    for m in ADDRESS_RE.finditer(text or ""):
        num, street = m.group(1), " ".join(m.group(2).split())
        words = street.replace(".", " ").split()
        if words[0].lower() in ADDRESS_BAD_FIRST:
            continue
        if len([w for w in words if w.upper() not in ("N", "S", "E", "W")]) < 2:
            continue                                  # a bare suffix ("2569 St") is not an address
        a = f"{num} {street}".title()
        if a not in out:
            out.append(a)
    return out

def named_neighborhoods(text):
    """City neighborhoods a Legistar title places the matter in: "in Walnut Hills",
    "in the Over-the-Rhine neighborhood". Names in business names ("OTR Holdings",
    "W Salon & Spa Hyde Park") and street names ("Linwood Avenue") do not count, and
    a name inside a longer one ("Westwood" in "East Westwood") is dropped."""
    names = list(CITY_NEIGHBORHOODS) + list(GEO_ALIASES)
    found = []
    for name in names:
        for variant in {name, name.upper()}:
            pat = (r"\b(?:[Ii]n|IN)\s+(?:(?:[Tt]he|THE)\s+)?(?:" + re.escape(variant) + r")"
                   r"(?![\w-])(?!\s+" + STREET_SUFFIX + r"\b)")
            for m in re.finditer(pat, text or ""):
                found.append((m.end() - len(variant), m.end(), GEO_ALIASES.get(name, name)))
    keep = [f for f in found
            if not any(o is not f and o[0] <= f[0] and f[1] <= o[1] and (o[1] - o[0]) > (f[1] - f[0]) for o in found)]
    out = []
    for _, _, n in sorted(keep):
        if n not in out:
            out.append(n)
    return out

def load_boundaries():
    """[(neighborhood names, bbox, polygons)] from BOUNDARY_FILE, downloading it if missing.
    Each polygon is a list of rings (outer ring first, then holes) of (lon, lat)."""
    if not os.path.exists(BOUNDARY_FILE):
        last = None
        for url in BOUNDARY_URLS:
            try:
                r = requests.get(url, timeout=120)
                r.raise_for_status()
                data = r.json()
                if len(data.get("features", [])) < 40:
                    raise ValueError(f"only {len(data.get('features', []))} features")
                with open(BOUNDARY_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, separators=(",", ":"))
                print(f"Downloaded {BOUNDARY_FILE} ({len(data['features'])} areas).")
                break
            except Exception as e:
                last = e
        else:
            raise RuntimeError(f"could not download neighborhood boundaries ({last})")
    with open(BOUNDARY_FILE, encoding="utf-8") as f:
        data = json.load(f)
    areas = []
    for feat in data["features"]:
        name = (feat.get("properties") or {}).get("SNA_NAME", "")
        names = SNA_NAMES.get(name, (name,))
        geom = feat.get("geometry") or {}
        polys = geom.get("coordinates", [])
        if geom.get("type") == "Polygon":
            polys = [polys]
        elif geom.get("type") != "MultiPolygon":
            continue
        polys = [[[(float(x), float(y)) for x, y, *_ in ring] for ring in poly] for poly in polys]
        xs = [x for poly in polys for x, _ in poly[0]]
        ys = [y for poly in polys for _, y in poly[0]]
        areas.append((names, (min(xs), min(ys), max(xs), max(ys)), polys))
    return areas

def point_in_ring(x, y, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside

def locate(lon, lat, areas):
    """Neighborhood names for a point, or () when it is outside every area."""
    for names, (x0, y0, x1, y1), polys in areas:
        if not (x0 <= lon <= x1 and y0 <= lat <= y1):
            continue
        for rings in polys:
            if point_in_ring(lon, lat, rings[0]) and not any(point_in_ring(lon, lat, h) for h in rings[1:]):
                return names
    return ()

def census_geocode(addresses):
    """{address: (lon, lat) or None} from the Census batch geocoder. Raises on a failed request."""
    out = {}
    for i in range(0, len(addresses), CENSUS_BATCH_SIZE):
        chunk = addresses[i:i + CENSUS_BATCH_SIZE]
        lines = "\n".join(f'{k},"{a.replace(chr(34), "")}",Cincinnati,OH,' for k, a in enumerate(chunk))
        r = requests.post(CENSUS_BATCH_URL, data={"benchmark": "Public_AR_Current"},
                          files={"addressFile": ("addresses.csv", lines, "text/csv")}, timeout=600)
        r.raise_for_status()
        got = {}
        for rec in csv.reader(r.text.splitlines()):
            if len(rec) >= 6 and rec[2] == "Match" and rec[0].isdigit():
                lon, lat = rec[5].split(",")
                got[int(rec[0])] = (float(lon), float(lat))
        for k, a in enumerate(chunk):
            out[a] = got.get(k)
        print(f"  geocoded {min(i + CENSUS_BATCH_SIZE, len(addresses))}/{len(addresses)} "
              f"({sum(1 for k in range(len(chunk)) if k in got)} matched in this batch)")
    return out

def address_geography(rows):
    """{matter_id: "Hood1|Hood2"} for rows whose title has an address: the neighborhood the
    title names, else the map's neighborhood for the address. Rows not in the result
    (no address, or no geocoded address inside the city) keep their AI tags."""
    areas = load_boundaries()
    cache = {}
    if os.path.exists(GEOCODE_CACHE_FILE):
        with open(GEOCODE_CACHE_FILE, encoding="utf-8") as f:
            cache = json.load(f)
    row_addrs = {}
    for r in rows:
        if r.get("matter_type") in NO_GEOCODE_TYPES:
            continue
        addrs = find_addresses(r.get("raw_title", ""))
        if addrs:
            row_addrs[r["matter_id"]] = (r, addrs)
    todo = sorted({a for _, addrs in row_addrs.values() for a in addrs if a not in cache})
    if todo:
        print(f"Geocoding {len(todo)} new address(es)...")
        try:
            cache.update({a: (list(p) if p else None) for a, p in census_geocode(todo).items()})
        except Exception as e:
            print(f"  Census geocoder failed ({e}); those addresses wait for the next run.")
        with open(GEOCODE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=0, sort_keys=True)
    out = {}
    for mid, (r, addrs) in row_addrs.items():
        # A neighborhood named in the Legistar title is used as stated; Legistar's
        # wording follows community council names, which differ from the SNA map
        # in places (2133 Ravine Street is "in Over-the-Rhine"; the map says CUF).
        named = named_neighborhoods(r.get("raw_title", ""))
        if named:
            out[mid] = "|".join(named)
            continue
        ai = normalize_geography(r.get("geography", "")).split("|")
        hoods = []
        for a in addrs:
            p = cache.get(a)
            if not p:
                continue
            names = locate(p[0], p[1], areas)
            if len(names) > 1:
                # A shared SNA area: keep the AI's pick when it named one of the two.
                names = tuple(n for n in names if n in ai) or names
            for n in names:
                if n not in hoods:
                    hoods.append(n)
        if hoods:
            out[mid] = "|".join(hoods)
    return out

def build_json(csv_rows, legistar_links, vote_lookup=None, geo_by_address=None):
    if vote_lookup is None:
        vote_lookup = {}
    geo_by_address = geo_by_address or {}
    by_fn = {}
    for r in csv_rows:
        by_fn.setdefault(r["file_number"], []).append(r)
    # matter ids that receive each file number's votes
    vote_owner = {}
    for fn, v in vote_lookup.items():
        rows = by_fn.get(fn, [])
        # Votes are keyed by Legistar's file number as Legistar stores it, which
        # is sometimes not 9 digits ("20", "0023-2021"); only blank is skipped.
        if not fn or not rows:
            continue
        targets = rows if len(rows) == 1 else vote_target_rows(rows, v)
        for r in targets:
            vote_owner[r["matter_id"]] = fn
    out = []
    for r in csv_rows:
        rq = normalize_requester(r.get('requester',''), r.get('intro_date',''))
        fn = r["file_number"]
        # A scraped link is keyed by file number, so it is used only when the
        # file number is valid and belongs to this one row.
        unique_fn = valid_file_number(fn) and len(by_fn.get(fn, [])) == 1
        link = (legistar_links.get(fn) if unique_fn else None) or legistar_permalink(r.get("matter_id"))
        rec = {
            "t":           r["clean_title"],
            "tp":          normalize_topics(r["topic_tags"]),
            "a":           r["action_type_ai"],
            "g":           geo_by_address.get(r["matter_id"]) or normalize_geography(r["geography"]),
            "d":           r["intro_date"][:10],
            "y":           r["intro_date"][:4],
            "rq":          rq,
            "st":          r["status"],
            "sm":          r["summary"],
            "f":           fn,
            "mt":          r["matter_type"],
            "id":          r["matter_id"],
            "legistar_url": link,
        }
        vfn = vote_owner.get(r["matter_id"])
        if vfn:
            v = vote_lookup[vfn]
            rec["vote_yes"]     = v.get("yes_votes", [])
            rec["vote_no"]      = v.get("no_votes", [])
            rec["vote_abstain"] = v.get("abstain_votes", [])
            rec["vote_absent"]  = v.get("absent_votes", [])
            rec["vote_excused"] = v.get("excused_votes", [])
        out.append(rec)
    return out

# ─── SYNC HELPERS ─────────────────────────────────────────────────────────────

# Fields refreshed on rows that are already in the CSV. Titles, summaries,
# tags and sponsors are left alone (they are AI-generated or hand-corrected).
REFRESH_FIELDS = ["file_number", "matter_type", "body", "status", "intro_date",
                  "agenda_date", "passed_date", "enactment_number"]

def looks_like_body_name(status):
    """Legistar stores a committee name in the status field on some old
    matters (for example BUDGET AND FINANCE COMMITTEE). Not a real status."""
    return len(status) > 8 and status.isupper()

def refresh_row(row, m):
    """Copy changed fields from Legistar matter m into CSV row. Returns {field: (old, new)}."""
    changes = {}
    for f in REFRESH_FIELDS:
        new = (m.get(f) or "").strip()
        old = (row.get(f) or "").strip()
        if not new or new == old:
            continue
        if f == "status" and looks_like_body_name(new):
            continue
        row[f] = new
        changes[f] = (old, new)
    return changes

def tag_new_items(items):
    """Tag items with Claude (skipping low-value types). Mutates items.
    Returns (input_tokens, output_tokens)."""
    total_input_tokens = 0
    total_output_tokens = 0
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    to_tag = [item for item in items if not fixed_wording(item)]

    skipped = len(items) - len(to_tag)
    print(f"\nTagging {len(to_tag)} items with Claude ({skipped} filings worded from the Legistar title)...")

    total_batches = (len(to_tag) + BATCH_SIZE - 1) // BATCH_SIZE
    for batch_start in range(0, len(to_tag), BATCH_SIZE):
        batch = to_tag[batch_start:batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE
        print(f"  Batch {batch_num + 1}/{total_batches}: {len(batch)} items...", end="", flush=True)
        results, in_tok, out_tok = tag_batch(client, batch)
        total_input_tokens += in_tok
        total_output_tokens += out_tok
        cost_so_far = (total_input_tokens/1_000_000*TAG_INPUT_COST) + (total_output_tokens/1_000_000*TAG_OUTPUT_COST)
        print(f" ${cost_so_far:.3f} spent so far")
        for j, item in enumerate(batch):
            p = next((r for r in results if isinstance(r, dict) and r.get("i") == j), None) if isinstance(results, list) else None
            if p and "error" not in p:
                topic_tags = "|".join(p.get("tp", [])).replace("energy and sustainability", "environment and sustainability")
                action_type = p.get("a", "")
                if item['matter_type'] in ('Registration', 'Registration-Update'):
                    topic_tags, action_type = "registrations and terminations", "registration"
                item.update({
                    "clean_title":    p.get("t", ""),
                    "topic_tags":     topic_tags,
                    "action_type_ai": action_type,
                    "geography":      "|".join(p.get("g", [])),
                    "summary":        p.get("s", ""),
                    "tag_status":     "success"
                })
                mark_awaiting(item)
            else:
                # Fallback to single-item tagging
                tag_item(client, item)
                if item.get("tag_status") == "success":
                    mark_awaiting(item)
                if item.get("tag_status") != "success":
                    # AI tagging failed twice. Keep the matter on the site with its
                    # raw title and no tags rather than leaving it out.
                    reason = str(item.get("tag_status", ""))[:150]
                    print(f"    untagged: {item.get('file_number', '')} ({reason})")
                    item.update({"clean_title": item["raw_title"], "topic_tags": "",
                                 "action_type_ai": "other", "geography": "", "summary": "",
                                 "tag_status": "success"})
                    item["notes"] = ((item.get("notes") or "") + " " + UNTAGGED_MARK).strip()
        time.sleep(DELAY_BETWEEN_ITEMS)
    return total_input_tokens, total_output_tokens

UNTAGGED_MARK = "[auto-tag failed]"

def mark_awaiting(item):
    """Note in the row that its attachment text was not available when it was tagged,
    so a later run re-tags it once the attachment is posted."""
    if att.awaiting(item, ATT_CACHE) and att.AWAITING_MARK not in (item.get("notes") or ""):
        item["notes"] = ((item.get("notes") or "") + " " + att.AWAITING_MARK).strip()

def retag_awaiting(rows):
    """Re-tag rows marked as awaiting their attachment once its text is available.
    Returns (fixed, still_waiting)."""
    todo = [r for r in rows if att.AWAITING_MARK in (r.get("notes") or "")]
    if not todo:
        return 0, 0
    print(f"\nChecking attachments for {len(todo)} row(s) tagged before their attachment was posted...")
    att.ensure_text(todo, ATT_CACHE, API_BASE)
    ready = [r for r in todo if not att.awaiting(r, ATT_CACHE)]
    gone = [r for r in todo if not att.needs_attachment(r.get("raw_title", ""))]
    for r in gone:   # Legistar title was completed; the mark no longer applies
        r["notes"] = (r.get("notes") or "").replace(att.AWAITING_MARK, "").strip()
    if not ready:
        return len(gone), len(todo) - len(gone)
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    fixed = 0
    for r in ready:
        it = dict(r)
        tag_item(client, it)
        if it.get("tag_status") == "success" and (it.get("clean_title") or "").strip():
            for k in ("clean_title", "topic_tags", "action_type_ai", "geography", "summary"):
                r[k] = it.get(k, "")
            r["notes"] = (r.get("notes") or "").replace(att.AWAITING_MARK, "").strip()
            fixed += 1
            print(f"    re-tagged from attachment: {r.get('file_number', '')}: {r['clean_title']}")
        time.sleep(DELAY_BETWEEN_ITEMS)
    return fixed + len(gone), len(todo) - fixed - len(gone)

def attach_test(file_numbers):
    """Fetch attachment text for the given file numbers and print the title and description
    the model writes from it next to the current ones. Changes no files."""
    with open(EXISTING_CSV, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["file_number"] in set(file_numbers)]
    print(f"Attachment test: {len(rows)} of {len(file_numbers)} file numbers found in the CSV.")
    cache = {}
    for r in rows:
        cache[str(r["matter_id"])] = att.fetch_one(API_BASE, r["matter_id"])
        e = cache[str(r["matter_id"])]
        print(f"  {r['file_number']}: {e['status']} {e.get('name', '')} {e.get('source', '')} "
              f"{len(e.get('text', ''))} chars {e.get('error', '')}")
        if e.get("text"):
            print("    text start: " + re.sub(r"\s+", " ", e["text"])[:400])
    ATT_CACHE.clear(); ATT_CACHE.update(cache)
    if ANTHROPIC_API_KEY in ("", "YOUR_API_KEY_HERE"):
        print("ANTHROPIC_API_KEY not set; skipping the title test.")
        return
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    results, tin, tout = tag_batch(client, rows)
    for j, r in enumerate(rows):
        p = next((x for x in results if isinstance(x, dict) and x.get("i") == j), {})
        print(f"\n  {r['file_number']}\n    current t: {r['clean_title']}\n    current s: {r['summary']}"
              f"\n    new t:     {p.get('t', p.get('error', ''))}\n    new s:     {p.get('s', '')}")
    cost = tin / 1_000_000 * TAG_INPUT_COST + tout / 1_000_000 * TAG_OUTPUT_COST
    print(f"\nTokens in {tin}, out {tout}; cost ${cost:.4f} for {len(rows)} items "
          f"(${cost / max(len(rows), 1):.4f} per item).")
RETAG_LIMIT = 60   # untagged rows retried per run

def retag_untagged(rows):
    """Retry AI tagging for rows an earlier run left untagged (marked in notes).
    Rows that tag successfully get their title, tags, geography and summary filled
    in and the marker removed; the rest keep the marker and are tried next run.
    Returns (fixed, still_untagged)."""
    todo = [r for r in rows if UNTAGGED_MARK in (r.get("notes") or "")]
    if not todo:
        return 0, 0
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    batch = todo[:RETAG_LIMIT]
    print(f"\nRetrying AI tagging for {len(batch)} of {len(todo)} untagged rows...")
    fixed = 0
    for r in batch:
        it = dict(r)
        tag_item(client, it)
        if it.get("tag_status") == "success" and (it.get("clean_title") or "").strip():
            for k in ("clean_title", "topic_tags", "action_type_ai", "geography", "summary"):
                r[k] = it.get(k, "")
            r["notes"] = (r.get("notes") or "").replace(UNTAGGED_MARK, "").strip()
            r["tag_status"] = "success"
            fixed += 1
            print(f"    retagged: {r.get('file_number', '')}")
        else:
            print(f"    still untagged: {r.get('file_number', '')} ({str(it.get('tag_status', ''))[:120]})")
        time.sleep(DELAY_BETWEEN_ITEMS)
    return fixed, len(todo) - fixed

def before_site_start(intro_date):
    """True if intro_date (YYYY-MM-DD...) is earlier than SITE_START. A blank date is kept."""
    d = (intro_date or "").strip()[:10]
    return bool(d) and d < SITE_START

def load_excluded():
    try:
        with open(EXCLUDE_FILE, encoding="utf-8") as f:
            return {str(x) for x in json.load(f)}
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Update the Cincinnati Council site data from Legistar.")
    ap.add_argument("--full-sync", action="store_true",
                    help=f"compare every matter introduced since --since (default {FULL_SYNC_SINCE})")
    ap.add_argument("--since", default=FULL_SYNC_SINCE, help="start date for --full-sync, YYYY-MM-DD")
    ap.add_argument("--modified-days", type=int, default=MODIFIED_LOOKBACK_DAYS,
                    help=f"also pull matters modified in the last N days (default {MODIFIED_LOOKBACK_DAYS})")
    ap.add_argument("--dry-run", action="store_true",
                    help="fetch and compare only; write nothing except the sync_*.csv reports")
    ap.add_argument("--attach-test", default="",
                    help="comma-separated file numbers: fetch attachment text, print new titles, change nothing")
    args = ap.parse_args()

    if args.attach_test:
        attach_test([x.strip() for x in args.attach_test.split(",") if x.strip()])
        return

    today = datetime.today()
    cutoff = today - timedelta(days=LOOKBACK_DAYS)
    mod_cutoff = today - timedelta(days=args.modified_days)
    print(f"API: {API_BASE}")
    print(f"Mode: {'FULL SYNC since ' + args.since if args.full_sync else 'normal'}"
          f"{' (dry run)' if args.dry_run else ''}")

    # Load existing CSV
    print(f"\nLoading {EXISTING_CSV}...")
    with open(EXISTING_CSV, newline="", encoding="utf-8") as f:
        existing_rows = list(csv.DictReader(f))
    excluded = load_excluded()
    n_before = len(existing_rows)
    existing_rows = [r for r in existing_rows if r["matter_id"] not in excluded]
    removed_excluded = n_before - len(existing_rows)
    n_before = len(existing_rows)
    existing_rows = [r for r in existing_rows if not before_site_start(r.get("intro_date", ""))]
    removed_old = n_before - len(existing_rows)
    existing_ids = {r["matter_id"] for r in existing_rows}
    existing_files = {r["file_number"] for r in existing_rows}
    print(f"Existing records: {len(existing_rows)}")
    if removed_excluded:
        print(f"Removed {removed_excluded} rows listed in {EXCLUDE_FILE}.")
    if removed_old:
        print(f"Removed {removed_old} rows introduced before {SITE_START}.")

    # Fetch matters from the API
    fetched = {}          # matter_id -> matter
    complete = True
    if args.full_sync:
        print(f"\nFetching all matters introduced since {args.since}...")
        items, ok = fetch_matters(f"MatterIntroDate+ge+datetime'{args.since}T00:00:00'", "full sync")
        complete = complete and ok
        for m in items:
            fetched[m["matter_id"]] = m
    else:
        print(f"\nFetching matters introduced since {cutoff.strftime('%Y-%m-%d')}...")
        items, ok = fetch_matters(f"MatterIntroDate+ge+datetime'{odata_date(cutoff)}'", "introduced")
        complete = complete and ok
        for m in items:
            fetched[m["matter_id"]] = m
        print(f"Fetching matters modified since {mod_cutoff.strftime('%Y-%m-%d')}...")
        items, ok = fetch_matters(f"MatterLastModifiedUtc+ge+datetime'{odata_date(mod_cutoff)}'", "modified")
        complete = complete and ok
        for m in items:
            fetched.setdefault(m["matter_id"], m)
    print(f"Fetched {len(fetched)} distinct matters.")
    if not fetched:
        print("Nothing came back from Legistar; leaving the CSV and JSON unchanged.")
        if not complete:
            print("Legistar could not be reached. Stopping with an error so the run is flagged.")
            sys.exit(1)

    # Split into refresh (already in CSV) and new
    row_by_id = {r["matter_id"]: r for r in existing_rows}
    new_matters, refreshed_rows, change_log = [], 0, []
    field_counts = {}
    skipped_old = []
    for mid, m in fetched.items():
        if mid in excluded:
            continue
        if before_site_start(m.get("intro_date", "")):
            skipped_old.append(m)
            continue
        row = row_by_id.get(mid)
        if row is None:
            new_matters.append(m)
            continue
        ch = refresh_row(dict(row) if args.dry_run else row, m)
        if ch:
            refreshed_rows += 1
            for fld, (o, n) in ch.items():
                field_counts[fld] = field_counts.get(fld, 0) + 1
                change_log.append((m["file_number"], mid, fld, o, n))

    # Legistar keeps old duplicate records (status "Historical" or a committee name)
    # under file numbers the CSV already has. They repeat an item the site already
    # shows, so they are skipped.
    reused = [m for m in new_matters if m["file_number"] and m["file_number"] in existing_files]
    reused_ids = {m["matter_id"] for m in reused}
    new_matters = [m for m in new_matters if m["matter_id"] not in reused_ids]
    print(f"\nAlready in CSV, fields changed on Legistar: {refreshed_rows}")
    for fld in REFRESH_FIELDS:
        if field_counts.get(fld):
            print(f"    {fld}: {field_counts[fld]}")
    if skipped_old:
        print(f"Skipped {len(skipped_old)} matter(s) introduced before {SITE_START}: "
              + ", ".join(f"{m.get('file_number') or m['matter_id']} ({m.get('intro_date', '')})" for m in skipped_old[:20]))
    print(f"Not in CSV yet (to add): {len(new_matters)}"
          + (f"  ({len(reused)} more skipped: file number already in the CSV)" if reused else ""))

    # Rows in the CSV that Legistar did not return (full sync only, and only if every page loaded)
    missing_on_legistar = []
    if args.full_sync and complete and fetched:
        missing_on_legistar = [r for r in existing_rows
                               if r.get("intro_date", "") >= args.since and r["matter_id"] not in fetched]
        print(f"In CSV but not returned by Legistar: {len(missing_on_legistar)} (reported, not deleted)")
        for r in missing_on_legistar[:50]:
            print(f"    {r.get('file_number') or '(no file number)'}  id {r['matter_id']}  {r.get('intro_date', '')}  "
                  f"[{r.get('status', '')}]  {r.get('clean_title', '')[:60]}")
    elif args.full_sync and not complete:
        print("Full sync did not finish every page; skipping the 'not on Legistar' comparison.")

    # Reports
    if change_log or new_matters or missing_on_legistar:
        if change_log:
            with open("sync_changes.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["file_number", "matter_id", "field", "old", "new"])
                w.writerows(change_log)
            print("Wrote sync_changes.csv")
        if missing_on_legistar:
            write_csv("sync_not_on_legistar.csv", missing_on_legistar)
            print("Wrote sync_not_on_legistar.csv")

    if args.dry_run:
        print("\nDry run: no changes made to the CSV or JSON.")
        return

    total_input_tokens = total_output_tokens = 0
    changed = bool(refreshed_rows) or removed_excluded > 0 or removed_old > 0
    if new_matters:
        if ANTHROPIC_API_KEY in ("", "YOUR_API_KEY_HERE"):
            print("\nANTHROPIC_API_KEY is not set: the new matters were NOT added. "
                  "Status refreshes are still saved.")
            new_matters = []
        else:
            ATT_CACHE.update(att.load_cache())
            stubs = [m for m in new_matters if att.needs_attachment(m.get("raw_title", ""))]
            if stubs:
                print(f"\nFetching attachment text for {len(stubs)} new item(s) whose title stops short...")
                att.ensure_text(stubs, ATT_CACHE, API_BASE)
            total_input_tokens, total_output_tokens = tag_new_items(new_matters)
            ok_new = [m for m in new_matters if m.get("tag_status") == "success"]
            print(f"\n{len(ok_new)}/{len(new_matters)} new items tagged successfully.")
            new_matters = ok_new
            changed = changed or bool(new_matters)

    if ANTHROPIC_API_KEY not in ("", "YOUR_API_KEY_HERE"):
        retagged, still_untagged = retag_untagged(existing_rows + new_matters)
        if retagged:
            changed = True
        if not ATT_CACHE:
            ATT_CACHE.update(att.load_cache())
        n_cache = len(ATT_CACHE)
        fixed_att, waiting_att = retag_awaiting(existing_rows + new_matters)
        if fixed_att:
            changed = True
        if waiting_att:
            print(f"{waiting_att} row(s) still await attachment text; checked again on the next run.")
        if ATT_CACHE and (len(ATT_CACHE) != n_cache or fixed_att or new_matters):
            att.save_cache(ATT_CACHE)
        if still_untagged:
            print(f"{still_untagged} row(s) are still untagged; they are retried on the next run.")

    if changed or not os.path.exists(OUTPUT_CSV):
        # Write the tagged-only CSV (keeps the GitHub copy small)
        all_rows = existing_rows + new_matters
        tagged_rows = [r for r in all_rows if r.get("tag_status") == "success"]
        write_csv(OUTPUT_CSV, tagged_rows)
        size_mb = os.path.getsize(OUTPUT_CSV) / 1024 / 1024
        print(f"CSV updated: {len(tagged_rows)} rows ({len(new_matters)} added, "
              f"{refreshed_rows} refreshed), {size_mb:.1f} MB")
    else:
        print("\nNo changes to the CSV.")

    # Scrape Legistar links for recent meetings
    print(f"\nFetching recent meeting URLs from API...")
    link_cutoff = min(cutoff, mod_cutoff)
    try:
        event_urls = fetch_recent_event_urls(link_cutoff)
    except Exception as e:
        print(f"  Could not list meetings ({e}); keeping existing links.")
        event_urls = []
    print(f"Found {len(event_urls)} recent meetings. Scraping for legislation links...")

    # Load existing link map from JSON
    link_map = {}
    try:
        with open(OUTPUT_JSON) as f:
            existing_json = json.load(f)
        for r in existing_json:
            if not r.get('_meta') and r.get('f') and r.get('legistar_url') and 'gateway.aspx' not in r['legistar_url']:
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

    # Print tagging cost if any tagging happened
    if total_input_tokens or total_output_tokens:
        actual_cost = (total_input_tokens/1_000_000*TAG_INPUT_COST) + (total_output_tokens/1_000_000*TAG_OUTPUT_COST)
        print(f"Tagging cost this run: ${actual_cost:.3f} ({total_input_tokens:,} input tokens, {total_output_tokens:,} output tokens)")

    # Load vote data
    vote_lookup = {}
    try:
        with open(VOTES_FILE) as f:
            votes_data = json.load(f)
        vote_lookup = {k: v for k, v in votes_data.items() if not k.startswith("_")}
        print(f"Loaded {len(vote_lookup)} vote records from {VOTES_FILE}")
    except:
        print(f"No {VOTES_FILE} found — votes will not be included")

    # Appointment and Reappointment wording from the Legistar title. Runs before
    # the manual overrides below, so a later manual fix wins and is kept.
    try:
        with open(OUTPUT_CSV, newline="", encoding="utf-8") as f:
            appt_rows = list(csv.DictReader(f))
        reworded = 0
        for row in appt_rows:
            if (row.get("matter_type") in ("Appointment", "Reappointment")
                    and APPOINTMENT_MARK not in (row.get("notes") or "")):
                res = appointment_text(row["matter_type"], row.get("raw_title", ""))
                if res:
                    row["clean_title"], row["summary"] = res
                    row["notes"] = ((row.get("notes") or "") + " " + APPOINTMENT_MARK).strip()
                    reworded += 1
        if reworded:
            with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(appt_rows)
        print(f"Appointment wording applied to {reworded} row(s).")
    except Exception as e:
        print(f"Appointment wording skipped ({e}).")

    # Registration, financial disclosure and successor wording from the Legistar
    # title (see FILING WORDING). Also before the manual overrides.
    try:
        with open(OUTPUT_CSV, newline="", encoding="utf-8") as f:
            filing_rows = list(csv.DictReader(f))
        nm = load_filing_names()
        reworded = kept = 0
        for row in filing_rows:
            if row.get("matter_type") in FILING_TYPES and FILING_MARK not in (row.get("notes") or ""):
                res = filing_text(row["matter_type"], row.get("raw_title", ""), nm)
                if res:
                    row["clean_title"], row["summary"] = res
                    row["notes"] = ((row.get("notes") or "") + " " + FILING_MARK).strip()
                    reworded += 1
                else:
                    kept += 1
        if reworded:
            with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(filing_rows)
        print(f"Filing wording applied to {reworded} row(s); {kept} in other forms keep their text.")
    except Exception as e:
        print(f"Filing wording skipped ({e}).")

    # Apply any pending manual title overrides (queued by the suggestion
    # review page) into the CSV so the fix survives this rebuild instead of
    # only living in council_data.json until the next run overwrites it.
    # Matched entries are consumed (removed) from TITLE_OVERRIDES_FILE;
    # unmatched ones are left pending in case the row shows up later.
    try:
        with open(TITLE_OVERRIDES_FILE) as f:
            pending_overrides = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pending_overrides = {}

    if pending_overrides:
        with open(OUTPUT_CSV, newline="", encoding="utf-8") as f:
            all_csv_rows = list(csv.DictReader(f))
        applied = []
        for row in all_csv_rows:
            fn = row.get("file_number", "")
            if fn in pending_overrides:
                row["clean_title"] = pending_overrides[fn]
                applied.append(fn)
        if applied:
            with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(all_csv_rows)
            print(f"Applied {len(applied)} pending title override(s): {', '.join(applied)}")
        remaining = {k: v for k, v in pending_overrides.items() if k not in applied}
        if remaining != pending_overrides:
            with open(TITLE_OVERRIDES_FILE, "w", encoding="utf-8") as f:
                json.dump(remaining, f, indent=2)
        if remaining:
            print(f"{len(remaining)} title override(s) still pending (file number not in CSV yet): {', '.join(remaining)}")

    # Apply any pending manual description (summary) overrides — same pattern
    # as the title overrides above, but writing to the CSV's "summary" column
    # and consuming entries from SUMMARY_OVERRIDES_FILE instead.
    try:
        with open(SUMMARY_OVERRIDES_FILE) as f:
            pending_summary_overrides = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pending_summary_overrides = {}

    if pending_summary_overrides:
        with open(OUTPUT_CSV, newline="", encoding="utf-8") as f:
            all_csv_rows = list(csv.DictReader(f))
        applied = []
        for row in all_csv_rows:
            fn = row.get("file_number", "")
            if fn in pending_summary_overrides:
                row["summary"] = pending_summary_overrides[fn]
                applied.append(fn)
        if applied:
            with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(all_csv_rows)
            print(f"Applied {len(applied)} pending description override(s): {', '.join(applied)}")
        remaining = {k: v for k, v in pending_summary_overrides.items() if k not in applied}
        if remaining != pending_summary_overrides:
            with open(SUMMARY_OVERRIDES_FILE, "w", encoding="utf-8") as f:
                json.dump(remaining, f, indent=2)
        if remaining:
            print(f"{len(remaining)} description override(s) still pending (file number not in CSV yet): {', '.join(remaining)}")

    # Rebuild JSON from tagged rows only
    print(f"\nRebuilding {OUTPUT_JSON}...")
    with open(OUTPUT_CSV, newline="", encoding="utf-8") as f:
        final_rows = [r for r in csv.DictReader(f) if r.get("tag_status") == "success"]

    try:
        geo_by_address = address_geography(final_rows)
        print(f"Neighborhood from address map: {len(geo_by_address)} records.")
    except Exception as e:
        geo_by_address = {}
        print(f"Address neighborhoods skipped ({e}); AI tags used.")
    json_records = build_json(final_rows, link_map, vote_lookup, geo_by_address)
    # UTC, so the value is the same wherever the pipeline runs; the pages convert it to Eastern time.
    meta = {'_meta': True, 'last_updated': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}
    output = [meta] + json_records

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, separators=(",", ":"))

    size = len(json.dumps(output, separators=(",", ":"))) / 1024
    print(f"Done. {OUTPUT_JSON} written ({size:.0f} KB)")
    print(f"\nNext step: upload {OUTPUT_JSON} to GitHub.")

    # Meetings for agenda.html. A failure here leaves the previous agenda.json in place.
    try:
        write_agenda(final_rows, vote_lookup, geo_by_address)
    except Exception as e:
        print(f"Could not build {AGENDA_FILE} ({e}); keeping the existing file.")
    try:
        write_agents(final_rows)
    except Exception as e:
        print(f"Could not build {AGENTS_FILE} ({e}); keeping the existing file.")

# ─── MEETINGS (agenda.json, agenda_YYYY.json) ─────────────────────────────────
# Meetings are kept in one file per year from AGENDA_ARCHIVE_START_YEAR. A year
# file that does not exist yet is read from Legistar in full (a one-time
# backfill). After that, each run re-reads only meetings from AGENDA_RECHECK_DAYS
# back to AGENDA_AHEAD_DAYS ahead, because actions are posted after a meeting.
# agenda.json holds the short window shown by default on agenda.html.

def clock_minutes(t):
    """Minutes after midnight for Legistar times such as "9:30 AM". Unparsed times sort last."""
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*([AaPp])\.?[Mm]\.?\s*$", t or "")
    if not m:
        return 24 * 60
    h = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "p" else 0)
    return h * 60 + int(m.group(2))

def fetch_meetings(start, end):
    """Legistar meetings with EventDate in [start, end) (YYYY-MM-DD) and their matter items.
    Items keep the Legistar title start in "lt"; titles are set later by title_items()."""
    url = (f"{API_BASE}/events?$filter=EventDate+ge+datetime'{start}T00:00:00'"
           f"+and+EventDate+lt+datetime'{end}T00:00:00'&$orderby=EventDate")
    events = json.loads(http_get_text(url, {"Accept": "application/json"}))
    meetings = []
    for e in events:
        eid = e.get("EventId")
        meetings.append({
            "id":       eid,
            "body":     (e.get("EventBodyName") or "").strip(),
            "date":     (e.get("EventDate") or "")[:10],
            "time":     (e.get("EventTime") or "").strip(),
            "location": (e.get("EventLocation") or "").strip(),
            "agenda_status": e.get("EventAgendaStatusName") or "",
            "url":      e.get("EventInSiteURL") or "",
            "comment":  event_comment(e),
            "items":    fetch_items(eid),
        })
    return meetings

def fetch_items(eid):
    """Matter items of one Legistar meeting, in agenda order. Lines with no matter
    (roll call, prayer, minutes) are left out."""
    items = json.loads(http_get_text(f"{API_BASE}/events/{eid}/eventitems",
                                     {"Accept": "application/json"}))
    time.sleep(DELAY_BETWEEN_ITEMS)
    kept = []
    for it in sorted(items, key=lambda i: i.get("EventItemAgendaSequence") or 0):
        if not it.get("EventItemMatterId"):
            continue
        kept.append({
            "n":      (it.get("EventItemAgendaNumber") or "").strip(),
            "id":     str(it["EventItemMatterId"]),
            "f":      it.get("EventItemMatterFile") or "",
            "mt":     it.get("EventItemMatterType") or "",
            "lt":     " ".join((it.get("EventItemTitle") or "").split())[:160],
            "action": it.get("EventItemActionName") or "",
            "pf":     it.get("EventItemPassedFlagName") or "",   # "Pass", "Fail" or ""
        })
    return kept

def event_comment(e):
    """Legistar's note on a meeting: "NOTICE OF CANCELLATION", "SPECIAL MEETING", etc."""
    return " ".join((e.get("EventComment") or "").split())

def vote_counts(v):
    """[yes, no, abstain, absent, excused] from a votes_api.json record."""
    return [len(v.get(k) or []) for k in
            ("yes_votes", "no_votes", "abstain_votes", "absent_votes", "excused_votes")]

def title_items(meetings, by_id, geo_by_address, vote_lookup):
    """Set t, sm, on_site, url, g and votes on each item. t is the site's short title when
    the matter is on the site, else the start of Legistar's title (kept in lt). sm is the
    site's one-line summary (on-site matters with a summary only). g is the site's
    neighborhood value. votes is the roll call count from votes_api.json when that vote
    was taken at this meeting (full Council only)."""
    for m in meetings:
        for it in m["items"]:
            row = by_id.get(it["id"])
            if row and row.get("clean_title"):
                it["t"] = row["clean_title"]
                it["on_site"] = True
                it.pop("lt", None)            # Legistar title not needed once on the site
                it["g"] = geo_by_address.get(it["id"]) or normalize_geography(row.get("geography", ""))
                sm = (row.get("summary") or "").strip()
                if sm:
                    it["sm"] = sm
                else:
                    it.pop("sm", None)
            else:
                it["t"] = it.get("lt") or it.get("t", "")
                it["on_site"] = False
                it.pop("g", None)
                it.pop("sm", None)
            it["url"] = legistar_permalink(it["id"])
            v = vote_lookup.get(it["f"]) if it.get("f") else None
            # Roll calls in votes_api.json are from full Council meetings only; a committee
            # meeting held the same day must not show them.
            if (v and m["body"] == "Cincinnati City Council" and v.get("meeting_date") == m["date"]
                    and (not v.get("matter_id") or v["matter_id"] == it["id"])):
                it["votes"] = vote_counts(v)
            else:
                it.pop("votes", None)
    meetings.sort(key=lambda m: (m["date"], clock_minutes(m["time"]), m["body"]))

def agenda_year_file(year):
    return f"agenda_{year}.json"

def write_agenda(rows, vote_lookup=None, geo_by_address=None):
    from zoneinfo import ZoneInfo
    vote_lookup = vote_lookup or {}
    geo_by_address = geo_by_address or {}
    today = datetime.now(ZoneInfo("America/New_York")).date()
    by_id = {r["matter_id"]: r for r in rows}
    years = {}
    for y in range(AGENDA_ARCHIVE_START_YEAR, today.year + 1):
        path = agenda_year_file(y)
        old = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                old = json.load(f)
            if old.get("format", 1) >= AGENDA_FORMAT:
                years[y] = old["meetings"]
                continue
        # Missing or older-format year: read it in full. On failure keep the old file.
        try:
            years[y] = fetch_meetings(f"{y}-01-01", f"{y + 1}-01-01")
            print(f"Meetings {y}: read {len(years[y])} from Legistar (backfill).")
        except Exception as e:
            print(f"Meetings {y}: backfill failed ({e}); retried next run.")
            if old:
                years[y] = old["meetings"]
    # Re-read the recent and upcoming window and replace those meetings.
    w_start = (today - timedelta(days=AGENDA_RECHECK_DAYS)).isoformat()
    w_end = (today + timedelta(days=AGENDA_AHEAD_DAYS + 1)).isoformat()
    fresh = fetch_meetings(w_start, w_end)
    for y in {int(w_start[:4]), int(w_end[:4])}:
        if y not in years and y >= AGENDA_ARCHIVE_START_YEAR:
            years[y] = []
    for y in list(years):
        keep = [m for m in years[y] if not (w_start <= m["date"] < w_end)]
        years[y] = keep + [m for m in fresh if m["date"][:4] == str(y)]
    # Past meetings (within AGENDA_PENDING_DAYS) whose items have no recorded action:
    # the Clerk had not entered the actions when the meeting was last read. Re-read
    # their items each run until actions appear.
    p_start = (today - timedelta(days=AGENDA_PENDING_DAYS)).isoformat()
    pending = [m for y in years for m in years[y]
               if p_start <= m["date"] < w_start and m["items"]
               and not re.search("cancel", m.get("comment", ""), re.I)
               and not any(it.get("action") for it in m["items"])]
    filled = 0
    for m in pending:
        try:
            m["items"] = fetch_items(m["id"])
            filled += any(it.get("action") for it in m["items"])
        except Exception as e:
            print(f"Meeting {m['id']} ({m['date']}): could not re-read items ({e}).")
    if pending:
        print(f"Re-read {len(pending)} past meeting(s) with no recorded actions; {filled} now have actions.")
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    index = []
    for y in sorted(years):
        title_items(years[y], by_id, geo_by_address, vote_lookup)
        fmt = AGENDA_FORMAT if all("pf" in it for m in years[y] for it in m["items"]) else 1
        with open(agenda_year_file(y), "w", encoding="utf-8") as f:
            json.dump({"year": y, "format": fmt, "generated_utc": gen, "meetings": years[y]},
                      f, separators=(",", ":"))
        index.append({"year": y, "meetings": len(years[y]),
                      "items": sum(len(m["items"]) for m in years[y])})
    with open(AGENDA_INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump({"generated_utc": gen, "years": index}, f, separators=(",", ":"))
    # Default view: AGENDA_PAST_DAYS back to AGENDA_AHEAD_DAYS ahead.
    d_start = (today - timedelta(days=AGENDA_PAST_DAYS)).isoformat()
    d_end = (today + timedelta(days=AGENDA_AHEAD_DAYS)).isoformat()
    window = [dict(m, upcoming=m["date"] >= today.isoformat())
              for y in sorted(years) for m in years[y] if d_start <= m["date"] <= d_end]
    with open(AGENDA_FILE, "w", encoding="utf-8") as f:
        json.dump({"generated_utc": gen, "from": d_start, "to": d_end, "meetings": window},
                  f, separators=(",", ":"))
    print(f"{AGENDA_FILE}: {len(window)} meetings; year files: "
          + ", ".join(f"{i['year']} ({i['meetings']})" for i in index))

# ─── LEGISLATIVE AGENTS (agents.json) ─────────────────────────────────────────
# Built from the Registration and Registration-Update rows of the CSV. Legistar's
# title for each filing reads "... from Legislative Agent <name>, <role>, <firm>,
# <address>. (<CLIENT>)". The agent is the text after "Legislative Agent" up to
# the first comma; the client is the parenthetical after the ZIP code (some
# filings name two). Names are merged with agent_aliases.json and
# org_aliases.json, reviewed by the council office. A span of representation
# runs from a registration to its termination, or to its expiration under CMC
# 112-5(e): the last business day of each odd-numbered year, unless a new
# registration was filed before then. Updates do not renew a registration.

AGENTS_FILE = "agents.json"
AGENT_ALIASES_FILE = "agent_aliases.json"
ORG_ALIASES_FILE = "org_aliases.json"
AGENT_FIRMS_ORDER = ["Government Strategies Group", "DSD Advisors",
                     "Taft / Focused Capital Solutions", "Firm not identified"]
_PAREN_SKIP = re.compile(r"^(UPDATED|TERMINATION|EMPLOYER|UPDATE|TERMINATED|AMENDED)$", re.I)
_ORG_SMALL_WORDS = {"of", "the", "and", "in", "for", "&", "to", "at", "on", "a", "an", "by", "with"}

def filing_agent(title):
    m = (re.search(r"Legislative (?:Agents?\s*[,:]?\s*)?([^,(]+)", title, re.I)
         or re.search(r"submitted by (?:the Clerk of Council from )?([^,(]+)", title, re.I))
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""

def filing_clients(title):
    """Client names in a filing title, and whether the filing is a termination."""
    t = title.strip()
    m = re.search(r"\d{5}(?:-\d{4})?\.?\s*(.*)$", t)
    tail = m.group(1) if m else t
    term = bool(re.search(r"\(TERMINAT|TERMINATION\)", t, re.I))
    out = []
    for p in (p.strip() for p in re.findall(r"\(([^()]*)\)?", tail)):
        if not p or _PAREN_SKIP.match(p):
            continue
        mm = re.match(r"termination\s*-\s*(.+)", p, re.I)
        if mm:
            p, term = mm.group(1).strip(), True
        out.append(p)
    return out, term

def org_key(name):
    k = name.lower().replace("’", "'").replace(" and ", " & ").replace("&", " & ")
    k = re.sub(r"[.,]", " ", k)
    k = re.sub(r"\b(llc|inc|corp|corporation|company|co)\b", " ", k)
    k = re.sub(r"^the\s+", "", k)
    return re.sub(r"\s+", " ", k).strip()

def filing_firm(title, agent, date, firm_from):
    rule = firm_from.get(agent)
    if rule and date >= rule[0]:
        return rule[1]
    if re.search(r"Government Strateg|Development Strategies|700 Walnut", title, re.I):
        return "Government Strategies Group"
    if re.search(r"DSD Advisors", title) or (re.search(r"Suite 1900", title)
                                             and re.search(r"2[25]5 E(ast|\.)?\s*(5th|Fifth)", title, re.I)):
        return "DSD Advisors"
    if re.search(r"Focused Capi", title, re.I):
        return "Taft / Focused Capital Solutions"
    return "Firm not identified"

def org_display(name, keep_upper, fixes):
    """All-caps names as filed are converted to title case; others are kept."""
    if name == name.upper() and re.search("[A-Z]", name):
        words = []
        for i, w in enumerate(name.split(" ")):
            if w.strip(",.") in keep_upper or re.search(r"\d", w):
                words.append(w)
            elif w.lower() in _ORG_SMALL_WORDS and i > 0:
                words.append(w.lower())
            else:
                words.append("-".join("/".join(p[:1].upper() + p[1:].lower() for p in s.split("/"))
                                      for s in w.split("-")))
        name = " ".join(words)
        name = re.sub(r"(\w)['’](S)\b", lambda m: m.group(1) + "’s", name)
        name = re.sub(r"\bO['’]r", "O’R", name)
    return fixes.get(name, name)

def registration_expiry(date):
    """Last business day of the odd-numbered year on or after the registration date."""
    y = int(date[:4])
    y = y if y % 2 else y + 1
    d = datetime(y, 12, 31).date()
    while d.weekday() > 4:
        d -= timedelta(days=1)
    return d.isoformat()

def agent_spans(filings, today):
    """filings: one agent's filings for one organization, oldest first.
    Returns [start, end or None, status, firm, last filing]; status T terminated,
    E expired, O open, N termination with no registration found."""
    spans, cur, seen = [], None, False
    for x in filings:
        is_reg = x["type"] == "Registration" and not x["term"]
        if cur and x["date"] > registration_expiry(cur["reg"]):
            spans.append([cur["start"], registration_expiry(cur["reg"]), "E", cur["firm"], cur["last"]])
            cur = None
        if cur is None:
            if x["term"]:
                if not seen:
                    spans.append([x["date"], x["date"], "N", x["firm"], x["date"]])
                    seen = True
                continue
            if is_reg or not seen:
                cur = {"start": x["date"], "reg": x["date"], "firm": x["firm"], "last": x["date"]}
                seen = True
            continue
        cur["last"], cur["firm"] = x["date"], x["firm"]
        if x["term"]:
            spans.append([cur["start"], x["date"], "T", cur["firm"], x["date"]])
            cur = None
        elif is_reg:
            cur["reg"] = x["date"]
    if cur:
        exp = registration_expiry(cur["reg"])
        spans.append([cur["start"], exp, "E", cur["firm"], cur["last"]] if exp < today
                     else [cur["start"], None, "O", cur["firm"], cur["last"]])
    return spans

def write_agents(rows):
    from zoneinfo import ZoneInfo
    with open(AGENT_ALIASES_FILE, encoding="utf-8") as f:
        aa = json.load(f)
    with open(ORG_ALIASES_FILE, encoding="utf-8") as f:
        oa = json.load(f)
    agent_alias = {v: k for k, vs in aa["names"].items() for v in vs}
    not_agents = set(aa.get("not_agents", []))
    firm_from = aa.get("firm_from", {})
    org_alias = {v: k for k, vs in oa["names"].items() for v in vs}
    not_orgs = set(oa.get("not_orgs", []))
    keep_upper = set(oa.get("keep_upper", []))
    fixes = oa.get("display", {})
    today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()

    filings = defaultdict(lambda: defaultdict(list))
    spellings = defaultdict(Counter)
    latest = {}
    skipped = Counter()
    regs = [r for r in rows if r.get("matter_type") in ("Registration", "Registration-Update")]
    for r in sorted(regs, key=lambda r: (r.get("intro_date", ""), r.get("file_number", ""))):
        title = r.get("raw_title", "")
        clients, term = filing_clients(title)
        agent = filing_agent(title)
        if not clients:
            skipped["no client named"] += 1
            continue
        if not agent or agent in not_agents:
            skipped["no agent named"] += 1
            continue
        agent = agent_alias.get(agent, agent)
        date = r.get("intro_date", "")[:10]
        firm = filing_firm(title, agent, date, firm_from)
        done = set()
        for c in clients:
            if c in not_orgs:
                skipped["client is not an organization"] += 1
                continue
            g = org_alias.get(org_key(c), org_key(c))
            if g in done:
                continue
            done.add(g)
            spellings[g][c] += 1
            filings[g][agent].append({"date": date, "type": r.get("matter_type"), "term": term, "firm": firm})
            latest[g] = r.get("matter_id", "")

    def display(g):
        if g in oa["names"]:
            return g
        c = spellings[g]
        mixed = [v for v in c if v != v.upper()]
        best = max(mixed, key=lambda v: c[v]) if mixed else max(c, key=lambda v: c[v])
        return org_display(best, keep_upper, fixes)

    orgs = []
    for g, by_agent in filings.items():
        orgs.append({"n": display(g), "u": legistar_permalink(latest[g]),
                     "a": [[a, agent_spans(xs, today)] for a, xs in sorted(by_agent.items())]})
    orgs.sort(key=lambda o: o["n"].lower())
    out = {"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
           "as_of": today, "firms": AGENT_FIRMS_ORDER, "orgs": orgs}
    with open(AGENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
    print(f"{AGENTS_FILE}: {len(orgs)} organizations from {len(regs)} registration filings; skipped "
          + ", ".join(f"{k} {v}" for k, v in sorted(skipped.items())))

# ─── APPOINTMENT WORDING ──────────────────────────────────────────────────────
# Appointment and Reappointment titles and descriptions are built from the
# Legistar title in one form: "Appoint <name> to the <board>" and "<Mayor or
# City Manager> appoints <name> to the <board> for <term>, subject to Council's
# advice and consent." Applied once per row (marked in notes); titles that do
# not follow a recognized form keep the AI wording.

APPOINTMENT_MARK = "[appointment wording]"
# Where the board name ends: a term, a seat or role description, or the end of the sentence.
_APPT_BODY_END = (r"(?=,?\s+(?:to\s+fill|to\s+complete|under\s+the|pursuant|representing|in\s+the\s+seat"
             r"|in\s+the\s+role|replacing|who\s+will|which\s+shall|having\s+been|as\s+(?:the|a|an)\b"
             r"|to\s+a\s|to\s+the\s+Cincinnati\s+(?:Administration|City\s+Council)|a\s+term|serving\b"
             r"|for\b|to\s+serve\b|with\s+(?:a|an)\b|effective\b|beginning\b|commencing\b|through\b"
             r"|until\b|ending\b)|\.\s|\.$|\s*\((?:Male|Female)|$)")
_APPT_PATTERNS = [
    # "I hereby appoint NAME as a citizen member of the BODY ..."
    re.compile(r"I\s+hereby\s+(?:re)?appoint(?:ment|ed|s)?\s+(?P<name>.+?)\s+as\s+(?:a|an|the)\s+[^,]*?\bmember\s+of\s+(?:the\s+)?(?P<body>.+?)" + _APPT_BODY_END, re.I),
    # Mayor or City Manager: "I hereby appoint NAME to the BODY for a term ..."
    re.compile(r"I\s+hereby\s+(?:re)?appoint(?:ment|ed|s)?\s+(?P<name>.+?)\s+(?:as\s+(?:the\s+)?(?:City[’']s\s+)?(?:representative|member|director|trustee)\s+)?(?:to|on)\s+(?:the\s+)?(?P<body>.+?)" + _APPT_BODY_END, re.I),
    # Council motion: "City Council hereby appoints NAME to the BODY for ..."
    re.compile(r"hereby\s+(?:re)?appoints\s+(?P<name>.+?)\s+(?:to|on)\s+(?:the\s+)?(?P<body>.+?)" + _APPT_BODY_END, re.I),
    # "WE MOVE that NAME, representing ORG, be appointed to the BODY for ..."
    re.compile(r"WE\s+MOVE\s+that\s+(?P<name>[^,]+?)(?:,\s+representing\s+[^,]+?)?(?:,[^,]*?)?,?\s+be\s+(?:re)?appointed\s+to\s+(?:the\s+)?(?P<body>.+?)" + _APPT_BODY_END, re.I),
    # City Manager memo: "appointing NAME to the BODY"
    re.compile(r"(?:appointing|appointment\s+of)\s+(?P<name>.+?)\s+to\s+(?:the\s+)?(?P<body>.+?)" + _APPT_BODY_END, re.I),
]
_APPT_TERM = re.compile(r"(?:for|with)\s+(?:a|an)\s+(?:term|terms|(?:one|two|three|four|five|six)[- ]year\s+term|unexpired\s+term)[^.(]*", re.I)
_APPT_SKIP = re.compile(r"resignation|vice\s+mayor\s+of|interim\s+replacement|deputy\s+clerk|committee\s+chairs", re.I)

def _appt_clean(s):
    s = re.sub(r"\s*\([^)]*\)", "", s)
    return re.sub(r"\s+", " ", s).strip(" ,.;")

def appointment_text(matter_type, raw_title):
    """(title, summary) for an Appointment or Reappointment, or None when the
    Legistar title does not follow a recognized form."""
    t = re.sub(r"\s+", " ", raw_title or "")
    if _APPT_SKIP.search(t):
        return None
    for p in _APPT_PATTERNS:
        m = p.search(t)
        if not m:
            continue
        name, raw_body = _appt_clean(m.group("name")), m.group("body")
        body = _appt_clean(raw_body)
        ab = re.search(r"\(([^)]*)\)\s*(.*)$", raw_body)
        if ab and len(body) > 70 and ab.group(1).strip():   # very long names with an acronym
            body = ("Cincinnati " if raw_body.startswith("Cincinnati") else "") + _appt_clean(ab.group(1) + " " + ab.group(2))
        if (not name or not body or len(name) < 4 or len(name.split()) > 7 or len(body) > 90
                or re.match(r"(represent|serve|act|position)\b", body, re.I) or " to the " in body):
            continue
        body = body[:1].upper() + body[1:]
        verb = "Reappoint" if matter_type == "Reappointment" else "Appoint"
        title = f"{verb} {name} to the {body}"
        tm = _APPT_TERM.search(t, m.end("body"))
        term = (" " + _appt_clean(tm.group(0))) if tm else ""
        sub = re.search(r"submitted\s+by\s+(Mayor\s+[A-Z][\w.]*(?:\s+[A-Z][\w.]*)?\s+[A-Z][\w'-]+"
                        r"|Councilmembers?\s+[^,]+|[^,]+,\s+(?:Interim\s+)?City\s+Manager)", t)
        who = sub.group(1).strip() if sub else ""
        if who.endswith("City Manager"):
            nm, role = who.rsplit(",", 1)
            who = f"{role.strip()} {nm.strip()}"
        if who.startswith("Councilmember"):
            summary = f"Motion by {who} to {verb.lower()} {name} to the {body}{term}."
        elif who:
            act = "reappoints" if verb == "Reappoint" else "appoints"
            summary = f"{who} {act} {name} to the {body}{term}, subject to Council's advice and consent."
        else:
            summary = f"{verb}s {name} to the {body}{term}."
        return title, summary
    return None

# ─── FILING WORDING ───────────────────────────────────────────────────────────
# Legislative Agent registrations, financial disclosure statements and successor
# designations are not sent to the AI. Their titles and descriptions are built
# from the Legistar title in fixed forms:
#   "Legislative Agent registration: <agent> for <client>" /
#       "<agent> registers as a Legislative Agent for <client>."
#   (update: "registration update" / "updates a Legislative Agent registration for";
#    termination: "termination" / "ends a Legislative Agent registration for")
#   "Financial disclosure statement: <name>" /
#       "The Clerk of Council files the financial disclosure statement of <name>, <position>."
#   "Successor designation certificate for <name>" and similar.
# Agent and client names use the same parsing and merges as the Legislative
# Agents page. Applied once per row (marked in notes) before the manual overrides,
# so a later manual fix wins and is kept. Titles in other forms keep their text.

FILING_MARK = "[filing wording]"
FILING_TYPES = {"Registration", "Registration-Update", "Statement", "Successor"}
_FDS = re.compile(r"(?:formally\s+filing\s+a\s+copy\s+of\s+the\s+(?:Financial\s+Disclosure\s+Statement\s*(?:for\s+)?)?"
                  r"|^STATEMENT,\s+submitted\s+by\s+the\s+Clerk\s+of\s+Council\s+from\s+)(?P<who>.+)$", re.I)
_ADDRESS = re.compile(r"^(?:\d|c/o\b|P\.?\s?O\.?\s+Box|Suite\b|One\s+[A-Z]\w+\s+(?:Street|Square|Plaza))", re.I)
_FDS_TAG = re.compile(r"\s*\((ETHICS|CITY)\)\s*\.?\s*$", re.I)

def _join_names(names):
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]

def load_filing_names():
    """Agent and organization merges shared with write_agents()."""
    with open(AGENT_ALIASES_FILE, encoding="utf-8") as f:
        aa = json.load(f)
    with open(ORG_ALIASES_FILE, encoding="utf-8") as f:
        oa = json.load(f)
    return {"agent_alias": {v: k for k, vs in aa["names"].items() for v in vs},
            "not_agents": set(aa.get("not_agents", [])),
            "org_alias": {v: k for k, vs in oa["names"].items() for v in vs},
            "org_names": set(oa["names"]),
            "keep_upper": set(oa.get("keep_upper", [])), "fixes": oa.get("display", {})}

def filing_role(t, agent):
    """Role and employer as filed: the text after the agent's name up to the address."""
    i = t.find(agent)
    if i < 0:
        return ""
    out = []
    for seg in t[i + len(agent):].split(","):
        seg = seg.strip(" .")
        if not seg:
            continue
        if _ADDRESS.match(seg) or seg.startswith("("):
            break
        if re.fullmatch(r"(?:Jr|Sr|I{2,3}|IV)", seg) and not out:
            continue   # name suffix after a comma ("Charles H. Gerhardt, III")
        if re.search(r"lobbyist", seg, re.I):
            continue   # job titles filed as "Lobbyist": the site uses "Legislative Agent"
        out.append(seg)
    role = ", ".join(out)
    return role if 0 < len(role) <= 100 else ""

def registration_text(matter_type, raw_title, nm):
    t = re.sub(r"\s+", " ", raw_title or "").strip()
    agent = filing_agent(t)
    role = filing_role(t, agent) if agent else ""
    if not agent or agent in nm["not_agents"] or len(agent.split()) > 6 or re.search(r"\d", agent):
        return None
    agent = nm["agent_alias"].get(agent, agent)
    clients, term = filing_clients(t)
    names = []
    for c in clients:   # entries the Agents page leaves out (not_orgs) are still named here
        g = nm["org_alias"].get(org_key(c), org_key(c))
        n = g if g in nm["org_names"] else org_display(c, nm["keep_upper"], nm["fixes"])
        if n not in names:
            names.append(n)
    if term:
        kind, verb = "termination", "ends a Legislative Agent registration"
    elif matter_type == "Registration-Update" or re.search(r"\(UPDATE[D]?\)", t, re.I):
        kind, verb = "registration update", "updates a Legislative Agent registration"
    else:
        kind, verb = "registration", "registers as a Legislative Agent"
    if names:
        who = _join_names(names)
        return (f"Legislative Agent {kind}: {agent} for {who}", f"{agent} {verb} for {who}.")
    if role:
        return (f"Legislative Agent {kind}: {agent}", f"{agent}, {role}, {verb}.")
    return (f"Legislative Agent {kind}: {agent}", f"{agent} {verb}; the filing names no client.")

def statement_text(raw_title):
    t = re.sub(r"\s+", " ", raw_title or "").strip()
    m = _FDS.search(t)
    if not m:
        return None
    who = m.group("who").strip()
    tag = _FDS_TAG.search(who)
    who = _FDS_TAG.sub("", who).strip().rstrip(".").strip()
    who = re.sub(r"\s*\(([^()]*/[^()]*)\)", r"/\1", who)   # "Name (Dept/Title)" -> "Name/Dept/Title"
    parts = [p.strip() for p in re.split(r"\s*/\s*|,\s+(?!Jr\b|Sr\b|I{2,3}\b|IV\b)", who) if p.strip()]
    if not parts or len(parts[0].split()) > 6 or len(parts[0].split()) < 2:
        return None
    name, position = parts[0], ", ".join(parts[1:])
    suffix = f" ({tag.group(1).title()} copy)" if tag else ""
    title = f"Financial disclosure statement: {name}{suffix}"
    summary = (f"The Clerk of Council files the financial disclosure statement of {name}"
               + (f", {position}" if position else "") + ".")
    return title, summary

def successor_text(raw_title):
    t = re.sub(r"\s+", " ", raw_title or "").strip()
    upd = " (updated)" if re.match(r"SUCCESSOR\s*\(UPDATE", t, re.I) else ""
    m = re.search(r"Certificates of all Councilmember-Elected for the (\S+) term", t, re.I)
    if m:
        return (f"Successor designation certificates for the {m.group(1)} Council term{upd}",
                f"The Clerk of Council reports that successor designation certificates were received from all Councilmembers-elect for the {m.group(1)} term.")
    m = re.search(r"Successor Designation Certificate for (.+?) was received", t, re.I)
    if m:
        return (f"Successor designation certificate for {m.group(1)}{upd}",
                f"The Clerk of Council reports that the successor designation certificate for {m.group(1)} was received.")
    m = re.search(r"SUCCESSOR DESIGNATION FORM, submitted by (?:the Clerk of Council from )?(.+?) pursuant", t, re.I)
    if m:
        return (f"Successor designation form from {m.group(1)}",
                f"{m.group(1)} files a successor designation form under the City Charter.")
    return None

def filing_text(matter_type, raw_title, nm):
    """(title, summary) for a filing, or None when the Legistar title is in another form."""
    t = (raw_title or "").lstrip()
    if matter_type in ("Registration", "Registration-Update") or (
            matter_type == "Statement" and re.match(r"REGISTRATION\b", t, re.I)):
        return registration_text(matter_type, t, nm)
    if matter_type == "Statement":
        return statement_text(t)
    if matter_type == "Successor":
        return successor_text(t)
    return None

if __name__ == "__main__":
    main()
