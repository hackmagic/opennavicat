# Build the CLI from the checked-out source, not from PyPI.
#
# This image used to run `pip install open-navicat`, which can only install a
# version PyPI actually has. When a release is cut before the PyPI publish job
# has succeeded -- or when publishing is broken -- the image build pulled an
# ancient version, or failed outright, even though the tag contained the code it
# was supposed to ship. Installing the local tree makes the image always match
# the commit that triggered it.
FROM python:3.12-slim AS builder

WORKDIR /build

# Copy only what the build needs so the dependency layer caches well.
COPY pyproject.toml poetry.lock README.md ./
COPY open_navicat ./open_navicat

RUN pip install --no-cache-dir --upgrade pip build \
    && python -m build --wheel --outdir /dist

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl

# Run as a non-root user; the CLI writes connection profiles under $HOME.
RUN useradd --create-home --uid 10001 opennavicat
USER opennavicat

ENTRYPOINT ["opennavicat"]
CMD ["--help"]
