"""Stage 1.1 — polite BFS crawler.

Reads:  nothing (start URL below)
Writes: data/raw/<slug>.html, checkpoints/crawler.json
"""

import csv
import json
import logging
import os
import re
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from urllib.robotparser import RobotFileParser

import requests

# --- site-specific config (swap domain by editing these) ---
BASE_URL = "https://animaldiversity.org"
SEED = "/accounts/Animalia/classification/"
# groups: (1) 'class="feature-less"' or '' (species without an account), (2) path, (3) rank
LINK_RE = re.compile(
    r'<div ?(class="feature-less")?>\s*(?:<span>\w+</span>)?\s*'
    r'<a href="(/accounts/[A-Za-z_]+/classification/)" class="taxon-link rank--(\w+)"'
)
# ------------------------------------------------------------

CONTACT_EMAIL = "xziduliak@stuba.sk"
USER_AGENT = f"vinf-crawler/0.1 (FIIT STU student project; {CONTACT_EMAIL})"
HEADERS = {"User-Agent": USER_AGENT, "From": CONTACT_EMAIL, "Accept": "text/html"}
TIMEOUT = 15
DELAY_SECONDS = 8
MAX_RETRIES = 3

RAW_DIR = Path("data/raw")
METADATA_FILE = Path("data/metadata.tsv")
CHECKPOINT_FILE = Path("checkpoints/crawler.json")
MAX_PAGES = None  # test limit; set to None for the full crawl


def load_checkpoint() -> tuple[deque[str], set[str]]:
    if not CHECKPOINT_FILE.exists():
        return deque([SEED]), {SEED}
    with open(CHECKPOINT_FILE) as f:
        data = json.load(f)
    return deque(data["queue"]), set(data["seen"])


def save_checkpoint(queue: deque[str], seen: set[str]) -> None:
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CHECKPOINT_FILE.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump({"queue": list(queue), "seen": list(seen)}, f)
    os.replace(tmp, CHECKPOINT_FILE)  # atomic: never leaves a half-written file


def extract_links(html: str) -> list[tuple[str, str]]:
    return list(dict.fromkeys(LINK_RE.findall(html)))


def fetch(url: str, delay: float) -> tuple[str | None, int]:

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=False)
        except requests.RequestException as e:
            logging.warning("fetch %s failed (%d/%d): %s", url, attempt + 1, MAX_RETRIES, e)
        else:
            if resp.status_code == 200:
                return resp.text, resp.status_code
            if resp.status_code in (302, 404):
                logging.info("fetch %s: HTTP %d, no account", url, resp.status_code)
                return None, resp.status_code
            logging.warning("fetch %s: HTTP %d (%d/%d)", url, resp.status_code, attempt + 1, MAX_RETRIES)

        finally:
            time.sleep(delay)
    return None, 0

def save(path: str, html: str) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    slug = path.strip("/").split("/")[-1]         # 'Panthera_leo'
    out = RAW_DIR / f"{slug}.html"
    out.write_text(html, encoding="utf-8")
    return out

def log_metadata(url: str, page_type: str, status: int | str, size: int, file: str) -> None:

    new = not METADATA_FILE.exists()
    with open(METADATA_FILE, "a", newline="") as f:          # "a" = append, nikdy neprepíše
        w = csv.writer(f, delimiter="\t")
        if new:
            w.writerow(["url", "type", "status", "timestamp", "size", "file"])
        ts = datetime.now().isoformat(timespec="seconds")
        w.writerow([url, page_type, status, ts, size, file])


def crawl() -> None:

    queue, seen = load_checkpoint()

    rp = RobotFileParser(BASE_URL + "/robots.txt")
    rp.read()
    delay = rp.crawl_delay(USER_AGENT) or DELAY_SECONDS
    logging.info("robots.txt crawl-delay for %s: %s s", USER_AGENT, delay)
    n = 0
    while queue:
        if MAX_PAGES is not None and n >= MAX_PAGES:
            logging.info("MAX_PAGES=%d reached, stopping", MAX_PAGES)
            break
        n += 1
        path = queue.popleft()

        if not rp.can_fetch(USER_AGENT, BASE_URL + path):
            logging.info("robots.txt disallows %s, skipping", path)
            log_metadata(path, "disallowed", "", 0, "")
            continue

        logging.info("[%d] queue=%d %s", n, len(queue), path)
        html, http_code = fetch(BASE_URL + path, delay)
        page_type = "classification" if path.endswith("classification/") else "species"

        if html is None:
            log_metadata(path, page_type, http_code, 0, "")
            continue

        if page_type == "classification":
            log_metadata(path, page_type, http_code, len(html), "")
            for featureless, link, rank in extract_links(html):
                if featureless:
                    # "feature-less" = nothing (no account, pictures, sounds) in the whole
                    # subtree, at any rank -> prune it without fetching
                    log_metadata(link, f"pruned_{rank.lower()}", "", 0, "")
                    continue
                if rank == "Species":
                    link = link.removesuffix("classification/")
                if link in seen:
                    continue
                seen.add(link)
                if rank == "Species":
                    queue.appendleft(link)  # species accounts first, navigation stays BFS
                else:
                    queue.append(link)
        else:
            out = save(path, html)
            log_metadata(path, page_type, http_code, len(html), str(out))

        save_checkpoint(queue, seen)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    crawl()

if __name__ == "__main__":
    main()
