#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试_parse_html_cells函数的修复效果
"""
import sys
import os

# 添加当前目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ocr_core import _parse_html_cells

def test_html_cells():
    """测试_parse_html_cells函数"""
    # 测试用例1：正常的HTML表格
    html1 = '''
    <table>
        <tr><td>Cell 1</td><td>Cell 2</td></tr>
        <tr><td>Cell 3</td><td>Cell 4</td></tr>
    </table>
    '''
    
    # 测试用例2：只有<td>标签的HTML
    html2 = '''
    <td>Cell 1</td><td>Cell 2</td><td>Cell 3</td><td>Cell 4</td><td>Cell 5</td><td>Cell 6</td>
    '''
    
    # 测试用例3：单个<td>标签
    html3 = '''
    <td>Single Cell</td>
    '''
    
    # 测试用例4：带有colspan的表格
    html4 = '''
    <table>
        <tr><td colspan="2">Cell 1</td><td>Cell 2</td></tr>
        <tr><td>Cell 3</td><td>Cell 4</td><td>Cell 5</td></tr>
    </table>
    '''
    
    test_cases = [
        (html1, "正常的HTML表格"),
        (html2, "只有<td>标签的HTML"),
        (html3, "单个<td>标签"),
        (html4, "带有colspan的表格"),
    ]
    
    for html, description in test_cases:
        print(f"\n测试: {description}")
        cells = _parse_html_cells(html)
        print(f"单元格数量: {len(cells)}")
        
        if cells:
            max_row = max(c['row'] for c in cells)
            max_col = max(c['col'] for c in cells)
            num_rows = max_row + 1
            num_cols = max_col + 1
            print(f"表格大小: {num_rows} 行 × {num_cols} 列")
            
            # 打印每个单元格的信息
            for i, cell in enumerate(cells):
                print(f"单元格 {i+1}: 行={cell['row']}, 列={cell['col']}, 内容='{cell['text']}'")
        else:
            print("没有识别到单元格")

if __name__ == "__main__":
    test_html_cells()
