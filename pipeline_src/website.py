"""
Photo Extract engine — scanner-app style extraction + natural enhancement.

For phone photos of physical printed items (old prints, clippings, posters)
lying tilted on a surface. Confidence-gated subject extraction: find the
largest convex quad and perspective-warp it, else background-trim + small
deskew, else keep the full frame — it never cuts the subject. Enhancement is
gentle and natural (no HDR/halos): CLAHE, mild WB, light denoise, masked
unsharp, all on the L channel. Optional face-based 90-degree upright fix.

Bundled with Enhance Studio. Engine-only: the
batch/CLI wrapper and all personal paths have been removed; the per-image
image-processing logic is unchanged.
"""


import cv2
import numpy as np
from PIL import Image, ImageOps


def pil_to_bgr(im):
    arr = np.array(im.convert("RGB"))
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def bgr_to_pil(bgr):
    return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))


def is_grayscale(bgr, tol=10):
    """True if the image is effectively monochrome / sepia (low channel spread)."""
    b, g, r = cv2.split(bgr.astype(np.int16))
    # sepia/B&W -> the per-pixel max channel difference is small after equalizing means
    diff = np.mean(np.abs(r - g)) + np.mean(np.abs(g - b))
    return diff < tol


def order_corners(pts):
    pts = pts.reshape(4, 2).astype(np.float32)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array([
        pts[np.argmin(s)],   # top-left
        pts[np.argmin(d)],   # top-right
        pts[np.argmax(s)],   # bottom-right
        pts[np.argmax(d)],   # bottom-left
    ], dtype=np.float32)


def find_quad(bgr):
    """Return ordered 4 corners of the dominant print rectangle, or None.
    Gated: area must be 20-92% of frame, shape must be convex & rectangle-ish."""
    H, W = bgr.shape[:2]
    scale = 900.0 / max(H, W)
    small = cv2.resize(bgr, None, fx=scale, fy=scale) if scale < 1 else bgr.copy()
    sh, sw = small.shape[:2]
    frame_area = sh * sw

    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 9, 60, 60)
    edges = cv2.Canny(gray, 40, 130)
    edges = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=2)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))

    cnts, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    best, best_area = None, 0
    for c in cnts:
        area = cv2.contourArea(c)
        if area < 0.20 * frame_area or area > 0.92 * frame_area:
            continue
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        # rectangle-ness: contour area vs its minAreaRect area
        rect = cv2.minAreaRect(approx)
        (rw, rh) = rect[1]
        if rw < 1 or rh < 1:
            continue
        rect_area = rw * rh
        if area / rect_area < 0.85:      # not filling its bounding rect -> not a clean rectangle
            continue
        ar = max(rw, rh) / min(rw, rh)
        if ar > 4.0:                     # absurdly elongated -> reject
            continue
        if area > best_area:
            best_area, best = area, approx

    if best is None:
        return None
    corners = order_corners(best) / scale
    return corners


def warp_quad(bgr, corners):
    (tl, tr, br, bl) = corners
    wA = np.linalg.norm(br - bl); wB = np.linalg.norm(tr - tl)
    hA = np.linalg.norm(tr - br); hB = np.linalg.norm(tl - bl)
    W = int(round(max(wA, wB))); H = int(round(max(hA, hB)))
    if W < 50 or H < 50:
        return None
    dst = np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], dtype=np.float32)
    M = cv2.getPerspectiveTransform(corners, dst)
    return cv2.warpPerspective(bgr, M, (W, H), flags=cv2.INTER_CUBIC,
                               borderMode=cv2.BORDER_REPLICATE)


def foreground_region(bgr):
    """Estimate the whole-subject foreground blob vs the border background.
    Returns dict(bbox, frac, angle, area) or None."""
    H, W = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    b = max(4, int(0.02 * min(H, W)))
    border = np.concatenate([
        gray[:b, :].ravel(), gray[-b:, :].ravel(),
        gray[:, :b].ravel(), gray[:, -b:].ravel()])
    bg = float(np.median(border))
    diff = np.abs(gray.astype(np.int16) - bg)
    mask = (diff > 28).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    area = cv2.contourArea(c)
    rect = cv2.minAreaRect(c)
    ang = rect[2]
    if ang < -45:
        ang += 90
    x, y, w, h = cv2.boundingRect(c)
    return {"bbox": (x, y, w, h), "frac": area / (H * W), "angle": ang,
            "bbox_area": float(w * h)}


def crop_from_region(bgr, fg):
    H, W = bgr.shape[:2]
    x, y, w, h = fg["bbox"]
    pad = int(0.01 * min(H, W))
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1, y1 = min(W, x + w + pad), min(H, y + h + pad)
    crop = bgr[y0:y1, x0:x1]
    ang = fg["angle"]
    if 0.4 < abs(ang) <= 15:
        ch, cw = crop.shape[:2]
        M = cv2.getRotationMatrix2D((cw / 2, ch / 2), ang, 1.0)
        crop = cv2.warpAffine(crop, M, (cw, ch), flags=cv2.INTER_CUBIC,
                              borderMode=cv2.BORDER_REPLICATE)
    return crop


def extract_subject(bgr):
    """Return (image, method_str).

    Safety gate against cutting content: a detected rectangle is only used for a
    perspective warp when it is nearly as large as the whole foreground blob.
    A small rectangle inside a larger subject (e.g. one photo inside a newspaper
    clipping with caption text) is rejected -> we crop the whole subject instead.
    """
    fg = foreground_region(bgr)
    quad = find_quad(bgr)

    if quad is not None:
        quad_area = abs(cv2.contourArea(quad.astype(np.float32)))
        is_outer = (fg is None) or (quad_area >= 0.72 * fg["bbox_area"])
        if is_outer:
            w = warp_quad(bgr, quad)
            if w is not None:
                return w, "quad-warp"

    if fg is not None and 0.15 < fg["frac"] < 0.97:
        return crop_from_region(bgr, fg), "trim-deskew"
    return bgr, "full-frame"


def auto_orient(bgr):
    try:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        det = cv2.CascadeClassifier(cascade_path)
        if det.empty():
            return bgr, 0
    except Exception:
        return bgr, 0
    best_rot, best_score = 0, -1.0
    for rot in (0, 90, 180, 270):
        if rot == 0:
            test = bgr
        else:
            code = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
                    270: cv2.ROTATE_90_COUNTERCLOCKWISE}[rot]
            test = cv2.rotate(bgr, code)
        g = cv2.cvtColor(test, cv2.COLOR_BGR2GRAY)
        g = cv2.equalizeHist(g)
        faces = det.detectMultiScale(g, scaleFactor=1.1, minNeighbors=6,
                                     minSize=(40, 40))
        score = sum(w * h for (x, y, w, h) in faces)
        if rot == 0:
            score *= 1.2          # bias toward leaving orientation unchanged
        if score > best_score:
            best_score, best_rot = score, rot
    if best_rot == 0 or best_score <= 0:
        return bgr, 0
    code = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
            270: cv2.ROTATE_90_COUNTERCLOCKWISE}[best_rot]
    return cv2.rotate(bgr, code), best_rot


def gentle_white_balance(bgr):
    """Mild gray-world WB, gain clamped to +/-12%. Skipped for B&W/sepia."""
    if is_grayscale(bgr):
        return bgr
    res = bgr.astype(np.float32)
    means = res.reshape(-1, 3).mean(axis=0)
    gray = means.mean()
    gains = np.clip(gray / np.maximum(means, 1e-3), 0.88, 1.12)
    res *= gains
    return np.clip(res, 0, 255).astype(np.uint8)


def enhance(bgr):
    # 1) gentle white balance
    bgr = gentle_white_balance(bgr)

    # 2) light edge-preserving denoise (kills grain/compression noise, keeps edges)
    bgr = cv2.bilateralFilter(bgr, 5, 35, 35)

    # work in LAB; all tonal/sharpen on L only -> no color shifts, no halos in chroma
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    L, A, B = cv2.split(lab)

    # 3) gentle local contrast (exposure/contrast lift without HDR look)
    clahe = cv2.createCLAHE(clipLimit=1.4, tileGridSize=(8, 8))
    L = clahe.apply(L)

    # 4) very mild global levels: clip 0.5/99.5 percentile, blend 50% to stay natural
    lo, hi = [float(v) for v in np.percentile(L, [0.5, 99.5])]
    if hi - lo > 30:
        Lf0 = L.astype(np.float32)
        stretched = np.clip((Lf0 - lo) * (255.0 / (hi - lo)), 0, 255)
        L = np.clip(0.5 * Lf0 + 0.5 * stretched, 0, 255).astype(np.uint8)

    # 5) masked / threshold unsharp on L (sharpen only meaningful edges -> no noise/halo)
    Lf = L.astype(np.float32)
    blur = cv2.GaussianBlur(Lf, (0, 0), 1.4)
    high = Lf - blur
    mask = (np.abs(high) > 3).astype(np.float32)        # threshold to skip flat areas
    L = np.clip(Lf + 0.45 * high * mask, 0, 255).astype(np.uint8)

    lab = cv2.merge([L, A, B])
    out = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

    # 6) subtle saturation lift ONLY if undersaturated; hard-capped (no oversaturation)
    if not is_grayscale(out):
        hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV).astype(np.float32)
        s_mean = hsv[..., 1].mean()
        if s_mean < 110:
            factor = min(1.10, 1.0 + (110 - s_mean) / 600.0)
            hsv[..., 1] = np.clip(hsv[..., 1] * factor, 0, 255)
            out = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    return out


def process_image(in_path, do_orient):
    im = Image.open(in_path)
    im = ImageOps.exif_transpose(im)
    fmt = (im.format or "").upper()
    bgr = pil_to_bgr(im)
    orig_shape = bgr.shape[:2]

    sub, method = extract_subject(bgr)
    rot = 0
    if do_orient:
        sub, rot = auto_orient(sub)
    enhanced = enhance(sub)
    return bgr, enhanced, method, rot, orig_shape, fmt
