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
import tkinter as tk
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

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
    """将 PDF 转为图片后用 OCR 识别文本（扫描件备选方案）。
    需要: brew install tesseract tesseract-lang
    """
    from pdf2image import convert_from_path
    import pytesseract

    try:
        pytesseract.get_tesseract_version()
    except pytesseract.TesseractNotFoundError:
        raise RuntimeError(
            "tesseract 未安装。安装方法:\n"
            "  brew install tesseract tesseract-lang"
        )

    try:
        images = convert_from_path(
            pdf_path, dpi=250, first_page=1, last_page=MAX_OCR_PAGES,
            fmt="jpeg", thread_count=2,
        )
    except Exception as exc:
        if "poppler" in str(exc).lower():
            raise RuntimeError(
                "扫描件识别还需要安装 Poppler。Windows 请安装 Poppler 并加入 PATH，"
                "然后重新打开软件。"
            ) from exc
        raise
    full_text = []
    for img in images:
        text = pytesseract.image_to_string(img, lang="chi_sim+eng")
        full_text.append(text)
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
        r"价税合计.*?[¥￥]\s*([\d,]+\.\d{2})",
        r"小写.*?[¥￥]\s*([\d,]+\.\d{2})",
        r"合计.*?[¥￥]\s*([\d,]+\.\d{2})",
        r"[¥￥]\s*([\d,]+\.\d{2})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            amount = match.group(1).replace(",", "")
            return amount
    return None


def find_invoice_date(text: str) -> str | None:
    """提取开票日期，统一返回 YYYYMMDD，便于按日期排序。"""
    patterns = [
        r"开票日期[：:]?\s*(\d{4})\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})",
        r"开票日期[：:]?\s*(\d{4})(\d{2})(\d{2})",
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
        r"发票号码[：:]?\s*([0-9\s]{8,24})",
        r"发票号[：:]?\s*([0-9\s]{8,24})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            number = re.sub(r"\s+", "", match.group(1))
            if 8 <= len(number) <= 20:
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
        self.root.title("发票识别与重命名工具")
        self.root.geometry("1120x600")
        self.root.minsize(700, 400)

        # 数据存储：每项为 {path, filename, buyer, date, amount, invoice_no, status}
        self.items: list[dict] = []
        self.rename_history: list[dict] = []
        self.processing = False
        self.ui_events: queue.Queue = queue.Queue()

        self._build_toolbar()
        self._build_table()
        self._build_statusbar()
        self.root.after(50, self._drain_ui_events)

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _build_toolbar(self):
        toolbar = ttk.Frame(self.root, padding=10)
        toolbar.pack(fill=tk.X)

        self.add_files_button = ttk.Button(
            toolbar, text="添加 PDF 文件", command=self.add_files
        )
        self.add_files_button.pack(side=tk.LEFT, padx=(0, 6))

        self.add_folder_button = ttk.Button(
            toolbar, text="添加文件夹", command=self.add_folder
        )
        self.add_folder_button.pack(side=tk.LEFT, padx=(0, 6))

        self.add_archive_button = ttk.Button(
            toolbar, text="添加压缩包", command=self.add_archive
        )
        self.add_archive_button.pack(side=tk.LEFT, padx=(0, 20))

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        self.preview_button = ttk.Button(
            toolbar, text="预览识别结果", command=self.start_preview
        )
        self.preview_button.pack(side=tk.LEFT, padx=(10, 6))

        self.rename_button = ttk.Button(
            toolbar, text="执行重命名", command=self.start_rename
        )
        self.rename_button.pack(side=tk.LEFT, padx=(0, 6))

        self.export_button = ttk.Button(
            toolbar, text="导出结果", command=self.export_results
        )
        self.export_button.pack(side=tk.LEFT, padx=(0, 6))

        self.undo_button = ttk.Button(
            toolbar, text="撤销上次重命名", command=self.undo_last_rename
        )
        self.undo_button.pack(side=tk.LEFT, padx=(0, 6))

        self.clear_button = ttk.Button(
            toolbar, text="清空列表", command=self.clear_list
        )
        self.clear_button.pack(side=tk.RIGHT)

    def _build_table(self):
        """发票列表表格，支持双击编辑。"""
        frame = ttk.Frame(self.root, padding=(10, 0))
        frame.pack(fill=tk.BOTH, expand=True)

        columns = ("filename", "buyer", "date", "amount", "invoice_no", "status")
        self.tree = ttk.Treeview(
            frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )

        self.tree.heading("filename", text="文件名")
        self.tree.heading("buyer", text="购买方名称")
        self.tree.heading("date", text="开票日期")
        self.tree.heading("amount", text="金额")
        self.tree.heading("invoice_no", text="发票号")
        self.tree.heading("status", text="状态")

        self.tree.column("filename", width=260, minwidth=150)
        self.tree.column("buyer", width=240, minwidth=120)
        self.tree.column("date", width=100, minwidth=80, anchor=tk.CENTER)
        self.tree.column("amount", width=120, minwidth=80, anchor=tk.CENTER)
        self.tree.column("invoice_no", width=120, minwidth=100, anchor=tk.CENTER)
        self.tree.column("status", width=110, minwidth=80, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 双击编辑
        self.tree.bind("<Double-1>", self._on_double_click)
        # 右键删除
        self.tree.bind("<Button-2>" if sys.platform == "darwin" else "<Button-3>", self._on_right_click)

    def _build_statusbar(self):
        """底部状态栏：进度条 + 状态文字。"""
        bottom = ttk.Frame(self.root, padding=(10, 6))
        bottom.pack(fill=tk.X)

        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.pack(fill=tk.X, pady=(0, 4))

        self.status_label = ttk.Label(bottom, text="就绪")
        self.status_label.pack(anchor=tk.W)

    # ------------------------------------------------------------------
    # 表格数据操作
    # ------------------------------------------------------------------

    def _insert_item(self, filepath: str):
        """添加一个 PDF 文件到列表（去重）。"""
        filepath = os.path.abspath(filepath)
        if any(it["path"] == filepath for it in self.items):
            return
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

    def _refresh_table(self):
        """用 self.items 刷新 Treeview。"""
        for row in self.tree.get_children():
            self.tree.delete(row)

        for i, item in enumerate(self.items):
            tags = ()
            status_text = item["status"]
            if item["status"] == "失败" and item.get("error"):
                status_text = item["error"][:30]
            elif item["status"] in ("成功", "已重命名"):
                tags = ("success",)
            elif item["status"] == "失败":
                tags = ("fail",)
            self.tree.insert(
                "",
                tk.END,
                iid=str(i),
                values=(
                    item["filename"],
                    item["buyer"],
                    item["date"],
                    item["amount"],
                    item["invoice_no"],
                    status_text,
                ),
                tags=tags,
            )

        self.tree.tag_configure("success", foreground="green")
        self.tree.tag_configure("fail", foreground="red")

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------

    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="选择 PDF 发票文件",
            filetypes=[("PDF 文件", "*.pdf"), ("所有文件", "*.*")],
        )
        for p in paths:
            self._insert_item(p)
        self._refresh_table()
        self._set_status(f"已添加 {len(paths)} 个文件")

    def add_folder(self):
        folder = filedialog.askdirectory(title="选择包含 PDF 发票的文件夹")
        if not folder:
            return
        count = 0
        for pdf_path in sorted(Path(folder).rglob("*")):
            if pdf_path.is_file() and pdf_path.suffix.lower() == ".pdf":
                self._insert_item(str(pdf_path))
                count += 1
        self._refresh_table()
        self._set_status(f"从文件夹（含子文件夹）导入了 {count} 个 PDF")

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

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        extract_root = os.path.join(desktop, f"发票提取_{timestamp}")
        os.makedirs(extract_root, exist_ok=True)

        failed = []
        for archive_path in paths:
            name = os.path.basename(archive_path)
            self._set_status(f"正在解压: {name}")
            # 每个压缩包解压到独立子目录
            sub_dir = os.path.join(extract_root, os.path.splitext(name)[0])
            os.makedirs(sub_dir, exist_ok=True)
            try:
                self._extract_archive(archive_path, sub_dir)
            except Exception as e:
                failed.append(f"{name}: {e}")

        # 递归导入所有解压出的 PDF
        imported = 0
        for pdf_path in sorted(Path(extract_root).rglob("*")):
            if pdf_path.is_file() and pdf_path.suffix.lower() == ".pdf":
                self._insert_item(str(pdf_path))
                imported += 1

        self._refresh_table()

        if imported > 0:
            self._set_status(f"从压缩包导入了 {imported} 个 PDF，已解压到: {extract_root}")
        else:
            self._set_status(f"压缩包中未找到 PDF 文件")

        if failed:
            msg = "\n".join(failed)
            messagebox.showwarning("解压问题", f"以下压缩包处理失败：\n\n{msg}")

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
        self.items.clear()
        self._refresh_table()
        self.progress["value"] = 0
        self._set_status("已清空")

    def _on_double_click(self, event):
        """双击单元格进入编辑模式。"""
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
        entry.place(x=bbox[0], y=bbox[1], width=bbox[2], height=bbox[3])
        entry.insert(0, current)
        entry.select_range(0, tk.END)
        entry.focus_set()

        def save_edit(*_):
            new_val = entry.get().strip()
            self.items[int(item_id)][col_name] = new_val
            entry.destroy()
            self._refresh_table()

        entry.bind("<Return>", save_edit)
        entry.bind("<FocusOut>", save_edit)
        entry.bind("<Escape>", lambda e: entry.destroy())

    def _on_right_click(self, event):
        """右键删除行。"""
        if self.processing:
            return
        item_id = self.tree.identify_row(event.y)
        if item_id:
            self.tree.delete(item_id)
            del self.items[int(item_id)]
            self._refresh_table()

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
        self.root.after(50, self._drain_ui_events)

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
            self.undo_button, self.clear_button,
        ):
            button.config(state=state)

    def _start_worker(self, target):
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

            if not buyer and not amount:
                item["error"] = "未匹配到购买方和金额"
            elif not buyer:
                item["error"] = "未匹配到购买方名称"
            elif not amount:
                item["error"] = "未匹配到金额"

            if buyer:
                item["buyer"] = buyer
            if amount:
                item["amount"] = amount
            if invoice_date:
                item["date"] = invoice_date
            if invoice_no:
                item["invoice_no"] = invoice_no

            item["status"] = "成功" if (buyer and amount) else "失败"
            return item["status"] == "成功"
        except ImportError as e:
            item["status"] = "失败"
            item["error"] = f"缺少依赖库: {e}"
            return False
        except Exception as e:
            item["status"] = "失败"
            item["error"] = str(e)[:80]
            return False

    def start_preview(self):
        if not self.items:
            messagebox.showinfo("提示", "请先添加 PDF 文件。")
            return
        self._start_worker(self._run_preview)

    def _run_preview(self):
        total = len(self.items)
        self._set_progress(0, total)
        try:
            for i, item in enumerate(self.items):
                self._set_status(f"正在识别: {item['filename']} ({i + 1}/{total})")
                self._recognize_one(item)
                self._set_progress(i + 1)
                self._post_ui(self._refresh_table)

            ok = sum(1 for it in self.items if it["status"] == "成功")
            self._set_status(f"预览完成：{ok}/{total} 识别成功")

            # 汇总错误，用户也可通过“导出结果”留存全部明细。
            errors = [(it["filename"], it.get("error", "")) for it in self.items if it["status"] == "失败"]
            if errors:
                msg = "\n".join(f"  {f}: {e}" for f, e in errors)
                self._post_ui(messagebox.showwarning, "识别问题", f"以下文件未能识别：\n\n{msg}")
        finally:
            self._finish_worker()

    def start_rename(self):
        if not self.items:
            messagebox.showinfo("提示", "请先添加 PDF 文件。")
            return

        pending = [it for it in self.items if it["status"] == "成功"]
        if not pending:
            messagebox.showinfo("提示", "没有可重命名的文件。请先预览识别结果。")
            return

        ok = messagebox.askokcancel(
            "确认重命名",
            f"将重命名 {len(pending)} 个文件，是否继续？\n\n"
            "文件名格式：开票日期_购买方名称_金额_发票号后8位.pdf\n"
            "（未识别到日期或发票号时会自动省略）\n"
            "重名自动加序号后缀。"
        )
        if not ok:
            return

        self._start_worker(self._run_rename)

    def _run_rename(self):
        pending = [(i, it) for i, it in enumerate(self.items) if it["status"] == "成功"]
        total = len(pending)
        self._set_progress(0, total)
        renamed = 0
        history = []

        try:
            for idx, (_, item) in enumerate(pending):
                self._set_status(f"正在重命名: {item['filename']} ({idx + 1}/{total})")
                old_path = item["path"]
                new_name = build_filename(
                    item["buyer"], item["amount"], item["date"], item["invoice_no"]
                )
                new_path = make_unique_path(old_path, new_name)

                try:
                    os.rename(old_path, new_path)
                    item["path"] = new_path
                    item["filename"] = os.path.basename(new_path)
                    item["status"] = "已重命名"
                    item["error"] = ""
                    history.append({"old_path": old_path, "new_path": new_path})
                    renamed += 1
                except OSError as exc:
                    item["status"] = "失败"
                    item["error"] = f"重命名失败: {exc}"

                self._set_progress(idx + 1)
                self._post_ui(self._refresh_table)

            if history:
                self.rename_history = history
            self._set_status(f"重命名完成：{renamed}/{total} 个文件")
            self._post_ui(
                messagebox.showinfo, "完成",
                f"成功重命名 {renamed}/{total} 个文件。\n可在本次打开软件期间撤销上次重命名。",
            )
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
