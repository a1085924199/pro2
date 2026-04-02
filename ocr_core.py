#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ocr_core.py - OCR 核心处理模块 v7.0

架构：
  PPStructureV3Pool      - 主引擎池（PPStructureV3），项目启动时预加载
                           负责：文本识别、版面分析、表格结构识别
  OCRTask                - 任务类型枚举
  OCRPipeline            - 统一流水线，按任务类型分发处理
  DocParser              - 单据解析器基类
  RepairOrderParser      - 调修单专用解析器
  RepairCardParser       - 返修卡专用解析器
  MaterialParser         - 航材出入库单专用解析器
"""
import os
import json
import re
import cv2
import numpy as np
import requests
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any

os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')

try:
    from paddleocr import PPStructureV3
    _PP_STRUCTURE_V3_AVAILABLE = True
except ImportError:
    _PP_STRUCTURE_V3_AVAILABLE = False

# 任务类型枚举
from enum import Enum

class OCRTask(str, Enum):
    TEXT         = 'text'          # 简单文本识别
    TABLE        = 'table'         # 表格识别
    REPAIR_ORDER = 'repair_order'  # 调修单
    REPAIR_CARD  = 'repair_card'   # 返修卡
    MATERIAL     = 'material'      # 航材出入库单
    GENERAL      = 'general'       # 通用识别

# ============================================================================
# 模型路径配置
# ============================================================================
PADDLEX_MODELS_DIR = r'C:\Users\Administrator\.paddlex\official_models'
DET_MODEL_DIR      = os.path.join(PADDLEX_MODELS_DIR, 'PP-OCRv5_server_det')
REC_MODEL_DIR      = os.path.join(PADDLEX_MODELS_DIR, 'PP-OCRv5_server_rec')

# ============================================================================
# PPStructureV3 主引擎池（单例，项目启动时预加载）
# ============================================================================
class PPStructureV3Pool:
    """
    PPStructureV3 主引擎单例。
    - 作为系统主引擎，负责所有任务的版面分析、OCR 和表格识别。
    - 项目启动时通过 warmup() 后台预加载，避免首次请求延迟。
    - 线程安全，双重检查锁定模式。
     - 支持模型缓存和预热。
    """
    _instance: Optional['PPStructureV3Pool'] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._engine = None
                    cls._instance._ready = False
                    cls._instance._init_lock = threading.Lock()
                    cls._instance._warmup_done = False
        return cls._instance

    def _init(self):
        """初始化 PPStructureV3 引擎（幂等）"""
        with self._init_lock:
            if self._ready:
                return
            if getattr(self, '_init_failed', False):
                raise RuntimeError('PPStructureV3 引擎初始化已失败，跳过重试')
            if not _PP_STRUCTURE_V3_AVAILABLE:
                print('[PPStructureV3] PPStructureV3 不可用，请升级 paddleocr')
                self._init_failed = True
                raise RuntimeError('PPStructureV3 不可用，请执行: pip install -U paddleocr')
            try:
                print('[PPStructureV3] 正在初始化 PPStructureV3 主引擎...')
                import paddle
                # 尝试使用 GPU 加速，如果不可用则回退到 CPU
                try:
                    paddle.device.set_device('gpu')
                    device = 'gpu'
                    print('[PPStructureV3] 使用 GPU 加速')
                except Exception:
                    paddle.device.set_device('cpu')
                    device = 'cpu'
                    print('[PPStructureV3] GPU 不可用，使用 CPU')
                
                self._engine = PPStructureV3(
                    text_detection_model_dir=DET_MODEL_DIR,
                    text_recognition_model_dir=REC_MODEL_DIR,
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_table_recognition=True,
                    use_textline_orientation=True,
                    use_seal_recognition=False,
                    use_formula_recognition=False,
                    use_chart_recognition=False,
                    device=device,
                )
                self._ready = True
                print('[PPStructureV3] PPStructureV3 主引擎启动成功')
            except Exception as e:
                print(f'[PPStructureV3] 引擎初始化失败: {e}')
                print('[PPStructureV3]   将自动降级为 PaddleOCR 引擎处理所有任务')
                self._engine = None
                # 标记已尝试初始化，避免重复触发
                self._ready = False
                self._init_failed = True
                raise

    def get(self):
        """获取引擎（按需同步初始化）。引擎不可用时返回 None。"""
        if not self._ready:
            self._init()
        return self._engine

    @property
    def available(self) -> bool:
        """引擎是否可用（初始化成功且引擎实例非空）"""
        return self._ready and self._engine is not None and not getattr(self, '_init_failed', False)

    def warmup(self):
        """后台线程预热，供服务 startup 事件调用"""
        def _load():
            try:
                self._init()
                # 预热：使用一个小的测试图像进行一次预测
                if self._ready and self._engine:
                    import cv2
                    import numpy as np
                    # 创建一个小的测试图像
                    test_img = np.zeros((100, 100, 3), dtype=np.uint8)
                    cv2.putText(test_img, 'test', (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                    # 执行一次预测
                    list(self._engine.predict(test_img, use_table_recognition=False))
                    self._warmup_done = True
                    print('[PPStructureV3] 引擎预热完成')
            except Exception as e:
                print(f'[PPStructureV3] 预加载失败（不影响服务运行）: {e}')
        threading.Thread(target=_load, daemon=True).start()

    @property
    def ready(self) -> bool:
        return self._ready
        
    @property
    def warmup_done(self) -> bool:
        return getattr(self, '_warmup_done', False)


# PPStructureV3 全局主引擎单例
v3_pool = PPStructureV3Pool()


# ============================================================================
# 通用工具函数
# ============================================================================

def preprocess_image(image_path: str) -> np.ndarray:
    """读取图像并缩放，宽度上限 1600px，返回 BGR ndarray。"""
    # 使用更快的图像读取方式
    img = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f'无法读取图像: {image_path}')
    h, w = img.shape[:2]
    MAX_W = 1600
    if w > MAX_W:
        # 使用更快的插值方法
        img = cv2.resize(img, (MAX_W, int(h * MAX_W / w)), interpolation=cv2.INTER_LINEAR)
    return img


def run_ocr(image_path: str) -> List[Dict]:
    """
    使用 PPStructureV3 对图像文件运行纯文本 OCR（不做版面分析/表格识别）。
    返回统一格式文本框列表：[{text, confidence, bbox, poly}]
    """
    engine = v3_pool.get()
    if engine is None:
        raise RuntimeError('PPStructureV3 引擎不可用，无法执行 OCR')
    img_bgr = preprocess_image(image_path)
    results = list(engine.predict(img_bgr))
    return _extract_texts_from_results(results)


def _extract_texts_from_results(results: list) -> List[Dict]:
    """
    从 PPStructureV3 的 Result 对象列表中提取文本信息。
    返回统一格式的文本框列表：[{text, confidence, bbox, poly, type}]
    """
    ocr_results: List[Dict] = []
    
    for result in results:
        # 尝试从 Result 对象的标准属性提取文本
        texts = getattr(result, 'texts', None) or getattr(result, 'rec_texts', [])
        scores = getattr(result, 'rec_scores', []) or getattr(result, 'scores', [])
        
        if isinstance(texts, list) and texts:
            for i, text in enumerate(texts):
                score = float(scores[i]) if i < len(scores) else 0.0
                # 获取文本框位置信息
                polys = getattr(result, 'rec_polys', []) or []
                poly = []
                if i < len(polys):
                    poly_raw = polys[i]
                    poly = poly_raw.tolist() if hasattr(poly_raw, 'tolist') else list(poly_raw)
                
                # 计算 bbox
                bbox = []
                if poly:
                    xs = [p[0] for p in poly]
                    ys = [p[1] for p in poly]
                    bbox = [min(xs), min(ys), max(xs), max(ys)]
                
                ocr_results.append({
                    'text': str(text),
                    'confidence': round(score, 4),
                    'bbox': bbox,
                    'poly': poly,
                    'type': 'text',
                })
        
        # 尝试从 blocks 属性获取（版面分析结果）
        blocks = getattr(result, 'blocks', []) or []
        for block in blocks:
            block_type = getattr(block, 'type', 'text') or 'text'
            if 'table' in str(block_type).lower():
                continue  # 跳过表格块，表格由 Result 对象直接处理
            
            block_texts = getattr(block, 'texts', []) or getattr(block, 'rec_texts', [])
            block_scores = getattr(block, 'rec_scores', []) or []
            
            for i, text_info in enumerate(block_texts):
                if isinstance(text_info, dict):
                    text = text_info.get('text', '')
                    score = float(text_info.get('confidence', 0.0))
                else:
                    text = str(text_info)
                    score = float(block_scores[i]) if i < len(block_scores) else 0.0
                
                poly = text_info.get('poly', []) if isinstance(text_info, dict) else []
                bbox = text_info.get('bbox', []) if isinstance(text_info, dict) else []
                
                ocr_results.append({
                    'text': text,
                    'confidence': round(score, 4),
                    'bbox': bbox,
                    'poly': poly,
                    'type': str(block_type).lower(),
                })
    
    return ocr_results


def _parse_v3_result(pp_result: list, img_shape: tuple, xlsx_path: str = "") -> Dict:
    """
    从 PPStructureV3.predict() 结果中提取所需数据。
    优先从 pp_result 的 HTML 属性解析（内存中，无文件锁定问题），
    Excel 文件路径仅作参考，不依赖读取。
    """
    ocr_results: List[Dict] = _extract_texts_from_results(pp_result)

    # 优先从 pp_result 的 html 属性解析（最可靠，无文件句柄冲突）
    for result in pp_result:
        html = getattr(result, 'html', None)
        if html:
            table_data = _parse_table_from_html(html if isinstance(html, str) else str(html))
            if table_data:
                return {
                    'ocr_results': ocr_results,
                    'table_regions': [{
                        'bbox': list(getattr(result, 'bbox', [])) if hasattr(result, 'bbox') else [],
                        'html': table_data['html'],
                        'cells': table_data['cells'],
                        'num_rows': table_data['num_rows'],
                        'num_cols': table_data['num_cols'],
                    }],
                    'layout_regions': [],
                }

    # 降级：尝试从 HTML 解析（结果对象中取不到时）
    table_regions: List[Dict] = []
    for result in pp_result:
        html = getattr(result, 'html', None)
        if html:
            bbox = getattr(result, 'bbox', [])
            table_regions.append({
                'bbox': list(bbox) if bbox else [],
                'html': html if isinstance(html, str) else str(html),
                'cells': [],
                'num_rows': 0,
                'num_cols': 0,
            })

    return {
        'ocr_results': ocr_results,
        'table_regions': table_regions,
        'layout_regions': [],
    }


def build_table_structure(text_boxes: List[Dict]) -> Optional[Dict]:
    """
    将文本框列表按行列分组，生成结构化表格。
    """
    if not text_boxes:
        # 返回空表而不是 None，确保总有输出
        return {
            'table_idx': 0,
            'html': '<table></table>',
            'cells': [],
            'raw_cells': [],
            'bbox': [],
            'num_rows': 0,
            'num_cols': 0,
        }

    def yc(b): bx = b.get('bbox', []); return (bx[1]+bx[3])/2 if len(bx)==4 else 0
    def xc(b): bx = b.get('bbox', []); return (bx[0]+bx[2])/2 if len(bx)==4 else 0
    def x1(b): bx = b.get('bbox', []); return bx[0] if len(bx)==4 else 0
    def row_h(b): bx = b.get('bbox', []); return abs(bx[3]-bx[1]) if len(bx)==4 else 20

    # ── 1. 按 y 坐标分行 ──────────────────────────────────────────────────────
    sorted_boxes = sorted(text_boxes, key=lambda b: (yc(b), x1(b)))
    rows: List[List[Dict]] = []
    for box in sorted_boxes:
        placed = False
        for row in rows:
            # 用当前行平均行高的 70% 作为合并阈值（更宽松）
            avg_h = sum(row_h(b) for b in row) / len(row)
            row_yc = sum(yc(b) for b in row) / len(row)
            # 同时考虑绝对距离和相对距离，防止过度分行
            if abs(yc(box) - row_yc) < max(avg_h * 0.70, 15):
                row.append(box)
                placed = True
                break
        if not placed:
            rows.append([box])
    for row in rows:
        row.sort(key=x1)

    # ── 2. 列对齐：收集所有文本框 x 中心点，聚类成列索引 ────────────────────
    all_xc = sorted(set(round(xc(b)) for row in rows for b in row))
    col_centers: List[float] = []
    
    # 动态计算聚类阈值：基于文本框宽度的平均值
    avg_box_width = sum(b.get('bbox', [2])[2] - b.get('bbox', [0])[0] 
                        for b in text_boxes if len(b.get('bbox', [])) == 4) / max(len(text_boxes), 1)
    cluster_thresh = max(avg_box_width * 0.3, 20)  # 至少 20 像素
    
    for v in all_xc:
        if col_centers and abs(v - col_centers[-1]) < cluster_thresh:
            col_centers[-1] = (col_centers[-1] + v) / 2
        else:
            col_centers.append(float(v))

    def _col_idx(box):
        v = xc(box)
        return min(range(len(col_centers)), key=lambda i: abs(col_centers[i] - v))

    cells, raw_cells = [], []
    for r_idx, row in enumerate(rows):
        for box in row:
            c_idx = _col_idx(box)
            cell = {'row': r_idx, 'col': c_idx, 'row_span': 1, 'col_span': 1,
                    'text': box.get('text',''), 'confidence': box.get('confidence',0.0),
                    'bbox': box.get('bbox',[])}
            cells.append(cell)
            raw_cells.append({**cell, 'poly': box.get('poly',[])})

    num_cols = len(col_centers)
    html_rows = []
    for row in rows:
        col_map: Dict[int,str] = {_col_idx(b): b.get('text','') for b in row}
        tds = ''.join(f'<td>{col_map.get(c,"")}</td>' for c in range(num_cols))
        html_rows.append(f'<tr>{tds}</tr>')
    html = '<table>'+''.join(html_rows)+'</table>'

    all_b = [b['bbox'] for b in text_boxes if len(b.get('bbox',[]))==4]
    overall_bbox = ([min(b[0] for b in all_b), min(b[1] for b in all_b),
                     max(b[2] for b in all_b), max(b[3] for b in all_b)] if all_b else [])
    return {'table_idx':0,'html':html,'cells':cells,'raw_cells':raw_cells,
            'bbox':overall_bbox,'num_rows':len(rows),'num_cols':num_cols}


# ============================================================================
# 单据解析器基类
# ============================================================================
class DocParser:
    FIELDS: List[str] = []

    def parse(self, image_path: str, use_fastgpt=False, fastgpt_config=None, output_dir: str = None) -> Dict:
        """
        统一解析入口：
        1. PPStructureV3 完整处理（版面分析 + OCR + 表格）
        2. 使用 Result 对象的方法保存 HTML + Excel
        3. 提取字段并返回统一输出结构
        """
        img_bgr = cv2.imread(image_path)
        if img_bgr is None:
            raise ValueError(f'无法读取图像: {image_path}')

        output_dir = output_dir or 'output'
        os.makedirs(output_dir, exist_ok=True)
        base_name = os.path.basename(image_path).split('.')[0]
        xlsx_path = os.path.join(output_dir, f"{base_name}_table.xlsx")

        # PPStructureV3 处理
        try:
            if not v3_pool.available:
                raise RuntimeError('PPStructureV3 不可用，使用降级引擎')
            engine = v3_pool.get()
            results = list(engine.predict(img_bgr))
            
            # 使用 Result 对象的方法保存表格数据
            for res in results:
                res.save_to_html(save_path=os.path.join(output_dir, f"{base_name}_table.html"))
                res.save_to_xlsx(save_path=xlsx_path)
            
            parsed = _parse_v3_result(results, img_bgr.shape[:2], xlsx_path=xlsx_path)
            ocr_results = parsed['ocr_results']
            table_regions = parsed['table_regions']
        except Exception as e:
            print(f'[DocParser] PPStructureV3 失败，使用纯 OCR 降级: {e}')
            ocr_results = run_ocr(image_path)
            table_regions = []
            print(f'[DocParser] 降级 OCR 完成，识别到 {len(ocr_results)} 个文本块')

        # 表格结构化
        if table_regions:
            table = {
                'table_idx': 0,
                'html': table_regions[0]['html'],
                'cells': table_regions[0]['cells'],
                'bbox': table_regions[0]['bbox'],
                'num_rows': max((c['row'] for c in table_regions[0]['cells']), default=0) + 1,
                'num_cols': max((c['col'] for c in table_regions[0]['cells']), default=0) + 1,
            }
        else:
            table = build_table_structure(ocr_results)

        # 字段提取
        if use_fastgpt and fastgpt_config and fastgpt_config.get('api_key'):
            fields = self._extract_fastgpt(ocr_results, fastgpt_config)
        else:
            fields = self.extract_fields(ocr_results)

        # 生成摘要
        filled = sum(1 for v in fields.values() if v)
        summary = (f'共识别 {len(ocr_results)} 个文本块'
                   + (f'，{len(table_regions)} 个表格区域' if table_regions else '')
                   + f'，提取字段 {filled}/{len(self.FIELDS)} 个')

        return {
            'success': True,
            'image_path': image_path,
            'image_name': os.path.basename(image_path),
            'ocr_results': ocr_results,
            'table_regions': table_regions,
            'extracted_fields': fields,
            'table': table,
            'summary': summary,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }

    def extract_fields(self, ocr_results: List[Dict]) -> Dict[str, str]:
        return {f: '' for f in self.FIELDS}

    def _extract_fastgpt(self, texts: List[Dict], cfg: Dict) -> Dict[str, str]:
        api_url = cfg.get('api_url', '')
        api_key = cfg.get('api_key', '')
        appid   = cfg.get('appid', '')
        if not api_key:
            return self.extract_fields(texts)
        try:
            ocr_text   = '\n'.join(t['text'] for t in texts)
            fields_str = '\n'.join(f'  - {f}' for f in self.FIELDS)
            prompt = (f'你是单据信息提取助手。请从以下OCR文本中提取字段：\n{fields_str}\n\n'
                      f'【OCR文本】\n{ocr_text}\n\n'
                      f'以JSON数组返回：[{{"field":"字段名","value":"内容"}}]，未找到填空字符串。只返回JSON数组。')
            resp = requests.post(
                api_url,
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json={'appId': appid, 'chatId': self.__class__.__name__, 'stream': False, 'detail': False,
                      'variables': {'ocr_text': ocr_text,
                                    'fields_def': json.dumps([{'field': f} for f in self.FIELDS], ensure_ascii=False)},
                      'messages': [{'role': 'user', 'content': prompt}]},
                timeout=30)
            if resp.status_code == 200:
                content = resp.json().get('choices',[{}])[0].get('message',{}).get('content','')
                m = re.search(r'\[.*\]', content, re.DOTALL)
                if m:
                    result = {f: '' for f in self.FIELDS}
                    for item in json.loads(m.group()):
                        fn = item.get('field','')
                        if fn in result: result[fn] = item.get('value','')
                    return result
        except Exception as e:
            print(f'FastGPT调用失败({self.__class__.__name__}): {e}')
        return self.extract_fields(texts)

    @staticmethod
    def _find_nearest(label_item, candidates, max_x_gap=600, max_y_gap=40):
        def _x1(i): b=i.get('bbox',[]); return b[0] if len(b)==4 else 0
        def _x2(i): b=i.get('bbox',[]); return b[2] if len(b)==4 else 9999
        def _y2(i): b=i.get('bbox',[]); return b[3] if len(b)==4 else 9999
        def _yc(i): b=i.get('bbox',[]); return (b[1]+b[3])/2 if len(b)==4 else 0
        lx2=_x2(label_item); lyc=_yc(label_item); ly2=_y2(label_item)
        best, best_dist = None, 9999
        for c in candidates:
            if c is label_item: continue
            cx1=_x1(c); cyc=_yc(c)
            if cx1 > lx2 and abs(cyc-lyc) < max_y_gap: dist=cx1-lx2
            elif cx1 < _x2(label_item)+50 and cyc > ly2 and (cyc-ly2) < max_y_gap*2: dist=cyc-ly2+200
            else: continue
            if dist < best_dist: best_dist=dist; best=c
        return best


# ── 调修单解析器 ──────────────────────────────────────────────────────────────
class RepairOrderParser(DocParser):
    FIELDS = ['调修单号','装备型号','器材名称','型（图）号','器件编号','邮寄地址','进厂时间']

    def extract_fields(self, ocr_results):
        fields = {f:'' for f in self.FIELDS}
        texts  = sorted(ocr_results, key=lambda t: t['bbox'][1] if len(t.get('bbox',[]))==4 else 0)
        F = self._find_nearest
        # 过滤掉空文本
        texts = [t for t in texts if t.get('text','').strip()]
        for item in texts:
            t = item['text']
            if not fields['调修单号']:
                if any(k in t for k in ['调修单','单号','调修单号']):
                    nb=F(item,texts)
                    if nb and len(nb['text'])>4: fields['调修单号']=nb['text']
                    elif len(t)>8 and re.search(r'[A-Za-z].*\d|\d.*[A-Za-z]',t): fields['调修单号']=t
                elif re.match(r'^[A-Z]{1,3}\d{6,}$',t.strip()): fields['调修单号']=t
            if not fields['装备型号']:
                if any(k in t for k in ['装备型号','型号','装备']):
                    nb=F(item,texts);
                    if nb: fields['装备型号']=nb['text']
                elif re.search(r'\d{3}[A-Za-z]?型|\d{3}-\d',t): fields['装备型号']=t
            if not fields['器材名称']:
                if any(k in t for k in ['器材名称','器材','名称']):
                    nb=F(item,texts);
                    if nb: fields['器材名称']=nb['text']
                elif any(k in t for k in ['组件','电源','计算','模块','单元']): fields['器材名称']=t
            if not fields['型（图）号']:
                if any(k in t for k in ['型（图）号','图号','型号图号']):
                    nb=F(item,texts);
                    if nb: fields['型（图）号']=nb['text']
                elif re.search(r'AL\d+|\d+AL|图\d+',t): fields['型（图）号']=t
            if not fields['器件编号']:
                if any(k in t for k in ['器件编号','器件','编号','件号']):
                    nb=F(item,texts)
                    if nb and re.match(r'^\d{4,}$',nb['text'].strip()): fields['器件编号']=nb['text']
                elif re.match(r'^\d{4,9}$',t.strip()): fields['器件编号']=t
            if not fields['邮寄地址']:
                if any(k in t for k in ['邮寄地址','地址','收件']):
                    nb=F(item,texts,max_x_gap=600,max_y_gap=60);
                    if nb: fields['邮寄地址']=nb['text']
                elif any(k in t for k in ['省','市','区','县','路','街道']) and len(t)>6: fields['邮寄地址']=t
            if not fields['进厂时间']:
                if any(k in t for k in ['进厂时间','进厂','入厂','日期']):
                    nb=F(item,texts)
                    if nb and any(k in nb['text'] for k in ['年','月','日','-','/']): fields['进厂时间']=nb['text']
                elif re.search(r'\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}',t): fields['进厂时间']=t
        return fields


# ── 返修卡解析器 ──────────────────────────────────────────────────────────────
class RepairCardParser(DocParser):
    FIELDS = ['返修单号','故障描述','送修单位','返修日期','技术状态']

    def extract_fields(self, ocr_results):
        fields = {f:'' for f in self.FIELDS}
        texts  = sorted(ocr_results, key=lambda t: t['bbox'][1] if len(t.get('bbox',[]))==4 else 0)
        for item in texts:
            t = item['text']
            for f in self.FIELDS:
                if not fields[f] and f in t:
                    val = t.replace(f,'').replace('：','').replace(':','').strip()
                    fields[f] = val if val else (self._find_nearest(item,texts) or {}).get('text','')
        return fields


# ── 航材出入库单解析器 ────────────────────────────────────────────────────────
class MaterialParser(DocParser):
    FIELDS_OUT = ['出库单号','航材名称','航材型号','数量','出库日期','经手人','领用单位','备注']
    FIELDS_IN  = ['入库单号','航材名称','航材型号','数量','入库日期','经手人','供应商','备注']
    FIELDS     = FIELDS_OUT  # 默认

    def __init__(self, doc_type: str = 'out'):
        self.doc_type = doc_type
        self.FIELDS   = self.FIELDS_OUT if doc_type == 'out' else self.FIELDS_IN

    def extract_fields(self, ocr_results):
        fields = {f:'' for f in self.FIELDS}
        for item in ocr_results:
            t = item['text']
            for f in self.FIELDS:
                if not fields[f] and f in t:
                    val = t.replace(f,'').replace('：','').replace(':','').strip()
                    if val: fields[f] = val
        return fields


# ============================================================================
# 统一 OCR 流水线
# ============================================================================
class OCRPipeline:
    """
    统一 OCR 流水线，按任务类型分发处理。
    """
    @staticmethod
    def process(image_path: str, task_type: OCRTask = OCRTask.GENERAL, **kwargs) -> Dict:
        """
        处理 OCR 任务，返回统一格式结果。

        参数:
            image_path: 图像文件路径
            task_type: 任务类型
            **kwargs: 额外参数
                - use_fastgpt: 是否使用 FastGPT 优化
                - fastgpt_config: FastGPT 配置
                - output_dir: 输出目录
        """
        output_dir = kwargs.get('output_dir', 'output')
        os.makedirs(output_dir, exist_ok=True)

        # 生成输出文件名
        base_name = os.path.basename(image_path).split('.')[0]
        json_path = os.path.join(output_dir, f"{base_name}.json")
        md_path = os.path.join(output_dir, f"{base_name}.md")
        html_path = os.path.join(output_dir, f"{base_name}_table.html")
        xlsx_path = os.path.join(output_dir, f"{base_name}_table.xlsx")

        # 初始化引擎
        engine = v3_pool.get()
        if engine is None:
            raise RuntimeError('PPStructureV3 引擎不可用')

        # 执行推理
        img_bgr = preprocess_image(image_path)
        results = list(engine.predict(img_bgr))

        # 使用 Result 对象的内置方法保存结果（参考 test_ppstructurev3_seal.py）
        for res in results:
            res.save_to_json(save_path=json_path)
            res.save_to_markdown(save_path=md_path)
            res.save_to_html(save_path=html_path)
            res.save_to_xlsx(save_path=xlsx_path)

        # 解析结果获取文本和表格数据
        parsed = _parse_v3_result(results, img_bgr.shape[:2], xlsx_path=xlsx_path)
        ocr_results = parsed['ocr_results']
        table_regions = parsed['table_regions']

        # 提取表格结构信息
        table = {
            'table_idx': 0,
            'html': '',
            'cells': [],
            'bbox': [],
            'num_rows': 0,
            'num_cols': 0,
        }
        if table_regions:
            table = {
                'table_idx': 0,
                'html': table_regions[0].get('html', ''),
                'cells': table_regions[0].get('cells', []),
                'bbox': table_regions[0].get('bbox', []),
                'num_rows': max((c['row'] for c in table_regions[0].get('cells', [])), default=0) + 1,
                'num_cols': max((c['col'] for c in table_regions[0].get('cells', [])), default=0) + 1,
            }
        elif ocr_results:
            # 如果没有检测到表格区域，使用备用方案
            table = build_table_structure(ocr_results)

        # 当 ocr_results 为空但 table_regions 有 cells 时，从 cells 重建 ocr_results
        # 这样字段解析器（RepairOrderParser 等）仍能正常工作
        if not ocr_results and table.get('cells'):
            cells = table['cells']
            # 估算 bbox（根据行列位置估算相对坐标，避免为空）
            for cell in cells:
                if cell.get('text', '').strip():
                    ocr_results.append({
                        'text': cell['text'],
                        'confidence': cell.get('confidence', 1.0),
                        'bbox': [cell['col'] * 100, cell['row'] * 30, (cell['col'] + 1) * 100, (cell['row'] + 1) * 30],
                        'poly': [],
                        'type': 'table_cell',
                    })

        # 根据任务类型选择解析器并提取字段
        extracted_fields = {}
        if task_type != OCRTask.GENERAL:
            parser_map = {
                OCRTask.REPAIR_ORDER: RepairOrderParser(),
                OCRTask.REPAIR_CARD: RepairCardParser(),
                OCRTask.MATERIAL: MaterialParser(kwargs.get('doc_type', 'out')),
            }
            parser = parser_map.get(task_type, DocParser())

            if kwargs.get('use_fastgpt') and kwargs.get('fastgpt_config'):
                extracted_fields = parser._extract_fastgpt(ocr_results, kwargs.get('fastgpt_config'))
            else:
                extracted_fields = parser.extract_fields(ocr_results)

        # 构建返回结果
        result = {
            'success': True,
            'image_path': image_path,
            'image_name': os.path.basename(image_path),
            'ocr_results': ocr_results,
            'table_regions': table_regions,
            'table': table,
            'extracted_fields': extracted_fields,
            'summary': f'共识别 {len(ocr_results)} 个文本块，{len(table_regions)} 个表格区域',
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }

        # 保存解析结果（包含提取的字段信息）
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print(f"[SUCCESS] 识别完成！结果已保存至：{output_dir}")
        print("[INFO] 生成的文件：")
        print(f"  - {base_name}.json (完整识别结果)")
        print(f"  - {base_name}.md (Markdown结果)")
        print(f"  - {base_name}_table.html (表格HTML)")
        print(f"  - {base_name}_table.xlsx (表格Excel)")

        return result

    @staticmethod
    def run(image_path: str, task: str = 'general', **kwargs) -> Dict:
        """
        兼容旧接口的运行方法
        """
        task_map = {
            'text': OCRTask.TEXT,
            'table': OCRTask.TABLE,
            'repair_order': OCRTask.REPAIR_ORDER,
            'repair_card': OCRTask.REPAIR_CARD,
            'material': OCRTask.MATERIAL,
            'general': OCRTask.GENERAL
        }
        task_type = task_map.get(task, OCRTask.GENERAL)
        return OCRPipeline.process(image_path, task_type, **kwargs)


# ============================================================================
# 兼容层：RepairOrderOCR
# ============================================================================
class RepairOrderOCR:
    """
    兼容旧接口的调修单OCR处理器
    """
    def __init__(self):
        pass

    def process_image(self, image_path: str, use_fastgpt: bool = False, fastgpt_config: dict = None, output_dir: str = None) -> Dict:
        """
        处理调修单图像
        """
        return OCRPipeline.process(
            image_path,
            task_type=OCRTask.REPAIR_ORDER,
            use_fastgpt=use_fastgpt,
            fastgpt_config=fastgpt_config,
            output_dir=output_dir or 'output'
        )

    def ocr_recognize(self, image_path: str, output_dir: str = None) -> List[Dict]:
        """
        纯OCR识别
        """
        result = OCRPipeline.process(
            image_path,
            task_type=OCRTask.TEXT,
            output_dir=output_dir or 'output'
        )
        return result['ocr_results']


# ============================================================================
# 表格解析工具：从 PPStructureV3 生成的 Excel 读取结构化表格
# ============================================================================
def _parse_table_from_html(html: str) -> Optional[Dict]:
    """
    从 PPStructureV3 的 HTML 表格中解析单元格结构。
    正确处理 rowspan/colspan 合并单元格，返回展开后的行列网格。
    """
    if not html:
        return None
    try:
        from html.parser import HTMLParser

        class TableParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.grid: List[List[str]] = []
                self.current_row: List[str] = []
                self.current_cell_text: str = ""
                self.in_cell: bool = False

            def handle_starttag(self, tag, attrs):
                attrs_dict = dict(attrs)
                if tag == "tr":
                    self.current_row = []
                elif tag in ("td", "th"):
                    self.in_cell = True
                    self.current_cell_text = ""

            def handle_endtag(self, tag):
                if tag in ("td", "th") and self.in_cell:
                    self.in_cell = False
                    text = self.current_cell_text.strip()
                    self.current_row.append(text)
                elif tag == "tr":
                    if self.current_row:
                        self.grid.append(self.current_row)

            def handle_data(self, data):
                if self.in_cell:
                    self.current_cell_text += data

        parser = TableParser()
        parser.feed(html)
        grid = parser.grid

        if not grid:
            return None

        num_rows = len(grid)
        num_cols = max((len(row) for row in grid), default=0)

        # 构建 cells 列表
        cells = []
        for r in range(num_rows):
            for c in range(len(grid[r])):
                cells.append({
                    'row': r,
                    'col': c,
                    'row_span': 1,
                    'col_span': 1,
                    'text': grid[r][c],
                    'confidence': 1.0,
                })

        # 重建标准 HTML（去掉非标准格式）
        rows_html = []
        for row in grid:
            rows_html.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
        std_html = "<table>" + "".join(rows_html) + "</table>"

        return {
            'html': std_html,
            'cells': cells,
            'num_rows': num_rows,
            'num_cols': num_cols,
        }
    except Exception as e:
        print(f"[_parse_table_from_html] 解析失败: {e}")
        return None


def _read_table_from_excel(xlsx_path: str) -> Optional[Dict]:
    """
    读取 PPStructureV3 保存的 Excel 文件，返回标准表格结构。
    这是最可靠的表格数据来源，比解析 HTML 或从文本框反推更准确。

    返回:
        {
            'html': str,           # 重建的 HTML 表格
            'cells': [{row, col, row_span, col_span, text, confidence}],
            'num_rows': int,
            'num_cols': int,
        }
        若文件不存在或读取失败，返回 None。
    """
    if not os.path.exists(xlsx_path):
        return None
    try:
        import pandas as pd
        df = pd.read_excel(xlsx_path, header=None, dtype=str).fillna("")
        grid = df.values.tolist()
        num_rows = len(grid)
        num_cols = len(grid[0]) if grid else 0

        if num_rows == 0 or num_cols == 0:
            return None

        cells = []
        for r in range(num_rows):
            for c in range(num_cols):
                cells.append({
                    'row': r,
                    'col': c,
                    'row_span': 1,
                    'col_span': 1,
                    'text': str(grid[r][c]),
                    'confidence': 1.0,
                })

        rows_html = []
        for r in range(num_rows):
            tds = "".join(f"<td>{grid[r][c]}</td>" for c in range(num_cols))
            rows_html.append(f"<tr>{tds}</tr>")
        html = "<table>" + "".join(rows_html) + "</table>"

        return {
            'html': html,
            'cells': cells,
            'num_rows': num_rows,
            'num_cols': num_cols,
        }
    except Exception as e:
        print(f"[_read_table_from_excel] 读取失败: {e}")
        return None


# ============================================================================
# 兼容层：表格相关函数和类
# ============================================================================
def run_pp_structure(image_path: str, output_dir: str = None) -> Dict:
    """
    兼容旧接口的表格识别函数
    """
    result = OCRPipeline.process(
        image_path,
        task_type=OCRTask.TABLE,
        output_dir=output_dir or 'output'
    )
    table = result.get('table', {})
    return {
        'html': table.get('html', ''),
        'cells': table.get('cells', []),
        'num_rows': table.get('num_rows', 0),
        'num_cols': table.get('num_cols', 0),
        'ocr_count': len(result.get('ocr_results', []))
    }

def _build_table_from_textboxes(text_boxes: List[Dict]) -> Dict:
    """
    从文本框构建表格结构（纯几何推断，仅作为最终 fallback）。
    优先由 _read_table_from_excel 处理，本函数仅在无 Excel 时兜底使用。
    """
    return build_table_structure(text_boxes)


class TableDetector:
    """
    表格检测辅助工具，提供单元格到网格的转换。
    """
    @staticmethod
    def _cells_to_grid(cells: List[Dict], num_rows: int, num_cols: int) -> List[List[str]]:
        """
        将单元格列表转换为二维网格数组。
        """
        grid = [[""] * num_cols for _ in range(num_rows)]
        for cell in cells:
            row = cell.get('row', 0)
            col = cell.get('col', 0)
            if 0 <= row < num_rows and 0 <= col < num_cols:
                grid[row][col] = cell.get('text', '')
        return grid


class TableExporter:
    """
    兼容旧接口的表格导出器
    """
    @staticmethod
    def export_all(grid: List[List[str]], base_path: str) -> Dict:
        """
        导出所有格式（JSON + HTML + Excel + CSV + Markdown）
        """
        return {
            'json':     TableExporter.to_json(grid, base_path + ".json"),
            'html':     TableExporter.to_html(grid, base_path + ".html"),
            'excel':    TableExporter.to_excel(grid, base_path + ".xlsx"),
            'csv':      TableExporter.to_csv(grid, base_path + ".csv"),
            'markdown': TableExporter.to_markdown(grid, base_path + ".md"),
        }
    
    @staticmethod
    def to_json(grid: List[List[str]], output_path: str) -> str:
        """导出为 JSON（包含行列结构）"""
        try:
            data = {
                "rows": len(grid),
                "cols": len(grid[0]) if grid else 0,
                "data": grid,
            }
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return output_path
        except Exception as e:
            print(f"[WARN] 导出JSON失败: {e}")
            return ""

    @staticmethod
    def to_html(grid: List[List[str]], output_path: str) -> str:
        """导出为 HTML 表格"""
        try:
            rows_html = []
            for r_idx, row in enumerate(grid):
                cells = ''.join(
                    f"<td>{cell}</td>" for cell in row
                )
                tag = 'th' if r_idx == 0 else 'td'
                rows_html.append(f"<tr>{cells}</tr>")
            html = (
                "<!DOCTYPE html>\n"
                "<html><head><meta charset='utf-8'>"
                "<style>"
                "table{border-collapse:collapse;width:100%;font-family:Microsoft YaHei,sans-serif}"
                "th,td{border:1px solid #ccc;padding:8px 12px;text-align:left}"
                "th{background:#f5f5f5;font-weight:bold}"
                "tr:nth-child(even){background:#fafafa}"
                "</style></head><body>"
                f"<table>{''.join(rows_html)}</table>"
                "</body></html>"
            )
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(html)
            return output_path
        except Exception as e:
            print(f"[WARN] 导出HTML失败: {e}")
            return ""

    @staticmethod
    def to_excel(grid: List[List[str]], output_path: str) -> str:
        """
        导出为Excel
        """
        try:
            import pandas as pd
            df = pd.DataFrame(grid)
            df.to_excel(output_path, index=False, header=False)
            return output_path
        except Exception as e:
            print(f"[WARN] 导出Excel失败: {e}")
            return ""
    
    @staticmethod
    def to_csv(grid: List[List[str]], output_path: str) -> str:
        """
        导出为CSV
        """
        try:
            import csv
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerows(grid)
            return output_path
        except Exception as e:
            print(f"[WARN] 导出CSV失败: {e}")
            return ""
    
    @staticmethod
    def to_markdown(grid: List[List[str]], output_path: str) -> str:
        """
        导出为Markdown
        """
        try:
            markdown = []
            for row in grid:
                markdown.append('| ' + ' | '.join(row) + ' |')
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(markdown))
            return output_path
        except Exception as e:
            print(f"[WARN] 导出Markdown失败: {e}")
            return ""
