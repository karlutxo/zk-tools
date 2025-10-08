export ZK_TOOLS_SECRET="$(openssl rand -hex 32)"

docker compose build
docker compose build --no-cache

docker compose up -d

