#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
repair.py - 程序入口 v3.0
调修单OCR识别系统

运行方式：
  Web模式（默认）:  python repair.py
                    启动 FastAPI 后端服务 http://localhost:1128
                    前端独立运行：cd web-ui && npm run dev

  CLI模式:          python repair.py --cli --image <图片路径>
"""
import sys
import os
import argparse
from datetime import datetime

# 离线模式：禁用 PaddleX 联网检查
os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')


def run_server(host: str = "0.0.0.0", port: int = 1129, reload: bool = False):
    """启动 FastAPI 后端服务"""
    try:
        import uvicorn
    except ImportError:
        print("错误: 请先安装 uvicorn：pip install uvicorn[standard]")
        sys.exit(1)

    # exe 环境下获取前端是否内置
    bundled = not (getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'))

    print("=" * 55)
    print("  智·链 OCR 平台 后端服务")
    print(f"  后端接口：http://localhost:{port}")
    print(f"  API文档：http://localhost:{port}/docs")
    if bundled:
        print(f"  前端地址：http://localhost:{port}/web-ui")
    else:
        print("  前端独立运行：cd web-ui && npm run dev")
        print("  前端地址：http://localhost:5173")
    print("=" * 55)

    uvicorn.run(
        "server:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


def run_cli(image_path, use_fastgpt=False, api_url="", api_key="", appid=""):
    """命令行单张图片处理"""
    from ocr_core import RepairOrderOCR

    if not os.path.exists(image_path):
        print(f"错误: 图片不存在: {image_path}")
        return

    print(f"处理图片: {image_path}")
    processor = RepairOrderOCR()
    fastgpt_cfg = {"api_url": api_url, "api_key": api_key, "appid": appid} if use_fastgpt else None
    result = processor.process_image(image_path, use_fastgpt=use_fastgpt, fastgpt_config=fastgpt_cfg)

    print("\n" + "=" * 50)
    print("识别结果:")
    print("=" * 50)
    for k, v in result["extracted_fields"].items():
        print(f"  {k}: {v}")

    print(f"\nOCR识别文本 ({len(result['ocr_results'])} 条):")
    for i, item in enumerate(result["ocr_results"], 1):
        print(f"  {i:3d}. {item['text']}  ({item['confidence']:.2%})")

    import json
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = f"{os.path.splitext(os.path.basename(image_path))[0]}_{ts}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {out_path}")


def main():
    parser = argparse.ArgumentParser(description="智·链 OCR 平台 v3.0")
    parser.add_argument("--cli",      action="store_true", help="命令行模式（单张图片处理）")
    parser.add_argument("--image",    type=str,            help="图片路径（CLI模式）")
    parser.add_argument("--fastgpt",  action="store_true", help="启用FastGPT解析")
    parser.add_argument("--api-url",  type=str, default="", help="FastGPT API地址")
    parser.add_argument("--api-key",  type=str, default="", help="FastGPT API密钥")
    parser.add_argument("--appid",    type=str, default="", help="FastGPT 应用ID")
    parser.add_argument("--host",     type=str, default="0.0.0.0", help="服务监听地址")
    parser.add_argument("--port",     type=int, default=1128,      help="服务监听端口")
    parser.add_argument("--reload",   action="store_true", help="开启热重载（开发模式）")
    args = parser.parse_args()

    if args.cli:
        if not args.image:
            print("错误: CLI模式需要 --image 参数")
            parser.print_help()
            return
        run_cli(args.image, args.fastgpt, args.api_url, args.api_key, args.appid)
    else:
        run_server(host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
