import abc
import contextlib
import os
import re
import subprocess
from pathlib import Path
from functools import cached_property

from celery import Celery
from celery.utils.log import get_task_logger
import docutils.nodes
from docutils.parsers import rst
from docutils.writers import html4css1
from pygments.formatters import HtmlFormatter
import toml

logger = get_task_logger(__name__)

settings = toml.load("./settings.toml")
app = Celery(
    "worker",
    broker="redis://redis:6379/0",
    result_backend="redis://redis:6379/0",
    include=["worker"],
)


@contextlib.contextmanager
def working_dir(directory):
    """
    Execute a block of code while in a particular working directory, restoring
    the previous directory once finished.
    """
    original = os.getcwd()
    os.chdir(directory)
    try:
        yield
    finally:
        os.chdir(original)


class PygmentsDirective(rst.Directive):
    """
    Handle code-block directives using Pygments
    """

    required_arguments = 0
    optional_arguments = 1
    final_argument_whitespace = True
    option_spec = {
        "height-limit": rst.directives.flag,
    }
    has_content = True

    _formatter_args = None

    @classmethod
    @contextlib.contextmanager
    def configure(cls, content_settings):
        """
        This should be called as a context to configure the pygments directive
        for a run.
        """
        settings = content_settings["pygments"]
        cls._formatter_args = {
            "style": settings["style"],
            "linenos": "inline",
        }
        try:
            yield cls
        finally:
            cls._formatter_args = None

    @classmethod
    def get_formatter(cls, **kwargs):
        if cls._formatter_args is None:
            raise ValueError(f"PygmentsDirective is not configured")
        args = cls._formatter_args.copy()
        args.update(kwargs)
        return HtmlFormatter(**args)

    def run(self):
        from pygments import highlight
        from pygments.lexers import get_lexer_by_name

        cssstyles = (
            "max-height: 200px; overflow-y: scroll;"
            if "height-limit" in self.options
            else ""
        )

        formatter = self.get_formatter(cssstyles=cssstyles)
        language = next(iter(self.arguments), "text")

        try:
            lexer = get_lexer_by_name(language)
        except ValueError:
            # no lexer found - use the text one instead of an exception
            lexer = get_lexer_by_name("text")
        parsed = highlight("\n".join(self.content), lexer, formatter)
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
        if "width" in node:
            # Modify the width so that it doesn't go wider than the page
            w = node["width"]
            if re.match(r"^[0-9.]+$", w):
                w += "px" # Interpret unitless as pixels
            node["width"] = f"min({w}, 100%)"
        super().visit_image(node)
        # Collect any images referenced
        uri = node["uri"]
        if Path(uri).is_absolute():
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

    def __init__(self, src):
        super().__init__()
        self.translator_class = BlogTranslator
        self._src = src

    def translate(self):
        from docutils.utils import Reporter

        super().translate()
        if len(self.document.parse_messages):
            logger.warning(f"Docutils reported issues with {self._src}")
        for m in self.document.parse_messages:
            if m["level"] == Reporter.WARNING_LEVEL:
                logger.warning(m.astext())
            elif m["level"] == Reporter.ERROR_LEVEL:
                logger.error(m.astext())
            elif m["level"] == Reporter.SEVERE_LEVEL:
                logger.critical(m.astext())
            else:
                logger.info(m.astext())

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
        logger.debug(f"Rendering {self.out_path}")
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


class Compiler(abc.ABC):
    """
    Compiles an rst page, returning a Renderable
    """

    def __init__(self, content_settings, src):
        self._content_settings = content_settings
        self.src = src

    def compile(self, jinja_env, out_dir):
        import shutil
        from pathlib import Path
        import docutils.core

        logger.debug(f"Compiling {self.src}")
        # Parse the document
        with open(self.src) as f:
            parts = docutils.core.publish_parts(
                source=f.read(),
                writer=BlogWriter(self.src),
            )
        doc_settings = parts["rstblog_settings"]
        doc_content = parts["rstblog_content"]
        doc_preview = parts["rstblog_preview"]
        title = doc_settings["title"]
        tags = doc_settings["tags"]
        # Determine page path
        url = Path(self.get_url(doc_settings))
        logger.debug(f"Got url {str(url)}, out_dir={str(out_dir)}")
        doc_dir = out_dir / url
        logger.debug(f"Doc dir: {str(doc_dir)}")
        out_path = doc_dir / "index.html"
        os.makedirs(doc_dir, exist_ok=True)  # Subpaths of dates may exist
        # Copy content
        logger.debug(f"Copying {len(doc_content)} items into {doc_dir}")
        for item in doc_content:
            item_src = Path(self.src).parent / item
            item_dest = doc_dir / item
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

    @abc.abstractmethod
    def get_template(self, jinja_env):
        pass

    @abc.abstractmethod
    def get_url(self, page_settings):
        pass


class PageCompiler(Compiler):
    def get_template(self, jinja_env):
        return jinja_env.get_template(self._content_settings["templates"]["page"])

    def get_url(self, page_settings):
        url = Path(page_settings["url"])
        if not Path(url).is_absolute():
            raise ValueError(
                f'Document {self.src} needs an absolute path, "{page_settings["url"]}" supplied'
            )
        return url.relative_to(Path("/"))


class PostCompiler(Compiler):
    def get_template(self, jinja_env):
        return jinja_env.get_template(self._content_settings["templates"]["page"])

    def get_url(self, page_settings):
        url = Path(page_settings["url"])
        date = Path(page_settings["date"].strftime("%Y/%m/%d"))  # YYY/MM/DD
        # There are two modes for posts:
        #  - Relative URL: The url is prepended by the date
        #  - Absolute URL: The URL is used without modification, much like a page
        #
        # Imported pages typically will use an absolute URL and handwritten
        # pages will typically use a relative URL.
        if not url.is_absolute():
            return date / url
        else:
            return url.relative_to(Path("/"))


class RstBlog:
    """
    Renders all blog content, including index and tag pages
    """

    def __init__(self, content_settings, pages, posts, jinja_env, out_dir):
        self._content_settings = content_settings
        self.pages = [
            PageCompiler(content_settings, p).compile(jinja_env, out_dir) for p in pages
        ]
        self.posts = [
            PostCompiler(content_settings, p).compile(jinja_env, out_dir) for p in posts
        ]
        self.index_template = jinja_env.get_template(
            content_settings["templates"]["index"]
        )
        self.out_dir = Path(out_dir)

    def render(self):
        import itertools
        from datetime import datetime

        # Posts are sorted by date
        self.posts.sort(key=lambda d: d.doc_settings["date"])
        self.posts.reverse()
        step = self._content_settings["paginate"]
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
            "posts": self.posts,
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
                with open(self.out_dir / f"{name}.html", "w") as f:
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
            with open(self.out_dir / f"./{name}.html", "w") as f:
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
    repo_dir = Path(settings["repository"]["directory"]).resolve()
    logger.info(f"Cloning {repo_url} into {repo_dir}")
    subprocess.run(["git", "clone", repo_url, repo_dir])


@app.task
def update():
    """
    Updates the repo and re-renders all content
    """
    import glob, shutil
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    repo_dir = Path(settings["repository"]["directory"]).resolve()
    logger.info(f"Updating {repo_dir}")
    with working_dir(repo_dir):
        subprocess.check_output(["git", "remote", "-v"])
        subprocess.check_output(["git", "fetch"])
        subprocess.check_output(["git", "reset", "--hard", "origin/main"])
        subprocess.check_output(["git", "clean", "-fdx", "."])
        content_settings = toml.load("./pyproject.toml")["tool"]["rstblog"]
        paths = content_settings[f"paths"]
        loader = FileSystemLoader(Path().resolve())
        posts_path = Path(paths["posts"]).resolve()
        if repo_dir not in posts_path.parents:
            raise ValueError(
                f"Resolved post path {str(posts_path)} not in repository {str(repo_dir)}"
            )
        pages_path = Path(paths["pages"]).resolve()
        if repo_dir not in pages_path.parents:
            raise ValueError(
                f"Resolved pages pat {str(pages_path)} not in repository {str(repo_dir)}"
            )
        static_paths = [Path(d) for d in paths["static"]]
        for p in static_paths:
            if p.is_absolute():
                raise ValueError(
                    f"Static path {str(p)} is absolute, which is not allowed"
                )
            if repo_dir not in p.resolve().parents:
                raise ValueError(
                    f"Static path {str(p.resolve())} is not in repository {str(repo_dir)}"
                )
        posts = glob.glob(str(posts_path) + "/**/*.rst", recursive=True)
        pages = glob.glob(str(pages_path) + "/**/*.rst", recursive=True)
        static = [(p, p.resolve()) for p in static_paths]

    jinja_env = Environment(loader=loader, autoescape=select_autoescape())
    out_dir = Path(settings["server"]["directory"]).resolve()
    logger.info(f"Cleaning {out_dir}")
    for p in out_dir.iterdir():
        if p.is_dir():
            shutil.rmtree(str(p), ignore_errors=True)
        else:
            os.remove(str(p))
    logger.info(f"Rendering into {out_dir}")
    with working_dir(out_dir), PygmentsDirective.configure(content_settings):
        # Copy in static content
        for relpath, srcpath in static:
            if srcpath.exists():
                shutil.copytree(str(srcpath), str(relpath.resolve()))
        # Helper static content
        pygments_css = Path(content_settings["pygments"]["csspath"]).resolve()
        if out_dir not in pygments_css.parents:
            raise ValueError(
                f"Pygments CSS path {pygments_css} is not in output folder {out_dir}"
            )
        with open(pygments_css, "w") as f:
            formatter = PygmentsDirective.get_formatter()
            f.write(formatter.get_style_defs(".highlight"))
        # Build the blog
        blog = RstBlog(content_settings, pages, posts, jinja_env, out_dir)
        blog.render()
