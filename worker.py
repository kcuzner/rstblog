from celery import Celery

import subprocess, os

import docutils.core
import toml

settings = toml.load("./settings.toml")
app = Celery(
    "worker",
    broker="redis://redis:6379/0",
    result_backend="redis://redis:6379/0",
    include=["worker"],
)


class WorkingDir:
    def __init__(self, directory):
        self.dir = directory

    def __enter__(self):
        self.original = os.getcwd()
        os.chdir(self.dir)

    def __exit__(self, type, value, traceback):
        os.chdir(self.original)


@app.task
def clone_repository():
    repo_url = settings["repository"]["url"]
    repo_dir = os.path.abspath(settings["repository"]["directory"])
    print(f"Cloning {repo_url} into {repo_dir}")
    os.makedirs(repo_dir, exist_ok=True)
    subprocess.run(["git", "clone", repo_url, repo_dir])


@app.task
def update():
    repo_dir = os.path.abspath(settings["repository"]["directory"])
    print(f"Updating {repo_dir}")
    with WorkingDir(repo_dir):
        subprocess.run(["git", "remote", "-v"])
        subprocess.run(["git", "pull"])
        index = os.path.abspath(settings["rst"]["index"])
    out_dir = os.path.abspath(settings["server"]["directory"])
    print(f"Rendering into {out_dir}")
    with WorkingDir(out_dir):
        docutils.core.publish_file(
            source_path=index, destination_path="./index.html", writer_name="html"
        )
