#!/usr/bin/env python3
"""
Package a PDF (or an already-rasterized folder of page images) into a
single self-contained flipbook HTML file, based on the index-pen-static.html
template -- see NEXT-STEPS.md for why this exists (replaces live pdf.js
rendering with pre-rasterized images, eliminating the render-lag problem
class entirely).

This is the local-script equivalent of dragging a PDF into
flipbook-builder-pen.html, except the PDF's content is rasterized once,
offline, with PyMuPDF (see rasterize-pdf.py) instead of embedded raw and
rendered live in the visitor's browser.

Usage:
    # From a PDF directly (rasterizes it first):
    python3 build-static-flipbook.py input.pdf [output.html] [--dpi 400] [--format jpg] [--quality 92]

    # From an already-rasterized folder (e.g. one you inspected/reused from
    # a prior rasterize-pdf.py run):
    python3 build-static-flipbook.py --images-dir some-pages/ output.html

Defaults: output.html = "<pdf-name>-flipbook.html" next to the input file.
When rasterizing from a PDF, the images are kept in "<pdf-name>-pages"
next to it afterward (same default rasterize-pdf.py itself uses) unless
--no-keep-images is passed.
"""

import argparse
import base64
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE_PATH = HERE / "index-pen-static.html"
MANIFEST_ANCHOR = "/*__PAGE_MANIFEST__*/ null"

# rasterize-pdf.py has a hyphen in its filename, so it can't be imported
# with a plain `import` statement -- load it by file path instead. This
# keeps one implementation of the actual rendering shared between the
# standalone script and this packager (see NEXT-STEPS-SERVERLESS.md's
# "share the rasterization logic, don't fork it" principle -- applies here
# too, not just to a future serverless function).
def _load_rasterize_module():
    spec = importlib.util.spec_from_file_location("rasterize_pdf", HERE / "rasterize-pdf.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MIME_BY_EXT = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def _image_size(p: Path):
    try:
        from PIL import Image
        with Image.open(p) as im:
            return im.size
    except ImportError:
        # Fall back to PyMuPDF (already a dependency of rasterize-pdf.py)
        # to read dimensions if Pillow isn't installed.
        import fitz
        with fitz.open(p) as im:
            pix = im[0].get_pixmap()
            return pix.width, pix.height


def images_dir_to_pages(images_dir: Path):
    """Reads an existing folder of rasterize-pdf.py output (or anything
    with the same page-NN[-display].ext naming) and returns [{"path": Path,
    "w": int, "h": int, "display_path": Path, "display_w": int,
    "display_h": int}, ...] in page order, deriving dimensions from each
    file's own JPEG/PNG header instead of assuming rasterize-pdf.py's
    return value is available (it isn't, when starting from a folder that
    was produced in a separate run). Every zoom-tier file (page-NN.ext)
    must have a matching display-tier sibling (page-NN-display.ext) --
    rasterize-pdf.py always writes both, so a missing one means a folder
    from before the two-tier change, or a manually-edited folder."""
    files = sorted(
        p for p in images_dir.iterdir()
        if p.suffix.lower() in MIME_BY_EXT and not p.stem.endswith("-display")
    )
    if not files:
        print(f"No page images found in {images_dir}", file=sys.stderr)
        sys.exit(1)

    pages = []
    for p in files:
        display_p = p.with_name(f"{p.stem}-display{p.suffix}")
        if not display_p.exists():
            print(
                f"Missing display-tier image: {display_p} (expected next to {p}) -- "
                "re-run rasterize-pdf.py on this PDF to regenerate both tiers.",
                file=sys.stderr,
            )
            sys.exit(1)
        w, h = _image_size(p)
        dw, dh = _image_size(display_p)
        pages.append({"path": p, "w": w, "h": h, "display_path": display_p, "display_w": dw, "display_h": dh})
    return pages


def build_manifest(pages):
    manifest = []
    total_bytes = 0
    for page in pages:
        path = page["path"]
        display_path = page["display_path"]
        mime = MIME_BY_EXT.get(path.suffix.lower(), "image/jpeg")
        display_mime = MIME_BY_EXT.get(display_path.suffix.lower(), "image/jpeg")
        data = path.read_bytes()
        display_data = display_path.read_bytes()
        total_bytes += len(data) + len(display_data)
        b64 = base64.b64encode(data).decode("ascii")
        display_b64 = base64.b64encode(display_data).decode("ascii")
        manifest.append({
            "src": f"data:{display_mime};base64,{display_b64}",
            "zoomSrc": f"data:{mime};base64,{b64}",
            "w": page["w"], "h": page["h"],
        })
    return manifest, total_bytes


def package(manifest, output_html: Path):
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    if template.count(MANIFEST_ANCHOR) != 1:
        print(
            f"Template anchor not found (or not unique) in {TEMPLATE_PATH} -- "
            "has index-pen-static.html been edited since this script was written?",
            file=sys.stderr,
        )
        sys.exit(1)
    manifest_json = json.dumps(manifest)
    final_html = template.replace(MANIFEST_ANCHOR, f"/*__PAGE_MANIFEST__*/ {manifest_json}")
    output_html.write_text(final_html, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdf", type=Path, nargs="?", help="Path to the source PDF (omit if using --images-dir)")
    parser.add_argument("output", type=Path, nargs="?", default=None, help="Output .html path (default: <name>-flipbook.html)")
    parser.add_argument("--images-dir", type=Path, default=None, help="Use an already-rasterized folder instead of a PDF")
    parser.add_argument("--dpi", type=int, default=400, help="Zoom-tier render DPI when rasterizing a PDF (default: 400 -- see rasterize-pdf.py's docstring)")
    parser.add_argument("--display-dpi", type=int, default=None, help="Display-tier render DPI when rasterizing a PDF (default: rasterize-pdf.py's own default, 300)")
    parser.add_argument("--format", choices=["jpg", "png"], default="jpg", help="Image format when rasterizing a PDF (default: jpg)")
    parser.add_argument("--quality", type=int, default=92, help="JPEG quality when rasterizing a PDF (default: 92)")
    parser.add_argument("--no-keep-images", action="store_true", help="Delete the intermediate rasterized-images folder after packaging (default: keep it)")
    args = parser.parse_args()

    if not args.images_dir and not args.pdf:
        parser.error("Provide a PDF path, or --images-dir pointing at an already-rasterized folder.")

    if not TEMPLATE_PATH.exists():
        print(f"Template not found: {TEMPLATE_PATH}", file=sys.stderr)
        sys.exit(1)

    images_dir_to_clean = None

    if args.images_dir:
        if not args.images_dir.is_dir():
            print(f"No such directory: {args.images_dir}", file=sys.stderr)
            sys.exit(1)
        stem = args.images_dir.name
        pages = images_dir_to_pages(args.images_dir)
        source_dir = args.images_dir.parent
    else:
        if not args.pdf.exists():
            print(f"No such file: {args.pdf}", file=sys.stderr)
            sys.exit(1)
        stem = args.pdf.stem
        source_dir = args.pdf.parent
        images_dir = args.pdf.with_name(args.pdf.stem + "-pages")
        rasterize_pdf = _load_rasterize_module()
        display_dpi = args.display_dpi if args.display_dpi is not None else rasterize_pdf.DISPLAY_DPI
        print(f"Rasterizing {args.pdf.name} at {args.dpi} DPI zoom / {display_dpi} DPI display ({args.format}, q={args.quality})...")
        pages = rasterize_pdf.rasterize(args.pdf, images_dir, args.dpi, args.format, args.quality, display_dpi=display_dpi)
        print(f"Rasterized {len(pages)} pages -> {images_dir}")
        if args.no_keep_images:
            images_dir_to_clean = images_dir

    output_html = args.output or (source_dir / f"{stem}-flipbook.html")

    print(f"Embedding {len(pages)} pages into {TEMPLATE_PATH.name}...")
    manifest, total_image_bytes = build_manifest(pages)
    package(manifest, output_html)

    final_size = output_html.stat().st_size
    print(
        f"\nDone: {output_html} ({final_size / 1e6:.1f}MB, "
        f"{total_image_bytes / 1e6:.1f}MB of page images embedded)"
    )
    print("Drag this file onto your Netlify project's deploy area to publish it.")

    if images_dir_to_clean:
        import shutil
        shutil.rmtree(images_dir_to_clean)
        print(f"Removed intermediate folder: {images_dir_to_clean}")


if __name__ == "__main__":
    main()
