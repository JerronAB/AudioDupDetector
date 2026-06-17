import sqlite3
from atexit import register
from marshal import loads, dumps

def ensureDatabase(DB: str):
    #create the table if it doesn't already exist
    print("Checking for databases...", )
    fp_db = sqlite3.connect(DB)
    fp_db_cur = fp_db.cursor()
    res = fp_db_cur.execute("SELECT name FROM sqlite_master")
    if not res.fetchone(): #is None if table doesn't exist
        print("No database found. Creating new table...")
        fp_db.execute("""
        CREATE TABLE fingerprints (
        path TEXT PRIMARY KEY, 
        fingerprint BLOB
        )""")
        fp_db.commit()
        fp_db.execute("""
        CREATE TABLE comparisons (
        id TEXT PRIMARY KEY, 
        timestamps TEXT
        )""")
        fp_db.commit()
    register(fp_db.close)
    return fp_db, fp_db_cur

def selectFrom(db_cursor, SELECT: str, FROM: str, WHERE: str, EQUALS_WHAT: str):
    res = db_cursor.execute(f"""
        SELECT {SELECT} FROM {FROM} 
        WHERE {WHERE}=?
        """, (EQUALS_WHAT,)
    )
    try: return loads(res.fetchone()[0])
    except TypeError: return None

def selectComparison(db_cursor, key: str):
    ts = selectFrom(db_cursor, "timestamps", "comparisons", "id", key)
    if ts: return ts
    else: return (None, None) #doubled to ensure unpacking doesn't fail

def selectFingerprint(db_cursor, key: str):
    return selectFrom(db_cursor, "fingerprint", "fingerprints", "path", key)

def insertInto(db_cursor, table, key, value):
    db_cursor.execute(f"""
        INSERT INTO {table} VALUES
        (?, ?)
    """, (key, dumps(value)))
    db_cursor.connection.commit()

def insertFingerprint(db_cursor, key, fp):
    insertInto(db_cursor, "fingerprints", key, fp)

def insertComparison(db_cursor, key, timestamps):
    assert isinstance(timestamps, tuple)
    assert len(timestamps) == 2
    insertInto(db_cursor, "comparisons", key, timestamps)