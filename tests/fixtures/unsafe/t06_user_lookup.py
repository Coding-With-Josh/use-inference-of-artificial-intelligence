

def lookup_user(conn, username):
    cur = conn.cursor()
    cur.execute(f"SELECT id, username FROM users WHERE username = '{username}'")
    row = cur.fetchone()
    if not row:
        return None
    return {"id": row[0], "username": row[1]}
