FROM python:3.12-slim

WORKDIR /app

# System deps for markitdown (pdf, docx) and playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install --no-cache-dir uv

# Copy dependency metadata first (cache layer)
COPY pyproject.toml .
RUN uv sync --no-dev

# Copy source
COPY harness/ ./harness/
COPY mcp_server.py op.py ./
COPY .env.example .env.example

# Runtime data directory
RUN mkdir -p data

EXPOSE 7860

CMD ["python", "-m", "harness.api.main"]
