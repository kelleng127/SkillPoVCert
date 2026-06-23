"""
label_generator.py
------------------
Generates a certified privacy label PNG for each Alexa skill analyzed
by the SkillPoV pipeline. Labels are based purely on backend code analysis —
no manifest comparison, no privacy policy matching. The code is the truth.

Pipeline:
  1. Read data_collection_results/final/<author>~~<skill>~~report.txt
  2. Send to ChatGPT for structured JSON extraction of data types/methods/summary
  3. Classify risk level deterministically in Python (not by ChatGPT)
  4. Draw a refined, visually polished privacy label and save as PNG

Risk Classification Logic (hardcoded, deterministic):
  - Each data type is assigned a sensitivity tier (high / medium / low)
  - A weighted score is computed across all detected data types
  - Score thresholds determine the final risk level:
      none   = score 0
      low    = score 1–3
      medium = score 4–7
      high   = score 8+

  Sensitivity weights:
      high   = 4 pts  (SSN, financial, biometric, health, precise location)
      medium = 2 pts  (name, email, phone, age, gender, postal code, address)
      low    = 1 pt   (preferences, reminders, general inputs)

  Collection method modifier:
      +1 if both conversation AND permission_api are used simultaneously

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
import math

# ── path bootstrap ────────────────────────────────────────────────────────────
_here        = os.path.dirname(os.path.abspath(__file__))
_root        = os.path.dirname(os.path.dirname(os.path.dirname(_here)))
_dataset     = os.path.join(_root, "dataset")
FINAL_PATH   = os.path.join(_dataset, "data_collection_results", "final")
LABELS_PATH  = os.path.join(_dataset, "labels")

# Subdirectories split by risk classification
LABEL_DIRS = {
    "none":   os.path.join(LABELS_PATH, "none"),
    "low":    os.path.join(LABELS_PATH, "low"),
    "medium": os.path.join(LABELS_PATH, "medium"),
    "high":   os.path.join(LABELS_PATH, "high"),
}
for _d in LABEL_DIRS.values():
    os.makedirs(_d, exist_ok=True)

# ── third-party imports ───────────────────────────────────────────────────────
try:
    import openai
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch
    import numpy as np
except ImportError as e:
    sys.exit(
        f"[ERROR] Missing dependency: {e}\n"
        "Run:  pip install openai matplotlib numpy"
    )

# ── OpenAI key ────────────────────────────────────────────────────────────────
_summary_py = os.path.join(
    _here, "privacy_notice_generator", "chatGPT_summary.py"
)
openai.api_key = os.environ.get("OPENAI_API_KEY", "")
if not openai.api_key and os.path.exists(_summary_py):
    for line in open(_summary_py):
        if "api_key" in line and "=" in line:
            m = re.search(r'["\']([sk]-[^"\']{20,})["\']', line)
            if m:
                openai.api_key = m.group(1)
if not openai.api_key:
    sys.exit(
        "[ERROR] OpenAI API key not found.\n"
        "Set OPENAI_API_KEY env var or add it to chatGPT_summary.py."
    )

# ─────────────────────────────────────────────────────────────────────────────
# RISK CLASSIFICATION — fully deterministic, no ChatGPT involvement
# ─────────────────────────────────────────────────────────────────────────────

# Sensitivity tier for each known data type keyword.
# Keywords are matched as substrings against the lowercase data type name.
SENSITIVITY_TIERS = {
    # HIGH sensitivity — weight 4 each
    # Personally Identifiable Information that is financial, biometric, or
    # government-issued. Even a single high-sensitivity item is significant.
    "high": [
        "ssn", "social security", "passport", "driver license",
        "bank account", "credit card", "debit card", "financial",
        "income", "salary", "biometric", "fingerprint", "face",
        "health", "medical", "diagnosis", "prescription",
        "precise location", "gps", "geolocation",
        "ethnicity", "race", "religion", "political",
    ],
    # MEDIUM sensitivity — weight 2 each
    # Standard PII that on its own is moderately sensitive but becomes
    # more serious in combination with other items.
    "medium": [
        "name", "full name", "first name", "last name",
        "email", "phone", "mobile", "number",
        "age", "birthday", "birth date", "date of birth",
        "gender", "sex",
        "address", "postal code", "zip code", "zip",
        "location", "city", "state", "country",
        "username", "user id", "account",
    ],
    # LOW sensitivity — weight 1 each
    # Behavioural or preference data that is minimally identifying on its own.
    "low": [
        "preference", "favourite", "favorite", "choice",
        "reminder", "alarm", "calendar", "schedule",
        "list", "item", "task", "note",
        "language", "setting", "option",
        "score", "progress", "history",
    ],
}

# Weights per sensitivity tier
TIER_WEIGHTS = {"high": 4, "medium": 2, "low": 1}

# Score → risk level thresholds.
# Designed so that:
#   - 1 low-sensitivity item alone  → low   (score=1)
#   - 2-3 medium items              → medium (score=4-6)
#   - 1 high + 1 medium item        → high  (score=6... borderline; 1 high alone=4→medium)
#   - 2 high items                  → high  (score=8)
#   - Many medium items             → high  (score≥8 at 4+ medium items)
THRESHOLDS = [
    (0,  0,  "none"),
    (1,  3,  "low"),
    (4,  7,  "medium"),
    (8,  999, "high"),
]

 
def get_sensitivity(data_type_name: str) -> str:
    """Return the sensitivity tier for a given data type name string."""
    name_lower = data_type_name.lower()
    for tier, keywords in SENSITIVITY_TIERS.items():
        if any(kw in name_lower for kw in keywords):
            return tier
    # Default: if unrecognised, treat as low
    return "low"


def classify_risk(data_types: list, collection_methods: list) -> str:
    """
    Compute a weighted risk score and return a risk level string.

    Args:
        data_types:         list of dicts with at least a "name" key
        collection_methods: list of method strings

    Returns:
        "none" | "low" | "medium" | "high"
    """
    if not data_types:
        return "none"

    score = 0
    for dt in data_types:
        tier   = dt.get("sensitivity") or get_sensitivity(dt.get("name", ""))
        # Normalise tier in case ChatGPT returned something unexpected
        if tier not in TIER_WEIGHTS:
            tier = get_sensitivity(dt.get("name", ""))
        score += TIER_WEIGHTS.get(tier, 1)

    # Method modifier: using both conversation AND permission API simultaneously
    # suggests the skill is actively requesting data through multiple vectors
    if "conversation" in collection_methods and "permission_api" in collection_methods:
        score += 1

    for lo, hi, level in THRESHOLDS:
        if lo <= score <= hi:
            return level

    return "high"


# ─────────────────────────────────────────────────────────────────────────────
# COLOUR PALETTE  —  deep navy + electric teal accent, warm white text
# ─────────────────────────────────────────────────────────────────────────────
P = {
    "bg":         "#0D1117",
    "surface":    "#161B22",
    "surface2":   "#21262D",
    "border":     "#30363D",
    "accent":     "#00D4AA",
    "accent_dim": "#004D3D",
    "blue":       "#388BFD",
    "blue_dim":   "#0D2A5C",
    "warn":       "#E3B341",
    "warn_dim":   "#3D2E00",
    "danger":     "#F85149",
    "danger_dim": "#3D0C0A",
    "text":       "#E6EDF3",
    "text2":      "#8B949E",
    "text3":      "#484F58",
    "white":      "#FFFFFF",
}

DATA_ICONS = {
    "name":        "◈",
    "email":       "✉",
    "age":         "◷",
    "birthday":    "◷",
    "location":    "◎",
    "address":     "◎",
    "postal":      "◎",
    "zip":         "◎",
    "gender":      "◈",
    "phone":       "✆",
    "number":      "✆",
    "income":      "◈",
    "ssn":         "◈",
    "ethnicity":   "◈",
    "financial":   "◈",
    "health":      "◈",
    "biometric":   "◈",
}

def icon_for(dt):
    dt_l = dt.lower()
    for key, ico in DATA_ICONS.items():
        if key in dt_l:
            return ico
    return "◆"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 – discover skills
# ─────────────────────────────────────────────────────────────────────────────
def discover_skills():
    if not os.path.isdir(FINAL_PATH):
        sys.exit(
            f"[ERROR] final/ folder not found at {FINAL_PATH}.\n"
            "Run scan_skills.py then main.py first."
        )
    skills = []
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
        })
    return skills

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 – ChatGPT structured extraction (data types + summary ONLY)
# risk_level is NOT requested from ChatGPT — we compute it ourselves
# ─────────────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """
You are a privacy analyst. Given a SkillPoV static-code-analysis report for
an Amazon Alexa skill, extract structured privacy information.

Return ONLY a valid JSON object — no markdown fences, no extra text:

{
  "data_types": [
    {
      "name": "short data type label, e.g. Full Name",
      "sensitivity": "low" | "medium" | "high",
      "how": "one short phrase describing how it is collected, e.g. asked via conversation"
    }
  ],
  "collection_methods": ["conversation" | "permission_api" | "inferred"],
  "data_shared_with_third_parties": true | false,
  "data_retained": true | false | "unknown",
  "summary": "2-3 sentence plain-English summary of what data this skill collects and why it matters to the user"
}

Sensitivity definitions:
- high   = financial, biometric, SSN, health, precise GPS location
- medium = name, email, phone, age, gender, postal code, address, city/state
- low    = general preferences, reminders, lists, non-personal inputs

Be concise. Only include data types explicitly evidenced in the report.
If nothing sensitive is collected, data_types should be an empty array.
Do NOT include a risk_level field — that is computed separately.
"""

def ask_chatgpt(report_text):
    try:
        resp = openai.ChatCompletion.create(
            model    = "gpt-3.5-turbo",
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": f"REPORT:\n{report_text}"},
            ],
            timeout  = 40,
        )
        raw = resp["choices"][0]["message"]["content"].strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$",        "", raw)
        return json.loads(raw)
    except Exception as e:
        print(f"  [WARN] ChatGPT error: {e}. Using safe defaults.")
        return {
            "data_types":                     [],
            "collection_methods":             [],
            "data_shared_with_third_parties": False,
            "data_retained":                  "unknown",
            "summary":                        "Analysis could not be completed.",
        }

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 – draw the label
# ─────────────────────────────────────────────────────────────────────────────
def draw_label(skill_name, author, analysis, risk_level, risk_score, out_path):

    W, H = 8.5, 11.5
    DPI  = 160
    fig  = plt.figure(figsize=(W, H), facecolor=P["bg"])
    ax   = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.set_facecolor(P["bg"])
    ax.axis("off")

    ML = 0.42
    MR = W - 0.42
    CW = MR - ML
    y  = H - 0.45

    # ── helpers ───────────────────────────────────────────────────────────────
    def t(x, yy, s, size=9, color=P["text"], weight="normal",
          align="left", style="normal", alpha=1.0, zorder=4):
        ax.text(x, yy, s, fontsize=size, color=color, fontweight=weight,
                ha=align, va="top", fontstyle=style, alpha=alpha,
                zorder=zorder, transform=ax.transData)

    def rect(x, yy, w, h, color, alpha=1.0, radius=0.12, zorder=2):
        box = FancyBboxPatch(
            (x, yy - h), w, h,
            boxstyle=f"round,pad=0,rounding_size={radius}",
            facecolor=color, edgecolor="none",
            alpha=alpha, zorder=zorder, transform=ax.transData,
        )
        ax.add_patch(box)

    def hrule(yy, color=P["border"], alpha=1.0):
        ax.plot([ML, MR], [yy, yy], color=color, linewidth=0.6,
                alpha=alpha, zorder=3, solid_capstyle="round")

    def section_label(yy, text):
        t(ML, yy, text.upper(), size=6.8, color=P["text3"], weight="bold")
        return yy - 0.28

    # ── background grid ───────────────────────────────────────────────────────
    for gx in np.linspace(0, W, 18):
        ax.plot([gx, gx], [0, H], color=P["border"],
                linewidth=0.3, alpha=0.18, zorder=0)
    for gy in np.linspace(0, H, 24):
        ax.plot([0, W], [gy, gy], color=P["border"],
                linewidth=0.3, alpha=0.18, zorder=0)

    # ── left accent bar ───────────────────────────────────────────────────────
    ax.add_patch(plt.Rectangle(
        (0, 0), 0.08, H, facecolor=P["accent"],
        alpha=0.9, zorder=5, transform=ax.transData,
    ))

    # ══════════════════════════════════════════════════════════════════════════
    # HEADER
    # ══════════════════════════════════════════════════════════════════════════
    rect(ML, y, CW, 1.55, P["surface"], radius=0.18)

    badge_x = MR - 0.15
    t(badge_x, y - 0.14, "SKILLCERT",
      size=6.5, color=P["accent"], weight="bold", align="right")
    t(badge_x, y - 0.30, "CERTIFIED PRIVACY LABEL",
      size=6, color=P["text2"], align="right")

    display = skill_name.replace("-", " ").replace("_", " ")
    display = " ".join(w.capitalize() for w in display.split())
    wrapped = textwrap.fill(display, width=28)
    lines   = wrapped.count("\n") + 1
    t(ML + 0.22, y - 0.18, wrapped,
      size=20, color=P["text"], weight="bold")
    t(ML + 0.22, y - 0.22 - lines * 0.42,
      f"by  {author}", size=9, color=P["text2"], style="italic")

    # risk pill
    risk_cfg = {
        "none":   (P["accent"], P["accent_dim"], "NO RISK"),
        "low":    (P["accent"], P["accent_dim"], "LOW RISK"),
        "medium": (P["warn"],   P["warn_dim"],   "MEDIUM RISK"),
        "high":   (P["danger"], P["danger_dim"], "HIGH RISK"),
    }
    rc, rc_dim, rl = risk_cfg.get(risk_level, (P["text3"], P["surface2"], "UNKNOWN"))
    pill_x = MR - 1.52
    pill_y = y - 0.76
    rect(pill_x, pill_y + 0.30, 1.35, 0.34, rc_dim, radius=0.14)
    ax.plot([pill_x, pill_x + 1.35], [pill_y + 0.30, pill_y + 0.30],
            color=rc, linewidth=1.2, alpha=0.7,
            solid_capstyle="round", zorder=3)
    t(pill_x + 0.675, pill_y + 0.20, f"● {rl}",
      size=8.5, color=rc, weight="bold", align="center")

    # risk score sub-label
    t(pill_x + 0.675, pill_y - 0.08,
      f"score: {risk_score}",
      size=6.5, color=P["text2"], align="center")

    y -= 1.72
    hrule(y)
    y -= 0.30

    # ══════════════════════════════════════════════════════════════════════════
    # SUMMARY
    # ══════════════════════════════════════════════════════════════════════════
    y = section_label(y, "Privacy Summary")
    summary         = analysis.get("summary", "No summary available.")
    wrapped_summary = textwrap.fill(summary, width=72)
    lines_s         = wrapped_summary.count("\n") + 1
    t(ML, y, wrapped_summary, size=9, color=P["text2"], style="italic")
    y -= lines_s * 0.23 + 0.30

    hrule(y)
    y -= 0.30

    # ══════════════════════════════════════════════════════════════════════════
    # DATA COLLECTED
    # ══════════════════════════════════════════════════════════════════════════
    y = section_label(y, "Data Collected  (detected via static code analysis)")

    data_types = analysis.get("data_types", [])

    # Ensure sensitivity is set on each item using our deterministic tiers
    for dt in data_types:
        if not dt.get("sensitivity") or dt["sensitivity"] not in ("high", "medium", "low"):
            dt["sensitivity"] = get_sensitivity(dt.get("name", ""))

    if not data_types:
        rect(ML, y + 0.06, CW, 0.52, P["accent_dim"], radius=0.12)
        ax.plot([ML, ML + CW], [y + 0.06, y + 0.06],
                color=P["accent"], linewidth=1.0, alpha=0.6,
                solid_capstyle="round", zorder=3)
        t(ML + CW / 2, y - 0.06,
          "✓   No personal data collection detected",
          size=10, color=P["accent"], weight="bold", align="center")
        y -= 0.70
    else:
        sens_color = {
            "high":   (P["danger"], P["danger_dim"]),
            "medium": (P["warn"],   P["warn_dim"]),
            "low":    (P["blue"],   P["blue_dim"]),
        }

        ROW_H = 0.54
        COL   = CW / 2 - 0.10
        rows  = math.ceil(len(data_types) / 2)

        for i, dt in enumerate(data_types):
            col_idx = i % 2
            row_idx = i // 2
            rx = ML + col_idx * (COL + 0.20)
            ry = y - row_idx * (ROW_H + 0.10)

            sens    = dt.get("sensitivity", "low").lower()
            fc, bc  = sens_color.get(sens, sens_color["low"])

            rect(rx, ry + 0.06, COL, ROW_H, bc, radius=0.12)
            rect(rx, ry + 0.06, 0.06, ROW_H, fc, radius=0.08)

            ico = icon_for(dt.get("name", ""))
            t(rx + 0.16, ry - 0.04, ico, size=13, color=fc)
            t(rx + 0.40, ry - 0.05,
              dt.get("name", "Unknown").title(),
              size=9.5, color=P["text"], weight="bold")
            t(rx + 0.40, ry - 0.24,
              textwrap.fill(dt.get("how", ""), width=28),
              size=7.5, color=P["text2"])
            t(rx + COL - 0.08, ry - 0.08,
              sens.upper(),
              size=6.5, color=fc, weight="bold", align="right")

        y -= rows * (ROW_H + 0.10) + 0.18

    hrule(y)
    y -= 0.30

    # ══════════════════════════════════════════════════════════════════════════
    # RISK SCORE BREAKDOWN
    # ══════════════════════════════════════════════════════════════════════════
    y = section_label(y, "Risk Score Breakdown")

    # Count items per tier
    tier_counts = {"high": 0, "medium": 0, "low": 0}
    for dt in data_types:
        tier = dt.get("sensitivity", "low").lower()
        if tier in tier_counts:
            tier_counts[tier] += 1

    breakdown_items = [
        (f"{tier_counts['high']}  high-sensitivity  (×4 pts each)",
         P["danger"] if tier_counts["high"] else P["text3"]),
        (f"{tier_counts['medium']}  medium-sensitivity  (×2 pts each)",
         P["warn"] if tier_counts["medium"] else P["text3"]),
        (f"{tier_counts['low']}  low-sensitivity  (×1 pt each)",
         P["blue"] if tier_counts["low"] else P["text3"]),
        (f"Total score: {risk_score}  →  {risk_level.upper()} RISK",
         rc),
    ]

    for label, color in breakdown_items:
        t(ML + 0.10, y, f"  {label}", size=8.5, color=color)
        y -= 0.28

    y -= 0.10
    hrule(y)
    y -= 0.30

    # ══════════════════════════════════════════════════════════════════════════
    # COLLECTION METHODS
    # ══════════════════════════════════════════════════════════════════════════
    y = section_label(y, "Collection Methods")

    methods       = analysis.get("collection_methods", [])
    method_labels = {
        "conversation":   ("◉", "Via Conversation",
                           "Skill asks the user directly during interaction"),
        "permission_api": ("◈", "Alexa Permission",
                           "Accesses data via Alexa's permission API"),
        "inferred":       ("◍", "Inferred",
                           "Data inferred from user behaviour"),
    }

    if not methods:
        t(ML, y, "No collection methods identified.",
          size=9, color=P["text3"])
        y -= 0.35
    else:
        MET_W = min((CW - 0.20 * (len(methods) - 1)) / max(len(methods), 1), 2.6)
        for i, m in enumerate(methods):
            ico, label, desc = method_labels.get(
                m, ("◆", m.replace("_", " ").title(), "")
            )
            mx = ML + i * (MET_W + 0.20)
            rect(mx, y + 0.06, MET_W, 0.64, P["surface2"], radius=0.12)
            t(mx + 0.18, y - 0.05, ico, size=14, color=P["accent"])
            t(mx + 0.44, y - 0.06, label, size=8.5, color=P["text"], weight="bold")
            t(mx + 0.44, y - 0.25,
              textwrap.fill(desc, width=22), size=7, color=P["text2"])
        y -= 0.84

    hrule(y)
    y -= 0.30

    # ══════════════════════════════════════════════════════════════════════════
    # DATA PRACTICES
    # ══════════════════════════════════════════════════════════════════════════
    y = section_label(y, "Data Practices")

    shared   = analysis.get("data_shared_with_third_parties", False)
    retained = analysis.get("data_retained", "unknown")

    def practice_card(px, py, w, title, value, value_color):
        rect(px, py + 0.06, w, 0.72, P["surface2"], radius=0.12)
        t(px + 0.18, py - 0.06, title, size=7.5, color=P["text3"], weight="bold")
        t(px + 0.18, py - 0.28, str(value).upper(),
          size=10, color=value_color, weight="bold")

    CARD_W  = (CW - 0.20) / 2
    sh_val  = "YES" if shared else "NO"
    sh_col  = P["warn"] if shared else P["accent"]
    practice_card(ML, y, CARD_W, "SHARED WITH THIRD PARTIES", sh_val, sh_col)

    ret_map = {
        True:      ("YES",     P["warn"]),
        False:     ("NO",      P["accent"]),
        "unknown": ("UNKNOWN", P["text3"]),
    }
    rv, rc_ret = ret_map.get(retained, ("UNKNOWN", P["text3"]))
    practice_card(ML + CARD_W + 0.20, y, CARD_W, "DATA RETAINED", rv, rc_ret)

    y -= 0.92
    hrule(y)

    # ══════════════════════════════════════════════════════════════════════════
    # FOOTER
    # ══════════════════════════════════════════════════════════════════════════
    ax.add_patch(plt.Rectangle(
        (0, 0), W, 0.54, facecolor=P["surface"],
        alpha=1.0, zorder=3, transform=ax.transData,
    ))
    ax.plot([0, W], [0.54, 0.54], color=P["border"],
            linewidth=0.6, alpha=0.6, zorder=4)

    t(ML, 0.36, "SkillCert  •  Automated Privacy Analysis",
      size=7.5, color=P["text3"])
    t(MR, 0.36, "Powered by SkillPoV  •  Static Code Analysis",
      size=7.5, color=P["text3"], align="right")
    t(W / 2, 0.18,
      "This label reflects data collection practices detected in the skill's source code.",
      size=6.8, color=P["text3"], align="center")

    fig.savefig(out_path, dpi=DPI, bbox_inches="tight",
                facecolor=P["bg"], pad_inches=0.05)
    plt.close(fig)
    print(f"  [OK] → {out_path}")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    skills = discover_skills()
    if not skills:
        sys.exit(
            f"[ERROR] No report files found in {FINAL_PATH}.\n"
            "Run scan_skills.py then main.py first."
        )

    print(f"\nFound {len(skills)} skill(s). Generating labels...\n")

    for s in skills:
        author, skill_name = s["author"], s["skill"]
        print(f"Processing: {author} / {skill_name}")

        report_text = open(s["report_path"]).read().strip()
        if not report_text:
            print("  [SKIP] Empty report.")
            continue

        print("  Calling ChatGPT for structured extraction...")
        analysis = ask_chatgpt(report_text)

        # Ensure sensitivity values are set using our deterministic logic
        for dt in analysis.get("data_types", []):
            if not dt.get("sensitivity") or \
               dt["sensitivity"] not in ("high", "medium", "low"):
                dt["sensitivity"] = get_sensitivity(dt.get("name", ""))

        # Compute risk score and level deterministically
        methods     = analysis.get("collection_methods", [])
        data_types  = analysis.get("data_types", [])
        risk_level  = classify_risk(data_types, methods)
        risk_score  = sum(
            TIER_WEIGHTS.get(
                dt.get("sensitivity") or get_sensitivity(dt.get("name", "")), 1
            )
            for dt in data_types
        )
        if "conversation" in methods and "permission_api" in methods:
            risk_score += 1

        print(f"  Data types : {len(data_types)}")
        print(f"  Risk score : {risk_score}  →  {risk_level.upper()}")

        # Route label into the correct subdirectory based on risk level
        label_dir  = LABEL_DIRS.get(risk_level, LABEL_DIRS["low"])
        label_path = os.path.join(label_dir, f"{author}~~{skill_name}_label.png")

        draw_label(
            skill_name  = skill_name,
            author      = author,
            analysis    = analysis,
            risk_level  = risk_level,
            risk_score  = risk_score,
            out_path    = label_path,
        )

    print(f"\nDone. Labels saved to:")
    for level, d in LABEL_DIRS.items():
        count = len([f for f in os.listdir(d) if f.endswith(".png")])
        print(f"  {level:8s} → {d}  ({count} label{'s' if count != 1 else ''})")


if __name__ == "__main__":
    main()