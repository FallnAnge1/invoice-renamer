"""格式转换窗口，复用主界面的工作线程与消息队列。"""
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from format_converter import IMAGE_SUFFIXES, MODES, convert_files


class ConverterDialog:
    def __init__(self, app):
        self.app = app
        self.paths = []
        self.busy = False
        self.window = tk.Toplevel(app.root)
        self.window.title("格式转换")
        self.window.geometry("780x650")
        self.window.minsize(650, 550)
        self.window.transient(app.root)
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        body = ttk.Frame(self.window, padding=16)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text="转换方式").pack(anchor=tk.W)
        self.mode = tk.StringVar(value=next(iter(MODES)))
        self.mode_box = ttk.Combobox(body, textvariable=self.mode,
                                    values=list(MODES), state="readonly")
        self.mode_box.pack(fill=tk.X, pady=(4, 8))
        self.mode_box.bind("<<ComboboxSelected>>", self.change_mode)
        ttk.Label(body, text="合并按下方列表顺序；可上移、下移调整。输出另存，同名自动加序号。",
                  wraplength=600).pack(anchor=tk.W)
        row = ttk.Frame(body)
        row.pack(fill=tk.X, pady=8)
        self.controls = []
        for label, command in [("添加文件", self.add_files), ("移除", self.remove),
                               ("上移", lambda: self.move(-1)), ("下移", lambda: self.move(1))]:
            button = ttk.Button(row, text=label, command=command)
            button.pack(side=tk.LEFT, padx=(0, 6))
            self.controls.append(button)
        list_frame = ttk.Frame(body)
        list_frame.pack(fill=tk.BOTH, expand=True)
        self.files = tk.Listbox(list_frame, selectmode=tk.BROWSE, height=8, exportselection=False)
        scroll = ttk.Scrollbar(list_frame, command=self.files.yview)
        self.files.config(yscrollcommand=scroll.set)
        self.files.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        output = ttk.Frame(body)
        output.pack(fill=tk.X, pady=10)
        ttk.Label(output, text="输出文件夹：").pack(side=tk.LEFT)
        self.output = tk.StringVar()
        self.output_entry = ttk.Entry(output, textvariable=self.output)
        self.output_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        choose = ttk.Button(output, text="选择…", command=self.choose_output)
        choose.pack(side=tk.LEFT, padx=(6, 0))
        self.controls.extend([self.output_entry, choose])
        self.import_pdf = tk.BooleanVar(value=True)
        check = ttk.Checkbutton(body, text="完成后将生成的 PDF 加入发票列表", variable=self.import_pdf)
        check.pack(anchor=tk.W)
        self.controls.append(check)
        ttk.Label(body, text="图片支持 JPG、PNG、WebP、BMP、单帧 TIFF；PDF 转图为 150 DPI。\n"
                  "格式转换不会自动识别文字；图片生成的 PDF 仍需 OCR。", wraplength=650).pack(anchor=tk.W, pady=6)
        self.start = ttk.Button(body, text="开始转换", command=self.run)
        self.start.pack(anchor=tk.E)
        self.controls.append(self.start)
        self.progress = ttk.Progressbar(body)
        self.progress.pack(fill=tk.X, pady=8)
        self.result = tk.Text(body, height=6, wrap=tk.WORD, state=tk.DISABLED)
        self.result.pack(fill=tk.BOTH)

    def close(self):
        if self.busy:
            messagebox.showinfo("正在转换", "请等待本次转换完成后关闭。", parent=self.window)
            return
        self.window.destroy()

    def change_mode(self, _event=None):
        self.paths.clear()
        self.refresh()

    def refresh(self):
        self.files.delete(0, tk.END)
        for index, path in enumerate(self.paths, 1):
            self.files.insert(tk.END, f"{index}. {path}")

    def add_files(self):
        images = MODES[self.mode.get()].startswith("image")
        pattern = " ".join("*" + suffix for suffix in sorted(IMAGE_SUFFIXES)) if images else "*.pdf"
        paths = filedialog.askopenfilenames(parent=self.window, title="选择要转换的文件",
                    filetypes=[("图片文件" if images else "PDF 文件", pattern)])
        for path in paths:
            if path not in self.paths:
                self.paths.append(path)
        self.refresh()

    def remove(self):
        selected = self.files.curselection()
        if selected:
            del self.paths[selected[0]]
            self.refresh()

    def move(self, offset):
        selected = self.files.curselection()
        if not selected:
            return
        old = selected[0]
        new = old + offset
        if 0 <= new < len(self.paths):
            self.paths[old], self.paths[new] = self.paths[new], self.paths[old]
            self.refresh()
            self.files.selection_set(new)
            self.files.see(new)

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
        self.show_result("正在转换，请稍候…")

        def update(value, total):
            self.app._post_ui(self.progress.config, value=value, maximum=total)

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
        self.app._set_status(f"格式转换完成：生成 {len(outputs)} 个文件，失败 {len(failures)} 项")
