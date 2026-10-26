# LazyLibrarian's front end

The single page front end, in the style of Sonarr and Radarr and built the same way: React,
TypeScript, TanStack Query, zustand, react-router and CSS modules, built by Vite. Its theme and
layout styles come from [Sonarr](https://github.com/Sonarr/Sonarr) (GPL-3.0).

It is replacing the old pages a few at a time. FastAPI serves its pages (`UI_PAGES` in
`lazylibrarian/webapp.py`) and the old pages serve everything else. It talks to LazyLibrarian
through `/api/v1`.

## Building

Node.js 24 or newer:

```
cd frontend
npm ci
npm run build
```

That type checks and builds into `data/ui`, which is committed so that installing from git
needs no Node.js. Commit `data/ui` with the source change that made it; CI fails when they don't
match. `npm start` rebuilds on every change while you work on it.
