import os
import time
import sqlite3
import numpy as np
from sentence_transformers import SentenceTransformer
from tqdm import tqdm
import faiss
import pickle
os.environ['http_proxy'] = 'http://127.0.0.1:57713'
os.environ['https_proxy'] = 'http://127.0.0.1:57713'

# --- 配置部分 ---
DATA_FOLDER = "./novels"        # 小说文件夹路径
DATA_FOLDER = r'\\Synology\home\sync od\funny\收藏小说\s.收藏小说'       # 小说文件夹路径
DB_PATH = "novel_database.db"   # SQLite 数据库路径
INDEX_PATH = "vectors.index"    # FAISS 索引文件路径
MODEL_NAME = "BAAI/bge-small-zh-v1.5" # 推荐的中文模型，体积小效果好
BATCH_SIZE = 64                 # 批处理大小，显存/内存大可调大
READ_CHARS = 1000               # 读取前多少字

class NovelProcessor:
    def __init__(self, db_path, model_name):
        self.db_path = db_path
        print(f"正在加载模型 {model_name} (首次运行需下载)...")
        self.model = SentenceTransformer(model_name)
        self.init_db()

    def init_db(self):
        """初始化 SQLite 数据库结构"""
        with sqlite3.connect(self.db_path) as conn:
            # 创建表：存储路径、最后修改时间、前1000字、向量数据(BLOB)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filepath TEXT UNIQUE,
                    filename TEXT,
                    mtime REAL,
                    preview_content TEXT,
                    embedding BLOB
                )
            """)
            # 创建索引加速查询
            conn.execute("CREATE INDEX IF NOT EXISTS idx_filepath ON documents(filepath)")
            conn.commit()

    def get_db_file_states(self):
        """获取数据库中现有的文件状态 {filepath: mtime}"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT filepath, mtime FROM documents")
            return {row[0]: row[1] for row in cursor.fetchall()}

    def scan_local_files(self, folder):
        """扫描本地文件夹，返回 {filepath: mtime}"""
        local_files = {}
        for root, _, files in os.walk(folder):
            for file in files:
                if file.lower().endswith(('.txt', '.md')): # 支持 txt 和 md
                    full_path = os.path.abspath(os.path.join(root, file))
                    mtime = os.path.getmtime(full_path)
                    local_files[full_path] = mtime
        return local_files

    def read_text(self, filepath):
        """读取文件前 READ_CHARS 字，处理编码错误"""
        try:
            # 优先尝试 UTF-8
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read(READ_CHARS)
        except UnicodeDecodeError:
            try:
                # 尝试 GBK (中文旧小说常见)
                with open(filepath, 'r', encoding='gb18030') as f:
                    return f.read(READ_CHARS)
            except Exception:
                return "" # 读取失败返回空
        except Exception:
            return ""

    def process(self, data_folder):
        """核心处理逻辑：增量更新"""
        print("正在扫描文件差异...")
        db_files = self.get_db_file_states()
        local_files = self.scan_local_files(data_folder)

        # 1. 找出需要删除的文件 (DB中有，本地没有)
        to_delete = set(db_files.keys()) - set(local_files.keys())
        if to_delete:
            print(f"发现 {len(to_delete)} 个文件已删除，正在清理数据库...")
            with sqlite3.connect(self.db_path) as conn:
                # 批量删除
                batch_del = list(to_delete)
                for i in range(0, len(batch_del), 900): # SQLite limit safe
                    chunk = batch_del[i:i+900]
                    placeholders = ','.join(['?'] * len(chunk))
                    conn.execute(f"DELETE FROM documents WHERE filepath IN ({placeholders})", chunk)
                conn.commit()

        # 2. 找出需要新增或更新的文件
        to_process = [] # [(filepath, mtime, filename), ...]
        
        for fpath, mtime in local_files.items():
            # 如果不在库里，或者修改时间变了，就需要重新处理
            if fpath not in db_files or db_files[fpath] != mtime:
                to_process.append((fpath, mtime, os.path.basename(fpath)))

        if not to_process:
            print("没有文件需要更新。")
            return

        print(f"发现 {len(to_process)} 个文件需要处理 (新增/修改)。")

        # 3. 批量处理：读取 -> 向量化 -> 存库
        # 分批次处理以节省内存
        with sqlite3.connect(self.db_path) as conn:
            for i in tqdm(range(0, len(to_process), BATCH_SIZE), desc="生成向量"):
                batch_items = to_process[i : i + BATCH_SIZE]
                
                texts = []
                valid_items = []

                # 读取文本
                for item in batch_items:
                    fpath, mtime, fname = item
                    content = self.read_text(fpath)
                    if content.strip(): # 忽略空文件
                        texts.append(content)
                        valid_items.append(item + (content,))
                
                if not texts:
                    continue

                # 批量生成向量 (这是最耗时的步骤，Batch化后极快)
                embeddings = self.model.encode(texts, normalize_embeddings=True)

                # 写入数据库
                rows_to_insert = []
                for idx, item in enumerate(valid_items):
                    fpath, mtime, fname, content = item
                    emb_blob = embeddings[idx].astype(np.float32).tobytes() # 转为二进制存储
                    rows_to_insert.append((fpath, fname, mtime, content, emb_blob))

                # 使用 replace into 处理更新的情况
                conn.executemany("""
                    INSERT OR REPLACE INTO documents (filepath, filename, mtime, preview_content, embedding)
                    VALUES (?, ?, ?, ?, ?)
                """, rows_to_insert)
                conn.commit()

    def export_index(self, index_path):
        """从数据库读取所有向量，构建 FAISS 索引并保存"""
        print("正在从数据库导出向量构建索引...")
        with sqlite3.connect(self.db_path) as conn:
            # 只读取 ID 和 向量
            cursor = conn.execute("SELECT id, embedding FROM documents")
            ids = []
            vectors = []
            
            for row in cursor:
                doc_id, blob = row
                vec = np.frombuffer(blob, dtype=np.float32)
                ids.append(doc_id)
                vectors.append(vec)
        
        if not vectors:
            print("数据库为空，无法构建索引。")
            return

        # 转换为 numpy 矩阵
        vectors_np = np.array(vectors)
        ids_np = np.array(ids).astype('int64') # FAISS 需要 int64 ID

        # 构建索引 (IndexFlatIP 用于余弦相似度，因为我们前面normalize过)
        # 如果你数据量特别大(>100w)，可以用 IndexIVFFlat
        dimension = vectors_np.shape[1]
        index = faiss.IndexFlatIP(dimension) 
        
        # FAISS 默认不支持带 ID 的添加，需要用 IndexIDMap
        index_with_ids = faiss.IndexIDMap(index)
        index_with_ids.add_with_ids(vectors_np, ids_np)

        # 保存索引
        faiss.write_index(index_with_ids, index_path)
        print(f"索引已保存至 {index_path}，包含 {len(ids)} 条数据。")

# --- 使用示例 ---
if __name__ == "__main__":
    # 1. 确保数据文件夹存在
    if not os.path.exists(DATA_FOLDER):
        os.makedirs(DATA_FOLDER)
        print(f"请将小说文件放入 {DATA_FOLDER} 文件夹中")
    else:
        # 2. 运行处理流程
        processor = NovelProcessor(DB_PATH, MODEL_NAME)
        
        # 这一步会扫描文件夹，更新 DB
        processor.process(DATA_FOLDER)
        
        # 这一步会生成用于快速搜索的 .index 文件
        processor.export_index(INDEX_PATH)