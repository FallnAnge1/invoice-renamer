"""批量照片转文字；逐项结果独立保存，切换照片不丢失人工修改。"""
import os
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from format_converter import IMAGE_SUFFIXES
from clipboard_import import ClipboardImport, is_text_input
from app_paths import desktop_directory
from ocr_engine import extract_text_from_image
from batch_ocr import new_record, merge_results, export_separate, result_text, describe_ocr_error
from ui_theme import style_text, FONT

LANGUAGES = {"中文＋英文": "chi_sim+eng", "中文": "chi_sim", "英文": "eng"}


class ImageOCRDialog:
    def __init__(self, app):
        self.app = app
        self.records = []
        self.current_index = None
        self.busy = False
        self.clipboard_import = ClipboardImport()
        self.save_folder = desktop_directory()
        self._loading = False
        self.preview_image = None
        self._preview_source = None
        self._preview_job = None
        self.window = ttk.Frame(app.workspace)
        self._image_viewer = None
        self.window.bind("<Control-v>", self.paste_shortcut)
        self.window.bind("<Destroy>", self.cleanup_clipboard, add="+")
        body = ttk.Frame(self.window, padding=(22, 18, 22, 18))
        body.pack(fill=tk.BOTH, expand=True)
        header = ttk.Frame(body)
        header.pack(fill=tk.X, pady=(0, 14))
        title = ttk.Frame(header)
        title.pack(side=tk.LEFT)
        ttk.Label(title, text="图片识字", style="PageTitle.TLabel").pack(side=tk.LEFT)
        ttk.Label(title, text="截图直接粘贴 · 文字默认保存到桌面", style="Muted.TLabel").pack(side=tk.LEFT, padx=(16, 0))
        self.export_button = ttk.Menubutton(header, text="批量导出")
        self.export_button.pack(side=tk.RIGHT)
        menu = tk.Menu(self.export_button, tearoff=False)
        menu.add_command(label="每张照片分别保存 TXT", command=self.export_each)
        menu.add_command(label="按列表顺序合并 TXT", command=self.export_merged)
        menu.add_separator()
        menu.add_command(label="复制全部合并文字", command=self.copy_merged)
        self.export_button.config(menu=menu)

        toolbar = ttk.Frame(body, style="Panel.TFrame", padding=(14, 10))
        toolbar.pack(fill=tk.X)
        self.choose_button = ttk.Button(toolbar, text="＋ 添加照片", command=self.choose_photo, style="Compact.TButton")
        self.choose_button.pack(side=tk.LEFT)
        self.paste_button = ttk.Button(toolbar, text="粘贴图片", command=self.paste_clipboard, style="Compact.TButton")
        self.paste_button.pack(side=tk.LEFT, padx=(8, 0))
        self.folder_button = ttk.Button(toolbar, text="导入文件夹", command=self.choose_folder, style="Compact.TButton")
        self.folder_button.pack(side=tk.LEFT, padx=(8, 16))
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=(0, 16))
        ttk.Label(toolbar, text="识别语言", style="CardMuted.TLabel").pack(side=tk.LEFT, padx=(0, 8))
        self.language = tk.StringVar(value="中文＋英文")
        self.language_box = ttk.Combobox(toolbar, textvariable=self.language,
                                        values=list(LANGUAGES), state="readonly", width=10)
        self.language_box.pack(side=tk.LEFT)
        self.recognize_button = ttk.Button(toolbar, text="开始批量识别", command=self.run, style="Primary.TButton")
        self.recognize_button.pack(side=tk.RIGHT)
        info = ttk.Frame(body)
        info.pack(fill=tk.X, pady=(10, 12))
        self.summary_label = ttk.Label(info, text="添加照片开始识别，已有文字会自动保留。", style="Small.TLabel")
        self.summary_label.pack(side=tk.LEFT)
        ttk.Label(info, text="切换照片自动保留本次修改", style="Small.TLabel").pack(side=tk.RIGHT)

        footer = ttk.Frame(body, style="Card.TFrame", padding=(14, 10))
        footer.pack(side=tk.BOTTOM, fill=tk.X, pady=(12, 0))
        self.status = ttk.Label(footer, text="就绪 · 添加照片或文件夹，开始批量识别。",
                                style="CardSmall.TLabel", wraplength=940)
        self.status.pack(anchor=tk.W, pady=(0, 8))
        self.progress = ttk.Progressbar(footer, mode="determinate")
        self.progress.pack(fill=tk.X)
        content = ttk.Frame(body)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(0, weight=0, minsize=208)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(0, weight=1)

        listing = ttk.Frame(content, style="Panel.TFrame", padding=(12, 14))
        listing.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self.list_label = ttk.Label(listing, text="照片队列 · 0", style="Heading.TLabel")
        self.list_label.pack(anchor=tk.W, pady=(0, 10))
        self.retry_button = ttk.Button(listing, text="仅重试失败项", command=self.run_failed, style="Compact.TButton")
        self.retry_button.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        manage = ttk.Frame(listing, style="Card.TFrame")
        manage.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))
        self.up_button = ttk.Button(manage, text="上移", command=lambda: self.move(-1), style="Compact.TButton")
        self.up_button.pack(side=tk.LEFT)
        self.down_button = ttk.Button(manage, text="下移", command=lambda: self.move(1), style="Compact.TButton")
        self.down_button.pack(side=tk.LEFT, padx=6)
        self.remove_button = ttk.Button(manage, text="移除", command=self.remove_current, style="Compact.TButton")
        self.remove_button.pack(side=tk.LEFT)
        table = ttk.Frame(listing, style="Card.TFrame")
        table.pack(fill=tk.BOTH, expand=True)
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.files = ttk.Treeview(table, columns=("name", "status"), show="headings", selectmode="browse", height=6,
                                  style="Queue.Treeview")
        self.files.heading("name", text="照片")
        self.files.heading("status", text="状态")
        self.files.column("name", width=125, minwidth=100)
        self.files.column("status", width=66, minwidth=60, stretch=False)
        scroll = ttk.Scrollbar(table, command=self.files.yview, style="Slim.Vertical.TScrollbar")
        horizontal = ttk.Scrollbar(table, orient=tk.HORIZONTAL, command=self.files.xview, style="Slim.Horizontal.TScrollbar")
        self.files.config(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.files.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.files.bind("<<TreeviewSelect>>", self.select_record)
        self.files.tag_configure("failed", foreground="#B35313")
        self.files.tag_configure("done", foreground="#147D59")
        self.empty_queue = ttk.Label(self.files, text="还没有照片\n\n添加照片、粘贴截图\n或导入整个文件夹。\n列表中可按 Ctrl+V", style="CardMuted.TLabel",
                                     anchor=tk.CENTER, justify=tk.CENTER, wraplength=150)

        self.preview_panes = ttk.Panedwindow(content, orient=tk.HORIZONTAL)
        self.preview_panes.grid(row=0, column=1, sticky="nsew")
        photo = ttk.Frame(self.preview_panes, style="Panel.TFrame", padding=(14, 14))
        self.preview_panes.add(photo, weight=5)
        photo_head = ttk.Frame(photo, style="Card.TFrame")
        photo_head.pack(fill=tk.X)
        ttk.Label(photo_head, text="原图预览", style="Heading.TLabel").pack(side=tk.LEFT)
        self.zoom_button = ttk.Button(photo_head, text="放大", style="Link.TButton", command=self.open_preview)
        self.zoom_button.pack(side=tk.RIGHT)
        self.filename = ttk.Label(photo, text="尚未选择照片", style="CardSmall.TLabel", wraplength=240)
        self.filename.pack(anchor=tk.W, pady=(8, 12))
        self.current_button = ttk.Button(photo, text="重新识别当前照片", command=self.run_current, style="Compact.TButton")
        self.current_button.pack(side=tk.BOTTOM, fill=tk.X, pady=(12, 0))
        self.photo_note = ttk.Label(photo, text="使用原图识别；拖动分隔线调整预览宽度。", style="CardSmall.TLabel", wraplength=240)
        self.photo_note.pack(side=tk.BOTTOM, anchor=tk.W, pady=(6, 0))
        self.meta_label = ttk.Label(photo, text="JPG / PNG / WebP / BMP / 单帧 TIFF", style="CardSmall.TLabel", wraplength=240)
        self.meta_label.pack(side=tk.BOTTOM, anchor=tk.W, pady=(10, 0))
        self.preview_stage = ttk.Frame(photo, style="Stage.TFrame", height=200)
        self.preview_stage.pack(fill=tk.BOTH, expand=True)
        self.preview = ttk.Label(self.preview_stage, text="照片预览\n\n选中左侧照片，开始对照校对。", anchor=tk.CENTER,
                                  justify=tk.CENTER, style="Stage.TLabel", wraplength=210)
        self.preview.place(relx=.5, rely=.5, anchor=tk.CENTER)
        self.preview.bind("<Double-1>", self.open_preview)
        self.preview_stage.bind("<Configure>", self.schedule_preview)
        photo.bind("<Configure>", self.resize_photo_labels)

        panel = ttk.Frame(self.preview_panes, style="Panel.TFrame", padding=(16, 14))
        self.preview_panes.add(panel, weight=6)
        result_head = ttk.Frame(panel, style="Card.TFrame")
        result_head.pack(fill=tk.X, pady=(0, 12))
        ttk.Label(result_head, text="识别文字 · 可编辑校对", style="Heading.TLabel").pack(side=tk.LEFT)
        self.result_badge = ttk.Label(result_head, text="等待照片", style="NeutralBadge.TLabel")
        self.result_badge.pack(side=tk.RIGHT)
        bottom = ttk.Frame(panel, style="Card.TFrame")
        bottom.pack(side=tk.BOTTOM, fill=tk.X, pady=(12, 0))
        self.copy_button = ttk.Button(bottom, text="复制文字", command=self.copy_text, style="Compact.TButton")
        self.copy_button.pack(side=tk.LEFT)
        self.save_button = ttk.Button(bottom, text="另存 TXT", command=self.save_text, style="Compact.TButton")
        self.save_button.pack(side=tk.LEFT, padx=8)
        self.count_label = ttk.Label(bottom, text="0 字符", style="CardSmall.TLabel")
        self.count_label.pack(side=tk.RIGHT)
        self.result = ScrolledText(panel, wrap=tk.WORD, height=10, width=24, undo=True)
        style_text(self.result)
        self.result.configure(font=(FONT, 12), highlightthickness=0, padx=2, pady=4, spacing3=7)
        self.result.vbar.configure(width=8, borderwidth=0, relief="flat", background="#CCD6E5",
                                   troughcolor="#F5F7FB", activebackground="#CCD6E5")
        self.result.pack(fill=tk.BOTH, expand=True)
        self.empty_result = ttk.Label(self.result, text="识别文字将在这里显示\n\n点击“开始批量识别”，随后可直接编辑校对。",
                                      style="CardMuted.TLabel", justify=tk.CENTER, anchor=tk.CENTER, wraplength=300)
        self.empty_result.bind("<Button-1>", self.focus_result)
        self.result.bind("<<Modified>>", self.on_text_change)
        self.result.bind("<FocusIn>", lambda _event: self.empty_result.place_forget())
        self.result.bind("<FocusOut>", lambda _event: self.sync_empty_result())
        self.window.bind("<Destroy>", self.cleanup_preview, add="+")
        self.set_busy(False)
        self._bind_page_shortcuts(self.window)

    def _bind_page_shortcuts(self, parent):
        for widget in parent.winfo_children():
            tags = widget.bindtags()
            if str(self.window) not in tags:
                widget.bindtags((*tags[:-1], str(self.window), tags[-1]))
            self._bind_page_shortcuts(widget)

    @property
    def path(self):
        return self.records[self.current_index]["path"] if self.current_index is not None else None

    @property
    def saved_text(self):
        return self.records[self.current_index]["saved_text"] if self.current_index is not None else ""

    @saved_text.setter
    def saved_text(self, value):
        if self.current_index is not None:
            self.records[self.current_index]["saved_text"] = value

    def store_current(self):
        if self.current_index is not None and not self._loading:
            record = self.records[self.current_index]
            previous = record["text"]
            record["text"] = self.result.get("1.0", "end-1c")
            old_status = record["status"]
            if previous != record["text"] and old_status in ("待识别", "无文字", "人工填写"):
                record["status"] = "人工填写" if record["text"].strip() else "待识别"
            if old_status != record["status"] and self.files.exists(str(self.current_index)):
                self.files.set(str(self.current_index), "status", record["status"])

    def on_text_change(self, _event=None):
        if not self.result.edit_modified():
            return
        self.result.edit_modified(False)
        if not self._loading:
            self.store_current()
            self.count_label.config(text=f"{len(self.result.get('1.0', 'end-1c'))} 字符")
            self.sync_controls()

    def update_result_actions(self):
        enabled = not self.busy
        has_text = bool(self.result.get("1.0", "end-1c").strip()) and self.current_index is not None
        for button in (self.copy_button, self.save_button):
            button.config(state=tk.NORMAL if enabled and has_text else tk.DISABLED)
        self.export_button.config(state=tk.NORMAL if enabled and any(record["text"].strip() for record in self.records) else tk.DISABLED)
        record = self.records[self.current_index] if self.current_index is not None else None
        status = record["status"] if record else "等待照片"
        badge_style = "OrangeBadge.TLabel" if status == "失败" else ("GreenBadge.TLabel" if status in ("成功", "人工填写") else "NeutralBadge.TLabel")
        self.result_badge.config(text="已识别 · 请校对" if status == "成功" else status, style=badge_style)
        text = self.result.get("1.0", "end-1c")
        unsaved = record is not None and text.strip() and text != record["saved_text"]
        self.count_label.config(text=f"{len(text)} 字符" + (" · 待保存" if unsaved else ""))
        self.sync_empty_result()

    def refresh_list(self):
        for row in self.files.get_children():
            if int(row) >= len(self.records):
                self.files.delete(row)
        for index, record in enumerate(self.records):
            values = (f"{index + 1:02d}  {Path(record['path']).name}", record["status"])
            tags = ("failed",) if record["status"] == "失败" else (("done",) if record["status"] == "成功" else ())
            if self.files.exists(str(index)):
                self.files.item(str(index), values=values, tags=tags)
            else:
                self.files.insert("", tk.END, iid=str(index), values=values, tags=tags)
        if self.current_index is not None:
            self.files.selection_set(str(self.current_index))
        self.list_label.config(text=f"照片队列 · {len(self.records)}")
        self.sync_controls()

    def sync_controls(self):
        enabled = not self.busy
        pending = any(record["status"] in ("待识别", "失败", "无文字") and not record["text"].strip() for record in self.records)
        self.recognize_button.config(state=tk.NORMAL if enabled and pending else tk.DISABLED)
        self.retry_button.config(state=tk.NORMAL if enabled and any(record["status"] == "失败" for record in self.records) else tk.DISABLED)
        has_current = self.current_index is not None
        self.current_button.config(state=tk.NORMAL if enabled and has_current else tk.DISABLED)
        self.remove_button.config(state=tk.NORMAL if enabled and has_current else tk.DISABLED)
        self.up_button.config(state=tk.NORMAL if enabled and has_current and self.current_index > 0 else tk.DISABLED)
        self.down_button.config(state=tk.NORMAL if enabled and has_current and self.current_index < len(self.records) - 1 else tk.DISABLED)
        self.zoom_button.config(state=tk.NORMAL if self._preview_source is not None else tk.DISABLED)
        if self.records:
            self.empty_queue.place_forget()
        else:
            self.empty_queue.place(relx=.5, rely=.4, anchor=tk.CENTER)
        counts = {status: sum(record["status"] == status for record in self.records)
                  for status in ("待识别", "成功", "失败", "无文字", "人工填写", "识别中")}
        self.summary_label.config(text=f"共 {len(self.records)} 张   ·   待识别 {counts['待识别']}   ·   已识别 {counts['成功'] + counts['人工填写']}   ·   失败 {counts['失败']}   ·   无文字 {counts['无文字']}")
        self.update_result_actions()

    def confirm_discard(self, indices):
        self.store_current()
        unsaved = [self.records[index] for index in indices if self.records[index]["text"].strip()
                   and self.records[index]["text"] != self.records[index]["saved_text"]]
        if unsaved:
            return messagebox.askyesno("保留识别文字", f"有 {len(unsaved)} 张照片的文字尚未复制或保存。是否放弃这些文字并继续？", parent=self.window)
        return True

    def can_replace_result(self):
        return self.confirm_discard([self.current_index]) if self.current_index is not None else True

    def close(self):
        if self.busy:
            messagebox.showinfo("正在识别", "请等待本次批量识别完成后关闭。", parent=self.window)
            return
        if self.confirm_discard(range(len(self.records))):
            self.window.destroy()

    def set_busy(self, busy):
        self.busy = busy
        for button in (self.choose_button, self.folder_button, self.paste_button):
            button.config(state=tk.DISABLED if busy else tk.NORMAL)
        self.language_box.config(state=tk.DISABLED if busy else "readonly")
        self.result.config(state=tk.DISABLED if busy or self.current_index is None else tk.NORMAL)
        self.recognize_button.config(text="正在批量识别…" if busy else "开始批量识别")
        self.sync_controls()

    def choose_photo(self):
        paths = filedialog.askopenfilenames(parent=self.window, title="选择照片（可多选）",
            filetypes=[("图片文件", " ".join("*" + suffix for suffix in sorted(IMAGE_SUFFIXES)))])
        self.add_photos(paths)

    def paste_shortcut(self, event):
        if not is_text_input(event.widget):
            self.paste_clipboard()
            return "break"

    def paste_clipboard(self):
        if self.busy or self.app.processing:
            return
        try:
            self.add_photos(self.clipboard_import.read())
        except (ValueError, OSError) as error:
            messagebox.showinfo("无法粘贴", str(error), parent=self.window)

    def cleanup_clipboard(self, event):
        if event.widget == self.window:
            self.clipboard_import.cleanup()

    def choose_folder(self):
        folder = filedialog.askdirectory(parent=self.window, title="导入照片文件夹（包含子文件夹）")
        if folder:
            try:
                self.add_photos([path for path in sorted(Path(folder).rglob("*"))
                                 if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES])
            except OSError as error:
                messagebox.showerror("导入失败", str(error), parent=self.window)

    def add_photos(self, paths):
        if self.busy:
            return
        self.store_current()
        known = {os.path.normcase(record["path"]) for record in self.records}
        added, skipped = 0, 0
        for path in paths:
            source = Path(path).resolve()
            key = os.path.normcase(str(source))
            if key in known or not source.is_file() or source.suffix.lower() not in IMAGE_SUFFIXES:
                skipped += 1
                continue
            self.records.append(new_record(source))
            known.add(key)
            added += 1
        if self.current_index is None and self.records:
            self.current_index = 0
            self.show_current()
        self.refresh_list()
        if added or skipped:
            self.status.config(text=f"新增 {added} 张照片，跳过 {skipped} 个重复或不支持的文件。已有结果和人工修改已保留。")

    def load_photo(self, path):
        self.add_photos([path])

    def select_record(self, _event=None):
        selection = self.files.selection()
        if not selection:
            return
        index = int(selection[0])
        if index != self.current_index and index < len(self.records):
            self.store_current()
            self.current_index = index
            self.show_current()

    def show_text(self):
        self._loading = True
        try:
            self.result.config(state=tk.NORMAL)
            self.result.delete("1.0", tk.END)
            text = self.records[self.current_index]["text"] if self.current_index is not None else ""
            self.result.insert("1.0", text)
            self.result.edit_reset()
            self.result.edit_modified(False)
            self.count_label.config(text=f"{len(text)} 字符")
            self.result.config(state=tk.DISABLED if self.busy or self.current_index is None else tk.NORMAL)
        finally:
            self._loading = False
        self.sync_controls()

    def focus_result(self, _event=None):
        if self.current_index is not None and not self.busy:
            self.empty_result.place_forget()
            self.result.focus_set()

    def sync_empty_result(self):
        if not self.result.get("1.0", "end-1c").strip() and self.window.focus_get() is not self.result:
            self.empty_result.place(relx=.5, rely=.35, anchor=tk.CENTER)
        else:
            self.empty_result.place_forget()

    def resize_photo_labels(self, event):
        width = max(160, event.width - 30)
        self.filename.config(wraplength=width)
        self.meta_label.config(wraplength=width)
        self.photo_note.config(wraplength=width)

    def schedule_preview(self, _event=None):
        if self._preview_job is not None:
            self.window.after_cancel(self._preview_job)
        self._preview_job = self.window.after(60, self.fit_preview)

    def fit_preview(self):
        if self._preview_job is not None:
            self.window.after_cancel(self._preview_job)
        self._preview_job = None
        if self._preview_source is None:
            return
        from PIL import ImageTk
        # 保留一份原图副本，窗口变化时重新生成预览，避免反复缩放损失清晰度。
        width = max(80, self.preview_stage.winfo_width() - 20)
        height = max(80, self.preview_stage.winfo_height() - 20)
        thumbnail = self._preview_source.copy()
        try:
            thumbnail.thumbnail((width, height))
            self.preview_image = ImageTk.PhotoImage(thumbnail, master=self.window)
            self.preview.config(image=self.preview_image, text="")
        finally:
            thumbnail.close()

    def cleanup_preview(self, event):
        if event.widget is not self.window:
            return
        if self._preview_job is not None:
            self.window.after_cancel(self._preview_job)
            self._preview_job = None
        if self._preview_source is not None:
            self._preview_source.close()
            self._preview_source = None

    def open_preview(self, _event=None):
        if self._preview_source is None:
            return
        if self._image_viewer is not None and self._image_viewer.winfo_exists():
            self._image_viewer.lift()
            return
        from PIL import ImageTk
        original = self._preview_source.copy()
        viewer = ttk.Frame(self.window)
        self._image_viewer = viewer
        viewer.place(x=0, y=0, relwidth=1, relheight=1)
        viewer.lift()
        top = ttk.Frame(viewer, padding=(18, 12))
        top.pack(fill=tk.X)
        ttk.Button(top, text="← 返回校对", command=viewer.destroy).pack(side=tk.LEFT, padx=(0, 16))
        ttk.Label(top, text=Path(self.path).name, font=(FONT, 11, "bold"), wraplength=560).pack(side=tk.LEFT)
        ttk.Label(top, text="仅查看原图 · 不修改文件", style="Small.TLabel").pack(side=tk.RIGHT)
        canvas = tk.Canvas(viewer, background="#E9EEF5", highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True, padx=18, pady=(0, 18))
        pending = [None]

        def render():
            pending[0] = None
            thumbnail = original.copy()
            try:
                thumbnail.thumbnail((max(80, canvas.winfo_width() - 32), max(80, canvas.winfo_height() - 32)))
                viewer.preview_image = ImageTk.PhotoImage(thumbnail, master=viewer)
                canvas.delete("all")
                canvas.create_image(canvas.winfo_width() / 2, canvas.winfo_height() / 2,
                                    anchor=tk.CENTER, image=viewer.preview_image)
            finally:
                thumbnail.close()

        def schedule(_event=None):
            if pending[0] is not None:
                viewer.after_cancel(pending[0])
            pending[0] = viewer.after(60, render)

        def cleanup(event):
            if event.widget is viewer:
                if pending[0] is not None:
                    viewer.after_cancel(pending[0])
                original.close()
                self._image_viewer = None

        canvas.bind("<Configure>", schedule)
        viewer.bind("<Destroy>", cleanup, add="+")
        canvas.bind("<Escape>", lambda _event: viewer.destroy())
        canvas.focus_set()

    def show_current(self):
        from PIL import Image, ImageOps
        self.show_text()
        self.preview_image = None
        if self._preview_source is not None:
            self._preview_source.close()
            self._preview_source = None
        if self.current_index is None:
            self.filename.config(text="尚未选择照片")
            self.preview.config(image="", text="照片预览\n\n选中左侧照片，开始对照校对。")
            self.meta_label.config(text="JPG / PNG / WebP / BMP / 单帧 TIFF")
            self.photo_note.config(text="识别使用原图，预览自动适应窗口。")
            self.sync_controls()
            return
        record = self.records[self.current_index]
        self.filename.config(text=Path(record["path"]).name)
        try:
            with Image.open(record["path"]) as source:
                if getattr(source, "n_frames", 1) > 1:
                    raise ValueError("多帧图片请先拆帧")
                with ImageOps.exif_transpose(source) as oriented:
                    self.meta_label.config(text=f"{oriented.width} × {oriented.height} 像素 · 原图")
                    self._preview_source = oriented.copy()
            self.photo_note.config(text=record["error"] or "识别使用原图，预览自动适应窗口。")
            self.fit_preview()
            self.schedule_preview()
        except Exception as error:
            self.preview.config(image="", text="无法预览这张照片")
            self.meta_label.config(text="请检查文件是否完整")
            self.photo_note.config(text=describe_ocr_error(error))
        self.sync_controls()

    def move(self, offset):
        if self.busy or self.current_index is None:
            return
        old, new = self.current_index, self.current_index + offset
        if 0 <= new < len(self.records):
            self.store_current()
            self.records[old], self.records[new] = self.records[new], self.records[old]
            self.current_index = new
            self.refresh_list()
            self.files.see(str(new))

    def remove_current(self):
        if self.busy or self.current_index is None or not self.can_replace_result():
            return
        del self.records[self.current_index]
        self.current_index = min(self.current_index, len(self.records) - 1) if self.records else None
        self.show_current()
        self.refresh_list()

    def run(self):
        self.store_current()
        indices = [index for index, record in enumerate(self.records)
                   if record["status"] in ("待识别", "失败", "无文字") and not record["text"].strip()]
        self.run_indices(indices)

    def run_current(self):
        self.run_indices([self.current_index] if self.current_index is not None else [])

    def run_failed(self):
        self.run_indices([index for index, record in enumerate(self.records) if record["status"] == "失败"])

    def run_indices(self, indices):
        if self.busy or self.app.processing or not indices or not self.confirm_discard(indices):
            return
        language = LANGUAGES[self.language.get()]
        jobs = [(index, self.records[index]["path"]) for index in indices]
        self.set_busy(True)
        self.progress.config(value=0, maximum=len(jobs))
        self.status.config(text=f"准备识别 {len(jobs)} 张照片…")

        def work():
            results = []
            try:
                for number, (index, path) in enumerate(jobs, 1):
                    self.app._post_ui(self.begin_record, index, number, len(jobs))
                    try:
                        text = extract_text_from_image(path, language) or ""
                        error = ""
                    except Exception as failure:
                        text, error = None, describe_ocr_error(failure)
                    results.append((index, text, error))
                    self.app._post_ui(self.apply_result, index, text, error, language)
                    self.app._post_ui(self.progress.config, value=number)
                self.app._post_ui(self.finish_batch, results)
            finally:
                self.app._finish_worker()

        if not self.app._start_worker(work):
            self.set_busy(False)

    def begin_record(self, index, number, total):
        self.records[index]["status"] = "识别中"
        self.refresh_list()
        self.status.config(text=f"正在识别 {number} / {total}：{Path(self.records[index]['path']).name}")

    def apply_result(self, index, text, error, language=""):
        record = self.records[index]
        record["language"] = language
        if error:
            record.update(status="失败", error=error)
        else:
            record.update(text=text, status="成功" if text.strip() else "无文字", error="")
        if index == self.current_index:
            self.show_text()
            self.photo_note.config(text=error or "识别使用原图，可对照右侧文字校对。")
        self.refresh_list()

    def finish_batch(self, results):
        self.set_busy(False)
        successful = sum(not error and bool(text.strip()) for _, text, error in results)
        failed = sum(bool(error) for _, _, error in results)
        empty = len(results) - successful - failed
        first_error = next((error for _, _, error in results if error), "")
        self.status.config(text=f"已处理 {len(results)} 张：成功 {successful}，失败 {failed}，无文字 {empty}。"
                           + ((first_error if len(results) == 1 else "选择失败照片可查看原因，或点击“仅重试失败项”。")
                              if first_error else "可逐张校对并批量导出。"))

    def complete(self, text, error):
        # 保留单张结果入口，供单张流程及既有回归测试调用。
        if self.current_index is None:
            return
        self.apply_result(self.current_index, text, error or "")
        self.finish_batch([(self.current_index, text, error or "")])

    def get_text(self):
        self.store_current()
        if self.current_index is None or not self.records[self.current_index]["text"].strip():
            messagebox.showinfo("提示", "当前照片暂无文字。", parent=self.window)
            return None
        return self.records[self.current_index]["text"]

    def copy_text(self):
        text = self.get_text()
        if text is not None:
            self.window.clipboard_clear()
            self.window.clipboard_append(text)
            self.saved_text = text
            self.sync_controls()
            self.status.config(text="已复制当前照片的文字。")

    def safe_text_target(self, path):
        key = os.path.normcase(str(Path(path).resolve()))
        if any(os.path.normcase(record["path"]) == key for record in self.records):
            raise ValueError("不能覆盖原照片，请另存为 TXT。")

    def save_text(self):
        text = self.get_text()
        if text is None:
            return
        path = filedialog.asksaveasfilename(parent=self.window, title="保存当前照片文字", defaultextension=".txt",
            initialdir=str(self.save_folder), initialfile=Path(self.path).stem + ".txt", filetypes=[("文本文件", "*.txt")])
        if path:
            try:
                self.safe_text_target(path)
                Path(path).write_text(result_text(self.records[self.current_index]), encoding="utf-8")
                self.save_folder = Path(path).parent
                self.saved_text = text
                self.sync_controls()
                self.status.config(text=f"文字已保存：{path}")
            except OSError as error:
                messagebox.showerror("保存失败", str(error), parent=self.window)
            except ValueError as error:
                messagebox.showerror("保存失败", str(error), parent=self.window)

    def export_each(self):
        if self.busy:
            return
        self.store_current()
        folder = filedialog.askdirectory(parent=self.window, title="分别保存 TXT（每图一份，同名自动加序号）",
                                         initialdir=str(self.save_folder))
        if not folder:
            return
        outputs, failures = export_separate(self.records, folder)
        if outputs:
            self.save_folder = Path(folder)
        for index, _path in outputs:
            self.records[index]["saved_text"] = self.records[index]["text"]
        skipped = len(self.records) - len(outputs) - len(failures)
        self.sync_controls()
        self.status.config(text=f"已保存 {len(outputs)} 份 TXT，跳过 {skipped} 项空结果，失败 {len(failures)} 项。输出位置：{folder}")
        if failures:
            messagebox.showwarning("部分导出失败", "\n".join(failures), parent=self.window)

    def export_merged(self):
        if self.busy:
            return
        self.store_current()
        text = merge_results(self.records)
        if not text:
            return
        path = filedialog.asksaveasfilename(parent=self.window, title="合并保存识别文字", defaultextension=".txt",
            initialdir=str(self.save_folder), initialfile="批量图片识别文字.txt", filetypes=[("文本文件", "*.txt")])
        if path:
            try:
                self.safe_text_target(path)
                Path(path).write_text(text, encoding="utf-8")
                self.save_folder = Path(path).parent
                self.mark_exported()
                self.status.config(text=f"已合并保存；按列表顺序，包含照片文件名，空结果跳过。位置：{path}")
            except (OSError, ValueError) as error:
                messagebox.showerror("导出失败", str(error), parent=self.window)

    def mark_exported(self):
        for record in self.records:
            if record["text"].strip():
                record["saved_text"] = record["text"]
        self.sync_controls()

    def copy_merged(self):
        if self.busy:
            return
        self.store_current()
        text = merge_results(self.records)
        if text:
            self.window.clipboard_clear()
            self.window.clipboard_append(text)
            self.mark_exported()
            self.status.config(text="已按列表顺序复制合并文字，空结果已跳过。")
