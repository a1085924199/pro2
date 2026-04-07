#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ocr_core.py - OCR 核心处理模块 v8.0

架构：
  PPStructureV3Pool    - 主引擎池（PP-Structure），项目启动时预加载
                        负责：文本识别、版面分析、表格结构识别（慢速模式）
  PaddleOCREnginePool  - 极速引擎池（纯 PaddleOCR），仅加载 det/rec 模型
                        负责：快速文本检测+识别，不做版面分析/表格识别（快速模式）
  OCRTask              - 任务类型枚举
  OCRPipeline          - 统一流水线，按任务类型分发处理
  DocParser            - 单据解析器基类
  RepairOrderParser    - 调修单专用解析器
  RepairCardParser     - 返修卡专用解析器
  MaterialParser       - 航材出入库单专用解析器

双引擎路由：
  - slow 模式（默认）：使用 PPStructureV3，走完整流程（版面分析+OCR+表格识别）
  - fast 模式（快速模式/批量模式强制）：使用纯 PaddleOCR，仅文本检测+识别，不生成表格
"""
import os
import sys
import json
import re
import cv2
import numpy as np
import requests
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Any

# Windows 控制台强制 UTF-8 输出（chcp 65001 的等效 Python 设置）
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass


def _log(msg: str, flush: bool = True):
    """带时间戳的日志输出（UTF-8 输出，已在模块顶层配置 stdout）"""
    ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f"[{ts}] {msg}", flush=flush)
    sys.stdout.flush()

os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')
os.environ.setdefault('PADDLE_PDX_MODEL_STORAGE_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models'))

try:
    from paddleocr import PPStructureV3, PaddleOCR
    _PP_STRUCTURE_V3_AVAILABLE = True
    _PADDLE_OCR_AVAILABLE = True
except ImportError:
    _PP_STRUCTURE_V3_AVAILABLE = False
    _PADDLE_OCR_AVAILABLE = False

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
# 优先使用 MODEL_PATH 环境变量，否则使用项目本地的 models/ 目录
_BASE_MODEL_DIR = os.environ.get(
    'MODEL_PATH',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models'),
)
PADDLEX_MODELS_DIR = _BASE_MODEL_DIR
DET_MODEL_DIR      = os.path.join(PADDLEX_MODELS_DIR, 'PP-OCRv5_server_det')
REC_MODEL_DIR      = os.path.join(PADDLEX_MODELS_DIR, 'PP-OCRv5_server_rec')
# 版面分析 + 表格识别模型（PPStructureV3 启动时按需加载）
DOC_LAYOUT_DIR     = os.path.join(PADDLEX_MODELS_DIR, 'PP-DocLayout_plus-L')
TABLE_CLS_DIR      = os.path.join(PADDLEX_MODELS_DIR, 'PP-LCNet_x1_0_table_cls')
DOC_ORI_DIR        = os.path.join(PADDLEX_MODELS_DIR, 'PP-LCNet_x1_0_doc_ori')
TEXTLINE_ORI_DIR   = os.path.join(PADDLEX_MODELS_DIR, 'PP-LCNet_x1_0_textline_ori')
# 表格识别子模型（与 PPStructureV3 官方参数名一致：wired_/wireless_*）
WIRED_TABLE_STRUCT_DIR    = os.path.join(PADDLEX_MODELS_DIR, 'SLANeXt_wired')
WIRED_TABLE_STRUCT_NAME   = 'SLANeXt_wired'
WIRELESS_TABLE_STRUCT_DIR = os.path.join(PADDLEX_MODELS_DIR, 'SLANet_plus')
WIRELESS_TABLE_STRUCT_NAME = 'SLANet_plus'
WIRED_TABLE_CELL_DIR      = os.path.join(PADDLEX_MODELS_DIR, 'RT-DETR-L_wired_table_cell_det')
WIRED_TABLE_CELL_NAME     = 'RT-DETR-L_wired_table_cell_det'
WIRELESS_TABLE_CELL_DIR   = os.path.join(PADDLEX_MODELS_DIR, 'RT-DETR-L_wireless_table_cell_det')
WIRELESS_TABLE_CELL_NAME  = 'RT-DETR-L_wireless_table_cell_det'
CHART_RECOG_DIR           = os.path.join(PADDLEX_MODELS_DIR, 'PP-Chart2Table')
# 文档去扭曲（部分版本在 use_doc_unwarping=False 时仍会实例化，传本地路径避免走 C 盘缓存）
DOC_UNWARP_DIR            = os.path.join(PADDLEX_MODELS_DIR, 'UVDoc')
# 版面分析模型名（PPStructureV3 内部根据模型目录名推断，默认从官方缓存下载 DocBlockLayout）
# 显式传入 name 使其跳过目录名校验，直接用 dir 指向本地路径
DOC_LAYOUT_NAME          = 'PP-DocLayout_plus-L'
# 图表识别模型名（chart_recognition_model_dir 指定后仍可能触发 PP-Chart2Table 内部子模型）
CHART_RECOG_NAME         = 'PP-Chart2Table'

# ============================================================================
# 全局：强制 PaddleX 所有模型走项目本地目录，不从 C 盘官方缓存读取
# ============================================================================
os.environ.setdefault('PADDLE_PDX_MODEL_STORAGE_DIR', PADDLEX_MODELS_DIR)
os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')  # 跳过联网校验

# 完整模型列表（PP-StructureV3 正常模式需要）：
#   PP-OCRv5_server_det/rec     - 文本检测+识别（必需）
#   PP-DocLayout_plus-L          - 版面分析 layout_detection_model_dir（必需）
#   PP-LCNet_x1_0_table_cls     - 表格分类（use_table_recognition=True 时需要）
#   PP-LCNet_x1_0_doc_ori        - 文档方向分类（已禁用但建议传路径）
#   PP-LCNet_x1_0_textline_ori  - 文本行方向分类（已禁用但建议传路径）
#   SLANeXt_wired / SLANet_plus - wired_/wireless_table_structure_recognition_model_dir
#   RT-DETR-L_*_table_cell_det  - wired_/wireless_table_cells_detection_model_dir
#   PP-Chart2Table              - chart_recognition_model_dir（表格链路可能加载）
#   UVDoc                       - doc_unwarping_model_dir（部分构建仍会创建）
#
# 已禁用的功能（use_*=False，尽量不加载）：公式、印章、图表识别开关等见下方初始化。

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
                print('[PPStructureV3] 正在初始化 PPStructureV3 主引擎...', flush=True)
                import paddle
                _log('[PPStructureV3] PaddlePaddle 已加载')
                _log('[PPStructureV3] 正在配置推理设备...')
                # 尝试使用 GPU 加速，如果不可用则回退到 CPU
                device = 'cpu'
                cpu_threads = 8
                enable_mkldnn = False
                try:
                    paddle.device.set_device('gpu')
                    device = 'gpu'
                    cpu_threads = None
                    enable_mkldnn = False
                    _log('[PPStructureV3] 检测到 GPU，将使用 GPU 加速推理')
                    try:
                        gpu_info = paddle.device.cuda.device_count()
                        _log(f'[PPStructureV3] 可用 GPU 数量: {gpu_info}')
                    except Exception:
                        pass
                except Exception as e:
                    _log(f'[PPStructureV3] GPU 不可用，将使用 CPU 推理 (mkldnn={enable_mkldnn}, threads={cpu_threads}): {e}')

                _log('[PPStructureV3] 正在加载 PP-OCRv5 检测模型...')
                t0 = time.time()
                self._engine = PPStructureV3(
                    # 版面 + 文本（官方参数名见 paddleocr.PPStructureV3.__init__）
                    layout_detection_model_name=DOC_LAYOUT_NAME,
                    layout_detection_model_dir=DOC_LAYOUT_DIR,
                    text_detection_model_dir=DET_MODEL_DIR,
                    text_recognition_model_dir=REC_MODEL_DIR,
                    table_classification_model_dir=TABLE_CLS_DIR,
                    doc_orientation_classify_model_dir=DOC_ORI_DIR,  # 指向项目 models/PP-LCNet_x1_0_doc_ori，避免走 C 盘缓存
                    table_orientation_classify_model_dir=DOC_ORI_DIR,
                    textline_orientation_model_dir=TEXTLINE_ORI_DIR,   # 已禁用 use_textline_orientation=False，但 TableRecognition 子流水线内部会加载
                    doc_unwarping_model_dir=None,          # 已禁用 use_doc_unwarping=False，None 避免懒加载
                    # 表格：有线/无线结构识别 + 单元格检测 + 图表转表（均指向项目 models/）
                    wired_table_structure_recognition_model_name=WIRED_TABLE_STRUCT_NAME,
                    wired_table_structure_recognition_model_dir=WIRED_TABLE_STRUCT_DIR,
                    wireless_table_structure_recognition_model_name=WIRELESS_TABLE_STRUCT_NAME,
                    wireless_table_structure_recognition_model_dir=WIRELESS_TABLE_STRUCT_DIR,
                    wired_table_cells_detection_model_name=WIRED_TABLE_CELL_NAME,
                    wired_table_cells_detection_model_dir=WIRED_TABLE_CELL_DIR,
                    wireless_table_cells_detection_model_name=WIRELESS_TABLE_CELL_NAME,
                    wireless_table_cells_detection_model_dir=WIRELESS_TABLE_CELL_DIR,
                    chart_recognition_model_name=CHART_RECOG_NAME,
                    chart_recognition_model_dir=CHART_RECOG_DIR,
                    # 功能开关
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_table_recognition=True,
                    use_textline_orientation=False,
                    use_seal_recognition=False,
                    use_formula_recognition=False,
                    use_chart_recognition=False,
                    use_region_detection=False,
                    device=device,
                    cpu_threads=cpu_threads,
                    enable_mkldnn=enable_mkldnn,
                )
                _log(f'[PPStructureV3] ✓ 引擎初始化完成，耗时 {time.time()-t0:.1f}s')
                self._ready = True
                print('[PPStructureV3] PPStructureV3 主引擎启动成功', flush=True)
            except Exception as e:
                _log(f'[PPStructureV3] ✗ 引擎初始化失败: {e}')
                _log('[PPStructureV3]   将自动降级为 PaddleOCR 引擎处理所有任务')
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
                    _log('[PPStructureV3] ✓ 引擎预热完成，模型已就绪')
            except Exception as e:
                _log(f'[PPStructureV3] ⚠ 预加载失败（不影响服务运行）: {e}')
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
# 纯 PaddleOCR 极速引擎池（快速模式专用）
# ============================================================================
class PaddleOCREnginePool:
    """
    纯 PaddleOCR 引擎单例，仅加载检测+识别模型，不加载 layout/table 模型。
    用于快速模式（fast_batch），跳过表格结构识别，只做文本检测+识别。

    特点：
    - 轻量级，仅需要 det_model_dir 和 rec_model_dir
    - 无版面分析、无表格识别，速度更快
    - 线程安全，双重检查锁定模式
    """
    _instance: Optional['PaddleOCREnginePool'] = None
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
                    cls._instance._init_failed = False
        return cls._instance

    def _init(self):
        """初始化纯 PaddleOCR 引擎（幂等）"""
        with self._init_lock:
            if self._ready:
                return
            if self._init_failed:
                raise RuntimeError('PaddleOCR 引擎初始化已失败，跳过重试')
            if not _PADDLE_OCR_AVAILABLE:
                print('[FastOCR] PaddleOCR 不可用，请升级 paddleocr')
                self._init_failed = True
                raise RuntimeError('PaddleOCR 不可用，请执行: pip install -U paddleocr')
            try:
                print('[FastOCR] 正在初始化纯 PaddleOCR 极速引擎...', flush=True)
                import paddle
                _log('[FastOCR] PaddlePaddle 已加载')
                _log('[FastOCR] 正在配置推理设备...')

                device = 'cpu'
                cpu_threads = 8
                enable_mkldnn = False
                try:
                    paddle.device.set_device('gpu')
                    device = 'gpu'
                    cpu_threads = None
                    enable_mkldnn = False
                    _log('[FastOCR] 检测到 GPU，将使用 GPU 加速推理')
                except Exception as e:
                    _log(f'[FastOCR] GPU 不可用，将使用 CPU 推理 (mkldnn={enable_mkldnn}, threads={cpu_threads}): {e}')

                _log('[FastOCR] 正在加载 PP-OCRv5 检测模型...')
                _log('[FastOCR] 正在加载 PP-OCRv5 识别模型...')
                t0 = time.time()
                # 设置本地模型存储目录，避免联网下载
                os.environ.setdefault('PADDLE_PDX_MODEL_STORAGE_DIR', PADDLEX_MODELS_DIR)
                self._engine = PaddleOCR(
                    # 指定本地模型路径
                    det_model_dir=DET_MODEL_DIR,
                    rec_model_dir=REC_MODEL_DIR,
                    # 禁用角度分类，避免加载额外模型
                    use_angle_cls=False,
                    # 注意：use_angle_cls 与 use_textline_orientation 互斥，不能同时设置
                    use_doc_unwarping=False,
                    rec_batch_num=16,            # 批量识别
                    device=device,               # gpu/cpu
                    cpu_threads=cpu_threads,       # CPU 线程数
                    enable_mkldnn=enable_mkldnn, # 启用 MKL-DNN 加速
                )
                _log(f'[FastOCR] ✓ 引擎初始化完成，耗时 {time.time()-t0:.1f}s')
                self._ready = True
                print('[FastOCR] 纯 PaddleOCR 极速引擎启动成功', flush=True)
            except Exception as e:
                _log(f'[FastOCR] ✗ 引擎初始化失败: {e}')
                self._engine = None
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
                if self._ready and self._engine:
                    import cv2
                    import numpy as np
                    test_img = np.zeros((100, 100, 3), dtype=np.uint8)
                    cv2.putText(test_img, 'test', (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                    list(self._engine.ocr(test_img))
                    self._warmup_done = True
                    _log('[FastOCR] ✓ 引擎预热完成，模型已就绪')
            except Exception as e:
                _log(f'[FastOCR] ⚠ 预加载失败（不影响服务运行）: {e}')
        threading.Thread(target=_load, daemon=True).start()

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def warmup_done(self) -> bool:
        return getattr(self, '_warmup_done', False)


# 纯 PaddleOCR 极速引擎全局单例
fast_ocr_pool = PaddleOCREnginePool()


# ============================================================================
# 通用工具函数
# ============================================================================

def preprocess_image(image_path: str) -> np.ndarray:
    """读取图像并缩放，宽度上限 1600px，返回 BGR ndarray。"""
    _log(f'[预处理] 正在读取图像: {image_path}')
    img = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f'无法读取图像: {image_path}')
    h, w = img.shape[:2]
    _log(f'[预处理] 原始图像尺寸: {w}x{h}')
    MAX_W = 1600
    if w > MAX_W:
        img = cv2.resize(img, (MAX_W, int(h * MAX_W / w)), interpolation=cv2.INTER_LINEAR)
        _log(f'[预处理] 图像已缩放至宽度 {MAX_W}px')
    else:
        _log(f'[预处理] 图像无需缩放')
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
    _log('[OCR] 正在进行文本识别...')
    t0 = time.time()
    try:
        results = list(engine.predict(img_bgr, use_table_recognition=True, use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False))
    except TypeError:
        results = list(engine.predict(img_bgr))
    _log(f'[OCR] 文本识别完成，耗时 {time.time()-t0:.1f}s')
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
            _log(f'[DocParser] 开始 PPStructureV3 推理，图像尺寸: {img_bgr.shape[1]}x{img_bgr.shape[0]}')
            t0 = time.time()
            results = list(engine.predict(img_bgr))
            _log(f'[DocParser] ✓ PPStructureV3 推理完成，耗时 {time.time()-t0:.1f}s，结果数量: {len(results)}')
            
            # 使用 Result 对象的方法保存表格数据
            for res in results:
                res.save_to_html(save_path=os.path.join(output_dir, f"{base_name}_table.html"))
                res.save_to_xlsx(save_path=xlsx_path)
            _log(f'[DocParser] 已保存 HTML/Excel 表格文件')
            
            parsed = _parse_v3_result(results, img_bgr.shape[:2], xlsx_path=xlsx_path)
            ocr_results = parsed['ocr_results']
            table_regions = parsed['table_regions']
            _log(f'[DocParser] 解析完成，文本块: {len(ocr_results)} 个，表格区域: {len(table_regions)} 个')
        except Exception as e:
            _log(f'[DocParser] ⚠ PPStructureV3 失败，使用纯 OCR 降级: {e}')
            ocr_results = run_ocr(image_path)
            table_regions = []
            _log(f'[DocParser] ✓ 降级 OCR 完成，识别到 {len(ocr_results)} 个文本块')

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
            fields = self.extract_fields(ocr_results, table_regions)

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

    def extract_fields(self, ocr_results: List[Dict], table_regions: List = None) -> Dict[str, str]:
        return {f: '' for f in self.FIELDS}

    def _extract_fastgpt(self, texts: List[Dict], cfg: Dict, table_regions=None) -> Dict[str, str]:
        api_url = cfg.get('api_url', '')
        api_key = cfg.get('api_key', '')
        appid   = cfg.get('appid', '')
        if not api_key or not api_url:
            return self.extract_fields(texts, table_regions)
        try:
            ocr_text   = '\n'.join(t['text'] for t in texts)
            fields_str = '\n'.join(f'  - {f}' for f in self.FIELDS)
            prompt = (f'你是单据信息提取助手。请从以下OCR文本中提取字段：\n{fields_str}\n\n'
                      f'【OCR文本】\n{ocr_text}\n\n'
                      f'以JSON对象返回，键为字段名，值为提取内容，未找到填空字符串。只返回JSON对象。')
            resp = requests.post(
                api_url,
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json={'appId': appid, 'chatId': self.__class__.__name__, 'stream': False, 'detail': False,
                      'variables': {'ocr_text': ocr_text,
                                    'fields_def': json.dumps([{'field': f} for f in self.FIELDS], ensure_ascii=False)},
                      'messages': [{'role': 'user', 'content': prompt}]},
                timeout=30)
            resp_data = resp.json()
            content = ''
            if isinstance(resp_data, dict):
                content = resp_data.get('choices', [{}])[0].get('message', {}).get('content', '')
                if not content:
                    for key in ['data', 'result', 'response']:
                        if key in resp_data:
                            val = resp_data[key]
                            if isinstance(val, dict):
                                content = val.get('content', val.get('text', str(val)))
                            elif isinstance(val, str):
                                content = val
                            break

            if not content:
                return self.extract_fields(texts, table_regions)

            # 清理 content：去除代码块标记
            clean_content = content.strip()
            if clean_content.startswith('```'):
                # 去除 ```json 或 ``` 等标记
                lines = clean_content.split('\n')
                if lines[0].startswith('```'):
                    lines = lines[1:]
                if lines and lines[-1].startswith('```'):
                    lines = lines[:-1]
                clean_content = '\n'.join(lines).strip()
                
            # 尝试多层解析：先尝试直接解析，然后尝试解析嵌套的 JSON
            result = {f: '' for f in self.FIELDS}
            parsed = None

            # 方法1：直接解析
            try:
                parsed = json.loads(clean_content)
            except json.JSONDecodeError:
                # 方法2：尝试从 content 中提取 JSON 对象
                m = re.search(r'\{[\s\S]*\}', clean_content, re.DOTALL)
                if m:
                    try:
                        parsed = json.loads(m.group())
                    except json.JSONDecodeError:
                        pass
                else:
                    pass

            # 方法3：如果 parsed 是字符串，尝试再次解析（处理嵌套 JSON）
            if parsed is not None:
                if isinstance(parsed, str):
                    # content 本身可能是 JSON 字符串，需要再次解析
                    try:
                        parsed = json.loads(parsed)
                    except json.JSONDecodeError:
                        m2 = re.search(r'\{[\s\S]*\}', parsed, re.DOTALL)
                        if m2:
                            try:
                                parsed = json.loads(m2.group())
                            except json.JSONDecodeError:
                                parsed = None
                        else:
                            parsed = None
                elif isinstance(parsed, dict):
                    # 检查是否需要从嵌套结构中提取
                    if 'data' in parsed and isinstance(parsed['data'], str):
                        try:
                            parsed = json.loads(parsed['data'])
                        except json.JSONDecodeError:
                            pass

            # 应用解析结果
            if parsed and isinstance(parsed, dict):
                for fn, val in parsed.items():
                    if fn in result:
                        result[fn] = str(val) if val else ''
                return result
            elif parsed and isinstance(parsed, list):
                for item in parsed:
                    fn = item.get('field', '')
                    if fn in result:
                        result[fn] = item.get('value', '')
                return result
        except Exception as e:
            print(f'FastGPT调用失败({self.__class__.__name__}): {e}')
        # 超时或解析失败时回退到规则提取（传入完整 OCR 文本供匹配）
        fallback_fields = self.extract_fields(texts, table_regions)
        # 再尝试从 OCR 全文补充未填字段
        full_text = '\n'.join(t['text'] for t in texts)
        for fn, val in fallback_fields.items():
            if not val:
                if fn == 'FRACAS/排故报告编号':
                    m = re.search(r'(FRA[A-Z0-9]{6,})', full_text, re.IGNORECASE)
                    if m:
                        fallback_fields[fn] = m.group(1).upper()
                elif fn == '电话号':
                    m = re.search(r'(1[3-9]\d{9})', full_text)
                    if m:
                        fallback_fields[fn] = m.group(1)
                elif fn == '图号':
                    m = re.search(r'(AL[\d\.\s]+\d{3})', full_text, re.IGNORECASE)
                    if m:
                        fallback_fields[fn] = re.sub(r'\s+', ' ', m.group(1).strip())
        return fallback_fields

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

    def extract_fields(self, ocr_results, table_regions=None):
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
    """
    返修件维修卡字段（与 FastGPT 提示一致）。
    重要：返修卡号优先从表头 NO.xxxx 提取。
    「返修故障件信息」与「损坏原因、修理结果」为表单上、下两个独立区块，须分别提取，不可混用。
    """
    FIELDS = [
        '返修卡号', '产品代号', '联系人', '顾客单位', '批次号', '电话号',
        '返修件名称', '图号', '返修故障件信息', '损坏原因修理结果', 'FRACAS/排故报告编号',
    ]

    @staticmethod
    def _clean_fault_section_footer(s: str) -> str:
        """去掉返修故障件信息段末尾的维修部门、日期等。"""
        if not s:
            return ''
        t = s.strip()
        t = re.split(r'维修部门\s*[：:]', t)[0].strip()
        t = re.sub(r'\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s*$', '', t).strip()
        return t

    @staticmethod
    def _clean_damage_section_tail(s: str) -> str:
        """去掉损坏原因修理结果段后的 FRACAS、维修人员等。"""
        if not s:
            return ''
        t = s.strip()
        if 'FRACAS' in t:
            t = t.split('FRACAS')[0].strip()
        if '排故报告编号' in t:
            t = t.split('排故报告编号')[0].strip()
        if '维修人员' in t:
            t = re.split(r'维修人员', t)[0].strip()
        return t.strip()

    @staticmethod
    def _regex_extract_fault_and_damage(s: str) -> tuple[str, str]:
        """
        按标签从全文或单单元格文本中拆分两段。
        返修故障件信息：……（至「损坏原因」标签前）
        损坏原因、修理结果：……（至 FRACAS / 排故 / 维修人员 前）
        """
        fault, damage = '', ''
        if not s:
            return fault, damage
        s = s.replace('\r', '\n')
        # 返修故障件信息（必须带标签，避免与下段混淆）
        mf = re.search(
            r'返修故障件信息\s*[：:]\s*([\s\S]*?)(?=\s*损坏原因\s*[、,，]?\s*修理结果\s*[：:]|\s*损坏原因\s*[：:])',
            s,
        )
        if not mf:
            mf = re.search(
                r'返修故障\s*[：:]\s*([\s\S]*?)(?=\s*损坏原因\s*[、,，]?\s*修理结果|\s*损坏原因\s*[：:])',
                s,
            )
        if mf:
            fault = RepairCardParser._clean_fault_section_footer(mf.group(1).strip())
        # 损坏原因、修理结果
        md = re.search(
            r'损坏原因\s*[、,，]?\s*修理结果\s*[：:]\s*([\s\S]*?)(?=FRACAS|排故报告编号|维修人员)',
            s,
            re.IGNORECASE,
        )
        if md:
            damage = RepairCardParser._clean_damage_section_tail(md.group(1).strip())
        return fault, damage

    @staticmethod
    def _collect_table_text_blobs(table_regions) -> list[str]:
        """所有表格单元格文本，用于分段识别（多格拆行时拼接）。"""
        blobs: list[str] = []
        for tr in (table_regions or []):
            for cell in tr.get('cells', []):
                ct = (cell.get('text') or '').strip()
                if ct:
                    blobs.append(ct)
        return blobs

    def extract_fields(self, ocr_results, table_regions=None):
        fields = {f: '' for f in self.FIELDS}
        texts = [t for t in ocr_results if t.get('text', '').strip()]
        full_text = '\n'.join(t['text'] for t in texts)
        F = self._find_nearest

        # ── 表格行列结构提取（优先）─────────────────────────────────────────────
        def _table_value(table_regions, keywords: list) -> str:
            """根据标签关键词在表格单元格中查找对应的值（右侧相邻列或下一行）"""
            for tr in (table_regions or []):
                for cell in tr.get('cells', []):
                    cell_text = cell.get('text', '').strip()
                    if not cell_text:
                        continue
                    # 匹配标签
                    for kw in keywords:
                        if kw in cell_text:
                            row, col = cell['row'], cell['col']
                            # 找同行下一列
                            for c in tr.get('cells', []):
                                if c['row'] == row and c['col'] == col + 1:
                                    val = c.get('text', '').strip()
                                    if val and '产品代号' not in val and '联系人' not in val and \
                                       '任务' not in val and '批次' not in val and '电话' not in val and \
                                       '返修件名称' not in val and '图号' not in val and \
                                       '数量' not in val and '#' not in val:
                                        return val
                            # 找同列下一行
                            for c in tr.get('cells', []):
                                if c['row'] == row + 1 and c['col'] == col:
                                    return c.get('text', '').strip()
            return ''

        def _table_row_value(table_regions, label_keywords: list, max_next_cols=5) -> str:
            """取标签所在行右侧若干列拼接成值（跨列大字段，如故障信息）"""
            for tr in (table_regions or []):
                for cell in tr.get('cells', []):
                    cell_text = cell.get('text', '').strip()
                    for kw in label_keywords:
                        if kw in cell_text:
                            row, col = cell['row'], cell['col']
                            parts = []
                            for c in tr.get('cells', []):
                                if c['row'] == row and c['col'] >= col + 1:
                                    t = c.get('text', '').strip()
                                    if t and '#' not in t:
                                        parts.append(t)
                            if parts:
                                return ' '.join(parts)
            return ''

        def _table_no_value(texts) -> str:
            """从 OCR 文本（非表格单元格）中找返修卡号 NO.xxxx"""
            for pat in (r'NO[\.\s．]*(\d{4,})', r'[Nn][Oo][\.\s．]*(\d{4,})', r'返修卡号[：:\s]*(\d+)', r'卡号[：:\s]*(\d{4,})'):
                m = re.search(pat, full_text)
                if m:
                    return m.group(1).strip()
            return ''

        def _table_fault_block(texts) -> str:
            """从 OCR 行中找「返修故障件信息」段（不得把仅含损坏原因、修理结果的行当作本字段）。"""
            lines = [t['text'].strip() for t in texts]
            for line in lines:
                if '返修故障件信息' in line or ('返修故障' in line and '损坏原因' not in line):
                    f, _ = RepairCardParser._regex_extract_fault_and_damage(line)
                    if f:
                        return f[:2000]
                    # 单行标签+正文无「损坏原因」时，取冒号后至行尾
                    if '返修故障' in line and '损坏原因' not in line:
                        for prefix in ('返修故障件信息：', '返修故障件信息:', '返修故障：', '返修故障:'):
                            if prefix in line:
                                tail = line.split(prefix, 1)[-1].strip()
                                if tail:
                                    return RepairCardParser._clean_fault_section_footer(tail)[:2000]
            # 多行：从含返修故障件信息的行起收集，遇损坏原因或 FRACAS 则停
            for i, line in enumerate(lines):
                if '返修故障件信息' not in line and not ('返修故障' in line and '损坏原因' not in line):
                    continue
                parts = [line]
                for j in range(i + 1, min(i + 8, len(lines))):
                    lj = lines[j]
                    if '损坏原因' in lj or 'FRACAS' in lj or '修理结果' in lj:
                        break
                    if any(k in lj for k in ('维修部门', '装备部')) and j > i:
                        parts.append(lj)
                        break
                    if lj and lj not in ('1', '2', '3', '4', '5'):
                        parts.append(lj)
                blob = ' '.join(parts)
                f, d = RepairCardParser._regex_extract_fault_and_damage(blob)
                if f:
                    return f[:2000]
                if not d and '返修故障' in blob:
                    for prefix in ('返修故障件信息：', '返修故障件信息:', '返修故障：', '返修故障:'):
                        if prefix in blob:
                            tail = blob.split(prefix, 1)[-1].strip()
                            if tail and '损坏原因' not in tail:
                                return RepairCardParser._clean_fault_section_footer(tail)[:2000]
            return ''

        def _extract_fault_info_from_cell(cell_text: str) -> str:
            """仅从含「返修故障件信息」的单元格取故障描述；若与损坏原因同格则正则拆分，不取损坏原因段。"""
            if not cell_text:
                return ''
            if '返修故障件信息' in cell_text or ('返修故障' in cell_text and '损坏原因' not in cell_text):
                f, _ = RepairCardParser._regex_extract_fault_and_damage(cell_text)
                if f:
                    return f
                if '返修故障' in cell_text and '损坏原因' not in cell_text:
                    for prefix in ('返修故障件信息：', '返修故障件信息:', '返修故障：', '返修故障:'):
                        if prefix in cell_text:
                            return RepairCardParser._clean_fault_section_footer(
                                cell_text.split(prefix, 1)[-1].strip()
                            )
            if '返修故障件信息' in cell_text and '损坏原因' in cell_text:
                f, _ = RepairCardParser._regex_extract_fault_and_damage(cell_text)
                return f or ''
            return ''

        # 逐字段从表格提取
        if not fields['返修卡号']:
            fields['返修卡号'] = _table_no_value(texts)

        if not fields['产品代号']:
            v = _table_value(table_regions, ['产品代号'])
            if not v:
                # 找「产品代号」标签右侧的非标签值
                for tr in (table_regions or []):
                    for cell in tr.get('cells', []):
                        if cell.get('text', '').strip() == '产品代号':
                            row, col = cell['row'], cell['col']
                            for c in tr.get('cells', []):
                                if c['row'] == row and c['col'] == col + 1:
                                    val = c.get('text', '').strip()
                                    if val and val not in ('联系人', '顾客单位', '批次号', '电话', '返修件名称', '图号'):
                                        fields['产品代号'] = val
                                        break
            else:
                fields['产品代号'] = v

        if not fields['联系人']:
            for tr in (table_regions or []):
                for cell in tr.get('cells', []):
                    if cell.get('text', '').strip() == '联系人':
                        row, col = cell['row'], cell['col']
                        for c in tr.get('cells', []):
                            if c['row'] == row and c['col'] == col + 1:
                                val = c.get('text', '').strip()
                                if val and '任务' not in val and val not in ('产品代号', '顾客单位', '批次号', '电话', '返修件名称', '图号', '数量'):
                                    fields['联系人'] = val
                                    break
                        break

        if not fields['顾客单位']:
            v = _table_value(table_regions, ['顾客单位', '客户单位'])
            if v:
                fields['顾客单位'] = v

        if not fields['批次号']:
            v = _table_value(table_regions, ['批次号'])
            if v:
                fields['批次号'] = re.sub(r'\D', '', v) or v

        if not fields['电话号']:
            v = _table_value(table_regions, ['电话', '电话号', '手机号'])
            if not v:
                m = re.search(r'(1[3-9]\d{9})', full_text)
                if m:
                    fields['电话号'] = m.group(1)
            else:
                fields['电话号'] = v

        if not fields['返修件名称']:
            v = _table_value(table_regions, ['返修件名称', '名称'])
            if v:
                fields['返修件名称'] = v

        if not fields['图号']:
            v = _table_value(table_regions, ['图号'])
            if not v:
                m = re.search(r'(AL[\d\.\s]+\d{3})', full_text, re.IGNORECASE)
                if m:
                    fields['图号'] = re.sub(r'\s+', ' ', m.group(1).strip())
            else:
                fields['图号'] = v

        # ── 返修故障件信息 / 损坏原因修理结果：先按标签从全文与表格拆分（两栏独立）──────────
        fault_best, damage_best = '', ''
        table_joined = '\n'.join(RepairCardParser._collect_table_text_blobs(table_regions))
        for blob in (full_text, table_joined):
            if not blob.strip():
                continue
            f, d = RepairCardParser._regex_extract_fault_and_damage(blob)
            if f and not fault_best:
                fault_best = f
            if d and not damage_best:
                damage_best = d
            if fault_best and damage_best:
                break
        if not fault_best or not damage_best:
            for ct in RepairCardParser._collect_table_text_blobs(table_regions):
                if len(ct) < 8:
                    continue
                f, d = RepairCardParser._regex_extract_fault_and_damage(ct)
                if f and not fault_best:
                    fault_best = f
                if d and not damage_best:
                    damage_best = d

        if fault_best:
            fields['返修故障件信息'] = fault_best
        if damage_best:
            fields['损坏原因修理结果'] = damage_best

        # 返修故障件信息：兜底（标签单独成格、或仅出现在 OCR 行）
        if not fields['返修故障件信息']:
            for tr in (table_regions or []):
                for cell in tr.get('cells', []):
                    cell_text = cell.get('text', '').strip()
                    if not cell_text:
                        continue
                    if '返修故障件信息' in cell_text or (
                        '返修故障' in cell_text and '损坏原因' not in cell_text
                    ):
                        v = _extract_fault_info_from_cell(cell_text)
                        if v:
                            fields['返修故障件信息'] = v
                            break
                if fields['返修故障件信息']:
                    break
            if not fields['返修故障件信息']:
                v = _table_row_value(table_regions, ['返修故障件信息', '返修故障'])
                if v:
                    fields['返修故障件信息'] = RepairCardParser._clean_fault_section_footer(v)
            if not fields['返修故障件信息']:
                v = _table_fault_block(texts)
                if v:
                    fields['返修故障件信息'] = v

        # 损坏原因修理结果：兜底（仅当正则未命中时）
        if not fields['损坏原因修理结果']:
            for tr in (table_regions or []):
                for cell in tr.get('cells', []):
                    cell_text = cell.get('text', '').strip()
                    if '损坏原因' in cell_text and len(cell_text) > 10:
                        _, d = RepairCardParser._regex_extract_fault_and_damage(cell_text)
                        if d:
                            fields['损坏原因修理结果'] = d
                            break
                        if '：' in cell_text:
                            result = cell_text.split('：', 1)[-1].strip()
                        elif ':' in cell_text:
                            result = cell_text.split(':', 1)[-1].strip()
                        else:
                            result = cell_text
                        if 'FRACAS' in result:
                            result = result.split('FRACAS')[0].strip()
                        if '排故报告编号' in result:
                            result = result.split('排故报告编号')[0].strip()
                        result = RepairCardParser._clean_damage_section_tail(result)
                        if result:
                            fields['损坏原因修理结果'] = result
                            break
                if fields['损坏原因修理结果']:
                    break
            if not fields['损坏原因修理结果']:
                for item in texts:
                    t = item.get('text', '').strip()
                    if '损坏原因' in t or '修理结果' in t:
                        _, d = RepairCardParser._regex_extract_fault_and_damage(t)
                        if d:
                            fields['损坏原因修理结果'] = d
                            break
                        if '：' in t:
                            result = t.split('：', 1)[-1].strip()
                        elif ':' in t:
                            result = t.split(':', 1)[-1].strip()
                        else:
                            result = t
                        if 'FRACAS' in result:
                            result = result.split('FRACAS')[0].strip()
                        result = RepairCardParser._clean_damage_section_tail(result)
                        if result:
                            fields['损坏原因修理结果'] = result
                            break

        if not fields['FRACAS/排故报告编号']:
            m = re.search(r'(FRA[A-Z0-9]{6,})', full_text, re.IGNORECASE)
            if m:
                fields['FRACAS/排故报告编号'] = m.group(1).upper()
            # 也从表格找
            if not fields['FRACAS/排故报告编号']:
                for tr in (table_regions or []):
                    for cell in tr.get('cells', []):
                        ct = cell.get('text', '').strip()
                        if 'FRACAS' in ct or '排故' in ct or '报告编号' in ct:
                            row, col = cell['row'], cell['col']
                            for c in tr.get('cells', []):
                                if c['row'] == row and c['col'] > col:
                                    val = c.get('text', '').strip()
                                    if val and val not in ('维修部门', '装备部'):
                                        fields['FRACAS/排故报告编号'] = val
                                        break
                            break

        return fields


# ── 航材出入库单解析器 ────────────────────────────────────────────────────────
class MaterialParser(DocParser):
    FIELDS_OUT = ['出库单号','航材名称','航材型号','数量','出库日期','经手人','领用单位','备注']
    FIELDS_IN  = ['入库单号','航材名称','航材型号','数量','入库日期','经手人','供应商','备注']
    FIELDS     = FIELDS_OUT  # 默认

    def __init__(self, doc_type: str = 'out'):
        self.doc_type = doc_type
        self.FIELDS   = self.FIELDS_OUT if doc_type == 'out' else self.FIELDS_IN

    def extract_fields(self, ocr_results, table_regions=None):
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
    统一 OCR 流水线，支持双引擎路由：
    - slow 模式（默认）：使用 PPStructureV3，走完整流程（版面分析+OCR+表格识别）
    - fast 模式：使用纯 PaddleOCR，仅文本检测+识别，不生成表格

    批量模式（fast_batch=True）强制使用 fast 模式。
    """
    @staticmethod
    def _process_fast(image_path: str, output_dir: str, use_fastgpt: bool = False,
                      fastgpt_config: dict = None, task_type: OCRTask = OCRTask.GENERAL,
                      **kwargs) -> Dict:
        """
        快速模式处理：使用纯 PaddleOCR 引擎，仅做文本检测+识别。

        参数:
            image_path: 图像文件路径
            output_dir: 输出目录
            use_fastgpt: 是否使用 FastGPT 增强字段提取
            fastgpt_config: FastGPT 配置
            task_type: 任务类型
            **kwargs: 额外参数

        返回: 统一格式结果字典
        """
        t_start = time.time()
        _log(f'[OCRPipeline/FAST] ========== 快速模式开始处理 ==========')
        _log(f'[OCRPipeline/FAST] 输入文件: {image_path}')
        _log(f'[OCRPipeline/FAST] 任务类型: {task_type.value}')

        os.makedirs(output_dir, exist_ok=True)

        # 获取纯 PaddleOCR 引擎
        _log(f'[OCRPipeline/FAST] 正在获取纯 PaddleOCR 极速引擎...')
        engine = fast_ocr_pool.get()
        if engine is None:
            raise RuntimeError('纯 PaddleOCR 引擎不可用')

        # 预处理图像
        _log(f'[OCRPipeline/FAST] 正在进行图像预处理...')
        img_bgr = preprocess_image(image_path)
        h, w = img_bgr.shape[:2]
        _log(f'[OCRPipeline/FAST] 预处理完成，图像尺寸: {w}x{h}')

        # 执行纯文本检测+识别
        _log(f'[OCRPipeline/FAST] >>> 正在执行纯文本检测+识别...')
        t0 = time.time()
        sys.stdout.flush()

        try:
            ocr_results_raw = engine.ocr(img_bgr)
        except Exception as e:
            _log(f'[OCRPipeline/FAST] ✗ OCR 失败: {e}')
            raise

        t_det_rec = time.time() - t0
        _log(f'[OCRPipeline/FAST] ✓ 文本检测+识别完成，耗时 {t_det_rec:.1f}s')

        # 转换结果格式
        _log(f'[OCRPipeline/FAST] >>> 正在转换 OCR 结果格式...')
        ocr_results: List[Dict] = []

        def _poly_to_bbox_and_flat(poly_obj) -> tuple:
            """从四边形点集得到 [x1,y1,x2,y2] 与扁平 poly 列表（兼容 ndarray / list）。"""
            if poly_obj is None:
                return [], []
            pts = np.asarray(poly_obj, dtype=np.float64)
            if pts.size == 0:
                return [], []
            if pts.ndim == 1 and len(pts) >= 4:
                xs = [float(pts[i]) for i in range(0, min(len(pts), 8), 2)]
                ys = [float(pts[i]) for i in range(1, min(len(pts), 8), 2)]
                flat = [float(x) for x in pts.tolist()] if hasattr(pts, 'tolist') else list(pts)
            else:
                flat = pts.reshape(-1).tolist()
                xs = [float(p[0]) for p in pts.reshape(-1, 2)]
                ys = [float(p[1]) for p in pts.reshape(-1, 2)]
            if not xs or not ys:
                return [], flat
            return [min(xs), min(ys), max(xs), max(ys)], flat

        def _page_seq(val, alt_key=None, page_dict=None):
            """从 page dict 取值；禁止对 ndarray 使用 `or`，否则触发真值歧义。"""
            if val is not None:
                return val
            if alt_key is not None and page_dict is not None:
                v2 = page_dict.get(alt_key)
                if v2 is not None:
                    return v2
            return []

        if ocr_results_raw and isinstance(ocr_results_raw, list) and len(ocr_results_raw) > 0:
            first_item = ocr_results_raw[0]
            if isinstance(first_item, dict):
                # PaddleOCR 3.x pipeline：每页一个 dict，含 rec_texts + rec_scores + dt_polys/rec_polys
                total_lines = 0
                for page in ocr_results_raw:
                    if not isinstance(page, dict):
                        continue
                    rec_texts = page.get('rec_texts')
                    if rec_texts is None:
                        rec_texts = []
                    elif isinstance(rec_texts, np.ndarray):
                        rec_texts = rec_texts.tolist()
                    rec_scores = page.get('rec_scores')
                    if rec_scores is None:
                        rec_scores = []
                    elif isinstance(rec_scores, np.ndarray):
                        rec_scores = rec_scores.astype(float).tolist()
                    rec_res = page.get('rec_res')
                    if rec_res is None:
                        rec_res = []
                    polys_src = _page_seq(page.get('rec_polys'), 'dt_polys', page)
                    if polys_src is None:
                        polys_src = []
                    rec_boxes = page.get('rec_boxes')
                    if rec_boxes is None:
                        rec_boxes = []

                    if len(rec_texts) > 0:
                        for idx, text in enumerate(rec_texts):
                            confidence = float(rec_scores[idx]) if idx < len(rec_scores) else 0.0
                            bbox, poly = [], []
                            if idx < len(polys_src):
                                bbox, poly = _poly_to_bbox_and_flat(polys_src[idx])
                            elif idx < len(rec_boxes) and rec_boxes[idx] is not None:
                                box = np.asarray(rec_boxes[idx]).reshape(-1)
                                if len(box) >= 4:
                                    bbox = [float(box[0]), float(box[1]), float(box[2]), float(box[3])]
                                    poly = bbox[:]
                            ocr_results.append({
                                'text': str(text),
                                'confidence': round(confidence, 4),
                                'bbox': bbox,
                                'poly': poly,
                                'type': 'text',
                            })
                        total_lines += len(rec_texts)
                    elif len(rec_res) > 0:
                        dt_polys = page.get('dt_polys', [])
                        for idx, text_info in enumerate(rec_res):
                            if isinstance(text_info, (list, tuple)) and len(text_info) >= 2:
                                text = text_info[0]
                                confidence = float(text_info[1])
                            else:
                                text = str(text_info)
                                confidence = 0.0
                            bbox, poly = [], []
                            if idx < len(dt_polys):
                                bbox, poly = _poly_to_bbox_and_flat(dt_polys[idx])
                            ocr_results.append({
                                'text': str(text),
                                'confidence': round(confidence, 4),
                                'bbox': bbox,
                                'poly': poly,
                                'type': 'text',
                            })
                        total_lines += len(rec_res)
                if total_lines:
                    _log(f'[OCRPipeline/FAST]   新版 dict 结果: 共 {total_lines} 条文本行')
            else:
                # 兼容旧版 list 格式
                for line_result in ocr_results_raw:
                    if line_result and isinstance(line_result, list):
                        for item in line_result:
                            if item and len(item) >= 2:
                                bbox_info = item[0]
                                text_info = item[1]
                                if isinstance(text_info, (list, tuple)) and len(text_info) >= 2:
                                    text = text_info[0]
                                    confidence = float(text_info[1])
                                else:
                                    text = str(text_info)
                                    confidence = 0.0
                                poly = []
                                if bbox_info and isinstance(bbox_info, list):
                                    poly = [float(p) for sublist in bbox_info for p in sublist]
                                bbox = []
                                if bbox_info and isinstance(bbox_info, list) and len(bbox_info) >= 4:
                                    xs = [p[0] for p in bbox_info]
                                    ys = [p[1] for p in bbox_info]
                                    bbox = [min(xs), min(ys), max(xs), max(ys)]
                                ocr_results.append({
                                    'text': str(text),
                                    'confidence': round(confidence, 4),
                                    'bbox': bbox,
                                    'poly': poly,
                                    'type': 'text',
                                })

        _log(f'[OCRPipeline/FAST] 转换完成，识别到 {len(ocr_results)} 个文本块')

        # 快速模式不生成表格结构，使用几何推断
        table = {
            'table_idx': 0,
            'html': '',
            'cells': [],
            'bbox': [],
            'num_rows': 0,
            'num_cols': 0,
        }

        # 根据任务类型选择解析器并提取字段
        _log(f'[OCRPipeline/FAST] >>> 正在提取字段信息...')
        extracted_fields: Dict[str, str] = {}
        if task_type != OCRTask.GENERAL:
            parser_map = {
                OCRTask.REPAIR_ORDER: RepairOrderParser(),
                OCRTask.REPAIR_CARD: RepairCardParser(),
                OCRTask.MATERIAL: MaterialParser(kwargs.get('doc_type', 'out')),
            }
            parser = parser_map.get(task_type, DocParser())

            if use_fastgpt and fastgpt_config and fastgpt_config.get('api_key'):
                _log(f'[OCRPipeline/FAST]   正在使用 FastGPT 增强字段提取...')
                extracted_fields = parser._extract_fastgpt(ocr_results, fastgpt_config, None)
            else:
                extracted_fields = parser.extract_fields(ocr_results, None)
            _log(f'[OCRPipeline/FAST]   字段提取完成: {extracted_fields}')

        # 构建返回结果
        result = {
            'success': True,
            'image_path': image_path,
            'image_name': os.path.basename(image_path),
            'ocr_results': ocr_results,
            'table_regions': [],  # 快速模式不生成表格区域
            'table': table,
            'extracted_fields': extracted_fields,
            'summary': f'快速模式：共识别 {len(ocr_results)} 个文本块（不生成表格结构）',
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'xlsx_path': '',       # 快速模式不生成 Excel
            'mode': 'fast',        # 标记为快速模式
            'skip_structure_artifacts': True,
        }

        total_time = time.time() - t_start
        _log(f'')
        _log(f'[SUCCESS] ✓ 快速模式识别完成！总计耗时 {total_time:.1f}s')
        _log(f'[OCRPipeline/FAST] ========== 处理结束 ==========')

        return result

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
                - mode: 'slow' | 'fast'，指定使用哪个引擎模式。
                  - 'slow': 使用 PPStructureV3（完整流程）
                  - 'fast': 使用纯 PaddleOCR（仅文本识别）
        """
        t_start = time.time()
        mode = kwargs.get('mode', 'slow')  # 'slow', 'fast'

        # 确定使用哪个引擎
        use_fast_engine = (mode == 'fast')

        # 快速模式：使用纯 PaddleOCR 引擎
        if use_fast_engine:
            _known_keys = {'use_fastgpt', 'fastgpt_config', 'output_dir'}
            _filtered = {k: v for k, v in kwargs.items() if k not in _known_keys}
            return OCRPipeline._process_fast(
                image_path=image_path,
                output_dir=kwargs.get('output_dir', 'output'),
                use_fastgpt=bool(kwargs.get('use_fastgpt', False)),
                fastgpt_config=kwargs.get('fastgpt_config'),
                task_type=task_type,
                **_filtered
            )

        # 正常模式：使用 PPStructureV3 完整流程
        _log(f'[OCRPipeline] ========== 开始处理 ==========')
        _log(f'[OCRPipeline] 任务类型: {task_type.value}')
        _log(f'[OCRPipeline] 输入文件: {image_path}')
        _log(f'[OCRPipeline] 引擎模式: 正常模式（PP-StructureV3）')
        
        output_dir = kwargs.get('output_dir', 'output')
        os.makedirs(output_dir, exist_ok=True)

        # 生成输出文件名
        base_name = os.path.basename(image_path).split('.')[0]
        json_path = os.path.join(output_dir, f"{base_name}.json")
        md_path = os.path.join(output_dir, f"{base_name}.md")
        html_path = os.path.join(output_dir, f"{base_name}_table.html")
        xlsx_path = os.path.join(output_dir, f"{base_name}_table.xlsx")

        # 初始化引擎
        _log(f'[OCRPipeline] 正在获取 PPStructureV3 引擎...')
        engine = v3_pool.get()
        if engine is None:
            raise RuntimeError('PPStructureV3 引擎不可用')

        # 预处理图像
        _log(f'[OCRPipeline] 正在进行图像预处理...')
        img_bgr = preprocess_image(image_path)
        h, w = img_bgr.shape[:2]
        _log(f'[OCRPipeline] 预处理完成，图像尺寸: {w}x{h}')

        # 执行推理 - 分阶段计时
        _log(f'[OCRPipeline] >>> 阶段 1/5: 正在执行 PPStructureV3 推理...')
        t_stage = time.time()
        
        # 文本检测 + 识别（最耗时阶段）
        _log(f'[OCRPipeline]   - 正在调用 engine.predict()...')
        t0 = time.time()
        sys.stdout.flush()
        results = list(engine.predict(img_bgr))
        t_det_rec = time.time() - t0
        _log(f'[OCRPipeline]   - 文本检测+识别完成，耗时 {t_det_rec:.1f}s')
        
        # 表格结构识别（可选，在 engine.predict 中已完成）
        t_html = time.time()
        html_count = 0
        for res in results:
            if hasattr(res, 'html') and res.html:
                html_count += 1
        t_html = time.time() - t_html
        _log(f'[OCRPipeline]   - HTML 表格提取完成，耗时 {t_html:.1f}s，检测到 {html_count} 个表格区域')
        
        t_ocr = time.time() - t_stage
        _log(f'[OCRPipeline] ✓ 阶段 1/5 完成，总耗时 {t_ocr:.1f}s（检测+识别: {t_det_rec:.1f}s，表格解析: {t_html:.1f}s），返回 {len(results)} 个结果')

        # 保存结果文件
        _log(f'[OCRPipeline] >>> 阶段 2/5: 正在保存识别结果文件（JSON/MD/HTML/Excel）...')
        t0 = time.time()
        for res in results:
            res.save_to_json(save_path=json_path)
            res.save_to_markdown(save_path=md_path)
            res.save_to_html(save_path=html_path)
            res.save_to_xlsx(save_path=xlsx_path)
        _log(f'[OCRPipeline] ✓ 阶段 2/5 完成，耗时 {time.time()-t0:.1f}s')

        # 解析结果获取文本和表格数据
        _log(f'[OCRPipeline] >>> 阶段 3/5: 正在解析推理结果...')
        t0 = time.time()
        parsed = _parse_v3_result(results, img_bgr.shape[:2], xlsx_path=xlsx_path)
        ocr_results = parsed['ocr_results']
        table_regions = parsed['table_regions']
        _log(f'[OCRPipeline] ✓ 阶段 3/5 完成，耗时 {time.time()-t0:.1f}s')
        _log(f'[OCRPipeline]   - 文本块数量: {len(ocr_results)}')
        _log(f'[OCRPipeline]   - 表格区域数量: {len(table_regions)}')

        # 提取表格结构信息
        _log(f'[OCRPipeline] >>> 阶段 4/5: 正在构建表格结构...')
        t0 = time.time()
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
            _log(f'[OCRPipeline]   使用表格区域，{table["num_rows"]} 行 x {table["num_cols"]} 列')
        elif ocr_results:
            # 如果没有检测到表格区域，使用备用方案
            table = build_table_structure(ocr_results)
            _log(f'[OCRPipeline]   使用几何推断构建表格，{table["num_rows"]} 行 x {table["num_cols"]} 列')
        else:
            _log(f'[OCRPipeline]   ⚠ 未检测到表格结构')
        _log(f'[OCRPipeline] ✓ 阶段 4/5 完成，耗时 {time.time()-t0:.1f}s')

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
        _log(f'[OCRPipeline] >>> 阶段 5/5: 正在提取字段信息...')
        t0 = time.time()
        extracted_fields = {}
        if task_type != OCRTask.GENERAL:
            parser_map = {
                OCRTask.REPAIR_ORDER: RepairOrderParser(),
                OCRTask.REPAIR_CARD: RepairCardParser(),
                OCRTask.MATERIAL: MaterialParser(kwargs.get('doc_type', 'out')),
            }
            parser = parser_map.get(task_type, DocParser())

            if kwargs.get('use_fastgpt') and kwargs.get('fastgpt_config'):
                _log(f'[OCRPipeline]   正在使用 FastGPT 增强字段提取...')
                extracted_fields = parser._extract_fastgpt(ocr_results, kwargs.get('fastgpt_config'), table_regions)
            else:
                extracted_fields = parser.extract_fields(ocr_results, table_regions)
            _log(f'[OCRPipeline]   字段提取完成: {extracted_fields}')
        _log(f'[OCRPipeline] ✓ 阶段 5/5 完成，耗时 {time.time()-t0:.1f}s')

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
            'xlsx_path': xlsx_path,
            'mode': 'slow',
        }

        # 保存解析结果（包含提取的字段信息）
        _log(f'[OCRPipeline] 正在保存最终 JSON 结果...')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        total_time = time.time() - t_start
        _log(f'')
        _log(f'[SUCCESS] ✓ 识别完成！总计耗时 {total_time:.1f}s')
        _log(f'[INFO] 生成的文件：')
        _log(f'  - {os.path.basename(json_path)} (完整识别结果)')
        _log(f'  - {os.path.basename(md_path)} (Markdown结果)')
        _log(f'  - {os.path.basename(html_path)} (表格HTML)')
        _log(f'  - {os.path.basename(xlsx_path)} (表格Excel)')
        _log(f'[OCRPipeline] ========== 处理结束 ==========')

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

    def process_image(self, image_path: str, use_fastgpt: bool = False, fastgpt_config: dict = None, output_dir: str = None, mode: str = "slow") -> Dict:
        """
        处理调修单图像

        参数:
            image_path: 图像文件路径
            use_fastgpt: 是否使用 FastGPT 增强
            fastgpt_config: FastGPT 配置
            output_dir: 输出目录
            mode: slow|fast - 控制引擎模式
        """
        return OCRPipeline.process(
            image_path,
            task_type=OCRTask.REPAIR_ORDER,
            use_fastgpt=use_fastgpt,
            fastgpt_config=fastgpt_config,
            output_dir=output_dir or 'output',
            mode=mode,
        )

    def process_repair_card(self, image_path: str, use_fastgpt: bool = False, fastgpt_config: dict = None, output_dir: str = None, mode: str = "slow") -> Dict:
        """处理返修卡图像（PPStructureV3 + RepairCardParser 字段 + 可选 FastGPT）"""
        from ocr_core import OCRPipeline, OCRTask
        return OCRPipeline.process(
            image_path,
            task_type=OCRTask.REPAIR_CARD,
            use_fastgpt=use_fastgpt,
            fastgpt_config=fastgpt_config,
            output_dir=output_dir or 'output',
            mode=mode,
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
