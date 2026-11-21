"""Single lazy Firestore client (service account via GOOGLE_APPLICATION_CREDENTIALS)."""
from functools import lru_cache

from backend.common import config


@lru_cache(maxsize=1)
def db():
    from google.cloud import firestore
    return firestore.Client(project=config.GCP_PROJECT or None)


def server_ts():
    from google.cloud import firestore
    return firestore.SERVER_TIMESTAMP
