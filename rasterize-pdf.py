#!/usr/bin/env python3
"""
Pre-rasterize a PDF into a folder of high-DPI page images.

Run this once per PDF, locally. It replaces live in-browser PDF rendering
(pdf.js) with a one-time offline render, so the flipbook viewer only ever
has to decode a plain image per page instead of interpreting PDF content
live -- see NEXT-STEPS.md for why.

Usage:
    python3 rasterize-pdf.py input.pdf [output_dir] [--dpi 300] [--format jpg] [--quality 92]

Defaults: output_dir = "<pdf-name>-pages" next to the input file, 300 DPI,
JPEG at quality 92. 300 DPI is the low end of the "crisp linework" target
range (300-400) -- it's the standard "print quality" threshold and produces
noticeably smaller files than 400 DPI with no visible softness on typical
portfolio-page line weights viewed at normal flipbook zoom. Bump to 400 DPI
for a page you plan to zoom into heavily.
"""

import argparse
import sys
import time
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    print("PyMuPDF is required: python3 -m pip install --user pymupdf", file=sys.stderr)
    sys.exit(1)


def rasterize(pdf_path: Path, out_dir: Path, dpi: int, fmt: str, quality: int, quiet: bool = False, progress_callback=None):
    """Rasterizes every page of pdf_path into out_dir. Returns a list of
    dicts (in page order) -- [{"path": Path, "w": int, "h": int}, ...] --
    so callers (e.g. build-static-flipbook.py) can embed the results
    without re-deriving dimensions from the files on disk.

    progress_callback(page_num, num_pages), if given, is called after each
    page finishes -- used by rasterizer_app.py to drive a progress bar
    without needing to parse this function's print() output."""
    doc = fitz.open(pdf_path)
    num_pages = doc.page_count
    pad = len(str(num_pages))
    out_dir.mkdir(parents=True, exist_ok=True)

    zoom = dpi / 72.0  # PDF user space is 72 DPI by definition
    matrix = fitz.Matrix(zoom, zoom)

    ext = "jpg" if fmt == "jpg" else "png"
    total_bytes = 0
    t0 = time.time()
    pages = []

    for i in range(num_pages):
        page = doc.load_page(i)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        out_path = out_dir / f"page-{i + 1:0{pad}d}.{ext}"
        if fmt == "jpg":
            pix.save(out_path, jpg_quality=quality)
        else:
            pix.save(out_path)
        size = out_path.stat().st_size
        total_bytes += size
        pages.append({"path": out_path, "w": pix.width, "h": pix.height})
        if not quiet:
            print(f"  page {i + 1}/{num_pages}: {pix.width}x{pix.height}px, {size / 1e6:.2f}MB")
        if progress_callback:
            progress_callback(i + 1, num_pages)

    elapsed = time.time() - t0
    if not quiet:
        print(f"\nDone: {num_pages} pages, {total_bytes / 1e6:.1f}MB total, {elapsed:.1f}s")
        print(f"Output: {out_dir}")
    return pages


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdf", type=Path, help="Path to the source PDF")
    parser.add_argument("out_dir", type=Path, nargs="?", default=None, help="Output folder (default: <pdf-name>-pages)")
    parser.add_argument("--dpi", type=int, default=300, help="Render DPI (default: 300; try 400 for max crispness)")
    parser.add_argument("--format", choices=["jpg", "png"], default="jpg", help="Image format (default: jpg)")
    parser.add_argument("--quality", type=int, default=92, help="JPEG quality 0-100 (default: 92; ignored for png)")
    args = parser.parse_args()

    if not args.pdf.exists():
        print(f"No such file: {args.pdf}", file=sys.stderr)
        sys.exit(1)

    out_dir = args.out_dir or args.pdf.with_name(args.pdf.stem + "-pages")
    print(f"Rasterizing {args.pdf.name} -> {out_dir} at {args.dpi} DPI ({args.format}, q={args.quality})")
    rasterize(args.pdf, out_dir, args.dpi, args.format, args.quality)


if __name__ == "__main__":
    main()
