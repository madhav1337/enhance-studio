"""Quick end-to-end check: run a synthetic image through all four pipelines."""
import os, tempfile
import numpy as np
from PIL import Image, ImageDraw

import pipelines


def make_test_image():
    # gray "table" background with a tilted colourful "print" bearing some text/shapes
    W, H = 900, 1200
    bg = np.full((H, W, 3), 150, np.uint8)
    img = Image.fromarray(bg)
    d = ImageDraw.Draw(img)
    d.rectangle([180, 240, 720, 960], fill=(210, 180, 140))       # the "photo"
    d.ellipse([320, 380, 580, 640], fill=(90, 120, 200))          # a subject blob
    for i in range(8):                                            # some "text" lines
        d.rectangle([230, 700 + i * 26, 670, 700 + i * 26 + 10], fill=(40, 40, 40))
    img = img.rotate(4, expand=False, fillcolor=(150, 150, 150))  # slight tilt
    path = os.path.join(tempfile.gettempdir(), "enhance_smoke_in.jpg")
    img.save(path, "JPEG", quality=95)
    return path


def main():
    src = make_test_image()
    cases = [
        ("quality", {}),
        ("website", {"orient": False}),
        ("news", {}),
        ("book", {"mode": "auto"}),
        ("book", {"mode": "cover"}),
        ("book", {"mode": "page"}),
    ]
    ok = 0
    for pid, opts in cases:
        try:
            pil, info = pipelines.enhance(pid, src, opts)
            assert pil.mode in ("RGB", "L") and pil.size[0] > 0
            print(f"OK   {pid:8s} {str(opts):24s} -> {pil.size}  {info.get('method','')}")
            ok += 1
        except Exception as ex:
            import traceback; traceback.print_exc()
            print(f"FAIL {pid:8s} {opts}: {type(ex).__name__}: {ex}")
    print(f"\n{ok}/{len(cases)} pipeline runs succeeded")
    raise SystemExit(0 if ok == len(cases) else 1)


if __name__ == "__main__":
    main()
