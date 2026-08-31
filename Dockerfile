FROM python:3.12-slim

WORKDIR /app

RUN useradd --create-home --uid 1000 appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY templates ./templates
COPY static ./static
COPY scripts ./scripts

RUN mkdir -p /app/data \
    && chmod +x /app/scripts/*.sh \
    && chown -R appuser:appuser /app

USER appuser

ENV PYTHONPATH=/app
ENV BAKERY_APPLY_DB=/app/data/app.db
ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

CMD ["./scripts/docker-entrypoint.sh"]
