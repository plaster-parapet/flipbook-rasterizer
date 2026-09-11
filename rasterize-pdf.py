#!/usr/bin/env python3
"""
Pre-rasterize a PDF into a folder of high-DPI page images.

Run this once per PDF, locally. It replaces live in-browser PDF rendering
(pdf.js) with a one-time offline render, so the flipbook viewer only ever
has to decode a plain image per page instead of interpreting PDF content
live -- see NEXT-STEPS.md for why.

Usage:
    python3 rasterize-pdf.py input.pdf [output_dir] [--dpi 400] [--format jpg] [--quality 92]

Defaults: output_dir = "<pdf-name>-pages" next to the input file, 400 DPI,
JPEG at quality 92. The viewer's max in-app zoom is 4x (see MAX_ZOOM in
index-pen-static.html); 300 DPI looks fine at the normal flipbook view but
visibly softens once zoomed in near that ceiling. 400 DPI was confirmed
(side-by-side, same page, same 4x zoom) to fix that softness, at roughly
2x the file size of 300 DPI. 600 DPI was also tried and didn't look
meaningfully crisper than 400 in that same comparison, while nearly
doubling file size again -- not worth it. 400 is the sweet spot.
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


# The viewer shows this DPI's image for ordinary flipping (all pages, all
# the time) and only swaps in the full `--dpi` image for the 1-2 pages
# actually on screen once the user zooms in past 1x. 300 DPI is the value
# already confirmed smooth for normal flip-through (the "300 DPI is the
# low end of the crisp linework range" reasoning from before the default
# was raised to 400 for zoom crispness -- see build-static-flipbook.py's
# manifest schema for how both tiers get embedded). Keeping the
# always-loaded tier at this size, instead of at the full zoom DPI, is
# what actually fixes flip lag -- a windowed *count* of resident images
# wasn't enough on its own when each one was still a 400+ DPI bitmap.
DISPLAY_DPI = 300


def _render_tier(page, dpi, out_path, fmt, quality):
    zoom = dpi / 72.0  # PDF user space is 72 DPI by definition
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    if fmt == "jpg":
        pix.save(out_path, jpg_quality=quality)
    else:
        pix.save(out_path)
    return pix.width, pix.height, out_path.stat().st_size


def rasterize(pdf_path: Path, out_dir: Path, dpi: int, fmt: str, quality: int, quiet: bool = False, progress_callback=None, display_dpi: int = DISPLAY_DPI):
    """Rasterizes every page of pdf_path into out_dir, at TWO resolutions
    each: a "zoom" tier (dpi -- the full quality used once someone
    actually zooms in) and a "display" tier (display_dpi -- what's shown
    the rest of the time, during ordinary flipping). Returns a list of
    dicts (in page order) -- [{"path": Path, "w": int, "h": int,
    "display_path": Path, "display_w": int, "display_h": int}, ...] -- so
    callers (e.g. build-static-flipbook.py) can embed both without
    re-deriving dimensions from the files on disk.

    progress_callback(page_num, num_pages), if given, is called after each
    page finishes -- used by rasterizer_app.py to drive a progress bar
    without needing to parse this function's print() output."""
    doc = fitz.open(pdf_path)
    num_pages = doc.page_count
    pad = len(str(num_pages))
    out_dir.mkdir(parents=True, exist_ok=True)

    ext = "jpg" if fmt == "jpg" else "png"
    total_bytes = 0
    t0 = time.time()
    pages = []

    for i in range(num_pages):
        page = doc.load_page(i)
        out_path = out_dir / f"page-{i + 1:0{pad}d}.{ext}"
        w, h, size = _render_tier(page, dpi, out_path, fmt, quality)

        display_out_path = out_dir / f"page-{i + 1:0{pad}d}-display.{ext}"
        dw, dh, dsize = _render_tier(page, display_dpi, display_out_path, fmt, quality)

        total_bytes += size + dsize
        pages.append({
            "path": out_path, "w": w, "h": h,
            "display_path": display_out_path, "display_w": dw, "display_h": dh,
        })
        if not quiet:
            print(f"  page {i + 1}/{num_pages}: {w}x{h}px zoom ({size / 1e6:.2f}MB) + {dw}x{dh}px display ({dsize / 1e6:.2f}MB)")
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
    parser.add_argument("--dpi", type=int, default=400, help="Zoom-tier render DPI (default: 400 -- stays crisp at the viewer's 4x max zoom; see module docstring)")
    parser.add_argument("--display-dpi", type=int, default=DISPLAY_DPI, help=f"Display-tier render DPI, used for ordinary flipping (default: {DISPLAY_DPI} -- keeps flips smooth; see module docstring)")
    parser.add_argument("--format", choices=["jpg", "png"], default="jpg", help="Image format (default: jpg)")
    parser.add_argument("--quality", type=int, default=92, help="JPEG quality 0-100 (default: 92; ignored for png)")
    args = parser.parse_args()

    if not args.pdf.exists():
        print(f"No such file: {args.pdf}", file=sys.stderr)
        sys.exit(1)

    out_dir = args.out_dir or args.pdf.with_name(args.pdf.stem + "-pages")
    print(f"Rasterizing {args.pdf.name} -> {out_dir} at {args.dpi} DPI zoom / {args.display_dpi} DPI display ({args.format}, q={args.quality})")
    rasterize(args.pdf, out_dir, args.dpi, args.format, args.quality, display_dpi=args.display_dpi)


if __name__ == "__main__":
    main()
