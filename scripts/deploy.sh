#!/usr/bin/env bash
set -euo pipefail
umask 077

cd "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
for binary in docker openssl curl awk flock python3 git; do
  command -v "$binary" >/dev/null || { printf 'Required command missing: %s\n' "$binary" >&2; exit 1; }
done
docker compose version >/dev/null
docker info >/dev/null
mkdir -p artifacts/production-backups
chmod 700 artifacts/production-backups
exec 9>artifacts/deploy.lock
flock -n 9 || { printf 'Another deployment is running.\n' >&2; exit 1; }

environment_file=.env.production
valid_domain() {
  # One DNS hostname, without a URL, port, whitespace or empty labels.
  [[ ${#1} -le 253 && "$1" == *.* ]] || return 1
  local label
  local -a labels
  IFS=. read -r -a labels <<< "$1"
  for label in "${labels[@]}"; do
    [[ ${#label} -le 63 && "$label" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]] || return 1
  done
  [[ "$1" != *. ]]
}
if [[ ! -e "$environment_file" ]]; then
  domain=${FLOWCREDIT_DOMAIN:-wiut-hackathon.dehqonhub.uz}
  valid_domain "$domain" || { printf 'Invalid production domain.\n' >&2; exit 1; }
  password=$(openssl rand -hex 32)
  encryption_key=$(openssl rand -hex 32)
  {
    printf 'DOMAIN=%s\n' "$domain"
    printf 'POSTGRES_PASSWORD=%s\n' "$password"
    printf 'AUTH_ENCRYPTION_KEY=%s\n' "$encryption_key"
    printf 'TRUSTED_PROXY_IP=172.30.84.1\nSESSION_TTL_HOURS=168\nAUTH_RATE_LIMIT_MAX=20\nML_TIMEOUT_MS=8000\n'
  } > "$environment_file"
  unset password encryption_key
  printf 'Created private .env.production with generated database credentials.\n'
fi
chmod 600 "$environment_file"
# Read values as data; never execute an environment file with source/eval.
env_value() {
  awk -v prefix="$1=" -v optional="${2:-false}" 'index($0,prefix)==1 {sub(/^[^=]*=/,""); sub(/\r$/,""); value=$0; count++} END {if(count>1 || (count==0 && optional!="true"))exit 1; print value}' "$environment_file"
}
domain=$(env_value DOMAIN)
valid_domain "$domain" || { printf 'Invalid DOMAIN in .env.production.\n' >&2; exit 1; }
database_password=$(env_value POSTGRES_PASSWORD)
[[ "$database_password" =~ ^[a-fA-F0-9]{64}$ ]] || { printf 'POSTGRES_PASSWORD must contain 64 hex characters. Preserve existing credentials; rotate the database password explicitly if needed.\n' >&2; exit 1; }
unset database_password
trusted_proxy=$(env_value TRUSTED_PROXY_IP)
[[ "$trusted_proxy" == 172.30.84.1 ]] || { printf 'TRUSTED_PROXY_IP must match the dedicated network gateway 172.30.84.1.\n' >&2; exit 1; }

encryption_key=$(env_value AUTH_ENCRYPTION_KEY true)
key_lines=$(awk 'index($0,"AUTH_ENCRYPTION_KEY=")==1 {count++} END {print count+0}' "$environment_file")
if [[ "$key_lines" == 0 ]]; then
  # Existing installations receive one stable key before MFA can be enabled.
  # Never overwrite an existing key; encrypted authenticator secrets depend on it.
  encryption_key=$(openssl rand -hex 32)
  printf '\nAUTH_ENCRYPTION_KEY=%s\n' "$encryption_key" >> "$environment_file"
  printf 'Initialized the private authentication encryption key. Preserve it with database backups.\n'
fi
[[ "$encryption_key" =~ ^[a-fA-F0-9]{64}$ ]] || { printf 'AUTH_ENCRYPTION_KEY must contain 64 hex characters. Preserve the existing encryption key.\n' >&2; exit 1; }
unset encryption_key key_lines

services=(db ml api web)
build_targets=(api web ml)

compose() {
  # The private file is authoritative, even if this shell has dev values exported.
  env -u DOMAIN -u POSTGRES_PASSWORD -u AUTH_ENCRYPTION_KEY -u TRUSTED_PROXY_IP -u SESSION_TTL_HOURS -u AUTH_RATE_LIMIT_MAX -u ML_TIMEOUT_MS -u ML_SERVICE_URL \
    docker compose --project-name flowcredit --env-file "$environment_file" -f docker-compose.production.yml "$@"
}
compose config --quiet
# Pin installed application image IDs before replacing mutable build tags.
# This is a manual application rollback aid; database rollback is never automatic.
rollback_stamp=$(date -u +%Y%m%dT%H%M%SZ)-$$
rollback_file="artifacts/production-backups/images-$rollback_stamp.txt"
skip_rollback_images=${FLOWCREDIT_SKIP_ROLLBACK_IMAGES:-0}
[[ "$skip_rollback_images" == 0 || "$skip_rollback_images" == 1 ]] || { printf 'Invalid rollback image override.\n' >&2; exit 1; }
if [[ "$skip_rollback_images" == 1 ]]; then
  printf 'Operator override: skipping old image preservation; database backup remains required.\n'
else
for service in api web ml; do
  current_container=$(compose ps --quiet "$service")
  if [[ -n "$current_container" ]]; then
    [[ "$current_container" =~ ^[a-f0-9]+$ ]] || exit 1
    current_image=$(docker inspect --format '{{.Image}}' "$current_container")
    [[ "$current_image" =~ ^sha256:[a-f0-9]{64}$ ]] || exit 1
    rollback_tag="flowcredit-$service:rollback-$rollback_stamp"
    if docker image inspect "$current_image" >/dev/null 2>&1; then
      docker image tag "$current_image" "$rollback_tag"
    else
      # Docker can retain a healthy container after its parent image was pruned.
      # Recover only the unprivileged ML filesystem; mounted audit data is not
      # included by docker commit. Never snapshot API/web runtime credentials.
      [[ "$service" == ml ]] || { printf 'Active %s image is unavailable; rollback cannot be preserved.\n' "$service" >&2; exit 1; }
      if ! docker inspect "$current_container" | python3 -c '
import json, re, sys
try:
    rows = json.load(sys.stdin)
    assert len(rows) == 1
    data = rows[0]
    assert data["Config"]["User"] == "10001:10001"
    assert data["State"]["Running"] is True
    assert data["HostConfig"]["Privileged"] is False
    allowed = {"PATH", "LANG", "GPG_KEY", "PYTHON_VERSION", "PYTHON_SHA256",
               "UV_COMPILE_BYTECODE", "UV_LINK_MODE", "PYTHONUNBUFFERED",
               "ML_MODEL_PATH", "ML_AUDIT_PATH", "OMP_NUM_THREADS",
               "OPENBLAS_NUM_THREADS", "PYTHONPATH", "FINAL_MODEL_BUNDLE"}
    values = data["Config"]["Env"]
    names = [value.split("=", 1)[0] for value in values]
    assert len(set(names)) == len(names) and set(names) <= allowed
    assert all("=" in value for value in values)
    environment = dict(value.split("=", 1) for value in values)
    assert environment.get("ML_AUDIT_PATH") == "/data/audit/requests.jsonl"
    assert environment.get("ML_MODEL_PATH", "/app/runtime/model.joblib") == "/app/runtime/model.joblib"
    assert environment.get("FINAL_MODEL_BUNDLE", "/app/ml-service/final_model/artifacts") == "/app/ml-service/final_model/artifacts"
    mounts = data["Mounts"]
    assert len(mounts) == 1 and mounts[0]["Type"] == "volume"
    assert mounts[0]["Name"] == "flowcredit_ml-audit"
    assert mounts[0]["Destination"] == "/data/audit"
except (AssertionError, KeyError, TypeError, ValueError):
    sys.exit(1)
'; then
        printf 'Active ML configuration is outside the safe rollback snapshot scope.\n' >&2
        exit 1
      fi
      recovered_image=$(docker commit --pause=false "$current_container" "$rollback_tag")
      [[ "$recovered_image" =~ ^sha256:[a-f0-9]{64}$ ]] || exit 1
      docker image inspect "$recovered_image" >/dev/null
      current_image=$recovered_image
      printf 'Recovered the active ML filesystem into a private rollback image.\n'
    fi
    printf '%s %s %s\n' "$service" "$rollback_tag" "$current_image" >> "$rollback_file"
  fi
done
fi
# Reject overlapping IPv4 subnets, except the correctly configured project network.
network_ids=$(docker network ls --quiet)
if [[ -n "$network_ids" ]]; then
  # IDs are generated hexadecimal Docker identifiers, not user shell input.
  # shellcheck disable=SC2086
  docker network inspect --format '{{.Name}} {{range .IPAM.Config}}{{.Subnet}}={{.Gateway}} {{end}}' $network_ids |
    awk '
      function address(value, octets) {split(value,octets,"."); return ((octets[1]*256+octets[2])*256+octets[3])*256+octets[4]}
      BEGIN {first=address("172.30.84.0"); last=first+255; collision=0}
      {for(i=2;i<=NF;i++) {
        split($i,config,"="); subnet=config[1]; gateway=config[2];
        if(index(subnet,":")>0 || index(subnet,"/")==0)continue;
        split(subnet,cidr,"/"); size=2^(32-cidr[2]); start=int(address(cidr[1])/size)*size; end=start+size-1;
        if(start<=last && end>=first && !($1=="flowcredit_default" && subnet=="172.30.84.0/24" && gateway=="172.30.84.1")) {
          printf "Docker network subnet collision: %s (%s, gateway %s)\n",$1,subnet,gateway > "/dev/stderr"; collision=1;
        }
      }}
      END {exit collision}'
fi

printf 'Building production API, web and local ML images.\n'
mkdir -p artifacts/deployment
chmod 755 artifacts/deployment
python3 scripts/operations/release.py
compose build --pull "${build_targets[@]}"
had_database=false
if docker volume inspect flowcredit_postgres-data >/dev/null 2>&1; then had_database=true; fi
if [[ "$had_database" == true ]]; then
  # Quiesce app writes before the consistent snapshot and startup migrations.
  compose stop --timeout 30 web api
fi
compose up -d --wait --wait-timeout 180 db
if [[ "$had_database" == true ]]; then
  backup="artifacts/production-backups/wiut-$(date -u +%Y%m%dT%H%M%SZ)-$$.dump"
  if ! compose exec -T db pg_dump -U wiut -d wiut --format=custom --no-owner --no-acl > "$backup.part"; then
    rm -f -- "$backup.part"
    printf 'Database backup failed. Application startup and migrations have not run.\n' >&2
    exit 1
  fi
  mv -- "$backup.part" "$backup"
  chmod 600 "$backup"
  printf 'Pre-migration database backup saved to %s\n' "$backup"
fi
compose up -d --wait --wait-timeout 300 "${services[@]}"
# Retire only the old scorer container. Its named audit volume and research
# source remain available; no persistent data or unrelated services are removed.
legacy_scorers=$(docker ps --all --quiet --filter label=com.docker.compose.project=flowcredit --filter label=com.docker.compose.service=teammate-ml)
if [[ -n "$legacy_scorers" ]]; then
  while IFS= read -r legacy_id; do
    [[ "$legacy_id" =~ ^[a-f0-9]+$ ]] || exit 1
    docker stop --time 30 "$legacy_id" >/dev/null
    docker rm "$legacy_id" >/dev/null
  done <<< "$legacy_scorers"
fi
python3 scripts/operations/release.py --serving
curl --fail --silent --show-error --connect-timeout 3 --max-time 15 \
  --header "Host: $domain" --header "Origin: https://$domain" \
  http://127.0.0.1:18080/api/health >/dev/null
rejected_origin=$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' --max-time 15 \
  --request POST --header "Host: $domain" --header 'Origin: https://example.invalid' \
  --header 'Content-Type: application/json' --data '{}' http://127.0.0.1:18080/api/auth/login)
[[ "$rejected_origin" == 403 ]] || { printf 'Production origin policy check failed.\n' >&2; exit 1; }
curl --fail --silent --show-error --max-time 15 --header "Host: $domain" \
  http://127.0.0.1:18080/release.json >/dev/null
printf 'Selected services are healthy on loopback. HTTPS host nginx must proxy %s to 127.0.0.1:18080.\n' "$domain"
