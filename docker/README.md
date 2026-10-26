# LazyLibrarian

LazyLibrarian finds and downloads ebooks, audiobooks, magazines and comics for the authors
and series you follow, sends them to your download client, and files the results in your
library, like Sonarr and Radarr do for TV and films.

Source, issues and documentation: [github.com/EccentricWkshp/LazyLibrarian](https://github.com/EccentricWkshp/LazyLibrarian)

## Quick start

`docker-compose.yml`:

```yaml
services:
  lazylibrarian:
    image: eccentricwkshp/lazylibrarian:latest
    container_name: lazylibrarian
    environment:
      - PUID=1000
      - PGID=1000
      - UMASK=022
      - TZ=Etc/UTC
      # optional, see Calibre and ffmpeg below
      # - DOCKER_MODS=linuxserver/mods:universal-calibre|linuxserver/mods:lazylibrarian-ffmpeg
    volumes:
      - ./config:/config
      - /path/to/books:/books
      - /path/to/downloads:/downloads
    ports:
      - 5299:5299
    restart: unless-stopped
```

Then `docker compose up -d`, and open `http://<your server>:5299` to choose a username and
password. The first-run setup only works from your local network, so nobody else can claim
a new install that's reachable from the internet.

Or with `docker run`:

```sh
docker run -d --name lazylibrarian \
  -e PUID=1000 -e PGID=1000 -e TZ=Etc/UTC \
  -v ./config:/config -v /path/to/books:/books -v /path/to/downloads:/downloads \
  -p 5299:5299 --restart unless-stopped \
  eccentricwkshp/lazylibrarian:latest
```

## Settings

| Setting | What it does |
| --- | --- |
| `-p 5299:5299` | The web interface |
| `-e PUID=1000`, `-e PGID=1000` | The user and group LazyLibrarian runs as, so the files it writes belong to you. Run `id` on the host to see yours |
| `-e UMASK=022` | Permissions of new files. `002` keeps them writable for the group |
| `-e TZ=Etc/UTC` | Your [time zone](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones), for schedules and log times |
| `-e DOCKER_MODS=...` | Optional [linuxserver.io mods](https://mods.linuxserver.io/) to add at startup, separated by `\|`. See Calibre and ffmpeg below |
| `-v /config` | Settings, database, cache and logs |
| `-v /books`, `-v /downloads` | Your library and your download client's completed downloads. Use the same path for downloads as your download client does, so LazyLibrarian finds them |

**Restart** and **Shutdown** in the web interface both start LazyLibrarian again inside the
container. To stop it, stop the container, for example with `docker compose stop`.

## Calibre and ffmpeg

The image is built on the linuxserver.io Ubuntu base image, so their mods work just as they do
with their LazyLibrarian image. Add the ones you need to `DOCKER_MODS`, separated by `|`:

| Mod | Adds | Then in LazyLibrarian |
| --- | --- | --- |
| `linuxserver/mods:universal-calibre` | Calibre, to convert ebooks and add them to a Calibre library (amd64 and arm64) | Settings > Processing: calibredb `/usr/bin/calibredb`, ebook-convert `/usr/bin/ebook-convert` |
| `linuxserver/mods:lazylibrarian-ffmpeg` | ffmpeg, to merge and tag audiobooks | Settings > Processing: ffmpeg `ffmpeg` |

Mods install each time the container is created, which adds a minute or two to that start.

## Moving from the linuxserver.io image

`/config` is laid out the same way, so you can point this image at your existing `/config`
folder and keep your other settings, mods included. Take a copy of that folder first: the
database is upgraded on the first start and can't be used with the old image afterwards.
Only one account is kept, as owner: the admin who logged in most recently, or the web server
login from your settings.

## Updating

LazyLibrarian doesn't update itself inside the container, pull the new image instead:

```sh
docker compose pull && docker compose up -d
```

## Tags

| Tag | |
| --- | --- |
| `latest` | The current master branch |
| `2026.10.25` (for example) | A release |
| `sha-1234567` | A single commit |

Images are built for `linux/amd64` and `linux/arm64`.

## The same image on GitHub

Every tag is also published as `ghcr.io/eccentricwkshp/lazylibrarian`. Docker Hub limits how
often you can pull without logging in, so use that one if you hit the limit, for example with
several containers updating automatically.

## Notes

- The container's health check asks `/ping` at the port in your settings, which answers without a login.
- Ghostscript, for magazine covers, and unrar, for comics in rar archives, are included.
