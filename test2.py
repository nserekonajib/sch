
import psycopg
from psycopg import sql
from pathlib import Path
from datetime import datetime


# ============================================================
# SUPABASE CONNECTION
# ============================================================

PASSWORD = "UQBCjkXg7kuG7iYI"

DB_CONFIG = {
    "host": "aws-0-eu-central-1.pooler.supabase.com",
    "port": 5432,
    "dbname": "postgres",
    "user": "postgres.qddnezmtskwclzzzfbun",
    "password": PASSWORD
}


# ============================================================
# EXPORT SETTINGS
# ============================================================

OUTPUT_FILE = "supabase_complete_schema.sql"

SCHEMA_NAME = "public"

# True  = export table data as INSERT statements
# False = structure only
INCLUDE_DATA = False


# ============================================================
# CONNECTION
# ============================================================

print("=" * 75)
print("SUPABASE DATABASE SQL EXPORTER")
print("=" * 75)

print("\nConnecting...")

conn = psycopg.connect(**DB_CONFIG)

print("Connected successfully!\n")

cursor = conn.cursor()


# ============================================================
# SQL OUTPUT
# ============================================================

output = []

output.append("-- ============================================================")
output.append("-- SUPABASE DATABASE EXPORT")
output.append("-- ============================================================")
output.append(f"-- Generated: {datetime.now()}")
output.append(f"-- Schema: {SCHEMA_NAME}")
output.append("-- Generated using Python + psycopg")
output.append("-- ============================================================\n")

output.append("BEGIN;\n")


# ============================================================
# HELPER
# ============================================================

def q(identifier):
    """
    Safely quote a PostgreSQL identifier.
    """
    return sql.Identifier(identifier).as_string(conn)


def lit(value):
    """
    Safely convert Python values into PostgreSQL literals.
    """
    return sql.Literal(value).as_string(conn)


def add_section(title):
    output.append("")
    output.append("-- ============================================================")
    output.append(f"-- {title}")
    output.append("-- ============================================================\n")


# ============================================================
# EXTENSIONS
# ============================================================

try:

    add_section("EXTENSIONS")

    cursor.execute("""
        SELECT extname, extversion
        FROM pg_extension
        WHERE extname NOT IN ('plpgsql')
        ORDER BY extname;
    """)

    extensions = cursor.fetchall()

    for extname, version in extensions:

        output.append(
            f'CREATE EXTENSION IF NOT EXISTS "{extname}";'
        )

    if extensions:
        output.append("")

except Exception as e:

    print("Warning reading extensions:", e)


# ============================================================
# ENUM TYPES
# ============================================================

try:

    add_section("ENUM TYPES")

    cursor.execute("""
        SELECT
            n.nspname AS schema_name,
            t.typname AS type_name,
            e.enumlabel
        FROM pg_type t
        JOIN pg_namespace n
            ON n.oid = t.typnamespace
        JOIN pg_enum e
            ON e.enumtypid = t.oid
        WHERE n.nspname = %s
        ORDER BY
            t.typname,
            e.enumsortorder;
    """, (SCHEMA_NAME,))

    rows = cursor.fetchall()

    enums = {}

    for schema_name, type_name, enum_label in rows:

        key = (schema_name, type_name)

        if key not in enums:
            enums[key] = []

        enums[key].append(enum_label)

    for (schema_name, type_name), labels in enums.items():

        values = ", ".join(lit(x) for x in labels)

        output.append(
            f'CREATE TYPE {q(schema_name)}.{q(type_name)} '
            f'AS ENUM ({values});'
        )

    output.append("")

except Exception as e:

    print("Warning reading enum types:", e)


# ============================================================
# SEQUENCES
# ============================================================

try:

    add_section("SEQUENCES")

    cursor.execute("""
        SELECT
            sequence_schema,
            sequence_name
        FROM information_schema.sequences
        WHERE sequence_schema = %s
        ORDER BY sequence_name;
    """, (SCHEMA_NAME,))

    sequences = cursor.fetchall()

    for schema_name, sequence_name in sequences:

        output.append(
            f'CREATE SEQUENCE IF NOT EXISTS '
            f'{q(schema_name)}.{q(sequence_name)};'
        )

    output.append("")

except Exception as e:

    print("Warning reading sequences:", e)


# ============================================================
# TABLES
# ============================================================

try:

    add_section("TABLES")

    cursor.execute("""
        SELECT
            c.oid,
            n.nspname,
            c.relname
        FROM pg_class c
        JOIN pg_namespace n
            ON n.oid = c.relnamespace
        WHERE n.nspname = %s
          AND c.relkind = 'r'
        ORDER BY c.relname;
    """, (SCHEMA_NAME,))

    tables = cursor.fetchall()

    print(f"Tables found: {len(tables)}")

    for table_oid, schema_name, table_name in tables:

        output.append(
            f'CREATE TABLE {q(schema_name)}.{q(table_name)} ('
        )

        cursor.execute("""
            SELECT
                a.attname,

                format_type(
                    a.atttypid,
                    a.atttypmod
                ) AS data_type,

                a.attnotnull,

                pg_get_expr(
                    d.adbin,
                    d.adrelid
                ) AS default_value,

                a.attidentity,

                a.attgenerated,

                a.attnum

            FROM pg_attribute a

            LEFT JOIN pg_attrdef d
                ON d.adrelid = a.attrelid
                AND d.adnum = a.attnum

            WHERE a.attrelid = %s
              AND a.attnum > 0
              AND NOT a.attisdropped

            ORDER BY a.attnum;
        """, (table_oid,))

        columns = cursor.fetchall()

        column_lines = []

        for (
            column_name,
            data_type,
            not_null,
            default_value,
            identity,
            generated,
            attnum
        ) in columns:

            line = f"    {q(column_name)} {data_type}"

            # Identity columns
            if identity == "a":

                line += " GENERATED ALWAYS AS IDENTITY"

            elif identity == "d":

                line += " GENERATED BY DEFAULT AS IDENTITY"

            # Generated columns
            elif generated == "s":

                if default_value:
                    line += f" GENERATED ALWAYS AS ({default_value}) STORED"

            # Normal default
            elif default_value:

                line += f" DEFAULT {default_value}"

            if not_null:
                line += " NOT NULL"

            column_lines.append(line)

        output.append(",\n".join(column_lines))

        output.append(");")
        output.append("")

except Exception as e:

    print("\nERROR reading tables:")
    print(e)

    conn.rollback()


# ============================================================
# DATA
# ============================================================

if INCLUDE_DATA:

    try:

        add_section("TABLE DATA")

        print("\nExporting table data...")

        for table_oid, schema_name, table_name in tables:

            print(f"  Exporting: {table_name}")

            cursor.execute(
                sql.SQL("SELECT * FROM {}.{}").format(
                    sql.Identifier(schema_name),
                    sql.Identifier(table_name)
                )
            )

            rows = cursor.fetchall()

            if not rows:
                continue

            column_names = [desc.name for desc in cursor.description]

            column_sql = ", ".join(
                q(column)
                for column in column_names
            )

            for row in rows:

                values = ", ".join(
                    lit(value)
                    for value in row
                )

                output.append(
                    f'INSERT INTO {q(schema_name)}.'
                    f'{q(table_name)} ({column_sql}) '
                    f'VALUES ({values});'
                )

            output.append("")

        print("Data export completed.")

    except Exception as e:

        print("\nERROR exporting data:")
        print(e)

        conn.rollback()


# ============================================================
# PRIMARY KEYS / UNIQUE / FOREIGN KEYS / CHECK CONSTRAINTS
# ============================================================

try:

    add_section("CONSTRAINTS")

    cursor.execute("""
        SELECT
            n.nspname,
            c.relname,
            con.conname,
            pg_get_constraintdef(con.oid, true),
            con.contype

        FROM pg_constraint con

        JOIN pg_class c
            ON c.oid = con.conrelid

        JOIN pg_namespace n
            ON n.oid = c.relnamespace

        WHERE n.nspname = %s

        ORDER BY
            CASE con.contype
                WHEN 'p' THEN 1
                WHEN 'u' THEN 2
                WHEN 'c' THEN 3
                WHEN 'f' THEN 4
                ELSE 5
            END,
            c.relname,
            con.conname;
    """, (SCHEMA_NAME,))

    constraints = cursor.fetchall()

    for (
        schema_name,
        table_name,
        constraint_name,
        definition,
        constraint_type
    ) in constraints:

        output.append(
            f'ALTER TABLE ONLY {q(schema_name)}.{q(table_name)} '
            f'ADD CONSTRAINT {q(constraint_name)} {definition};'
        )

    output.append("")

except Exception as e:

    print("Warning reading constraints:", e)


# ============================================================
# INDEXES
# ============================================================

try:

    add_section("INDEXES")

    cursor.execute("""
        SELECT
            n.nspname,
            t.relname,
            i.relname,
            pg_get_indexdef(i.oid)

        FROM pg_index x

        JOIN pg_class t
            ON t.oid = x.indrelid

        JOIN pg_class i
            ON i.oid = x.indexrelid

        JOIN pg_namespace n
            ON n.oid = t.relnamespace

        WHERE n.nspname = %s

          AND NOT EXISTS (
              SELECT 1
              FROM pg_constraint c
              WHERE c.conindid = i.oid
          )

        ORDER BY
            t.relname,
            i.relname;
    """, (SCHEMA_NAME,))

    indexes = cursor.fetchall()

    print(f"Indexes found: {len(indexes)}")

    for (
        schema_name,
        table_name,
        index_name,
        index_definition
    ) in indexes:

        output.append(
            index_definition + ";"
        )

    output.append("")

except Exception as e:

    print("Warning reading indexes:", e)


# ============================================================
# FUNCTIONS
# ============================================================

try:

    add_section("FUNCTIONS")

    cursor.execute("""
        SELECT
            n.nspname,
            p.oid,
            p.proname,
            pg_get_functiondef(p.oid)

        FROM pg_proc p

        JOIN pg_namespace n
            ON n.oid = p.pronamespace

        WHERE n.nspname = %s

        ORDER BY
            p.proname,
            p.oid;
    """, (SCHEMA_NAME,))

    functions = cursor.fetchall()

    print(f"Functions found: {len(functions)}")

    for (
        schema_name,
        function_oid,
        function_name,
        function_definition
    ) in functions:

        output.append(function_definition)

        if not function_definition.endswith(";"):
            output.append(";")

        output.append("")

except Exception as e:

    print("Warning reading functions:", e)


# ============================================================
# TRIGGERS
# ============================================================

try:

    add_section("TRIGGERS")

    cursor.execute("""
        SELECT
            n.nspname,
            c.relname,
            t.tgname,
            pg_get_triggerdef(t.oid, true)

        FROM pg_trigger t

        JOIN pg_class c
            ON c.oid = t.tgrelid

        JOIN pg_namespace n
            ON n.oid = c.relnamespace

        WHERE n.nspname = %s
          AND NOT t.tgisinternal

        ORDER BY
            c.relname,
            t.tgname;
    """, (SCHEMA_NAME,))

    triggers = cursor.fetchall()

    print(f"Triggers found: {len(triggers)}")

    for (
        schema_name,
        table_name,
        trigger_name,
        trigger_definition
    ) in triggers:

        output.append(
            trigger_definition + ";"
        )

    output.append("")

except Exception as e:

    print("Warning reading triggers:", e)


# ============================================================
# ROW LEVEL SECURITY
# ============================================================

try:

    add_section("ROW LEVEL SECURITY")

    cursor.execute("""
        SELECT
            n.nspname,
            c.relname,
            c.relrowsecurity,
            c.relforcerowsecurity

        FROM pg_class c

        JOIN pg_namespace n
            ON n.oid = c.relnamespace

        WHERE n.nspname = %s
          AND c.relkind = 'r'

        ORDER BY c.relname;
    """, (SCHEMA_NAME,))

    rls_tables = cursor.fetchall()

    for (
        schema_name,
        table_name,
        rls_enabled,
        rls_forced
    ) in rls_tables:

        if rls_enabled:

            output.append(
                f'ALTER TABLE {q(schema_name)}.{q(table_name)} '
                f'ENABLE ROW LEVEL SECURITY;'
            )

        if rls_forced:

            output.append(
                f'ALTER TABLE {q(schema_name)}.{q(table_name)} '
                f'FORCE ROW LEVEL SECURITY;'
            )

    output.append("")

except Exception as e:

    print("Warning reading RLS:", e)


# ============================================================
# RLS POLICIES
# ============================================================

try:

    add_section("RLS POLICIES")

    cursor.execute("""
        SELECT
            schemaname,
            tablename,
            policyname,
            permissive,
            roles,
            cmd,
            qual,
            with_check

        FROM pg_policies

        WHERE schemaname = %s

        ORDER BY
            tablename,
            policyname;
    """, (SCHEMA_NAME,))

    policies = cursor.fetchall()

    print(f"RLS policies found: {len(policies)}")

    for (
        schema_name,
        table_name,
        policy_name,
        permissive,
        roles,
        command,
        using_expression,
        check_expression
    ) in policies:

        permissive_sql = (
            "PERMISSIVE"
            if permissive == "PERMISSIVE"
            else "RESTRICTIVE"
        )

        roles_sql = ", ".join(
            q(role)
            if role != "public"
            else "PUBLIC"
            for role in roles
        )

        statement = (
            f'CREATE POLICY {q(policy_name)} '
            f'ON {q(schema_name)}.{q(table_name)} '
            f'AS {permissive_sql} '
            f'FOR {command} '
            f'TO {roles_sql}'
        )

        if using_expression:

            statement += (
                f' USING ({using_expression})'
            )

        if check_expression:

            statement += (
                f' WITH CHECK ({check_expression})'
            )

        statement += ";"

        output.append(statement)

    output.append("")

except Exception as e:

    print("Warning reading RLS policies:", e)


# ============================================================
# VIEWS
# ============================================================

try:

    add_section("VIEWS")

    cursor.execute("""
        SELECT
            n.nspname,
            c.relname,
            pg_get_viewdef(c.oid, true)

        FROM pg_class c

        JOIN pg_namespace n
            ON n.oid = c.relnamespace

        WHERE n.nspname = %s
          AND c.relkind = 'v'

        ORDER BY c.relname;
    """, (SCHEMA_NAME,))

    views = cursor.fetchall()

    print(f"Views found: {len(views)}")

    for (
        schema_name,
        view_name,
        definition
    ) in views:

        output.append(
            f'CREATE OR REPLACE VIEW '
            f'{q(schema_name)}.{q(view_name)} AS'
        )

        output.append(definition + ";")
        output.append("")

except Exception as e:

    print("Warning reading views:", e)


# ============================================================
# FINISH
# ============================================================

output.append("COMMIT;")
output.append("")
output.append("-- ============================================================")
output.append("-- END OF SUPABASE EXPORT")
output.append("-- ============================================================")


# ============================================================
# WRITE FILE
# ============================================================

try:

    Path(OUTPUT_FILE).write_text(
        "\n".join(output),
        encoding="utf-8"
    )

    print("\n" + "=" * 75)
    print("EXPORT COMPLETED SUCCESSFULLY")
    print("=" * 75)

    print(f"\nSQL file:")
    print(Path(OUTPUT_FILE).resolve())

    print(f"\nSize:")
    print(
        f"{Path(OUTPUT_FILE).stat().st_size / 1024:.2f} KB"
    )

    print("\nExported:")
    print("  ✓ Extensions")
    print("  ✓ Enum types")
    print("  ✓ Sequences")
    print("  ✓ Tables")
    print("  ✓ Constraints")
    print("  ✓ Indexes")
    print("  ✓ Functions")
    print("  ✓ Triggers")
    print("  ✓ RLS configuration")
    print("  ✓ RLS policies")
    print("  ✓ Views")

    if INCLUDE_DATA:
        print("  ✓ Table data")

    print("\nReady for restoration into another PostgreSQL/Supabase database.")

except Exception as e:

    print("\nFAILED WRITING SQL FILE:")
    print(e)

finally:

    cursor.close()
    conn.close()

    print("\nDatabase connection closed.")

