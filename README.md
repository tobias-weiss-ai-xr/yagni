# yagni

**You Aren't Gonna Need It.** The SaaS with zero features, live at
[yagni.graphwiz.ai](https://yagni.graphwiz.ai/).

One HTML file. No JS, no backend, no build, no tracking. 100% FOSS (MIT).

## Deploy

Primary: upload the repo root to any static host.

Fallback (GitHub Pages):

```sh
git push origin main:gh-pages
```

…then enable Pages on the `gh-pages` branch. Same files, no build step.

## Test

```sh
./test.sh
```

Checks the contract: headline present, zero scripts/external fetches, license exists.
