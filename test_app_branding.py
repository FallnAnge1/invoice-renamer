import ctypes
import os
from pathlib import Path
import shutil
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from PIL import Image
from app_branding import APP_ID, apply_branding, resource_path, set_windows_app_id


class BrandingTest(unittest.TestCase):
    def test_icon_has_transparency_and_windows_sizes(self):
        with Image.open(resource_path("assets/app.ico")) as icon:
            self.assertTrue({(16, 16), (32, 32), (48, 48), (256, 256)} <= icon.ico.sizes())
        with Image.open(resource_path("assets/app.png")) as image:
            self.assertEqual(image.size, (256, 256))
            self.assertEqual(image.getchannel("A").getextrema(), (0, 255))

    def test_source_and_extracted_resources_work_from_unrelated_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            assets = Path(folder) / "assets"
            assets.mkdir()
            for name in ("app.png", "app.ico"):
                shutil.copy2(resource_path("assets/" + name), assets / name)
            previous = Path.cwd()
            root = tk.Tk()
            root.withdraw()
            try:
                os.chdir(folder)
                apply_branding(root)
                self.assertEqual(root.brand_logo.width(), 64)
                self.assertEqual(root.brand_small.width(), 16)
                with patch.object(sys, "_MEIPASS", folder, create=True):
                    apply_branding(root)
                    self.assertEqual(resource_path("assets/app.ico"), assets / "app.ico")
                    self.assertEqual(len(root._brand_images), 4)
            finally:
                os.chdir(previous)
                root.update_idletasks()
                root.destroy()

    @unittest.skipUnless(sys.platform == "win32", "Windows taskbar application ID")
    def test_windows_taskbar_identity_is_explicit(self):
        set_windows_app_id()
        value = ctypes.c_wchar_p()
        getter = ctypes.windll.shell32.GetCurrentProcessExplicitAppUserModelID
        getter.argtypes = [ctypes.POINTER(ctypes.c_wchar_p)]
        getter.restype = ctypes.c_long
        self.assertEqual(getter(ctypes.byref(value)), 0)
        try:
            self.assertEqual(value.value, APP_ID)
        finally:
            free = ctypes.windll.ole32.CoTaskMemFree
            free.argtypes = [ctypes.c_void_p]
            free(ctypes.cast(value, ctypes.c_void_p))
