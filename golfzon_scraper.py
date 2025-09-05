from playwright.sync_api import sync_playwright, TimeoutError
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import time
import re
import sys
import json
import argparse
import math

# Base URLs
URL = "https://www.global.golfzon.com/courses/about-course"
BASE = "https://www.global.golfzon.com"

NUM_RE = re.compile(r"-?\d+(?:[\d,]*\d)?(?:\.\d+)?")

def to_int_maybe(text):
    if not text:
        return None
    m = NUM_RE.search(text.replace(",", ""))
    if not m:
        return None
    try:
        return int(float(m.group(0)))
    except ValueError:
        return None

def to_float_maybe(text):
    if not text:
        return None
    m = NUM_RE.search(text.replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None

def load_all_courses(page, max_stagnant_rounds=2, pause_ms=250, max_iters=220):
    """Scrolls & clicks until all courses are loaded on the page (fast path)."""
    sel_cards = "#search-course-body a[href^='/courses/']"
    stagnant = 0
    last_count = -1

    for _ in range(max_iters):  # hard cap for safety
        # Try clicking any 'Load more' visible button
        try:
            load_more = page.get_by_role("button", name=re.compile(r"(more|load)", re.I))
            if load_more.is_visible():
                load_more.click(timeout=1500)
        except Exception:
            pass

        # Scroll
        try:
            page.evaluate("() => window.scrollBy(0, document.documentElement.scrollHeight)")
        except Exception:
            pass
        page.wait_for_timeout(pause_ms)

        # Count cards
        try:
            count = page.locator(sel_cards).count()
        except Exception:
            count = last_count

        if count > last_count:
            last_count = count
            stagnant = 0
        else:
            stagnant += 1
            if stagnant >= max_stagnant_rounds:
                break

def extract_holes_par_yardage(detail_soup: BeautifulSoup):
    """Extracts overall course info: holes, par, yardage with multiple fallbacks."""
    candidates = []
    block = detail_soup.select_one(".span-space--dot")
    if block:
        candidates.append(" ".join(s.get_text(" ", strip=True) for s in block.find_all("span")))
    # Full-page fallback
    candidates.append(detail_soup.get_text(" ", strip=True))

    holes = par = yardage = None
    for text in candidates:
        if holes is None:
            m = re.search(r"(\d+)\s*H\b", text, flags=re.I)
            if m:
                holes = to_int_maybe(m.group(1))

        if par is None:
            m = re.search(r"\bPar\s*([0-9]+)", text, flags=re.I)
            if m:
                par = to_int_maybe(m.group(1))

        if yardage is None:
            m = re.search(r"([\d,]+)\s*yd\b", text, flags=re.I)
            if m:
                yardage = to_int_maybe(m.group(1))

        if holes and par and yardage:
            break

    return holes, par, yardage

def _get_video_url(block: BeautifulSoup):
    # Try <video> first
    vid = block.select_one("video.video-crop, video")
    if vid:
        for key in ("src", "data-src"):
            if vid.get(key):
                return vid.get(key)
        # Try <source> children
        src_el = vid.select_one("source")
        if src_el:
            for key in ("src", "data-src"):
                if src_el.get(key):
                    return src_el.get(key)
    return None

def extract_per_hole_info(page):
    """
    Click through all hole tabs and extract per-hole info.
    Returns dict: {hole_number: {"par": int|None, "tees": [...], "video": url|None}}
    """
    holes_data = {}

    try:
        page.wait_for_selector(".tabs-scroll", timeout=4000)
    except Exception:
        return holes_data

    tabs = page.locator(".tabs-scroll div")
    try:
        tab_count = tabs.count()
    except Exception:
        return holes_data

    # Build list of (index, hole_num)
    hole_tabs = []
    for i in range(tab_count):
        try:
            label = tabs.nth(i).inner_text().strip()
        except Exception:
            continue
        if re.fullmatch(r"\d+\s*H", label, flags=re.I):
            hole_tabs.append((i, int(re.sub(r"\D", "", label))))

    if not hole_tabs:
        return holes_data

    for i, hole_num in hole_tabs:
        tab = tabs.nth(i)
        try:
            tab.click(timeout=1000)
        except Exception:
            try:
                page.evaluate("(el) => el.click()", tab)
            except Exception:
                continue

        page.wait_for_timeout(80)  # tiny pause for DOM swap
        detail_soup = BeautifulSoup(page.content(), "html.parser")
        block = detail_soup.select_one("div.block")
        if not block:
            # fallback
            blocks = detail_soup.select("div.block, section, article")
            block = blocks[0] if blocks else None
        if not block:
            continue

        par_value = None
        par_span = block.select_one("span.gz-text-xsm")
        if par_span:
            par_value = to_int_maybe(par_span.get_text(strip=True))

        tees = []
        for row in block.select("div.flex.items-center.justify-between.border-b"):
            tee_name_el = row.select_one("div.gz-text-md")
            distance_el = row.find("div", class_=re.compile(r"w-\[\s*78px\s*\]"))
            height_el = row.find("div", class_=re.compile(r"w-\[\s*92px\s*\]"))

            if not (tee_name_el and distance_el and height_el):
                cells = row.select("div")
                if len(cells) >= 3:
                    tee_name_el = tee_name_el or cells[0]
                    numeric_cells = [c for c in cells[1:] if NUM_RE.search(c.get_text())]
                    if len(numeric_cells) >= 2:
                        distance_el = distance_el or numeric_cells[0]
                        height_el = height_el or numeric_cells[1]

            if tee_name_el and distance_el and height_el:
                tee_name = tee_name_el.get_text(strip=True)
                dist_val = to_int_maybe(distance_el.get_text(strip=True))
                height_val = to_float_maybe(height_el.get_text(strip=True))
                tees.append({"tee": tee_name, "distance": dist_val, "height": height_val})

        video_url = _get_video_url(block)
        holes_data[hole_num] = {"par": par_value, "tees": tees, "video": video_url}

    return holes_data

# ---------------------- SPEED + STABILITY HELPERS ----------------------

RETRY_ERR_PATTERN = re.compile(
    r"(ERR_NAME_NOT_RESOLVED|ERR_CONNECTION_RESET|ERR_CONNECTION_CLOSED|ERR_ADDRESS_UNREACHABLE|Timeout)", re.I
)

def safe_goto(page, url, max_retries=4, base_timeout=6000, wait_until="domcontentloaded"):
    """
    Goto with retries + exponential backoff for flaky DNS/network.
    """
    attempt = 0
    while True:
        try:
            page.goto(url, wait_until=wait_until, timeout=base_timeout)
            return True
        except Exception as e:
            attempt += 1
            msg = str(e)
            is_retryable = RETRY_ERR_PATTERN.search(msg) is not None
            if not is_retryable or attempt > max_retries:
                # Final failure
                raise
            # backoff (0.5s, 1s, 2s, 3s...)
            backoff = 0.5 * attempt
            time.sleep(backoff)

def main():
    parser = argparse.ArgumentParser(description="Scrape Golfzon courses.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of courses (for testing)")
    args = parser.parse_args()

    start_time = time.time()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage", "--no-sandbox"]
            )
            context = browser.new_context()
            context.set_default_timeout(8000)

            def block(route, request):
                rt = request.resource_type
                if rt in ("image", "media", "font", "stylesheet"):
                    return route.abort()
                url = request.url.lower()
                if url.endswith((".mp4",".webm",".mov",".gif",".png",".jpg",".jpeg",".webp",".woff",".woff2",".ttf",".otf",".ico",".css")):
                    return route.abort()
                route.continue_()
            context.route("**/*", block)

            listing_page = context.new_page()
            safe_goto(listing_page, URL, wait_until="domcontentloaded", base_timeout=10000)
            listing_page.wait_for_selector("#search-course-body", timeout=10000)
            load_all_courses(listing_page)

            # Collect links (no soup, use locators)
            cards = listing_page.locator("#search-course-body a[href^='/courses/']")
            n = cards.count()
            if n == 0:
                raise RuntimeError("No course links found.")

            print(f"Found {n} course links", file=sys.stderr)

            links = []
            for i in range(n):
                a = cards.nth(i)
                href = a.get_attribute("href")
                name = a.locator("h4").inner_text().strip() if a.locator("h4").count() else None
                if href and name:
                    links.append((name, urljoin(BASE, href)))

            if args.limit:
                links = links[:args.limit]

            # Reuse ONE page for details (faster than creating many)
            detail_page = context.new_page()

            results = []
            for idx, (name, course_url) in enumerate(links, start=1):
                try:
                    safe_goto(detail_page, course_url, wait_until="domcontentloaded", base_timeout=10000)
                    detail_page.wait_for_timeout(120)

                    detail_html = detail_page.content()
                    detail_soup = BeautifulSoup(detail_html, "html.parser")

                    holes, par, yardage = extract_holes_par_yardage(detail_soup)
                    per_hole = extract_per_hole_info(detail_page)

                    results.append({
                        "name": name,
                        "url": course_url,
                        "holes": holes,
                        "par": par,
                        "yardage": yardage,
                        "per_hole": per_hole
                    })

                    print(f"[{idx}] {name} scraped")
                except TimeoutError:
                    print(f"[{idx}] {name} — ERROR (timeout)", file=sys.stderr)
                except KeyboardInterrupt:
                    print("\nInterrupted — saving partial results…", file=sys.stderr)
                    break
                except Exception as e:
                    print(f"[{idx}] {name} — ERROR ({type(e).__name__}: {e})", file=sys.stderr)

            # Close pages
            try:
                listing_page.close()
            except Exception:
                pass
            try:
                detail_page.close()
            except Exception:
                pass
            browser.close()

            # Save
            with open("golf_courses.json", "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)

            print(f"\nScraped {len(results)} courses total")
            print("Data saved to golf_courses.json")

    except KeyboardInterrupt:
        print("\nInterrupted — exiting.", file=sys.stderr)

    elapsed = time.time() - start_time
    print(f"Total time taken: {elapsed:.2f} seconds ({elapsed/60:.2f} minutes)")

if __name__ == "__main__":
    main()
