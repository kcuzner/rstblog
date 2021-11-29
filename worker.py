from celery import Celery

import subprocess, os

import docutils.nodes
from docutils.parsers import rst
from docutils.writers import html4css1
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
        return [docutils.nodes.raw("", parsed, format="html")]


rst.directives.register_directive("code-block", PygmentsDirective)


class rstblog_settings(docutils.nodes.Element):
    pass


class RstBlogSettingsDirective(rst.Directive):
    """
    Handle rstblog-settings directives

    Date must be in the format YYYY/MM/DD
    """

    def taglist(argument):
        if argument and argument.strip():
            return [x.strip() for x in argument.split(",") if x.strip()]
        return []

    def date(argument):
        from datetime import datetime

        if argument is None:
            raise ValueError("argument required but not supplied")
        return datetime.strptime(argument, "%Y/%m/%d")

    required_arguments = 0
    optional_arguments = 0
    option_spec = {
        "title": rst.directives.unchanged_required,
        "date": date,
        "url": rst.directives.uri,
        "tags": taglist,
    }

    def run(self):
        node = rstblog_settings()
        for name in self.option_spec:
            if name in self.options:
                node[name] = self.options[name]
            else:
                node[name] = self.option_spec[name](None)
        return [node]


rst.directives.register_directive("rstblog-settings", RstBlogSettingsDirective)


class BlogTranslator(html4css1.HTMLTranslator):
    """
    Customized docutils translator which handles the rstblog-settings nodes
    declaring metadata about a document.
    """

    def __init__(self, document):
        super().__init__(document)
        self.rstblog_settings = {}
        self.rstblog_content = []

    def visit_image(self, node):
        super().visit_image(node)
        # Collect any images referenced
        uri = node["uri"]
        if os.path.isabs(uri):
            raise ValueError(
                f"Image {node} references an absolute path to an image, this is not allowed"
            )
        self.rstblog_content.append(uri)

    def visit_rstblog_settings(self, node):
        for setting, value in node.attlist():
            self.rstblog_settings[setting] = value

    def depart_rstblog_settings(self, node):
        pass


class BlogWriter(html4css1.Writer):
    """
    Customized docutils writer which handles the rstblog-settings nodes
    declaring metadata about a document.
    """

    rstblog_attributes = ("rstblog_settings", "rstblog_content")

    visitor_attributes = html4css1.Writer.visitor_attributes + rstblog_attributes

    def __init__(self):
        super().__init__()
        self.translator_class = BlogTranslator

    def assemble_parts(self):
        super().assemble_parts()
        for part in self.visitor_attributes:
            if part in self.rstblog_attributes:
                self.parts[part] = getattr(self, part)
            else:
                self.parts[part] = "".join(getattr(self, part))


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
    from pathlib import Path
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
    print(f"Cleaning {out_dir}")
    for f in os.listdir(out_dir):
        path = os.path.join(out_dir, f)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            os.remove(path)
    print(f"Rendering into {out_dir}")
    with WorkingDir(out_dir):
        # Copy in static content
        for s in static:
            shutil.rmtree(s[0], ignore_errors=True)
            if os.path.exists(s[1]):
                shutil.copytree(s[1], os.path.abspath(s[0]))
        # Render each page
        page_tmpl = jinja_env.get_template(settings["blog"]["page"])
        for page in pages:
            print(f"Rendering {page}")
            # Parse the page
            with open(page) as f:
                parts = docutils.core.publish_parts(
                    source=f.read(), writer=BlogWriter()
                )
            page_settings = parts["rstblog_settings"]
            page_content = parts["rstblog_content"]
            title = page_settings["title"]
            url = page_settings["url"]
            # Determine page path
            if not os.path.isabs(url):
                raise ValueError(
                    f'Page {page} needs an absolute path, "{page_settings["url"]}" supplied'
                )
            page_dir = os.path.join(out_dir, os.path.relpath(url, "/"))
            os.makedirs(page_dir)
            out_path = os.path.join(page_dir, "index.html")
            # Copy content
            print(f"Copying {len(page_content)} items into {out_dir}")
            for item in page_content:
                item_src = os.path.join(Path(page).parent, item)
                item_dest = os.path.join(page_dir, item)
                shutil.copyfile(item_src, item_dest)
            print(f"Rendering into {out_path}")
            with open(out_path, "w") as f:
                f.write(page_tmpl.render(parts=parts))
        # Render the index
        index = jinja_env.get_template(settings["blog"]["index"])
        with open("./index.html", "w") as f:
            f.write(index.render())
