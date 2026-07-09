# 🎨 Enhance Studio

**A local, privacy-first web app that batch-enhances your photos, scans, newspaper clippings and book pages — drag, drop, download.**

[![CI](https://github.com/madhav1337/enhance-studio/actions/workflows/ci.yml/badge.svg)](https://github.com/madhav1337/enhance-studio/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.x-000000?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![OpenCV](https://img.shields.io/badge/OpenCV-4.x%20%7C%205.x-5C3EE8?logo=opencv&logoColor=white)](https://opencv.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Enhance Studio wraps four purpose-built image-enhancement pipelines behind one clean browser UI. Everything runs **100% on your own machine** — no uploads to any server, no accounts, no internet required after install. Point it at a folder of phone photos of old prints, faded newspaper clippings, or book pages, and get clean, natural, higher-quality results back.

![Enhance Studio](docs/screenshot.png?v=2)

## 🔗 Links

- **Project page (GitHub Pages):** https://madhav1337.github.io/enhance-studio/
- **Source code:** https://github.com/madhav1337/enhance-studio
- **Run it locally:** see [Getting started](#-getting-started) below

> ℹ️ The project page above is a static showcase. Enhance Studio is a local Python/Flask
> app that does its image processing on your machine, so the actual enhancing runs when
> you launch it locally (or deploy it to a Python host such as Render or Hugging Face Spaces).

---

## ✨ Features

- **Drag & drop, one or many** — queue a whole batch; the page processes them one by one and shows live status.
- **Before / after wipe slider** — drag to compare the original and the enhanced result pixel-for-pixel.
- **Four specialised pipelines** (see below) — pick the right tool for each kind of image.
- **Per-image options** — e.g. optional auto-rotate, or force a book "cover" vs "text page" mode.
- **Download one, or download all as a ZIP.**
- **Non-destructive by design** — your originals are never read or modified; the app only touches uploaded copies.
- **Private & offline** — the server binds to `127.0.0.1` only. Your images never leave your computer.

## 🖼️ The four pipelines

| Pipeline | Best for | What it does |
| --- | --- | --- |
| **Photo Quality** | Any photo you just want cleaner & sharper | Edge-preserving denoise → gentle local contrast → high-quality Lanczos upscale → masked unsharp. Preserves composition, colours, faces and B&W **exactly** — no crop, no AI invention. |
| **Photo Extract** | Phone photos of printed photos/clippings on a table | Detects the print, perspective-corrects, deskews and crops it (confidence-gated so it **never cuts the subject**), then enhances naturally. |
| **Newspaper** | Scans of newspaper clippings | Auto-crop, deskew, edge-preserving denoise and text-edge-only sharpening — reads like a clean flatbed scan, not an AI image. Paper texture and colour preserved. |
| **Book / Document** | Book covers and text pages | Segments a cover/photo onto a clean white 3:4 canvas, **or** flat-field-whitens a text page and sharpens the text. Auto-picks the mode from the filename. |

## 🛠️ Tech stack

**Python · Flask · OpenCV · NumPy · Pillow · vanilla JS/HTML/CSS** (zero front-end build step)

## 🏗️ How it works

```
Browser (drag-drop, wipe slider, ZIP)  ──HTTP──▶  Flask app (app.py)
                                                       │
                                                       ▼
                                             pipelines.py  (uniform adapter)
                                                       │
                        ┌──────────────┬───────────────┼───────────────┐
                        ▼              ▼               ▼               ▼
                 quality.py      website.py        news.py          book.py
                                   ( pipeline_src/ — pure image-processing engines )
```

- `app.py` — a small Flask server: `upload → run pipeline → before/after + download`. One image per request; the page orchestrates the batch and the ZIP bundle.
- `pipelines.py` — a thin adapter exposing a single `enhance(pipeline, path, options)` call over all four engines.
- `pipeline_src/` — the four image-processing engines. Each is pure per-image logic (OpenCV/NumPy/Pillow) with built-in **safety gates** (e.g. "never cut the subject", "keep it natural, no HDR/halos").

## 🚀 Getting started

**Prerequisites:** Python 3.9+ installed.

```bash
# 1. Clone
git clone https://github.com/madhav1337/enhance-studio.git
cd enhance-studio

# 2. Create & activate a virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
python app.py
```

Then open **http://127.0.0.1:5000** (it opens automatically). On Windows you can also just double-click **`run.bat`**.

To stop the server, close its terminal window (or press `Ctrl+C`).

## 📖 Usage

1. Pick a pipeline (Photo Quality, Photo Extract, Newspaper, or Book / Document).
2. Drag one or more images onto the drop zone (`.jpg .jpeg .png .webp .tif .tiff .bmp`).
3. Watch each result appear; drag the **wipe slider** to compare before/after.
4. **Download** a single result, or **Download all** as a ZIP.

## 📁 Project structure

```
enhance-studio/
├── app.py              # Flask server & HTTP routes
├── pipelines.py        # uniform adapter over the four engines + UI metadata
├── pipeline_src/       # the image-processing engines
│   ├── quality.py
│   ├── website.py
│   ├── news.py
│   └── book.py
├── templates/index.html
├── static/{app.js, style.css}
├── tests/smoke_test.py # runs every pipeline on a synthetic image
├── .github/workflows/  # CI (installs deps, runs the smoke test)
├── requirements.txt
├── run.bat             # Windows launcher
└── LICENSE
```

## ✅ Testing

A lightweight smoke test runs a synthetic image through all four pipelines and
checks each produces a valid output:

```bash
python tests/smoke_test.py
```

It runs automatically on every push via [GitHub Actions](.github/workflows/ci.yml)
(Python 3.11 and 3.12) — see the **CI** badge at the top.

## 🔒 Security & privacy

- **Local only.** The server listens on `127.0.0.1` — it is not exposed to your network or the internet. (This uses Flask's development server, which is intended for local/personal use; don't expose it publicly.)
- **Your originals are safe.** Uploaded files are saved as copies under `uploads/`; results go to `outputs/`. The app never reads or writes anything else.
- **Hardened routes.** Filenames are sanitised, every file route resolves through `os.path.basename` (no path traversal), only image extensions are accepted, and uploads are capped at 128 MB.
- `uploads/` and `outputs/` are git-ignored and can be cleared anytime.

## 🗺️ Roadmap ideas

- [ ] Server-side batch queue with progress bar
- [ ] Optional pipeline parameter sliders in the UI
- [ ] Dockerfile for one-command setup

## 📄 License

Released under the [MIT License](LICENSE) — free to use, modify and share.
