#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试性能优化效果
"""
import time
import sys
import os

# 添加当前目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ocr_core import v3_pool, preprocess_image

def test_model_warmup():
    """测试模型预热效果"""
    print("=== 测试模型预热 ===")
    start_time = time.time()
    
    # 预热模型
    v3_pool.warmup()
    
    # 等待预热完成
    time.sleep(2)
    
    # 再次获取引擎，测试初始化时间
    start_init = time.time()
    engine = v3_pool.get()
    end_init = time.time()
    
    print(f"模型初始化时间: {end_init - start_init:.2f} 秒")
    print(f"模型预热状态: {'已完成' if v3_pool.warmup_done else '未完成'}")
    print(f"总耗时: {end_init - start_time:.2f} 秒")
    print()

def test_image_processing():
    """测试图像处理效果"""
    print("=== 测试图像处理 ===")
    test_image = "test_table.png"
    
    if not os.path.exists(test_image):
        print(f"测试图像不存在: {test_image}")
        return
    
    start_time = time.time()
    img = preprocess_image(test_image)
    end_time = time.time()
    
    print(f"图像处理时间: {end_time - start_time:.2f} 秒")
    print(f"图像尺寸: {img.shape[1]}x{img.shape[0]}")
    print()

def main():
    """主函数"""
    print("开始性能测试...")
    print()
    
    test_model_warmup()
    test_image_processing()
    
    print("性能测试完成!")

if __name__ == "__main__":
    main()
