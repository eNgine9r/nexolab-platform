# Isolated fixed-Python candidate for CVE-2026-19445.
# Debian 13's distroless/python3 bundles affected CPython 3.13.5.
# Build upstream fixed CPython 3.13.16 and transplant ONLY /usr/local
# into the minimal Debian13 distroless base, preserving nonroot identity.
# PR-only — never deploy without evidence and an explicit operator cutover.
FROM python:3.13.16-slim-trixie AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/app
COPY requirements.txt ./
RUN python -m pip install --target /opt/app/site-packages -r requirements.txt
COPY *.py ./
# pip, vendored setuptools/urllib3/msgpack and installer tooling are
# build-only and must not enter the minimal runtime image.
RUN mkdir -p /opt/runtime-data \
    && find /opt/app -type d -exec chmod 0755 {} + \
    && find /opt/app -type f -exec chmod 0644 {} + \
    && rm -rf /usr/local/lib/python3.13/site-packages/pip \
              /usr/local/lib/python3.13/site-packages/pip-*.dist-info \
              /usr/local/lib/python3.13/site-packages/setuptools \
              /usr/local/lib/python3.13/site-packages/setuptools-*.dist-info \
              /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13

# The minimal distroless base omits Python's SQLite shared library, even
# though the upstream Python standard library needs it for acquisition state.
# Copy only the real ABI-matched library from the pinned build stage.
# Its Debian package provenance/version must remain part of the release review.
RUN mkdir -p /opt/runtime-libs \
    && sqlite_lib="$(find /usr/lib -name libsqlite3.so.0 -print -quit)" \
    && test -n "$sqlite_lib" \
    && cp -L "$sqlite_lib" /opt/runtime-libs/libsqlite3.so.0 \
    && chmod 0644 /opt/runtime-libs/libsqlite3.so.0

# CVE-2026-124851 (#1743): gcr.io/distroless/base-debian13 still ships the
# vulnerable libzstd1 1.5.7+dfsg-1. Install Debian's exact security build in
# distroless's own package layout (library files, status.d control record and
# md5sums), so the library itself is replaced, not only its metadata. Remove
# this stage once the upstream distroless base ships the fixed version.
FROM python:3.13.16-slim-trixie AS libzstd-fix
ARG LIBZSTD1_VERSION=1.5.7+dfsg-1+deb13u1
RUN set -eu; \
    apt-get update; \
    cd /tmp; \
    apt-get download "libzstd1=${LIBZSTD1_VERSION}"; \
    deb="$(ls libzstd1_*.deb)"; \
    test "$(dpkg-deb -f "$deb" Package)" = "libzstd1"; \
    test "$(dpkg-deb -f "$deb" Version)" = "$LIBZSTD1_VERSION"; \
    test "$(dpkg-deb -f "$deb" Architecture)" = "$(dpkg --print-architecture)"; \
    mkdir -p /opt/libzstd/root/var/lib/dpkg/status.d /opt/libzstd/control; \
    dpkg-deb -x "$deb" /opt/libzstd/root; \
    dpkg-deb -e "$deb" /opt/libzstd/control; \
    dpkg-deb -f "$deb" > /opt/libzstd/root/var/lib/dpkg/status.d/libzstd1; \
    cp /opt/libzstd/control/md5sums /opt/libzstd/root/var/lib/dpkg/status.d/libzstd1.md5sums; \
    (cd /opt/libzstd/root && md5sum --quiet -c var/lib/dpkg/status.d/libzstd1.md5sums); \
    rm -rf /var/lib/apt/lists/* "/tmp/$deb"

FROM gcr.io/distroless/base-debian13:nonroot

# Fixed libzstd1 (CVE-2026-124851, #1743) over the base image's vulnerable copy.
COPY --from=libzstd-fix /opt/libzstd/root/ /

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/site-packages \
    LD_LIBRARY_PATH=/usr/local/lib

WORKDIR /app
COPY --from=builder --chown=nonroot:nonroot /usr/local /usr/local
# Preserve existing operational scripts that invoke Debian's old interpreter path.
# Same patched interpreter binary, no second Python package manager/runtime.
COPY --from=builder --chown=nonroot:nonroot /usr/local/bin/python3.13 /usr/bin/python3
COPY --from=builder --chown=nonroot:nonroot /usr/local/bin/python3.13 /usr/bin/python3.13
COPY --from=builder --chown=nonroot:nonroot /opt/runtime-libs /usr/local/lib
COPY --from=builder --chown=nonroot:nonroot /opt/app /app
COPY --from=builder --chown=nonroot:nonroot /opt/runtime-data /var/lib/nexolab

USER nonroot
EXPOSE 8081
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD ["/usr/local/bin/python3", "-c", "import json,urllib.request; json.load(urllib.request.urlopen('http://127.0.0.1:8081/health', timeout=2))"]

CMD ["/usr/local/bin/python3", "/app/adaptive_main.py"]
