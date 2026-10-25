#!/bin/sh
# Run LazyLibrarian as the user and group in PUID and PGID, like the linuxserver.io images,
# so the files it writes in /config and your library folders belong to you
set -e

umask "$UMASK"
export HOME=/config

if [ "$(id -u)" = "0" ]; then
    groupmod --non-unique --gid "$PGID" lazylibrarian
    usermod --non-unique --uid "$PUID" --gid "$PGID" lazylibrarian
    # Only when it's wrong, as going through a large cache takes a while
    if [ "$(stat -c %u:%g /config)" != "$PUID:$PGID" ]; then
        echo "Changing the owner of /config to $PUID:$PGID"
        chown -R "$PUID:$PGID" /config
    fi
    exec setpriv --reuid="$PUID" --regid="$PGID" --init-groups "$@"
fi

# Started with --user, so run as that user and leave ownership alone
exec "$@"
