
"""
PaddleOCR 识别测试 Demo
使用 PaddleOCR 完整 API（包含检测+识别）
"""
import os
import time

from paddleocr import PaddleOCR


def main():
    # 使用 PaddleOCR（包含检测+识别）
    ocr = PaddleOCR(lang='ch', enable_mkldnn=True, cpu_threads=12)
    print(f"\n[2] 正在识别图片...")
    t1 = time.time()

    # 执行检测+识别
    results = ocr.predict("001.png")

    t2 = time.time()
    print(f"识别耗时: {t2 - t1:.2f}s")

    print(results)


if __name__ == "__main__":
    main()