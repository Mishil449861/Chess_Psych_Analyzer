# Multi-stage build keeps the final image small.
# Stage 1: builder with full toolchain for pip wheels.
FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: runtime — slim, with stockfish + just the pip site-packages we built.
FROM python:3.12-slim

# Stockfish from apt: avoids needing to compile inside the image.
RUN apt-get update \
 && apt-get install -y --no-install-recommends stockfish \
 && rm -rf /var/lib/apt/lists/*

# Copy pip --user installs from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    STOCKFISH_PATH=/usr/games/stockfish \
    CHESS_PSYCH_DB=/data/chess_psych.db

WORKDIR /app
COPY *.py ./
COPY tests ./tests

# Mount a volume here in production to persist the DB
VOLUME ["/data"]

ENTRYPOINT ["python", "cli.py"]
CMD ["--help"]
