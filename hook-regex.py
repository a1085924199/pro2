# hook-regex.py - PyInstaller 钩子文件
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# 收集 regex 模块的所有数据文件
datas = collect_data_files('regex')

# 收集所有子模块
hiddenimports = collect_submodules('regex')

# 强制添加核心扩展模块
_needed_modules = [
    'regex',
    'regex._regex',
    'regex._regex_core',
    'regex._main',
    'regex._regex_32',
    'regex._regex_core_32',
]

for m in _needed_modules:
    if m not in hiddenimports:
        hiddenimports.append(m)

# 特殊处理：regex 的 C 扩展是动态加载的，需要明确包含
# 使用 binaries 而非 datas 来确保 .pyd 文件被正确处理
import os, sys

# 尝试找到 regex 的 .pyd 文件位置
try:
    import regex as _regex_module
    _regex_path = os.path.dirname(_regex_module.__file__)
    
    # 检查是否存在 C 扩展
    for f in os.listdir(_regex_path):
        if f.startswith('_regex') and f.endswith('.pyd'):
            # 添加到 binaries
            binaries.append((os.path.join(_regex_path, f), 'regex'))
except Exception:
    pass
