import json
import re
import sys
from golfzon_scraper import COUNTRY_MAP
# ----- load data -----
with open("golf_courses.json", "r", encoding="utf-8") as f:
    courses = json.load(f)

NUM_RE = re.compile(r"-?\d+(?:[\d,]*\d)?(?:\.\d+)?")

def parse_hole_input(hole_input, total_holes=None):
    """Convert input like '1,3,5-9' into a list of ints."""
    holes = set()
    for part in (hole_input or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            if start.strip().isdigit() and end.strip().isdigit():
                a, b = int(start), int(end)
                if a > b: a, b = b, a
                for h in range(a, b + 1):
                    if not total_holes or h <= int(total_holes):
                        holes.add(h)
        elif part.isdigit():
            h = int(part)
            if not total_holes or h <= int(total_holes):
                holes.add(h)
    return sorted(holes)
def normalize_country(input_str):
    """Return standardized full country name if match, else None."""
    if not input_str:
        return None
    key = input_str.strip().upper()
    # If it's a code, map directly
    if key in COUNTRY_MAP:
        return COUNTRY_MAP[key]
    for code, name in COUNTRY_MAP.items():
        if key.lower() == name.lower():
            return name
    return input_str
def to_int_maybe(x):
    if x is None: return None
    s = str(x).replace(",", "")
    m = NUM_RE.search(s)
    if not m: return None
    try: return int(float(m.group(0)))
    except ValueError: return None

def compute_tee_totals(course):
    """Sum distances by tee name across all holes for a course."""
    totals = {}
    per_hole = course.get("per_hole") or {}
    for hole in per_hole.values():
        for tee in (hole.get("tees") or []):
            name = (tee.get("tee") or "").strip()
            if not name:
                continue
            dist = to_int_maybe(tee.get("distance"))
            if dist is None:
                continue
            totals[name] = totals.get(name, 0) + dist
    return totals

def parse_yardage_range(text):
    """Accepts '6000-6500', '>=6000', '<=6500', '6200', '6000 6500'."""
    if not text:
        return (None, None)
    t = text.strip().replace(",", "")
    if "-" in t:
        a, b = t.split("-", 1)
        a, b = to_int_maybe(a), to_int_maybe(b)
        if a and b and a > b: a, b = b, a
        return (a, b)
    if t.startswith(">="):
        return (to_int_maybe(t[2:]), None)
    if t.startswith("<="):
        return (None, to_int_maybe(t[2:]))
    nums = [to_int_maybe(n) for n in re.findall(r"\d+", t)]
    nums = [n for n in nums if n is not None]
    if not nums:
        return (None, None)
    if len(nums) == 1:
        return (nums[0], nums[0])
    a, b = nums[0], nums[1]
    if a > b: a, b = b, a
    return (a, b)

def within_range(val, lo, hi):
    if val is None: return False
    if lo is not None and val < lo: return False
    if hi is not None and val > hi: return False
    return True

def display_hole_sums(course, holes):
    """Show total yards across selected holes for each tee color."""
    per_hole = course.get("per_hole") or {}
    totals = {}

    for hole_num in holes:
        hole = per_hole.get(str(hole_num))
        if not hole:
            continue
        for tee in hole.get("tees", []):
            name = (tee.get("tee") or "").strip()
            dist = to_int_maybe(tee.get("distance"))
            if not name or dist is None:
                continue
            totals[name] = totals.get(name, 0) + dist

    print(f"\nCourse: {course['name']}")
    print(f"Holes selected: {holes}")
    if totals:
        print("Total yardage by tee:")
        for k, v in sorted(totals.items(), key=lambda kv: kv[0].lower()):
            print(f"  {k}: {v} yd")
    else:
        print("No tee data found for these holes.")

def list_with_index(items, fmt=lambda x: x):
    for i, it in enumerate(items, 1):
        print(f"[{i}] {fmt(it)}")

# ---------------- CLI ----------------

print("Choose search mode:")
print("  [1] Search by course name")
print("  [2] Search by tee color yardage range (sum across holes)")
print("  [3] Search by country")
mode = (input("Enter 1, 2 or 3: ").strip() or "1")

# ----- Mode 1: search by course name -----
if mode == "1":
    query = input("Enter part of the course name to search: ").strip().lower()
    matches = [c for c in courses if query in c["name"].lower()]

    if not matches:
        print("No courses matched that name.")
        sys.exit(0)

    print("\nCourses found:")
    list_with_index(matches, fmt=lambda c: c["name"])

    choice = input("\nSelect a course by number: ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(matches):
        selected_course = matches[int(choice) - 1]
        print(f"\nSelected: {selected_course['name']}")
        print(f"Holes: {selected_course.get('holes')}, Par: {selected_course.get('par')}, Yardage: {selected_course.get('yardage')}")

        totals = compute_tee_totals(selected_course)
        if totals:
            print("\nTee totals (sum of distances across holes):")
            for k, v in sorted(totals.items(), key=lambda kv: kv[0].lower()):
                print(f"  {k}: {v} yd")

        hole_input = input("\nEnter hole numbers (e.g. 1-9, 3,5,7): ").strip()
        holes = parse_hole_input(hole_input, total_holes=selected_course.get("holes"))
        display_hole_sums(selected_course, holes)
    else:
        print("Invalid choice.")
    sys.exit(0)

# ----- Mode 2: tee yardage -----
if mode == "2":
    tee_color = input("Tee color/name (e.g. Blue, White, Black): ").strip()
    yardage_text = input("Yardage range (e.g. 6000-6500, >=6200, <=6800, or 6400): ").strip()
    lo, hi = parse_yardage_range(yardage_text)

    if not tee_color:
        print("No tee color provided.")
        sys.exit(0)

    matches = []
    for c in courses:
        totals = compute_tee_totals(c)
        match_key = next((k for k in totals.keys() if k.lower() == tee_color.lower()), None)
        if not match_key:
            continue
        total_yd = totals[match_key]
        if within_range(total_yd, lo, hi):
            matches.append((c, match_key, total_yd))

    if not matches:
        print("No courses matched that tee yardage range.")
        sys.exit(0)

    matches.sort(key=lambda x: x[2])
    print("\nCourses matching tee yardage:")
    list_with_index(matches, fmt=lambda m: f"{m[0]['name']} — {m[1]}: {m[2]} yd")

    choice = input("\nSelect a course by number to view holes (or Enter to exit): ").strip()
    if choice.isdigit():
        idx = int(choice)
        if 1 <= idx <= len(matches):
            selected_course = matches[idx - 1][0]
            print(f"\nSelected: {selected_course['name']}")
            holes_str = input("Enter hole numbers (e.g. 1-9, 3,5,7): ").strip()
            holes = parse_hole_input(holes_str, total_holes=selected_course.get("holes"))
            display_hole_sums(selected_course, holes)
    sys.exit(0)

# ----- Mode 3: country filter -----
if mode == "3":
    raw = input("Enter country name or 3-letter code (leave blank for all): ").strip()
    country = normalize_country(raw)

    if country:
        matches = [c for c in courses if country.lower() in (c.get("country") or "").lower()]
    else:
        matches = courses[:]  # no filter → all courses

    if not matches:
        print("No matches found for that country.")
        sys.exit(0)

    tee_color = input("Tee color/name (optional, e.g. Blue, White, Black — leave blank for all): ").strip()
    yardage_text = input("Enter yardage range for filtering (e.g. 6000-6500, >=6200, <=6800, or 6400): ").strip()
    lo, hi = parse_yardage_range(yardage_text)

    filtered = []
    for c in matches:
        if tee_color:  # filter by tee totals
            totals = compute_tee_totals(c)
            match_key = next((k for k in totals.keys() if k.lower() == tee_color.lower()), None)
            if not match_key:
                continue
            total_yd = totals[match_key]
            if within_range(total_yd, lo, hi):
                filtered.append((c, match_key, total_yd))
        else:  # fallback to course yardage
            yd = c.get("yardage")
            if within_range(yd, lo, hi):
                filtered.append((c, None, yd))

    if not filtered:
        print("No courses matched that filter in this country.")
        sys.exit(0)

    print("\nCourses found:")
    if tee_color:
        list_with_index(filtered, fmt=lambda m: f"{m[0]['name']} ({m[0].get('country')}) — {m[1]}: {m[2]} yd")
    else:
        list_with_index(filtered, fmt=lambda m: f"{m[0]['name']} ({m[0].get('country')}) — {m[2]} yd")

    choice = input("\nSelect a course by number: ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(filtered):
        selected_course, tee_key, yardage = filtered[int(choice) - 1]
        print(f"\nSelected: {selected_course['name']} ({selected_course.get('country')})")
        print(f"Holes: {selected_course.get('holes')}, Par: {selected_course.get('par')}, Yardage: {selected_course.get('yardage')}")

        totals = compute_tee_totals(selected_course)
        if totals:
            print("\nTee totals (sum of distances across holes):")
            for k, v in sorted(totals.items(), key=lambda kv: kv[0].lower()):
                print(f"  {k}: {v} yd")

        holes_str = input("\nEnter hole numbers (e.g. 1-9, 3,5,7): ").strip()
        holes = parse_hole_input(holes_str, total_holes=selected_course.get("holes"))
        display_hole_sums(selected_course, holes)
    sys.exit(0)


print("\nCourses found:")
list_with_index(matches, fmt=lambda c: c["name"])

choice = input("\nSelect a course by number: ").strip()
if choice.isdigit() and 1 <= int(choice) <= len(matches):
    selected_course = matches[int(choice) - 1]
    print(f"\nSelected: {selected_course['name']}")
    print(f"Holes: {selected_course.get('holes')}, Par: {selected_course.get('par')}, Yardage: {selected_course.get('yardage')}")

    totals = compute_tee_totals(selected_course)
    if totals:
        print("\nTee totals (sum of distances across holes):")
        for k, v in sorted(totals.items(), key=lambda kv: kv[0].lower()):
            print(f"  {k}: {v} yd")

    hole_input = input("\nEnter hole numbers (e.g. 1-9, 3,5,7): ").strip()
    holes = parse_hole_input(hole_input, total_holes=selected_course.get("holes"))
    display_hole_sums(selected_course, holes)
else:
    print("Invalid choice.")
