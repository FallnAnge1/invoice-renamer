"""Windows 剪贴板图片和文件导入；临时图片只在当前窗口存活期间保留。"""
from pathlib import Path
import tempfile

from PIL import Image, ImageGrab
from format_converter import IMAGE_SUFFIXES, _write_output


class ClipboardImport:
    def __init__(self):
        self._temporary = None

    def read(self, allowed=IMAGE_SUFFIXES):
        try:
            payload = ImageGrab.grabclipboard()
        except (OSError, RuntimeError) as error:
            raise ValueError("暂时无法读取剪贴板，请重新复制图片后再试。") from error
        if isinstance(payload, Image.Image):
            try:
                if ".png" not in allowed:
                    raise ValueError("剪贴板中是图片，请先选择图片转 PDF 或图片互转模式。")
                if self._temporary is None:
                    self._temporary = tempfile.TemporaryDirectory(prefix="invoice-clipboard-")
                return [_write_output(self._temporary.name, "剪贴板图片", ".png",
                                      lambda stream: payload.save(stream, format="PNG"))]
            finally:
                payload.close()
        if isinstance(payload, list):
            paths = []
            known = set()
            for value in payload:
                path = Path(value).resolve()
                key = str(path).casefold()
                if path.is_file() and path.suffix.lower() in allowed and key not in known:
                    paths.append(str(path))
                    known.add(key)
            if paths:
                return paths
        raise ValueError("剪贴板中没有当前功能支持的图片或文件。请先截图、复制图片，或在资源管理器中复制文件后再粘贴；文字和图片网址不支持。")

    def is_temporary(self, path):
        return self._temporary is not None and Path(path).resolve().parent == Path(self._temporary.name).resolve()

    def cleanup(self):
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None


def is_text_input(widget):
    """文本框中的 Ctrl+V 保持原有文字粘贴行为。"""
    return widget.winfo_class() in {"Text", "Entry", "TEntry", "TCombobox", "Spinbox", "TSpinbox"}
