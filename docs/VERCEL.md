# Import ContextLens from GitHub into Vercel Hobby

This configuration hosts the four-view address dossier with bundled evidence.
It uses the same Python resolver and claim code as the local app. Each hosted
investigation returns its complete result in one request. It does not depend on
cross-request memory, SQLite, external databases, model keys, or library API keys.

The legacy research-tools interface and optional model interpreter remain local
features. Historical images, modern map tiles, and original source links still
need internet access.

## 1. Prepare the Git version

Put the demo source files in a GitHub repository you control. Confirm that the
selected branch contains vercel.json and api/service.py.

## 2. Import the repository

1. Sign into https://vercel.com using the GitHub account that owns your deployment repository.
2. Select your personal Hobby account.
3. Choose **Add New → Project**.
4. In **Import Git Repository**, select **your deployment repository**.
5. If it is absent, use the GitHub integration's repository-access settings to
   grant Vercel access to this repository.
6. Keep **Root Directory** at the repository root. Do not select frontend/.
7. Choose **Other** as the framework preset. The repository intentionally uses a
   standard Python function alongside a Vite-built static interface.

## 3. Confirm build settings

| Setting | Value |
|---|---|
| Framework preset | Other |
| Root directory | Repository root |
| Node.js version | 24.x |
| Python | 3.12, supplied by .python-version |
| Install command | npm ci |
| Build command | npm run check && npm run build && python3 scripts/prepare_vercel.py |
| Output directory | dist |
| Environment variables | None required |
| Database or paid add-on | None required |

vercel.json supplies the build, static routing, and Python-function settings.
Keep the checked-in package-lock.json. Do not add SHLIB_API_KEY or DEEPSEEK_API_KEY
for this hosted snapshot demo; the adapter deliberately never uses them.

Choose **Deploy**. Wait until the deployment reports **Ready** and save the actual
generated .vercel.app URL. A repository import is configuration, not proof of a
working deployment.

## 4. Verify the deployed app

1. Open the generated URL in a fresh browser session.
2. Open /api/health on the same domain. Expect ok=true, official_records=154,
   seed_records=0, and investigation_mode="synchronous".
3. Run 436 Avenue Joffre with era 1934. Inspect Identity, Events, Atlas, and Sources.
4. Run Nanjing Road department store. Confirm that multiple candidate roads are shown.
5. Run 9999 Mars Road. Confirm the unresolved state.
6. Download the evidence JSON and open at least one original source URI.
7. Repeat the address investigation after a page reload. It must not rely on a job
   from a previous function instance.
8. If the demo needs public access, check the production URL in a signed-out
   browser and configure Deployment Protection to match the intended audience.

For an automated check of both languages, all four views, and JSON downloads:

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m playwright install chromium
python3 scripts/check_browser.py --base-url https://YOUR-PROJECT.vercel.app
```

Add the verified production URL to README.md after checking the site. Do not substitute a guessed project URL.

## 5. Reproduce the hosted mode locally

Use Python 3.12 and Node.js 24:

```bash
npm ci
npm run check
npm run build
python3 scripts/prepare_vercel.py
python3 scripts/preview_vercel.py
```

Open http://127.0.0.1:8766. The API is the same stateless handler used by Vercel.
The original local app remains available through python3 start.py on port 8765.

## Why a direct import of the old server was insufficient

The original server uses a continuously running ThreadingHTTPServer, an in-memory
InvestigationStore, and writable local indexes. Those assumptions do not provide
durable jobs across separate serverless invocations. api/service.py exposes the
core operations as a Vercel-supported handler. app/vercel_api.py finishes the
investigation synchronously and validates candidate IDs against a fresh resolution.
Mutable cache/index paths are separated from the read-only packaged snapshot.

## Troubleshooting

| Symptom | Check |
|---|---|
| Import deploys the old app | Confirm the deployed commit contains vercel.json and api/service.py. |
| Python framework detected unexpectedly | Select Other; install requirements.txt, not requirements-optional.txt. |
| Page loads but API returns HTTP 500 / FUNCTION_INVOCATION_FAILED | Deploy the current handler, which uses process_api_request rather than Vercel's reserved handle_request method. Check runtime logs if the error persists. |
| Page loads but API is 404 | Confirm the project root and vercel.json rewrites. |
| Investigation polling fails | Rebuild frontend/src/main.ts; the hosted adapter returns the result in the POST response. |
| Map or archival scan does not load | These assets come from external providers; evidence and source metadata remain inspectable. |
| Visitor sees a sign-in screen | Check Deployment Protection for the exact production URL. |
| Free usage is exhausted | Check Hobby usage; local deployment remains available. |

## Hosting scope and official documentation

Hobby is for personal, non-commercial use and has usage limits. This lightweight
research demo is designed for that setting; eligibility for institutional or
commercial operation should be checked against Vercel's current terms.

- [Import from Git](https://vercel.com/docs/git)
- [Python functions and supported handlers](https://vercel.com/docs/functions/runtimes/python/api-directory)
- [Python version and runtime](https://vercel.com/docs/functions/runtimes/python)
- [Hobby usage and eligibility](https://vercel.com/docs/plans/hobby)
- [Function limits](https://vercel.com/docs/functions/limitations)

Configuration prepared against the documentation available on 2026-09-12.
