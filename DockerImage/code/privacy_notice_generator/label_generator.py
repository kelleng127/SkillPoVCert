"""
label_generator.py
------------------
Reads SkillPoV pipeline outputs and generates an Apple-style privacy nutrition
label PNG for each Alexa skill.

Focus: Match permissions declared in skill.json manifest against data
       collection practices extracted from skill source code by SkillPoV.

Pipeline:
  1. Read data_collection_results/final/<author>~~<skill>~~report.txt
  2. Read dataset/results/<skill_folder>/skill.json -> manifest_file
  3. Parse manifest for declared permissions
  4. Send both to ChatGPT to get structured JSON comparing the two
  5. Draw Apple-style label and save as PNG to dataset/labels/

Usage (from SkillPoV root):
    python3 DockerImage/code/label_generator.py

Output:
    dataset/labels/<author>~~<skill>_label.png
"""

import os
import sys
import json
import re
import textwrap

# ── path bootstrap ────────────────────────────────────────────────────────────
_here        = os.path.dirname(os.path.abspath(__file__))
_root        = os.path.dirname(os.path.dirname(os.path.dirname(_here)))
_dataset     = os.path.join(_root, "dataset")
FINAL_PATH   = os.path.join(_dataset, "data_collection_results", "final")
RESULTS_PATH = os.path.join(_dataset, "results")
LABELS_PATH  = os.path.join(_dataset, "labels")
os.makedirs(LABELS_PATH, exist_ok=True)

# ── third-party imports ───────────────────────────────────────────────────────
try:
    import openai
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch
except ImportError as e:
    sys.exit(f"[ERROR] Missing dependency: {e}\n"
             "Run:  pip install openai matplotlib")

# ── OpenAI key (read from chatGPT_summary.py) ────────────────────────────────
_summary_py = os.path.join(_here, "privacy_notice_generator", "chatGPT_summary.py")
openai.api_key = "'YOUR_API_KEY_HERE'"
if os.path.exists(_summary_py):
    for line in open(_summary_py):
        if "api_key" in line and "=" in line:
            m = re.search(r'["\']([sk]-[^"\']+)["\']', line)
            if m:
                openai.api_key = m.group(1)
if not openai.api_key:
    sys.exit("[ERROR] OpenAI API key not found. Set it in chatGPT_summary.py line 6.")

# ── permission -> friendly name map ──────────────────────────────────────────
PERMISSION_MAP = {
    "alexa::profile:name:read":                               "Full Name",
    "alexa::profile:given_name:read":                         "First Name",
    "alexa::profile:email:read":                              "Email Address",
    "alexa::profile:mobile_number:read":                      "Phone Number",
    "alexa::devices:all:address:full:read":                   "Device Address",
    "alexa:devices:all:address:country_and_postal_code:read": "Postal Code",
    "alexa::devices:all:geolocation:read":                    "Geolocation",
    "alexa::alerts:reminders:skill:readwrite":                "Reminders",
    "alexa::lists:read":                                      "Shopping/To-do Lists",
    "alexa::lists:write":                                     "Shopping/To-do Lists (write)",
}

# permission API -> data type keyword (for matching)
PERMISSION_DATA_TYPE = {
    "alexa::profile:name:read":                               "name",
    "alexa::profile:given_name:read":                         "name",
    "alexa::profile:email:read":                              "email",
    "alexa::profile:mobile_number:read":                      "number",
    "alexa::devices:all:address:full:read":                   "address",
    "alexa:devices:all:address:country_and_postal_code:read": "postal code",
    "alexa::devices:all:geolocation:read":                    "location",
    "alexa::alerts:reminders:skill:readwrite":                "reminder",
    "alexa::lists:read":                                      "list",
    "alexa::lists:write":                                     "list",
}

def friendly_permission(perm):
    return PERMISSION_MAP.get(
        perm, perm.split(":")[-1].replace("_", " ").title()
    )

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 – discover skills
# ─────────────────────────────────────────────────────────────────────────────
def discover_skills():
    skills = []
    if not os.path.isdir(FINAL_PATH):
        sys.exit(f"[ERROR] final/ folder not found at {FINAL_PATH}.\n"
                 "Run scan_skills.py then main.py first.")
    for fname in os.listdir(FINAL_PATH):
        if not fname.endswith("~~report.txt"):
            continue
        stem  = fname[: -len("~~report.txt")]
        parts = stem.split("~~")
        if len(parts) < 2:
            continue
        author, skill = parts[0], parts[1]
        skills.append({
            "author":      author,
            "skill":       skill,
            "report_path": os.path.join(FINAL_PATH, fname),
            "label_path":  os.path.join(LABELS_PATH,
                                        f"{author}~~{skill}_label.png"),
        })
    return skills

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 – load permissions from manifest
# ─────────────────────────────────────────────────────────────────────────────
def load_permissions(author, skill):
    permissions = []
    for folder in os.listdir(RESULTS_PATH):
        if author not in folder or skill not in folder:
            continue
        skill_json_path = os.path.join(RESULTS_PATH, folder, "skill.json")
        if not os.path.exists(skill_json_path):
            continue
        try:
            skill_data    = json.loads(open(skill_json_path).read())
            manifest_file = skill_data.get("manifest_file", "")
            if not manifest_file or not os.path.exists(manifest_file):
                break
            raw     = json.loads(open(manifest_file).read())
            content = raw.get("manifest", raw.get("skillManifest", {}))
            for p in content.get("permissions", []):
                permissions.append(p.get("name", ""))
        except Exception:
            pass
        break
    return permissions

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 – local matching (permissions vs extracted data collection)
# ─────────────────────────────────────────────────────────────────────────────
def match_permissions_to_collection(permissions, report_text):
    """
    For each permission declared in the manifest, check whether the
    corresponding data type appears in the SkillPoV extraction report.
    Returns three lists:
        matched   - permissions whose data type was also found in code
        unmatched - permissions declared but NOT found in code (over-declared)
        code_only - data types found in code but NOT covered by any permission
    """
    report_lower = report_text.lower()

    # data types found by SkillPoV in code
    code_data_types = set()
    known_types = ["name", "age", "email", "location", "address",
                   "birthday", "gender", "number", "postal code",
                   "zip code", "phone", "income", "ssn", "ethnicity"]
    for dt in known_types:
        if dt in report_lower:
            code_data_types.add(dt)

    matched   = []
    unmatched = []
    covered   = set()

    for perm in permissions:
        data_type = PERMISSION_DATA_TYPE.get(perm, "")
        if data_type and any(data_type in c for c in code_data_types):
            matched.append(perm)
            covered.add(data_type)
        else:
            unmatched.append(perm)

    # data types in code not covered by any permission
    code_only = [dt for dt in code_data_types
                 if not any(dt in PERMISSION_DATA_TYPE.get(p, "")
                            for p in permissions)]

    return matched, unmatched, code_only

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 – ask ChatGPT for structured summary of extracted data types
# ─────────────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """
You are a privacy analyst reviewing an Alexa skill data-collection report
produced by static code analysis.

Return ONLY a JSON object with this exact schema (no markdown, no extra text):

{
  "data_types": ["list of specific data types collected via conversation, e.g. name, age, location"],
  "collection_methods": ["conversation", "permission_api"],
  "summary": "one sentence plain-English summary of what this skill collects"
}

Be specific and concise. Only include data types explicitly evidenced in the report.
"""

def ask_chatgpt(report_text, permissions):
    perm_str = (", ".join(friendly_permission(p) for p in permissions)
                if permissions else "none")
    user_msg = (
        f"DATA COLLECTION REPORT (from static code analysis):\n{report_text}\n\n"
        f"PERMISSIONS DECLARED IN MANIFEST: {perm_str}"
    )
    try:
        resp = openai.ChatCompletion.create(
            model    = "gpt-3.5-turbo",
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_msg},
            ],
            timeout  = 30,
        )
        raw = resp["choices"][0]["message"]["content"].strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$",        "", raw)
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  [WARN] JSON parse error: {e}. Using defaults.")
    except Exception as e:
        print(f"  [WARN] ChatGPT call failed: {e}. Using defaults.")

    return {
        "data_types":         [],
        "collection_methods": [],
        "summary":            "Analysis unavailable.",
    }

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 – draw the label
# ─────────────────────────────────────────────────────────────────────────────
C_BG     = "#1c1c1e"
C_CARD   = "#2c2c2e"
C_WHITE  = "#ffffff"
C_GRAY   = "#8e8e93"
C_BLUE   = "#0a84ff"
C_GREEN  = "#30d158"
C_RED    = "#ff453a"
C_YELLOW = "#ffd60a"
C_ORANGE = "#ff9f0a"

def pill(ax, x, y, w, h, color, radius=0.15, alpha=1.0):
    box = FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        facecolor=color, edgecolor="none", alpha=alpha,
        transform=ax.transData, zorder=2,
    )
    ax.add_patch(box)

def draw_label(skill_name, author, analysis, permissions,
               matched, unmatched, code_only, out_path):

    fig_w, fig_h = 7, 11
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    fig.patch.set_facecolor(C_BG)
    ax.set_facecolor(C_BG)
    ax.set_xlim(0, fig_w)
    ax.set_ylim(0, fig_h)
    ax.axis("off")

    pad   = 0.35
    inner = fig_w - 2 * pad

    def txt(x, y, s, **kw):
        kw.setdefault("color", C_WHITE)
        kw.setdefault("va", "top")
        kw.setdefault("fontsize", 9)
        ax.text(x, y, s, transform=ax.transData, zorder=3, **kw)

    def hline(y):
        ax.axhline(y, color=C_GRAY, linewidth=0.5, alpha=0.35,
                   xmin=pad / fig_w, xmax=(fig_w - pad) / fig_w)

    def section_header(y, label):
        txt(pad + 0.1, y, label,
            fontsize=8, color=C_GRAY, fontweight="bold",
            fontfamily="monospace")
        return y - 0.30

    def chips_row(start_x, start_y, labels, color):
        x, y = start_x, start_y
        for label in labels:
            est_w = len(label) * 0.115 + 0.35
            if x + est_w > fig_w - pad:
                x  = start_x
                y -= 0.35
            pill(ax, x, y - 0.24, est_w, 0.26, color, radius=0.10)
            txt(x + 0.12, y - 0.05, label,
                fontsize=8, color=C_WHITE, fontweight="bold")
            x += est_w + 0.12
        return y - 0.38

    # ── HEADER ────────────────────────────────────────────────────────────────
    y = fig_h - pad
    pill(ax, pad, y - 0.62, inner, 0.72, C_CARD, radius=0.2)
    txt(pad + 0.22, y - 0.10,
        "Privacy Nutrition Label",
        fontsize=10, color=C_GRAY, fontstyle="italic")

    display = skill_name.replace("-", " ").replace("_", " ").title()
    wrapped = textwrap.fill(display, width=34)
    y -= 0.60
    txt(pad + 0.22, y, wrapped,
        fontsize=14, fontweight="bold", linespacing=1.3)
    y -= 0.18 * (1 + wrapped.count("\n"))
    txt(pad + 0.22, y - 0.05, f"by {author}",
        fontsize=8.5, color=C_GRAY)
    y -= 0.40

    hline(y); y -= 0.22

    # ── CONSISTENCY BADGE ─────────────────────────────────────────────────────
    if len(permissions) == 0 and len(code_only) == 0:
        badge_label = "✓  CONSISTENT  —  No Data Collection"
        badge_sub   = ("No permissions requested and no data collection "
                       "detected in code.")
        badge_color = C_GREEN
    elif len(unmatched) == 0 and len(code_only) == 0 and permissions:
        badge_label = "✓  CONSISTENT"
        badge_sub   = ("All declared permissions match data collection "
                       "found in code.")
        badge_color = C_GREEN
    elif len(unmatched) > 0 and len(code_only) == 0:
        badge_label = "⚠  OVER-DECLARED"
        badge_sub   = ("Manifest declares permissions not evidenced "
                       "in code.")
        badge_color = C_YELLOW
    elif len(code_only) > 0 and len(unmatched) == 0:
        badge_label = "✗  UNDER-DECLARED"
        badge_sub   = ("Code collects data not covered by any "
                       "manifest permission.")
        badge_color = C_RED
    else:
        badge_label = "✗  INCONSISTENT"
        badge_sub   = ("Mismatches found between manifest permissions "
                       "and code behavior.")
        badge_color = C_RED

    pill(ax, pad, y - 0.52, inner, 0.62, badge_color, alpha=0.15, radius=0.2)
    pill(ax, pad, y - 0.52, 0.07,  0.62, badge_color, radius=0.12)
    txt(pad + 0.20, y - 0.06, badge_label,
        fontsize=12, color=badge_color, fontweight="bold")
    txt(pad + 0.20, y - 0.30,
        textwrap.fill(badge_sub, width=54),
        fontsize=8, color=C_GRAY, linespacing=1.3)
    y -= 0.75

    hline(y); y -= 0.22

    # ── SUMMARY ───────────────────────────────────────────────────────────────
    y = section_header(y, "SKILL SUMMARY")
    summary = textwrap.fill(analysis.get("summary", "N/A"), width=60)
    txt(pad + 0.1, y, summary,
        fontsize=9, color=C_WHITE, linespacing=1.4)
    y -= 0.20 * (1 + summary.count("\n")) + 0.20

    hline(y); y -= 0.22

    # ── DATA COLLECTED IN CODE ────────────────────────────────────────────────
    y = section_header(y, "DATA COLLECTED  (detected in source code)")
    data_types = analysis.get("data_types", [])
    if data_types:
        y = chips_row(pad + 0.1, y, [d.title() for d in data_types], C_BLUE)
    else:
        txt(pad + 0.1, y, "No personal data collection detected.",
            color=C_GREEN)
        y -= 0.35

    methods = analysis.get("collection_methods", [])
    if methods:
        txt(pad + 0.1, y,
            "Via: " + ", ".join(m.replace("_", " ").title()
                                for m in methods),
            fontsize=8, color=C_GRAY, fontstyle="italic")
        y -= 0.30

    hline(y); y -= 0.22

    # ── PERMISSIONS IN MANIFEST ───────────────────────────────────────────────
    y = section_header(y, "PERMISSIONS DECLARED IN MANIFEST")
    if permissions:
        for perm in permissions:
            friendly  = friendly_permission(perm)
            is_match  = perm in matched
            dot_color = C_GREEN if is_match else C_YELLOW
            pill(ax, pad + 0.10, y - 0.20, 0.13, 0.22, dot_color, radius=0.08)
            txt(pad + 0.33, y,       friendly,
                fontsize=9, fontweight="bold")
            txt(pad + 0.33, y - 0.18, perm,
                fontsize=6.5, color=C_GRAY, fontstyle="italic")
            match_label = "matched in code" if is_match else "not found in code"
            txt(fig_w - pad - 0.1, y - 0.08, match_label,
                fontsize=7.5,
                color=C_GREEN if is_match else C_YELLOW,
                ha="right")
            y -= 0.44
    else:
        txt(pad + 0.1, y, "No permissions declared in manifest.",
            color=C_GRAY)
        y -= 0.35

    hline(y); y -= 0.22

    # ── UNDECLARED COLLECTION ─────────────────────────────────────────────────
    y = section_header(y, "UNDECLARED DATA COLLECTION  (in code, no permission)")
    if code_only:
        y = chips_row(pad + 0.1, y,
                      [d.title() for d in code_only], C_RED)
        txt(pad + 0.1, y,
            "These data types were found in code but have no\n"
            "corresponding permission declared in the manifest.",
            fontsize=8, color=C_GRAY, linespacing=1.4)
        y -= 0.42
    else:
        txt(pad + 0.1, y,
            "All detected data collection is covered by manifest permissions.",
            color=C_GREEN)
        y -= 0.35

    # ── FOOTER ────────────────────────────────────────────────────────────────
    hline(0.28)
    txt(fig_w / 2, 0.15,
        "Generated by SkillCert  •  Powered by SkillPoV",
        fontsize=7.5, color=C_GRAY, ha="center", fontstyle="italic")

    plt.tight_layout(pad=0)
    plt.savefig(out_path, dpi=180, bbox_inches="tight", facecolor=C_BG)
    plt.close(fig)
    print(f"  [OK] Saved → {out_path}")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    skills = discover_skills()
    if not skills:
        sys.exit(f"[ERROR] No report files found in {FINAL_PATH}.\n"
                 "Run scan_skills.py then main.py first.")

    print(f"Found {len(skills)} skill(s). Generating labels...\n")

    for s in skills:
        author, skill_name = s["author"], s["skill"]
        print(f"Processing: {author}/{skill_name}")

        report_text = open(s["report_path"]).read().strip()
        if not report_text:
            print("  [SKIP] Empty report.")
            continue

        permissions = load_permissions(author, skill_name)
        matched, unmatched, code_only = match_permissions_to_collection(
            permissions, report_text
        )

        print(f"  Permissions declared : {len(permissions)}")
        print(f"  Matched in code      : {len(matched)}")
        print(f"  Not found in code    : {len(unmatched)}")
        print(f"  In code, undeclared  : {len(code_only)}")

        print("  Calling ChatGPT for structured summary...")
        analysis = ask_chatgpt(report_text, permissions)

        draw_label(
            skill_name  = skill_name,
            author      = author,
            analysis    = analysis,
            permissions = permissions,
            matched     = matched,
            unmatched   = unmatched,
            code_only   = code_only,
            out_path    = s["label_path"],
        )

    print(f"\nDone. Labels saved to: {LABELS_PATH}")

if __name__ == "__main__":
    main()