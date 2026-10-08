"""Long-term local memory (SQLite): facts the user asked Sama to remember + task history."""
import sqlite3
import time
from pathlib import Path


class Memory:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS facts(k TEXT PRIMARY KEY, v TEXT, ts REAL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, goal TEXT, result TEXT, ts REAL)")
        self.db.commit()

    def remember(self, key, value):
        self.db.execute("REPLACE INTO facts VALUES(?,?,?)", (key, value, time.time()))
        self.db.commit()

    def recall(self, query=""):
        rows = self.db.execute("SELECT k,v FROM facts WHERE k LIKE ? OR v LIKE ? ORDER BY ts DESC LIMIT 20",
                               (f"%{query}%", f"%{query}%")).fetchall()
        return {k: v for k, v in rows}

    def log_task(self, goal, result):
        self.db.execute("INSERT INTO tasks(goal,result,ts) VALUES(?,?,?)", (goal, result, time.time()))
        self.db.commit()

    def recent_tasks(self, n=5):
        return self.db.execute("SELECT goal,result FROM tasks ORDER BY id DESC LIMIT ?", (n,)).fetchall()
