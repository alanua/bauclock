import sqlite3
import os

def check():
    db_path = "d:\\Downloads\\SEK\\BauClock\\bauclock.db"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS daily_summaries")
    cur.execute("DROP TABLE IF EXISTS monthly_adjustments")
    try:
        cur.execute("ALTER TABLE payments DROP COLUMN payment_type")
    except Exception as e:
        print("Could not drop payment_type:", e)
    conn.commit()
    conn.close()
    
if __name__ == "__main__":
    check()
