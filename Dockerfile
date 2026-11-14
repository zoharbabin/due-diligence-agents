# ---- Build stage ----
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS builder

WORKDIR /build

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY src/ src/

RUN pip install --no-cache-dir --prefix=/install .

# ---- Runtime stage ----
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

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
