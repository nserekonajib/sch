import psycopg
from pathlib import Path

PASSWORD = "Njk9WzAVwii5EjR0"





DB_CONFIG = {
    "host": "aws-0-eu-central-1.pooler.supabase.com",
    "port": 5432,
    "dbname": "postgres",
    "user": "postgres.qddnezmtskwclzzzfbun",
    "password": PASSWORD
}


backup_file = "auth_users_clean_backup.sql"


print("Connecting...")

conn = psycopg.connect(**DB_CONFIG)

print("Connected!")

cursor = conn.cursor()


try:

    print("Disabling triggers...")

    cursor.execute(
        "SET session_replication_role = 'replica';"
    )


    sql = Path(backup_file).read_text(
        encoding="utf-8"
    )


    print("Restoring auth users...")


    cursor.execute(sql)


    cursor.execute(
        "SET session_replication_role = 'origin';"
    )


    conn.commit()


    print("Auth users restored successfully!")


except Exception as e:

    print("FAILED:")
    print(e)

    conn.rollback()


finally:

    cursor.close()
    conn.close()