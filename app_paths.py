"""面向用户的默认保存位置，兼容 Windows 重定向桌面。"""
from pathlib import Path
import sys


def desktop_directory():
    if sys.platform == "win32":
        import ctypes
        buffer = ctypes.create_unicode_buffer(32768)
        # CSIDL_DESKTOPDIRECTORY，尊重 OneDrive / 用户重定向设置。
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buffer) == 0 and buffer.value:
            return Path(buffer.value)
    return Path.home() / "Desktop"
