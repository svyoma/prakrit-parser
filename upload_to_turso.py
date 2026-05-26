"""
One-time script to upload verb_forms_final.sql data to Turso database.
Transforms schema from SQL file format to Turso format.
"""

import re
import sys
import time
import requests

# Turso connection (read-write token)
TURSO_URL = "https://prakrit-khasoochi.aws-ap-south-1.turso.io/v2/pipeline"
TURSO_TOKEN = sys.argv[1] if len(sys.argv) > 1 else ""

if not TURSO_TOKEN:
    print("Usage: python upload_to_turso.py <read-write-token>")
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {TURSO_TOKEN}",
    "Content-Type": "application/json"
}

# Schema transformations
PERSON_MAP = {
    "Third Person": "third",
    "Second Person": "second",
    "First Person": "first",
}
NUMBER_MAP = {
    "sg": "singular",
    "pl": "plural",
}


def execute_batch(statements):
    """Execute a batch of SQL statements via Turso pipeline API"""
    requests_list = [{"type": "execute", "stmt": s} for s in statements]
    requests_list.append({"type": "close"})
    payload = {"requests": requests_list}

    for attempt in range(3):
        try:
            resp = requests.post(TURSO_URL, headers=HEADERS, json=payload, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                errors = []
                for i, r in enumerate(data.get("results", [])):
                    if r.get("type") == "error":
                        errors.append(f"Statement {i}: {r.get('error', {}).get('message', 'unknown')}")
                return True, errors
            else:
                if attempt < 2:
                    time.sleep(2)
                    continue
                return False, [f"HTTP {resp.status_code}: {resp.text[:200]}"]
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
                continue
            return False, [str(e)]
    return False, ["Max retries exceeded"]


def execute_single(sql, args=None):
    """Execute a single SQL query and return rows"""
    stmt = {"sql": sql}
    if args:
        stmt["args"] = [{"type": "text", "value": str(a)} for a in args]
    payload = {
        "requests": [
            {"type": "execute", "stmt": stmt},
            {"type": "close"}
        ]
    }
    resp = requests.post(TURSO_URL, headers=HEADERS, json=payload, timeout=30)
    data = resp.json()
    result = data["results"][0]
    if result.get("type") != "ok":
        return None
    rows = result["response"]["result"].get("rows", [])
    return [[c.get("value") if isinstance(c, dict) else c for c in row] for row in rows]


def parse_sql_file(filepath):
    """Parse INSERT statements from SQL file"""
    records = []
    pattern = re.compile(
        r"VALUES\s*\(\d+,\s*'([^']*)',\s*'([^']*)',\s*'([^']*)',\s*'([^']*)',\s*'([^']*)',\s*'([^']*)'\)"
    )
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if not line.startswith("INSERT"):
                continue
            m = pattern.search(line)
            if m:
                records.append({
                    "root": m.group(1),
                    "form": m.group(2),
                    "tense": m.group(3),
                    "voice": m.group(4),
                    "person": m.group(5),
                    "number": m.group(6),
                })
    return records


def main():
    print("=== Turso Upload Script ===\n")

    # Test connection
    rows = execute_single("SELECT 1")
    if rows is None:
        print("ERROR: Cannot connect to Turso. Check token.")
        sys.exit(1)
    print("Connected to Turso successfully.\n")

    # Get current counts
    verb_roots_count = int(execute_single("SELECT COUNT(*) FROM verb_roots")[0][0])
    verb_forms_count = int(execute_single("SELECT COUNT(*) FROM verb_forms")[0][0])
    print(f"Current Turso data: {verb_roots_count} verb roots, {verb_forms_count} verb forms\n")

    # Parse SQL file
    print("Parsing verb_forms_final.sql...")
    records = parse_sql_file("verb_forms_final.sql")
    print(f"Parsed {len(records)} verb form records\n")

    # Get unique roots from SQL file
    sql_roots = sorted(set(r["root"] for r in records))
    print(f"Unique roots in SQL file: {len(sql_roots)}")

    # Get existing roots from Turso
    print("Loading existing roots from Turso...")
    existing_roots = {}
    rows = execute_single("SELECT root_id, root FROM verb_roots")
    for row in rows:
        existing_roots[row[1]] = row[0]
    print(f"Existing roots in Turso: {len(existing_roots)}")

    # Find missing roots
    missing_roots = [r for r in sql_roots if r not in existing_roots]
    print(f"New roots to add: {len(missing_roots)}\n")

    # Insert missing roots in batches
    if missing_roots:
        print("Inserting new roots...")
        batch_size = 100
        for i in range(0, len(missing_roots), batch_size):
            batch = missing_roots[i:i + batch_size]
            stmts = []
            for root in batch:
                stmts.append({
                    "sql": "INSERT OR IGNORE INTO verb_roots (root) VALUES (?)",
                    "args": [{"type": "text", "value": root}]
                })
            ok, errors = execute_batch(stmts)
            if not ok:
                print(f"  ERROR inserting roots batch {i}: {errors}")
            else:
                sys.stdout.write(f"\r  Inserted roots: {min(i + batch_size, len(missing_roots))}/{len(missing_roots)}")
                sys.stdout.flush()
        print()

        # Reload root mapping
        print("Reloading root IDs...")
        existing_roots = {}
        rows = execute_single("SELECT root_id, root FROM verb_roots")
        for row in rows:
            existing_roots[row[1]] = row[0]
        print(f"Total roots now: {len(existing_roots)}\n")

    # Insert verb forms in batches
    print("Inserting verb forms...")
    batch_size = 200
    inserted = 0
    skipped = 0
    errors_total = 0
    start_time = time.time()

    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        stmts = []
        for rec in batch:
            root_id = existing_roots.get(rec["root"])
            if not root_id:
                skipped += 1
                continue

            person = PERSON_MAP.get(rec["person"], rec["person"])
            number = NUMBER_MAP.get(rec["number"], rec["number"])

            stmts.append({
                "sql": "INSERT OR IGNORE INTO verb_forms (root_id, form, tense, voice, mood, dialect, person, number) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                "args": [
                    {"type": "integer", "value": str(root_id)},
                    {"type": "text", "value": rec["form"]},
                    {"type": "text", "value": rec["tense"]},
                    {"type": "text", "value": rec["voice"]},
                    {"type": "text", "value": "indicative"},
                    {"type": "text", "value": "standard"},
                    {"type": "text", "value": person},
                    {"type": "text", "value": number},
                ]
            })

        if stmts:
            ok, errors = execute_batch(stmts)
            if ok:
                inserted += len(stmts)
                if errors:
                    errors_total += len(errors)
            else:
                errors_total += len(stmts)

        elapsed = time.time() - start_time
        rate = (i + batch_size) / elapsed if elapsed > 0 else 0
        eta = (len(records) - i - batch_size) / rate if rate > 0 else 0
        sys.stdout.write(f"\r  Progress: {min(i + batch_size, len(records))}/{len(records)} | "
                         f"Inserted: {inserted} | Errors: {errors_total} | "
                         f"ETA: {int(eta)}s    ")
        sys.stdout.flush()

    print(f"\n\nUpload complete!")
    print(f"  Inserted: {inserted}")
    print(f"  Skipped (no root_id): {skipped}")
    print(f"  Errors: {errors_total}")

    # Verify final counts
    new_roots = int(execute_single("SELECT COUNT(*) FROM verb_roots")[0][0])
    new_forms = int(execute_single("SELECT COUNT(*) FROM verb_forms")[0][0])
    print(f"\nFinal Turso data: {new_roots} verb roots (+{new_roots - verb_roots_count}), "
          f"{new_forms} verb forms (+{new_forms - verb_forms_count})")

    # Verify indexes exist
    print("\nVerifying indexes...")
    indexes = execute_single("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name IN ('verb_forms', 'verb_roots')")
    for idx in indexes:
        print(f"  {idx[0]}")

    print("\nDone!")


if __name__ == "__main__":
    main()
