from celery import Celery

import subprocess, os
from functools import cached_property

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
        for fmt in ("%Y/%m/%d", "%d %B %Y", "%d %b %Y"):
            try:
                return datetime.strptime(argument, fmt)
            except ValueError:
                pass
        raise ValueError(f"Unrecognized date format: {argument}")

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


class rstblog_break(docutils.nodes.Element):
    pass


class RstBlogBreakDirective(rst.Directive):
    """
    Handle rstblog-break directives
    """

    required_arguments = 0
    optional_arguments = 0

    def run(self):
        return [rstblog_break()]


rst.directives.register_directive("rstblog-break", RstBlogBreakDirective)


class BlogTranslator(html4css1.HTMLTranslator):
    """
    Customized docutils translator which handles the rstblog-settings nodes
    declaring metadata about a document.
    """

    def __init__(self, document):
        super().__init__(document)
        self.rstblog_settings = {}
        self.rstblog_content = []
        self._rstblog_preview = None

    @property
    def rstblog_preview(self):
        return self._rstblog_preview if self._rstblog_preview else "".join(self.body)

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

    def visit_rstblog_break(self, node):
        self._rstblog_preview = "".join(self.body)

    def depart_rstblog_break(self, node):
        pass


class BlogWriter(html4css1.Writer):
    """
    Customized docutils writer which handles the rstblog-settings nodes
    declaring metadata about a document.
    """

    rstblog_attributes = ("rstblog_settings", "rstblog_content", "rstblog_preview")

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


class Renderable:
    """
    Something which renders into an output file
    """

    def __init__(self, out_path, render_fn):
        self.out_path = out_path
        self.render_fn = render_fn

    def render(self, **kwargs):
        print(f"Rendering {self.out_path}")
        with open(self.out_path, "w") as f:
            f.write(self.render_fn(**kwargs))


class DocumentRenderable(Renderable):
    """
    Renderable that holds some metadata about a document
    """

    def __init__(self, out_path, render_fn, url, doc_settings, doc_preview):
        super().__init__(out_path, render_fn)
        self._url = url
        self.doc_settings = doc_settings
        self.doc_preview = doc_preview

    @cached_property
    def title(self):
        return self.doc_settings["title"]

    @cached_property
    def tags(self):
        return self.doc_settings["tags"]

    @cached_property
    def url(self):
        return self._url


class Compiler:
    """
    Compiles an rst page, returning a Renderable
    """

    def __init__(self, src):
        self.src = src

    def compile(self, jinja_env, out_dir):
        import shutil
        from pathlib import Path
        import docutils.core

        print(f"Compiling {self.src}")
        # Parse the document
        with open(self.src) as f:
            parts = docutils.core.publish_parts(source=f.read(), writer=BlogWriter())
        doc_settings = parts["rstblog_settings"]
        doc_content = parts["rstblog_content"]
        doc_preview = parts["rstblog_preview"]
        title = doc_settings["title"]
        tags = doc_settings["tags"]
        # Determine page path
        url = self.get_url(doc_settings)
        print(f"Got url {url}, out_dir={out_dir}")
        doc_dir = os.path.join(out_dir, url)
        print(f"Doc dir: {doc_dir}")
        out_path = os.path.join(doc_dir, "index.html")
        os.makedirs(doc_dir, exist_ok=True)  # Subpaths of dates may exist
        # Copy content
        print(f"Copying {len(doc_content)} items into {doc_dir}")
        for item in doc_content:
            item_src = os.path.join(Path(self.src).parent, item)
            item_dest = os.path.join(doc_dir, item)
            shutil.copyfile(item_src, item_dest)
        # Set up for rendering
        # Actual rendering occurs later since we need the full list of posts
        # and such for each page to be rendered correctly.
        template = self.get_template(jinja_env)
        return DocumentRenderable(
            out_path,
            lambda **kwargs: template.render(
                parts=parts, title=title, tags=tags, **kwargs
            ),
            url,
            doc_settings,
            doc_preview,
        )

    def get_template(self, jinja_env):
        raise NotImplementedError(f"get_template must be overriden in {type(self)}")

    def get_url(self, page_settings):
        raise NotImplementedError(f"get_template must be overridden in {type(self)}")


class PageCompiler(Compiler):
    def get_template(self, jinja_env):
        return jinja_env.get_template(settings["blog"]["page"])

    def get_url(self, page_settings):
        url = page_settings["url"]
        if not os.path.isabs(url):
            raise ValueError(
                f'Document {self.src} needs an absolute path, "{page_settings["url"]}" supplied'
            )
        return os.path.relpath(url, "/")


class PostCompiler(Compiler):
    def get_template(self, jinja_env):
        return jinja_env.get_template(settings["blog"]["post"])

    def get_url(self, page_settings):
        url = page_settings["url"]
        date = page_settings["date"].strftime("%Y/%m/%d")  # YYY/MM/DD
        if not os.path.isabs(url):
            raise ValueError(
                f'Document {self.src} needs an absolute path, "{page_settings["url"]}" supplied'
            )
        return os.path.join(date, os.path.relpath(url, "/"))


class RstBlog:
    """
    Renders all blog content, including index and tag pages
    """

    def __init__(self, pages, posts, jinja_env, out_dir):
        self.pages = [PageCompiler(p).compile(jinja_env, out_dir) for p in pages]
        self.posts = [PostCompiler(p).compile(jinja_env, out_dir) for p in posts]
        self.index_template = jinja_env.get_template(settings["blog"]["index"])
        self.out_dir = out_dir

    def render(self):
        import itertools
        from datetime import datetime

        # Posts are sorted by date
        self.posts.sort(key=lambda d: d.doc_settings["date"])
        self.posts.reverse()
        step = settings["blog"]["paginate"]
        paginated = [self.posts[i : i + step] for i in range(0, len(self.posts), step)]
        post_months = [
            (d.doc_settings["date"].strftime("%Y/%m"), d) for d in self.posts
        ]
        posts_by_month = [
            (datetime.strptime(m, "%Y/%m"), m, list(g))
            for m, g in itertools.groupby(
                self.posts, key=lambda p: p.doc_settings["date"].strftime("%Y/%m")
            )
        ]

        # Render everything
        render_params = {
            "pages": self.pages,
            "posts_by_month": posts_by_month,
            "posts_paginated": paginated,
        }
        # Pages and posts
        for r in self.pages + self.posts:
            r.render(**render_params)
        # Monthly index
        for date, url, posts in posts_by_month:
            month_paginated = [posts[i : i + step] for i in range(0, len(posts), step)]
            name = f"{url}/index.html"
            month = date.strftime("%b %Y")
            for i, page in enumerate(month_paginated):
                name = f"{url}/index{i}" if i else f"{url}/index"
                # NOTE: The folder should have already been created when rendering
                # pages and posts
                with open(os.path.join(self.out_dir, f"{name}.html"), "w") as f:
                    f.write(
                        self.index_template.render(
                            index_name=f"Posts {month}, Page {i+1}",
                            index_posts=posts,
                            index_number=0,
                            index_count=1,
                            **render_params,
                        )
                    )
        # Main index
        for i, page in enumerate(paginated):
            name = f"index{i}" if i else "index"
            with open(os.path.join(self.out_dir, f"./{name}.html"), "w") as f:
                f.write(
                    self.index_template.render(
                        index_name=f"Page {i+1}",
                        index_posts=page,
                        index_number=i,
                        index_count=len(paginated),
                        **render_params,
                    )
                )


@app.task
def clone_repository():
    """
    Creates the initial repository clone
    """
    repo_url = settings["repository"]["url"]
    repo_dir = os.path.abspath(settings["repository"]["directory"])
    print(f"Cloning {repo_url} into {repo_dir}")
    subprocess.run(["git", "clone", repo_url, repo_dir])


@app.task
def update():
    """
    Updates the repo and re-renders all content
    """
    import glob, shutil
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    repo_dir = os.path.abspath(settings["repository"]["directory"])
    print(f"Updating {repo_dir}")
    with WorkingDir(repo_dir):
        subprocess.check_output(["git", "remote", "-v"])
        subprocess.check_output(["git", "fetch"])
        subprocess.check_output(["git", "reset", "--hard", "origin/master"])
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
        blog = RstBlog(pages, posts, jinja_env, out_dir)
        blog.render()
