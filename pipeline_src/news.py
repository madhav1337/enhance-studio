"""
Newspaper engine — natural archival restoration.

For scans/photos of newspaper clippings. Aims to look like a clean flatbed
scan, not an AI image: auto-crop, small-angle deskew, edge-preserving
bilateral denoise (smooths paper grain, keeps texture), gentle CLAHE and
threshold ('masked') unsharp that sharpens only true text edges. All tonal
work on the L channel, so paper colour and texture are preserved. No OCR.

Bundled with Enhance Studio. Engine-only: the
batch/CLI wrapper and all personal paths have been removed; the per-image
image-processing logic is unchanged.
"""


import cv2
import numpy as np
from PIL import Image, ImageOps


MAX_SKEW_DEG = 10.0


def load_bgr(path):
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        rgb = np.asarray(im)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def bg_color(bgr):
    h, w = bgr.shape[:2]
    p = max(4, min(h, w) // 40)
    patches = np.concatenate([
        bgr[:p, :p].reshape(-1, 3), bgr[:p, w - p:].reshape(-1, 3),
        bgr[h - p:, :p].reshape(-1, 3), bgr[h - p:, w - p:].reshape(-1, 3)])
    return np.median(patches, axis=0)


def auto_crop(bgr):
    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    mag = cv2.magnitude(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3),
                        cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))
    col = mag.sum(axis=0); row = mag.sum(axis=1)
    k = max(3, (min(h, w) // 100) | 1)
    col = cv2.GaussianBlur(col.reshape(1, -1), (k, 1), 0).ravel()
    row = cv2.GaussianBlur(row.reshape(-1, 1), (1, k), 0).ravel()
    if col.max() <= 0 or row.max() <= 0:
        return bgr, False
    cidx = np.where(col > 0.04 * col.max())[0]
    ridx = np.where(row > 0.04 * row.max())[0]
    if cidx.size == 0 or ridx.size == 0:
        return bgr, False
    x0, x1 = int(cidx[0]), int(cidx[-1]); y0, y1 = int(ridx[0]), int(ridx[-1])
    px = max(2, int(0.01 * w)); py = max(2, int(0.01 * h))
    x0 = max(0, x0 - px); x1 = min(w, x1 + px + 1)
    y0 = max(0, y0 - py); y1 = min(h, y1 + py + 1)
    nw, nh = x1 - x0, y1 - y0
    removed = (x0 > px) or (y0 > py) or (x1 < w - px) or (y1 < h - py)
    keeps = (nw * nh) >= 0.45 * (w * h) and nw > 0.3 * w and nh > 0.3 * h
    if removed and keeps:
        return bgr[y0:y1, x0:x1].copy(), True
    return bgr, False


def _proj_score(binary, angle):
    h, w = binary.shape
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    rot = cv2.warpAffine(binary, M, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
    proj = rot.sum(axis=1, dtype=np.float64)
    return float(((proj[1:] - proj[:-1]) ** 2).sum())


def deskew(bgr, bg):
    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    scale = 1000.0 / max(h, w)
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else gray
    binary = cv2.threshold(small, 0, 1, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    best = max((_proj_score(binary, a), a) for a in np.arange(-MAX_SKEW_DEG, MAX_SKEW_DEG + 1e-3, 0.5))[1]
    best = max((_proj_score(binary, a), a) for a in np.arange(best - 0.5, best + 0.5 + 1e-3, 0.1))[1]
    if abs(best) < 0.2:
        return bgr, 0.0
    best = float(np.clip(best, -MAX_SKEW_DEG, MAX_SKEW_DEG))
    M = cv2.getRotationMatrix2D((w / 2, h / 2), best, 1.0)
    out = cv2.warpAffine(bgr, M, (w, h), flags=cv2.INTER_CUBIC,
                         borderMode=cv2.BORDER_CONSTANT,
                         borderValue=tuple(float(c) for c in bg))
    return out, best


def edge_preserving_denoise(bgr):
    """Bilateral filter: smooths paper grain, keeps text edges + paper texture.
    Light settings so the result doesn't look plasticky."""
    return cv2.bilateralFilter(bgr, d=7, sigmaColor=30, sigmaSpace=6)


def gentle_clahe(l):
    return cv2.createCLAHE(clipLimit=1.2, tileGridSize=(16, 16)).apply(l)


def masked_unsharp(l, amount=0.35, sigma=1.0, threshold=4):
    """Unsharp that only acts on real edges (|detail| > threshold). Flat paper
    is left alone -> no grain amplification, no halos. Gentle amount."""
    lf = l.astype(np.float32)
    blur = cv2.GaussianBlur(lf, (0, 0), sigma)
    detail = lf - blur
    detail[np.abs(detail) < threshold] = 0.0          # ignore paper micro-noise
    out = lf + amount * detail
    return np.clip(out, 0, 255).astype(np.uint8)


def natural_tone(bgr):
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = gentle_clahe(l)            # mild local contrast only
    l = masked_unsharp(l)          # edge-only crispness, no halos/grain
    return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)


def enhance(path):
    bgr = load_bgr(path)
    in_h, in_w = bgr.shape[:2]
    bgr, cropped = auto_crop(bgr)
    bg = bg_color(bgr)
    bgr, angle = deskew(bgr, bg)
    bgr = edge_preserving_denoise(bgr)
    bgr = natural_tone(bgr)
    bgr = np.clip(bgr, 0, 255).astype(np.uint8)
    out_h, out_w = bgr.shape[:2]
    return bgr, dict(in_dim=(in_w, in_h), out_dim=(out_w, out_h),
                     cropped=cropped, skew=angle)
