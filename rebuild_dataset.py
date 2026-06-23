#!/usr/bin/env python3
"""
rebuild_dataset.py
------------------
Phase 1 — Remove repos with no detected data collection, keeping exactly 8
           edge-case controls (non-collecting skills retained for diversity).
Phase 2 — Clone every skill listed in Skill_Test_Result.csv that is not
           already present in dataset/repos/.

Run from the SkillPoVCert root:
    python3 rebuild_dataset.py [--dry-run]

After this script finishes, re-run the full analysis pipeline:
    python3 DockerImage/code/data_collection_analysis/scan_skills.py
    python3 DockerImage/code/privacy_notice_generator/main.py
    python3 DockerImage/code/privacy_notice_generator/label_generator.py
"""

import os
import sys
import csv
import shutil
import subprocess
import argparse

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT        = os.path.dirname(os.path.abspath(__file__))
REPOS_DIR   = os.path.join(ROOT, "dataset", "repos")
RESULTS_DIR = os.path.join(ROOT, "dataset", "results")
CSV_FILE    = os.path.join(ROOT, "Skill_Test_Result.csv")

# ── Non-collecting skills to KEEP as edge-case controls (<10) ─────────────────
# Diverse sample: trivia, audio, utility, multi-language, etc.
KEEP_EDGE_CASES = {
    ("07jeancms",      "skill-trivia"),
    ("adithyabhonsley","Fizz-Buzz"),
    ("AdrianGlez18",   "Curiosidades-historicas-en-Alexa"),
    ("agrygo99",       "MyTarotCard"),
    ("1onder",         "Quantum"),
    ("acucciniello",   "business-bear"),
    ("aespringfield",  "seconds"),
    ("13thontheleft",  "test-audioplayer"),
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def find_results_entry(author: str, skill: str):
    """
    Return the dataset/results/<entry> dir for author/skill, or None.
    Results dirs are named by replacing '/' in the skill path with '~',
    so we match by the trailing '~repos~<author>~<skill>' suffix.
    """
    suffix = f"~repos~{author}~{skill}"
    for entry in os.listdir(RESULTS_DIR):
        if entry.endswith(suffix):
            return os.path.join(RESULTS_DIR, entry)
    return None


def has_data_collection(author: str, skill: str) -> bool:
    """Return True when the pipeline produced a non-empty report.txt."""
    entry = find_results_entry(author, skill)
    if entry is None:
        return False
    report = os.path.join(entry, "report.txt")
    return os.path.isfile(report) and os.path.getsize(report) > 0


def repo_exists(author: str, skill: str) -> bool:
    return os.path.isdir(os.path.join(REPOS_DIR, author, skill))


def git_clone(author: str, skill: str, dry: bool) -> bool:
    url  = f"https://github.com/{author}/{skill}"
    dest = os.path.join(REPOS_DIR, author, skill)
    print(f"  [CLONE] {author}/{skill}  ← {url}")
    if dry:
        return True
    os.makedirs(os.path.join(REPOS_DIR, author), exist_ok=True)
    result = subprocess.run(
        ["git", "clone", "--depth=1", "--quiet", url, dest],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        err = result.stderr.strip().splitlines()
        print(f"    [FAIL] {err[-1] if err else 'unknown error'}")
        shutil.rmtree(dest, ignore_errors=True)
        return False
    return True


# ── Phase 1 ───────────────────────────────────────────────────────────────────

def phase1_remove(dry: bool) -> dict:
    print("\n" + "═" * 58)
    print("  Phase 1 — Removing skills with no data collection")
    print("═" * 58 + "\n")

    removed, kept_collecting, kept_edge = [], [], []

    for author in sorted(os.listdir(REPOS_DIR)):
        author_path = os.path.join(REPOS_DIR, author)
        if not os.path.isdir(author_path):
            continue
        for skill in sorted(os.listdir(author_path)):
            skill_path = os.path.join(author_path, skill)
            if not os.path.isdir(skill_path):
                continue

            if (author, skill) in KEEP_EDGE_CASES:
                print(f"  [KEEP-EDGE]       {author}/{skill}")
                kept_edge.append((author, skill))
                continue

            if has_data_collection(author, skill):
                print(f"  [KEEP-COLLECTING] {author}/{skill}")
                kept_collecting.append((author, skill))
                continue

            # No data collection detected — remove
            print(f"  [REMOVE]          {author}/{skill}")
            removed.append((author, skill))
            if not dry:
                shutil.rmtree(skill_path, ignore_errors=True)
                results_entry = find_results_entry(author, skill)
                if results_entry:
                    shutil.rmtree(results_entry, ignore_errors=True)

    # Clean up now-empty author directories
    if not dry:
        for author in os.listdir(REPOS_DIR):
            author_path = os.path.join(REPOS_DIR, author)
            if os.path.isdir(author_path) and not os.listdir(author_path):
                os.rmdir(author_path)

    print(f"\n  Removed {len(removed)} skill(s)")
    print(f"  Kept {len(kept_collecting)} collecting skill(s)")
    print(f"  Kept {len(kept_edge)} edge-case control(s)")
    return {"removed": removed, "collecting": kept_collecting, "edge": kept_edge}


# ── Phase 2 ───────────────────────────────────────────────────────────────────

def phase2_clone(dry: bool) -> dict:
    print("\n" + "═" * 58)
    print("  Phase 2 — Cloning skills from Skill_Test_Result.csv")
    print("═" * 58 + "\n")

    cloned, failed, skipped = [], [], []

    with open(CSV_FILE, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)  # skip header row
        seen = set()
        for row in reader:
            if not row:
                continue
            path = row[0].strip()
            if "~~" not in path:
                continue
            # CSV path format:  author~~skillName
            author, _, skill = path.partition("~~")
            author = author.strip()
            skill  = skill.strip()
            if not author or not skill:
                continue

            key = (author, skill)
            if key in seen:
                continue
            seen.add(key)

            if repo_exists(author, skill):
                print(f"  [SKIP]  {author}/{skill} already present")
                skipped.append(key)
                continue

            ok = git_clone(author, skill, dry)
            if ok:
                cloned.append(key)
            else:
                failed.append(key)

    print(f"\n  Cloned:  {len(cloned)}")
    print(f"  Failed:  {len(failed)}")
    print(f"  Skipped: {len(skipped)} (already present)")

    if failed:
        print("\n  Failed repos (URL not reachable or repo private/renamed):")
        for a, s in failed:
            print(f"    https://github.com/{a}/{s}")

    return {"cloned": cloned, "failed": failed, "skipped": skipped}


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Rebuild SkillPoVCert dataset: remove non-collecting skills, clone CSV skills."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would happen without making any changes.",
    )
    args = parser.parse_args()

    if args.dry_run:
        print("\n[DRY RUN] No files will be deleted or cloned.\n")

    p1 = phase1_remove(args.dry_run)
    p2 = phase2_clone(args.dry_run)

    total_remaining = (
        len(p1["collecting"]) +
        len(p1["edge"]) +
        len(p2["cloned"]) +
        len(p2["skipped"])
    )

    print("\n" + "═" * 58)
    print("  Summary")
    print("═" * 58)
    print(f"  Removed (no data collection):  {len(p1['removed'])}")
    print(f"  Retained (collecting):         {len(p1['collecting'])}")
    print(f"  Retained (edge-case controls): {len(p1['edge'])}")
    print(f"  Cloned from CSV:               {len(p2['cloned'])}")
    print(f"  Clone failures:                {len(p2['failed'])}")
    print(f"  Total skills in dataset now:   {total_remaining}")

    if not args.dry_run:
        print("\n  Next steps — re-run the full pipeline:")
        print("    python3 DockerImage/code/data_collection_analysis/scan_skills.py")
        print("    python3 DockerImage/code/privacy_notice_generator/main.py")
        print("    python3 DockerImage/code/privacy_notice_generator/label_generator.py")


if __name__ == "__main__":
    main()
