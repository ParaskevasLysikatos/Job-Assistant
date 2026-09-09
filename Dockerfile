FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Athens

WORKDIR /app

# Dependencies first so code edits don't invalidate the pip layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code (templates included).
COPY src/ ./src/

# Mounted at runtime by docker-compose, created here so the image also
# works standalone with `docker run`.
RUN mkdir -p /app/output /app/data

ENTRYPOINT ["python", "-m", "src.main"]
CMD []
