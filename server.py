#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server.py - FastAPI OCR 后端服务 v2.0
提供 HTTP 接口供 React 前端调用，替代原 PyQt5 GUI。

主引擎：PPStructureV3（启动时预加载）

接口列表：
  POST /api/ocr/pipeline          - 统一流水线入口（推荐）
  POST /api/ocr/repair-order      - 调修单 OCR 识别
  POST /api/ocr/repair-card       - 返修卡 OCR 识别
  POST /api/ocr/material          - 航材出入库单识别
  POST /api/ocr/general           - 通用文档/表格 OCR 识别
  POST /api/ocr/table-structure   - PP-Structure 表格识别
  POST /api/ocr/repair-archive/merge - 调修单+返修卡批量表合并为返修件档案
  GET  /api/health                - 健康检查
  GET  /api/config/fastgpt        - 读取 FastGPT 配置
  POST /api/config/fastgpt        - 保存 FastGPT 配置
"""
import os
import sys
import json
import shutil
import tempfile
import traceback
import base64
from io import BytesIO
from datetime import datetime
from typing import Dict, List, Optional

# Windows 控制台强制 UTF-8
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

# 离线模式，禁用联网检查
os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# OCR 核心（延迟导入，避免启动时就加载模型）
_ocr_processor = None
_table_pipeline = None


def get_ocr_processor():
    """懒加载 RepairOrderOCR，只在首次请求时初始化"""
    global _ocr_processor
    if _ocr_processor is None:
        from ocr_core import RepairOrderOCR
        _ocr_processor = RepairOrderOCR()
    return _ocr_processor


def get_table_pipeline():
    """懒加载通用OCR pipeline（与调修单共用同一引擎）"""
    global _table_pipeline
    if _table_pipeline is None:
        _table_pipeline = get_ocr_processor()
    return _table_pipeline

# ─── FastAPI App ─────────────────────────────────────────────────────────────
app = FastAPI(
    title="OCR·CHAIN 后端服务",
    description="PaddleOCR 识别引擎 + FastGPT 可选接口",
    version="1.0.0",
)


@app.on_event("startup")
async def _warmup():
    """服务启动时预加载 PPStructureV3 主引擎"""
    import threading
    def _load():
        try:
            print("[OCR·CHAIN] 正在预加载引擎，请稍候...")
            from ocr_core import v3_pool, fast_ocr_pool

            # 预加载 PPStructureV3 主引擎（慢速模式）
            print("[OCR·CHAIN] 正在预加载 PPStructureV3 主引擎...")
            v3_pool.warmup()

            # 预加载纯 PaddleOCR 极速引擎（快速模式）
            print("[OCR·CHAIN] 正在预加载纯 PaddleOCR 极速引擎...")
            fast_ocr_pool.warmup()

            # 同时预热兼容引擎（后台）
            get_ocr_processor()
            print("[OCR·CHAIN] 引擎预加载指令已下发，后台加载中...")
        except Exception as e:
            print(f"[OCR·CHAIN] 预加载失败（不影响服务运行）: {e}")
    threading.Thread(target=_load, daemon=True).start()

# 允许前端跨域（开发时 Vite 在 5173，生产可关闭）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── 工具函数 ─────────────────────────────────────────────────────────────────
def _save_upload(upload: UploadFile) -> str:
    """将上传文件保存到临时目录，返回路径"""
    suffix = os.path.splitext(upload.filename or "")[1] or ".png"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        shutil.copyfileobj(upload.file, tmp)
    finally:
        tmp.close()
    return tmp.name


def _cleanup(*paths: str):
    for p in paths:
        try:
            os.unlink(p)
        except Exception:
            pass
def _get_output_dir() -> str:
    """获取 output 目录路径"""
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    os.makedirs(d, exist_ok=True)
    return d


def _create_session_dir() -> str:
    """
    创建一个以时间戳命名的新会话目录，用于存放本次识别的所有输出文件。
    目录名格式：session_YYYYMMDD_HHMMSS_ffffff
    """
    output_dir = _get_output_dir()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    session_dir = os.path.join(output_dir, f"session_{timestamp}")
    os.makedirs(session_dir, exist_ok=True)
    return session_dir


# 调修单导出：与业务模板一致的列顺序（横向一行 + 原图）
REPAIR_ORDER_EXPORT_FIELDS = [
    '调修单号', '装备型号', '器材名称', '型（图）号', '器件编号', '邮寄地址', '进厂时间',
]

# 返修卡导出字段（与 ocr_core.RepairCardParser.FIELDS 一致）
REPAIR_CARD_EXPORT_FIELDS = [
    '返修卡号', '产品代号', '联系人', '顾客单位', '批次号', '电话号',
    '返修件名称', '图号', '返修故障件信息', '损坏原因修理结果', 'FRACAS/排故报告编号',
]


def _repair_order_field_map(fields_list: list) -> dict[str, str]:
    m: dict[str, str] = {}
    for item in fields_list:
        f = item.get('field', '')
        v = item.get('value', '')
        if f in REPAIR_ORDER_EXPORT_FIELDS:
            m[f] = v
    return m


def _repair_card_field_map(fields_list: list) -> dict[str, str]:
    m: dict[str, str] = {}
    for item in fields_list:
        f = item.get('field', '')
        v = item.get('value', '')
        if f in REPAIR_CARD_EXPORT_FIELDS:
            m[f] = v
    return m


def _write_repair_order_excel_template(
    path: str,
    field_map: dict[str, str],
    image_name: str,
    recognition_time: str,
    image_bytes: Optional[bytes],
) -> None:
    """生成与业务模板一致的 xlsx：蓝底表头、一行数据、J 列嵌入缩略原图。"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.drawing.image import Image as XLImage
    from PIL import Image as PILImage

    wb = Workbook()
    ws = wb.active
    ws.title = '调修单'

    headers = [
        '图片名称', '调修单号', '装备型号', '器材名称', '型（图）号',
        '器件编号', '邮寄地址', '进厂时间', '识别时间', '原图',
    ]
    header_fill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
    header_font = Font(color='FFFFFF', bold=True, size=11)
    thin = Side(style='thin', color='B4C6E7')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    align = Alignment(vertical='center', wrap_text=True)

    for col, title in enumerate(headers, start=1):
        c = ws.cell(row=1, column=col, value=title)
        c.fill = header_fill
        c.font = header_font
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        c.border = border

    row_vals = [
        image_name or '',
        field_map.get('调修单号', ''),
        field_map.get('装备型号', ''),
        field_map.get('器材名称', ''),
        field_map.get('型（图）号', ''),
        field_map.get('器件编号', ''),
        field_map.get('邮寄地址', ''),
        field_map.get('进厂时间', ''),
        recognition_time or '',
        '',  # 原图列由图片覆盖
    ]
    for col, val in enumerate(row_vals, start=1):
        c = ws.cell(row=2, column=col, value=val)
        c.alignment = align
        c.border = border

    from openpyxl.utils import get_column_letter
    col_widths = [14, 22, 18, 14, 16, 14, 28, 12, 20, 18]
    for i, w in enumerate(col_widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    thumb_path: Optional[str] = None
    if image_bytes:
        try:
            pil = PILImage.open(BytesIO(image_bytes))
            if pil.mode in ('RGBA', 'P'):
                pil = pil.convert('RGB')
            try:
                resample = PILImage.Resampling.LANCZOS
            except AttributeError:
                resample = PILImage.LANCZOS  # type: ignore[attr-defined]
            pil.thumbnail((520, 380), resample)
            thumb_path = tempfile.NamedTemporaryFile(delete=False, suffix='.png').name
            pil.save(thumb_path, 'PNG')
            xl_img = XLImage(thumb_path)
            ws.add_image(xl_img, 'J2')
            ws.row_dimensions[2].height = 220
        except Exception as e:
            print(f'[调修单导出] 嵌入原图失败（仍保存表格）: {e}', flush=True)
    else:
        ws.row_dimensions[2].height = 28

    wb.save(path)
    if thumb_path:
        try:
            os.unlink(thumb_path)
        except OSError:
            pass


def _write_repair_card_excel_template(
    path: str,
    field_map: dict[str, str],
    image_name: str,
    recognition_time: str,
    image_bytes: Optional[bytes],
) -> None:
    """返修卡：横向一行 + 多列字段 + 末列嵌入缩略原图。"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.drawing.image import Image as XLImage
    from PIL import Image as PILImage

    wb = Workbook()
    ws = wb.active
    ws.title = '返修卡'

    headers = [
        '图片名称', '返修卡号', '产品代号', '联系人', '顾客单位', '批次号', '电话号',
        '返修件名称', '图号', '返修故障件信息', '损坏原因修理结果', 'FRACAS/排故报告编号',
        '识别时间', '原图',
    ]
    header_fill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
    header_font = Font(color='FFFFFF', bold=True, size=10)
    thin = Side(style='thin', color='B4C6E7')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    align = Alignment(vertical='center', wrap_text=True)

    for col, title in enumerate(headers, start=1):
        c = ws.cell(row=1, column=col, value=title)
        c.fill = header_fill
        c.font = header_font
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        c.border = border

    row_vals = [
        image_name or '',
        field_map.get('返修卡号', ''),
        field_map.get('产品代号', ''),
        field_map.get('联系人', ''),
        field_map.get('顾客单位', ''),
        field_map.get('批次号', ''),
        field_map.get('电话号', ''),
        field_map.get('返修件名称', ''),
        field_map.get('图号', ''),
        field_map.get('返修故障件信息', ''),
        field_map.get('损坏原因修理结果', ''),
        field_map.get('FRACAS/排故报告编号', ''),
        recognition_time or '',
        '',
    ]
    for col, val in enumerate(row_vals, start=1):
        c = ws.cell(row=2, column=col, value=val)
        c.alignment = align
        c.border = border

    from openpyxl.utils import get_column_letter
    col_widths = [12, 14, 10, 10, 24, 10, 12, 14, 14, 28, 28, 18, 18, 14]
    for i, w in enumerate(col_widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    thumb_path: Optional[str] = None
    if image_bytes:
        try:
            pil = PILImage.open(BytesIO(image_bytes))
            if pil.mode in ('RGBA', 'P'):
                pil = pil.convert('RGB')
            try:
                resample = PILImage.Resampling.LANCZOS
            except AttributeError:
                resample = PILImage.LANCZOS  # type: ignore[attr-defined]
            pil.thumbnail((480, 360), resample)
            thumb_path = tempfile.NamedTemporaryFile(delete=False, suffix='.png').name
            pil.save(thumb_path, 'PNG')
            xl_img = XLImage(thumb_path)
            ws.add_image(xl_img, 'N2')
            ws.row_dimensions[2].height = 200
        except Exception as e:
            print(f'[返修卡导出] 嵌入原图失败（仍保存表格）: {e}', flush=True)
    else:
        ws.row_dimensions[2].height = 28

    wb.save(path)
    if thumb_path:
        try:
            os.unlink(thumb_path)
        except OSError:
            pass


def _write_repair_order_excel_batch(path: str, rows: List[dict]) -> None:
    """
    调修单批量导出：多行数据，表头与单张导出一致。
    rows: [{ "image_name", "recognition_time", "field_map": dict, "image_bytes": Optional[bytes] }, ...]
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.utils import get_column_letter
    from PIL import Image as PILImage

    wb = Workbook()
    ws = wb.active
    ws.title = '调修单'

    headers = [
        '图片名称', '调修单号', '装备型号', '器材名称', '型（图）号',
        '器件编号', '邮寄地址', '进厂时间', '识别时间', '原图',
    ]
    header_fill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
    header_font = Font(color='FFFFFF', bold=True, size=11)
    thin = Side(style='thin', color='B4C6E7')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    align = Alignment(vertical='center', wrap_text=True)

    for col, title in enumerate(headers, start=1):
        c = ws.cell(row=1, column=col, value=title)
        c.fill = header_fill
        c.font = header_font
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        c.border = border

    col_widths = [14, 22, 18, 14, 16, 14, 28, 12, 20, 18]
    for i, w in enumerate(col_widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    thumb_paths: List[str] = []
    try:
        resample = PILImage.Resampling.LANCZOS
    except AttributeError:
        resample = PILImage.LANCZOS  # type: ignore[attr-defined]

    for i, row in enumerate(rows):
        r = i + 2
        fm = row.get('field_map') or {}
        row_vals = [
            row.get('image_name') or '',
            fm.get('调修单号', ''),
            fm.get('装备型号', ''),
            fm.get('器材名称', ''),
            fm.get('型（图）号', ''),
            fm.get('器件编号', ''),
            fm.get('邮寄地址', ''),
            fm.get('进厂时间', ''),
            row.get('recognition_time') or '',
            '',
        ]
        for col, val in enumerate(row_vals, start=1):
            c = ws.cell(row=r, column=col, value=val)
            c.alignment = align
            c.border = border

        img_b = row.get('image_bytes')
        if img_b:
            try:
                pil = PILImage.open(BytesIO(img_b))
                if pil.mode in ('RGBA', 'P'):
                    pil = pil.convert('RGB')
                pil.thumbnail((520, 380), resample)
                tp = tempfile.NamedTemporaryFile(delete=False, suffix='.png').name
                pil.save(tp, 'PNG')
                thumb_paths.append(tp)
                xl_img = XLImage(tp)
                ws.add_image(xl_img, f'J{r}')
                ws.row_dimensions[r].height = 220
            except Exception as e:
                print(f'[调修单批量导出] 第{i + 1}行嵌入原图失败: {e}', flush=True)
                ws.row_dimensions[r].height = 28
        else:
            ws.row_dimensions[r].height = 28

    wb.save(path)
    for tp in thumb_paths:
        try:
            os.unlink(tp)
        except OSError:
            pass


def _write_repair_card_excel_batch(path: str, rows: List[dict]) -> None:
    """返修卡批量导出。rows: [{ image_name, recognition_time, field_map, image_bytes? }, ...]"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.utils import get_column_letter
    from PIL import Image as PILImage

    wb = Workbook()
    ws = wb.active
    ws.title = '返修卡'

    headers = [
        '图片名称', '返修卡号', '产品代号', '联系人', '顾客单位', '批次号', '电话号',
        '返修件名称', '图号', '返修故障件信息', '损坏原因修理结果', 'FRACAS/排故报告编号',
        '识别时间', '原图',
    ]
    header_fill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
    header_font = Font(color='FFFFFF', bold=True, size=10)
    thin = Side(style='thin', color='B4C6E7')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    align = Alignment(vertical='center', wrap_text=True)

    for col, title in enumerate(headers, start=1):
        c = ws.cell(row=1, column=col, value=title)
        c.fill = header_fill
        c.font = header_font
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        c.border = border

    col_widths = [12, 14, 10, 10, 24, 10, 12, 14, 14, 28, 28, 18, 18, 14]
    for i, w in enumerate(col_widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    thumb_paths: List[str] = []
    try:
        resample = PILImage.Resampling.LANCZOS
    except AttributeError:
        resample = PILImage.LANCZOS  # type: ignore[attr-defined]

    for i, row in enumerate(rows):
        r = i + 2
        fm = row.get('field_map') or {}
        row_vals = [
            row.get('image_name') or '',
            fm.get('返修卡号', ''),
            fm.get('产品代号', ''),
            fm.get('联系人', ''),
            fm.get('顾客单位', ''),
            fm.get('批次号', ''),
            fm.get('电话号', ''),
            fm.get('返修件名称', ''),
            fm.get('图号', ''),
            fm.get('返修故障件信息', ''),
            fm.get('损坏原因修理结果', ''),
            fm.get('FRACAS/排故报告编号', ''),
            row.get('recognition_time') or '',
            '',
        ]
        for col, val in enumerate(row_vals, start=1):
            c = ws.cell(row=r, column=col, value=val)
            c.alignment = align
            c.border = border

        img_b = row.get('image_bytes')
        if img_b:
            try:
                pil = PILImage.open(BytesIO(img_b))
                if pil.mode in ('RGBA', 'P'):
                    pil = pil.convert('RGB')
                pil.thumbnail((480, 360), resample)
                tp = tempfile.NamedTemporaryFile(delete=False, suffix='.png').name
                pil.save(tp, 'PNG')
                thumb_paths.append(tp)
                xl_img = XLImage(tp)
                ws.add_image(xl_img, f'N{r}')
                ws.row_dimensions[r].height = 200
            except Exception as e:
                print(f'[返修卡批量导出] 第{i + 1}行嵌入原图失败: {e}', flush=True)
                ws.row_dimensions[r].height = 28
        else:
            ws.row_dimensions[r].height = 28

    wb.save(path)
    for tp in thumb_paths:
        try:
            os.unlink(tp)
        except OSError:
            pass


def _field_result(fields: dict, ocr_results: list) -> dict:
    """将提取字段转换为前端 ResultTable 需要的格式"""
    # 计算每个字段值的置信度（取对应 OCR 文本的最大置信度）
    text_conf: dict[str, float] = {}
    for item in ocr_results:
        text_conf[item["text"]] = max(text_conf.get(item["text"], 0.0), item["confidence"])

    results = []
    for field, value in fields.items():
        conf = text_conf.get(value, 0.0) if value else 0.0
        results.append({
            "key":        field,
            "field":      field,
            "value":      value,
            "confidence": round(conf, 4),
        })
    return results


# ─── Config 路径 ────────────────────────────────────────────────────────────────
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

STEP_KEYS = ["repair_order_ocr", "repair_card_ocr", "archive_generation", "ids_match", "quote_generation"]

DEFAULT_CONFIG = {
    k: {"api_url": "", "api_key": "", "appid": "", "enabled": False}
    for k in STEP_KEYS
}


def _load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
            # 兼容旧版扁平格式（单一配置）
            if any(k in data for k in STEP_KEYS):
                cfg = {**DEFAULT_CONFIG, **data}
            else:
                # 旧版格式迁移：将旧配置映射到 repair_order_ocr
                cfg = {**DEFAULT_CONFIG}
                cfg["repair_order_ocr"] = {
                    "api_url": data.get("api_url", ""),
                    "api_key": data.get("api_key", ""),
                    "appid":   data.get("appid", ""),
                    "enabled": data.get("enabled", False),
                }
            return cfg
        except Exception:
            pass
    return {**DEFAULT_CONFIG}


def _save_config(cfg: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ─── 路由 ─────────────────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@app.get("/api/config/fastgpt")
def get_fastgpt_config():
    """读取各步骤 FastGPT 配置"""
    return _load_config()


@app.post("/api/config/fastgpt")
async def save_fastgpt_config(payload: dict):
    """
    保存各步骤 FastGPT 配置。
    Body: { repair_order_ocr: {...}, repair_card_ocr: {...}, ids_match: {...}, quote_generation: {...} }
    """
    cfg = _load_config()
    for key in STEP_KEYS:
        if key in payload:
            entry = payload[key]
            cfg[key] = {
                "api_url": str(entry.get("api_url", "")),
                "api_key": str(entry.get("api_key", "")),
                "appid":   str(entry.get("appid", "")),
                "enabled": bool(entry.get("enabled", False)),
            }
    _save_config(cfg)
    return {"success": True, "config": cfg}


@app.post("/api/ocr/pipeline")
async def ocr_pipeline(
    file:           UploadFile = File(...),
    task:           str  = Form("general"),   # OCRTask 枚举值
    use_fastgpt:    bool = Form(False),
    api_url:        str  = Form(""),
    api_key:        str  = Form(""),
    appid:          str  = Form(""),
    doc_type:       str  = Form("out"),        # 仅 material 任务使用
    export_format:  str  = Form("none"),       # none|excel|csv|markdown|all
    mode:           str  = Form("slow"),       # slow|fast，控制引擎模式
):
    """
    统一 OCR 流水线接口（推荐主入口）。

    task 取值：
      text         - 简单文本识别（PPStructureV3 OCR）
      table        - 表格识别（PPStructureV3 + 三阶段降级）
      repair_order - 调修单（PPStructureV3 + 字段提取 + 可选FastGPT）
      repair_card  - 返修卡
      material     - 航材出入库单（doc_type: out|in）
      inspection   - 检验报告单
      maintenance  - 维修记录单
      quotation    - 报价单
      general      - 通用版面分析

    mode 取值：
      slow  - 正常模式，使用 PPStructureV3（完整流程，生成表格）
      fast  - 快速模式，使用纯 PaddleOCR（仅文本检测+识别）

    返回：{ success, task, fields, raw_text, table_html,
             ocr_count, table_regions, summary, exports, timestamp, mode }
    """
    from datetime import datetime as dt
    import sys
    
    def _log(msg: str):
        ts = dt.now().strftime('%H:%M:%S.%f')[:-3]
        try:
            print(f"[{ts}] [PipelineAPI] {msg}", flush=True)
        except UnicodeEncodeError:
            for old, new in {'\u2714': '[OK]', '\u2717': '[FAIL]', '\u26a0': '[WARN]'}.items():
                msg = msg.replace(old, new)
            print(f"[{ts}] [PipelineAPI] {msg}", flush=True)
        sys.stdout.flush()
    
    _log(f'收到请求 task={task}, filename={file.filename}, export_format={export_format}, mode={mode}')
    tmp_path = _save_upload(file)
    _log(f'临时文件: {tmp_path}')
    # 创建独立会话目录，存放本次识别的所有文件
    session_dir = _create_session_dir()
    _log(f'会话目录: {session_dir}')
    try:
        from ocr_core import OCRPipeline
        _log(f'开始执行 OCR 流水线...')
        t0 = dt.now()
        result = OCRPipeline.run(
            tmp_path,
            task=task,
            use_fastgpt=use_fastgpt,
            fastgpt_config={"api_url": api_url, "api_key": api_key, "appid": appid} if use_fastgpt else None,
            doc_type=doc_type,
            output_dir=session_dir,
            mode=mode,
        )
        elapsed = (dt.now() - t0).total_seconds()
        _log(f'✓ Pipeline 完成，耗时 {elapsed:.1f}s，文本块: {len(result.get("ocr_results", []))}')

        # 获取提取的字段（优先使用 FastGPT 增强结果）
        extracted_fields = result.get("extracted_fields", {})

        # 字段列表格式化
        fields_list = _field_result(
            extracted_fields,
            result.get("ocr_results", [])
        )

        # 当启用 FastGPT 时，summary 使用 FastGPT 返回的字段摘要
        summary = result.get("summary", "")
        if use_fastgpt and extracted_fields:
            filled = sum(1 for v in extracted_fields.values() if v)
            summary = f"FastGPT 增强识别完成，共提取 {filled} 个字段: " + \
                      ", ".join(f"{k}={v}" for k, v in extracted_fields.items() if v)

        # 可选导出（保存到会话目录）
        # 注意：优先使用 FastGPT 增强后的字段结果
        exports: dict = {}

        # 如果有 FastGPT 增强的字段，先保存一份结构化的字段结果
        if use_fastgpt and extracted_fields:
            fastgpt_fields_path = os.path.join(session_dir, f"fastgpt_fields_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            try:
                fastgpt_data = {
                    "source": "fastgpt_enhanced",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "fields": extracted_fields,
                    "ocr_text": result.get("summary", ""),
                }
                with open(fastgpt_fields_path, 'w', encoding='utf-8') as f:
                    json.dump(fastgpt_data, f, ensure_ascii=False, indent=2)
                exports["fastgpt_fields"] = fastgpt_fields_path
                _log(f'已保存 FastGPT 增强字段: {fastgpt_fields_path}')
            except Exception as e:
                _log(f'保存 FastGPT 字段失败: {e}')

        # 表格导出（当有原始表格数据时才导出）
        table = result.get("table")
        if export_format != "none" and table:
            _log(f'正在导出格式: {export_format}')
            from ocr_core import TableExporter, TableDetector
            cells = table.get("cells", [])
            nr = table.get("num_rows", 0)
            nc = table.get("num_cols", 0)
            grid = TableDetector._cells_to_grid(cells, nr, nc) if cells else []

            # 如果使用 FastGPT 且有提取的字段，用 FastGPT 字段构建可导出格式
            if use_fastgpt and extracted_fields and not cells:
                # FastGPT 有字段但无原始表格结构，按字段构建简单表格
                grid = [[field, str(value)] for field, value in extracted_fields.items() if value]
                nr = len(grid)
                nc = 2

            if grid:
                base = os.path.join(session_dir, f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
                if export_format == "all":
                    exports = TableExporter.export_all(grid, base)
                elif export_format == "excel":
                    exports["excel"] = TableExporter.to_excel(grid, base + ".xlsx")
                elif export_format == "csv":
                    exports["csv"] = TableExporter.to_csv(grid, base + ".csv")
                elif export_format == "markdown":
                    exports["markdown"] = TableExporter.to_markdown(grid, base + ".md")
                elif export_format == "html":
                    exports["html"] = TableExporter.to_html(grid, base + ".html")
                elif export_format == "json":
                    exports["json"] = TableExporter.to_json(grid, base + ".json")
            elif use_fastgpt and extracted_fields:
                # 没有原始表格但有 FastGPT 字段时，直接导出字段为 CSV/MD/JSON
                _log(f'无原始表格，使用 FastGPT 字段导出...')
                base = os.path.join(session_dir, f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

                if export_format in ("csv", "all"):
                    csv_path = base + ".csv"
                    with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
                        import csv
                        writer = csv.writer(f)
                        writer.writerow(["字段名称", "提取内容"])
                        for field, value in extracted_fields.items():
                            writer.writerow([field, value])
                    exports["csv"] = csv_path

                if export_format in ("markdown", "all"):
                    md_path = base + ".md"
                    with open(md_path, 'w', encoding='utf-8') as f:
                        f.write("# OCR 识别结果 (FastGPT 增强)\n\n")
                        f.write(f"**识别时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                        f.write("| 字段名称 | 提取内容 |\n")
                        f.write("|---------|----------|\n")
                        for field, value in extracted_fields.items():
                            f.write(f"| {field} | {value} |\n")
                    exports["markdown"] = md_path

                if export_format in ("json", "all"):
                    json_path = base + ".json"
                    with open(json_path, 'w', encoding='utf-8') as f:
                        json.dump({
                            "source": "fastgpt_enhanced",
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "fields": extracted_fields,
                        }, f, ensure_ascii=False, indent=2)
                    exports["json"] = json_path

                if export_format == "excel":
                    xlsx_path = base + ".xlsx"
                    import pandas as pd
                    df = pd.DataFrame([
                        {"字段名称": f, "提取内容": v}
                        for f, v in extracted_fields.items()
                    ])
                    df.to_excel(xlsx_path, index=False)
                    exports["excel"] = xlsx_path

            _log(f'导出完成: {list(exports.keys())}')

        return {
            "success":       True,
            "task":          task,
            "fields":        fields_list,
            "raw_text":      result.get("summary", ""),
            "table_html":    result.get("html", ""),
            "table_regions": [
                {
                    "bbox": r["bbox"], 
                    "html": r["html"],
                    "num_rows": (max((c["row"] for c in r["cells"]), default=0) + 1) if r["cells"] else 0,
                    "num_cols": (max((c["col"] for c in r["cells"]), default=0) + 1) if r["cells"] else 0,
                    "cell_count": len(r["cells"])
                }
                for r in result.get("table_regions", [])
            ],
            "ocr_count":     len(result.get("ocr_results", [])),
            "summary":       result.get("summary", ""),
            "exports":       exports,
            "mode":          result.get("mode", "slow"),
            "timestamp":     result.get("timestamp",
                                datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        }
    except Exception as e:
        _log(f'✗ Pipeline 失败: {e}')
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _cleanup(tmp_path)


@app.post("/api/ocr/repair-order")
async def ocr_repair_order(
    file: UploadFile = File(...),
    use_fastgpt: bool = Form(False),
    mode: str = Form("slow"),
    api_url:  str = Form(""),
    api_key:  str = Form(""),
    appid:    str = Form(""),
):
    """
    调修单 OCR 识别。
    mode: slow|fast - 控制引擎模式
    返回：{ success, fields, ocr_count, timestamp, raw_exports, fastgpt_used, mode }
    """
    from datetime import datetime as dt
    import sys

    def _log(msg: str):
        ts = dt.now().strftime('%H:%M:%S.%f')[:-3]
        try:
            print(f"[{ts}] [调修单API] {msg}", flush=True)
        except UnicodeEncodeError:
            for old, new in {'\u2714': '[OK]', '\u2717': '[FAIL]', '\u26a0': '[WARN]'}.items():
                msg = msg.replace(old, new)
            print(f"[{ts}] [调修单API] {msg}", flush=True)
        sys.stdout.flush()

    _log(f'收到识别请求，文件名: {file.filename}')
    _log(f'use_fastgpt={use_fastgpt}, mode={mode}')
    tmp_path = _save_upload(file)
    _log(f'临时文件已保存: {tmp_path}')
    session_dir = _create_session_dir()
    _log(f'会话目录: {session_dir}')
    try:
        _log('正在加载 OCR 处理器...')
        processor = get_ocr_processor()
        _log('OCR 处理器已就绪')
        fastgpt_cfg = {"api_url": api_url, "api_key": api_key, "appid": appid} if use_fastgpt else None
        _log(f'开始执行调修单识别...')
        t0 = dt.now()
        result = processor.process_image(
            tmp_path,
            use_fastgpt=use_fastgpt,
            fastgpt_config=fastgpt_cfg,
            output_dir=session_dir,
            mode=mode,
        )
        if result is None:
            _log('✗ OCR 处理器返回 None')
            raise ValueError('OCR 处理器返回空结果')
    except Exception as e:
        _log(f'✗ 识别失败: {e}')
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f'[调修单识别] {e}')
    finally:
        _cleanup(tmp_path)

    elapsed = (dt.now() - t0).total_seconds()

    # 记录字段提取来源
    extracted_fields = result["extracted_fields"]
    fastgpt_enabled = use_fastgpt and bool(fastgpt_cfg and fastgpt_cfg.get('api_key'))
    _log(f'✓ 识别完成，耗时 {elapsed:.1f}s')
    _log(f'  - 文本块: {len(result["ocr_results"])} 个')
    _log(f'  - FastGPT 启用: {fastgpt_enabled}')
    _log(f'  - 模式: {mode}')
    _log(f'  - 提取字段: {extracted_fields}')

    fields_list = _field_result(extracted_fields, result["ocr_results"])

    # 构建原始表格文件路径
    base_name = os.path.splitext(os.path.basename(tmp_path))[0]
    raw_json_path = os.path.join(session_dir, f"{base_name}.json")
    raw_html_path = os.path.join(session_dir, f"{base_name}_table.html")
    xlsx_raw = (result.get("xlsx_path") or "").strip()
    xlsx_exists = bool(xlsx_raw and os.path.exists(xlsx_raw))

    return {
        "success":   True,
        "fields":    fields_list,
        "ocr_count": len(result["ocr_results"]),
        "timestamp": result["timestamp"],
        # 原始表格文件路径
        "raw_exports": {
            "json": raw_json_path if os.path.exists(raw_json_path) else None,
            "html": raw_html_path if os.path.exists(raw_html_path) else None,
            "xlsx": xlsx_raw if xlsx_exists else None,
        },
        "fastgpt_used": fastgpt_enabled,
    }


@app.post("/api/ocr/repair-order/batch")
async def ocr_repair_order_batch(
    files: List[UploadFile] = File(...),
    use_fastgpt: bool = Form(False),
    mode: str = Form("slow"),
    api_url: str = Form(""),
    api_key: str = Form(""),
    appid: str = Form(""),
):
    """调修单批量识别。

    mode: slow|fast - 控制引擎模式
    """
    from datetime import datetime as dt

    if not files:
        raise HTTPException(status_code=400, detail="请至少上传一张图片")
    processor = get_ocr_processor()
    fastgpt_cfg = {"api_url": api_url, "api_key": api_key, "appid": appid} if use_fastgpt else None
    out_list: List[dict] = []
    for uf in files:
        fn = uf.filename or "image"
        tmp_path = _save_upload(uf)
        session_dir = _create_session_dir()
        try:
            result = processor.process_image(
                tmp_path,
                use_fastgpt=use_fastgpt,
                fastgpt_config=fastgpt_cfg,
                output_dir=session_dir,
                mode=mode,
            )
            extracted_fields = result["extracted_fields"]
            fields_list = _field_result(extracted_fields, result["ocr_results"])
            out_list.append({
                "success": True,
                "filename": fn,
                "fields": fields_list,
                "ocr_count": len(result["ocr_results"]),
                "timestamp": result["timestamp"],
                "mode": result.get("mode", "slow"),
                "fastgpt_used": use_fastgpt and bool(fastgpt_cfg and fastgpt_cfg.get("api_key")),
                "error": None,
            })
        except Exception as e:
            traceback.print_exc()
            out_list.append({
                "success": False,
                "filename": fn,
                "fields": [],
                "ocr_count": 0,
                "timestamp": dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                "fastgpt_used": False,
                "error": str(e),
            })
        finally:
            _cleanup(tmp_path)
    return {
        "success": all(x["success"] for x in out_list),
        "mode": mode,
        "count": len(out_list),
        "results": out_list,
    }


@app.post("/api/ocr/repair-order/export")
async def export_repair_order(
    fields_json: str = Form(""),
    fmt: str = Form("excel"),
    doc_type: str = Form("repair_order"),
    image_name: str = Form(""),
    recognition_time: str = Form(""),
    original_image: Optional[UploadFile] = File(default=None),
):
    """
    调修单识别结果导出接口。

    repair_order：横向一行模板，列为
      图片名称、调修单号、装备型号、器材名称、型（图）号、器件编号、邮寄地址、进厂时间、识别时间、原图（Excel 内嵌缩略图）。
    repair_card：沿用两列「字段名称 / 识别内容」导出（无模板图）。

    文件写入 output/ 根目录，便于 /api/export/download?filename= 下载。

    参数:
        fields_json       - JSON 字段列表 [{key, field, value, confidence}]
        fmt               - excel | csv | json | all
        doc_type          - repair_order | repair_card
        image_name        - 原图文件名（对应「图片名称」列）
        recognition_time  - 识别完成时间（对应「识别时间」列），缺省为服务端当前时间
        original_image    - 可选，上传的原图，用于 Excel J 列嵌入
    """
    from datetime import datetime as dt

    def _log(msg: str):
        ts = dt.now().strftime('%H:%M:%S.%f')[:-3]
        try:
            print(f"[{ts}] [调修单导出] {msg}", flush=True)
        except UnicodeEncodeError:
            for old, new in {'\u2714': '[OK]', '\u2717': '[FAIL]', '\u26a0': '[WARN]'}.items():
                msg = msg.replace(old, new)
            print(f"[{ts}] [调修单导出] {msg}", flush=True)
        sys.stdout.flush()

    _log(f'收到导出请求 fmt={fmt} doc_type={doc_type}')
    out_root = _get_output_dir()
    image_bytes: Optional[bytes] = None
    if original_image is not None:
        image_bytes = await original_image.read()
        if image_bytes:
            fn = original_image.filename or '(binary)'
            _log(f'收到原图 {fn}，大小 {len(image_bytes)} bytes')
        if not image_name and original_image.filename:
            image_name = original_image.filename
    if not recognition_time.strip():
        recognition_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    try:
        fields_list: list = json.loads(fields_json) if fields_json else []
        _log(f'解析到 {len(fields_list)} 个字段')

        base_name = f"调修单_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        exports: dict[str, str] = {}

        if doc_type == 'repair_order':
            field_map = _repair_order_field_map(fields_list)

            if fmt in ('excel', 'all'):
                _log('正在导出 Excel（调修单横向模板 + 原图）...')
                try:
                    path = os.path.join(out_root, f"{base_name}.xlsx")
                    _write_repair_order_excel_template(
                        path, field_map, image_name, recognition_time, image_bytes,
                    )
                    exports['excel'] = path
                    _log(f'✓ Excel: {path}')
                except Exception as e:
                    _log(f'⚠ Excel 导出失败: {e}')
                    traceback.print_exc()

            if fmt in ('csv', 'all'):
                _log('正在导出 CSV...')
                try:
                    import csv
                    path = os.path.join(out_root, f"{base_name}.csv")
                    headers = [
                        '图片名称', '调修单号', '装备型号', '器材名称', '型（图）号',
                        '器件编号', '邮寄地址', '进厂时间', '识别时间', '原图',
                    ]
                    row = [
                        image_name or '',
                        field_map.get('调修单号', ''),
                        field_map.get('装备型号', ''),
                        field_map.get('器材名称', ''),
                        field_map.get('型（图）号', ''),
                        field_map.get('器件编号', ''),
                        field_map.get('邮寄地址', ''),
                        field_map.get('进厂时间', ''),
                        recognition_time,
                        '(见 Excel 内嵌图)' if image_bytes else '',
                    ]
                    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                        w = csv.writer(f)
                        w.writerow(headers)
                        w.writerow(row)
                    exports['csv'] = path
                    _log(f'✓ CSV: {path}')
                except Exception as e:
                    _log(f'⚠ CSV 导出失败: {e}')

            if fmt in ('json', 'all'):
                _log('正在导出 JSON...')
                try:
                    export_data = {
                        'doc_type': '调修单',
                        'image_name': image_name,
                        'recognition_time': recognition_time,
                        'export_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'fields': {f: field_map.get(f, '') for f in REPAIR_ORDER_EXPORT_FIELDS},
                        'raw_results': fields_list,
                    }
                    if image_bytes:
                        export_data['original_image_base64'] = base64.b64encode(image_bytes).decode('ascii')
                        export_data['original_image_mime'] = original_image.content_type if original_image else ''
                    path = os.path.join(out_root, f"{base_name}.json")
                    with open(path, 'w', encoding='utf-8') as f:
                        json.dump(export_data, f, ensure_ascii=False, indent=2)
                    exports['json'] = path
                    _log(f'✓ JSON: {path}')
                except Exception as e:
                    _log(f'⚠ JSON 导出失败: {e}')

        else:
            # 返修卡：横向一行模板（与调修单类似）或两列竖表
            field_map = _repair_card_field_map(fields_list)
            base_card = f"返修卡_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"

            if fmt in ('excel', 'all'):
                _log('正在导出 Excel（返修卡横向模板 + 可选原图）...')
                try:
                    path = os.path.join(out_root, f"{base_card}.xlsx")
                    _write_repair_card_excel_template(
                        path, field_map, image_name, recognition_time, image_bytes,
                    )
                    exports['excel'] = path
                    _log(f'✓ Excel: {path}')
                except Exception as e:
                    _log(f'⚠ 返修卡 Excel 失败: {e}')
                    traceback.print_exc()

            if fmt in ('csv', 'all'):
                try:
                    import csv
                    path = os.path.join(out_root, f"{base_card}.csv")
                    headers = [
                        '图片名称', '返修卡号', '产品代号', '联系人', '顾客单位', '批次号', '电话号',
                        '返修件名称', '图号', '返修故障件信息', '损坏原因修理结果', 'FRACAS/排故报告编号',
                        '识别时间', '原图',
                    ]
                    row = [
                        image_name or '',
                        field_map.get('返修卡号', ''),
                        field_map.get('产品代号', ''),
                        field_map.get('联系人', ''),
                        field_map.get('顾客单位', ''),
                        field_map.get('批次号', ''),
                        field_map.get('电话号', ''),
                        field_map.get('返修件名称', ''),
                        field_map.get('图号', ''),
                        field_map.get('返修故障件信息', ''),
                        field_map.get('损坏原因修理结果', ''),
                        field_map.get('FRACAS/排故报告编号', ''),
                        recognition_time,
                        '(见 Excel 内嵌图)' if image_bytes else '',
                    ]
                    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                        w = csv.writer(f)
                        w.writerow(headers)
                        w.writerow(row)
                    exports['csv'] = path
                    _log(f'✓ CSV: {path}')
                except Exception as e:
                    _log(f'⚠ 返修卡 CSV 失败: {e}')

            if fmt in ('json', 'all'):
                try:
                    export_data = {
                        'doc_type': '返修卡',
                        'image_name': image_name,
                        'recognition_time': recognition_time,
                        'export_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'fields': {f: field_map.get(f, '') for f in REPAIR_CARD_EXPORT_FIELDS},
                        'raw_results': fields_list,
                    }
                    if image_bytes:
                        export_data['original_image_base64'] = base64.b64encode(image_bytes).decode('ascii')
                        export_data['original_image_mime'] = original_image.content_type if original_image else ''
                    path = os.path.join(out_root, f"{base_card}.json")
                    with open(path, 'w', encoding='utf-8') as f:
                        json.dump(export_data, f, ensure_ascii=False, indent=2)
                    exports['json'] = path
                    _log(f'✓ JSON: {path}')
                except Exception as e:
                    _log(f'⚠ 返修卡 JSON 失败: {e}')

        return {
            "success":   True,
            "exports":   exports,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    except HTTPException:
        raise
    except Exception as e:
        _log(f'✗ 导出失败: {e}')
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ocr/repair-order/export-batch")
async def export_repair_batch(
    batch_json: str = Form(...),
    doc_type: str = Form("repair_order"),
    fmt: str = Form("excel"),
    images: Optional[List[UploadFile]] = File(None),
):
    """
    批量导出调修单或返修卡识别结果（多行同一工作表）。
    batch_json: [{ "image_name", "recognition_time", "fields": [FieldResult,...] }, ...]
    images: 可选，与 batch 行顺序一致的原图，用于 Excel 末列缩略图。
    """
    out_root = _get_output_dir()
    try:
        rows_in = json.loads(batch_json) if batch_json else []
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"batch_json 无效: {e}")
    if not rows_in:
        raise HTTPException(status_code=400, detail="batch_json 为空")

    img_bytes_list: List[Optional[bytes]] = []
    if images:
        for im in images:
            b = await im.read()
            img_bytes_list.append(b if b else None)
    while len(img_bytes_list) < len(rows_in):
        img_bytes_list.append(None)

    exports: dict[str, str] = {}
    ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    base = f"调修单批量_{ts}" if doc_type == 'repair_order' else f"返修卡批量_{ts}"

    if doc_type == 'repair_order':
        rows_out = []
        for i, row in enumerate(rows_in):
            fl = row.get('fields') or []
            fm = _repair_order_field_map(fl if isinstance(fl, list) else [])
            rows_out.append({
                'image_name': row.get('image_name') or '',
                'recognition_time': row.get('recognition_time') or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'field_map': fm,
                'image_bytes': img_bytes_list[i],
            })
        if fmt in ('excel', 'all'):
            path = os.path.join(out_root, f"{base}.xlsx")
            _write_repair_order_excel_batch(path, rows_out)
            exports['excel'] = path
        if fmt in ('csv', 'all'):
            import csv
            path = os.path.join(out_root, f"{base}.csv")
            headers = [
                '图片名称', '调修单号', '装备型号', '器材名称', '型（图）号',
                '器件编号', '邮寄地址', '进厂时间', '识别时间', '原图',
            ]
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f)
                w.writerow(headers)
                for row in rows_out:
                    fm = row['field_map']
                    w.writerow([
                        row['image_name'],
                        fm.get('调修单号', ''),
                        fm.get('装备型号', ''),
                        fm.get('器材名称', ''),
                        fm.get('型（图）号', ''),
                        fm.get('器件编号', ''),
                        fm.get('邮寄地址', ''),
                        fm.get('进厂时间', ''),
                        row['recognition_time'],
                        '(见 Excel)' if row.get('image_bytes') else '',
                    ])
            exports['csv'] = path
        if fmt in ('json', 'all'):
            path = os.path.join(out_root, f"{base}.json")
            dump = {
                'doc_type': '调修单批量',
                'export_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'rows': [],
            }
            for row in rows_out:
                dump['rows'].append({
                    'image_name': row['image_name'],
                    'recognition_time': row['recognition_time'],
                    'fields': {f: row['field_map'].get(f, '') for f in REPAIR_ORDER_EXPORT_FIELDS},
                })
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(dump, f, ensure_ascii=False, indent=2)
            exports['json'] = path
    else:
        rows_out = []
        for i, row in enumerate(rows_in):
            fl = row.get('fields') or []
            fm = _repair_card_field_map(fl if isinstance(fl, list) else [])
            rows_out.append({
                'image_name': row.get('image_name') or '',
                'recognition_time': row.get('recognition_time') or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'field_map': fm,
                'image_bytes': img_bytes_list[i],
            })
        if fmt in ('excel', 'all'):
            path = os.path.join(out_root, f"{base}.xlsx")
            _write_repair_card_excel_batch(path, rows_out)
            exports['excel'] = path
        if fmt in ('csv', 'all'):
            import csv
            path = os.path.join(out_root, f"{base}.csv")
            headers = [
                '图片名称', '返修卡号', '产品代号', '联系人', '顾客单位', '批次号', '电话号',
                '返修件名称', '图号', '返修故障件信息', '损坏原因修理结果', 'FRACAS/排故报告编号',
                '识别时间', '原图',
            ]
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f)
                w.writerow(headers)
                for row in rows_out:
                    fm = row['field_map']
                    w.writerow([
                        row['image_name'],
                        fm.get('返修卡号', ''),
                        fm.get('产品代号', ''),
                        fm.get('联系人', ''),
                        fm.get('顾客单位', ''),
                        fm.get('批次号', ''),
                        fm.get('电话号', ''),
                        fm.get('返修件名称', ''),
                        fm.get('图号', ''),
                        fm.get('返修故障件信息', ''),
                        fm.get('损坏原因修理结果', ''),
                        fm.get('FRACAS/排故报告编号', ''),
                        row['recognition_time'],
                        '(见 Excel)' if row.get('image_bytes') else '',
                    ])
            exports['csv'] = path
        if fmt in ('json', 'all'):
            path = os.path.join(out_root, f"{base}.json")
            dump = {
                'doc_type': '返修卡批量',
                'export_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'rows': [],
            }
            for row in rows_out:
                dump['rows'].append({
                    'image_name': row['image_name'],
                    'recognition_time': row['recognition_time'],
                    'fields': {f: row['field_map'].get(f, '') for f in REPAIR_CARD_EXPORT_FIELDS},
                })
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(dump, f, ensure_ascii=False, indent=2)
            exports['json'] = path

    return {
        "success": True,
        "exports": exports,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.post("/api/ocr/repair-archive/merge")
async def merge_repair_archive(
    repair_order_xlsx: UploadFile = File(...),
    repair_card_xlsx: UploadFile = File(...),
    join_type: str = Form("inner"),
):
    """
    上传「调修单批量识别表」「返修卡批量识别表」两个 xlsx（与导出模板列名一致），
    按 装备型号=产品代号、器材名称=返修件名称、器件编号=批次号、型（图）号=图号 四键合并，
    生成「返修件档案.xlsx」。join_type: inner | left（左连以返修卡为主）。
    """
    if join_type not in ("inner", "left"):
        raise HTTPException(status_code=400, detail="join_type 须为 inner 或 left")
    from repair_archive_merge import build_repair_archive_xlsx

    out_root = _get_output_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    out_name = f"返修件档案_{ts}.xlsx"
    out_path = os.path.join(out_root, out_name)
    td = tempfile.mkdtemp()
    try:
        order_path = os.path.join(td, "order.xlsx")
        card_path = os.path.join(td, "card.xlsx")
        bo = await repair_order_xlsx.read()
        bc = await repair_card_xlsx.read()
        if not bo or not bc:
            raise HTTPException(status_code=400, detail="请上传非空的 xlsx 文件")
        with open(order_path, "wb") as f:
            f.write(bo)
        with open(card_path, "wb") as f:
            f.write(bc)
        stats = build_repair_archive_xlsx(order_path, card_path, out_path, join_type=join_type)  # type: ignore[arg-type]
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        shutil.rmtree(td, ignore_errors=True)

    return {
        "success": True,
        "exports": {"excel": out_path},
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "filename": out_name,
        **stats,
    }


@app.post("/api/ocr/repair-card")
async def ocr_repair_card(
    file: UploadFile = File(...),
    use_fastgpt: bool = Form(False),
    mode: str = Form("slow"),
    api_url:  str = Form(""),
    api_key:  str = Form(""),
    appid:    str = Form(""),
):
    """
    返修卡 OCR：PPStructureV3 版面/表格 + RepairCardParser 字段 + 可选 FastGPT。
    mode: slow|fast - 控制引擎模式
    返回：{ success, fields, ocr_count, timestamp, raw_exports, fastgpt_used, mode }
    """
    from datetime import datetime as dt
    import sys

    def _log(msg: str):
        ts = dt.now().strftime('%H:%M:%S.%f')[:-3]
        try:
            print(f"[{ts}] [返修卡API] {msg}", flush=True)
        except UnicodeEncodeError:
            for old, new in {'\u2714': '[OK]', '\u2717': '[FAIL]', '\u26a0': '[WARN]'}.items():
                msg = msg.replace(old, new)
            print(f"[{ts}] [返修卡API] {msg}", flush=True)
        sys.stdout.flush()

    _log(f'收到识别请求，文件名: {file.filename}, use_fastgpt={use_fastgpt}, mode={mode}')
    tmp_path = _save_upload(file)
    session_dir = _create_session_dir()
    _log(f'会话目录: {session_dir}')
    try:
        processor = get_ocr_processor()
        fastgpt_cfg = {"api_url": api_url, "api_key": api_key, "appid": appid} if use_fastgpt else None
        t0 = dt.now()
        result = processor.process_repair_card(
            tmp_path,
            use_fastgpt=use_fastgpt,
            fastgpt_config=fastgpt_cfg,
            output_dir=session_dir,
            mode=mode,
        )
        elapsed = (dt.now() - t0).total_seconds()

        extracted_fields = result["extracted_fields"]
        fastgpt_enabled = use_fastgpt and bool(fastgpt_cfg and fastgpt_cfg.get('api_key'))
        _log(f'✓ 识别完成，耗时 {elapsed:.1f}s，FastGPT={fastgpt_enabled}，mode={result.get("mode","slow")}，字段: {extracted_fields}')

        fields_list = _field_result(extracted_fields, result["ocr_results"])

        base_name = os.path.splitext(os.path.basename(tmp_path))[0]
        raw_json_path = os.path.join(session_dir, f"{base_name}.json")
        raw_html_path = os.path.join(session_dir, f"{base_name}_table.html")
        xlsx_raw = (result.get("xlsx_path") or "").strip()
        xlsx_exists = bool(xlsx_raw and os.path.exists(xlsx_raw))

        return {
            "success":   True,
            "fields":    fields_list,
            "ocr_count": len(result["ocr_results"]),
            "timestamp": result["timestamp"],
            "raw_exports": {
                "json": raw_json_path if os.path.exists(raw_json_path) else None,
                "html": raw_html_path if os.path.exists(raw_html_path) else None,
                "xlsx": xlsx_raw if xlsx_exists else None,
            },
            "fastgpt_used": fastgpt_enabled,
            "mode":         result.get("mode", "slow"),
        }
    except Exception as e:
        _log(f'✗ 识别失败: {e}')
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _cleanup(tmp_path)


@app.post("/api/ocr/repair-card/batch")
async def ocr_repair_card_batch(
    files: List[UploadFile] = File(...),
    use_fastgpt: bool = Form(False),
    mode: str = Form("slow"),
    api_url: str = Form(""),
    api_key: str = Form(""),
    appid: str = Form(""),
):
    """返修卡批量识别。

    mode: slow|fast - 控制引擎模式
    """
    from datetime import datetime as dt

    if not files:
        raise HTTPException(status_code=400, detail="请至少上传一张图片")
    processor = get_ocr_processor()
    fastgpt_cfg = {"api_url": api_url, "api_key": api_key, "appid": appid} if use_fastgpt else None
    out_list: List[dict] = []
    for uf in files:
        fn = uf.filename or "image"
        tmp_path = _save_upload(uf)
        session_dir = _create_session_dir()
        try:
            result = processor.process_repair_card(
                tmp_path,
                use_fastgpt=use_fastgpt,
                fastgpt_config=fastgpt_cfg,
                output_dir=session_dir,
                mode=mode,
            )
            extracted_fields = result["extracted_fields"]
            fields_list = _field_result(extracted_fields, result["ocr_results"])
            out_list.append({
                "success": True,
                "filename": fn,
                "fields": fields_list,
                "ocr_count": len(result["ocr_results"]),
                "timestamp": result["timestamp"],
                "mode": result.get("mode", "slow"),
                "fastgpt_used": use_fastgpt and bool(fastgpt_cfg and fastgpt_cfg.get("api_key")),
                "error": None,
            })
        except Exception as e:
            traceback.print_exc()
            out_list.append({
                "success": False,
                "filename": fn,
                "fields": [],
                "ocr_count": 0,
                "timestamp": dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                "fastgpt_used": False,
                "error": str(e),
            })
        finally:
            _cleanup(tmp_path)
    return {
        "success": all(x["success"] for x in out_list),
        "mode": mode,
        "count": len(out_list),
        "results": out_list,
    }


@app.post("/api/ocr/material")
async def ocr_material(
    file: UploadFile = File(...),
    doc_type: str = Form("out"),   # "out" 出库单 | "in" 入库单
):
    """
    航材出入库单 OCR 识别。
    返回：{ success, fields, ocr_count, timestamp }
    """
    tmp_path = _save_upload(file)
    session_dir = _create_session_dir()
    try:
        processor = get_ocr_processor()
        ocr_results = processor.ocr_recognize(tmp_path, output_dir=session_dir)

        if doc_type == "out":
            TARGET = ['出库单号', '航材名称', '航材型号', '数量', '出库日期', '经手人', '领用单位', '备注']
        else:
            TARGET = ['入库单号', '航材名称', '航材型号', '数量', '入库日期', '经手人', '供应商', '备注']

        fields: dict[str, str] = {f: "" for f in TARGET}
        for item in ocr_results:
            text = item["text"]
            for f in TARGET:
                if not fields[f] and f in text:
                    val = text.replace(f, "").replace("：", "").replace(":", "").strip()
                    if val:
                        fields[f] = val

        fields_list = _field_result(fields, ocr_results)
        return {
            "success":   True,
            "fields":    fields_list,
            "ocr_count": len(ocr_results),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _cleanup(tmp_path)


@app.post("/api/ocr/general")
async def ocr_general(
    file: UploadFile = File(...),
    mode: str = Form("doc"),            # "doc" 文档识别 | "table" 表格识别
    export_format: str = Form("none"),  # "none" | "excel" | "csv" | "markdown" | "all"
):
    """
    通用 OCR 识别。
    - doc 模式：返回全文文本行列表
    - table 模式：尝试结构化表格，返回行列 cells，支持 export_format 导出
    返回：{ success, fields, raw_text, table_html, ocr_count, exports, timestamp }
    """
    tmp_path = _save_upload(file)
    # 创建独立会话目录，存放本次识别的所有文件
    session_dir = _create_session_dir()
    try:
        from ocr_core import OCRPipeline, OCRTask, TableDetector, TableExporter

        # 统一流水线：一次调用获取 OCR 结果 + 表格结构
        pipeline_result = OCRPipeline.process(
            tmp_path,
            task_type=OCRTask.TABLE if mode == "table" else OCRTask.GENERAL,
            output_dir=session_dir,
        )
        ocr_results = pipeline_result.get("ocr_results", [])
        table_data = pipeline_result.get("table", {})

        raw_text = " | ".join(item["text"] for item in ocr_results)
        summary = f"已识别 {len(ocr_results)} 个文本块，共 {len(raw_text)} 字符。"

        table_html = ""
        exports: dict = {}
        cells = table_data.get("cells", [])
        num_rows = table_data.get("num_rows", 0)
        num_cols = table_data.get("num_cols", 0)
        if mode == "table" and cells:
            table_html = table_data.get("html", "")

            fields_list = [
                {
                    "key":        f"r{c['row']}c{c['col']}",
                    "field":      f"第{c['row']+1}行 第{c['col']+1}列",
                    "value":      c["text"],
                    "confidence": c.get("confidence", 1.0),
                }
                for c in cells
            ]

            if cells and num_rows > 0 and num_cols > 0:
                summary = f"已识别表格结构，共 {num_rows} 行 × {num_cols} 列，{len(cells)} 个单元格。"
            elif ocr_results:
                summary = f"已识别 {len(ocr_results)} 个文本块，但无法形成有效表格结构。"
            else:
                summary = "未检测到任何内容。"

            # ── 多格式导出 ──────────────────────────────────────────────────
            if export_format != "none" and cells:
                grid = TableDetector._cells_to_grid(cells, num_rows, num_cols)
                base = os.path.join(session_dir, f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
                if export_format == "all":
                    exports = TableExporter.export_all(grid, base)
                elif export_format == "excel":
                    exports["excel"] = TableExporter.to_excel(grid, base + ".xlsx")
                elif export_format == "csv":
                    exports["csv"] = TableExporter.to_csv(grid, base + ".csv")
                elif export_format == "markdown":
                    exports["markdown"] = TableExporter.to_markdown(grid, base + ".md")
                elif export_format == "html":
                    exports["html"] = TableExporter.to_html(grid, base + ".html")
                elif export_format == "json":
                    exports["json"] = TableExporter.to_json(grid, base + ".json")
        else:
            # 文档模式：每行文本作为一个字段
            fields_list = [
                {
                    "key":        str(i),
                    "field":      f"第 {i+1} 行",
                    "value":      item["text"],
                    "confidence": item["confidence"],
                }
                for i, item in enumerate(ocr_results)
            ]

        return {
            "success":    True,
            "fields":     fields_list,
            "raw_text":   summary,
            "table_html": table_html,
            "ocr_count":  len(ocr_results),
            "cells":      cells,
            "num_rows":   num_rows,
            "num_cols":   num_cols,
            "exports":    exports,
            "timestamp":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _cleanup(tmp_path)


@app.post("/api/ocr/export-format")
async def ocr_export_format(
    cells:   str = Form(""),
    num_rows: int = Form(0),
    num_cols: int = Form(0),
    fmt:      str = Form("excel"),
):
    """
    专用导出接口：接收前端缓存的识别结果（cells），只做格式转换，不执行 OCR。
    用于已识别过的表格，直接导出多格式文件，避免重复识别。

    参数:
        cells   - JSON 字符串化的 cells 列表
        num_rows- 表格行数
        num_cols- 表格列数
        fmt     - excel|csv|markdown|html|json|all

    返回: { success, exports: {fmt: file_path}, timestamp }
    """
    # 创建独立会话目录
    session_dir = _create_session_dir()
    try:
        from ocr_core import TableDetector, TableExporter

        if not cells or num_rows <= 0 or num_cols <= 0:
            raise HTTPException(status_code=400, detail="cells 或行列数参数无效")

        cells_list: List[Dict] = json.loads(cells)
        grid = TableDetector._cells_to_grid(cells_list, num_rows, num_cols)
        if not grid:
            raise HTTPException(status_code=400, detail="无法从 cells 构建表格网格")

        base = os.path.join(session_dir, f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

        exports: Dict[str, str] = {}
        if fmt == "all":
            exports = TableExporter.export_all(grid, base)
        elif fmt == "excel":
            exports["excel"] = TableExporter.to_excel(grid, base + ".xlsx")
        elif fmt == "csv":
            exports["csv"] = TableExporter.to_csv(grid, base + ".csv")
        elif fmt == "markdown":
            exports["markdown"] = TableExporter.to_markdown(grid, base + ".md")
        elif fmt == "html":
            exports["html"] = TableExporter.to_html(grid, base + ".html")
        elif fmt == "json":
            exports["json"] = TableExporter.to_json(grid, base + ".json")
        else:
            raise HTTPException(status_code=400, detail=f"不支持的导出格式: {fmt}")

        return {
            "success":   True,
            "exports":   exports,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ocr/table-structure")
async def ocr_table_structure(
    file: UploadFile = File(...),
):
    """
    PP-Structure 表格识别接口。
    使用专用表格结构分析引擎，返回 HTML 表格 + 单元格列表。
    返回：{ success, table_html, cells, num_rows, num_cols, ocr_count, timestamp }
    """
    tmp_path = _save_upload(file)
    session_dir = _create_session_dir()
    try:
        from ocr_core import run_pp_structure
        result = run_pp_structure(tmp_path, output_dir=session_dir)
        return {
            "success":    True,
            "table_html": result.get("html", ""),
            "cells":      result.get("cells", []),
            "num_rows":   result.get("num_rows", 0),
            "num_cols":   result.get("num_cols", 0),
            "ocr_count":  result.get("ocr_count", 0),
            "timestamp":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _cleanup(tmp_path)


# ─── 入口 ─────────────────────────────────────────────────────────────────────
@app.get("/api/export/download")
async def export_download(filename: str):
    """
    通用文件下载接口。
    用于下载 OCR 识别结果导出的文件（Excel、HTML、JSON 等）。

    参数: filename - 需要下载的文件名（不含路径）

    返回: 文件流
    """
    from fastapi.responses import FileResponse

    # 获取 output 目录
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

    # 禁止路径遍历
    safe_name = os.path.basename(filename)
    file_path = os.path.join(output_dir, safe_name)

    # 先尝试直接路径
    if os.path.exists(file_path):
        pass  # 找到文件
    else:
        # 尝试在 output 的子目录（session_*）中查找
        found = False
        if os.path.exists(output_dir):
            for entry in os.listdir(output_dir):
                sub_dir = os.path.join(output_dir, entry)
                if os.path.isdir(sub_dir) and entry.startswith('session_'):
                    candidate = os.path.join(sub_dir, safe_name)
                    if os.path.exists(candidate):
                        file_path = candidate
                        found = True
                        break
        if not found:
            raise HTTPException(status_code=404, detail=f"文件不存在: {safe_name}")

    # 根据扩展名设置媒体类型
    import mimetypes
    media_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"

    try:
        return FileResponse(
            path=file_path,
            filename=safe_name,
            media_type=media_type,
        )
    except RuntimeError:
        raise HTTPException(status_code=404, detail=f"文件不存在或已被清理: {safe_name}")


@app.get("/api/export/list")
async def export_list():
    """
    列出 output 目录下可下载的导出文件。
    返回: { files: [{name, size, modified}] }
    """
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    os.makedirs(output_dir, exist_ok=True)
    
    files = []
    if os.path.exists(output_dir):
        for f in sorted(os.listdir(output_dir), key=lambda x: -os.path.getmtime(os.path.join(output_dir, x))):
            full_path = os.path.join(output_dir, f)
            if os.path.isfile(full_path):
                stat = os.stat(full_path)
                files.append({
                    "name": f,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                })
    
    return {"files": files}


if __name__ == "__main__":
    import uvicorn
    # 8000 常被其它程序占用（Errno 10048）；默认 8001，可用环境变量 OCR_CHAIN_PORT 覆盖
    port = int(os.environ.get("OCR_CHAIN_PORT", "8001"))
    print(f"[OCR·CHAIN] 启动后端服务 http://localhost:{port}")
    print(f"[OCR·CHAIN] API 文档：http://localhost:{port}/docs")
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
