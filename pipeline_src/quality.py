"""
Photo Quality engine — content-preserving upscale + denoise + sharpen.

Makes the same photograph higher-resolution and cleaner while preserving
composition, colours, faces and B&W exactly. No crop, no deskew, no rotation
(only EXIF orientation is baked in), no generative/AI super-resolution:
upscaling is high-quality Lanczos interpolation only, so nothing is invented.
All tonal/sharpen work is on the L (luma) channel; chroma is never touched.

Bundled with Enhance Studio. Engine-only: the
batch/CLI wrapper and all personal paths have been removed; the per-image
image-processing logic is unchanged.
"""


import cv2
import numpy as np
from PIL import Image, ImageOps


TARGET_LONG = 3000
MAX_FACTOR = 2.0


def pil_to_bgr(im):
    return cv2.cvtColor(np.array(im.convert("RGB")), cv2.COLOR_RGB2BGR)


def bgr_to_pil(bgr):
    return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))


def upscale_factor(h, w):
    long_edge = max(h, w)
    if long_edge >= TARGET_LONG:
        return 1.0
    return min(MAX_FACTOR, TARGET_LONG / float(long_edge))


def enhance_quality(bgr):
    """Content-preserving quality enhancement. Returns enhanced BGR."""
    # 1) LIGHT edge-preserving denoise (grain / compression / minor scan noise).
    #    Kept deliberately gentle so skin texture & fine detail survive (no waxy /
    #    beautified look, no blotchy patches in smooth backgrounds).
    den = cv2.fastNlMeansDenoisingColored(bgr, None, h=2, hColor=2,
                                          templateWindowSize=7, searchWindowSize=21)

    # 2) gentle local-contrast clarity on L only (no color shift, no HDR)
    lab = cv2.cvtColor(den, cv2.COLOR_BGR2LAB)
    L, A, B = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=1.2, tileGridSize=(8, 8))
    L = clahe.apply(L)
    den = cv2.cvtColor(cv2.merge([L, A, B]), cv2.COLOR_LAB2BGR)

    # 3) high-quality Lanczos upscale (genuine resolution increase, no generation)
    h, w = den.shape[:2]
    f = upscale_factor(h, w)
    if f > 1.001:
        den = cv2.resize(den, (int(round(w * f)), int(round(h * f))),
                         interpolation=cv2.INTER_LANCZOS4)

    # 4) masked/threshold unsharp on L only (crisp edges, no halos / noise boost)
    lab = cv2.cvtColor(den, cv2.COLOR_BGR2LAB)
    L, A, B = cv2.split(lab)
    Lf = L.astype(np.float32)
    blur = cv2.GaussianBlur(Lf, (0, 0), 1.2)
    high = Lf - blur
    mask = (np.abs(high) > 3).astype(np.float32)
    L = np.clip(Lf + 0.4 * high * mask, 0, 255).astype(np.uint8)
    out = cv2.cvtColor(cv2.merge([L, A, B]), cv2.COLOR_LAB2BGR)
    return out


def process_image(in_path):
    im = ImageOps.exif_transpose(Image.open(in_path))
    bgr = pil_to_bgr(im)
    enh = enhance_quality(bgr)
    return bgr, enh, bgr.shape[:2], enh.shape[:2]
