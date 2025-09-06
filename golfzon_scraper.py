from playwright.sync_api import sync_playwright, TimeoutError
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import time, re, sys, json, argparse

# Base URLs
URL = "https://www.global.golfzon.com/courses/about-course"
BASE = "https://www.global.golfzon.com"

NUM_RE = re.compile(r"-?\d+(?:[\d,]*\d)?(?:\.\d+)?")
COUNTRY_MAP = {
    "USA": "United States",
    "KOR": "South Korea",
    "JPN": "Japan",
    "CHN": "China",
    "THA": "Thailand",
    "TWN": "Taiwan",
    "DOM": "Dominican Republic",
    "VIE": "Vietnam",
    "PHI": "Philippines",
    "AUS": "Australia",
    "IRL": "Ireland",
    "CAN": "Canada",
    "MEX": "Mexico",
    "GBR": "United Kingdom",
    "GER": "Germany",
    "FRA": "France",
    "ITA": "Italy",
    "ESP": "Spain",
    "UAE": "United Arab Emirates",
    "SGP": "Singapore",
}
import subprocess
import sys

def run_scraper(limit=None):
    """Run the golfzon scraper as a subprocess and wait for completion."""
    cmd = [sys.executable, "golfzon_scraper.py"]
    if limit:
        cmd.extend(["--limit", str(limit)])
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout, result.stderr


def to_int_maybe(text):
    if not text:
        return None
    try:
        return int(re.sub(r"[^\d]", "", text))
    except:
        return None

def to_float_maybe(text):
    if not text:
        return None
    try:
        return float(re.sub(r"[^\d.-]", "", text))
    except:
        return None

def load_all_courses(page, max_stagnant_rounds=2, pause_ms=250, max_iters=220):
    sel_cards = "#search-course-body a[href^='/courses/']"
    stagnant = 0
    last_count = -1

    for _ in range(max_iters):
        try:
            load_more = page.get_by_role("button", name=re.compile(r"(more|load)", re.I))
            if load_more.is_visible():
                load_more.click(timeout=1500)
        except Exception:
            pass

        page.evaluate("() => window.scrollBy(0, document.documentElement.scrollHeight)")
        page.wait_for_timeout(pause_ms)

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

def extract_per_hole_info(page):
    """Click through all hole tabs and extract per-hole info."""
    holes_data = {}
    try:
        page.wait_for_selector(".tabs-scroll", timeout=4000)
    except Exception:
        return holes_data

    tabs = page.locator(".tabs-scroll div")
    tab_count = tabs.count()
    hole_tabs = []
    for i in range(tab_count):
        try:
            label = tabs.nth(i).inner_text().strip()
        except Exception:
            continue
        if re.fullmatch(r"\d+\s*H", label, flags=re.I):
            hole_tabs.append((i, int(re.sub(r"\D", "", label))))

    for i, hole_num in hole_tabs:
        tab = tabs.nth(i)
        try:
            tab.click(timeout=1000)
        except Exception:
            try:
                page.evaluate("(el) => el.click()", tab)
            except Exception:
                continue

        page.wait_for_timeout(100)
        soup = BeautifulSoup(page.content(), "html.parser")
        block = soup.select_one("div.block")
        if not block:
            continue

        # Hole par
        par_value = None
        par_span = block.select_one("span.gz-text-xsm")
        if par_span:
            par_value = to_int_maybe(par_span.get_text(strip=True))

        # Tees
        tees = []
        for row in block.select("div.flex.items-center.justify-between.border-b"):
            tee_name_el = row.select_one("div.gz-text-md")
            dist_el = row.find("div", class_=re.compile(r"w-\[78px\]"))
            height_el = row.find("div", class_=re.compile(r"w-\[92px\]"))
            if tee_name_el and dist_el and height_el:
                tees.append({
                    "tee": tee_name_el.get_text(strip=True),
                    "distance": to_int_maybe(dist_el.get_text(strip=True)),
                    "height": to_float_maybe(height_el.get_text(strip=True))
                })

        holes_data[hole_num] = {"par": par_value, "tees": tees, "video": None}

    return holes_data

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Limit number of courses")
    args = parser.parse_args()

    start_time = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-dev-shm-usage", "--no-sandbox"])
        context = browser.new_context()
        context.set_default_timeout(8000)

        listing_page = context.new_page()
        listing_page.goto(URL, wait_until="domcontentloaded", timeout=20000)
        listing_page.wait_for_selector("#search-course-body", timeout=15000)
        load_all_courses(listing_page)

        cards = listing_page.locator("#search-course-body a[href^='/courses/']")
        n = cards.count()
        print(f"Found {n} courses", file=sys.stderr)

        links = []
        for i in range(n):
            a = cards.nth(i)
            href = a.get_attribute("href")
            name = a.locator("h4").inner_text().strip() if a.locator("h4").count() else None
            if not (href and name):
                continue

            # Extract spans for country/yardage/holes/par
            spans = a.locator("span.break-normal")
            span_texts = [spans.nth(j).inner_text().strip() for j in range(spans.count())]

            country = holes = par = yardage = None
            if span_texts:
                if not any(c.isdigit() for c in span_texts[0]):  # First span = country acronym
                    country_code = span_texts[0]
                    country = COUNTRY_MAP.get(country_code.upper(), country_code)  # map or fallback
            for t in span_texts:
                if "yd" in t:
                    yardage = to_int_maybe(t)
                elif "H" in t and "Par" not in t:
                    holes = to_int_maybe(t)
                elif "Par" in t:
                    par = to_int_maybe(t)

            links.append({
                "name": name,
                "url": urljoin(BASE, href),
                "country": country,
                "holes": holes,
                "par": par,
                "yardage": yardage
            })

        if args.limit:
            links = links[:args.limit]

        # Reuse one detail page
        detail_page = context.new_page()
        results = []
        for idx, course in enumerate(links, start=1):
            try:
                detail_page.goto(course["url"], wait_until="domcontentloaded", timeout=15000)
                detail_page.wait_for_timeout(200)
                per_hole = extract_per_hole_info(detail_page)
                course["per_hole"] = per_hole
                print(f"[{idx}] {course['name']} scraped")
            except TimeoutError:
                print(f"[{idx}] {course['name']} — ERROR (timeout)", file=sys.stderr)
                course["per_hole"] = {}
            results.append(course)

        browser.close()

        with open("golf_courses.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        elapsed = time.time() - start_time
        print(f"\n✅ Scraped {len(results)} courses")
        print(f"⏱️ {elapsed:.2f}s ({elapsed/60:.2f}m)")
        print("Data saved to golf_courses.json")

if __name__ == "__main__":
    main()
