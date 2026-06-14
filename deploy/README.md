# Sinlex deploy files

This directory stores deployment configuration snapshots for the current server.
They are versioned as templates/source files and are not applied automatically by this repository yet.

- `nginx/sinlex.tech` - public landing, `/app/` Streamlit proxy, `/api/` FastAPI proxy.
- `systemd/sinlex-server.service` - FastAPI service.
- `systemd/sinlex-streamlit.service` - Streamlit UI service.
- `sync_landing.sh` - syncs repository `landing/` into live `/var/www/landing/` and validates nginx.
- `deploy_server.sh` - fetches `origin/main`, resets the working tree, syncs landing, validates nginx, and restarts Sinlex services.

The live server still uses:

- `/etc/nginx/sites-available/sinlex.tech`
- `/etc/systemd/system/sinlex-server.service`
- `/etc/systemd/system/sinlex-streamlit.service`

Auto-deploy should be added in a separate step after the initial GitHub upload is verified.
