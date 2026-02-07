import time,os
import sqlite3
import faiss
import numpy as np
from flask import Flask, render_template, request, jsonify, render_template_string
from sentence_transformers import SentenceTransformer
os.environ['http_proxy'] = 'http://127.0.0.1:57713'
os.environ['https_proxy'] = 'http://127.0.0.1:57713'

# --- 配置 ---
DB_PATH = "novel_database.db"
INDEX_PATH = "vectors.index"
MODEL_NAME = "BAAI/bge-small-zh-v1.5"

# --- 搜索引擎核心类 (单例模式) ---
class SearchEngine:
    def __init__(self):
        print("正在初始化搜索引擎...")
        t0 = time.time()
        
        # 1. 加载模型 (通常耗时 2-3秒)
        self.model = SentenceTransformer(MODEL_NAME)
        
        # 2. 加载 FAISS 索引 (毫秒级)
        try:
            self.index = faiss.read_index(INDEX_PATH)
        except Exception as e:
            print(f"错误: 无法加载索引文件 {INDEX_PATH}。请先运行预处理脚本。")
            raise e
            
        print(f"搜索引擎初始化完成，耗时 {time.time() - t0:.2f}s")
        print(f"索引包含向量数: {self.index.ntotal}")

    def search(self, query, top_k=5):
        t_start = time.time()
        
        # 1. 文本转向量
        q_vec = self.model.encode([query], normalize_embeddings=True)
        
        # 2. 向量检索 (返回 距离D 和 ID I)
        D, I = self.index.search(q_vec, top_k)
        
        # 3. 结果处理
        doc_ids = [int(i) for i in I[0] if i != -1]
        if not doc_ids:
            return [], 0.0

        results_map = {}
        # 连接数据库获取详情
        with sqlite3.connect(DB_PATH) as conn:
            placeholders = ','.join('?' * len(doc_ids))
            sql = f"SELECT id, filename, preview_content FROM documents WHERE id IN ({placeholders})"
            cursor = conn.execute(sql, doc_ids)
            for row in cursor:
                results_map[row[0]] = {
                    'filename': row[1],
                    'preview': row[2]
                }

        # 4. 组装有序结果
        final_results = []
        for rank, doc_id in enumerate(doc_ids):
            if doc_id in results_map:
                item = results_map[doc_id]
                score = float(D[0][rank])
                final_results.append({
                    'id': doc_id,
                    'filename': item['filename'],
                    'preview': item['preview'][:200] + "...", # 截取展示
                    'score': round(score, 4), # 相似度分数
                    'match_percent': int(score * 100) # 转换为百分比展示
                })
        
        t_cost = time.time() - t_start
        return final_results, t_cost

# --- Flask 应用 ---
app = Flask(__name__)

# 全局加载引擎，避免每次请求都重新加载模型
try:
    engine = SearchEngine()
except Exception:
    engine = None

# --- 前端 HTML 模板 (使用 Tailwind CSS 美化) ---
@app.route('/')
def index():
    """直接渲染 templates 目录下的 index.html"""
    if engine is None:
        return "<h1>错误: 系统未初始化</h1><p>请检查向量索引是否存在。</p>"
    
    # Flask 会自动去 templates 文件夹里找文件
    return render_template('index.html')

@app.route('/api/search', methods=['POST'])
def api_search():
    """
    通用 API 接口
    Input: JSON { "query": "...", "top_k": 5 }
    Output: JSON { "status": "success", "data": [...], "time": 0.02 }
    """
    if engine is None:
        return jsonify({"status": "error", "message": "Engine not loaded"}), 500

    data = request.get_json()
    if not data or 'query' not in data:
        return jsonify({"status": "error", "message": "Missing query"}), 400

    query_text = data['query']
    top_k = data.get('top_k', 5) # 默认搜5条

    try:
        instruction = "为这个句子生成表示以用于检索相关文章："
        full_query = instruction + query_text
        results, t_cost = engine.search(full_query, top_k)
        return jsonify({
            "status": "success",
            "data": results,
            "time": t_cost
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    # threaded=True 允许并发请求 (对于只读搜索是安全的)
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)