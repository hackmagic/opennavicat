FROM python:3.12-slim AS builder

RUN pip install --no-cache-dir open-navicat

FROM python:3.12-slim

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/opennavicat /usr/local/bin/opennavicat

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENTRYPOINT ["opennavicat"]
CMD ["--help"]
