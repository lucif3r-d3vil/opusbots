FROM python:3.11-slim

WORKDIR /app

COPY config-web/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Reuse the same config.py the bots use, so both sides always agree on schema
COPY shared/config.py shared/config.py
RUN touch shared/__init__.py

COPY config-web/app.py .
COPY config-web/templates/ templates/

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    CONFIG_PATH=/config/config.json

CMD ["python", "app.py"]
