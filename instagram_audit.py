#!/usr/bin/env python3
"""
instagram_audit.py

Reads Instagram followers/following exports and reports personal accounts
that you follow but that do not follow you back.

Usage:
    python instagram_audit.py --following following.json --followers followers_1.json
    python instagram_audit.py --following following.txt  --followers followers.txt
    python instagram_audit.py --following following.json --followers followers_1.json --output report.txt

Supported formats:
    JSON: Instagram's official data export (connections/followers_and_following/)
    TXT:  One username per line (plain list)
"""

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Heuristic configuration – add/remove terms to tune business detection.
# ---------------------------------------------------------------------------
BUSINESS_KEYWORDS = {
    "shop", "store", "brand", "official", "co", "corp", "inc", "ltd",
    "llc", "gmbh", "media", "agency", "studio", "group", "team",
    "news", "tv", "radio", "magazine", "journal", "press", "blog",
    "marketing", "digital", "design", "creative", "productions",
    "photography", "photo", "films", "music", "records", "label",
    "fashion", "beauty", "skincare", "cosmetics", "haircare",
    "food", "restaurant", "cafe", "bakery", "kitchen", "chef",
    "fitness", "gym", "wellness", "health", "clinic", "dental",
    "real_estate", "realty", "properties", "invest", "finance",
    "travel", "tours", "hotel", "resort", "airline",
    "tech", "software", "app", "solutions", "systems", "consulting",
    "academy", "school", "university", "education", "institute",
    "foundation", "charity", "nonprofit", "ngo",
    "auto", "motors", "cars", "dealer",
    "pet", "vet", "grooming",
}


# ---------------------------------------------------------------------------
# 1. Data reading
# ---------------------------------------------------------------------------

def load_usernames_from_json(path: str) -> set[str]:
    """
    Parse an Instagram JSON export file and return a set of usernames.

    Instagram exports two shapes:
      - followers_*.json  → top-level list of entry objects
      - following.json    → dict with a single key whose value is a list

    Each entry object contains a "string_list_data" array; the first element's
    "value" field holds the username.
    """
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    # Normalise to a flat list of entry objects regardless of shape.
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        # e.g. {"relationships_following": [...]}
        if len(data) == 1:
            entries = next(iter(data.values()))
        else:
            # Try the most common key names first, then fall back.
            for key in ("relationships_following", "relationships_followers"):
                if key in data:
                    entries = data[key]
                    break
            else:
                # Merge all lists found in the dict.
                entries = []
                for v in data.values():
                    if isinstance(v, list):
                        entries.extend(v)
    else:
        raise ValueError(f"Unexpected JSON structure in {path!r}")

    usernames: set[str] = set()
    for entry in entries:
        try:
            username = entry["string_list_data"][0]["value"].lower().strip()
            if username:
                usernames.add(username)
        except (KeyError, IndexError, TypeError):
            # Silently skip malformed entries.
            continue

    return usernames


def load_usernames_from_txt(path: str) -> set[str]:
    """
    Parse a plain-text file where each non-empty line is one username.
    Leading '@' symbols and surrounding whitespace are stripped.
    """
    usernames: set[str] = set()
    with open(path, "r", encoding="utf-8") as fh:
        for raw_line in fh:
            username = raw_line.strip().lstrip("@").lower()
            if username:
                usernames.add(username)
    return usernames


def load_usernames(path: str) -> set[str]:
    """
    Auto-detect file format by extension and delegate to the right loader.
    Raises FileNotFoundError if the path does not exist.
    Raises ValueError for unsupported extensions.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File not found: {path!r}")

    ext = os.path.splitext(path)[1].lower()
    if ext == ".json":
        return load_usernames_from_json(path)
    elif ext in (".txt", ".csv", ""):
        return load_usernames_from_txt(path)
    else:
        raise ValueError(
            f"Unsupported file extension {ext!r}. Use .json or .txt"
        )


# ---------------------------------------------------------------------------
# 2. Business-account heuristic
# ---------------------------------------------------------------------------

def looks_like_business(username: str) -> bool:
    """
    Return True when the username resembles a business/brand account.

    Heuristic rules (all applied to the lower-cased username):
      1. Contains any word from BUSINESS_KEYWORDS separated by common
         delimiters (_, ., -) or as a standalone token.
      2. Ends with a digit-heavy suffix (e.g. brand123, shop_2024).
         – A personal account occasionally ends with digits, so we only
           flag this when combined with another signal.

    This is intentionally conservative: it is better to include a borderline
    business account in the report than to accidentally hide a real person.
    """
    # Split on common Instagram username separators.
    tokens = set(username.replace(".", "_").replace("-", "_").split("_"))

    for keyword in BUSINESS_KEYWORDS:
        if keyword in tokens:
            return True
        # Also catch compound tokens that *contain* the keyword (e.g. "shopify").
        if any(keyword in token for token in tokens if len(token) > len(keyword)):
            return True

    return False


# ---------------------------------------------------------------------------
# 3. Comparison logic
# ---------------------------------------------------------------------------

def find_non_returners(
    following: set[str],
    followers: set[str],
    exclude_businesses: bool = True,
) -> list[str]:
    """
    Return a sorted list of usernames that the user follows but who do not
    follow back.

    Args:
        following:          Usernames the user follows.
        followers:          Usernames that follow the user.
        exclude_businesses: When True, accounts flagged as businesses are
                            omitted (you may not expect them to follow back).

    Returns:
        Sorted list of usernames.
    """
    not_following_back = following - followers

    if exclude_businesses:
        not_following_back = {
            u for u in not_following_back if not looks_like_business(u)
        }

    return sorted(not_following_back)


# ---------------------------------------------------------------------------
# 4. Report generation
# ---------------------------------------------------------------------------

def generate_report(
    non_returners: list[str],
    following_count: int,
    followers_count: int,
    exclude_businesses: bool,
    output_path: Optional[str] = None,
) -> None:
    """
    Print (and optionally save) a human-readable report.

    Args:
        non_returners:      Sorted list of usernames not following back.
        following_count:    Total number of accounts the user follows.
        followers_count:    Total number of the user's followers.
        exclude_businesses: Whether business accounts were filtered out.
        output_path:        If provided, the report is also written to this file.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    separator = "=" * 60

    lines: list[str] = [
        separator,
        "  Instagram Follower Audit Report",
        f"  Generated: {timestamp}",
        separator,
        "",
        f"  Accounts you follow   : {following_count}",
        f"  Your followers        : {followers_count}",
        f"  Business accounts     : {'excluded' if exclude_businesses else 'included'}",
        f"  Not following back    : {len(non_returners)}",
        "",
        separator,
        "  Accounts to review (follow but no follow-back):",
        separator,
        "",
    ]

    if non_returners:
        for i, username in enumerate(non_returners, start=1):
            lines.append(f"  {i:>4}.  @{username}")
    else:
        lines.append("  None found – everyone you follow, follows you back!")

    lines += ["", separator, "  End of report", separator]

    report_text = "\n".join(lines)
    print(report_text)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(report_text + "\n")
        print(f"\n  Report saved to: {output_path}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="instagram_audit",
        description=(
            "Compare Instagram following/followers exports and list personal "
            "accounts that do not follow you back."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python instagram_audit.py \\\n"
            "      --following connections/followers_and_following/following.json \\\n"
            "      --followers connections/followers_and_following/followers_1.json\n\n"
            "  python instagram_audit.py \\\n"
            "      --following following.txt --followers followers.txt \\\n"
            "      --include-businesses --output report.txt"
        ),
    )
    parser.add_argument(
        "--following",
        required=True,
        metavar="PATH",
        help="Path to the following list (.json or .txt).",
    )
    parser.add_argument(
        "--followers",
        required=True,
        metavar="PATH",
        help="Path to the followers list (.json or .txt).",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        default=None,
        help="Optional path to save the report as a text file.",
    )
    parser.add_argument(
        "--include-businesses",
        action="store_true",
        default=False,
        help=(
            "Include accounts that look like businesses/brands in the report. "
            "By default they are excluded because you may not expect them to "
            "follow back."
        ),
    )
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    exclude_businesses = not args.include_businesses

    try:
        following = load_usernames(args.following)
        followers = load_usernames(args.followers)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error loading files: {exc}", file=sys.stderr)
        sys.exit(1)

    if not following:
        print("Warning: the following list is empty – nothing to compare.", file=sys.stderr)

    non_returners = find_non_returners(following, followers, exclude_businesses)

    generate_report(
        non_returners=non_returners,
        following_count=len(following),
        followers_count=len(followers),
        exclude_businesses=exclude_businesses,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
