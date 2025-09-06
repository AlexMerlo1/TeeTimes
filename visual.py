import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st

# ---------- Config ----------
JSON_PATH_DEFAULT = "golf_courses.json"
NUM_RE = re.compile(r"-?\d+(?:[\d,]*\d)?(?:\.\d+)?")

try:
    from golfzon_scraper import COUNTRY_MAP as _COUNTRY_MAP
    COUNTRY_MAP = dict(_COUNTRY_MAP)
except Exception:
    COUNTRY_MAP = {}

# ---------- Helpers ----------
def parse_hole_input(hole_input, total_holes=None):
    """Convert input like '1,3,5-9' into a sorted list of ints."""
    holes = set()
    for part in (hole_input or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            if start.strip().isdigit() and end.strip().isdigit():
                a, b = int(start), int(end)
                if a > b:
                    a, b = b, a
                for h in range(a, b + 1):
                    if not total_holes or h <= int(total_holes):
                        holes.add(h)
        elif part.isdigit():
            h = int(part)
            if not total_holes or h <= int(total_holes):
                holes.add(h)
    return sorted(holes)

def normalize_country(input_str):
    """Return standardized full country name if match, else the original string."""
    if not input_str:
        return None
    key = input_str.strip().upper()
    # If it's a code, map directly
    if key in COUNTRY_MAP:
        return COUNTRY_MAP[key]
    for code, name in COUNTRY_MAP.items():
        if key.lower() == str(name).lower():
            return name
    return input_str

def to_int_maybe(x):
    if x is None:
        return None
    s = str(x).replace(",", "")
    m = NUM_RE.search(s)
    if not m:
        return None
    try:
        return int(float(m.group(0)))
    except ValueError:
        return None

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
        if a and b and a > b:
            a, b = b, a
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
    if a > b:
        a, b = b, a
    return (a, b)

def within_range(val, lo, hi):
    if val is None:
        return False
    if lo is not None and val < lo:
        return False
    if hi is not None and val > hi:
        return False
    return True

def flatten_courses(courses):
    """Return a DataFrame with one row per (course, hole, tee)."""
    rows = []
    for c in courses:
        per_hole = c.get("per_hole") or {}
        for hole_no, hole_data in per_hole.items():
            for tee in (hole_data.get("tees") or []):
                rows.append({
                    "Course": c.get("name"),
                    "Country": c.get("country"),
                    "URL": c.get("url"),
                    "TotalHoles": c.get("holes"),
                    "CoursePar": c.get("par"),
                    "CourseYardage": c.get("yardage"),
                    "Hole": int(hole_no),
                    "Par": hole_data.get("par"),
                    "Tee": tee.get("tee"),
                    "Distance": to_int_maybe(tee.get("distance")),
                    "Elevation": tee.get("height")
                })
    if not rows:
        return pd.DataFrame(columns=[
            "Course","Country","URL","TotalHoles","CoursePar","CourseYardage",
            "Hole","Par","Tee","Distance","Elevation"
        ])
    return pd.DataFrame(rows)

def load_courses_from_source(file_uploader, path_default=JSON_PATH_DEFAULT):
    """Load courses from uploaded file or local path."""
    if file_uploader is not None:
        try:
            data = json.load(file_uploader)
            if not isinstance(data, list):
                st.error("Uploaded JSON must be a list of course objects.")
                return []
            return data
        except Exception as e:
            st.error(f"Failed to parse uploaded JSON: {e}")
            return []

    p = Path(path_default)
    if not p.exists():
        st.warning(f"No file uploaded and default path not found: {p.resolve()}")
        return []
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            st.error("Local JSON must be a list of course objects.")
            return []
        return data
    except Exception as e:
        st.error(f"Error reading local JSON: {e}")
        return []

def course_card(course_obj):
    totals = compute_tee_totals(course_obj)
    with st.expander(f"{course_obj.get('name')}  —  {course_obj.get('country')}  |  "
                     f"{course_obj.get('holes')} holes  |  Par {course_obj.get('par')}  |  "
                     f"{course_obj.get('yardage')} yds", expanded=False):
        cols = st.columns(2)
        with cols[0]:
            st.markdown("**Tee totals (yd):**")
            if totals:
                st.table(pd.DataFrame(
                    [{"Tee": k, "TotalYardage": v} for k, v in sorted(totals.items())]
                ))
            else:
                st.write("_No tee data_")
        with cols[1]:
            if course_obj.get("url"):
                st.markdown(f"[Open course page]({course_obj['url']})")
            st.markdown("**Meta:**")
            st.write({
                "Holes": course_obj.get("holes"),
                "Par": course_obj.get("par"),
                "Course Yardage": course_obj.get("yardage"),
                "Country": course_obj.get("country"),
            })

# ---------- UI ----------
st.set_page_config(page_title="Golf Course Easy Search", page_icon="🏌️", layout="wide")
st.title("Golf Course Easy Search")

with st.sidebar:
    st.header("Data")
    up = st.file_uploader("Upload golf_courses.json", type=["json"])
    st.caption("If you don’t upload, the app will look for `golf_courses.json` in the same folder.")
    st.divider()
courses = load_courses_from_source(up)
if not courses:
    st.stop()

df = flatten_courses(courses)
all_courses = sorted(df["Course"].dropna().unique().tolist())
all_countries = sorted(df["Country"].dropna().unique().tolist())
all_tees = sorted(df["Tee"].dropna().unique().tolist())

# ---------- Unified Filters ----------
st.sidebar.header("Filters")
q_name = st.sidebar.text_input("Course name contains (optional):", "")
raw = st.sidebar.text_input("Country name or 3-letter code (leave blank for all):", "")
country = normalize_country(raw)
tee_color = st.sidebar.selectbox("Tee color (optional):", ["(all)"] + all_tees, index=0)
yardage_text = st.sidebar.text_input("Yardage range (optional):", "")
lo, hi = parse_yardage_range(yardage_text)

# ---------- Apply Filters ----------
course_list = []
for c in courses:
    # filter by name
    if q_name and q_name.lower() not in str(c.get("name", "")).lower():
        continue
    # filter by country
    if country and country.lower() not in str(c.get("country", "")).lower():
        continue
    course_list.append(c)

# tee & yardage filters
filtered = []
for c in course_list:
    if tee_color != "(all)":
        totals = compute_tee_totals(c)
        key = next((k for k in totals.keys() if str(k).lower() == tee_color.lower()), None)
        if not key:
            continue
        total_yd = totals[key]
        if within_range(total_yd, lo, hi):
            filtered.append((c, key, total_yd))
    else:
        yd = c.get("yardage")
        if within_range(yd, lo, hi):
            filtered.append((c, None, yd))

# ---------- Results ----------
st.subheader(f"Results ({len(filtered)})")
if tee_color != "(all)":
    disp = pd.DataFrame([
        {"Course": m[0].get("name"), "Country": m[0].get("country"),
         "Tee": m[1], "TotalYardage(yds)": m[2], "Par": m[0].get("par"),
         "Holes": m[0].get("holes"), "URL": m[0].get("url")}
        for m in filtered
    ])
else:
    disp = pd.DataFrame([
        {"Course": m[0].get("name"), "Country": m[0].get("country"),
         "CourseYardage(yds)": m[2], "Par": m[0].get("par"),
         "Holes": m[0].get("holes"), "URL": m[0].get("url")}
        for m in filtered
    ])
st.dataframe(disp, use_container_width=True)
st.download_button("Download results (CSV)", disp.to_csv(index=False), "search_results.csv", "text/csv")

# ---------- Course Details ----------
if not disp.empty and "Course" in disp.columns:
    names = disp["Course"].dropna().tolist()
    selected_name = st.selectbox("Pick a course to view selected holes:", ["(none)"] + names)
    if selected_name != "(none)":
        selected_course = next((c for c, *_ in filtered if c.get("name") == selected_name), None)
        if selected_course:
            course_card(selected_course)
            hole_text = st.text_input("Enter hole numbers (e.g. `1-9, 3,5,7`):", "1-18")
            holes = parse_hole_input(hole_text, selected_course.get("holes"))
            per_hole = selected_course.get("per_hole") or {}
            rows = []
            for h in holes:
                hole = per_hole.get(str(h))
                if hole:
                    for t in (hole.get("tees") or []):
                        rows.append({
                            "Hole": h,
                            "Par": hole.get("par"),
                            "Tee": t.get("tee"),
                            "Distance": to_int_maybe(t.get("distance")),
                            "Elevation": t.get("height"),
                        })
            if rows:
                sel_df = pd.DataFrame(rows).sort_values(["Hole","Tee"])
                totals = sel_df.groupby("Tee")["Distance"].sum().reset_index().rename(columns={"Distance":"TotalDistance(yds)"})
                st.markdown("**Total yardage by tee for selected holes:**")
                st.table(totals)
                st.download_button("Download selected holes (CSV)", sel_df.to_csv(index=False), "selected_holes.csv", "text/csv")
            else:
                st.info("No tee data for those holes.")
else:
    st.info("⚠️ No courses available to select.")
