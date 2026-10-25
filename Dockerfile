# syntax=docker/dockerfile:1
#
# LazyLibrarian, laid out like the linuxserver.io and hotio images of Sonarr and Radarr:
# settings, database, cache and logs in /config, owned by the PUID and PGID you choose.
# See docker-compose.yml for an example.

FROM python:3.13-slim

# ghostscript makes magazine covers from pdfs, libmagic1 identifies downloaded files,
# tini passes signals on and reaps stray child processes
RUN apt-get update \
    && apt-get install -y --no-install-recommends ghostscript libmagic1 tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --root-user-action=ignore --disable-pip-version-check -r requirements.txt

COPY . .

# A "Package" install doesn't update itself, the image is updated instead. The commit shows as
# the version in the web interface.
ARG LL_COMMIT=unknown
RUN printf 'LAZYLIBRARIAN_VERSION = "Package"\nLAZYLIBRARIAN_HASH = "%s"\n' "$LL_COMMIT" > lazylibrarian/version.py \
    && python -m compileall -q LazyLibrarian.py lazylibrarian lib \
    && useradd --system --no-create-home --home-dir /config --shell /usr/sbin/nologin lazylibrarian \
    && mkdir /config

# LAZYLIBRARIAN_SUPERVISED: a restart from the web interface exits, and Docker starts it again
ENV PUID=1000 \
    PGID=1000 \
    UMASK=022 \
    LAZYLIBRARIAN_SUPERVISED=1 \
    PYTHONUNBUFFERED=1

VOLUME /config
EXPOSE 5299

HEALTHCHECK --interval=1m --timeout=10s --start-period=2m \
    CMD ["python", "/app/docker/healthcheck.py"]

ENTRYPOINT ["/usr/bin/tini", "--", "sh", "/app/docker/entrypoint.sh"]
CMD ["python", "/app/LazyLibrarian.py", "--datadir", "/config", "--config", "/config/config.ini", "--nolaunch"]
