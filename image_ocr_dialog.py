"""批量照片转文字；逐项结果独立保存，切换照片不丢失人工修改。"""
import os
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from format_converter import IMAGE_SUFFIXES
from ocr_engine import extract_text_from_image
from batch_ocr import new_record, merge_results, export_separate, result_text
from ui_theme import heading, style_text, FONT

LANGUAGES = {"中文＋英文": "chi_sim+eng", "中文": "chi_sim", "英文": "eng"}


class ImageOCRDialog:
    def __init__(self, app):
        self.app = app
        self.records = []
        self.current_index = None
        self.busy = False
        self._loading = False
        self.preview_image = None
        self.window = tk.Toplevel(app.root)
        self.window.title("批量图片识别文字 · 发票与文档助手")
        self.window.geometry("1240x800")
        self.window.minsize(1060, 680)
        self.window.transient(app.root)
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        body = ttk.Frame(self.window, padding=24)
        body.pack(fill=tk.BOTH, expand=True)
        heading(body, "批量图片识别文字", "一次添加多张照片，逐张校对；切换照片保留修改，支持分别或合并导出。")
        toolbar = ttk.Frame(body)
        toolbar.pack(fill=tk.X, pady=(0, 18))
        self.choose_button = ttk.Button(toolbar, text="添加照片", command=self.choose_photo)
        self.choose_button.pack(side=tk.LEFT)
        self.folder_button = ttk.Button(toolbar, text="导入文件夹", command=self.choose_folder)
        self.folder_button.pack(side=tk.LEFT, padx=8)
        ttk.Label(toolbar, text="识别语言", style="Muted.TLabel").pack(side=tk.LEFT, padx=(8, 6))
        self.language = tk.StringVar(value="中文＋英文")
        self.language_box = ttk.Combobox(toolbar, textvariable=self.language,
                                        values=list(LANGUAGES), state="readonly", width=12)
        self.language_box.pack(side=tk.LEFT)
        self.recognize_button = ttk.Button(toolbar, text="开始批量识别", command=self.run, style="Primary.TButton")
        self.recognize_button.pack(side=tk.RIGHT)
        self.status = ttk.Label(body, text="本机识别 · 无需上传 · 批量识别会跳过已有文字的记录。",
                                style="Muted.TLabel", wraplength=980)
        self.status.pack(side=tk.BOTTOM, anchor=tk.W, pady=(10, 0))
        self.progress = ttk.Progressbar(body, mode="determinate")
        self.progress.pack(side=tk.BOTTOM, fill=tk.X, pady=(14, 0))
        content = ttk.Frame(body)
        content.pack(fill=tk.BOTH, expand=True)
        for column, weight in enumerate((24, 30, 46)):
            content.columnconfigure(column, weight=weight, uniform="panes")
        content.rowconfigure(0, weight=1)

        listing = ttk.Frame(content)
        listing.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self.list_label = ttk.Label(listing, text="照片列表 · 0 张", font=(FONT, 11, "bold"))
        self.list_label.pack(anchor=tk.W, pady=(0, 8))
        self.retry_button = ttk.Button(listing, text="仅重试失败项", command=self.run_failed)
        self.retry_button.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        manage = ttk.Frame(listing)
        manage.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))
        self.up_button = ttk.Button(manage, text="上移", command=lambda: self.move(-1), style="Compact.TButton")
        self.up_button.pack(side=tk.LEFT)
        self.down_button = ttk.Button(manage, text="下移", command=lambda: self.move(1), style="Compact.TButton")
        self.down_button.pack(side=tk.LEFT, padx=6)
        self.remove_button = ttk.Button(manage, text="移除", command=self.remove_current, style="Compact.TButton")
        self.remove_button.pack(side=tk.LEFT)
        table = ttk.Frame(listing)
        table.pack(fill=tk.BOTH, expand=True)
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.files = ttk.Treeview(table, columns=("name", "status"), show="headings", selectmode="browse", height=6)
        self.files.heading("name", text="照片名称")
        self.files.heading("status", text="状态")
        self.files.column("name", width=145, minwidth=95)
        self.files.column("status", width=80, minwidth=70)
        scroll = ttk.Scrollbar(table, command=self.files.yview)
        horizontal = ttk.Scrollbar(table, orient=tk.HORIZONTAL, command=self.files.xview)
        self.files.config(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.files.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.files.bind("<<TreeviewSelect>>", self.select_record)
        self.files.tag_configure("failed", foreground="#B35313")
        self.files.tag_configure("done", foreground="#147D59")

        photo = ttk.Frame(content, style="Card.TFrame", padding=16)
        photo.grid(row=0, column=1, sticky="nsew", padx=(0, 14))
        ttk.Label(photo, text="原始照片", style="Heading.TLabel").pack(anchor=tk.W)
        self.filename = ttk.Label(photo, text="尚未选择照片", style="CardMuted.TLabel", wraplength=240)
        self.filename.pack(anchor=tk.W, pady=(8, 0))
        self.current_button = ttk.Button(photo, text="重新识别当前", command=self.run_current)
        self.current_button.pack(side=tk.BOTTOM, fill=tk.X, pady=(12, 0))
        self.meta_label = ttk.Label(photo, text="支持 JPG、PNG、WebP、BMP、单帧 TIFF。", style="CardMuted.TLabel", wraplength=240)
        self.meta_label.pack(side=tk.BOTTOM, anchor=tk.W)
        self.preview = ttk.Label(photo, text="从左侧选择照片预览", anchor=tk.CENTER,
                                  justify=tk.CENTER, style="CardMuted.TLabel", wraplength=230)
        self.preview.pack(fill=tk.BOTH, expand=True, pady=14)

        panel = ttk.Frame(content)
        panel.grid(row=0, column=2, sticky="nsew")
        result_head = ttk.Frame(panel)
        result_head.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(result_head, text="当前照片文字", font=(FONT, 11, "bold")).pack(side=tk.LEFT)
        self.count_label = ttk.Label(result_head, text="0 字符", style="Muted.TLabel")
        self.count_label.pack(side=tk.RIGHT)
        bottom = ttk.Frame(panel)
        bottom.pack(side=tk.BOTTOM, fill=tk.X, pady=(12, 0))
        self.copy_button = ttk.Button(bottom, text="复制当前", command=self.copy_text, style="Compact.TButton")
        self.copy_button.pack(side=tk.LEFT)
        self.save_button = ttk.Button(bottom, text="保存当前 TXT", command=self.save_text, style="Compact.TButton")
        self.save_button.pack(side=tk.LEFT, padx=8)
        self.export_button = ttk.Menubutton(bottom, text="批量导出")
        self.export_button.pack(side=tk.RIGHT)
        menu = tk.Menu(self.export_button, tearoff=False)
        menu.add_command(label="分别保存 TXT（每图一份）", command=self.export_each)
        menu.add_command(label="合并保存 TXT（按列表顺序）", command=self.export_merged)
        menu.add_separator()
        menu.add_command(label="复制合并文字", command=self.copy_merged)
        self.export_button.config(menu=menu)
        self.result = ScrolledText(panel, wrap=tk.WORD, height=10, width=24, undo=True)
        style_text(self.result)
        self.result.pack(fill=tk.BOTH, expand=True)
        self.result.bind("<<Modified>>", self.on_text_change)
        self.set_busy(False)

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
        self.list_label.config(text=f"照片列表 · {len(self.records)} 张")
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
        for button in (self.choose_button, self.folder_button):
            button.config(state=tk.DISABLED if busy else tk.NORMAL)
        self.language_box.config(state=tk.DISABLED if busy else "readonly")
        self.result.config(state=tk.DISABLED if busy or self.current_index is None else tk.NORMAL)
        self.recognize_button.config(text="正在批量识别…" if busy else "开始批量识别")
        self.sync_controls()

    def choose_photo(self):
        paths = filedialog.askopenfilenames(parent=self.window, title="选择照片（可多选）",
            filetypes=[("图片文件", " ".join("*" + suffix for suffix in sorted(IMAGE_SUFFIXES)))])
        self.add_photos(paths)

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

    def show_current(self):
        from PIL import Image, ImageOps, ImageTk
        self.show_text()
        self.preview_image = None
        if self.current_index is None:
            self.filename.config(text="尚未选择照片")
            self.preview.config(image="", text="从左侧选择照片预览")
            self.meta_label.config(text="支持 JPG、PNG、WebP、BMP、单帧 TIFF。")
            return
        record = self.records[self.current_index]
        self.filename.config(text=Path(record["path"]).name)
        try:
            with Image.open(record["path"]) as source:
                if getattr(source, "n_frames", 1) > 1:
                    raise ValueError("多帧图片请先拆帧")
                with ImageOps.exif_transpose(source) as oriented:
                    dimensions = f"{oriented.width} × {oriented.height} 像素"
                    oriented.thumbnail((230, 300))
                    self.preview_image = ImageTk.PhotoImage(oriented, master=self.window)
            self.preview.config(image=self.preview_image, text="")
            self.meta_label.config(text=dimensions + "\n" + (record["error"] or "识别使用原图；切换照片保留修改。"))
        except Exception as error:
            self.preview.config(image="", text="无法预览这张照片")
            self.meta_label.config(text=str(error))

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
                        text, error = None, str(failure)
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
            self.meta_label.config(text=error or "识别完成，文字可编辑校对。")
        self.refresh_list()

    def finish_batch(self, results):
        self.set_busy(False)
        successful = sum(not error and bool(text.strip()) for _, text, error in results)
        failed = sum(bool(error) for _, _, error in results)
        empty = len(results) - successful - failed
        first_error = next((error for _, _, error in results if error), "")
        self.status.config(text=f"已处理 {len(results)} 张：成功 {successful}，失败 {failed}，无文字 {empty}。"
                           + ("首个失败：" + first_error if first_error else "可逐张校对并批量导出。"))

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
            initialfile=Path(self.path).stem + ".txt", filetypes=[("文本文件", "*.txt")])
        if path:
            try:
                self.safe_text_target(path)
                Path(path).write_text(result_text(self.records[self.current_index]), encoding="utf-8")
                self.saved_text = text
                self.status.config(text=f"文字已保存：{path}")
            except OSError as error:
                messagebox.showerror("保存失败", str(error), parent=self.window)
            except ValueError as error:
                messagebox.showerror("保存失败", str(error), parent=self.window)

    def export_each(self):
        if self.busy:
            return
        self.store_current()
        folder = filedialog.askdirectory(parent=self.window, title="分别保存 TXT（每图一份，同名自动加序号）")
        if not folder:
            return
        outputs, failures = export_separate(self.records, folder)
        for index, _path in outputs:
            self.records[index]["saved_text"] = self.records[index]["text"]
        skipped = len(self.records) - len(outputs) - len(failures)
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
            initialfile="批量图片识别文字.txt", filetypes=[("文本文件", "*.txt")])
        if path:
            try:
                self.safe_text_target(path)
                Path(path).write_text(text, encoding="utf-8")
                self.mark_exported()
                self.status.config(text=f"已合并保存；按列表顺序，包含照片文件名，空结果跳过。位置：{path}")
            except (OSError, ValueError) as error:
                messagebox.showerror("导出失败", str(error), parent=self.window)

    def mark_exported(self):
        for record in self.records:
            if record["text"].strip():
                record["saved_text"] = record["text"]

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
