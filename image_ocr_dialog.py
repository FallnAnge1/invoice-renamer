"""照片转文字窗口；OCR 在后台执行，结果可编辑、复制、另存。"""
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from format_converter import IMAGE_SUFFIXES
from ocr_engine import extract_text_from_image

LANGUAGES = {"中文＋英文": "chi_sim+eng", "中文": "chi_sim", "英文": "eng"}


class ImageOCRDialog:
    def __init__(self, app):
        self.app = app
        self.path = None
        self.busy = False
        self.preview_image = None
        self.window = tk.Toplevel(app.root)
        self.window.title("图片识别文字")
        self.window.geometry("840x700")
        self.window.minsize(650, 550)
        self.window.transient(app.root)
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        body = ttk.Frame(self.window, padding=14)
        body.pack(fill=tk.BOTH, expand=True)
        toolbar = ttk.Frame(body)
        toolbar.pack(fill=tk.X)
        self.choose_button = ttk.Button(toolbar, text="选择照片", command=self.choose_photo)
        self.choose_button.pack(side=tk.LEFT)
        self.language = tk.StringVar(value="中文＋英文")
        self.language_box = ttk.Combobox(toolbar, textvariable=self.language,
                                        values=list(LANGUAGES), state="readonly", width=12)
        self.language_box.pack(side=tk.LEFT, padx=10)
        self.recognize_button = ttk.Button(toolbar, text="识别文字", command=self.run)
        self.recognize_button.pack(side=tk.LEFT)
        self.filename = ttk.Label(body, text="请选择 JPG、PNG、WebP、BMP 或单帧 TIFF 图片", wraplength=600)
        self.filename.pack(anchor=tk.W, pady=8)
        self.preview = ttk.Label(body, text="照片预览", anchor=tk.CENTER)
        self.preview.pack(fill=tk.X)
        ttk.Label(body, text="识别结果（可编辑校对）：").pack(anchor=tk.W, pady=(10, 4))
        self.result = ScrolledText(body, wrap=tk.WORD, height=10, undo=True)
        bottom = ttk.Frame(body)
        self.copy_button = ttk.Button(bottom, text="复制全部文字", command=self.copy_text)
        self.copy_button.pack(side=tk.LEFT)
        self.save_button = ttk.Button(bottom, text="保存为 TXT", command=self.save_text)
        self.save_button.pack(side=tk.LEFT, padx=10)
        self.status = ttk.Label(body, text="照片在本机识别，无需上传。请尽量使用清晰、摆正的印刷文字照片。",
                                wraplength=600)
        self.status.pack(side=tk.BOTTOM, anchor=tk.W)
        bottom.pack(side=tk.BOTTOM, fill=tk.X, pady=10)
        self.result.pack(fill=tk.BOTH, expand=True)
        self.set_busy(False)

    def close(self):
        if self.busy:
            messagebox.showinfo("正在识别", "请等待识别完成后关闭。", parent=self.window)
            return
        self.window.destroy()

    def set_busy(self, busy):
        self.busy = busy
        self.choose_button.config(state=tk.DISABLED if busy else tk.NORMAL)
        self.recognize_button.config(state=tk.DISABLED if busy or not self.path else tk.NORMAL)
        self.language_box.config(state=tk.DISABLED if busy else "readonly")
        for button in (self.copy_button, self.save_button):
            button.config(state=tk.DISABLED if busy else tk.NORMAL)
        self.result.config(state=tk.DISABLED if busy else tk.NORMAL)

    def choose_photo(self):
        path = filedialog.askopenfilename(parent=self.window, title="选择要识别的照片",
            filetypes=[("图片文件", " ".join("*" + suffix for suffix in sorted(IMAGE_SUFFIXES)))])
        if path:
            self.load_photo(path)

    def load_photo(self, path):
        from PIL import Image, ImageOps, ImageTk
        try:
            with Image.open(path) as source:
                if getattr(source, "n_frames", 1) > 1:
                    raise ValueError("请选择单张图片；多帧图片请先拆帧")
                with ImageOps.exif_transpose(source) as oriented:
                    oriented.thumbnail((600, 200))
                    preview = ImageTk.PhotoImage(oriented, master=self.window)
        except Exception as error:
            messagebox.showerror("无法打开图片", str(error), parent=self.window)
            return
        self.path = str(path)
        self.preview_image = preview
        self.preview.config(image=preview, text="")
        self.filename.config(text=str(path))
        self.result.delete("1.0", tk.END)
        self.result.edit_reset()
        self.status.config(text="照片已加载，点击“识别文字”开始。")
        self.set_busy(False)

    def run(self):
        if self.busy or self.app.processing or not self.path:
            return
        path, language = self.path, LANGUAGES[self.language.get()]
        self.set_busy(True)
        self.status.config(text="正在识别文字，请稍候…")

        def work():
            try:
                text = extract_text_from_image(path, language)
                self.app._post_ui(self.complete, text, None)
            except Exception as error:
                self.app._post_ui(self.complete, None, str(error))
            finally:
                self.app._finish_worker()

        self.app._start_worker(work)

    def complete(self, text, error):
        self.set_busy(False)
        if error:
            self.status.config(text="识别失败：" + error)
            return
        self.result.delete("1.0", tk.END)
        self.result.insert("1.0", text)
        self.result.edit_reset()
        self.status.config(text=f"识别完成，共 {len(text)} 个字符，可编辑、复制或保存。" if text else
                           "未识别到文字，请换一张清晰、摆正的照片后重试。")

    def get_text(self):
        text = self.result.get("1.0", "end-1c")
        if not text.strip():
            messagebox.showinfo("提示", "暂无文字，请先识别或输入文字。", parent=self.window)
            return None
        return text

    def copy_text(self):
        text = self.get_text()
        if text is not None:
            self.window.clipboard_clear()
            self.window.clipboard_append(text)
            self.status.config(text="已复制全部文字。")

    def save_text(self):
        text = self.get_text()
        if text is None:
            return
        path = filedialog.asksaveasfilename(parent=self.window, title="保存识别文字", defaultextension=".txt",
            initialfile=(Path(self.path).stem if self.path else "识别文字") + ".txt",
            filetypes=[("文本文件", "*.txt")])
        if path:
            try:
                if self.path and Path(path).resolve() == Path(self.path).resolve():
                    raise ValueError("请另存为 TXT，不能覆盖原照片。")
                Path(path).write_text(text, encoding="utf-8")
                self.status.config(text=f"文字已保存：{path}")
            except Exception as error:
                messagebox.showerror("保存失败", str(error), parent=self.window)
