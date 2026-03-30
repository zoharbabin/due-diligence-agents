# ---- Build stage ----
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY src/ src/

RUN pip install --no-cache-dir --prefix=/install .

# ---- Runtime stage ----
FROM python:3.12-slim

LABEL maintainer="dd-agents team"
LABEL description="Forensic M&A due diligence pipeline using Claude Agent SDK"

RUN apt-get update && \
    apt-get install -y --no-install-recommends poppler-utils && \
    rm -rf /var/lib/apt/lists/* && \
    useradd --create-home --shell /bin/bash ddagent

COPY --from=builder /install /usr/local

WORKDIR /workspace

USER ddagent

ENTRYPOINT ["dd-agents"]
CMD ["--help"]
