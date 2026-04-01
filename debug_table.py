#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
debug_table.py - 表格识别调试脚本
"""
import os
import sys
from ocr_core import OCRPipeline, _parse_html_cells

# 离线模式，禁用联网检查
os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')


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
    
    # 使用 OCRPipeline 进行表格识别
    print("\n1. 正在进行表格识别...")
    try:
        result = OCRPipeline.run(image_path, task='table')
        
        if not result.get('success', False):
            print("错误：表格识别失败")
            sys.exit(1)
        
        print(f"识别成功: {result['summary']}")
        
        # 检查表格数据
        table = result.get('table')
        if table:
            print("\n2. 表格数据:")
            print(f"   行数: {table.get('num_rows', 0)}")
            print(f"   列数: {table.get('num_cols', 0)}")
            print(f"   单元格数: {len(table.get('cells', []))}")
            
            # 检查单元格数据
            cells = table.get('cells', [])
            if cells:
                print("\n3. 前5个单元格:")
                for i, cell in enumerate(cells[:5]):
                    print(f"   单元格 {i+1}: row={cell.get('row')}, col={cell.get('col')}, text={cell.get('text')[:20]}")
            
            # 检查HTML
            html = table.get('html', '')
            if html:
                print("\n4. HTML预览:")
                print(f"   HTML长度: {len(html)}")
                print(f"   前200字符: {html[:200]}...")
                
                # 测试_parse_html_cells函数
                print("\n5. 测试_parse_html_cells函数:")
                parsed_cells = _parse_html_cells(html)
                print(f"   解析出的单元格数: {len(parsed_cells)}")
                if parsed_cells:
                    print("   前5个解析的单元格:")
                    for i, cell in enumerate(parsed_cells[:5]):
                        print(f"   单元格 {i+1}: row={cell.get('row')}, col={cell.get('col')}, text={cell.get('text')[:20]}")
                    
                    # 计算行数和列数
                    if parsed_cells:
                        max_row = max((c.get('row', 0) for c in parsed_cells), default=0)
                        max_col = max((c.get('col', 0) for c in parsed_cells), default=0)
                        print(f"   计算的行数: {max_row + 1}")
                        print(f"   计算的列数: {max_col + 1}")
        
        # 检查table_regions
        table_regions = result.get('table_regions', [])
        if table_regions:
            print("\n6. 表格区域:")
            for i, region in enumerate(table_regions):
                print(f"   区域 {i+1}:")
                print(f"      单元格数: {len(region.get('cells', []))}")
                print(f"      HTML长度: {len(region.get('html', ''))}")
                
    except Exception as e:
        print(f"错误：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
