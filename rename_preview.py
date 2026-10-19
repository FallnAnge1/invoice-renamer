"""只读生成命名计划，用户确认后按同一目标路径执行。"""
import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from invoice_validation import validate_invoice
from ui_theme import heading


def path_key(path):
    return os.path.normcase(os.path.abspath(path))


def file_signature(path):
    info = Path(path).stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def build_rename_plan(items, filename_builder):
    """预留本批次目标名，和已存在的磁盘文件一起检查，绝不写入文件。"""
    plan, reserved, seen = [], set(), set()
    for index, item in enumerate(items):
        source = Path(item["path"]).absolute()
        values, errors, warnings = validate_invoice(item)
        entry = {"index": index, "source": str(source), "target": "", "fields": values,
                 "errors": errors, "warnings": warnings, "action": "skip", "conflict": False,
                 "reason": "", "signature": None}
        plan.append(entry)
        key = path_key(source)
        if key in seen:
            entry["reason"] = "重复的源文件记录，跳过"
            continue
        seen.add(key)
        if item["status"] == "已重命名":
            entry["reason"] = "已完成重命名，跳过"
            continue
        if item["status"] == "待处理":
            entry["reason"] = "尚未识别，请先识别并校对"
            continue
        if errors:
            entry["reason"] = "；".join(errors.values())
            continue
        try:
            if source.suffix.lower() != ".pdf" or not source.is_file():
                raise ValueError("源 PDF 文件不存在或已移走")
            entry["signature"] = file_signature(source)
            filename = filename_builder(values["buyer"], values["amount"], values["date"], values["invoice_no"])
            target = source.with_name(filename)
            if path_key(target) == key:
                entry["target"] = str(target)
                entry["reason"] = "名称已符合规则，无需修改"
                continue
            for counter in range(1, 10000):
                target = source.with_name(filename if counter == 1 else f"{Path(filename).stem}_{counter}.pdf")
                if path_key(target) == key:
                    break
                if not os.path.lexists(target) and path_key(target) not in reserved:
                    break
            else:
                raise ValueError("同名文件过多，请先整理目标目录")
            if path_key(target) == key:
                entry.update(target=str(target), reason="名称已符合规则，无需修改")
                continue
            reserved.add(path_key(target))
            entry.update(target=str(target), action="rename", conflict=counter > 1)
            notes = (["磁盘或本批次重名，已自动加序号"] if counter > 1 else []) + list(warnings.values())
            entry["reason"] = "；".join(notes) if notes else "校验通过"
        except (OSError, ValueError) as error:
            entry["reason"] = str(error)
    return plan


def rename_no_replace(source, target):
    """Windows rename 不覆盖目标；其他平台用独占硬链接实现同样的保护。"""
    if os.path.lexists(target):
        raise FileExistsError("预览后目标名称已被占用，请重新预览")
    if os.name == "nt":
        os.rename(source, target)
    else:
        os.link(source, target)
        try:
            os.unlink(source)
        except OSError:
            os.unlink(target)
            raise


class RenamePreviewDialog:
    def __init__(self, app, plan):
        self.app, self.plan = app, plan
        self.window = tk.Toplevel(app.root)
        self.window.title("重命名预览 · 发票与文档助手")
        self.window.geometry("1100x720")
        self.window.minsize(920, 640)
        self.window.transient(app.root)
        self.window.grab_set()
        body = ttk.Frame(self.window, padding=24)
        body.pack(fill=tk.BOTH, expand=True)
        heading(body, "重命名预览", "核对新旧文件名后执行；格式异常或未识别的文件会跳过。")
        self.ready = sum(entry["action"] == "rename" for entry in plan)
        conflicts = sum(entry["conflict"] for entry in plan)
        ttk.Label(body, text=f"共 {len(plan)} 项    ·    将修改 {self.ready} 项    ·    自动加序号 {conflicts} 项    ·    跳过 {len(plan) - self.ready} 项",
                  style="Badge.TLabel").pack(fill=tk.X, pady=(0, 14))
        footer = ttk.Frame(body)
        footer.pack(side=tk.BOTTOM, fill=tk.X, pady=(14, 0))
        ttk.Button(footer, text="返回修改", command=self.window.destroy).pack(side=tk.LEFT)
        self.confirm_button = ttk.Button(footer, text=f"确认执行 {self.ready} 项", style="Primary.TButton", command=self.confirm)
        self.confirm_button.pack(side=tk.RIGHT)
        if not self.ready:
            self.confirm_button.config(state=tk.DISABLED)
        self.detail = ttk.Label(body, text="选中一项可查看完整路径与校验说明。", wraplength=840,
                                style="Muted.TLabel", justify=tk.LEFT)
        self.detail.pack(side=tk.BOTTOM, fill=tk.X, pady=(12, 0))
        ttk.Label(body, text="日期、号码留空时省略；已填写但格式错误时须先修改。这里只校验格式，不查验发票真伪。",
                  style="Muted.TLabel", wraplength=840).pack(anchor=tk.W, pady=(0, 10))
        frame = ttk.Frame(body)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(frame, columns=("old", "new", "action", "reason"), show="headings", selectmode="browse")
        for name, title, width in (("old", "原文件名", 215), ("new", "计划新文件名", 350),
                                   ("action", "处理方式", 110), ("reason", "校验 / 跳过原因", 260)):
            self.tree.heading(name, text=title)
            self.tree.column(name, width=width, minwidth=90)
        vertical = ttk.Scrollbar(frame, command=self.tree.yview)
        horizontal = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.config(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        for index, entry in enumerate(plan):
            self.tree.insert("", tk.END, iid=str(index), values=(Path(entry["source"]).name,
                Path(entry["target"]).name if entry["target"] else "—",
                "执行 · 加序号" if entry["conflict"] else ("执行" if entry["action"] == "rename" else "跳过"),
                entry["reason"]), tags=("ready" if entry["action"] == "rename" else "skipped",))
        self.tree.tag_configure("ready", foreground="#147D59")
        self.tree.tag_configure("skipped", foreground="#B35313")
        self.tree.bind("<<TreeviewSelect>>", self.show_detail)
        body.bind("<Configure>", lambda event: self.detail.config(wraplength=max(600, event.width - 20)))

    def show_detail(self, _event=None):
        selected = self.tree.selection()
        if selected:
            entry = self.plan[int(selected[0])]
            self.detail.config(text=f"原路径：{entry['source']}\n目标路径：{entry['target'] or '不修改'}\n说明：{entry['reason']}")

    def confirm(self):
        if not self.ready or self.app.processing:
            return
        self.confirm_button.config(state=tk.DISABLED)
        self.window.destroy()
        self.app._start_worker(lambda: self.app._run_rename(self.plan))
