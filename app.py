r"""
Enhance Studio - a local drag-and-drop web front-end for four image-enhancement
pipelines (photo quality, photo extract, newspaper, book/document).

Run it (after `pip install -r requirements.txt`):

    python app.py

then open http://127.0.0.1:5000 (it also opens automatically). The server binds
to 127.0.0.1 only, so it is reachable from this machine, not the network.

Originals are safe: uploaded files are copies stored under ./uploads, and the
enhancement code only ever reads those copies.
"""
import os
import io
import re
import uuid
import zipfile
import traceback

from flask import (Flask, request, jsonify, render_template,
                   send_from_directory, send_file, abort)

import pipelines

APP_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(APP_DIR, "uploads")
OUTPUT_DIR = os.path.join(APP_DIR, "outputs")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 128 * 1024 * 1024   # 128 MB per image


def _safe_stem(filename):
    stem = os.path.splitext(os.path.basename(filename or "image"))[0]
    stem = SAFE_NAME.sub("_", stem).strip("_")
    return stem or "image"


def _save_pil(pil, out_path):
    if pil.mode not in ("RGB", "L"):
        pil = pil.convert("RGB")
    ext = os.path.splitext(out_path)[1].lower()
    if ext == ".png":
        pil.save(out_path, "PNG", optimize=True)
    else:
        pil.save(out_path, "JPEG", quality=95, progressive=True,
                 optimize=True, subsampling=0)


@app.route("/")
def index():
    return render_template("index.html", pipelines=pipelines.PIPELINES)


@app.route("/api/enhance", methods=["POST"])
def api_enhance():
    pipeline = request.form.get("pipeline", "")
    if pipeline not in pipelines._RUNNERS:
        return jsonify({"ok": False, "error": f"unknown pipeline {pipeline!r}"}), 400

    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"ok": False, "error": "no file uploaded"}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXT:
        return jsonify({"ok": False, "error": f"unsupported type {ext}"}), 400

    # options come across as strings in multipart form data
    options = {}
    if "orient" in request.form:
        options["orient"] = request.form.get("orient") == "true"
    if "mode" in request.form:
        options["mode"] = request.form.get("mode")

    uid = uuid.uuid4().hex
    in_name = f"{uid}{ext}"
    in_path = os.path.join(UPLOAD_DIR, in_name)
    file.save(in_path)

    try:
        pil_out, info = pipelines.enhance(pipeline, in_path, options)
    except Exception as ex:                       # report per-file, keep server up
        traceback.print_exc()
        return jsonify({"ok": False, "error": f"{type(ex).__name__}: {ex}",
                        "original_name": file.filename}), 500

    out_ext = ".png" if ext == ".png" else ".jpg"
    out_name = f"{uid}_out{out_ext}"
    _save_pil(pil_out, os.path.join(OUTPUT_DIR, out_name))

    download_name = f"{_safe_stem(file.filename)}_{pipeline}{out_ext}"
    return jsonify({
        "ok": True,
        "original_name": file.filename,
        "original_url": f"/uploads/{in_name}",
        "enhanced_url": f"/outputs/{out_name}",
        "output_id": out_name,
        "download_name": download_name,
        "info": info,
    })


@app.route("/api/zip", methods=["POST"])
def api_zip():
    """Bundle a set of already-produced outputs into a single download."""
    data = request.get_json(silent=True) or {}
    items = data.get("items", [])
    if not items:
        return jsonify({"ok": False, "error": "no items"}), 400
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        seen = {}
        for it in items:
            oid = os.path.basename(it.get("output_id", ""))
            src = os.path.join(OUTPUT_DIR, oid)
            if not oid or not os.path.exists(src):
                continue
            arc = it.get("download_name") or oid
            arc = os.path.basename(arc)
            # de-duplicate arcnames so nothing is silently dropped from the zip
            if arc in seen:
                seen[arc] += 1
                stem, ext = os.path.splitext(arc)
                arc = f"{stem}_{seen[arc]}{ext}"
            else:
                seen[arc] = 0
            zf.write(src, arc)
    buf.seek(0)
    return send_file(buf, mimetype="application/zip",
                     as_attachment=True, download_name="enhanced.zip")


@app.route("/download/<name>")
def download(name):
    name = os.path.basename(name)
    if not os.path.exists(os.path.join(OUTPUT_DIR, name)):
        abort(404)
    dl = request.args.get("as", name)
    return send_from_directory(OUTPUT_DIR, name, as_attachment=True,
                               download_name=os.path.basename(dl))


@app.route("/uploads/<name>")
def serve_upload(name):
    return send_from_directory(UPLOAD_DIR, os.path.basename(name))


@app.route("/outputs/<name>")
def serve_output(name):
    return send_from_directory(OUTPUT_DIR, os.path.basename(name))


def _open_browser(url):
    """Open the app in Brave if it's installed, else the system default browser."""
    import webbrowser
    candidates = [
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                     "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            try:
                webbrowser.register("brave", None, webbrowser.BackgroundBrowser(path))
                webbrowser.get("brave").open(url)
                return
            except Exception:
                break
    webbrowser.open(url)


if __name__ == "__main__":
    import threading

    port = int(os.environ.get("PORT", "5000"))
    url = f"http://127.0.0.1:{port}"
    # open the browser shortly after the server starts (STUDIO_NO_BROWSER=1 to skip)
    if os.environ.get("STUDIO_NO_BROWSER") != "1" and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        threading.Timer(1.2, lambda: _open_browser(url)).start()
    print(f"\n  Enhance Studio -> {url}\n")
    app.run(host="127.0.0.1", port=port, threaded=True, debug=False)
