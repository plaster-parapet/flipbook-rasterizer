# Flipbook Rasterizer

A small desktop app that turns a PDF into a fast, lag-free flipbook: pick a
PDF, get back a self-contained `.html` file ready to drag onto Netlify (or
send to whoever manages the site).

It's a thin `tkinter` GUI wrapper around `rasterize-pdf.py` (renders each
PDF page to a high-DPI image via PyMuPDF) and `build-static-flipbook.py`
(embeds those images into a flipbook viewer template,
`index-pen-static.html`) — see `rasterizer_app.py` for how they're loaded.
This pre-rasterization approach replaces live in-browser PDF rendering,
which used to lag badly on large/image-heavy PDFs.

## Building

**macOS**, locally:

```
pip install pymupdf pyinstaller
pyinstaller --name "Flipbook Rasterizer" --windowed \
  --add-data "rasterize-pdf.py:." \
  --add-data "build-static-flipbook.py:." \
  --add-data "index-pen-static.html:." \
  --hidden-import fitz --collect-all fitz \
  rasterizer_app.py
```

Requires a Python built against a modern Tcl/Tk (8.6+) — Apple's system
Python (`/usr/bin/python3`) links an old, broken Tk 8.5 that silently fails
to render label text. Use a python.org or Homebrew Python instead.

**Windows**: built automatically by `.github/workflows/build-windows.yml`
on every push to `main` (and on-demand via the Actions tab's "Run
workflow" button) — this repo has no Windows machine to build on locally,
so GitHub's free Windows runners do it. The build produces a single
portable `Flipbook Rasterizer.exe`, uploaded as a workflow artifact.
