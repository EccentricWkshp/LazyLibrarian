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
| `-v /config` | Settings, database, cache and logs |
| `-v /books`, `-v /downloads` | Your library and your download client's completed downloads. Use the same path for downloads as your download client does, so LazyLibrarian finds them |

Use a restart policy such as `unless-stopped`. **Restart** in the web interface exits the
container and relies on Docker to start it again. **Shutdown** stops it until you start it.

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

- The container's health check asks `http://localhost:5299/ping`, which answers without a login.
- Ghostscript is included, for magazine covers. Calibre's `ebook-convert` and ffmpeg aren't.
