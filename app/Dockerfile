FROM python:3.12-slim
WORKDIR /app

# Runtime libraries required by opencv-python (not present in slim images)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')" || exit 1
# --timeout 3000: video generation is long-running
CMD ["gunicorn", "--workers", "3", "--bind", "0.0.0.0:5000", "--timeout", "3000", "app:app"]
