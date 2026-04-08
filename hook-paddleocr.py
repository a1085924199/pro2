# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 钩子文件 - PaddleOCR 3.x / PaddleX 3.x
"""
import os, site
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_all

SITE_PKGS = site.getsitepackages()[0] if site.getsitepackages() else r'E:\Anaconda_envs\envs\pro2\Lib\site-packages'

# ==================== PaddleOCR 3.x ====================
datas = collect_data_files('paddleocr')
hiddenimports = collect_submodules('paddleocr')

for m in [
    'paddleocr',
    'paddleocr._pipelines',
    'paddleocr._pipelines.ocr',
    'paddleocr._pipelines.base',
    'paddleocr._pipelines.pp_structurev3',
    'paddleocr._models',
    'paddleocr._utils',
]:
    if m not in hiddenimports:
        hiddenimports.append(m)

# ==================== PaddlePaddle ====================
datas += collect_data_files('paddle')
for m in collect_submodules('paddle'):
    if m not in hiddenimports:
        hiddenimports.append(m)

# ==================== PaddleX 3.x ====================
datas += collect_data_files('paddlex')
for m in collect_submodules('paddlex'):
    if m not in hiddenimports:
        hiddenimports.append(m)

# ==================== shapely ====================
try:
    datas += collect_data_files('shapely')
except Exception:
    pass
if 'shapely._geos' not in hiddenimports:
    hiddenimports.append('shapely._geos')

# ==================== fastapi / starlette ====================
datas += collect_data_files('fastapi')
datas += collect_data_files('starlette')
for m in collect_submodules('starlette'):
    if m not in hiddenimports:
        hiddenimports.append(m)

# ==================== regex ====================
_regex_dir = os.path.join(SITE_PKGS, 'regex')
if os.path.exists(_regex_dir):
    for f in os.listdir(_regex_dir):
        if f.endswith('.pyd'):
            datas.append((os.path.join(_regex_dir, f), 'regex'))
datas += collect_data_files('regex')
for m in ['regex._regex_core', 'regex._main']:
    if m not in hiddenimports:
        hiddenimports.append(m)

# ==================== pyclipper ====================
_pyclipper_dir = os.path.join(SITE_PKGS, 'pyclipper')
if os.path.exists(_pyclipper_dir):
    for f in os.listdir(_pyclipper_dir):
        if f.endswith('.pyd'):
            datas.append((os.path.join(_pyclipper_dir, f), 'pyclipper'))

# ==================== PaddleX OCR 动态依赖（已在 spec 中处理，此处仅收集子模块） ====================
for pkg in ['ftfy', 'einops', 'pyclipper', 'bidi']:
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:
        pass
