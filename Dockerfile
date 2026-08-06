FROM python:3.12-alpine

COPY exporter.py /app/exporter.py

USER nobody
EXPOSE 9835

# /healthz не трогает свитчи — только подтверждает, что HTTP-сервер жив.
# Shell-форма ради подстановки LISTEN_PORT.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -q --spider "http://127.0.0.1:${LISTEN_PORT:-9835}/healthz" || exit 1

CMD ["python", "/app/exporter.py"]
