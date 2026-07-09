"""
Book / Document engine — two content-aware modes.

COVER: segment the book/photo from a plain surface, deskew, and composite it
centred on a clean white 3:4 canvas (book-preserving flood/mask gates so the
subject is never cut). PAGE: flat-field whiten the paper, suppress
show-through, boost and sharpen text, deskew, and centre on white. classify()
picks the mode from the filename; callers may override it.

Bundled with Enhance Studio. Engine-only: the
batch/CLI wrapper and all personal paths have been removed; the per-image
image-processing logic is unchanged.
"""


import cv2
import numpy as np
from PIL import Image, ImageOps, ImageEnhance, ImageFilter


CANVAS_W, CANVAS_H = 1200, 1600
CONTENT_FRAC = 0.90
MAX_UPSCALE = 1.7
JPEG_QUALITY = 90
WHITE = (255, 255, 255)
PAGE_KEYS = ("anukram", "anukrma", "anukrmaa", "anukramank", "prasthavana",
             "anuvachan", "anuwachan", "anuvach", "anukvachan", "anusar")


def classify(name):
    n = name.lower()
    if "front" in n or "back" in n:
        return "cover"
    for k in PAGE_KEYS:
        if k in n:
            return "page"
    return "cover"


def pil_to_rgb(path):
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    return np.asarray(im)


def fill_holes(mask):
    h, w = mask.shape
    ff = mask.copy()
    m2 = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(ff, m2, (0, 0), 255)
    return mask | cv2.bitwise_not(ff)


def whiten_bg_border(rgb, tol=10, max_fill=0.30):
    """For covers that don't cleanly segment (full-bleed or light covers): whiten any
    uniform neutral background that touches the image border (a grey sliver or a corner
    triangle left by a slight tilt). Tight tolerance + gates so it never eats the cover:
      - skip if the border ring is colourful (a real full-bleed cover edge)
      - skip if the flood would consume a large area (a light cover field, not a sliver)
    """
    h, w = rgb.shape[:2]
    r = max(3, int(min(h, w) * 0.03))
    ring = np.concatenate([rgb[:r, :].reshape(-1, 3), rgb[-r:, :].reshape(-1, 3),
                           rgb[:, :r].reshape(-1, 3), rgb[:, -r:].reshape(-1, 3)])
    sat = cv2.cvtColor(ring.reshape(-1, 1, 3), cv2.COLOR_RGB2HSV)[:, 0, 1].mean()
    if sat > 45:
        return rgb
    work = rgb.copy()
    fmask = np.zeros((h + 2, w + 2), np.uint8)
    flags = 4 | cv2.FLOODFILL_MASK_ONLY | (255 << 8)
    lo = (tol, tol, tol); up = (tol, tol, tol)
    sx = max(6, w // 30); sy = max(6, h // 30)
    seeds = []
    for x in range(0, w, sx):
        seeds += [(x, 0), (x, h - 1)]
    for y in range(0, h, sy):
        seeds += [(0, y), (w - 1, y)]
    for (px, py) in seeds:
        if fmask[py + 1, px + 1] == 0:
            cv2.floodFill(work, fmask, (px, py), 0, lo, up, flags)
    filled = fmask[1:-1, 1:-1] > 0
    if filled.mean() > max_fill:
        return rgb
    out = rgb.copy()
    out[filled] = 255
    return out


def _largest_fg(fg):
    n, lbl, stats, _ = cv2.connectedComponentsWithStats(fg, 8)
    if n <= 1:
        return None
    idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return (lbl == idx).astype(np.uint8) * 255


def segment_book(rgb):
    """Deskewed, centred crop of the book on white + foreground area fraction.

    Book-preserving strategy: flood-fill the BACKGROUND inward from the image borders
    with a TIGHT tolerance. The flood walks across the uniform grey surface and its soft
    shadow but stops at the book's printed edge, so it can only ever mark genuine
    border-connected background -- never interior book content. We whiten ONLY those
    flood-confirmed background pixels, so the book is never cut or erased. Hard guards:
    if the flood finds almost no background (book fills frame) or leaks into the book
    (fills too much), we bail to None and the caller keeps the full frame intact.
    """
    h, w = rgb.shape[:2]
    f = rgb.astype(np.float32)
    cs = max(6, int(min(h, w) * 0.05))
    corners = np.concatenate([
        rgb[:cs, :cs].reshape(-1, 3), rgb[:cs, -cs:].reshape(-1, 3),
        rgb[-cs:, :cs].reshape(-1, 3), rgb[-cs:, -cs:].reshape(-1, 3)]).astype(np.float32)
    bg = np.median(corners, axis=0)
    bg_std = float(corners.std(0).mean())

    # foreground = colour-distance from the background; gives a SOLID mask for a
    # clearly-coloured book on grey (unlike a flood, which under-fills textured surfaces).
    diff = np.linalg.norm(f - bg, axis=2)
    d8 = np.clip(diff, 0, 255).astype(np.uint8)
    otsu, _ = cv2.threshold(d8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    thr = max(float(otsu), 20.0, bg_std * 2.3)
    mask = (diff > thr).astype(np.uint8) * 255
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=3)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k, iterations=1)
    big = _largest_fg(mask)
    if big is None:
        return None, 0.0
    big = fill_holes(big)
    frac = big.sum() / 255.0 / (h * w)

    # SHAPE GATE: a correctly-segmented book is a solid, near-rectangular blob. When the
    # book's colour is close to the background (muted/light covers, full-bleed), the mask
    # is jagged/holey (low extent/solidity) -> reject and keep the full frame intact, so
    # the book is NEVER cut or erased. The gate is what makes the hull cut below safe.
    cnts, _ = cv2.findContours(big, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    c = max(cnts, key=cv2.contourArea)
    area = cv2.contourArea(c)
    (rw, rh) = cv2.minAreaRect(c)[1]
    extent = area / (rw * rh + 1e-6)            # rotation-invariant rectangularity
    solidity = area / (cv2.contourArea(cv2.convexHull(c)) + 1e-6)
    if not (0.20 <= frac <= 0.96 and extent >= 0.80 and solidity >= 0.92):
        return None, frac

    angle = cv2.minAreaRect(c)[2]
    if angle < -45: angle += 90
    if angle > 45:  angle -= 90
    if abs(angle) > 15:
        angle = 0.0

    # cut along the convex hull -> clean straight edges; hull contains the whole book
    # mask, so nothing inside the book is removed.
    clean = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(clean, cv2.convexHull(c), 255)

    M = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, 1.0)
    rgb_r = cv2.warpAffine(rgb, M, (w, h), flags=cv2.INTER_CUBIC,
                           borderMode=cv2.BORDER_REPLICATE)
    mask_r = cv2.warpAffine(clean, M, (w, h), flags=cv2.INTER_NEAREST)

    ys, xs = np.where(mask_r > 0)
    if len(xs) < 50:
        return None, frac
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    pad = int(0.004 * max(h, w))
    x0 = max(0, x0 - pad); y0 = max(0, y0 - pad)
    x1 = min(w - 1, x1 + pad); y1 = min(h - 1, y1 + pad)

    crop = rgb_r[y0:y1 + 1, x0:x1 + 1].copy()
    cm = mask_r[y0:y1 + 1, x0:x1 + 1]
    crop[cm == 0] = 255          # whiten only outside the book hull
    return crop, frac


def deskew_page(rgb):
    """Small-angle deskew via projection-profile variance maximization."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    small = cv2.resize(gray, (0, 0), fx=0.5, fy=0.5)
    inv = 255 - small
    inv = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    h, w = inv.shape
    best_a, best_s = 0.0, -1
    for a in np.arange(-6, 6.01, 0.5):
        M = cv2.getRotationMatrix2D((w / 2, h / 2), a, 1.0)
        r = cv2.warpAffine(inv, M, (w, h), flags=cv2.INTER_NEAREST)
        proj = r.sum(1).astype(np.float64)
        s = ((proj[1:] - proj[:-1]) ** 2).sum()
        if s > best_s:
            best_s, best_a = s, a
    if abs(best_a) < 0.25:
        return rgb
    H, W = rgb.shape[:2]
    M = cv2.getRotationMatrix2D((W / 2, H / 2), best_a, 1.0)
    return cv2.warpAffine(rgb, M, (W, H), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


def levels(rgb, bp, wp, gamma=1.0):
    """Photoshop-style input levels per pixel (applied to all channels)."""
    f = rgb.astype(np.float32)
    f = (f - bp) / float(wp - bp)
    f = np.clip(f, 0, 1) ** (1.0 / gamma)
    return (f * 255.0).astype(np.uint8)


def flatfield_whiten(rgb, strength=0.92):
    """Estimate paper illumination via morphological closing, divide to whiten paper,
    then clamp light show-through to pure white while preserving dark ink."""
    out = np.empty_like(rgb, dtype=np.float32)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31))
    for c in range(3):
        ch = rgb[:, :, c].astype(np.float32)
        bg = cv2.morphologyEx(ch, cv2.MORPH_CLOSE, k)
        bg = cv2.GaussianBlur(bg, (0, 0), 9)
        norm = ch / np.clip(bg, 1.0, None) * 255.0
        out[:, :, c] = ch * (1 - strength) + norm * strength
    out = np.clip(out, 0, 255).astype(np.uint8)
    # suppress show-through: stretch so paper+ghost text -> white, ink stays dark
    out = levels(out, bp=58, wp=200, gamma=1.05)
    # final soft clip: near-white pixels -> pure #FFFFFF (kills residual tint)
    lum = cv2.cvtColor(out, cv2.COLOR_RGB2GRAY)
    nearwhite = lum > 208
    out[nearwhite] = 255
    return out


def segment_page(rgb):
    """After whitening, isolate the bright paper rectangle and crop to it, whitening
    any dark/colored edge strips (table edge, painted page-block, binding) outside it.
    Runs on the already flat-fielded image where paper is near-white.

    These are black-ink-on-white text pages with no legitimate colored content, so any
    bright + vividly-saturated pixel (orange painted page-edge, a stray green pen, etc.)
    is bleed/clutter and is safely whitened."""
    h, w = rgb.shape[:2]
    rgb = rgb.copy()
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    colored = (hsv[:, :, 1] > 50) & (hsv[:, :, 2] > 110)
    if colored.mean() < 0.06:          # small colored clutter (orange page-edge, pen) -> white
        rgb[colored] = 255

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    dark = (gray < 135).astype(np.uint8)
    dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)))
    col = dark.sum(0); row = dark.sum(1)
    cth = max(2, 0.012 * h); rth = max(2, 0.012 * w)
    cols = np.where(col > cth)[0]; rows = np.where(row > rth)[0]
    if len(cols) < 5 or len(rows) < 5:
        return rgb                         # no reliable text block -> leave as is
    x0, x1 = int(cols[0]), int(cols[-1])
    y0, y1 = int(rows[0]), int(rows[-1])
    mx = int(0.06 * (x1 - x0)); my = int(0.05 * (y1 - y0))
    x0 = max(0, x0 - mx); x1 = min(w - 1, x1 + mx)
    y0 = max(0, y0 - my); y1 = min(h - 1, y1 + my)
    if (x1 - x0) < 0.22 * w or (y1 - y0) < 0.22 * h:
        return rgb                         # implausible -> safe fallback
    return rgb[y0:y1 + 1, x0:x1 + 1]


def enhance_common(pil, mode):
    if mode == "cover":
        pil = ImageEnhance.Color(pil).enhance(1.08)
        pil = ImageEnhance.Contrast(pil).enhance(1.06)
        pil = ImageEnhance.Brightness(pil).enhance(1.03)
        pil = pil.filter(ImageFilter.UnsharpMask(radius=2.2, percent=130, threshold=2))
    else:
        pil = ImageEnhance.Contrast(pil).enhance(1.12)
        pil = ImageEnhance.Brightness(pil).enhance(1.02)
        pil = pil.filter(ImageFilter.UnsharpMask(radius=1.8, percent=150, threshold=2))
    return pil


def place_on_canvas(pil):
    cw, ch = pil.size
    target_h = CONTENT_FRAC * CANVAS_H
    target_w = CONTENT_FRAC * CANVAS_W
    scale = min(target_h / ch, target_w / cw, MAX_UPSCALE)
    nw, nh = max(1, round(cw * scale)), max(1, round(ch * scale))
    resample = Image.LANCZOS
    content = pil.resize((nw, nh), resample)
    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), WHITE)
    canvas.paste(content, ((CANVAS_W - nw) // 2, (CANVAS_H - nh) // 2))
    return canvas


def process(path, mode):
    rgb = pil_to_rgb(path)
    if mode == "cover":
        crop, frac = segment_book(rgb)
        if crop is None:
            crop = whiten_bg_border(rgb)   # full-frame fallback + safe grey-edge cleanup
        # no gray-world WB on covers: it neutralizes intentionally-tinted covers
        pil = Image.fromarray(crop)
        pil = enhance_common(pil, "cover")
    else:
        rgb = deskew_page(rgb)
        rgb = flatfield_whiten(rgb, 0.92)
        rgb = segment_page(rgb)
        pil = Image.fromarray(rgb)
        pil = enhance_common(pil, "page")
    return place_on_canvas(pil)
