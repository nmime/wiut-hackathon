# Production deployment

The production stack uses Compose project `flowcredit` with PostgreSQL, NestJS, React/nginx and the local ML service. Only the web container publishes a port: `127.0.0.1:18080`. PostgreSQL and ML audit records live in durable named volumes, `flowcredit_postgres-data` and `flowcredit_ml-audit`. No database, API or ML port is exposed to the internet.

On the Ubuntu server, after cloning this repository, run:

```sh
bash scripts/deploy.sh
```

Install Docker Engine with the Compose plugin first. The script also requires `openssl`, `curl`, `awk` and `flock`, which are standard Ubuntu packages. Node and Python run inside the images. The ML image uses the repository's existing fixed training recipe; the deploy script does not run evaluation or rewrite committed reports.

The first run generates a 256-bit random database password in `.env.production`, sets its permissions to `600`, and uses `wiut-hackathon.dehqonhub.uz`. To choose another domain on the first run, use `FLOWCREDIT_DOMAIN=example.com bash scripts/deploy.sh`. Subsequent runs preserve `.env.production`; edit its unquoted `DOMAIN` value deliberately when changing the hostname. `.env.production.example` documents the format and contains a placeholder, not usable credentials. Changing the environment password does not rotate an existing PostgreSQL user's password: rotate it in the database and update the private environment file together.

The host's nginx must already have a separate HTTPS virtual host and a valid certificate for this domain. Configure its HTTPS location to proxy to `http://127.0.0.1:18080`, pass `Host $host`, and overwrite `X-Forwarded-For` with the verified client `$remote_addr`. Redirect public HTTP to HTTPS. Allow port 80 for the configured ACME challenge path and port 443 for the app. This script deliberately does not change nginx, certificates, DNS, firewall rules or other applications on the host.

If Cloudflare proxies the hostname, the host nginx must first trust only Cloudflare's published address ranges and use `real_ip_header CF-Connecting-IP`. The inner nginx then trusts only the dedicated Docker gateway, `172.30.84.1`, and overwrites the API's forwarded header. Never trust arbitrary client forwarding chains or expose the API directly while one-hop proxy trust is enabled. Secure, HttpOnly session cookies are always enabled in this production Compose file, and the API accepts only the exact `https://DOMAIN` application origin. TLS terminates at the host nginx.

The stack owns subnet `172.30.84.0/24` with gateway `172.30.84.1`. The script rejects overlaps with other Docker networks before building. The nginx template uses the official image's entrypoint and substitutes only `TRUSTED_PROXY_IP`, preserving nginx variables such as `$remote_addr` and `$http_host`.

The bundled model is the default endpoint, `http://ml:8000`. A qualified replacement can be configured with `ML_SERVICE_URL` in the private environment file when its service or reachable endpoint is available. The default four-service stack and bundled model remain available; changing the URL alone does not create a replacement service.

Updates build images first. When a database volume already exists, the script stops web/API writes, starts PostgreSQL alone, and creates a consistent custom-format dump under `artifacts/production-backups/` before starting the API's migrations. Backups have permissions `600`; the directory has permissions `700` and is ignored by Git. Startup archives legacy synthetic portfolios without deleting accounts, model results, decisions or audit events. A backup failure stops the update before application startup. Updates can cause a brief maintenance interruption.

The script never runs `down -v` or deletes a persistent volume. Keep a separately secured copy of the database dumps and `.env.production` off the server; local dumps alone do not protect against host loss. A failed update can leave the web/API stopped, so inspect the error and repair it before restarting them. Restore into a separate PostgreSQL instance first to verify a dump with `pg_restore`; applying a database rollback to the live system requires an explicit operator decision.

For status and safe diagnostics:

```sh
docker compose --project-name flowcredit --env-file .env.production -f docker-compose.production.yml ps
docker compose --project-name flowcredit --env-file .env.production -f docker-compose.production.yml logs --tail 100 api ml web
curl --fail -H 'Host: wiut-hackathon.dehqonhub.uz' http://127.0.0.1:18080/api/health
```

Keep the private environment file and backups out of tickets or command output. Use `docker compose config --quiet` for validation; the full rendered configuration contains database credentials. The current app has a bounded in-process authentication limiter and supports one API process per database. This packaging does not add email verification, password recovery, MFA, backup retention or a monitoring service. Forecast and payment-capacity limitations remain documented in the ML integration notes.
