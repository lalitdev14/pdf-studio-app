# --- build the frontend
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- runtime
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends \
      poppler-utils qpdf tesseract-ocr tesseract-ocr-eng libreoffice-writer libreoffice-calc libreoffice-impress \
      fonts-dejavu-core libheif1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/app ./app
COPY --from=web /web/dist ./dist
ENV FRONTEND_DIST=/srv/dist DATA_DIR=/data UNICODE_FONT_PATH=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf
RUN useradd -m app && mkdir /data && chown app /data
USER app
VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
