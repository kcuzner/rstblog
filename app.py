#!/usr/bin/env python3

from flask import Flask, request

import functools
import hashlib
import hmac
import logging
import toml

import worker

settings = toml.load("./settings.toml")
app = Flask(__name__)

worker.clone_repository.delay().wait()

_log = app.logger

def validate_hmac(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        sig = request.headers.get("X-Hub-Signature-256", None)
        if sig is None:
            return {"message": "X-Hub-Signature-256 header missing"}, 403
        hashobj = hmac.new(
            settings["server"]["secret"].encode("utf-8"),
            msg=request.data,
            digestmod=hashlib.sha256,
        )
        expected = "sha256=" + hashobj.hexdigest()
        if not hmac.compare_digest(expected, sig):
            return {"message": "HMAC validation failed"}, 401
        _log.debug("Validated HMAC")
        return f(*args, **kwargs)

    return wrapper


@app.route("/refresh", methods=["POST"])
@validate_hmac
def request_refresh():
    _log.info("Refresh request received")
    worker.update.delay()
    return {}
