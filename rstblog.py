#!/usr/bin/env python3

from flask import Flask, request

import asyncio, atexit, datetime, enum, queue, subprocess, os
from functools import wraps
import toml

settings = toml.load("./settings.toml")
actions = queue.Queue()
app = Flask(__name__)


class ActionType(enum.Enum):
    REFRESH = 1


class Action:
    def __init__(self, action):
        self.type = action
        self.timestamp = datetime.datetime.now()


def action_handler():
    """
    Handles long-running requests to regenerate the repository outputs
    """
    print("Waiting for action requests")
    while True:
        action = actions.get()
        print(action)

handler_thread = threading.Thread(target=action_handler)
handler_thread.start()

def validate_hmac(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        return {}, 401

    return wrapper


@app.route("/refresh", methods=["POST"])
@validate_hmac
async def request_refresh():
    data = request.json
    print(data)
    return {}


def main():
    repo_dir = settings["repository"]["directory"]

    os.makedirs(repo_dir, exist_ok=True)
    subprocess.run(["git", "clone", settings["repository"]["url"]])


if __name__ == "__main__":
    main()
