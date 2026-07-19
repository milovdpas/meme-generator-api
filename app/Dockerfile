FROM python:3.12-slim
WORKDIR /app

# libgl1/libglib2.0-0: required by opencv-python (not present in slim images)
# curl: used by the Ofelia cleanup job (see docker-compose.prod.yml labels)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://localhost:5000/health || exit 1
# --timeout 3000: video generation is long-running
CMD ["gunicorn", "--workers", "3", "--bind", "0.0.0.0:5000", "--timeout", "3000", "app:app"]
