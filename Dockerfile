FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir -e .

COPY . .

RUN chmod +x scripts/entrypoint.sh

EXPOSE 8000

CMD ["sh", "scripts/entrypoint.sh"]
