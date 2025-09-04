from playwright.sync_api import sync_playwright, TimeoutError
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import time
import re
import sys
import json

# Base URLs
URL = "https://www.global.golfzon.com/courses/about-course"
BASE = "https://www.global.golfzon.com"


def load_all_courses(page, max_stagnant_rounds=3, pause_ms=800):
    """Scrolls & clicks until all courses are loaded on the page."""
    sel_cards = "#search-course-body a[href^='/courses/']"
    stagnant = 0
    last_count = -1

    while True:
        try:
            load_more = page.get_by_role("button", name=re.compile(r"(more|load)", re.I))
            if load_more.is_visible():
                load_more.click()
                page.wait_for_load_state("networkidle")
        except Exception:
            pass

        page.evaluate("() => { window.scrollBy(0, document.documentElement.scrollHeight); }")
        page.wait_for_timeout(pause_ms)

        count = page.locator(sel_cards).count()
        if count > last_count:
            last_count = count
            stagnant = 0
        else:
            stagnant += 1

        if stagnant >= max_stagnant_rounds:
            break


def extract_holes_par_yardage(detail_soup: BeautifulSoup):
    """Extracts overall course info: holes, par, yardage."""
    candidates = []
    block = detail_soup.select_one(".span-space--dot")

    if block:
        candidates.append(" ".join(s.get_text(" ", strip=True) for s in block.find_all("span")))

    candidates.append(detail_soup.get_text(" ", strip=True))

    holes = par = yardage = None

    for text in candidates:
        if holes is None:
            m = re.search(r'(\d+)\s*H\b', text, flags=re.I)
            if m:
                holes = int(m.group(1))

        if par is None:
            m = re.search(r'\bPar\s*([0-9]+)', text, flags=re.I)
            if m:
                par = int(m.group(1))

        if yardage is None:
            m = re.search(r'([\d,]+)\s*yd\b', text, flags=re.I)
            if m:
                yardage = int(m.group(1).replace(",", ""))

        if holes and par and yardage:
            break

    return holes, par, yardage


def extract_per_hole_info(page):
    """
    Click through all hole tabs and extract per-hole info.
    Returns dict: {hole_number: {"par": int, "tees": [...], "video": url}}
    """
    holes_data = {}

    tabs = page.locator(".tabs-scroll div")
    tab_count = tabs.count()

    for i in range(tab_count):
        tab = tabs.nth(i)
        label = tab.inner_text().strip()
        if not label.endswith("H"):
            continue

        hole_num = int(label.replace("H", ""))

        tab.click()
        page.wait_for_timeout(500)

        detail_soup = BeautifulSoup(page.content(), "html.parser")
        block = detail_soup.select_one("div.block")
        if not block:
            continue

        par_span = block.select_one("span.gz-text-xsm")
        par_value = None
        if par_span:
            try:
                par_value = int(par_span.get_text(strip=True).replace("PAR ", ""))
            except:
                pass

        tees = []
        for row in block.select("div.flex.items-center.justify-between.border-b"):
            tee_name = row.select_one("div.gz-text-md")
            distance = row.find("div", class_=re.compile(r"w-\[78px\]"))
            height = row.find("div", class_=re.compile(r"w-\[92px\]"))

            if tee_name and distance and height:
                dist_val = distance.get_text(strip=True).replace("yd", "").strip()
                height_val = height.get_text(strip=True).replace("yd", "").strip()

                try:
                    dist_val = int(dist_val)
                except ValueError:
                    pass
                try:
                    height_val = float(height_val)
                except ValueError:
                    pass

                tees.append({
                    "tee": tee_name.get_text(strip=True),
                    "distance": dist_val,
                    "height": height_val
                })

        video_el = block.select_one("video.video-crop")
        video_url = video_el["src"] if video_el else None

        holes_data[hole_num] = {
            "par": par_value,
            "tees": tees,
            "video": video_url
        }

    return holes_data


def main():
    start_time = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        listing_page = browser.new_page()

        # Load listing page
        listing_page.goto(URL, wait_until="networkidle")
        listing_page.wait_for_selector("#search-course-body", timeout=20000)

        # Scroll/load all courses
        load_all_courses(listing_page)
        listing_html = listing_page.content()

        # Parse listing page
        listing_soup = BeautifulSoup(listing_html, "html.parser")
        cards = listing_soup.select("#search-course-body a[href^='/courses/']")
        if not cards:
            raise RuntimeError("No course links found after scrolling.")

        print(f"Found {len(cards)} course links", file=sys.stderr)

        results = []

        # Iterate over courses
        for idx, a in enumerate(cards, start=1):
            title_el = a.select_one("h4")
            href = a.get("href")
            if not title_el or not href:
                continue

            name = title_el.get_text(strip=True)
            course_url = urljoin(BASE, href)

            try:
                # 👉 Open detail in a new tab
                detail_page = browser.new_page()
                detail_page.goto(course_url, wait_until="networkidle", timeout=30000)
                detail_page.wait_for_timeout(500)

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

                detail_page.close() 

            except TimeoutError:
                print(f"[{idx}] {name} — ERROR (timeout)")

        browser.close()

        # ✅ Save results into JSON file
        with open("golf_courses.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        print(f"\nScraped {len(results)} courses total")
        print("Data saved to golf_courses.json")
    end_time = time.time()
    elapsed = end_time - start_time
    print(f"⏱️ Total time taken: {elapsed:.2f} seconds "
          f"({elapsed/60:.2f} minutes)")


if __name__ == "__main__":
    main()
