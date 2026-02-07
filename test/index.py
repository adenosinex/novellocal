import os
import time
import sqlite3
import numpy as np
from sentence_transformers import SentenceTransformer
from tqdm import tqdm
import faiss
import pickle
import datetime

# 设置代理（如不需要可注释）
os.environ['http_proxy'] = 'http://127.0.0.1:57713'
os.environ['https_proxy'] = 'http://127.0.0.1:57713'

# --- 尝试导入视频处理库 ---
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    print("提示: 未安装 opencv-python，视频文件将仅读取大小信息，无法读取时长和分辨率。")
    CV2_AVAILABLE = False

# --- 全局配置列表 ---
# 在这里定义多个索引任务，彼此独立
CONFIG_LIST = [
    {
        "name": "Local_Novels",
        "folder": r"./novels",  # 你的小说路径
        "db_path": "db_novels.sqlite",
        "index_path": "index_novels.faiss",
        "type": "text",  # 类型：text 或 video
        "extensions": ('.txt', '.md', '.epub')
    },
    {
        "name": "Nas_Novels",
        "folder": r"\\Synology\home\sync od\funny\收藏小说\s.收藏小说",
        "db_path": "db_nas_novels.sqlite",
        "index_path": "index_nas_novels.faiss",
        "type": "text",
        "extensions": ('.txt', '.md')
    },
    {
        "name": "My_Videos",
        "folder": r"\\Synology\home\sync od\dy-fastnas\2026-02-05 auto", # 示例视频路径
        "db_path": "db_videos.sqlite",
        "index_path": "index_videos.faiss",
        "type": "video",
        "extensions": ('.mp4', '.mkv', '.avi', '.mov')
    }
]

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
BATCH_SIZE = 64
READ_CHARS = 1000  # 文本读取字数上限

class FileIndexer:
    def __init__(self, model_name):
        print(f"Loading Model: {model_name} ...")
        self.model = SentenceTransformer(model_name)

    def get_video_metadata(self, filepath):
        """提取视频元信息：时长、分辨率、大小"""
        file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
        meta_str = f"Size: {file_size_mb:.2f}MB"
        
        if CV2_AVAILABLE:
            try:
                cap = cv2.VideoCapture(filepath)
                if cap.isOpened():
                    width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                    height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                    
                    duration = frame_count / fps if fps > 0 else 0
                    minutes = int(duration // 60)
                    seconds = int(duration % 60)
                    
                    meta_str += f", Resolution: {int(width)}x{int(height)}, Duration: {minutes}m{seconds}s"
                cap.release()
            except Exception as e:
                pass # 读取视频流失败则只保留文件大小
        return meta_str

    def read_file_content(self, filepath, file_type):
        """
        核心读取函数
        返回: (preview_text, embedding_text)
        preview_text: 用于存数据库展示
        embedding_text: 用于生成向量（包含文件名和关键信息）
        """
        filename = os.path.basename(filepath)
        
        # --- 策略 A: 文本文件 ---
        if file_type == 'text':
            content = ""
            try:
                # 优先 UTF-8
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read(READ_CHARS)
            except UnicodeDecodeError:
                try:
                    # 备选 GB18030
                    with open(filepath, 'r', encoding='gb18030') as f:
                        content = f.read(READ_CHARS)
                except Exception:
                    content = "Decode Failed"
            except Exception:
                content = "Read Error"
            
            # 清洗空白字符
            content = content.strip()
            # 向量化文本 = 文件名 + 换行 + 文本内容 (增加文件名的权重)
            embedding_text = f"文件名: {filename}\n内容: {content}"
            return content, embedding_text

        # --- 策略 B: 视频/非文本文件 ---
        elif file_type == 'video':
            meta = self.get_video_metadata(filepath)
            # 向量化文本 = 文件名 + 元数据
            embedding_text = f"文件名: {filename}\n信息: {meta}"
            return meta, embedding_text
        
        return "", filename

    def init_db(self, db_path):
        """初始化单个配置的数据库"""
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filepath TEXT UNIQUE,
                    filename TEXT,
                    file_type TEXT,
                    mtime REAL,
                    preview_content TEXT,
                    embedding BLOB
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_filepath ON documents(filepath)")
            conn.commit()

    def run_config(self, config):
        """运行单个配置任务"""
        print(f"\n--- 处理任务: {config['name']} ---")
        
        folder = config['folder']
        db_path = config['db_path']
        index_path = config['index_path']
        file_type = config['type']
        extensions = config['extensions']

        if not os.path.exists(folder):
            print(f"跳过: 文件夹不存在 {folder}")
            return

        self.init_db(db_path)

        # 1. 扫描本地文件
        local_files = {}
        print(f"扫描目录: {folder}")
        for root, _, files in os.walk(folder):
            for file in files:
                if file.lower().endswith(extensions):
                    full_path = os.path.abspath(os.path.join(root, file))
                    local_files[full_path] = os.path.getmtime(full_path)

        # 2. 读取数据库状态
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute("SELECT filepath, mtime FROM documents")
            db_files = {row[0]: row[1] for row in cursor.fetchall()}

        # 3. 计算差异
        to_delete = set(db_files.keys()) - set(local_files.keys())
        to_process = []
        
        for fpath, mtime in local_files.items():
            if fpath not in db_files or db_files[fpath] != mtime:
                to_process.append(fpath)

        # 4. 执行删除
        if to_delete:
            print(f"清理 {len(to_delete)} 个已删除文件...")
            with sqlite3.connect(db_path) as conn:
                batch = list(to_delete)
                for i in range(0, len(batch), 900):
                    chunk = batch[i:i+900]
                    placeholders = ','.join(['?'] * len(chunk))
                    conn.execute(f"DELETE FROM documents WHERE filepath IN ({placeholders})", chunk)
                conn.commit()

        # 5. 执行新增/更新
        if to_process:
            print(f"发现 {len(to_process)} 个文件需要更新...")
            with sqlite3.connect(db_path) as conn:
                for i in tqdm(range(0, len(to_process), BATCH_SIZE), desc="索引中"):
                    batch_paths = to_process[i : i + BATCH_SIZE]
                    
                    texts_to_embed = []
                    rows_to_insert = []
                    
                    # 批量读取内容
                    for fpath in batch_paths:
                        preview, embed_text = self.read_file_content(fpath, file_type)
                        texts_to_embed.append(embed_text)
                        
                        mtime = local_files[fpath]
                        filename = os.path.basename(fpath)
                        rows_to_insert.append({
                            "path": fpath, "name": filename, 
                            "type": file_type, "mtime": mtime, 
                            "preview": preview
                        })

                    # 批量生成向量
                    if texts_to_embed:
                        embeddings = self.model.encode(texts_to_embed, normalize_embeddings=True)
                        
                        # 组合数据
                        final_data = []
                        for idx, row in enumerate(rows_to_insert):
                            emb_blob = embeddings[idx].astype(np.float32).tobytes()
                            final_data.append((
                                row["path"], row["name"], row["type"], 
                                row["mtime"], row["preview"], emb_blob
                            ))
                        
                        conn.executemany("""
                            INSERT OR REPLACE INTO documents 
                            (filepath, filename, file_type, mtime, preview_content, embedding)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, final_data)
                        conn.commit()
        else:
            print("文件无变化。")

        # 6. 生成独立索引文件
        self.export_index(db_path, index_path)

    def export_index(self, db_path, index_path):
        """生成 FAISS 索引"""
        print(f"正在生成索引: {index_path}")
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute("SELECT id, embedding FROM documents")
            ids = []
            vectors = []
            for row in cursor:
                ids.append(row[0])
                vectors.append(np.frombuffer(row[1], dtype=np.float32))
        
        if not vectors:
            print("警告: 数据库为空，跳过生成索引。")
            return

        vectors_np = np.array(vectors)
        ids_np = np.array(ids).astype('int64')
        
        # 建立索引 (Inner Product 用于余弦相似度)
        dimension = vectors_np.shape[1]
        index = faiss.IndexFlatIP(dimension)
        index_with_ids = faiss.IndexIDMap(index)
        index_with_ids.add_with_ids(vectors_np, ids_np)
        
        faiss.write_index(index_with_ids, index_path)
        print(f"索引生成完毕，包含 {len(ids)} 条数据。")

# --- 主程序入口 ---
if __name__ == "__main__":
    indexer = FileIndexer(MODEL_NAME)
    
    # 依次处理配置文件中的每个任务
    for config in CONFIG_LIST:
        try:
            indexer.run_config(config)
        except Exception as e:
            print(f"任务 {config['name']} 处理出错: {e}")
            import traceback
            traceback.print_exc()

    print("\n所有任务处理完成。")