# syntax=docker/dockerfile:1.7

FROM python:3.12.6-slim

LABEL org.opencontainers.image.source="https://example.local/clara" \
      org.opencontainers.image.description="Offline Scientific Writing Suite core tooling image"

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install system dependencies for LaTeX tooling (Debian packages pinned by name).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        chktex \
        texlive-extra-utils \
        perl \
        libyaml-tiny-perl \
        libfile-homedir-perl \
        locales \
        git \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Generate UTF-8 locales required by LanguageTool/Vale.
RUN sed -i 's/^# *\\(en_US.UTF-8\\)/\\1/' /etc/locale.gen \
    && sed -i 's/^# *\\(de_DE.UTF-8\\)/\\1/' /etc/locale.gen \
    && locale-gen

# Tectonic 0.15.0 – pinned release archive.
ARG TECTONIC_VERSION=0.15.0
ARG TARGETARCH
RUN set -eux; \
    case "${TARGETARCH}" in \
      amd64) TECTONIC_ARCH="x86_64-unknown-linux-gnu" ;; \
      arm64) TECTONIC_ARCH="aarch64-unknown-linux-musl" ;; \
      *) echo "Unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40${TECTONIC_VERSION}/tectonic-${TECTONIC_VERSION}-${TECTONIC_ARCH}.tar.gz" -o /tmp/tectonic.tar.gz; \
    tar -xzf /tmp/tectonic.tar.gz -C /tmp; \
    if [ -f "/tmp/tectonic-${TECTONIC_VERSION}-${TECTONIC_ARCH}/tectonic" ]; then \
        install -m 0755 "/tmp/tectonic-${TECTONIC_VERSION}-${TECTONIC_ARCH}/tectonic" /usr/local/bin/tectonic; \
    elif [ -f /tmp/tectonic/tectonic ]; then \
        install -m 0755 /tmp/tectonic/tectonic /usr/local/bin/tectonic; \
    elif [ -f /tmp/tectonic ]; then \
        install -m 0755 /tmp/tectonic /usr/local/bin/tectonic; \
    else \
        echo "Tectonic binary not found in archive" >&2; exit 1; \
    fi; \
    rm -rf /tmp/tectonic /tmp/tectonic-* /tmp/tectonic.tar.gz

# Vale 3.6.0 – pinned binary release.
ARG VALE_VERSION=3.6.0
RUN set -eux; \
    case "${TARGETARCH}" in \
      amd64) VALE_PKG="vale_${VALE_VERSION}_Linux_64-bit.tar.gz" ;; \
      arm64) VALE_PKG="vale_${VALE_VERSION}_Linux_arm64.tar.gz" ;; \
      *) echo "Unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://github.com/errata-ai/vale/releases/download/v${VALE_VERSION}/${VALE_PKG}" -o /tmp/vale.tar.gz; \
    tar -xzf /tmp/vale.tar.gz -C /tmp; \
    if [ -f /tmp/vale ]; then \
        install -m 0755 /tmp/vale /usr/local/bin/vale; \
    elif [ -f /tmp/vale/vale ]; then \
        install -m 0755 /tmp/vale/vale /usr/local/bin/vale; \
    else \
        echo "Vale binary not found in archive" >&2; exit 1; \
    fi; \
    rm -rf /tmp/vale /tmp/vale.tar.gz

# Python tooling (codespell) with pinned version.
RUN pip install --no-cache-dir codespell==2.3.0

# Project Python dependencies.
COPY src/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

WORKDIR /work
ENV PYTHONPATH=/work/src

CMD ["python", "-m", "clara.cli"]
