#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试PPStructureV3表格识别功能
"""
import os 
import sys 
from pathlib import Path 
from paddleocr import PPStructureV3 
  
def main(image_path=None): 
    # ====== 配置参数 ====== 
    if image_path is None:
        image_path = "4.jpg"  # 默认图片路径
    output_dir = "output" 
  
    # 检查输入文件是否存在 
    if not os.path.exists(image_path): 
        print(f"[ERROR] 错误：图片文件不存在: {os.path.abspath(image_path)}") 
        sys.exit(1) 
  
    # 创建输出目录 
    Path(output_dir).mkdir(parents=True, exist_ok=True) 
  
    try: 
        # ====== 初始化 PP-StructureV3 ====== 
        print("[INFO] 正在初始化 PP-StructureV3（启用 CPU + 表格识别）...") 
        pipeline = PPStructureV3( 
            device="cpu", 
            use_seal_recognition=False,     # 不需要印章识别
            use_table_recognition=True,     # 启用表格识别
            use_formula_recognition=False,  # 可按需关闭以提速 
            use_doc_orientation_classify=False, 
        ) 
  
        # ====== 执行推理 ====== 
        print("[INFO] 正在进行结构化识别（含表格）...") 
        results = pipeline.predict(input=image_path) 
  
        if not results: 
            print("[WARN] 识别完成，但未返回任何结果。") 
            return 
  
        # ====== 保存结果 ====== 
        base_name = Path(image_path).stem 
        json_path = os.path.join(output_dir, f"{base_name}.json") 
        md_path = os.path.join(output_dir, f"{base_name}.md") 
        html_path = os.path.join(output_dir, f"{base_name}_table.html")
        xlsx_path = os.path.join(output_dir, f"{base_name}_table.xlsx")
  
        # 保存结果
        for res in results: 
            # 保存完整结果
            res.save_to_json(save_path=json_path) 
            res.save_to_markdown(save_path=md_path)
            
            # 保存表格为 HTML
            try:
                res.save_to_html(save_path=html_path)
                print(f"[INFO] 表格已保存为 HTML: {html_path}")
            except Exception as e:
                print(f"[WARN] 保存 HTML 表格失败: {e}")
            
            # 保存表格为 XLSX
            try:
                res.save_to_xlsx(save_path=xlsx_path)
                print(f"[INFO] 表格已保存为 XLSX: {xlsx_path}")
            except Exception as e:
                print(f"[WARN] 保存 XLSX 表格失败: {e}")
  
        print(f"[SUCCESS] 识别完成！结果已保存至：{os.path.abspath(output_dir)}") 
        print("[INFO] 生成的文件：")
        print(f"  - {base_name}.json (完整识别结果)")
        print(f"  - {base_name}.md (完整Markdown结果)")
        print(f"  - {base_name}_table.html (表格HTML)")
        print(f"  - {base_name}_table.xlsx (表格Excel)")
  
    except Exception as e: 
        print(f"[ERROR] 发生异常: {e}") 
        import traceback 
        traceback.print_exc() 


if __name__ == "__main__": 
    # 如果命令行提供了参数，使用第一个参数作为图片路径
    if len(sys.argv) > 1:
        main(sys.argv[1])
    else:
        main()