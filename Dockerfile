FROM python:3.11-slim-buster

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY render_main.py .
COPY finance.db .
COPY entrypoint.sh .
RUN chmod +x /app/entrypoint.sh

# Create a directory for the database and ensure it's writable
RUN mkdir -p /data
VOLUME /data

CMD ["/app/entrypoint.sh"]
