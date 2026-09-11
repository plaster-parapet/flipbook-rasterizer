#!/usr/bin/env python3
"""
Minimal desktop GUI wrapper around rasterize-pdf.py + build-static-flipbook.py.

Lets someone pick a PDF and produces a ready-to-deploy, self-contained
flipbook HTML file -- the same output as running build-static-flipbook.py
by hand, just without needing a terminal or Python installed (once this is
packaged into a standalone app via PyInstaller -- see
NEXT-STEPS-DESKTOP-APP.md).

This file does NOT reimplement rasterization or packaging -- it only calls
into rasterize-pdf.py and build-static-flipbook.py, per that plan's
constraint to keep this a thin GUI/packaging layer over already-verified
logic, not a second copy of it.
"""

import importlib.util
import os
import sys
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# rasterize-pdf.py and build-static-flipbook.py have hyphens in their
# filenames (can't `import` them directly) and, once this app is bundled
# by PyInstaller, aren't real sibling files on disk anymore -- they're
# extracted to sys._MEIPASS as data files at runtime (see the PyInstaller
# --add-data flags in the build instructions). HERE resolves to wherever
# they actually are in both the "running as a plain script" and "running
# as a bundled app" cases.
if getattr(sys, "frozen", False):
    HERE = Path(sys._MEIPASS)
else:
    HERE = Path(__file__).resolve().parent


def _load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rasterize_pdf = _load_module("rasterize_pdf", "rasterize-pdf.py")
build_static_flipbook = _load_module("build_static_flipbook", "build-static-flipbook.py")


APP_TITLE = "Flipbook Rasterizer"
DEFAULT_DPI = 400  # matches rasterize-pdf.py's own default -- see that file for why


BG = "#f4f4f2"  # explicit light background -- tkinter on macOS otherwise
# inherits the system dark-mode window chrome while leaving widget text at
# its default black, which renders invisible on a dark background. Fixing
# every widget's colors explicitly (rather than toggling appearance modes)
# keeps this legible regardless of the friend's system theme.
FG = "#1a1a1a"
FG_MUTED = "#555"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("480x280")
        self.resizable(False, False)
        self.configure(bg=BG)

        tk.Label(
            self, text="Turn a PDF into a fast, lag-free flipbook.",
            font=("Helvetica", 13, "bold"), bg=BG, fg=FG,
        ).pack(pady=(24, 4))
        tk.Label(
            self, text="Choose a PDF, then choose where to save the finished flipbook.",
            bg=BG, fg=FG_MUTED,
        ).pack(pady=(0, 18))

        self.choose_btn = tk.Button(
            self, text="Choose PDF...", command=self.choose_pdf, width=24, height=2,
            bg="#ffffff", fg=FG, highlightbackground=BG,
        )
        self.choose_btn.pack(pady=4)

        self.status_label = tk.Label(self, text="", bg=BG, fg=FG_MUTED)
        self.status_label.pack(pady=(18, 4))

        # PyMuPDF registers a C++-level global context that, on process
        # exit, tries to flush pending warnings by calling back into
        # Python. Tk's own shutdown path (destroying the last window ->
        # Tcl_Exit -> the C library's exit()) runs that global-destructor
        # chain *after* Python's interpreter is already torn down, which
        # segfaults (confirmed via a real crash report: EXC_BAD_ACCESS in
        # PyUnicode_DecodeUTF8, called from mupdf's DiagnosticCallback,
        # called from fz_drop_context, called from exit()'s C++ static
        # destructors). There's nothing left to flush or save at this
        # point -- the flipbook file is already written to disk before the
        # window can be closed -- so os._exit() skips that broken shutdown
        # path entirely instead of trying to fix mupdf's global state.
        self.protocol("WM_DELETE_WINDOW", lambda: os._exit(0))

        self.progress = ttk.Progressbar(self, orient="horizontal", length=380, mode="determinate")
        # Packed/unpacked around a job rather than left empty-and-visible,
        # so the window doesn't show a stalled-looking empty bar at rest.
        self.progress.pack(pady=4)
        self.progress.pack_forget()

    def choose_pdf(self):
        path = filedialog.askopenfilename(title="Choose a PDF", filetypes=[("PDF files", "*.pdf")])
        if not path:
            return
        pdf_path = Path(path)
        default_name = pdf_path.stem + "-flipbook.html"
        out_path = filedialog.asksaveasfilename(
            title="Save flipbook as...",
            initialfile=default_name,
            defaultextension=".html",
            filetypes=[("HTML file", "*.html")],
        )
        if not out_path:
            return
        self.start_job(pdf_path, Path(out_path))

    def start_job(self, pdf_path: Path, out_path: Path):
        self.choose_btn.config(state="disabled")
        self.progress.pack(pady=4)
        self.progress["value"] = 0
        self.status_label.config(text="Starting...")
        # Rasterization runs for real seconds on a heavy PDF -- off the
        # main thread so the window stays responsive (macOS/Windows both
        # mark an unresponsive-for-a-few-seconds window as "Not
        # Responding", which reads as broken even though it would finish
        # fine on its own).
        threading.Thread(target=self.run_job, args=(pdf_path, out_path), daemon=True).start()

    def run_job(self, pdf_path: Path, out_path: Path):
        try:
            images_dir = pdf_path.with_name(pdf_path.stem + "-pages")

            def on_progress(n, total):
                self.after(0, self.update_progress, n, total)

            pages = rasterize_pdf.rasterize(
                pdf_path, images_dir, DEFAULT_DPI, "jpg", 92,
                quiet=True, progress_callback=on_progress,
            )
            self.after(0, lambda: self.status_label.config(text="Packaging flipbook..."))
            manifest, _ = build_static_flipbook.build_manifest(pages)
            build_static_flipbook.package(manifest, out_path)
            self.after(0, self.job_done, out_path, None)
        except Exception as err:
            traceback.print_exc()
            self.after(0, self.job_done, out_path, err)

    def update_progress(self, n, total):
        self.progress["maximum"] = total
        self.progress["value"] = n
        self.status_label.config(text=f"Rendering page {n} of {total}...")

    def job_done(self, out_path: Path, error):
        self.choose_btn.config(state="normal")
        self.progress.pack_forget()
        if error:
            self.status_label.config(text="Something went wrong.")
            messagebox.showerror(APP_TITLE, f"Could not build the flipbook:\n\n{error}")
        else:
            self.status_label.config(text="Done!")
            messagebox.showinfo(
                APP_TITLE,
                f"Your flipbook is ready:\n\n{out_path}\n\n"
                "Drag this file onto your Netlify deploy area (or send it to "
                "whoever manages your site) to publish it.",
            )


if __name__ == "__main__":
    App().mainloop()
