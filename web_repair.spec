# -*- mode: python ; coding: utf-8 -*-
# web_repair.spec - Web版打包配置
# PaddleOCR 3.4.0 / PaddleX 3.4.2 / PaddlePaddle 3.2.0 + FastAPI Web框架
#
# 打包命令: E:\Anaconda_envs\envs\pro2\python.exe -m PyInstaller web_repair.spec --clean -y

import os

# ==================== 路径配置 ====================
PROJECT_DIR    = r'D:\Pyproject\pro2'
WEB_UI_DIST    = os.path.join(PROJECT_DIR, 'web-ui', 'dist')
MODELS_DIR     = os.path.join(PROJECT_DIR, 'models')

# Anaconda 虚拟环境路径
ANACONDA       = r'E:\Anaconda_envs\envs\pro2'
SITE_PKGS      = os.path.join(ANACONDA, 'Lib', 'site-packages')
PADDLE_LIBS    = os.path.join(SITE_PKGS, 'paddle', 'libs')

# ==================== Windows API Set DLL（解决 Win7 兼容问题） ====================
# api-ms-win-core-path-l1-1-0.dll 等 DLL 在 Win7 上不存在，
# 需从 conda 环境根目录和 Library\bin 显式打包进 exe。
_api_dlls = []
for _src_dir in [ANACONDA, os.path.join(ANACONDA, 'Library', 'bin')]:
    if os.path.isdir(_src_dir):
        for _dll in os.listdir(_src_dir):
            if _dll.startswith('api-') and _dll.endswith('.dll'):
                _api_dlls.append((os.path.join(_src_dir, _dll), '.'))

# UCRT 运行时 DLL（api-*.dll 依赖这些基础 C 运行时）
_ucrt_dlls = []
for _src_dir in [ANACONDA, os.path.join(ANACONDA, 'Library', 'bin')]:
    if os.path.isdir(_src_dir):
        for _dll in os.listdir(_src_dir):
            if _dll.startswith('ucrtbase') or (_dll.startswith('vcruntime') and '140' in _dll):
                _ucrt_dlls.append((os.path.join(_src_dir, _dll), '.'))

# ==================== PaddleX OCR 动态依赖（hook 无法自动收集，直接用 3-tuple） ====================
_paddlex_ocr_deps = []
for _pkg in ['premailer', 'bs4', 'openpyxl', 'et_xmlfile', 'cssutils',
             'ftfy', 'einops', 'pyclipper', 'bidi']:
    _pkg_dir = os.path.join(SITE_PKGS, _pkg)
    if os.path.exists(_pkg_dir):
        _paddlex_ocr_deps.append((_pkg_dir, _pkg))

# ==================== PaddleX 需要的 dist-info 目录（importlib.metadata.version 必需） ====================
# opencv-contrib-python 的版本检查（opencv_python 也需要，因为 cv2 来自它）
# safetensors / tokenizers / pypdfium2 同样需要版本信息
for _di in os.listdir(SITE_PKGS):
    if _di.endswith('.dist-info') and any(_d in _di for _d in [
        'opencv_contrib_python', 'opencv_python', 'safetensors',
        'tokenizers', 'pypdfium2',
    ]):
        _paddlex_ocr_deps.append((os.path.join(SITE_PKGS, _di), _di))

a = Analysis(
    ['repair.py'],
    pathex=[
        PROJECT_DIR,
        SITE_PKGS,
        PADDLE_LIBS,
    ],
    binaries=[
        (PADDLE_LIBS, '.'),
    ] + _api_dlls + _ucrt_dlls,
    datas=[
        # ==================== 项目文件 ====================
        ('ocr_core.py',                       '.'),
        ('server.py',                         '.'),
        ('repair_archive_merge.py',           '.'),

        # ==================== 前端资源 ====================
        (WEB_UI_DIST,                         'web-ui/dist'),

        # ==================== 模型目录 ====================
        (MODELS_DIR,                          'models'),
    ] + _paddlex_ocr_deps,
    hiddenimports=[
        # ==================== 本地模块 ====================
        'repair_archive_merge',

        # ==================== 修复已知问题 ====================
        'shapely._geos',
        'pydantic_core._pydantic_core',

        # ==================== PaddleX OCR 动态依赖 ====================
        'ftfy', 'premailer', 'einops', 'bs4', 'openpyxl',
        'et_xmlfile', 'cssutils', 'pyclipper', 'bidi',
        'pyclipper',  # premailer 内部引用
    ],
    hookspath=['.'],  # 加载 hook-paddleocr.py 自动收集依赖
    excludes=[
        'matplotlib',
        'tkinter',
        'notebook',
        'IPython',
        'PyQt5',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'PyQt5.sip',
        'PySide6',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='web_repair',
    debug=False,
    win_private_assemblies=True,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='web_repair',
)
