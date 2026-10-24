"""Attachment text for items whose Legistar title stops short.

Motions and some other items end their Legistar title with "(BALANCE ON FILE IN
THE CLERK'S OFFICE)" or "...as follows:". The rest of the text is only in the
attached PDF. This module finds those items, downloads the main attachment from
the public Legistar API, extracts its text and caches it in attachment_text.json
so the title and description can be written from the full text.

Text comes from the PDF's own text layer when it has one (pypdf); scanned pages
are read with Tesseract OCR (pdftoppm + tesseract command-line tools).

Cache entry, keyed by matter_id:
  {"status": "ok", "attachment_id": "...", "name": "Motion", "checked": "YYYY-MM-DD",
   "source": "text" | "ocr", "text": "..."}
  {"status": "none", "checked": "YYYY-MM-DD", "tries": n, "error": "..."}
A "none" entry is re-checked on later runs for NONE_RETRY_DAYS after the first try.
"""
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timedelta

import requests

CACHE_FILE = "attachment_text.json"
TEXT_MAX = 6000          # characters kept in the cache per item
PROMPT_MAX = 3000        # characters sent to the model per item
MAX_PAGES = 6            # pages read per PDF
NONE_RETRY_DAYS = 30     # keep re-checking an item with no attachment for this long
FETCH_LIMIT = 40         # attachments downloaded per run
AWAITING_MARK = "[awaiting attachment]"

# The title stops short and points to the attachment.
_STUB_RE = re.compile(
    r"BALANCE\s+ON\s+FILE|(?:the\s+following|as\s+follows)\s*:\s*(?:\(|$)",
    re.IGNORECASE)
# Attachment names that hold the legislative text itself, in order of preference.
_MAIN_NAMES = [r"\bmotion\b", r"\bordinance\b", r"\bresolution\b", r"legislation"]


def needs_attachment(raw_title):
    """True when the Legistar title points to an attachment for the rest of its text."""
    return bool(_STUB_RE.search(raw_title or ""))


def load_cache(path=CACHE_FILE):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache, path=CACHE_FILE):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")


def _get(url, timeout=60, tries=3, headers=None):
    for attempt in range(1, tries + 1):
        try:
            r = requests.get(url, timeout=timeout, headers=headers or {})
            r.raise_for_status()
            return r
        except Exception:
            if attempt == tries:
                raise
            time.sleep(4 * attempt)


def list_attachments(api_base, matter_id):
    """Return [(attachment_id, name, url, sort)] for a matter, from the public API.
    The API answers in JSON unless asked for XML; JSON is requested explicitly."""
    r = _get(f"{api_base}/matters/{matter_id}/attachments", headers={"Accept": "application/json"})
    out = []
    for a in r.json() or []:
        if a.get("MatterAttachmentShowOnInternetPage") is False:
            continue
        url = (a.get("MatterAttachmentHyperlink") or "").strip()
        if not url:
            continue
        out.append((str(a.get("MatterAttachmentId") or ""), (a.get("MatterAttachmentName") or "").strip(),
                    url, int(a.get("MatterAttachmentSort") or 0)))
    return out


def choose_attachment(atts):
    """Pick the attachment most likely to hold the item's own text."""
    pdfs = [a for a in atts if a[2].lower().split("?")[0].endswith(".pdf")] or atts
    for pat in _MAIN_NAMES:
        hits = [a for a in pdfs if re.search(pat, a[1] or "", re.IGNORECASE)]
        if hits:
            return sorted(hits, key=lambda a: a[3])[0]
    return sorted(pdfs, key=lambda a: a[3])[0] if pdfs else None


def _ocr_pages(pdf_bytes, n_pages):
    """OCR the first n_pages with pdftoppm + tesseract. Returns '' if the tools are missing."""
    if not (shutil.which("pdftoppm") and shutil.which("tesseract")):
        return ""
    texts = []
    with tempfile.TemporaryDirectory() as d:
        pdf = os.path.join(d, "a.pdf")
        with open(pdf, "wb") as f:
            f.write(pdf_bytes)
        subprocess.run(["pdftoppm", "-r", "300", "-gray", "-png", "-f", "1", "-l", str(n_pages),
                        pdf, os.path.join(d, "p")], check=True, capture_output=True, timeout=300)
        for img in sorted(x for x in os.listdir(d) if x.endswith(".png")):
            res = subprocess.run(["tesseract", os.path.join(d, img), "-", "--psm", "6"],
                                 capture_output=True, text=True, timeout=300)
            texts.append(res.stdout)
    return "\n".join(texts)


def extract_text(pdf_bytes):
    """Return (text, source). Uses the text layer; falls back to OCR when it is nearly empty."""
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        n = min(len(reader.pages), MAX_PAGES)
        text = "\n".join((reader.pages[i].extract_text() or "") for i in range(n))
    except Exception:
        n, text = MAX_PAGES, ""
    if len(re.sub(r"\s", "", text)) >= 200:
        return text, "text"
    ocr = _ocr_pages(pdf_bytes, n or MAX_PAGES)
    return (ocr, "ocr") if len(re.sub(r"\s", "", ocr)) > len(re.sub(r"\s", "", text)) else (text, "text")


def fetch_one(api_base, matter_id):
    """Fetch and extract the main attachment for one matter. Returns a cache entry."""
    today = datetime.today().strftime("%Y-%m-%d")
    try:
        att = choose_attachment(list_attachments(api_base, matter_id))
        if not att:
            return {"status": "none", "checked": today, "error": "no attachment listed"}
        aid, name, url, _ = att
        text, source = extract_text(_get(url, timeout=120).content)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n", text).strip()
        if len(text) < 80:
            return {"status": "none", "checked": today, "error": f"little text in {name} ({len(text)} chars)"}
        return {"status": "ok", "attachment_id": aid, "name": name, "checked": today,
                "source": source, "text": text[:TEXT_MAX]}
    except Exception as e:
        return {"status": "none", "checked": today, "error": str(e)[:200]}


def ensure_text(items, cache, api_base, limit=FETCH_LIMIT):
    """Fetch attachment text for items that need it and are not cached (or are due a re-check).
    Mutates cache. Returns the number of downloads attempted."""
    today = datetime.today()
    done = 0
    for it in items:
        mid = str(it.get("matter_id", ""))
        if not mid or not needs_attachment(it.get("raw_title", "")):
            continue
        entry = cache.get(mid)
        if entry and entry.get("status") == "ok":
            continue
        if entry and entry.get("status") == "none":
            first = entry.get("first_checked") or entry.get("checked")
            try:
                if today - datetime.strptime(first, "%Y-%m-%d") > timedelta(days=NONE_RETRY_DAYS):
                    continue
            except Exception:
                pass
            if entry.get("checked") == today.strftime("%Y-%m-%d"):
                continue
        if done >= limit:
            break
        new = fetch_one(api_base, mid)
        if new["status"] == "none":
            new["first_checked"] = (entry or {}).get("first_checked") or (entry or {}).get("checked") or new["checked"]
            new["tries"] = (entry or {}).get("tries", 0) + 1
        cache[mid] = new
        done += 1
        print(f"    attachment {it.get('file_number', mid)}: {new['status']}"
              + (f" ({new.get('name')}, {new.get('source')}, {len(new.get('text', ''))} chars)"
                 if new["status"] == "ok" else f" ({new.get('error', '')})"))
        time.sleep(0.5)
    return done


def prompt_text(item, cache):
    """Text to send the model for one item: the Legistar title plus attachment text if cached."""
    raw = re.sub(r"\s+", " ", item.get("raw_title", "")).replace("|", "/")
    entry = cache.get(str(item.get("matter_id", "")))
    if entry and entry.get("status") == "ok":
        att = re.sub(r"\s+", " ", entry["text"]).replace("|", "/")[:PROMPT_MAX]
        return f"{raw} [ATTACHED TEXT ({entry.get('name') or 'attachment'}): {att}]"
    return raw


def awaiting(item, cache):
    """True when the item needs attachment text and none is cached yet."""
    if not needs_attachment(item.get("raw_title", "")):
        return False
    entry = cache.get(str(item.get("matter_id", "")))
    return not (entry and entry.get("status") == "ok")
