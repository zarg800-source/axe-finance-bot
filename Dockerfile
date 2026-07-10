FROM python:3.11-slim-bookworm

WORKDIR /app

# Install tesseract OCR (still needed by receipt_parser.py's OCR fallback)
RUN apt-get update && apt-get install -y tesseract-ocr && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY core.py .
COPY receipt_parser.py .
COPY render_main.py .
COPY finance.db .
COPY entrypoint.sh .
COPY dashboard.html .
COPY cfo-finance-bot.html .
RUN chmod +x /app/entrypoint.sh

# Create a directory for the database and ensure it's writable
RUN mkdir -p /data
VOLUME /data

CMD ["/app/entrypoint.sh"]
