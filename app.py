#!/usr/bin/env python3

from flask import Flask, request

import asyncio, atexit, datetime, enum, queue, subprocess, os
from functools import wraps
import toml

import worker

settings = toml.load("./settings.toml")
actions = queue.Queue()
app = Flask(__name__)

worker.clone_repository.delay().wait()


def validate_hmac(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        return {}, 401

    return wrapper


@app.route("/test")
def hi():
    worker.update.delay()
    return {}


@app.route("/refresh", methods=["POST"])
@validate_hmac
async def request_refresh():
    data = request.json
    print(data)
    return {}
