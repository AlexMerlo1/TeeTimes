import json

with open("golf_courses.json", "r") as f:
    courses = json.load(f)

def parse_hole_input(hole_input, total_holes=None):
    """
    Convert input like '1,3,5-9' into a list of ints.
    """
    holes = set()
    parts = hole_input.split(",")
    for part in parts:
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            if start.isdigit() and end.isdigit():
                for h in range(int(start), int(end) + 1):
                    if not total_holes or h <= total_holes:
                        holes.add(h)
        elif part.isdigit():
            h = int(part)
            if not total_holes or h <= total_holes:
                holes.add(h)
    return sorted(holes)

def display_hole_info(course, holes):
    print(f"\nCourse: {course['name']}\n")
    for hole_num in holes:
        hole = course["per_hole"].get(str(hole_num))
        if hole:
            print(f"Hole {hole_num}: Par {hole['par']}")
            for tee in hole.get("tees", []):
                print(f"  {tee['tee']}: {tee['distance']} yards (height: {tee['height']})")
        else:
            print(f"Hole {hole_num} not found.")

if __name__ == "__main__":
    keyword = input("Enter part of a course name to search: ").strip().lower()

    # Find matching courses
    matches = [c for c in courses if keyword in c["name"].lower()]

    if not matches:
        print("No matches found.")
    else:
        print("\nCourses found:")
        for i, course in enumerate(matches, 1):
            print(f"[{i}] {course['name']}")

        choice = input("\nSelect a course by number: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(matches):
            selected_course = matches[int(choice) - 1]

            print(f"\nSelected: {selected_course['name']}")
            print(f"Holes: {selected_course['holes']}, Par: {selected_course['par']}, Yardage: {selected_course['yardage']}")

            hole_input = input("\nEnter hole numbers (e.g. 1-9, 3,5,7): ").strip()
            holes = parse_hole_input(hole_input, total_holes=selected_course.get("holes"))
            display_hole_info(selected_course, holes)
        else:
            print("Invalid choice.")
