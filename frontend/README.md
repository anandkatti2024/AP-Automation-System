# Templegate AP frontend

React and Vite provide the single-page interface for the Django AP workflow.
During development, Vite proxies `/api` requests to Django at
`http://127.0.0.1:8000`. Production assets use `/static/` and are served by
Django/WhiteNoise from the same origin.

See the repository [README](../README.md) for full local setup and test
instructions.

From this directory:

```powershell
npm ci
npm run dev
npm run lint
npm run build
```
