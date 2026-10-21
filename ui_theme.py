"""全应用共享的桌面主题与布局组件。"""
import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk
from pathlib import Path

BG = "#F2F5FA"
WHITE = "#FFFFFF"
INK = "#18263D"
MUTED = "#62738B"
BLUE = "#245BE8"
LINE = "#DDE5F0"
FONT = "Microsoft YaHei UI"


def apply_theme(root):
    root.configure(background=BG)
    root.option_add("*Menu.font", (FONT, 10))
    root.option_add("*TCombobox*Listbox.font", (FONT, 10))
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=(FONT, 10), background=BG, foreground=INK)
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=WHITE)
    style.configure("Panel.TFrame", background=WHITE, borderwidth=1, relief="solid", bordercolor=LINE)
    style.configure("Stage.TFrame", background="#F5F7FB")
    style.configure("Stage.TLabel", background="#F5F7FB", foreground=MUTED, font=(FONT, 10))
    style.configure("TLabel", background=BG, foreground=INK)
    style.configure("Card.TLabel", background=WHITE)
    style.configure("Title.TLabel", font=(FONT, 22, "bold"), foreground=INK)
    style.configure("PageTitle.TLabel", font=(FONT, 18, "bold"), foreground=INK)
    style.configure("TPanedwindow", background=BG)
    style.configure("Heading.TLabel", font=(FONT, 12, "bold"), background=WHITE)
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("CardMuted.TLabel", foreground=MUTED, background=WHITE)
    style.configure("Small.TLabel", font=(FONT, 9), foreground=MUTED)
    style.configure("CardSmall.TLabel", font=(FONT, 9), foreground=MUTED, background=WHITE)
    style.configure("GreenBadge.TLabel", font=(FONT, 9), foreground="#13765B", background="#E6F5ED", padding=(8, 4))
    style.configure("OrangeBadge.TLabel", font=(FONT, 9), foreground="#A65016", background="#FFF0DF", padding=(8, 4))
    style.configure("NeutralBadge.TLabel", font=(FONT, 9), foreground=MUTED, background="#EEF2F7", padding=(8, 4))
    style.configure("Stat.TLabel", font=(FONT, 23, "bold"), background=WHITE, foreground=BLUE)
    style.configure("Badge.TLabel", foreground=BLUE, background="#E7EEFF", padding=(12, 7))
    style.configure("TButton", background=WHITE, foreground=INK, padding=(13, 9),
                    borderwidth=1, bordercolor=LINE, focusthickness=2, focuscolor="#B4C7FC")
    style.map("TButton", background=[("disabled", "#F1F4F8"), ("active", "#EAF0FF")],
              foreground=[("disabled", "#98A5B7")])
    style.configure("TMenubutton", background=WHITE, foreground=INK, padding=(10, 8),
                    borderwidth=1, bordercolor=LINE, relief="flat")
    style.map("TMenubutton", background=[("disabled", "#F1F4F8"), ("active", "#EAF0FF")],
              foreground=[("disabled", "#98A5B7")])
    style.configure("Primary.TButton", background=BLUE, foreground=WHITE, bordercolor=BLUE)
    style.configure("Compact.TButton", padding=(8, 8), width=0)
    style.configure("Compact.Primary.TButton", padding=(8, 8), width=0)
    style.map("Primary.TButton", background=[("disabled", "#C8D4ED"), ("active", "#194BCC")],
              foreground=[("disabled", "#FFFFFF"), ("!disabled", WHITE)])
    style.configure("TEntry", fieldbackground=WHITE, bordercolor=LINE, padding=7)
    style.configure("TCombobox", fieldbackground=WHITE, background=WHITE, padding=7, bordercolor=LINE)
    style.map("TCombobox", fieldbackground=[("readonly", WHITE)])
    style.configure("TCheckbutton", padding=(0, 5))
    style.configure("Treeview", background=WHITE, fieldbackground=WHITE, foreground=INK,
                    rowheight=40, borderwidth=0, font=(FONT, 10))
    style.configure("Treeview.Heading", background="#EAF0F8", foreground=MUTED,
                    font=(FONT, 10, "bold"), padding=(10, 12), relief="flat")
    style.map("Treeview", background=[("selected", "#DCE7FF")], foreground=[("selected", "#153FAD")])
    style.configure("Queue.Treeview", rowheight=38, borderwidth=0, relief="flat", bordercolor=WHITE,
                    lightcolor=WHITE, darkcolor=WHITE)
    style.configure("Link.TButton", padding=(2, 1), width=0, background=WHITE, foreground=BLUE, borderwidth=0)
    style.map("Link.TButton", background=[("active", "#EAF0FF"), ("!active", WHITE)],
              foreground=[("disabled", "#98A5B7"), ("!disabled", BLUE)])
    style.configure("Queue.Treeview.Heading", background=WHITE, padding=(8, 9), font=(FONT, 9), foreground=MUTED)
    style.configure("TProgressbar", background=BLUE, troughcolor="#E4EBF5", borderwidth=0, thickness=6)
    style.configure("Horizontal.TProgressbar", background=BLUE, troughcolor="#E4EBF5",
                    bordercolor="#E4EBF5", lightcolor=BLUE, darkcolor=BLUE, borderwidth=0, thickness=6)
    style.configure("TSeparator", background=LINE)
    style.configure("TScrollbar", background="#D2DCEB", troughcolor=BG, borderwidth=0,
                    arrowcolor=MUTED)
    for orient, sticky in (("Vertical", "ns"), ("Horizontal", "ew")):
        name = f"Slim.{orient}.TScrollbar"
        style.layout(name, [(f"{orient}.Scrollbar.trough", {"sticky": sticky, "children": [
            (f"{orient}.Scrollbar.thumb", {"expand": "1", "sticky": "nsew"})]})])
        style.configure(name, background="#CCD6E5", troughcolor="#F5F7FB", borderwidth=0,
                        bordercolor="#F5F7FB", lightcolor="#CCD6E5", darkcolor="#CCD6E5", width=8)


def heading(parent, title, subtitle):
    frame = ttk.Frame(parent)
    frame.pack(fill=tk.X, pady=(0, 18))
    ttk.Label(frame, text=title, style="Title.TLabel").pack(anchor=tk.W)
    ttk.Label(frame, text=subtitle, style="Muted.TLabel").pack(anchor=tk.W, pady=(5, 0))
    return frame


def style_text(widget):
    widget.configure(font=(FONT, 11), background=WHITE, foreground=INK, relief="flat",
                     borderwidth=0, highlightthickness=1, highlightbackground=LINE,
                     highlightcolor=BLUE, padx=14, pady=12, insertbackground=BLUE,
                     selectbackground="#DCE7FF", selectforeground=INK, spacing1=3, spacing3=6)


def open_folder(path):
    path = str(Path(path).resolve())
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
