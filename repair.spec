# -*- mode: python ; coding: utf-8 -*-
# repair.spec - 适配 PaddleOCR 3.4.0 / PaddleX 3.4.2 / PaddlePaddle 3.2.0
# 项目结构: repair.py (入口) + ocr_core.py (OCR核心) + ui_window.py (主窗口)
# Anaconda 环境: E:\Anaconda

import os

ANACONDA    = r'E:\Anaconda\Lib\site-packages'
PADDLE_LIBS = os.path.join(ANACONDA, 'paddle', 'libs')
PYQT5_DIR   = os.path.join(ANACONDA, 'PyQt5')
PADDLEOCR   = os.path.join(ANACONDA, 'paddleocr')
PADDLEX     = os.path.join(ANACONDA, 'paddlex')

a = Analysis(
    ['repair.py'],  # 入口；依赖 ocr_core.py + ui_window.py
    pathex=[
        r'D:\Pyproject\pro2',   # ocr_core.py / ui_window.py 所在目录
        ANACONDA,
        PADDLE_LIBS,
    ],
    binaries=[
        (os.path.join(ANACONDA, 'paddle', 'libs'), '.'),
    ],
    datas=[
        # 源模块（拆分后需显式打包）
        ('ocr_core.py',  '.'),
        ('ui_window.py', '.'),
        # 本地模型目录
        ('models', 'models'),
        # PaddleOCR 3.x 资源
        (os.path.join(PADDLEOCR, '_pipelines'), 'paddleocr/_pipelines'),
        (os.path.join(PADDLEOCR, '_models'),    'paddleocr/_models'),
        (os.path.join(PADDLEOCR, '_utils'),     'paddleocr/_utils'),
        # PaddleX 资源
        (os.path.join(PADDLEX, 'configs'),   'paddlex/configs'),
        (os.path.join(PADDLEX, 'repo_apis'), 'paddlex/repo_apis'),
        # PyQt5 插件
        (os.path.join(PYQT5_DIR, 'Qt5', 'plugins', 'platforms'),    'PyQt5/Qt5/plugins/platforms'),
        (os.path.join(PYQT5_DIR, 'Qt5', 'plugins', 'styles'),       'PyQt5/Qt5/plugins/styles'),
        (os.path.join(PYQT5_DIR, 'Qt5', 'plugins', 'imageformats'), 'PyQt5/Qt5/plugins/imageformats'),
    ],
    hiddenimports=[
        # PaddlePaddle
        'paddle', 'paddle.nn', 'paddle.nn.functional',
        'paddle.tensor', 'paddle.static', 'paddle.vision', 'paddle.inference',
        # PaddleOCR 3.x
        'paddleocr', 'paddleocr._pipelines', 'paddleocr._pipelines.ocr',
        'paddleocr._pipelines.base', 'paddleocr._models', 'paddleocr._utils',
        'paddleocr._utils.deprecation', 'paddleocr._utils.logging',
        # PaddleX
        'paddlex', 'paddlex.inference', 'paddlex.inference.pipelines',
        'paddlex.inference.pipelines.ocr', 'paddlex.inference.pipelines.ocr.pipeline',
        'paddlex.inference.pipelines.ocr.result', 'paddlex.utils', 'paddlex.utils.config',
        # 图像处理
        'cv2', 'numpy', 'numpy.core', 'numpy.linalg',
        'PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFont',
        'skimage', 'skimage.io', 'skimage.transform',
        'shapely', 'shapely.geometry', 'pyclipper', 'lmdb', 'rapidfuzz',
        # PyQt5
        'PyQt5', 'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets', 'PyQt5.sip',
        # 工具库
        'yaml', 'requests', 'requests.adapters',
        'openpyxl', 'openpyxl.styles', 'openpyxl.worksheet',
        'pandas', 'pandas._libs.tslibs.timedeltas',
        'repair_archive_merge',
        'tqdm', 'colorama',
        # 标准库
        'json', 'os', 'sys', 'pathlib', 'datetime', 're', 'io', 'logging', 'warnings',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'tkinter', 'notebook', 'IPython', 'scipy'],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='repair',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,   # GUI模式，不显示控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='repair',
)
