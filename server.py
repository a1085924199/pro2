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
  POST /api/ocr/inspection-report - 检验报告单识别
  POST /api/ocr/maintenance-record- 维修记录单识别
  POST /api/ocr/quotation         - 报价单识别
  POST /api/ocr/table-structure   - PP-Structure 表格识别
  POST /api/ocr/table-advanced    - 三阶段线检测表格识别
  GET  /api/health                - 健康检查
  GET  /api/config/fastgpt        - 读取 FastGPT 配置
  POST /api/config/fastgpt        - 保存 FastGPT 配置
"""
import os
import json
import shutil
import tempfile
import traceback
from datetime import datetime
from typing import Optional

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
            print("[OCR·CHAIN] 正在预加载 PPStructureV3 主引擎，请稍候...")
            from ocr_core import v3_pool
            v3_pool.warmup()
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

STEP_KEYS = ["repair_order_ocr", "repair_card_ocr", "ids_match", "quote_generation"]

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

    返回：{ success, task, fields, raw_text, table_html,
             ocr_count, table_regions, summary, exports, timestamp }
    """
    tmp_path = _save_upload(file)
    try:
        from ocr_core import OCRPipeline
        fastgpt_cfg = (
            {"api_url": api_url, "api_key": api_key, "appid": appid}
            if use_fastgpt else None
        )
        result = OCRPipeline.run(
            tmp_path,
            task=task,
            use_fastgpt=use_fastgpt,
            fastgpt_config=fastgpt_cfg,
            doc_type=doc_type,
        )

        # 字段列表格式化
        fields_list = _field_result(
            result.get("extracted_fields", {}),
            result.get("ocr_results", [])
        )

        # 可选导出
        exports: dict = {}
        table = result.get("table")
        if export_format != "none" and table:
            from ocr_core import TableExporter, TableDetector
            cells = table.get("cells", [])
            nr = table.get("num_rows", 0)
            nc = table.get("num_cols", 0)
            grid = TableDetector._cells_to_grid(cells, nr, nc) if cells else []
            if grid:
                import tempfile
                base = tempfile.mktemp(prefix="ocr_export_")
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
            "timestamp":     result.get("timestamp",
                                datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _cleanup(tmp_path)


@app.post("/api/ocr/repair-order")
async def ocr_repair_order(
    file: UploadFile = File(...),
    use_fastgpt: bool = Form(False),
    api_url:  str = Form(""),
    api_key:  str = Form(""),
    appid:    str = Form(""),
):
    """
    调修单 OCR 识别。
    返回：{ success, fields: [{key,field,value,confidence}], ocr_count, timestamp }
    """
    tmp_path = _save_upload(file)
    try:
        processor = get_ocr_processor()
        fastgpt_cfg = {"api_url": api_url, "api_key": api_key, "appid": appid} if use_fastgpt else None
        result = processor.process_image(tmp_path, use_fastgpt=use_fastgpt, fastgpt_config=fastgpt_cfg)

        fields_list = _field_result(result["extracted_fields"], result["ocr_results"])
        return {
            "success":   True,
            "fields":    fields_list,
            "ocr_count": len(result["ocr_results"]),
            "timestamp": result["timestamp"],
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _cleanup(tmp_path)


@app.post("/api/ocr/repair-card")
async def ocr_repair_card(
    file: UploadFile = File(...),
    use_fastgpt: bool = Form(False),
    api_url:  str = Form(""),
    api_key:  str = Form(""),
    appid:    str = Form(""),
):
    """
    返修卡 OCR 识别（通用 OCR，提取所有文本行）。
    返回：{ success, fields: [{key,field,value,confidence}], ocr_count, timestamp }
    """
    tmp_path = _save_upload(file)
    try:
        processor = get_ocr_processor()
        ocr_results = processor.ocr_recognize(tmp_path)

        # 返修卡字段关键词匹配
        CARD_FIELDS = ['返修单号', '故障描述', '送修单位', '返修日期', '技术状态']
        fields: dict[str, str] = {f: "" for f in CARD_FIELDS}

        for item in ocr_results:
            text = item["text"]
            for f in CARD_FIELDS:
                if not fields[f] and f in text:
                    # 取同行其余内容作为值
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
    try:
        processor = get_ocr_processor()
        ocr_results = processor.ocr_recognize(tmp_path)

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
    try:
        processor = get_ocr_processor()
        ocr_results = processor.ocr_recognize(tmp_path)

        raw_text = " | ".join(item["text"] for item in ocr_results)
        summary = f"已识别 {len(ocr_results)} 个文本块，共 {len(raw_text)} 字符。"

        table_html = ""
        exports: dict = {}
        if mode == "table":
            from ocr_core import _build_table_from_textboxes, TableExporter, TableDetector
            table = _build_table_from_textboxes(ocr_results)
            cells = table.get("cells", []) if table else []
            table_html = table.get("html", "") if table else ""
            num_rows = table.get("num_rows", 0) if table else 0
            num_cols = table.get("num_cols", 0) if table else 0
            
            # 若纯 OCR 结构化无效，尝试三阶段线检测
            if not cells or num_rows == 0 or num_cols == 0:
                try:
                    print("[OCRPipeline] 纯 OCR 结构化失败，尝试三阶段线检测...")
                    det_result = TableDetector.process(tmp_path)
                    if det_result and det_result.get("num_rows", 0) > 0 and det_result.get("num_cols", 0) > 0:
                        table = det_result
                        cells = det_result.get("cells", [])
                        table_html = det_result.get("html", "")
                        num_rows = det_result.get("num_rows", 0)
                        num_cols = det_result.get("num_cols", 0)
                        print("[OCRPipeline] 三阶段线检测成功")
                except Exception as e:
                    print(f"[OCRPipeline] 三阶段线检测失败: {e}")
            
            fields_list = [
                {
                    "key":        f"r{c['row']}c{c['col']}",
                    "field":      f"第{c['row']+1}行 第{c['col']+1}列",
                    "value":      c["text"],
                    "confidence": c["confidence"],
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
            if export_format != "none" and table and cells:
                import tempfile
                grid = TableDetector._cells_to_grid(cells, num_rows, num_cols)
                base = tempfile.mktemp(prefix="ocr_general_")
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
            "exports":    exports,
            "timestamp":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _cleanup(tmp_path)


@app.post("/api/ocr/inspection-report")
async def ocr_inspection_report(
    file: UploadFile = File(...),
    use_fastgpt: bool = Form(False),
    api_url:  str = Form(""),
    api_key:  str = Form(""),
    appid:    str = Form(""),
):
    """
    检验报告单 OCR 识别。
    返回：{ success, fields: [{key,field,value,confidence}], ocr_count, timestamp }
    """
    tmp_path = _save_upload(file)
    try:
        from ocr_core import InspectionReportParser
        parser = InspectionReportParser()
        fastgpt_cfg = {"api_url": api_url, "api_key": api_key, "appid": appid} if use_fastgpt else None
        result = parser.parse(tmp_path, use_fastgpt=use_fastgpt, fastgpt_config=fastgpt_cfg)
        fields_list = _field_result(result["extracted_fields"], result["ocr_results"])
        return {
            "success":   True,
            "fields":    fields_list,
            "ocr_count": len(result["ocr_results"]),
            "timestamp": result["timestamp"],
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _cleanup(tmp_path)


@app.post("/api/ocr/maintenance-record")
async def ocr_maintenance_record(
    file: UploadFile = File(...),
    use_fastgpt: bool = Form(False),
    api_url:  str = Form(""),
    api_key:  str = Form(""),
    appid:    str = Form(""),
):
    """
    维修记录单 OCR 识别。
    返回：{ success, fields: [{key,field,value,confidence}], ocr_count, timestamp }
    """
    tmp_path = _save_upload(file)
    try:
        from ocr_core import MaintenanceRecordParser
        parser = MaintenanceRecordParser()
        fastgpt_cfg = {"api_url": api_url, "api_key": api_key, "appid": appid} if use_fastgpt else None
        result = parser.parse(tmp_path, use_fastgpt=use_fastgpt, fastgpt_config=fastgpt_cfg)
        fields_list = _field_result(result["extracted_fields"], result["ocr_results"])
        return {
            "success":   True,
            "fields":    fields_list,
            "ocr_count": len(result["ocr_results"]),
            "timestamp": result["timestamp"],
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _cleanup(tmp_path)


@app.post("/api/ocr/quotation")
async def ocr_quotation(
    file: UploadFile = File(...),
    use_fastgpt: bool = Form(False),
    api_url:  str = Form(""),
    api_key:  str = Form(""),
    appid:    str = Form(""),
):
    """
    报价单 OCR 识别。
    返回：{ success, fields: [{key,field,value,confidence}], ocr_count, timestamp }
    """
    tmp_path = _save_upload(file)
    try:
        from ocr_core import QuotationParser
        parser = QuotationParser()
        fastgpt_cfg = {"api_url": api_url, "api_key": api_key, "appid": appid} if use_fastgpt else None
        result = parser.parse(tmp_path, use_fastgpt=use_fastgpt, fastgpt_config=fastgpt_cfg)
        fields_list = _field_result(result["extracted_fields"], result["ocr_results"])
        return {
            "success":   True,
            "fields":    fields_list,
            "ocr_count": len(result["ocr_results"]),
            "timestamp": result["timestamp"],
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _cleanup(tmp_path)


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
    try:
        from ocr_core import run_pp_structure
        result = run_pp_structure(tmp_path)
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


@app.post("/api/ocr/table-advanced")
async def ocr_table_advanced(
    file: UploadFile = File(...),
    export_format: str = Form("none"),  # "none" | "excel" | "csv" | "markdown" | "all"
):
    """
    三阶段表格识别接口（线检测 → TSR → 单元格重建）。

    - Stage 1：HoughLinesP 检测横纵线
    - Stage 2：交点矩阵构建逻辑单元格坐标
    - Stage 3：逐单元格 ROI 送入 OCR，语义对齐归并

    export_format 参数控制是否同时导出文件：
      none     - 仅返回 JSON
      excel    - 额外导出 .xlsx
      csv      - 额外导出 .csv
      markdown - 额外导出 .md
      all      - 导出三种格式

    返回：{ success, table_html, cells, grid, num_rows, num_cols,
             source, debug, exports, timestamp }
    """
    tmp_path = _save_upload(file)
    try:
        from ocr_core import TableDetector, TableExporter
        result = TableDetector.process(tmp_path)

        exports: dict = {}
        grid = result.get("grid", [])
        if export_format != "none" and grid:
            import tempfile, os as _os
            base = tempfile.mktemp(prefix="table_export_")
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

        return {
            "success":    True,
            "table_html": result.get("html", ""),
            "cells":      result.get("cells", []),
            "grid":       grid,
            "num_rows":   result.get("num_rows", 0),
            "num_cols":   result.get("num_cols", 0),
            "source":     result.get("source", ""),
            "debug":      result.get("debug", {}),
            "exports":    exports,
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
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"文件不存在: {safe_name}")
    
    # 根据扩展名设置媒体类型
    import mimetypes
    media_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    
    return FileResponse(
        path=file_path,
        filename=safe_name,
        media_type=media_type,
    )


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
    port = 8001
    print(f"[OCR·CHAIN] 启动后端服务 http://localhost:{port}")
    print(f"[OCR·CHAIN] API 文档：http://localhost:{port}/docs")
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
