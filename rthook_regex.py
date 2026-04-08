# rthook_regex.py - PyInstaller runtime hook for regex module
import sys
import os

# 在 exe 环境下，确保 regex 的 .pyd 文件可以被正确加载
if getattr(sys, 'frozen', False):
    # 获取 _internal 目录路径
    if hasattr(sys, '_MEIPASS'):
        # 单文件模式
        base_path = sys._MEIPASS
    else:
        # 目录模式
        base_path = os.path.dirname(sys.executable)

    regex_path = os.path.join(base_path, 'regex')
    if os.path.exists(regex_path):
        # 将 regex 目录添加到 DLL 搜索路径
        os.add_dll_directory(regex_path)

    # 同时添加可能的二进制路径
    internal_path = os.path.join(base_path, '_internal')
    if os.path.exists(internal_path):
        os.add_dll_directory(internal_path)
        regex_internal_path = os.path.join(internal_path, 'regex')
        if os.path.exists(regex_internal_path):
            os.add_dll_directory(regex_internal_path)
