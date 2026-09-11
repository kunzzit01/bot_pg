FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Kuala_Lumpur \
    BOT_DATA_DIR=/app/data

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

RUN mkdir -p /app/data
VOLUME ["/app/data"]

CMD ["python", "bot.py"]
