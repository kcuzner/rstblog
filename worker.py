from celery import Celery

import subprocess, os

from docutils.parsers import rst
import toml

settings = toml.load("./settings.toml")
app = Celery(
    "worker",
    broker="redis://redis:6379/0",
    result_backend="redis://redis:6379/0",
    include=["worker"],
)


class WorkingDir:
    """
    Execute a block of code while in a particular working directory, restoring
    the previous directory once finished.
    """

    def __init__(self, directory):
        self.dir = directory

    def __enter__(self):
        self.original = os.getcwd()
        os.chdir(self.dir)

    def __exit__(self, type, value, traceback):
        os.chdir(self.original)


class PygmentsDirective(rst.Directive):
    """
    Handle code-block directives using Pygments
    """

    required_arguments = 1
    optional_arguments = 0
    final_argument_whitespace = True
    option_spec = {}
    has_content = True

    def run(self):
        from docutils import nodes
        from pygments import highlight
        from pygments.lexers import get_lexer_by_name
        from pygments.formatters import HtmlFormatter

        pygments_formatter = HtmlFormatter()

        print(f"Rendering {self.content}")

        try:
            lexer = get_lexer_by_name(self.arguments[0])
        except ValueError:
            # no lexer found - use the text one instead of an exception
            lexer = get_lexer_by_name("text")
        parsed = highlight("\n".join(self.content), lexer, pygments_formatter)
        return [nodes.raw("", parsed, format="html")]


rst.directives.register_directive("code-block", PygmentsDirective)


@app.task
def clone_repository():
    """
    Creates the initial repository clone
    """
    repo_url = settings["repository"]["url"]
    repo_dir = os.path.abspath(settings["repository"]["directory"])
    print(f"Cloning {repo_url} into {repo_dir}")
    os.makedirs(repo_dir, exist_ok=True)
    subprocess.run(["git", "clone", repo_url, repo_dir])


@app.task
def update():
    """
    Updates the repo and re-renders all content
    """
    import glob, shutil
    import docutils.core
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    repo_dir = os.path.abspath(settings["repository"]["directory"])
    print(f"Updating {repo_dir}")
    with WorkingDir(repo_dir):
        subprocess.run(["git", "remote", "-v"])
        subprocess.run(["git", "pull"])
        loader = FileSystemLoader(os.path.abspath("./"))
        posts = glob.glob(
            os.path.abspath(settings["blog"]["posts"]) + "/**/*.rst", recursive=True
        )
        pages = glob.glob(
            os.path.abspath(settings["blog"]["pages"]) + "/**/*.rst", recursive=True
        )
        static = [(d, os.path.abspath(d)) for d in settings["blog"]["static"]]

    jinja_env = Environment(loader=loader, autoescape=select_autoescape())
    out_dir = os.path.abspath(settings["server"]["directory"])
    print(f"Rendering into {out_dir}")
    with WorkingDir(out_dir):
        # Copy in static content
        for s in static:
            shutil.rmtree(s[0], ignore_errors=True)
            if os.path.exists(s[1]):
                shutil.copytree(s[1], os.path.abspath(s[0]))
        # Render the index
        index = jinja_env.get_template(settings["blog"]["index"])
        with open("./index.html", "w") as f:
            f.write(index.render())
        # docutils.core.publish_file(
        #     source_path=index, destination_path="./index.html", writer_name="html"
        # )
