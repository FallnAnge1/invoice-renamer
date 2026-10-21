"""统一文件、窗口、任务栏及应用内图标，兼容单 EXE 临时资源目录。"""
from pathlib import Path
import sys
import tkinter as tk

APP_ID = "FallnAnge1.InvoiceDocumentAssistant"


def resource_path(name):
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / name


def set_windows_app_id():
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)


def apply_branding(root):
    set_windows_app_id()
    source = tk.PhotoImage(master=root, file=str(resource_path("assets/app.png")))
    root.brand_logo = source.subsample(4, 4)
    root.brand_small = source.subsample(16, 16)
    medium = source.subsample(8, 8)
    if sys.platform == "win32":
        root.iconbitmap(default=str(resource_path("assets/app.ico")))
    root.iconphoto(True, source, root.brand_logo, medium, root.brand_small)
    # Tk 的 iconphoto 与控件都需要持有图像引用。
    root._brand_images = (source, root.brand_logo, medium, root.brand_small)
