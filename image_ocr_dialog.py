"""照片转文字窗口；OCR 在后台执行，结果可编辑、复制、另存。"""
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from format_converter import IMAGE_SUFFIXES
from ocr_engine import extract_text_from_image
from ui_theme import heading, style_text, FONT

LANGUAGES = {"中文＋英文": "chi_sim+eng", "中文": "chi_sim", "英文": "eng"}


class ImageOCRDialog:
    def __init__(self, app):
        self.app = app
        self.path = None
        self.busy = False
        self.preview_image = None
        self.saved_text = ""
        self.window = tk.Toplevel(app.root)
        self.window.title("图片识别文字 · 发票与文档助手")
        self.window.geometry("1120x780")
        self.window.minsize(960, 680)
        self.window.transient(app.root)
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        body = ttk.Frame(self.window, padding=24)
        body.pack(fill=tk.BOTH, expand=True)
        heading(body, "图片识别文字", "选择照片，提取中英文；识别结果可编辑、复制或另存。")
        toolbar = ttk.Frame(body)
        toolbar.pack(fill=tk.X, pady=(0, 18))
        self.choose_button = ttk.Button(toolbar, text="选择照片", command=self.choose_photo)
        self.choose_button.pack(side=tk.LEFT)
        ttk.Label(toolbar, text="识别语言", style="Muted.TLabel").pack(side=tk.LEFT, padx=(20, 8))
        self.language = tk.StringVar(value="中文＋英文")
        self.language_box = ttk.Combobox(toolbar, textvariable=self.language,
                                        values=list(LANGUAGES), state="readonly", width=12)
        self.language_box.pack(side=tk.LEFT)
        self.recognize_button = ttk.Button(toolbar, text="识别文字", command=self.run, style="Primary.TButton")
        self.recognize_button.pack(side=tk.RIGHT)
        self.status = ttk.Label(body, text="本机识别 · 无需上传 · 清晰的印刷文字照片效果更好。",
                                style="Muted.TLabel", wraplength=880)
        self.status.pack(side=tk.BOTTOM, anchor=tk.W, pady=(10, 0))
        self.progress = ttk.Progressbar(body, mode="indeterminate")
        self.progress.pack(side=tk.BOTTOM, fill=tk.X, pady=(14, 0))
        content = ttk.Frame(body)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(0, weight=2, uniform="panes")
        content.columnconfigure(1, weight=3, uniform="panes")
        content.rowconfigure(0, weight=1)
        photo = ttk.Frame(content, style="Card.TFrame", padding=18)
        photo.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        ttk.Label(photo, text="原始照片", style="Heading.TLabel").pack(anchor=tk.W)
        self.filename = ttk.Label(photo, text="尚未选择照片", style="CardMuted.TLabel", wraplength=290)
        self.filename.pack(anchor=tk.W, pady=(8, 0))
        self.preview = ttk.Label(photo, text="照片预览\n\n支持 JPG、PNG、WebP、BMP、单帧 TIFF",
                                  anchor=tk.CENTER, justify=tk.CENTER, style="CardMuted.TLabel", wraplength=280)
        self.preview.pack(fill=tk.BOTH, expand=True, pady=14)
        self.meta_label = ttk.Label(photo, text="尽量摆正照片，避免反光和模糊。", style="CardMuted.TLabel", wraplength=290)
        self.meta_label.pack(anchor=tk.W)
        result_panel = ttk.Frame(content)
        result_panel.grid(row=0, column=1, sticky="nsew")
        result_head = ttk.Frame(result_panel)
        result_head.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(result_head, text="识别结果", font=(FONT, 11, "bold")).pack(side=tk.LEFT)
        self.count_label = ttk.Label(result_head, text="0 字符", style="Muted.TLabel")
        self.count_label.pack(side=tk.RIGHT)
        bottom = ttk.Frame(result_panel)
        bottom.pack(side=tk.BOTTOM, fill=tk.X, pady=(12, 0))
        self.copy_button = ttk.Button(bottom, text="复制全部文字", command=self.copy_text)
        self.copy_button.pack(side=tk.LEFT)
        self.save_button = ttk.Button(bottom, text="保存 TXT", command=self.save_text)
        self.save_button.pack(side=tk.RIGHT)
        self.result = ScrolledText(result_panel, wrap=tk.WORD, height=10, width=30, undo=True)
        style_text(self.result)
        self.result.pack(fill=tk.BOTH, expand=True)
        self.result.bind("<<Modified>>", self.on_text_change)
        self.set_busy(False)

    def on_text_change(self, _event=None):
        if not self.result.edit_modified():
            return
        self.result.edit_modified(False)
        text = self.result.get("1.0", "end-1c")
        self.count_label.config(text=f"{len(text)} 字符")
        self.update_result_actions()

    def update_result_actions(self):
        enabled = not self.busy and bool(self.result.get("1.0", "end-1c").strip())
        for button in (self.copy_button, self.save_button):
            button.config(state=tk.NORMAL if enabled else tk.DISABLED)

    def can_replace_result(self):
        current = self.result.get("1.0", "end-1c")
        if current.strip() and current != self.saved_text:
            return messagebox.askyesno("保留识别文字", "当前文字尚未复制或保存。是否放弃当前文字并继续？", parent=self.window)
        return True

    def close(self):
        if self.busy:
            messagebox.showinfo("正在识别", "请等待识别完成后关闭。", parent=self.window)
            return
        if not self.can_replace_result():
            return
        self.window.destroy()

    def set_busy(self, busy):
        self.busy = busy
        self.choose_button.config(state=tk.DISABLED if busy else tk.NORMAL)
        self.recognize_button.config(state=tk.DISABLED if busy or not self.path else tk.NORMAL)
        self.language_box.config(state=tk.DISABLED if busy else "readonly")
        self.result.config(state=tk.DISABLED if busy else tk.NORMAL)
        self.update_result_actions()
        if busy:
            self.progress.config(mode="indeterminate")
            self.progress.start(12)
            self.recognize_button.config(text="正在识别…")
        else:
            self.progress.stop()
            self.progress.config(mode="determinate", value=0)
            self.recognize_button.config(text="识别文字")

    def choose_photo(self):
        path = filedialog.askopenfilename(parent=self.window, title="选择要识别的照片",
            filetypes=[("图片文件", " ".join("*" + suffix for suffix in sorted(IMAGE_SUFFIXES)))])
        if path:
            self.load_photo(path)

    def load_photo(self, path):
        if self.busy:
            return
        from PIL import Image, ImageOps, ImageTk
        try:
            with Image.open(path) as source:
                if getattr(source, "n_frames", 1) > 1:
                    raise ValueError("请选择单张图片；多帧图片请先拆帧")
                with ImageOps.exif_transpose(source) as oriented:
                    dimensions = f"{oriented.width} × {oriented.height} 像素"
                    oriented.thumbnail((300, 320))
                    preview = ImageTk.PhotoImage(oriented, master=self.window)
        except Exception as error:
            messagebox.showerror("无法打开图片", str(error), parent=self.window)
            return
        if not self.can_replace_result():
            return
        self.path = str(Path(path).resolve())
        self.preview_image = preview
        self.preview.config(image=preview, text="")
        self.filename.config(text=Path(path).name)
        self.meta_label.config(text=dimensions + " · 原图尺寸\n识别时使用原图，不使用缩略预览。")
        self.result.delete("1.0", tk.END)
        self.result.edit_reset()
        self.saved_text = ""
        self.count_label.config(text="0 字符")
        self.status.config(text="照片已加载，点击“识别文字”开始。")
        self.set_busy(False)

    def run(self):
        if self.busy or self.app.processing or not self.path:
            return
        if not self.can_replace_result():
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
        self.count_label.config(text=f"{len(text)} 字符")
        self.update_result_actions()
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
            self.saved_text = text
            self.status.config(text="已复制全部文字，可粘贴到其他软件。")

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
                self.saved_text = text
                self.status.config(text=f"文字已保存：{path}")
            except Exception as error:
                messagebox.showerror("保存失败", str(error), parent=self.window)
