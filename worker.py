from celery import Celery

import subprocess, os
import toml

settings = toml.load("./settings.toml")
app = Celery("worker", broker="redis://redis:6379/0", include=["worker"])

@app.task
def clone_repository():
    print("Cloning...")
    return
    repo_dir = settings["repository"]["directory"]

    os.makedirs(repo_dir, exist_ok=True)
    subprocess.run(["git", "clone", settings["repository"]["url"]])

