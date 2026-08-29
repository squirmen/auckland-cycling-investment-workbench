# Container reproduction record

> Evidence status (2026-08-29): a build from an isolated archive of staged tree
> `7fbe94a1fa52cbc8acdf37cb0a1383a03c08b853` and its offline runtime checks
> passed on Linux arm64. The build includes the locked frontend, 15 frontend
> unit tests, the staged Python package, and a checksum-pinned R5 engine.
> Independent CI/amd64 reproduction and redistributed GPL corresponding-source
> obligations remain release gates.

## Validation build

- Date: 2026-08-29 (Pacific/Auckland).
- Host architecture: Apple Silicon `arm64`; Colima reported Linux `aarch64`, 4 CPUs,
  an 8 GiB memory limit, a 40 GiB disk limit, Docker runtime, and virtiofs mounts.
- Command run from the repository root:

  ```sh
  docker build --tag ciw:staged-clean .
  ```

- Result: the isolated staged-tree image completed successfully using a partly
  warm local layer cache. Exact elapsed and cold-build times were not captured.
- Local image ID:
  `sha256:e0c162a146e32e7517a8c015667d76b3f2ff1038aec8835b1d4af3c25316f5dd`.
- Local image size: 566,049,220 bytes (539.83 MiB), reported by
  `docker image inspect`.
- This image ID is architecture-specific local evidence, not a published
  multi-platform registry digest.

## Immutable inputs

| Input | Pin |
|---|---|
| Python | `python:3.11.16-slim-bookworm@sha256:2e32f7d302adc1c37428355c1e646897c0c53f4fd60b6a551245fb90ee129f91` |
| Node.js | `node:24.19.0-bookworm-slim@sha256:3638d9a6fe4030bd716be989438248074489337ba3275657f93595428be4fc03` |
| Java | `eclipse-temurin:21-jre-jammy@sha256:d63bd8d9b171999cbed8576f2c76e874dd4856791a358536e5c4d407e77edc13` |
| uv | `ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1` |
| R5 engine | `r5-v7.5.1-r5py-all.jar`, SHA-256 `d50be106cadd7b636cfc0e209052767d7df570629f79fdf98ecd5cf5d2d89be7` |
| Debian packages | Snapshot `20260803T000000Z`; `gdal-bin=3.6.2+dfsg-1+b2`; `osmium-tool=1.15.0-1` |

Lock and build-file hashes used by the validation image:

| File | SHA-256 |
|---|---|
| `uv.lock` | `bcdb36f244c9ac2a48d05ef9319daa94f7d3535a483593d1f96cfbb1c64ca109` |
| `web/package-lock.json` | `4a9748eea6f23cdc07bdfd2ef40a2ae27a9036cb6f10f1ca697b434e6c0dabc8` |
| `Dockerfile` | `b7b0f7b4c327efc097518c1d96f48ae2893b7cb6fe55b6ef3889cf68b2501100` |
| `configs/r5py.yml` | `cf510309c36fcd7e23fe7efd59a43630960bbf247e259db727d72f61b8f9ba86` |
| `third_party/r5/LICENSE` | `50ceabea3b9979201c7e4e888ccce89e03a788fa9d6a546cf106c49d0f896bba` |
| `third_party/r5py/LICENSE-MIT` | `303afa022b401801dee726af477fdca2a589c7678998fbc1de538922a5e07d2e` |

The Python environment is installed with `uv sync --locked`; the frontend is
installed with `npm ci`. The Docker build ran frontend linting, type checking,
all 15 unit tests, and the production build before assembling the image.
The isolated host and installed container package both reported implementation
digest `d2730c1e232b2c1c6b26c47f0bf260ec64657eb1f5b394c0f975225a384e54d3`.

## Runtime checks

The following checks ran successfully against `ciw:staged-clean` with
container networking disabled:

| Check | Observed result |
|---|---|
| `python --version` | Python 3.11.16 |
| `java -version` | Eclipse Temurin OpenJDK 21.0.11 LTS |
| `gdalinfo --version` | GDAL 3.6.2 |
| `osmium --version` | osmium-tool 1.15.0; libosmium 2.18.0 |
| `node --version` | Node.js v24.19.0 |
| `npm --version` | npm 11.17.0 |
| `r5py.__version__` | r5py 1.1.7 |
| Embedded R5 engine | JVM 21.0.11 started through r5py; `com.conveyal.r5.SoftwareVersion` reported `v7.5.1-r5py`, commit `2255a29e9a196dd5079853bfdbb6ba1dacdb56b3`; JAR SHA-256 `d50be106cadd7b636cfc0e209052767d7df570629f79fdf98ecd5cf5d2d89be7` |
| Routing licence files | Pinned R5 and r5py MIT texts present below `/opt/licenses` |
| `ciw validate --config configs/auckland.yml --config-only` | `Validation: OK` |
| Staged/container implementation digest | Identical SHA-256 content digest `d2730c1e232b2c1c6b26c47f0bf260ec64657eb1f5b394c0f975225a384e54d3` |
| `npm run build` in `/opt/ciw-web` | production client rebuilt successfully; 246.27 kB JavaScript bundle (69.93 kB gzip) |

The first final-stage runtime check found that the complete-toolchain image did
not preserve the methodology source used by the frontend bundler. The
Dockerfile now copies that source into `/opt/documentation`; the image above is
the post-fix rebuild, and its independent in-image frontend rebuild passed.
The same audit found that the pinned r5py package would otherwise download its
R5 JAR at first import. The final image instead embeds and checksum-verifies R5
7.5.1 during the build and directs r5py to that fixed local path. Both runtime
checks above were repeated with container networking disabled.

## Toolchain targets and bounds

The default `complete-toolchain` image includes the locked frontend source,
Node.js, npm, installed frontend packages, built static client, Python analysis
environment, Java, GDAL, and osmium. The `analysis-runtime` target omits Node.js,
npm, frontend source, and frontend development packages while retaining the
built static client:

```sh
docker build --target analysis-runtime \
  -t auckland-cycling-investment-workbench:runtime .
```

Chromium is intentionally not embedded in either image. Browser installation
and Playwright accessibility/end-to-end tests run in the locked GitHub Actions
job; this avoids shipping a browser in the analysis runtime.

No process-level peak-memory telemetry was captured, so no peak is claimed.
The build ran inside a Colima VM hard-limited to 8 GiB, establishing an 8 GiB
upper bound for the whole VM during this run, not a measured build peak. This is
below the 20 GB acceptance ceiling.

Only the Linux arm64 image was built and exercised locally. The base-image pins
are multi-platform indexes and the Dockerfile is architecture-neutral, but an
independent Linux amd64 build and runtime check remain required before claiming
verified multi-architecture reproduction.
