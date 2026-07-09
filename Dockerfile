# Universal container for Enhance Studio — works on Hugging Face Spaces (SDK: docker),
# Render, Fly.io, Railway, or any Docker host.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    MAX_UPLOAD_MB=25 \
    STUDIO_NO_BROWSER=1

WORKDIR /app

# Minimal system libs some OpenCV/NumPy paths expect (kept small).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

# Hugging Face Spaces expects 7860; Render/others inject $PORT. Both are handled.
EXPOSE 7860
CMD ["sh", "-c", "gunicorn app:app -b 0.0.0.0:${PORT:-7860} -w 1 -t 120"]
