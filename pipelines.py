"""
Adapter layer for Enhance Studio.

Exposes ONE uniform call over the four bundled enhancement engines:

    enhance(pipeline, in_path, options) -> (PIL.Image RGB, info_dict)

The engines live in the in-repo ``pipeline_src`` package; each keeps its exact
per-image image-processing logic (including the "never cut the subject" and
natural-look safety gates). No pixel math is re-implemented here, and nothing in
this module reads or writes anything but the uploaded copy it is given.
"""
import os

import cv2
from PIL import Image

from pipeline_src import quality, website, news, book

# Human-facing metadata for the UI (kept here so the frontend and backend agree).
PIPELINES = [
    {
        "id": "quality",
        "icon": "🪄",
        "name": "Photo Quality",
        "tagline": "Upscale + denoise + sharpen. Nothing else changes.",
        "desc": "Makes the same photo higher-resolution and cleaner while preserving "
                "composition, colors, faces and B&W exactly. No crop, no AI invention.",
        "options": [],
    },
    {
        "id": "website",
        "icon": "🖼️",
        "name": "Photo Extract",
        "tagline": "Scanner-style crop + deskew + natural enhance.",
        "desc": "For phone photos of printed photos/clippings on a table. Detects the "
                "print, straightens and crops it (never cuts the subject), then enhances "
                "naturally.",
        "options": [
            {
                "key": "orient", "type": "checkbox", "default": False,
                "label": "Attempt 90 degree auto-rotate",
                "hint": "Off by default - face-based rotation is unreliable; "
                        "enable to try it per image.",
            },
        ],
    },
    {
        "id": "news",
        "icon": "📰",
        "name": "Newspaper",
        "tagline": "Natural archival restoration.",
        "desc": "For newspaper-clipping scans. Auto-crop, deskew, gentle denoise and "
                "edge-only sharpening so it reads like a clean flatbed scan, not an AI "
                "image. Colors and paper texture preserved.",
        "options": [],
    },
    {
        "id": "book",
        "icon": "📖",
        "name": "Book Cover / Page",
        "tagline": "Segment cover onto white, or whiten a text page.",
        "desc": "Document / book pipeline. Covers and photos are segmented onto a clean "
                "white 3:4 canvas; text pages are paper-whitened and text-sharpened. "
                "Auto picks the mode from the filename.",
        "options": [
            {
                "key": "mode", "type": "radio", "default": "auto",
                "label": "Mode",
                "choices": [
                    {"value": "auto", "label": "Auto (by filename)"},
                    {"value": "cover", "label": "Cover"},
                    {"value": "page", "label": "Text page"},
                ],
            },
        ],
    },
]


def _bgr_to_pil(bgr):
    return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))


# --------------------------------------------------------------------------- runners
def _run_quality(in_path, options):
    _orig, enh, oshape, eshape = quality.process_image(in_path)
    info = {
        "method": "denoise + Lanczos upscale + sharpen",
        "orig_size": [oshape[1], oshape[0]],
        "out_size": [eshape[1], eshape[0]],
    }
    return _bgr_to_pil(enh), info


def _run_website(in_path, options):
    do_orient = bool(options.get("orient", False))
    _orig, enh, method, rot, oshape, _fmt = website.process_image(in_path, do_orient)
    info = {
        "method": method + (f" + rot{rot}" if rot else ""),
        "orig_size": [oshape[1], oshape[0]],
        "out_size": [enh.shape[1], enh.shape[0]],
    }
    return _bgr_to_pil(enh), info


def _run_news(in_path, options):
    bgr, meta = news.enhance(in_path)
    bits = ["natural archival"]
    if meta.get("cropped"):
        bits.append("crop")
    if meta.get("skew"):
        bits.append(f"deskew {meta['skew']:+.1f}")
    info = {
        "method": " + ".join(bits),
        "orig_size": list(meta["in_dim"]),
        "out_size": list(meta["out_dim"]),
    }
    return _bgr_to_pil(bgr), info


def _run_book(in_path, options):
    mode = options.get("mode", "auto")
    if mode not in ("cover", "page"):
        mode = book.classify(os.path.basename(in_path))
    pil = book.process(in_path, mode)        # already a PIL RGB image on a white canvas
    info = {"method": f"{mode} onto white canvas", "out_size": list(pil.size)}
    return pil, info


_RUNNERS = {
    "quality": _run_quality,
    "website": _run_website,
    "news": _run_news,
    "book": _run_book,
}


def enhance(pipeline, in_path, options=None):
    """Run one uploaded image through the chosen pipeline.

    Returns (PIL.Image in RGB, info_dict). Raises ValueError for an unknown
    pipeline id; other exceptions propagate to the caller to report per-file.
    """
    if pipeline not in _RUNNERS:
        raise ValueError(f"unknown pipeline: {pipeline!r}")
    options = options or {}
    return _RUNNERS[pipeline](in_path, options)
