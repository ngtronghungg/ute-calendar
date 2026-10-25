"""
WCAG 2.1 Contrast Ratio Verification Script
Calculates luminance and contrast ratios according to W3C specifications.
"""

def luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip('#')
    r, g, b = [int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4)]
    rgb = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]

def contrast_ratio(hex1: str, hex2: str) -> float:
    l1 = luminance(hex1)
    l2 = luminance(hex2)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)

colors = {
    "--bg": "#161615",
    "--surface": "#1E1D1B",
    "--surface-2": "#262523",
    "--text": "#F1EEE8",
    "--text-muted": "#B3AEA4",
    "--text-subtle": "#8A857C",
    "--accent": "#0072BC",
    "--accent-text": "#6DB3E8",
    "#FFFFFF": "#FFFFFF",
    "--danger": "#E5736B",
    "--ok": "#8FB996",
    "--warn": "#D8B26A",
}

course_colors = [
    ("#6DB3E8", "Course 1 (Sky Blue)"),
    ("#D8B26A", "Course 2 (Warm Gold)"),
    ("#8FB996", "Course 3 (Sage Green)"),
    ("#B9A0D6", "Course 4 (Lavender Purple)"),
    ("#E0927F", "Course 5 (Coral Orange)"),
    ("#7FC4C0", "Course 6 (Light Aqua)"),
    ("#C9B38B", "Course 7 (Warm Sand)"),
    ("#9AA3B5", "Course 8 (Steel Slate)"),
]

def run_checks():
    print("=== WCAG 2.1 Contrast Ratios Verification ===")
    bg = colors["--bg"]
    surface = colors["--surface"]

    checks = [
        ("--text (#F1EEE8) on --bg (#161615)", colors["--text"], bg, 12.0),
        ("--text (#F1EEE8) on --surface (#1E1D1B)", colors["--text"], surface, 10.0),
        ("--text-muted (#B3AEA4) on --bg (#161615)", colors["--text-muted"], bg, 7.0),
        ("--text-muted (#B3AEA4) on --surface (#1E1D1B)", colors["--text-muted"], surface, 6.0),
        ("--text-subtle (#8A857C) on --bg (#161615)", colors["--text-subtle"], bg, 4.5),
        ("--text-subtle (#8A857C) on --surface (#1E1D1B)", colors["--text-subtle"], surface, 4.0),
        ("--accent-text (#6DB3E8) on --bg (#161615)", colors["--accent-text"], bg, 6.0),
        ("--accent-text (#6DB3E8) on --surface (#1E1D1B)", colors["--accent-text"], surface, 5.5),
        ("#FFFFFF on --accent (#0072BC)", "#FFFFFF", colors["--accent"], 4.5),
    ]

    for name, fg_c, bg_c, target in checks:
        ratio = contrast_ratio(fg_c, bg_c)
        passed = "PASS" if ratio >= target else "FAIL"
        print(f"{name:50} -> {ratio:.2f}:1 (Target: >= {target:.1f}:1) [{passed}]")

    print("\n--- Course Colors on --surface (#1E1D1B) (Target >= 3.0:1 for 8px graphical dots/lines) ---")
    for hex_c, desc in course_colors:
        ratio = contrast_ratio(hex_c, surface)
        passed = "PASS" if ratio >= 3.0 else "FAIL"
        print(f"{hex_c} ({desc:28}) -> {ratio:.2f}:1 [{passed}]")

if __name__ == "__main__":
    run_checks()
