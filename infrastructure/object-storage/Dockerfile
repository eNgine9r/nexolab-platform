FROM --platform=$BUILDPLATFORM alpine:3.22.1@sha256:4bcff63911fcb4448bd4fdacec207030997caf25e9bea4045fa6c8c44de311d1 AS build
ARG TARGETARCH
ARG BUILDARCH
ARG VERSITYGW_VERSION=1.8.0
ARG VERSITYGW_COMMIT=fd04bc1df2656298577b82667a4195c77f8c7563
ARG GO_VERSION=1.27.3
ARG GO_SHA256_AMD64=65efbc80fdc1fa2cd2631cad5b481777a68e8725f34e89f50fc6ac714e379b40
ARG GO_SHA256_ARM64=a06e99309dbcbdca1a8ccd2282c3ee146e55930886e26b4f1193269587165f49
ENV PATH="/usr/local/go/bin:$PATH" GOTOOLCHAIN=local CGO_ENABLED=0 GOMAXPROCS=2 GOFLAGS="-p=2"
RUN set -eux; \
    case "$TARGETARCH" in amd64|arm64) ;; *) exit 64 ;; esac; \
    case "$BUILDARCH" in \
      amd64) expected="$GO_SHA256_AMD64" ;; \
      arm64) expected="$GO_SHA256_ARM64" ;; \
      *) echo "Unsupported build architecture: $BUILDARCH" >&2; exit 64 ;; \
    esac; \
    apk add --no-cache ca-certificates git; \
    wget -q -O /tmp/go.tar.gz "https://dl.google.com/go/go${GO_VERSION}.linux-${BUILDARCH}.tar.gz"; \
    printf '%s  %s\n' "$expected" /tmp/go.tar.gz | sha256sum -c -; \
    tar -xzf /tmp/go.tar.gz -C /usr/local; \
    rm /tmp/go.tar.gz; \
    go version | grep -F "go${GO_VERSION} "; \
    mkdir /src; cd /src; git init; \
    git remote add origin https://github.com/versity/versitygw.git; \
    git fetch --depth=1 origin "$VERSITYGW_COMMIT"; \
    git checkout --detach FETCH_HEAD; \
    test "$(git rev-parse HEAD)" = "$VERSITYGW_COMMIT"
WORKDIR /src
# Rebuild the same release with fixed Go HTTP/TLS and x/net. No SDK, Git,
# module downloader or network dependency enters the finished local runtime.
RUN set -eux; \
    go get golang.org/x/net@v0.60.0; \
    go mod download; \
    go mod verify; \
    mkdir /out; \
    GOOS=linux GOARCH="$TARGETARCH" go build -trimpath -buildvcs=false \
      -ldflags="-s -w -X=main.Version=${VERSITYGW_VERSION} -X=main.Build=${VERSITYGW_COMMIT}" \
      -o /out/versitygw ./cmd/versitygw; \
    go version -m /out/versitygw | grep -F "go${GO_VERSION}"; \
    go version -m /out/versitygw | grep -E 'golang.org/x/net[[:space:]]+v0\.60\.0[[:space:]]'; \
    go version -m /out/versitygw | grep -F "GOARCH=${TARGETARCH}"; \
    if [ "$TARGETARCH" = "$BUILDARCH" ]; then /out/versitygw --version | grep -F "${VERSITYGW_VERSION}"; fi; \
    case "$TARGETARCH" in amd64) other_arch=arm64 ;; arm64) other_arch=amd64 ;; esac; \
    GOOS=linux GOARCH="$other_arch" go build -trimpath -buildvcs=false \
      -ldflags="-s -w -X=main.Version=${VERSITYGW_VERSION} -X=main.Build=${VERSITYGW_COMMIT}" \
      -o /tmp/versitygw-cross ./cmd/versitygw; \
    go version -m /tmp/versitygw-cross | grep -F "GOARCH=${other_arch}"; \
    rm /tmp/versitygw-cross

FROM scratch
COPY --from=build /out/versitygw /usr/local/bin/versitygw
EXPOSE 9000
ENTRYPOINT ["/usr/local/bin/versitygw"]
CMD ["posix", "/data"]
