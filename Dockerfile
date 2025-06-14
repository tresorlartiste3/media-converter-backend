FROM python:3.9-slim

RUN apt-get update && \
    apt-get install -y ffmpeg git build-essential wget && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

EXPOSE 8000
CMD ["gunicorn", "server:app", "--bind", "0.0.0.0:8000"]