#!/usr/bin/env python3
"""
ICOdrops project page scraper.
Reads a CSV with a 'source_url' column, scrapes each project page,
and outputs an enriched CSV with additional fields.

Usage:
    python3 scrape_icodrops.py input_projects.csv --output enriched_projects.csv
"""

import argparse
import csv
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

CACHE_FILE = "_scrape_cache.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36"
}
DEFAULT_WORKERS = 5
DELAY = 0.3  # seconds between requests per worker

SCRAPED_FIELDS = [
    "website_url",
    "whitepaper_url",
    "twitter_url",
    "github_url",
    "eth_smart_contract_address",
    "other_smart_contract_address_list",
    "activity_count",
    "tge_distribution_date",
    "investor_count",
    "total_raised",
    "investing_round_count",
    "fdv",
    "ecosystems_list",
]

# Values that mean "no data" on the site
DASH_VALUES = {"—", "–", "-", "$—", "$–", "$-"}

# Columns to rename from input CSV to match spec
COLUMN_RENAMES = {
    "source_url": "icodrops_url",
    "Source URL": "icodrops_url",
    "categories": "project_category",
    "Categories": "project_category",
}


def load_cache(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def save_cache(path: Path, cache: dict):
    with open(path, "w") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def extract_capsule_links(soup: BeautifulSoup) -> dict:
    """Extract named links from the capsule link section near the project title."""
    result = {"website_url": "", "whitepaper_url": "", "twitter_url": "", "github_url": ""}
    seen = set()
    for a in soup.select("a.capsule"):
        text = a.get_text(strip=True).lower()
        href = a.get("href", "").strip()
        if not href or href in seen:
            continue
        seen.add(href)
        if text == "website":
            result["website_url"] = href
        elif text == "whitepaper":
            result["whitepaper_url"] = href
        elif text == "twitter":
            result["twitter_url"] = href
        elif text == "github":
            result["github_url"] = href
    return result


def extract_contract_addresses(soup: BeautifulSoup) -> dict:
    """Extract ETH and other smart contract addresses from capsule links."""
    eth_address = ""
    other_addresses = []
    seen = set()

    for a in soup.select("a.capsule"):
        href = a.get("href", "").strip()
        if not href or href in seen:
            continue
        seen.add(href)

        # Check for etherscan.io link
        if "etherscan.io" in href:
            match = re.search(r"(0x[a-fA-F0-9]{40})", href)
            if match and not eth_address:
                eth_address = match.group(1)
            continue

        # Check for other blockchain explorers
        parsed = urlparse(href)
        host = parsed.hostname or ""
        if any(x in host for x in ["scan.", "explorer.", "hecoinfo."]):
            match = re.search(r"(0x[a-fA-F0-9]{40})", href)
            addr = match.group(1) if match else href
            other_addresses.append(addr)

    return {
        "eth_smart_contract_address": eth_address,
        "other_smart_contract_address_list": "; ".join(other_addresses),
    }


def extract_activities(soup: BeautifulSoup) -> dict:
    """Extract activity count, TGE distribution date, and investor count from Past Activities."""
    result = {"activity_count": "", "tge_distribution_date": ""}

    # Count activities: each round/activity has a Proj-Rounds-Header
    headers = soup.select(".Proj-Rounds-Header")
    if headers:
        result["activity_count"] = str(len(headers))

    # TGE distribution date
    for header in headers:
        title_el = header.select_one(".Proj-Rounds-Header__title")
        if title_el and "tge" in title_el.get_text(strip=True).lower():
            for item in header.select(".Proj-Rounds-Header__item"):
                text = item.get_text(strip=True)
                date_match = re.search(
                    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4})",
                    text
                )
                if date_match:
                    result["tge_distribution_date"] = date_match.group(1)
                    break
            break

    return result


def extract_overview(soup: BeautifulSoup) -> dict:
    """Extract Total Raised, FDV, round count, ecosystems, and investor count from Overview."""
    result = {
        "total_raised": "",
        "investing_round_count": "",
        "fdv": "",
        "ecosystems_list": "",
        "investor_count": "",
    }

    # Total Raised and FDV from price blocks
    for block in soup.select(".Overview-Section-Price-Block__box"):
        title_el = block.select_one(".Overview-Section-Price-Block__title")
        value_el = block.select_one(".Overview-Section-Price-Block__value")
        if not title_el or not value_el:
            continue
        title = title_el.get_text(strip=True)
        value = value_el.get_text(strip=True)
        if title == "Total Raised":
            result["total_raised"] = value
        elif title == "FDV":
            result["fdv"] = value

    # Round count from "In X rounds" text
    round_text_el = soup.select_one(".Overview-Section-Price-Block__round-text")
    if round_text_el:
        match = re.search(r"(\d+)\s*round", round_text_el.get_text(strip=True))
        if match:
            result["investing_round_count"] = match.group(1)

    # Ecosystems
    for item in soup.select(".Overview-Section-Info-List__item"):
        name_el = item.select_one(".Overview-Section-Info-List__name")
        if name_el and "ecosystem" in name_el.get_text(strip=True).lower():
            ecosystems = [
                e.get_text(strip=True)
                for e in item.select(".Overview-Section-Info-List__capsules-item")
            ]
            result["ecosystems_list"] = "; ".join(ecosystems)
            break

    # Investor count from overview
    for item in soup.select(".Overview-Section-Info-List__item"):
        name_el = item.select_one(".Overview-Section-Info-List__name")
        if name_el and "investor" in name_el.get_text(strip=True).lower():
            # Count: look for "+N" pattern or count investor elements
            investors_el = item.select_one(".Overview-Section-Info-List__investors")
            if investors_el:
                more = investors_el.select_one(".Overview-Section-Info-List__investors-section")
                main = investors_el.select_one(".Overview-Section-Info-List__main-investor")
                count = 0
                if main:
                    count = 1
                if more:
                    match = re.search(r"\+(\d+)", more.get_text(strip=True))
                    if match:
                        count += int(match.group(1))
                if count > 0:
                    result["investor_count"] = str(count)
            break

    return result


def scrape_project(url: str) -> dict:
    """Scrape a single ICOdrops project page and return extracted fields."""
    result = {field: "" for field in SCRAPED_FIELDS}

    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")

    result.update(extract_capsule_links(soup))
    result.update(extract_contract_addresses(soup))
    result.update(extract_activities(soup))
    result.update(extract_overview(soup))

    return result


def main():
    parser = argparse.ArgumentParser(description="Scrape ICOdrops project pages")
    parser.add_argument("input_csv", help="Path to input CSV with source_url column")
    parser.add_argument("--output", "-o", default="enriched_projects.csv",
                        help="Output CSV path (default: enriched_projects.csv)")
    parser.add_argument("--workers", "-w", type=int, default=DEFAULT_WORKERS,
                        help=f"Number of concurrent workers (default: {DEFAULT_WORKERS})")
    args = parser.parse_args()

    input_path = Path(args.input_csv)
    if not input_path.exists():
        print(f"Error: {input_path} not found", file=sys.stderr)
        sys.exit(1)

    cache_path = input_path.parent / CACHE_FILE
    cache = load_cache(cache_path)
    cache_lock = threading.Lock()

    # Read input CSV
    with open(input_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        input_fieldnames = list(reader.fieldnames)
        rows = list(reader)

    # Determine source_url column (case-insensitive)
    url_col = None
    for col in input_fieldnames:
        if col.strip().lower() == "source_url":
            url_col = col
            break
    if not url_col:
        print("Error: no 'source_url' column found in input CSV", file=sys.stderr)
        sys.exit(1)

    # Rename input columns to match spec
    output_fieldnames = [COLUMN_RENAMES.get(col, col) for col in input_fieldnames] + SCRAPED_FIELDS
    total = len(rows)

    # Collect unique URLs that need scraping
    urls_to_scrape = set()
    for row in rows:
        url = row.get(url_col, "").strip()
        if url and url not in cache:
            urls_to_scrape.add(url)

    cached_count = sum(1 for row in rows if row.get(url_col, "").strip() in cache)
    print(f"Loaded {total} projects from {input_path}")
    print(f"Cache has {len(cache)} previously scraped URLs ({cached_count} rows already cached)")
    print(f"Need to scrape: {len(urls_to_scrape)} unique URLs")
    print(f"Workers: {args.workers}")
    print(f"Output: {args.output}\n")

    # Progress tracking
    progress = {"done": 0, "errors": 0}
    progress_lock = threading.Lock()
    scrape_total = len(urls_to_scrape)
    start_time = time.time()

    def scrape_one(url: str) -> tuple:
        """Scrape a single URL. Returns (url, result_dict, error_msg)."""
        time.sleep(DELAY)  # stagger requests
        try:
            result = scrape_project(url)
            with cache_lock:
                cache[url] = result
            with progress_lock:
                progress["done"] += 1
                done = progress["done"]
                elapsed = time.time() - start_time
                rate = done / elapsed if elapsed > 0 else 0
                remaining = (scrape_total - done) / rate if rate > 0 else 0
                print(f"  [{done}/{scrape_total}] OK  {url}  "
                      f"({rate:.1f}/s, ~{remaining:.0f}s left)", flush=True)
            return (url, result, None)
        except Exception as e:
            with progress_lock:
                progress["done"] += 1
                progress["errors"] += 1
                print(f"  [{progress['done']}/{scrape_total}] ERROR  {url}  {e}", flush=True)
            return (url, None, str(e))

    # Scrape concurrently
    if urls_to_scrape:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(scrape_one, url): url for url in urls_to_scrape}
            for future in as_completed(futures):
                future.result()  # propagate exceptions

        # Save cache once after all scraping is done
        save_cache(cache_path, cache)

    # Merge results in original row order
    enriched_rows = []
    for row in rows:
        url = row.get(url_col, "").strip()
        scraped = cache.get(url, {field: "" for field in SCRAPED_FIELDS})
        # Label empty or dash-only scraped fields as MISSING
        scraped = {k: ("MISSING" if (not v or v.strip() in DASH_VALUES) else v)
                   for k, v in scraped.items()}
        # Rename input columns to match spec
        merged = {COLUMN_RENAMES.get(k, k): v for k, v in row.items()}
        merged.update(scraped)
        enriched_rows.append(merged)

    # Write output
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=output_fieldnames)
        writer.writeheader()
        writer.writerows(enriched_rows)

    elapsed = time.time() - start_time
    print(f"\nDone in {elapsed:.1f}s. Wrote {len(enriched_rows)} rows to {args.output}")
    if progress["errors"]:
        print(f"  {progress['errors']} URLs failed (empty fields in output)")


if __name__ == "__main__":
    main()
