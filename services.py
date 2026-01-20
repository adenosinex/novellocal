import utils_mark
# 文件打分

def mark_novel(user, novel_id, score, tag=None):
    conn = utils.get_db()
    cur = conn.execute('SELECT filename, path FROM novels WHERE id = ?', (novel_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return False
    utils_mark.write_mark(user, novel_id, row['filename'], row['path'], score, tag)
    return True

def get_novel_mark(user, novel_id):
    return utils_mark.get_mark(user, novel_id)

def get_all_tags():
    return utils_mark.get_all_tags()
import utils_read_record
from pathlib import Path
import utils

# 小说列表

def list_novels(page=1, page_size=20, with_total=False):
    conn = utils.get_db()
    offset = (page - 1) * page_size
    cur = conn.execute('SELECT id, filename, first100, added_at FROM novels ORDER BY added_at DESC LIMIT ? OFFSET ?', (page_size, offset))
    novels = cur.fetchall()
    total = None
    if with_total:
        total = conn.execute('SELECT COUNT(*) FROM novels').fetchone()[0]
    conn.close()
    if with_total:
        return novels, total
    return novels

# 索引文件或目录

def index_path(path_str):
    candidate = Path(path_str)
    if not candidate.is_absolute():
        candidate = utils.NOVELS_DIR / candidate
    if candidate.exists() and candidate.is_dir():
        count = 0
        for p in candidate.rglob('*.txt'):
            ok, _ = utils.index_file(p)
            if ok:
                count += 1
            print(f'\rIndexed: {count} - {"Success" if ok else "Failed"}', end='')
        print()  # Move to the next line after the loop
        return True, f'已索引目录 {candidate} 下 {count} 个文件（.txt）'
    ok, err = utils.index_file(candidate)
    if ok:
        return True, f'已索引: {candidate}'
    else:
        return False, f'索引失败: {err}'

# 搜索小说

def search_novels(q_filename, q_text):
    sql = 'SELECT id, filename, first100, added_at,path FROM novels'
    clauses = []
    params = []
    if q_filename:
        clauses.append('filename LIKE ?')
        params.append(f'%{q_filename}%')
    if q_text:
        clauses.append('first100 LIKE ?')
        params.append(f'%{q_text}%')
    if clauses:
        sql += ' WHERE ' + ' OR '.join(clauses)
    sql += ' ORDER BY added_at DESC LIMIT 200'
    conn = utils.get_db()
    cur = conn.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return rows

# 获取小说分页内容

def get_novel_page(novel_id, chapter_idx, page_num=None, page_size=None, user='default'):
    conn = utils.get_db()
    cur = conn.execute('SELECT * FROM novels WHERE id = ?', (novel_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None, None, None, None, None, None, None
    path = Path(row['path'])
    if not path.exists():
        content = ''
        chapters = [{'title': '文件不存在', 'start': 0, 'end': 0}]
    else:
        content, mtime = utils.memdb_get(str(path.resolve()))
        if content is None:
            try:
                content = utils.read_text_with_encoding(path)
            except Exception as e:
                content = f'读取文件失败: {e}'
            try:
                utils.memdb_set(str(path.resolve()), content, path.stat().st_mtime)
            except Exception:
                pass
        chapters = utils.extract_chapters(content)
    # 仅在未指定章节时自动跳转到历史节点
    node = None
    if chapter_idx is None:
        node = utils_read_record.get_read_node(user, novel_id)
        if node:
            chapter_idx = node.get('chapter_idx', 0)
    if chapter_idx is None or chapter_idx < 0 or chapter_idx >= len(chapters):
        chapter_idx = 0
    chap = chapters[chapter_idx]
    chapter_text = content[chap['start']:chap['end']] if chap['end'] > chap['start'] else ''
    # 记录整章节，无分页
    utils_read_record.write_read_log(user, novel_id, chapter_idx, 1)
    total_chars = len(content)
    read_chars = chap['end']
    percent = round(read_chars / total_chars * 100, 2) if total_chars > 0 else 0
    utils_read_record.write_read_node(user, novel_id, chapter_idx, 1, filename=row['filename'], total_chars=total_chars, percent=percent)
    return row['filename'], chapter_text, chapters, chapter_idx, 1, 1, node
