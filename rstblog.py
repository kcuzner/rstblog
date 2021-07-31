#!/usr/bin/env python3

from flask import Flask, request

import asyncio, datetime, enum, subprocess, os
import toml

settings = toml.load("./settings.toml")
actions = asyncio.Queue()
app = Flask(__name__)


class ActionType(enum.Enum):
    REFRESH = 1


class Action:
    def __init__(self, action):
        self.type = action
        self.timestamp = datetime.datetime.now()


async def cloner():
    """
    Handles long-running requests to regenerate the repository outputs
    """
    while True:
        request = await requests.get()
        print(request)


@app.route("/refresh", methods=["POST"])
async def request_refresh():
    data = request.json


def main():

    repo_dir = settings["repository"]["directory"]

    os.makedirs(repo_dir, exist_ok=True)
    subprocess.run(["git", "clone", settings["repository"]["url"]])


if __name__ == "__main__":
    main()
