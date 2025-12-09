import csv
from pathlib import Path
from datetime import datetime

RECORD_DIR = Path(__file__).parent / 'records'
RECORD_DIR.mkdir(exist_ok=True)
MARK_FILE = RECORD_DIR / 'mark.csv'

def write_mark(user, novel_id, filename, path, score):
    with MARK_FILE.open('a', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            datetime.now().isoformat(), user, novel_id, filename, path, score
        ])

def get_mark(user, novel_id):
    if not MARK_FILE.exists():
        return None
    with MARK_FILE.open('r', encoding='utf-8', newline='') as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 6 and row[1] == user and row[2] == str(novel_id):
                return row[5]
    return None
