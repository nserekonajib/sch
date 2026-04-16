import re

def analyze_sql_backup(file_path):
    insert_count = 0
    tables = set()
    total_rows = 0

    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()

                # Check for INSERT statements
                if line.upper().startswith("INSERT INTO"):
                    insert_count += 1

                    # Extract table name
                    match = re.search(r'INSERT INTO\s+`?(\w+)`?', line, re.IGNORECASE)
                    if match:
                        tables.add(match.group(1))

                    # Estimate number of rows inserted
                    values_part = line.split("VALUES", 1)
                    if len(values_part) > 1:
                        rows = values_part[1].count("),(") + 1
                        total_rows += rows

        print("=== SQL BACKUP ANALYSIS ===")
        print(f"INSERT statements found: {insert_count}")
        print(f"Estimated total rows: {total_rows}")
        print(f"Tables with data ({len(tables)}):")

        for table in sorted(tables):
            print(f" - {table}")

        if insert_count == 0:
            print("\n⚠️ No data found! This backup likely contains only structure (CREATE TABLE).")

    except FileNotFoundError:
        print("❌ File not found. Check the path.")
    except Exception as e:
        print(f"❌ Error: {e}")


# 👉 Replace with your .sql file path
analyze_sql_backup("n.sql")