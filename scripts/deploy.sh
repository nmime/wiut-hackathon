#!/usr/bin/env bash
set -euo pipefail
umask 077

cd "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
for binary in docker openssl curl awk flock; do
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
  {
    printf 'DOMAIN=%s\n' "$domain"
    printf 'POSTGRES_PASSWORD=%s\n' "$password"
    printf 'TRUSTED_PROXY_IP=172.30.84.1\nSESSION_TTL_HOURS=168\nAUTH_RATE_LIMIT_MAX=20\nML_TIMEOUT_MS=8000\n'
  } > "$environment_file"
  unset password
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

model_endpoint=$(env_value ML_SERVICE_URL true)
services=(db ml api web)
build_targets=(api web ml)
if [[ "${model_endpoint%/}" == http://teammate-ml:8000 ]]; then
  services+=(teammate-ml)
  build_targets+=(teammate-ml)
fi

compose() {
  # The private file is authoritative, even if this shell has dev values exported.
  env -u DOMAIN -u POSTGRES_PASSWORD -u TRUSTED_PROXY_IP -u SESSION_TTL_HOURS -u AUTH_RATE_LIMIT_MAX -u ML_TIMEOUT_MS -u ML_SERVICE_URL \
    docker compose --project-name flowcredit --env-file "$environment_file" -f docker-compose.production.yml "$@"
}
compose config --quiet
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
curl --fail --silent --show-error --connect-timeout 3 --max-time 15 \
  --header "Host: $domain" --header "Origin: https://$domain" \
  http://127.0.0.1:18080/api/health >/dev/null
rejected_origin=$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' --max-time 15 \
  --request POST --header "Host: $domain" --header 'Origin: https://example.invalid' \
  --header 'Content-Type: application/json' --data '{}' http://127.0.0.1:18080/api/auth/login)
[[ "$rejected_origin" == 403 ]] || { printf 'Production origin policy check failed.\n' >&2; exit 1; }
printf 'Selected services are healthy on loopback. HTTPS host nginx must proxy %s to 127.0.0.1:18080.\n' "$domain"
