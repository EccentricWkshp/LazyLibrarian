# syntax=docker/dockerfile:1
#
# LazyLibrarian on the linuxserver.io Ubuntu base image, laid out like their image: settings,
# database, cache and logs in /config, PUID, PGID and UMASK choose who owns the files, and
# DOCKER_MODS works, for example linuxserver/mods:universal-calibre for ebook conversion and
# linuxserver/mods:lazylibrarian-ffmpeg for audiobooks. See docker-compose.yml for an example.

FROM ghcr.io/linuxserver/unrar:latest AS unrar

FROM ghcr.io/linuxserver/baseimage-ubuntu:noble

# ghostscript makes magazine covers from pdfs, libmagic1 identifies downloaded files, libunrar
# (multiverse) reads comic archives in rar format, RAR5 ones too, which the unrar command's
# listing doesn't always give dates for
RUN apt-get update \
    && apt-get install -y --no-install-recommends ghostscript libmagic1 libunrar5t64 python3-venv \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

WORKDIR /app/lazylibrarian

# the base image puts /lsiopy/bin first on the PATH, so python3 is this virtualenv
COPY requirements.txt .
RUN python3 -m venv /lsiopy \
    && pip install --no-cache-dir --disable-pip-version-check -r requirements.txt

COPY . .

# A "Package" install doesn't update itself, the image is updated instead. The commit shows as
# the version in the web interface.
ARG LL_COMMIT=unknown
RUN printf 'LAZYLIBRARIAN_VERSION = "Package"\nLAZYLIBRARIAN_HASH = "%s"\n' "$LL_COMMIT" > lazylibrarian/version.py \
    && python3 -m compileall -q LazyLibrarian.py lazylibrarian lib \
    && cp -r docker/root/. / \
    && chmod +x /etc/s6-overlay/s6-rc.d/*/run

# comic archives in rar format
COPY --from=unrar /usr/bin/unrar-ubuntu /usr/bin/unrar

# a restart from the web interface exits, and s6 starts LazyLibrarian again
ENV LAZYLIBRARIAN_SUPERVISED=1 \
    PYTHONUNBUFFERED=1

VOLUME /config
EXPOSE 5299

HEALTHCHECK --interval=1m --timeout=10s --start-period=2m \
    CMD ["python3", "/app/lazylibrarian/docker/healthcheck.py"]
