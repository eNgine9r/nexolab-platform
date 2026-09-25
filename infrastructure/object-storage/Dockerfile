FROM --platform=$BUILDPLATFORM alpine:3.22.1@sha256:4bcff63911fcb4448bd4fdacec207030997caf25e9bea4045fa6c8c44de311d1 AS fetch
ARG TARGETARCH
ARG BUILDARCH
ARG VERSITYGW_VERSION=1.8.0
ARG VERSITYGW_SHA256_AMD64=2ba2c734d10d2c4e651d03182cb4b246656bc735a2f282db7b0b73fba6073467
ARG VERSITYGW_SHA256_ARM64=b34051d33f5a9c457f790896acb7bd7d7e15ad8d92efb70616b924f37e401910
RUN set -eux; \
    case "$TARGETARCH" in \
      amd64) archive_arch="x86_64"; expected="$VERSITYGW_SHA256_AMD64" ;; \
      arm64) archive_arch="arm64"; expected="$VERSITYGW_SHA256_ARM64" ;; \
      *) echo "Unsupported VersityGW target architecture: $TARGETARCH" >&2; exit 64 ;; \
    esac; \
    archive="versitygw_v${VERSITYGW_VERSION}_Linux_${archive_arch}.tar.gz"; \
    url="https://github.com/versity/versitygw/releases/download/v${VERSITYGW_VERSION}/${archive}"; \
    wget -O /tmp/versitygw.tar.gz "$url"; \
    printf '%s  %s\n' "$expected" /tmp/versitygw.tar.gz | sha256sum -c -; \
    mkdir -p /tmp/extract /out; \
    tar -xzf /tmp/versitygw.tar.gz -C /tmp/extract; \
    binary="$(find /tmp/extract -type f -name versitygw -print -quit)"; \
    test -n "$binary"; \
    install -m 0755 "$binary" /out/versitygw; \
    if [ "$TARGETARCH" = "$BUILDARCH" ]; then /out/versitygw --version | grep -F "${VERSITYGW_VERSION}"; fi

FROM scratch
COPY --from=fetch /out/versitygw /usr/local/bin/versitygw
EXPOSE 9000
ENTRYPOINT ["/usr/local/bin/versitygw"]
CMD ["posix", "/data"]
