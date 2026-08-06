FROM python:3.12-alpine

COPY exporter.py /app/exporter.py

USER nobody
EXPOSE 9835
CMD ["python", "/app/exporter.py"]
