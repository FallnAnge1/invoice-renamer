"""格式转换窗口，复用主界面的工作线程与消息队列。"""
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from format_converter import IMAGE_SUFFIXES, MODES, convert_files
from clipboard_import import ClipboardImport, is_text_input
from ui_theme import heading, style_text, open_folder, FONT, INK, LINE


class ConverterDialog:
    def __init__(self, app):
        self.app = app
        self.paths = []
        self.outputs = []
        self.last_folder = None
        self.busy = False
        self.clipboard_import = ClipboardImport()
        self.window = tk.Toplevel(app.root)
        self.window.title("格式转换 · 发票与文档助手")
        self.window.geometry("900x800")
        self.window.minsize(760, 720)
        self.window.transient(app.root)
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Control-v>", self.paste_shortcut)
        self.window.bind("<Destroy>", self.cleanup_clipboard, add="+")
        body = ttk.Frame(self.window, padding=24)
        body.pack(fill=tk.BOTH, expand=True)
        heading(body, "格式转换", "图片与 PDF 互转、合并拆分，原文件始终保留。")
        ttk.Label(body, text="01  选择转换方式", font=(FONT, 11, "bold")).pack(anchor=tk.W)
        self.mode = tk.StringVar(value=next(iter(MODES)))
        self.mode_box = ttk.Combobox(body, textvariable=self.mode, values=list(MODES), state="readonly")
        self.mode_box.pack(fill=tk.X, pady=(8, 6))
        self.mode_box.bind("<<ComboboxSelected>>", self.change_mode)
        self.mode_hint = ttk.Label(body, style="Muted.TLabel", wraplength=680)
        self.mode_hint.pack(anchor=tk.W, pady=(0, 12))

        # 固定底部操作区先布局，让窄窗口也能看到转换结果和按钮。
        footer = ttk.Frame(body)
        footer.pack(side=tk.BOTTOM, fill=tk.X)
        self.result = ScrolledText(footer, height=3, wrap=tk.WORD, state=tk.DISABLED)
        style_text(self.result)
        self.result.pack(fill=tk.X, pady=(10, 0))
        self.progress = ttk.Progressbar(footer)
        self.progress.pack(fill=tk.X, pady=(12, 8))
        action = ttk.Frame(footer)
        action.pack(fill=tk.X)
        self.open_button = ttk.Button(action, text="打开输出文件夹", command=self.open_output)
        self.open_button.pack(side=tk.LEFT)
        self.start = ttk.Button(action, text="开始转换", command=self.run, style="Primary.TButton")
        self.start.pack(side=tk.RIGHT)
        self.progress_label = ttk.Label(action, text="等待添加文件", style="Muted.TLabel")
        self.progress_label.pack(side=tk.RIGHT, padx=14)
        settings = ttk.Frame(body)
        settings.pack(side=tk.BOTTOM, fill=tk.X, pady=(12, 0))
        ttk.Label(settings, text="03  保存位置", font=(FONT, 11, "bold")).pack(anchor=tk.W)
        output = ttk.Frame(settings)
        output.pack(fill=tk.X, pady=8)
        self.output = tk.StringVar()
        self.output_entry = ttk.Entry(output, textvariable=self.output)
        self.output_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        choose = ttk.Button(output, text="更改位置", command=self.choose_output)
        choose.pack(side=tk.LEFT, padx=(8, 0))
        self.import_pdf = tk.BooleanVar(value=True)
        self.import_check = ttk.Checkbutton(settings, text="生成 PDF 后加入发票列表，继续识别与重命名", variable=self.import_pdf)
        self.import_check.pack(anchor=tk.W)

        row = ttk.Frame(body)
        row.pack(fill=tk.X, pady=(0, 8))
        self.count_label = ttk.Label(row, text="02  添加文件  ·  0 个", font=(FONT, 11, "bold"))
        self.count_label.pack(side=tk.LEFT)
        self.add_button = ttk.Button(row, text="添加文件", command=self.add_files)
        self.add_button.pack(side=tk.RIGHT)
        self.paste_button = ttk.Button(row, text="从剪贴板粘贴", command=self.paste_clipboard)
        self.paste_button.pack(side=tk.RIGHT, padx=8)
        list_frame = ttk.Frame(body)
        list_frame.pack(fill=tk.BOTH, expand=True)
        self.files = tk.Listbox(list_frame, selectmode=tk.EXTENDED, height=5, exportselection=False,
                               font=(FONT, 10), relief="flat", borderwidth=0, highlightthickness=1,
                               highlightbackground=LINE, selectbackground="#DCE7FF", selectforeground=INK,
                               activestyle="none")
        scroll = ttk.Scrollbar(list_frame, command=self.files.yview)
        self.files.config(yscrollcommand=scroll.set)
        self.files.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.files.bind("<<ListboxSelect>>", lambda _event: self.update_controls())
        manage = ttk.Frame(body)
        manage.pack(fill=tk.X, pady=(6, 0))
        self.remove_button = ttk.Button(manage, text="移除所选", command=self.remove)
        self.remove_button.pack(side=tk.LEFT)
        self.up_button = ttk.Button(manage, text="上移", command=lambda: self.move(-1))
        self.up_button.pack(side=tk.LEFT, padx=8)
        self.down_button = ttk.Button(manage, text="下移", command=lambda: self.move(1))
        self.down_button.pack(side=tk.LEFT)
        ttk.Label(manage, text="合并按列表从上到下的顺序", style="Muted.TLabel").pack(side=tk.RIGHT)
        self.controls = [self.add_button, self.paste_button, self.remove_button, self.up_button, self.down_button,
                         self.output_entry, choose, self.import_check, self.start]
        self.output.trace_add("write", lambda *_args: self.update_controls())
        self.show_result("添加文件或粘贴截图即可转换（列表中按 Ctrl+V）。同名结果自动加序号。")
        self.update_hint()
        self.update_controls()

    def update_hint(self):
        mode = MODES[self.mode.get()]
        text = {
            "image_pdf": "每张图片生成独立 PDF；若需继续提取发票内容，转换后再进行 OCR。",
            "images_pdf": "多张图片合成一份 PDF。可用上移、下移调整页序。",
            "pdf_png": "PDF 每页导出一张 PNG 图片，分辨率 150 DPI。",
            "pdf_jpg": "PDF 每页导出一张 JPG 图片，分辨率 150 DPI。",
            "merge_pdf": "将多份 PDF 合成一份，保留页面内容；按列表顺序合并。",
            "split_pdf": "PDF 按页拆分，每页生成一份独立 PDF。",
        }.get(mode, "支持 JPG、PNG、WebP、BMP、单帧 TIFF 输入；透明图转 JPG/BMP 使用白底。")
        self.mode_hint.config(text=text)

    def update_controls(self):
        enabled = not self.busy
        self.start.config(state=tk.NORMAL if enabled and self.paths and self.output.get().strip() else tk.DISABLED)
        selection = self.files.curselection()
        self.remove_button.config(state=tk.NORMAL if enabled and selection else tk.DISABLED)
        for button, available in ((self.up_button, len(selection) == 1 and selection[0] > 0),
                                   (self.down_button, len(selection) == 1 and selection[0] < len(self.paths) - 1)):
            button.config(state=tk.NORMAL if enabled and available else tk.DISABLED)
        mode = MODES[self.mode.get()]
        self.import_check.config(state=tk.NORMAL if enabled and mode in ("image_pdf", "images_pdf", "merge_pdf", "split_pdf") else tk.DISABLED)
        self.open_button.config(state=tk.NORMAL if enabled and self.outputs and self.last_folder else tk.DISABLED)

    def open_output(self):
        if self.last_folder:
            try:
                open_folder(self.last_folder)
            except OSError as error:
                messagebox.showerror("无法打开文件夹", str(error), parent=self.window)

    def close(self):
        if self.busy:
            messagebox.showinfo("正在转换", "请等待本次转换完成后关闭。", parent=self.window)
            return
        self.window.destroy()

    def change_mode(self, _event=None):
        if self.busy:
            return
        images = MODES[self.mode.get()].startswith("image")
        allowed = IMAGE_SUFFIXES if images else {".pdf"}
        old_count = len(self.paths)
        self.paths = [path for path in self.paths if Path(path).suffix.lower() in allowed]
        removed = old_count - len(self.paths)
        self.refresh()
        self.update_hint()
        if removed:
            self.show_result(f"已切换转换方式；移除 {removed} 个不适用的列表项，原文件保留。")

    def refresh(self):
        self.files.delete(0, tk.END)
        for index, path in enumerate(self.paths, 1):
            self.files.insert(tk.END, f"  {index:02d}   {Path(path).name}   ·   {Path(path).parent.name}")
        self.count_label.config(text=f"02  添加文件  ·  {len(self.paths)} 个")
        self.update_controls()

    def add_files(self):
        if self.busy or self.app.processing:
            return
        images = MODES[self.mode.get()].startswith("image")
        pattern = " ".join("*" + suffix for suffix in sorted(IMAGE_SUFFIXES)) if images else "*.pdf"
        paths = filedialog.askopenfilenames(parent=self.window, title="选择要转换的文件",
                    filetypes=[("图片文件" if images else "PDF 文件", pattern)])
        self.add_paths(paths)

    def add_paths(self, paths):
        images = MODES[self.mode.get()].startswith("image")
        added = 0
        allowed = IMAGE_SUFFIXES if images else {".pdf"}
        known = {str(Path(path).resolve()).casefold() for path in self.paths}
        for path in paths:
            key = str(Path(path).resolve()).casefold()
            if key not in known and Path(path).is_file() and Path(path).suffix.lower() in allowed:
                self.paths.append(path)
                known.add(key)
                added += 1
        if self.paths and not self.output.get().strip():
            first = self.paths[0]
            self.output.set(str(Path.home() / "图片转换结果" if self.clipboard_import.is_temporary(first)
                                else Path(first).parent / "转换结果"))
        self.refresh()
        if paths:
            self.progress_label.config(text=f"已添加 {added} 个文件")

    def paste_shortcut(self, event):
        if not is_text_input(event.widget):
            self.paste_clipboard()
            return "break"

    def paste_clipboard(self):
        if self.busy or self.app.processing:
            return
        allowed = IMAGE_SUFFIXES if MODES[self.mode.get()].startswith("image") else {".pdf"}
        try:
            self.add_paths(self.clipboard_import.read(allowed))
        except (ValueError, OSError) as error:
            messagebox.showinfo("无法粘贴", str(error), parent=self.window)

    def cleanup_clipboard(self, event):
        if event.widget == self.window:
            self.clipboard_import.cleanup()

    def remove(self):
        selected = self.files.curselection()
        if self.busy:
            return
        for index in reversed(selected):
            del self.paths[index]
        self.refresh()

    def move(self, offset):
        selected = self.files.curselection()
        if self.busy or len(selected) != 1:
            return
        old = selected[0]
        new = old + offset
        if 0 <= new < len(self.paths):
            self.paths[old], self.paths[new] = self.paths[new], self.paths[old]
            self.refresh()
            self.files.selection_set(new)
            self.files.see(new)
            self.update_controls()

    def choose_output(self):
        folder = filedialog.askdirectory(parent=self.window, title="选择输出文件夹")
        if folder:
            self.output.set(folder)

    def show_result(self, text):
        self.result.config(state=tk.NORMAL)
        self.result.delete("1.0", tk.END)
        self.result.insert("1.0", text)
        self.result.config(state=tk.DISABLED)

    def run(self):
        if self.busy or self.app.processing:
            return
        if not self.paths or not self.output.get().strip():
            messagebox.showinfo("提示", "请添加文件并选择输出文件夹。", parent=self.window)
            return
        folder = Path(self.output.get().strip()).expanduser().absolute()
        if folder.exists() and not folder.is_dir():
            messagebox.showerror("输出位置错误", "请选择文件夹。", parent=self.window)
            return
        paths, mode, import_pdf = list(self.paths), MODES[self.mode.get()], self.import_pdf.get()
        self.busy = True
        for control in self.controls:
            control.config(state=tk.DISABLED)
        self.mode_box.config(state=tk.DISABLED)
        self.progress.config(value=0, maximum=len(paths))
        self.open_button.config(state=tk.DISABLED)
        self.progress_label.config(text="正在转换…")
        self.show_result("正在转换，请稍候…")

        def update(value, total):
            self.app._post_ui(self.progress.config, value=value, maximum=total)
            self.app._post_ui(self.progress_label.config, text=f"已处理 {value} / {total}")

        def work():
            try:
                outputs, failures = convert_files(paths, mode, folder, progress=update)
                self.app._post_ui(self.complete, outputs, failures, import_pdf, folder)
            except Exception as error:
                self.app._post_ui(self.complete, [], [str(error)], import_pdf, folder)
            finally:
                self.app._finish_worker()

        self.app._start_worker(work)

    def complete(self, outputs, failures, import_pdf, folder):
        self.busy = False
        self.outputs = outputs
        self.last_folder = folder
        for control in self.controls:
            control.config(state=tk.NORMAL)
        self.mode_box.config(state="readonly")
        if import_pdf:
            for path in outputs:
                if Path(path).suffix.lower() == ".pdf":
                    self.app._insert_item(path)
            self.app._refresh_table()
        self.show_result(f"已生成 {len(outputs)} 个文件；失败 {len(failures)} 项。\n输出位置：{folder}\n"
                         + ("失败详情：\n" + "\n".join(failures) if failures else "转换完成，原文件已保留。"))
        self.progress_label.config(text=f"完成 {len(outputs)} 个 · 失败 {len(failures)} 项")
        self.update_controls()
        self.app._set_status(f"格式转换完成：生成 {len(outputs)} 个文件，失败 {len(failures)} 项")
