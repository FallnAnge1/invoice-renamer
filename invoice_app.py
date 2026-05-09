#!/usr/bin/env python3
"""发票识别与重命名 - Windows 图形界面

双击表格单元格可手动修正识别结果。
"""

from __future__ import annotations

import os
import re
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# 导入核心识别函数（兼容 PyInstaller 打包）
if getattr(sys, "frozen", False):
    _base = sys._MEIPASS
else:
    _base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _base)
from rename_invoices import (
    extract_text_from_pdf,
    extract_text_via_ocr,
    find_buyer_name,
    find_amount,
    sanitize_filename,
)


class InvoiceApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("发票识别与重命名工具")
        self.root.geometry("960x600")
        self.root.minsize(700, 400)

        # 数据存储：每项为 {path, filename, buyer, amount, status}
        self.items: list[dict] = []

        self._build_toolbar()
        self._build_table()
        self._build_statusbar()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _build_toolbar(self):
        toolbar = ttk.Frame(self.root, padding=10)
        toolbar.pack(fill=tk.X)

        ttk.Button(
            toolbar, text="添加 PDF 文件", command=self.add_files
        ).pack(side=tk.LEFT, padx=(0, 6))

        ttk.Button(
            toolbar, text="添加文件夹", command=self.add_folder
        ).pack(side=tk.LEFT, padx=(0, 20))

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        ttk.Button(
            toolbar, text="预览识别结果", command=self.start_preview
        ).pack(side=tk.LEFT, padx=(10, 6))

        ttk.Button(
            toolbar, text="执行重命名", command=self.start_rename
        ).pack(side=tk.LEFT, padx=(0, 6))

        ttk.Button(
            toolbar, text="清空列表", command=self.clear_list
        ).pack(side=tk.RIGHT)

    def _build_table(self):
        """发票列表表格，支持双击编辑。"""
        frame = ttk.Frame(self.root, padding=(10, 0))
        frame.pack(fill=tk.BOTH, expand=True)

        columns = ("filename", "buyer", "amount", "status")
        self.tree = ttk.Treeview(
            frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )

        self.tree.heading("filename", text="文件名")
        self.tree.heading("buyer", text="购买方名称")
        self.tree.heading("amount", text="金额")
        self.tree.heading("status", text="状态")

        self.tree.column("filename", width=300, minwidth=150)
        self.tree.column("buyer", width=280, minwidth=120)
        self.tree.column("amount", width=120, minwidth=80, anchor=tk.CENTER)
        self.tree.column("status", width=80, minwidth=60, anchor=tk.CENTER)

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
            "amount": "",
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
            elif item["status"] == "成功":
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
                    item["amount"],
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
        for f in sorted(os.listdir(folder)):
            if f.lower().endswith(".pdf"):
                self._insert_item(os.path.join(folder, f))
                count += 1
        self._refresh_table()
        self._set_status(f"从文件夹导入了 {count} 个 PDF")

    def clear_list(self):
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
        # 仅允许编辑「购买方名称」和「金额」列
        if col_idx not in (1, 2):
            return

        col_name = ["filename", "buyer", "amount", "status"][col_idx]
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
        item_id = self.tree.identify_row(event.y)
        if item_id:
            self.tree.delete(item_id)
            del self.items[int(item_id)]
            self._refresh_table()

    # ------------------------------------------------------------------
    # 识别与重命名（线程执行）
    # ------------------------------------------------------------------

    def _set_status(self, text: str):
        self.status_label.config(text=text)

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
        threading.Thread(target=self._run_preview, daemon=True).start()

    def _run_preview(self):
        total = len(self.items)
        self.progress["maximum"] = total
        self.progress["value"] = 0

        for i, item in enumerate(self.items):
            self._set_status(f"正在识别: {item['filename']} ({i + 1}/{total})")
            self._recognize_one(item)
            self.progress["value"] = i + 1
            self.root.after(0, self._refresh_table)

        ok = sum(1 for it in self.items if it["status"] == "成功")
        self._set_status(f"预览完成：{ok}/{total} 识别成功")

        # 汇总错误
        errors = [(it["filename"], it.get("error", "")) for it in self.items if it["status"] == "失败"]
        if errors:
            msg = "\n".join(f"  {f}: {e}" for f, e in errors)
            self.root.after(0, lambda: messagebox.showwarning("识别问题", f"以下文件未能识别：\n\n{msg}"))

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
            "文件名格式：购买方名称_金额.pdf \n"
            "重名自动加序号后缀。"
        )
        if not ok:
            return

        threading.Thread(target=self._run_rename, daemon=True).start()

    def _run_rename(self):
        pending = [(i, it) for i, it in enumerate(self.items) if it["status"] == "成功"]
        total = len(pending)
        self.progress["maximum"] = total
        self.progress["value"] = 0
        renamed = 0

        for idx, (pos, item) in enumerate(pending):
            self._set_status(f"正在重命名: {item['filename']} ({idx + 1}/{total})")

            name = sanitize_filename(item["buyer"])
            new_name = f"{name}_{item['amount']}.pdf"
            new_path = os.path.join(os.path.dirname(item["path"]), new_name)

            # 冲突处理
            if os.path.exists(new_path) and new_path != item["path"]:
                base = f"{name}_{item['amount']}"
                counter = 2
                while os.path.exists(new_path):
                    new_name = f"{base}_{counter}.pdf"
                    new_path = os.path.join(os.path.dirname(item["path"]), new_name)
                    counter += 1

            try:
                os.rename(item["path"], new_path)
                item["path"] = new_path
                item["filename"] = new_name
                renamed += 1
            except OSError as e:
                item["status"] = "失败"

            self.progress["value"] = idx + 1
            self.root.after(0, self._refresh_table)

        self._set_status(f"重命名完成：{renamed}/{total} 个文件")
        self.root.after(0, lambda: messagebox.showinfo("完成", f"成功重命名 {renamed}/{total} 个文件。"))


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
