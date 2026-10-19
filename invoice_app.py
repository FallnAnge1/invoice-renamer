#!/usr/bin/env python3
"""发票识别与重命名 - Windows 图形界面

双击表格单元格可手动修正识别结果。
"""

from __future__ import annotations

import datetime
import csv
import logging
import os
import queue
import re
import shutil
import sys
import threading
import tempfile
import tkinter as tk
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from ocr_engine import prepare_ocr
from ui_theme import apply_theme, FONT
from invoice_validation import validate_invoice, update_validation
from rename_preview import build_rename_plan, RenamePreviewDialog, file_signature, path_key, rename_no_replace

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

MAX_TEXT_PAGES = 20
MAX_OCR_PAGES = 10
MAX_FILENAME_LENGTH = 180


# ======================================================================
# PDF 文本提取与发票信息识别
# ======================================================================

def extract_text_from_pdf(pdf_path: str) -> str:
    """用 pdfplumber 提取 PDF 文本，按页拼接返回。"""
    import pdfplumber

    full_text = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages[:MAX_TEXT_PAGES]:
            text = page.extract_text()
            if text:
                full_text.append(text)
    return "\n".join(full_text)


def extract_text_via_ocr(pdf_path: str) -> str:
    """将扫描 PDF 渲染为图片后，通过内置或系统 Tesseract 识别。"""
    import pypdfium2 as pdfium
    import pytesseract

    ocr_config = prepare_ocr()

    full_text = []
    document = pdfium.PdfDocument(pdf_path)
    try:
        for page_index in range(min(len(document), MAX_OCR_PAGES)):
            page = document[page_index]
            bitmap = page.render(scale=2.5)
            image = bitmap.to_pil()
            try:
                full_text.append(pytesseract.image_to_string(
                    image, lang="chi_sim+eng", config=ocr_config,
                ))
            finally:
                image.close()
                bitmap.close()
                page.close()
    finally:
        document.close()
    return "\n".join(full_text)


def find_buyer_name(text: str) -> str | None:
    """从发票文本中提取购买方名称。"""
    patterns = [
        r"购买方名称[：:]\s*(.+?)(?:\n|$)",
        r"购\s+名称[：:]\s*(.+?)\s+销",
        r"买\s+名称[：:]\s*(\S+?)\s+售",
        r"纳税人名称[：:]\s*([^\n]{4,40})",
        r"购.{0,50}?名称[：:]\s*([^\n]{2,40})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            name = match.group(1).strip()
            if name and len(name) >= 2 and not any(
                keyword in name
                for keyword in ["地址", "电话", "开户", "账号", "密码", "填写", "售", "销"]
            ):
                return name
    return None


def find_amount(text: str) -> str | None:
    """从发票文本中提取价税合计金额。"""
    patterns = [
        r"价税合计.*?[¥￥]\s*([-+]?[0-9A-Za-z][0-9A-Za-z,.]*)",
        r"小写.*?[¥￥]\s*([-+]?[0-9A-Za-z][0-9A-Za-z,.]*)",
        r"合计.*?[¥￥]\s*([-+]?[0-9A-Za-z][0-9A-Za-z,.]*)",
        r"[¥￥]\s*([-+]?[0-9A-Za-z][0-9A-Za-z,.]*)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            raw = match.group(1)
            values, errors, _ = validate_invoice({"buyer": "校验", "amount": raw})
            return raw if "amount" in errors else values["amount"]
    return None


def find_invoice_date(text: str) -> str | None:
    """提取开票日期，统一返回 YYYYMMDD，便于按日期排序。"""
    patterns = [
        r"开票日期[：:]?\s*(\d{4})\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})(?![0-9A-Za-z])",
        r"开票日期[：:]?\s*(\d{4})(\d{2})(\d{2})(?![0-9A-Za-z])",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            date = datetime.date(*(int(value) for value in match.groups()))
            return date.strftime("%Y%m%d")
        except ValueError:
            continue
    return None


def find_invoice_number(text: str) -> str | None:
    """提取发票号码；仅保留数字，避免误把校验码写入文件名。"""
    patterns = [
        r"发票号码[：:]?[ \t]*([^\r\n]+)",
        r"发票号[：:]?[ \t]*([^\r\n]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            raw = re.split(r"\s+(?=[\u4e00-\u9fff])", match.group(1).strip(), maxsplit=1)[0]
            number = re.sub(r"\s+", "", raw)
            if re.fullmatch(r"[0-9]{8,20}", number):
                return number
    return None


def sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符。"""
    illegal_chars = r'[<>:"/\\|?*]'
    name = re.sub(illegal_chars, "", name)
    name = re.sub(r"\s+", "", name).strip(". ")
    return name or "未命名"


def build_filename(buyer: str, amount: str, invoice_date: str = "", invoice_no: str = "") -> str:
    """生成便于检索且在 Windows 中可用的发票文件名。"""
    parts = []
    if invoice_date:
        parts.append(sanitize_filename(invoice_date))
    parts.extend([sanitize_filename(buyer), sanitize_filename(amount)])
    if invoice_no:
        parts.append(sanitize_filename(invoice_no)[-8:])

    stem = "_".join(parts)
    # 给扩展名和 Windows 完整路径留出余量，避免过长导致重命名失败。
    return f"{stem[:MAX_FILENAME_LENGTH]}.pdf"


def make_unique_path(original_path: str, filename: str) -> str:
    """生成不冲突的目标路径；原文件名相同时不额外加序号。"""
    source = Path(original_path)
    candidate = source.with_name(filename)
    if candidate == source or not candidate.exists():
        return str(candidate)

    for counter in range(2, 10_000):
        candidate = source.with_name(f"{Path(filename).stem}_{counter}.pdf")
        if not candidate.exists():
            return str(candidate)
    raise RuntimeError("同名文件过多，无法生成可用文件名")


def _safe_archive_path(dest_dir: str, member_name: str) -> Path:
    """防止压缩包内的 ../ 路径覆盖目标目录之外的文件。"""
    root = Path(dest_dir).resolve()
    member = Path(member_name)
    if member.is_absolute() or ".." in member.parts:
        raise ValueError(f"压缩包含不安全路径: {member_name}")
    target = (root / member).resolve()
    if os.path.commonpath([str(root), str(target)]) != str(root):
        raise ValueError(f"压缩包含不安全路径: {member_name}")
    return target


class InvoiceApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("发票与文档助手")
        self.root.geometry("1180x820")
        self.root.minsize(960, 700)
        apply_theme(root)

        # 数据存储：每项为 {path, filename, buyer, date, amount, invoice_no, status}
        self.items: list[dict] = []
        self.rename_history: list[dict] = []
        self.processing = False
        self._editor = None
        self._after_id = None
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.ui_events: queue.Queue = queue.Queue()

        self._build_toolbar()
        self._build_table()
        self._build_statusbar()
        self._refresh_table()
        self._after_id = self.root.after(50, self._drain_ui_events)

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _build_toolbar(self):
        header = ttk.Frame(self.root, padding=(24, 20, 24, 14))
        header.pack(fill=tk.X)
        titles = ttk.Frame(header)
        titles.pack(side=tk.LEFT)
        ttk.Label(titles, text="发票与文档助手", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(titles, text="整理发票、转换文件、提取照片文字，在一个地方完成。",
                  style="Muted.TLabel").pack(anchor=tk.W, pady=(5, 0))
        ttk.Label(header, text="本机处理 · 无需上传", style="Badge.TLabel").pack(side=tk.RIGHT)

        tools = ttk.Frame(self.root, padding=(24, 0, 24, 14))
        tools.pack(fill=tk.X)
        self.convert_button = ttk.Button(tools, text="格式转换  →", command=self.open_converter)
        self.convert_button.pack(side=tk.LEFT)
        self.image_ocr_button = ttk.Button(tools, text="图片识别文字  →", command=self.open_image_ocr)
        self.image_ocr_button.pack(side=tk.LEFT, padx=10)
        ttk.Label(tools, text="图片 / PDF 互转、合并拆分与中英文提取", style="Muted.TLabel").pack(side=tk.LEFT, padx=6)

        stats = ttk.Frame(self.root, padding=(24, 0, 24, 16))
        self.stats_frame = stats
        stats.pack(fill=tk.X)
        self.stat_values = []
        for index, label in enumerate(("全部文件", "待识别", "可重命名", "需复核")):
            stats.columnconfigure(index, weight=1, uniform="stats")
            card = ttk.Frame(stats, style="Card.TFrame", padding=(18, 12))
            card.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 10, 0))
            ttk.Label(card, text=label, style="CardMuted.TLabel").pack(anchor=tk.W)
            value = ttk.Label(card, text="0", style="Stat.TLabel")
            value.pack(anchor=tk.W, pady=(2, 0))
            self.stat_values.append(value)

        toolbar = ttk.Frame(self.root, padding=(24, 0, 24, 14))
        self.import_toolbar = toolbar
        toolbar.pack(fill=tk.X)
        self.add_files_button = ttk.Button(toolbar, text="01  添加 PDF", command=self.add_files, style="Compact.TButton")
        self.add_files_button.pack(side=tk.LEFT, padx=(0, 6))
        self.add_folder_button = ttk.Button(toolbar, text="文件夹", command=self.add_folder, style="Compact.TButton")
        self.add_folder_button.pack(side=tk.LEFT, padx=(0, 6))
        self.add_archive_button = ttk.Button(toolbar, text="压缩包", command=self.add_archive, style="Compact.TButton")
        self.add_archive_button.pack(side=tk.LEFT, padx=(0, 16))
        self.preview_button = ttk.Button(toolbar, text="02  识别校对", command=self.start_preview, style="Compact.TButton")
        self.preview_button.pack(side=tk.LEFT, padx=(0, 6))
        self.rename_button = ttk.Button(toolbar, text="03  命名预览", command=self.start_rename, style="Compact.Primary.TButton")
        self.rename_button.pack(side=tk.LEFT)
        self.clear_button = ttk.Button(toolbar, text="清空列表", command=self.clear_list, style="Compact.TButton")
        self.clear_button.pack(side=tk.RIGHT)
        self.export_button = ttk.Button(toolbar, text="导出记录", command=self.export_results, style="Compact.TButton")
        self.export_button.pack(side=tk.RIGHT, padx=6)
        self.undo_button = ttk.Button(toolbar, text="撤销重命名", command=self.undo_last_rename, style="Compact.TButton")
        self.undo_button.pack(side=tk.RIGHT)
        self.root.bind("<Configure>", self._responsive_layout)

    def _responsive_layout(self, event):
        if event.widget is not self.root:
            return
        if event.height < 780 and self.stats_frame.winfo_manager():
            self.stats_frame.pack_forget()
        elif event.height >= 780 and not self.stats_frame.winfo_manager():
            self.stats_frame.pack(fill=tk.X, before=self.import_toolbar)

    def open_image_ocr(self):
        if self.processing:
            return
        from image_ocr_dialog import ImageOCRDialog
        ImageOCRDialog(self)

    def open_converter(self):
        if self.processing:
            return
        from converter_dialog import ConverterDialog
        ConverterDialog(self)

    def _build_table(self):
        frame = ttk.Frame(self.root, padding=(24, 0, 24, 0))
        self.table_frame = frame
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        caption = ttk.Frame(frame)
        caption.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(caption, text="发票列表", font=(FONT, 11, "bold")).pack(side=tk.LEFT)
        ttk.Label(caption, text="双击字段修改 · 选中查看命名预览 · 右键管理文件", style="Muted.TLabel").pack(side=tk.RIGHT)
        columns = ("filename", "buyer", "date", "amount", "invoice_no", "status")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="extended")
        for name, title, width, minimum in (
            ("filename", "当前文件名", 255, 160), ("buyer", "购买方名称", 235, 150),
            ("date", "开票日期", 105, 90), ("amount", "价税合计", 100, 85),
            ("invoice_no", "发票号码", 185, 170), ("status", "处理状态", 115, 95),
        ):
            self.tree.heading(name, text=title)
            self.tree.column(name, width=width, minwidth=minimum, anchor=tk.W if name in ("filename", "buyer") else tk.CENTER)
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.tree.yview)
        horizontal = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=scrollbar.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")
        horizontal.grid(row=2, column=0, sticky="ew")
        self.empty_label = ttk.Label(self.tree, text="还没有发票文件\n从上方添加 PDF、文件夹或压缩包开始。",
                                     anchor=tk.CENTER, justify=tk.CENTER, style="CardMuted.TLabel")
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<<TreeviewSelect>>", self._show_selection)
        self.tree.bind("<Delete>", lambda _event: self.remove_selected())
        self.tree.bind("<Button-2>" if sys.platform == "darwin" else "<Button-3>", self._on_right_click)

    def _build_statusbar(self):
        bottom = ttk.Frame(self.root, padding=(24, 10, 24, 14))
        bottom.pack(side=tk.BOTTOM, fill=tk.X)
        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.pack(fill=tk.X, pady=(0, 8))
        self.status_label = ttk.Label(bottom, text="就绪 · 先导入文件，再识别和校对。", style="Muted.TLabel", wraplength=900)
        self.status_label.pack(anchor=tk.W)
        detail = ttk.Frame(self.root, style="Card.TFrame", padding=(18, 12))
        detail.pack(side=tk.BOTTOM, fill=tk.X, padx=24, pady=(10, 0))
        ttk.Label(detail, text="命名预览与处理说明", style="Heading.TLabel").pack(anchor=tk.W)
        self.detail_label = ttk.Label(detail, text="选择一份发票，查看完整路径、命名预览和问题说明。",
                                      style="CardMuted.TLabel", wraplength=880, justify=tk.LEFT)
        self.detail_label.pack(anchor=tk.W, pady=(6, 0))
        detail.bind("<Configure>", lambda event: self.detail_label.config(wraplength=max(300, event.width - 36)))
        self.table_frame.pack_forget()
        self.table_frame.pack(fill=tk.BOTH, expand=True)

    def close(self):
        if self.processing:
            messagebox.showinfo("任务进行中", "请等待当前任务结束后关闭，避免中断文件处理。", parent=self.root)
            return
        if self._after_id:
            self.root.after_cancel(self._after_id)
        self.root.destroy()

    def _sync_actions(self):
        ready = not self.processing
        has_files = bool(self.items)
        states = {
            self.preview_button: ready and any(it["status"] in ("待处理", "失败") for it in self.items),
            self.rename_button: ready and has_files,
            self.export_button: ready and has_files,
            self.clear_button: ready and has_files,
            self.undo_button: ready and bool(self.rename_history),
        }
        for button, enabled in states.items():
            button.config(state=tk.NORMAL if enabled else tk.DISABLED)

    def _show_selection(self, _event=None):
        selected = self.tree.selection()
        if not selected:
            self.detail_label.config(text="选择一份发票，查看完整路径、命名预览和问题说明。")
            return
        index = int(selected[0])
        if index >= len(self.items):
            return
        item = self.items[index]
        values, errors, warnings = validate_invoice(item)
        name = (build_filename(values["buyer"], values["amount"], values["date"], values["invoice_no"])
                if not errors else "先修正字段，再预览目标文件名")
        text = f"目标文件名：{name}\n当前位置：{item['path']}"
        messages = list(errors.values()) if item["status"] != "待处理" else []
        if item.get("error") and item["error"] not in "；".join(messages):
            messages.insert(0, item["error"])
        if messages:
            text += "\n需处理：" + "；".join(messages)
        elif warnings and item["status"] != "待处理":
            text += "\n命名提醒：" + "；".join(warnings.values())
        self.detail_label.config(text=text)

    # ------------------------------------------------------------------
    # 表格数据操作
    # ------------------------------------------------------------------

    def _insert_item(self, filepath: str):
        """添加一个 PDF 文件到列表（去重）。"""
        filepath = os.path.abspath(filepath)
        if not Path(filepath).is_file() or Path(filepath).suffix.lower() != ".pdf":
            return False
        if any(os.path.normcase(it["path"]) == os.path.normcase(filepath) for it in self.items):
            return False
        self.items.append({
            "path": filepath,
            "filename": os.path.basename(filepath),
            "buyer": "",
            "date": "",
            "amount": "",
            "invoice_no": "",
            "status": "待处理",
            "error": "",
        })
        return True

    def _refresh_table(self):
        """用 self.items 刷新 Treeview。"""
        selected_paths = {self.items[int(row)]["path"] for row in self.tree.selection()
                          if int(row) < len(self.items)}
        view = self.tree.yview()
        for row in self.tree.get_children():
            self.tree.delete(row)

        for i, item in enumerate(self.items):
            tags = ("even" if i % 2 == 0 else "odd",)
            status_text = {"成功": "可预览命名", "失败": "需复核", "待处理": "待识别"}.get(item["status"], item["status"])
            _, validation_errors, _ = validate_invoice(item)
            mark = lambda field: item[field] + (" [异常]" if field in validation_errors and item[field] else "")
            if item["status"] in ("成功", "已重命名"):
                tags += ("success",)
            elif item["status"] == "失败":
                tags += ("fail",)
            self.tree.insert(
                "",
                tk.END,
                iid=str(i),
                values=(
                    item["filename"],
                    mark("buyer"),
                    mark("date"),
                    mark("amount"),
                    mark("invoice_no"),
                    status_text,
                ),
                tags=tags,
            )

            if item["path"] in selected_paths:
                self.tree.selection_add(str(i))
        self.tree.tag_configure("even", background="#FFFFFF")
        self.tree.tag_configure("odd", background="#F7F9FD")
        self.tree.tag_configure("success", foreground="#147D59")
        self.tree.tag_configure("fail", foreground="#B35313")
        if view:
            self.tree.yview_moveto(view[0])
        if self.items:
            self.empty_label.place_forget()
        else:
            self.empty_label.place(relx=.5, rely=.5, anchor=tk.CENTER)
        counts = [len(self.items), sum(it["status"] == "待处理" for it in self.items),
                  sum(it["status"] == "成功" for it in self.items),
                  sum(it["status"] == "失败" for it in self.items)]
        for label, count in zip(self.stat_values, counts):
            label.config(text=str(count))
        self._sync_actions()
        self._show_selection()

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------

    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="选择 PDF 发票文件",
            filetypes=[("PDF 文件", "*.pdf")],
        )
        if not paths:
            return
        count = sum(self._insert_item(p) for p in paths)
        self._refresh_table()
        self._set_status(f"新增 {count} 个 PDF，跳过 {len(paths) - count} 个重复或无效文件。")

    def add_folder(self):
        folder = filedialog.askdirectory(title="选择包含 PDF 发票的文件夹")
        if not folder:
            return
        self._start_worker(lambda: self._run_folder(folder))

    def _run_folder(self, folder):
        try:
            count = 0
            for pdf_path in sorted(Path(folder).rglob("*")):
                if pdf_path.is_file() and pdf_path.suffix.lower() == ".pdf":
                    count += int(self._insert_item(str(pdf_path)))
            self._set_status(f"从文件夹（含子文件夹）新增 {count} 个 PDF，重复文件已跳过。")
        except OSError as error:
            self._set_status(f"导入文件夹失败：{error}")
        finally:
            self._post_ui(self._refresh_table)
            self._finish_worker()

    def add_archive(self):
        """添加压缩包，自动解压到桌面并导入 PDF。"""
        paths = filedialog.askopenfilenames(
            title="选择压缩包",
            filetypes=[
                ("压缩文件", "*.zip;*.rar;*.7z"),
                ("ZIP 文件", "*.zip"),
                ("RAR 文件", "*.rar"),
                ("7Z 文件", "*.7z"),
                ("所有文件", "*.*"),
            ],
        )
        if not paths:
            return

        self._start_worker(lambda: self._run_archives(paths))

    def _run_archives(self, paths):
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            desktop = Path.home() / "Desktop"
            desktop.mkdir(parents=True, exist_ok=True)
            extract_root = Path(tempfile.mkdtemp(prefix=f"发票提取_{timestamp}_", dir=desktop))
            failed = []
            self._set_progress(0, len(paths))
            for index, archive_path in enumerate(paths):
                name = Path(archive_path).name
                self._set_status(f"正在解压：{name} ({index + 1}/{len(paths)})")
                sub_dir = extract_root / f"{index + 1:02d}_{Path(name).stem}"
                sub_dir.mkdir(parents=True)
                try:
                    self._extract_archive(archive_path, str(sub_dir))
                except Exception as error:
                    failed.append(f"{name}: {error}")
                self._set_progress(index + 1)
            imported = sum(int(self._insert_item(str(path))) for path in sorted(extract_root.rglob("*"))
                           if path.is_file() and path.suffix.lower() == ".pdf")
            self._set_status(f"从压缩包新增 {imported} 个 PDF，输出位置：{extract_root}")
            if failed:
                self._post_ui(messagebox.showwarning, "解压问题", "以下压缩包未完整解压：\n\n" + "\n".join(failed))
        except OSError as error:
            self._set_status(f"导入压缩包失败：{error}")
        finally:
            self._post_ui(self._refresh_table)
            self._finish_worker()

    def _extract_archive(self, archive_path: str, dest_dir: str) -> int:
        """解压压缩包到目标目录，返回解压出的 PDF 数量。"""
        ext = os.path.splitext(archive_path)[1].lower()

        if ext == ".zip":
            with zipfile.ZipFile(archive_path, "r") as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    target = _safe_archive_path(dest_dir, info.filename)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as source, target.open("wb") as destination:
                        shutil.copyfileobj(source, destination)

        elif ext == ".rar":
            import rarfile
            with rarfile.RarFile(archive_path, "r") as rf:
                for info in rf.infolist():
                    if info.isdir():
                        continue
                    target = _safe_archive_path(dest_dir, info.filename)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with rf.open(info) as source, target.open("wb") as destination:
                        shutil.copyfileobj(source, destination)

        elif ext == ".7z":
            import py7zr
            with py7zr.SevenZipFile(archive_path, "r") as szf:
                for member_name in szf.getnames():
                    _safe_archive_path(dest_dir, member_name)
                szf.extractall(dest_dir)

        else:
            raise ValueError(f"不支持的压缩格式: {ext}")

        return sum(
            1 for path in Path(dest_dir).rglob("*")
            if path.is_file() and path.suffix.lower() == ".pdf"
        )

    def clear_list(self):
        if self.processing:
            return
        if self.items and not messagebox.askyesno("清空列表", "仅移除列表记录，原文件会保留。是否清空？", parent=self.root):
            return
        if self._editor is not None:
            editor, self._editor = self._editor, None
            editor.destroy()
        self.items.clear()
        self._refresh_table()
        self.progress["value"] = 0
        self._set_status("已清空")

    def _on_double_click(self, event):
        """双击单元格进入编辑模式。"""
        if self.processing or self._editor is not None:
            return
        region = self.tree.identify_region(event.x, event.y)
        if region != "cell":
            return

        column = self.tree.identify_column(event.x)
        item_id = self.tree.identify_row(event.y)
        if not item_id:
            return

        col_idx = int(column.lstrip("#")) - 1
        # 仅允许编辑识别字段；文件名和状态由程序维护。
        if col_idx not in (1, 2, 3, 4):
            return

        col_name = ["filename", "buyer", "date", "amount", "invoice_no", "status"][col_idx]
        bbox = self.tree.bbox(item_id, column)

        current = self.items[int(item_id)].get(col_name, "")

        entry = ttk.Entry(self.tree)
        self._editor = entry
        entry.place(x=bbox[0], y=bbox[1], width=bbox[2], height=bbox[3])
        entry.insert(0, current)
        entry.select_range(0, tk.END)
        entry.focus_set()

        def save_edit(*_):
            if self._editor is not entry:
                return
            self._editor = None
            new_val = entry.get().strip()
            entry.destroy()
            self._apply_edit(int(item_id), col_name, new_val)

        def cancel_edit(_event=None):
            if self._editor is entry:
                self._editor = None
                entry.destroy()

        entry.bind("<Return>", save_edit)
        entry.bind("<FocusOut>", save_edit)
        entry.bind("<Escape>", cancel_edit)

    def _apply_edit(self, index, field, value):
        item = self.items[index]
        item[field] = value
        update_validation(item)
        self._refresh_table()

    def _on_right_click(self, event):
        """右键菜单仅从列表移除，不删除磁盘文件。"""
        if self.processing:
            return
        item_id = self.tree.identify_row(event.y)
        if item_id:
            if item_id not in self.tree.selection():
                self.tree.selection_set(item_id)
            menu = tk.Menu(self.root, tearoff=False)
            menu.add_command(label="从列表移除所选（保留原文件）", command=self.remove_selected)
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

    def remove_selected(self):
        if self.processing or self._editor is not None:
            return
        selected = sorted((int(row) for row in self.tree.selection()), reverse=True)
        self.tree.selection_remove(self.tree.selection())
        for index in selected:
            del self.items[index]
        self._refresh_table()
        if selected:
            self._set_status(f"已从列表移除 {len(selected)} 个文件，原文件保留。")

    # ------------------------------------------------------------------
    # 识别与重命名（线程执行）
    # ------------------------------------------------------------------

    def _post_ui(self, callback, *args, **kwargs):
        """从工作线程投递界面任务，不直接调用任何 Tk 方法。"""
        self.ui_events.put((callback, args, kwargs))

    def _drain_ui_events(self):
        """仅由 Tk 主线程执行队列中的界面更新。"""
        try:
            while True:
                callback, args, kwargs = self.ui_events.get_nowait()
                callback(*args, **kwargs)
        except queue.Empty:
            pass
        self._after_id = self.root.after(50, self._drain_ui_events)

    def _set_status(self, text: str):
        self._post_ui(self.status_label.config, text=text)

    def _set_progress(self, value: int, maximum: int | None = None):
        def update():
            if maximum is not None:
                self.progress["maximum"] = maximum
            self.progress["value"] = value
        self._post_ui(update)

    def _set_processing(self, processing: bool):
        self.processing = processing
        state = tk.DISABLED if processing else tk.NORMAL
        for button in (
            self.add_files_button, self.add_folder_button, self.add_archive_button,
            self.preview_button, self.rename_button, self.export_button,
            self.undo_button, self.clear_button, self.convert_button, self.image_ocr_button,
        ):
            button.config(state=state)
        self._sync_actions()

    def _start_worker(self, target):
        if self._editor is not None:
            self._editor.event_generate("<FocusOut>")
        if self.processing:
            messagebox.showinfo("提示", "当前任务尚未完成，请稍候。")
            return False
        self._set_processing(True)
        threading.Thread(target=target, daemon=True).start()
        return True

    def _finish_worker(self):
        self._post_ui(self._set_processing, False)

    def _recognize_one(self, item: dict) -> bool:
        """识别单个 PDF，结果写回 item。"""
        item["error"] = ""
        for field in ("buyer", "amount", "date", "invoice_no"):
            item[field] = ""
        try:
            text = extract_text_from_pdf(item["path"])

            if not text or len(text.strip()) < 10:
                item["error"] = "PDF 无文字（可能是扫描件）"
                try:
                    text = extract_text_via_ocr(item["path"])
                except Exception as e:
                    item["error"] = f"OCR 失败: {e}"
                    item["status"] = "失败"
                    return False

            buyer = find_buyer_name(text)
            amount = find_amount(text)
            invoice_date = find_invoice_date(text)
            invoice_no = find_invoice_number(text)
            # 有标签但格式无法识别时保留原值，交由校验提示，避免把异常当成可选字段缺失。
            if not invoice_date:
                raw = re.search(r"开票日期[：:]?[ \t]*([^\r\n]{1,40})", text)
                invoice_date = raw.group(1).strip() if raw else None
            if not invoice_no:
                raw = re.search(r"(?:发票号码|发票号)[：:]?[ \t]*([^\r\n]{1,40})", text)
                invoice_no = raw.group(1).strip() if raw else None

            if buyer:
                item["buyer"] = buyer
            if amount:
                item["amount"] = amount
            if invoice_date:
                item["date"] = invoice_date
            if invoice_no:
                item["invoice_no"] = invoice_no

            return update_validation(item)
        except ImportError as e:
            item["status"] = "失败"
            item["error"] = f"缺少依赖库: {e}"
            return False
        except Exception as e:
            item["status"] = "失败"
            item["error"] = str(e)[:80]
            return False

    def start_preview(self):
        if self.processing:
            return
        if not self.items:
            messagebox.showinfo("提示", "请先添加 PDF 文件。")
            return
        self._start_worker(self._run_preview)

    def _run_preview(self):
        pending = [item for item in self.items if item["status"] in ("待处理", "失败")]
        total = len(pending)
        self._set_progress(0, total)
        try:
            for i, item in enumerate(pending):
                self._set_status(f"正在识别: {item['filename']} ({i + 1}/{total})")
                self._recognize_one(item)
                self._set_progress(i + 1)
                self._post_ui(self._refresh_table)

            ok = sum(1 for it in pending if it["status"] == "成功")
            self._set_status(f"预览完成：{ok}/{total} 识别成功")

            # 汇总错误，用户也可通过“导出结果”留存全部明细。
            errors = [(it["filename"], it.get("error", "")) for it in pending if it["status"] == "失败"]
            if errors:
                msg = "\n".join(f"  {f}: {e}" for f, e in errors)
                self._post_ui(messagebox.showwarning, "识别问题", f"以下文件未能识别：\n\n{msg}")
        finally:
            self._finish_worker()

    def start_rename(self):
        if self.processing:
            return
        if self._editor is not None:
            self._editor.event_generate("<FocusOut>")
        if not self.items:
            messagebox.showinfo("提示", "请先添加 PDF 文件。")
            return
        plan = build_rename_plan(self.items, build_filename)
        RenamePreviewDialog(self, plan)

    def _run_rename(self, plan=None):
        # 界面始终传入用户确认过的计划；无参数路径供内部流程和回归测试使用。
        if plan is None:
            plan = build_rename_plan(self.items, build_filename)
        pending = [entry for entry in plan if entry["action"] == "rename"]
        total = len(pending)
        skipped = len(plan) - total
        self._set_progress(0, total)
        renamed, failed, history = 0, [], []
        try:
            for position, entry in enumerate(pending, 1):
                item = self.items[entry["index"]]
                old_path, new_path = entry["source"], entry["target"]
                self._set_status(f"正在重命名：{Path(old_path).name} ({position}/{total})")
                try:
                    values, errors, _ = validate_invoice(item)
                    if errors or values != entry["fields"] or path_key(item["path"]) != path_key(old_path):
                        raise RuntimeError("预览后记录已改变，请重新预览")
                    if file_signature(old_path) != entry["signature"]:
                        raise RuntimeError("预览后源文件已改变，请重新核对")
                    rename_no_replace(old_path, new_path)
                    item.update(entry["fields"])
                    item.update(path=new_path, filename=Path(new_path).name, status="已重命名", error="")
                    history.append({"old_path": old_path, "new_path": new_path})
                    renamed += 1
                except (OSError, RuntimeError) as error:
                    item["status"] = "失败"
                    item["error"] = f"重命名未执行：{error}"
                    failed.append(f"{Path(old_path).name}：{error}")
                self._set_progress(position)
                self._post_ui(self._refresh_table)
            if history:
                self.rename_history = history
            summary = f"修改 {renamed} 项，跳过 {skipped} 项，执行失败 {len(failed)} 项。"
            self._set_status("重命名完成：" + summary)
            self._post_ui(messagebox.showinfo, "重命名完成", summary +
                ("\n\n" + "\n".join(failed) if failed else "\n可在本次打开软件期间撤销上次修改。"))
        finally:
            self._finish_worker()

    def export_results(self):
        """导出识别与处理记录，便于复核、留档或交接。"""
        if not self.items:
            messagebox.showinfo("提示", "没有可导出的结果。")
            return

        default_name = f"发票识别结果_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv"
        target = filedialog.asksaveasfilename(
            title="导出识别结果",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV 文件", "*.csv")],
        )
        if not target:
            return

        try:
            with open(target, "w", newline="", encoding="utf-8-sig") as fp:
                writer = csv.DictWriter(
                    fp,
                    fieldnames=[
                        "当前路径", "当前文件名", "购买方名称", "开票日期", "价税合计",
                        "发票号码", "状态", "错误说明",
                    ],
                )
                writer.writeheader()
                for item in self.items:
                    writer.writerow({
                        "当前路径": item["path"],
                        "当前文件名": item["filename"],
                        "购买方名称": item["buyer"],
                        "开票日期": item["date"],
                        "价税合计": item["amount"],
                        "发票号码": item["invoice_no"],
                        "状态": item["status"],
                        "错误说明": item.get("error", ""),
                    })
            self._set_status(f"已导出结果：{target}")
            messagebox.showinfo("导出完成", f"识别结果已导出到：\n{target}")
        except OSError as exc:
            messagebox.showerror("导出失败", f"无法保存文件：\n{exc}")

    def undo_last_rename(self):
        """撤销本次运行中最近一次批量重命名。"""
        if self.processing:
            return
        if not self.rename_history:
            messagebox.showinfo("提示", "本次打开软件后还没有可撤销的重命名操作。")
            return
        if not messagebox.askokcancel(
            "确认撤销", f"将尝试恢复 {len(self.rename_history)} 个文件的原文件名，是否继续？"
        ):
            return
        self._start_worker(self._run_undo)

    def _run_undo(self):
        history = list(self.rename_history)
        restored = 0
        failed = []
        failed_records = []
        self._set_progress(0, len(history))
        try:
            for index, record in enumerate(reversed(history), start=1):
                old_path = record["old_path"]
                new_path = record["new_path"]
                try:
                    if not os.path.exists(new_path):
                        raise FileNotFoundError("找不到已重命名文件")
                    if os.path.exists(old_path):
                        raise FileExistsError("原文件名已被其他文件占用")
                    os.rename(new_path, old_path)
                    for item in self.items:
                        if item["path"] == new_path:
                            item["path"] = old_path
                            item["filename"] = os.path.basename(old_path)
                            item["status"] = "成功"
                            item["error"] = ""
                            break
                    restored += 1
                except OSError as exc:
                    failed.append(f"{os.path.basename(new_path)}: {exc}")
                    failed_records.append(record)
                self._set_progress(index)
                self._post_ui(self._refresh_table)

            self.rename_history = failed_records
            self._set_status(f"撤销完成：{restored}/{len(history)} 个文件已恢复")
            details = "" if not failed else "\n\n未恢复：\n" + "\n".join(failed)
            self._post_ui(
                messagebox.showinfo, "撤销完成", f"已恢复 {restored}/{len(history)} 个文件。{details}"
            )
        finally:
            self._finish_worker()


def main():
    root = tk.Tk()

    # Windows 任务栏图标（可选）
    try:
        root.iconbitmap(default="invoice.ico")
    except Exception:
        pass

    app = InvoiceApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
