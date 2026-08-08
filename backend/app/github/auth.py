import time
import jwt

import requests

from app.config import GITHUB_APP_ID, PRIVATE_KEY_PATH


def generate_jwt():

    with open(PRIVATE_KEY_PATH, "r") as f:
        private_key = f.read()

    payload = {
        "iat": int(time.time()),
        "exp": int(time.time()) + 600,
        "iss": GITHUB_APP_ID
    }

    token = jwt.encode(
        payload,
        private_key,
        algorithm="RS256"
    )

    return token


def get_installation_token(installation_id: int):

    jwt_token = generate_jwt()

    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/vnd.github+json"
    }

    response = requests.post(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        headers=headers,
    )

    response.raise_for_status()

    return response.json()["token"]    