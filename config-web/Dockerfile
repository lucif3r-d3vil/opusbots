FROM python:3.11-slim

WORKDIR /app

COPY config-web/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ shared/
COPY bots/ bots/

COPY config-web/app.py .
COPY config-web/templates/ templates/

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    CONFIG_PATH=/config/config.json

CMD ["python", "app.py"]
