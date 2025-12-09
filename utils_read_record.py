import csv
from pathlib import Path
from datetime import datetime

RECORD_DIR = Path(__file__).parent / 'records'
RECORD_DIR.mkdir(exist_ok=True)

LOG_FILE = RECORD_DIR / 'read_log.csv'
NODE_FILE = RECORD_DIR / 'read_node.csv'

# 写入阅读日志（追加）
def write_read_log(user, novel_id, chapter_idx, page_num):
    with LOG_FILE.open('a', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            datetime.now().isoformat(), user, novel_id, chapter_idx, page_num
        ])

PROGRESS_FILE = RECORD_DIR / 'read_progress.csv'

# 写入最新节点（覆盖）
def write_read_node(user, novel_id, chapter_idx, page_num, filename=None, total_chars=None, percent=None):
    nodes = {}
    if NODE_FILE.exists():
        with NODE_FILE.open('r', encoding='utf-8', newline='') as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) >= 5:
                    nodes[(row[1], row[2])] = row
    nodes[(user, str(novel_id))] = [datetime.now().isoformat(), user, str(novel_id), str(chapter_idx), str(page_num)]
    with NODE_FILE.open('w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        for v in nodes.values():
            writer.writerow(v)
    # 记录进度到 read_progress.csv
    if filename is not None and total_chars is not None and percent is not None:
        with PROGRESS_FILE.open('a', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().isoformat(), user, novel_id, filename, total_chars, percent
            ])

# 读取最新节点
def get_read_node(user, novel_id):
    if not NODE_FILE.exists():
        return None
    with NODE_FILE.open('r', encoding='utf-8', newline='') as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 5 and row[1] == user and row[2] == str(novel_id):
                return {
                    'chapter_idx': int(row[3]),
                    'page_num': int(row[4])
                }
    return None
