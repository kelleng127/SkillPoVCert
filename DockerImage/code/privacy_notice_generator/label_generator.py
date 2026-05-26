"""
label_generator.py
------------------
Generates a certified privacy label PNG for each Alexa skill analyzed
by the SkillPoV pipeline. Labels are based purely on backend code analysis —
no manifest comparison, no privacy policy matching. The code is the truth.

Pipeline:
  1. Read data_collection_results/final/<author>~~<skill>~~report.txt
  2. Send to ChatGPT for structured JSON extraction of data practices
  3. Draw a refined, visually polished privacy label and save as PNG

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
os.makedirs(LABELS_PATH, exist_ok=True)

# ── third-party imports ───────────────────────────────────────────────────────
try:
    import openai
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.patches import FancyBboxPatch, Circle
    import matplotlib.patheffects as pe
    from matplotlib.colors import LinearSegmentedColormap
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
# COLOUR PALETTE  —  deep navy + electric teal accent, warm white text
# ─────────────────────────────────────────────────────────────────────────────
P = {
    "bg":           "#0D1117",   # near-black background
    "surface":      "#161B22",   # card surface
    "surface2":     "#21262D",   # elevated surface / row bg
    "border":       "#30363D",   # subtle border
    "accent":       "#00D4AA",   # electric teal — primary accent
    "accent_dim":   "#004D3D",   # teal at low opacity
    "blue":         "#388BFD",   # secondary accent (blue)
    "blue_dim":     "#0D2A5C",
    "warn":         "#E3B341",   # amber warning
    "warn_dim":     "#3D2E00",
    "danger":       "#F85149",   # red
    "danger_dim":   "#3D0C0A",
    "text":         "#E6EDF3",   # primary text
    "text2":        "#8B949E",   # secondary text
    "text3":        "#484F58",   # tertiary / disabled
    "white":        "#FFFFFF",
}

# data-type → icon character (Unicode block elements / arrows)
DATA_ICONS = {
    "name":         "◈",
    "email":        "✉",
    "age":          "◷",
    "birthday":     "◷",
    "location":     "◎",
    "address":      "◎",
    "postal code":  "◎",
    "zip code":     "◎",
    "gender":       "◈",
    "phone":        "✆",
    "number":       "✆",
    "income":       "◈",
    "ssn":          "◈",
    "ethnicity":    "◈",
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
            "label_path":  os.path.join(
                LABELS_PATH, f"{author}~~{skill}_label.png"
            ),
        })
    return skills

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 – ChatGPT structured extraction
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
  "risk_level": "none" | "low" | "medium" | "high",
  "summary": "2-3 sentence plain-English summary of what data this skill collects and why it matters to the user"
}

Rules:
- sensitivity high   = financial, biometric, SSN, health, precise location
- sensitivity medium = name, email, phone, age, gender, postal code
- sensitivity low    = general preferences, reminders, non-personal inputs
- risk_level is an overall assessment combining data types and methods
- Be concise. Only include what is evidenced in the report.
- If nothing sensitive is collected, data_types may be an empty array and risk_level should be "none".
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
            "data_types":                   [],
            "collection_methods":           [],
            "data_shared_with_third_parties": False,
            "data_retained":                "unknown",
            "risk_level":                   "unknown",
            "summary":                      "Analysis could not be completed.",
        }

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 – draw the label
# ─────────────────────────────────────────────────────────────────────────────

def draw_label(skill_name, author, analysis, out_path):
    # ── canvas ────────────────────────────────────────────────────────────────
    W, H = 8.5, 11.5          # inches
    DPI  = 160
    fig  = plt.figure(figsize=(W, H), facecolor=P["bg"])
    ax   = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.set_facecolor(P["bg"])
    ax.axis("off")

    # ── layout constants ──────────────────────────────────────────────────────
    ML   = 0.42      # margin left
    MR   = W - 0.42  # margin right
    CW   = MR - ML   # content width
    y    = H - 0.45  # cursor (top → bottom)

    # ── helpers ───────────────────────────────────────────────────────────────
    def t(x, yy, s, size=9, color=P["text"], weight="normal",
          align="left", style="normal", alpha=1.0, zorder=4):
        ax.text(x, yy, s,
                fontsize=size, color=color, fontweight=weight,
                ha=align, va="top", fontstyle=style,
                alpha=alpha, zorder=zorder,
                transform=ax.transData)

    def rect(x, yy, w, h, color, alpha=1.0, radius=0.12, zorder=2):
        box = FancyBboxPatch(
            (x, yy - h), w, h,
            boxstyle=f"round,pad=0,rounding_size={radius}",
            facecolor=color, edgecolor="none",
            alpha=alpha, zorder=zorder,
            transform=ax.transData,
        )
        ax.add_patch(box)

    def hrule(yy, color=P["border"], alpha=1.0):
        ax.plot([ML, MR], [yy, yy],
                color=color, linewidth=0.6, alpha=alpha,
                zorder=3, solid_capstyle="round")

    def section_label(yy, text):
        t(ML, yy, text.upper(),
          size=6.8, color=P["text3"], weight="bold")
        return yy - 0.28

    # ── subtle grid lines in background ───────────────────────────────────────
    for gx in np.linspace(0, W, 18):
        ax.plot([gx, gx], [0, H],
                color=P["border"], linewidth=0.3, alpha=0.18, zorder=0)
    for gy in np.linspace(0, H, 24):
        ax.plot([0, W], [gy, gy],
                color=P["border"], linewidth=0.3, alpha=0.18, zorder=0)

    # ── accent bar — left edge ────────────────────────────────────────────────
    ax.add_patch(plt.Rectangle(
        (0, 0), 0.08, H,
        facecolor=P["accent"], alpha=0.9, zorder=5,
        transform=ax.transData,
    ))

    # ══════════════════════════════════════════════════════════════════════════
    # HEADER
    # ══════════════════════════════════════════════════════════════════════════
    rect(ML, y, CW, 1.55, P["surface"], radius=0.18)

    # "CERTIFIED PRIVACY LABEL" badge top-right
    badge_x = MR - 0.15
    t(badge_x, y - 0.14,
      "SKILLCERT",
      size=6.5, color=P["accent"], weight="bold", align="right")
    t(badge_x, y - 0.30,
      "CERTIFIED PRIVACY LABEL",
      size=6, color=P["text3"], align="right")

    # skill name
    display = skill_name.replace("-", " ").replace("_", " ")
    # title-case each word
    display = " ".join(w.capitalize() for w in display.split())
    wrapped = textwrap.fill(display, width=28)
    lines   = wrapped.count("\n") + 1
    t(ML + 0.22, y - 0.18, wrapped,
      size=20, color=P["text"], weight="bold")

    t(ML + 0.22, y - 0.22 - lines * 0.42,
      f"by  {author}",
      size=9, color=P["text2"], style="italic")

    # risk pill top-left of header
    risk      = analysis.get("risk_level", "unknown").lower()
    risk_cfg  = {
        "none":    (P["accent"],  P["accent_dim"],  "NO RISK"),
        "low":     (P["accent"],  P["accent_dim"],  "LOW RISK"),
        "medium":  (P["warn"],    P["warn_dim"],    "MEDIUM RISK"),
        "high":    (P["danger"],  P["danger_dim"],  "HIGH RISK"),
        "unknown": (P["text3"],   P["surface2"],    "UNKNOWN"),
    }
    rc, rc_dim, rl = risk_cfg.get(risk, risk_cfg["unknown"])
    pill_x = MR - 1.52
    pill_y = y - 0.92
    rect(pill_x, pill_y + 0.30, 1.35, 0.34, rc_dim, radius=0.14)
    ax.plot([pill_x, pill_x + 1.35], [pill_y + 0.30, pill_y + 0.30],
            color=rc, linewidth=1.2, alpha=0.7,
            solid_capstyle="round", zorder=3)
    t(pill_x + 0.675, pill_y + 0.20,
      f"● {rl}",
      size=8.5, color=rc, weight="bold", align="center")

    y -= 1.72
    hrule(y)
    y -= 0.30

    # ══════════════════════════════════════════════════════════════════════════
    # SUMMARY
    # ══════════════════════════════════════════════════════════════════════════
    y = section_label(y, "Privacy Summary")
    summary = analysis.get("summary", "No summary available.")
    wrapped_summary = textwrap.fill(summary, width=72)
    lines_s = wrapped_summary.count("\n") + 1
    t(ML, y, wrapped_summary,
      size=9, color=P["text2"], style="italic")
    y -= lines_s * 0.23 + 0.30

    hrule(y)
    y -= 0.30

    # ══════════════════════════════════════════════════════════════════════════
    # DATA COLLECTED
    # ══════════════════════════════════════════════════════════════════════════
    y = section_label(y, "Data Collected  (detected via static code analysis)")

    data_types = analysis.get("data_types", [])

    if not data_types:
        # green "no collection" banner
        rect(ML, y + 0.06, CW, 0.52, P["accent_dim"], radius=0.12)
        ax.plot([ML, ML + CW], [y + 0.06, y + 0.06],
                color=P["accent"], linewidth=1.0, alpha=0.6,
                solid_capstyle="round", zorder=3)
        t(ML + CW / 2, y - 0.06,
          "✓   No personal data collection detected",
          size=10, color=P["accent"], weight="bold", align="center")
        y -= 0.70
    else:
        # sensitivity colour map
        sens_color = {
            "high":   (P["danger"],  P["danger_dim"]),
            "medium": (P["warn"],    P["warn_dim"]),
            "low":    (P["blue"],    P["blue_dim"]),
        }

        ROW_H   = 0.54
        COL     = CW / 2 - 0.10
        n       = len(data_types)
        rows    = math.ceil(n / 2)

        for i, dt in enumerate(data_types):
            col_idx = i % 2
            row_idx = i // 2
            rx = ML + col_idx * (COL + 0.20)
            ry = y - row_idx * (ROW_H + 0.10)

            sens  = dt.get("sensitivity", "low").lower()
            fc, bc = sens_color.get(sens, sens_color["low"])

            # row background
            rect(rx, ry + 0.06, COL, ROW_H, bc, radius=0.12)
            # left accent stripe
            rect(rx, ry + 0.06, 0.06, ROW_H, fc, radius=0.08)

            # icon
            ico = icon_for(dt.get("name", ""))
            t(rx + 0.16, ry - 0.04, ico,
              size=13, color=fc)

            # data type name
            t(rx + 0.40, ry - 0.05,
              dt.get("name", "Unknown").title(),
              size=9.5, color=P["text"], weight="bold")

            # how collected
            how_text = textwrap.fill(
                dt.get("how", ""), width=28
            )
            t(rx + 0.40, ry - 0.24,
              how_text,
              size=7.5, color=P["text2"])

            # sensitivity badge
            t(rx + COL - 0.08, ry - 0.08,
              sens.upper(),
              size=6.5, color=fc, weight="bold", align="right")

        y -= rows * (ROW_H + 0.10) + 0.18

    hrule(y)
    y -= 0.30

    # ══════════════════════════════════════════════════════════════════════════
    # COLLECTION METHODS
    # ══════════════════════════════════════════════════════════════════════════
    y = section_label(y, "Collection Methods")

    methods = analysis.get("collection_methods", [])
    method_labels = {
        "conversation":   ("◉", "Via Conversation",  "Skill asks the user directly during interaction"),
        "permission_api": ("◈", "Alexa Permission",  "Accesses data via Alexa's permission API"),
        "inferred":       ("◍", "Inferred",           "Data inferred from user behaviour"),
    }

    if not methods:
        t(ML, y, "No collection methods identified.",
          size=9, color=P["text3"])
        y -= 0.35
    else:
        MET_W = (CW - 0.20 * (len(methods) - 1)) / max(len(methods), 1)
        MET_W = min(MET_W, 2.6)
        for i, m in enumerate(methods):
            ico, label, desc = method_labels.get(
                m, ("◆", m.replace("_", " ").title(), "")
            )
            mx = ML + i * (MET_W + 0.20)
            rect(mx, y + 0.06, MET_W, 0.64, P["surface2"], radius=0.12)
            t(mx + 0.18, y - 0.05, ico,
              size=14, color=P["accent"])
            t(mx + 0.44, y - 0.06, label,
              size=8.5, color=P["text"], weight="bold")
            t(mx + 0.44, y - 0.25,
              textwrap.fill(desc, width=22),
              size=7, color=P["text2"])
        y -= 0.84

    hrule(y)
    y -= 0.30

    # ══════════════════════════════════════════════════════════════════════════
    # DATA PRACTICES ROW  (third-party sharing | retention)
    # ══════════════════════════════════════════════════════════════════════════
    y = section_label(y, "Data Practices")

    shared   = analysis.get("data_shared_with_third_parties", False)
    retained = analysis.get("data_retained", "unknown")

    def practice_card(px, py, w, title, value, value_color):
        rect(px, py + 0.06, w, 0.72, P["surface2"], radius=0.12)
        t(px + 0.18, py - 0.06, title,
          size=7.5, color=P["text3"], weight="bold")
        t(px + 0.18, py - 0.28, str(value).upper(),
          size=10, color=value_color, weight="bold")

    CARD_W = (CW - 0.20) / 2

    # third-party sharing
    sh_val   = "YES" if shared else "NO"
    sh_color = P["warn"] if shared else P["accent"]
    practice_card(ML, y, CARD_W, "SHARED WITH THIRD PARTIES", sh_val, sh_color)

    # data retention
    ret_map = {
        True:      ("YES",     P["warn"]),
        False:     ("NO",      P["accent"]),
        "unknown": ("UNKNOWN", P["text3"]),
    }
    rv, rc_ret = ret_map.get(retained, ("UNKNOWN", P["text3"]))
    practice_card(ML + CARD_W + 0.20, y, CARD_W, "DATA RETAINED", rv, rc_ret)

    y -= 0.92

    hrule(y)
    y -= 0.30

    # ══════════════════════════════════════════════════════════════════════════
    # FOOTER
    # ══════════════════════════════════════════════════════════════════════════
    # bottom bar
    ax.add_patch(plt.Rectangle(
        (0, 0), W, 0.54,
        facecolor=P["surface"], alpha=1.0, zorder=3,
        transform=ax.transData,
    ))
    ax.plot([0, W], [0.54, 0.54],
            color=P["border"], linewidth=0.6,
            alpha=0.6, zorder=4)

    t(ML, 0.36,
      "SkillCert  •  Automated Privacy Analysis",
      size=7.5, color=P["text3"])
    t(MR, 0.36,
      "Powered by SkillPoV  •  Static Code Analysis",
      size=7.5, color=P["text3"], align="right")

    t(W / 2, 0.18,
      "This label reflects data collection practices detected in the skill's source code.",
      size=6.8, color=P["text3"], align="center")

    # ── save ──────────────────────────────────────────────────────────────────
    fig.savefig(
        out_path, dpi=DPI,
        bbox_inches="tight",
        facecolor=P["bg"],
        pad_inches=0.05,
    )
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

        print("  Calling ChatGPT for structured analysis...")
        analysis = ask_chatgpt(report_text)

        print(f"  Risk level : {analysis.get('risk_level', '?')}")
        print(f"  Data types : {len(analysis.get('data_types', []))}")

        draw_label(
            skill_name = skill_name,
            author     = author,
            analysis   = analysis,
            out_path   = s["label_path"],
        )

    print(f"\nDone. Labels saved to:\n  {LABELS_PATH}\n")


if __name__ == "__main__":
    main()