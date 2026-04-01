#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
create_test_image.py - 创建测试表格图像
"""
import cv2
import numpy as np

# 创建测试图像
img = np.ones((500, 700, 3), dtype=np.uint8) * 255

# 添加标题
cv2.putText(img, '测试表格', (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 2)

# 绘制表格
cv2.rectangle(img, (50, 100), (650, 450), (0, 0, 0), 2)

# 绘制水平线
for i in range(5):
    y = 100 + i * 70
    cv2.line(img, (50, y), (650, y), (0, 0, 0), 1)

# 绘制垂直线
for i in range(4):
    x = 50 + i * 200
    cv2.line(img, (x, 100), (x, 450), (0, 0, 0), 1)

# 添加表头
headers = ['姓名', '年龄', '职业']
for i, header in enumerate(headers):
    x = 150 + i * 200
    cv2.putText(img, header, (x-30, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 1)

# 添加数据
rows = [
    ['张三', '25', '工程师'],
    ['李四', '30', '教师'],
    ['王五', '35', '医生']
]

for row_idx, row in enumerate(rows):
    for col_idx, cell in enumerate(row):
        x = 150 + col_idx * 200
        y = 210 + row_idx * 70
        cv2.putText(img, cell, (x-30, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 1)

# 保存图像
test_image_path = 'test_table.png'
cv2.imwrite(test_image_path, img)
print(f'已创建测试图像: {test_image_path}')
print('图像尺寸:', img.shape)
