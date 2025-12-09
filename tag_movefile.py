import csv
import os
import shutil
from pathlib import Path
import sqlite3
from pathlib import Path
import datetime
import re
import chardet
import threading

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / 'novels.db'
NOVELS_DIR = BASE_DIR / 'novels'
NOVELS_DIR.mkdir(parents=True, exist_ok=True)


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

files=[]
def move_file():
        
    # 确保目标目录存在
    target_dir = Path("novels")
    target_dir.mkdir(exist_ok=True)

    cnt=0
    global files
    # 读取 mark.csv
    with open("records/mark.csv", "r", encoding="utf-8") as f:
        # CSV 可能没有标题行，按位置取字段
        for line_num, row in enumerate(csv.reader(f), start=1):
            try:
                # 至少需要 6 列：时间、级别、ID、文件名、路径、数字、tag
                if len(row) < 7:
                
                    continue

                file_path_str = row[4]  # 第5列（索引4）是完整路径
                tag = row[6].strip()    # 第7列（索引6）是 tag

                if tag == "del":
                    files.append(file_path_str)
                    src = Path(file_path_str)
                    if src.exists():
                        dst = target_dir / src.name
                        print(f"移动: {src} → {dst}")
                        shutil.move(str(src), str(dst))
                        cnt+=1
                    else:
                        continue
                        print(f"警告：文件不存在，跳过 → {src}")
            except Exception as e:
                print(f"处理第 {line_num} 行时出错: {e}")

    print("处理完成！",cnt)

def del_data():
    global files
    conn = get_db()
    cnt_data=conn.execute('select count(*) from novels').fetchone()[0]
    print("删除前数据量:",cnt_data)
    for f in files:
        conn.execute('delete from novels where path= ?', (f,)) 
    conn.commit()
    cnt_data2=conn.execute('select count(*) from novels').fetchone()[0]
    # print("删除后数据量:",cnt_data)
    print("删除数据：",cnt_data-cnt_data2)
    conn.close()
if __name__ == "__main__":
    move_file()
    del_data()