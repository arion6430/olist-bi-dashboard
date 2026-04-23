import os
import redis

# Metadata database (Superset's own PostgreSQL)
SQLALCHEMY_DATABASE_URI = os.environ.get(
    "SQLALCHEMY_DATABASE_URI",
    "postgresql+psycopg2://superset:superset_meta_pass@superset-db:5432/superset",
)

# Secret key
SECRET_KEY = os.environ.get("SUPERSET_SECRET_KEY", "")

# Redis cache
REDIS_HOST = "superset-redis"
REDIS_PORT = 6379
REDIS_CELERY_DB = 0
REDIS_RESULTS_DB = 1

CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_DEFAULT_TIMEOUT": 300,
    "CACHE_KEY_PREFIX": "superset_",
    "CACHE_REDIS_HOST": REDIS_HOST,
    "CACHE_REDIS_PORT": REDIS_PORT,
    "CACHE_REDIS_DB": REDIS_RESULTS_DB,
}

DATA_CACHE_CONFIG = CACHE_CONFIG

class CeleryConfig:
    broker_url = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_CELERY_DB}"
    imports = ("superset.sql_lab",)
    result_backend = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_RESULTS_DB}"
    worker_prefetch_multiplier = 1
    task_acks_late = False
    beat_schedule = {
        "reports.scheduler": {
            "task": "reports.scheduler",
            "schedule": 1,
        },
    }

CELERY_CONFIG = CeleryConfig

# Allow all hosts in dev
WTF_CSRF_ENABLED = True
ENABLE_PROXY_FIX = True
