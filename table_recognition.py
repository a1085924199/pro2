#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
table_recognition.py - 通用表格识别脚本

功能：
1. 通用表格识别（使用 OCRPipeline）
2. 原表预览（利用 result['html']）
3. Excel 导出（利用 TableExporter）
"""
import os
import sys
import tempfile
from pathlib import Path

# 离线模式，禁用联网检查
os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')

from ocr_core import OCRPipeline, TableExporter, TableDetector


def main():
    """主函数"""
    if len(sys.argv) != 2:
        print(f"用法: {sys.argv[0]} <图像路径>")
        sys.exit(1)
    
    image_path = sys.argv[1]
    if not os.path.exists(image_path):
        print(f"错误：图像文件不存在: {image_path}")
        sys.exit(1)
    
    print(f"处理图像: {image_path}")
    
    # 步骤1：使用 OCRPipeline 进行表格识别
    print("\n1. 正在进行表格识别...")
    try:
        result = OCRPipeline.run(image_path, task='table')
        
        if not result.get('success', False):
            print("错误：表格识别失败")
            sys.exit(1)
        
        print(f"识别成功: {result['summary']}")
        
        # 步骤2：获取原表预览 HTML
        table_html = result.get('html', '')
        if table_html:
            print("\n2. 原表预览 HTML 已生成")
            # 保存预览 HTML 文件
            preview_path = f"{Path(image_path).stem}_preview.html"
            with open(preview_path, 'w', encoding='utf-8') as f:
                f.write(table_html)
            print(f"   预览文件已保存至: {preview_path}")
        else:
            print("\n2. 警告：未生成表格预览 HTML")
        
        # 步骤3：Excel 导出
        table = result.get('table')
        if table:
            print("\n3. 正在导出 Excel 文件...")
            cells = table.get('cells', [])
            num_rows = table.get('num_rows', 0)
            num_cols = table.get('num_cols', 0)
            
            if cells and num_rows > 0 and num_cols > 0:
                # 将 cells 转换为 grid 格式
                grid = TableDetector._cells_to_grid(cells, num_rows, num_cols)
                
                if grid:
                    # 生成临时文件名
                    base = tempfile.mktemp(prefix="table_export_")
                    excel_path = f"{Path(image_path).stem}_table.xlsx"
                    
                    # 导出 Excel
                    try:
                        export_path = TableExporter.to_excel(grid, excel_path)
                        print(f"   Excel 文件已保存至: {export_path}")
                    except Exception as e:
                        print(f"   Excel 导出失败: {e}")
                else:
                    print("   无法生成表格网格数据")
            else:
                print("   表格数据为空")
        else:
            print("\n3. 警告：未找到表格数据，无法导出 Excel")
        
        # 步骤4：显示识别结果摘要
        print("\n4. 识别结果摘要:")
        print(f"   任务类型: {result.get('task', 'table')}")
        print(f"   图像名称: {result.get('image_name', '')}")
        print(f"   识别文本块: {len(result.get('ocr_results', []))}")
        print(f"   表格区域: {len(result.get('table_regions', []))}")
        print(f"   表格大小: {table.get('num_rows', 0)} 行 × {table.get('num_cols', 0)} 列")
        print(f"   处理时间: {result.get('timestamp', '')}")
        
    except Exception as e:
        print(f"错误：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
