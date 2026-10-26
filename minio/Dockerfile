# MinIO-сервер + клиент mc, собранные из официальных исходников.
#
# MinIO перестал публиковать образы minio/minio и minio/mc на Docker Hub ("pull access denied"),
# поэтому собираем сами. Один образ с обоими бинарниками: им пользуются и `minio`, и одноразовый
# `minio-init` (mc), а `docker compose exec minio mc ...` доступен для обслуживания.
#
# Обновление: поменять MINIO_RELEASE / MC_RELEASE ниже (теги RELEASE.* из
# https://github.com/minio/minio/tags и https://github.com/minio/mc/tags) и тег `image:` у minio
# в docker-compose.yml / docker-compose.prod.yml — новый тег заставит compose пересобрать образ.
# Go-версию сверять с go.mod (директивы `go` / `toolchain`) выбранного релиза.

ARG MINIO_RELEASE=RELEASE.2025-10-15T17-29-55Z
ARG MC_RELEASE=RELEASE.2025-08-13T08-35-41Z
ARG GO_IMAGE=golang:1.24.13-alpine3.23
ARG RUNTIME_IMAGE=alpine:3.24

FROM ${GO_IMAGE} AS gobase
RUN apk add --no-cache git
# GOTOOLCHAIN=local — не скачивать другой Go молча: если go.mod потребует новее, сборка упадёт
ENV CGO_ENABLED=0 GOTOOLCHAIN=local
WORKDIR /src

FROM gobase AS minio-build
ARG MINIO_RELEASE
RUN git clone --depth 1 --branch "${MINIO_RELEASE}" https://github.com/minio/minio.git . \
 && git log -1 --format='minio %H %cI'
# Как в официальном релизном сборщике: время релиза из тега, префикс RELEASE
# (gen-ldflags читает префикс из env MINIO_RELEASE — переопределяем его только для этой команды)
RUN set -eu; \
    ts="$(echo "${MINIO_RELEASE#RELEASE.}" | sed -E 's/T([0-9]{2})-([0-9]{2})-([0-9]{2})Z$/T\1:\2:\3Z/')"; \
    ldflags="$(MINIO_RELEASE=RELEASE go run buildscripts/gen-ldflags.go "$ts")"; \
    go build -tags kqueue -trimpath -ldflags "$ldflags" -o /out/minio . ; \
    /out/minio --version

FROM gobase AS mc-build
ARG MC_RELEASE
RUN git clone --depth 1 --branch "${MC_RELEASE}" https://github.com/minio/mc.git . \
 && git log -1 --format='mc %H %cI'
RUN set -eu; \
    ts="$(echo "${MC_RELEASE#RELEASE.}" | sed -E 's/T([0-9]{2})-([0-9]{2})-([0-9]{2})Z$/T\1:\2:\3Z/')"; \
    ldflags="$(MC_RELEASE=RELEASE go run buildscripts/gen-ldflags.go "$ts")"; \
    go build -tags kqueue -trimpath -ldflags "$ldflags" -o /out/mc . ; \
    /out/mc --version

FROM ${RUNTIME_IMAGE}
ARG MINIO_RELEASE
ARG MC_RELEASE
LABEL org.opencontainers.image.title="profichat/minio" \
      org.opencontainers.image.description="MinIO ${MINIO_RELEASE} + mc ${MC_RELEASE}, built from source" \
      org.opencontainers.image.version="${MINIO_RELEASE}" \
      org.opencontainers.image.source="https://github.com/minio/minio" \
      org.opencontainers.image.licenses="AGPL-3.0-only"

# sh/until/sleep (entrypoint'ы в compose) есть в busybox alpine; ca-certificates — для TLS наружу
RUN apk add --no-cache ca-certificates \
 && addgroup -S -g 10001 minio \
 && adduser -S -D -u 10001 -G minio -h /home/minio minio \
 && mkdir -p /data \
 && chown minio:minio /data

COPY --from=minio-build /out/minio /usr/bin/minio
COPY --from=mc-build /out/mc /usr/bin/mc

# /data принадлежит minio: свежий именованный том наследует владельца при первом монтировании.
# Конфиг mc — во временный каталог (HOME у minio тоже доступен на запись).
ENV MC_CONFIG_DIR=/tmp/.mc
USER minio
WORKDIR /home/minio

EXPOSE 9000 9001
ENTRYPOINT ["minio"]
CMD ["server", "/data", "--console-address", ":9001"]
