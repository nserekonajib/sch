import psycopg
from pathlib import Path
import json
import uuid
from decimal import Decimal
from datetime import datetime

PASSWORD = "OJYMMzwQADEUZsTM"



DB_CONFIG = {
    "host": "aws-1-eu-west-1.pooler.supabase.com",
    "port": 6543,
    "dbname": "postgres",
    "user": "postgres.wliebcdrpxxdqktjprdp",
    "password": PASSWORD
}


columns = [
    "instance_id",
    "id",
    "aud",
    "role",
    "email",
    "encrypted_password",
    "email_confirmed_at",
    "invited_at",
    "confirmation_token",
    "confirmation_sent_at",
    "recovery_token",
    "recovery_sent_at",
    "email_change_token_new",
    "email_change",
    "email_change_sent_at",
    "last_sign_in_at",
    "raw_app_meta_data",
    "raw_user_meta_data",
    "is_super_admin",
    "created_at",
    "updated_at",
    "phone",
    "phone_confirmed_at",
    "phone_change",
    "phone_change_token",
    "phone_change_sent_at",
    "email_change_token_current",
    "email_change_confirm_status",
    "banned_until",
    "reauthentication_token",
    "reauthentication_sent_at",
    "is_sso_user",
    "deleted_at",
    "is_anonymous"
]


def sql_value(v):

    if v is None:
        return "NULL"

    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"

    if isinstance(v, (dict,list)):
        return "'" + json.dumps(v).replace("'", "''") + "'::jsonb"

    return "'" + str(v).replace("'", "''") + "'"


conn = psycopg.connect(**DB_CONFIG)

cur = conn.cursor()


query = f"""
SELECT {",".join(columns)}
FROM auth.users;
"""


cur.execute(query)


rows = cur.fetchall()


print("Users:", len(rows))


sql = [
    "SET session_replication_role='replica';",
    "BEGIN;"
]


cols = ",".join(
    f'"{c}"'
    for c in columns
)


for row in rows:

    values = ",".join(
        sql_value(v)
        for v in row
    )

    sql.append(
        f"""
INSERT INTO auth.users
({cols})
VALUES ({values});
"""
    )


sql.append(
    "COMMIT;"
)


Path(
    "auth_users_clean_backup.sql"
).write_text(
    "\n".join(sql),
    encoding="utf-8"
)


cur.close()
conn.close()


print("Created auth_users_clean_backup.sql")