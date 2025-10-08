
source .venv/bin/activate

export ZK_TOOLS_SECRET="$(openssl rand -hex 32)"
export TZ='Atlantic/Canary'

gunicorn -w 4 -b 0.0.0.0:8000 app:app   



