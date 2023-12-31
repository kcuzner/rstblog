# rstblog

> :warning: :warning: :warning: ***THIS IS A WORK IN PROGRESS*** :warning: :warning: :warning:
>
> Contact me directly or open an issue to inquire about the status of this project.

This is some static blogging software based on reStructuredText hosted on a cloud git repository
and compiled into static HTML in response to webhooks.

This was born out of frustration with the resources required to run a wordpress-based blog on AWS
with constant Russian spam attacks. Even after giving up and getting rid of all commenting
functionality, the server would experience frequent crashes (running out of filesystem handles and
the like). This is an attempt an extremely lightweight blog which can run cheaply on the smallest
AWS instance and handle reasonably sized DDOS attacks (I've counted only about 10 or 20 servers per
"spam cohort", as I call them, in my logs). It's also possible that some of my woes come from my
own misconfiguration of the server, so this is also an attempt to resolve those kinds of problems.

# Featuers

- Git-based publishing workflow, specifically tailored towards GitHub.
- No commenting functionality (yes, to me this is a feature).
- Static-only HTML. No resources required for every request to dynamically render things.

# Parts

The blog runs as a self-contained set of containers put together with `docker-compose`. There are a
few components:

## nginx

The heart of the blog is nginx, set up to render the blog HTML and forward publish requests into a
small pywsgi app.

## web

The web service runs a Flask application which handles the publish requests. In the future this
could be extended to also provide the commenting backend, should I decide I feel like moderating
comments again.

## worker

The worker is a Celery app which handles long running work requests, such as rendering the content
in a git repository.

## redis

Redis is used as the backbone for the communication between `web` and `worker`.

# Deployment

This is meant to be deployed on a single server, along with several other apps. I haven't quite
figured this all out, but my attack plan is as follows:

 - On the host server, have a "primary service group" which takes over ports 80 and 443, serving
   with nginx. It should have a named network and the nginx configuration file should have
   knowledge of the apps that are running and reverse-proxy to them. One app, probably this one,
   will serve the `/` endpoint.
 - For each app to run, such as this blog, they'll be executed with a separate `docker-compose`
   invocation, but should be overridden to have their nginx instance attached to the aforementioned
   named network, probably with the hostname overridden to something more global.

Things I still haven't worked out include how to survive reboots and whether or not the overhead of
basically running dozens of nginx servers on a single machine is well-advised.

This repository should be cloned directly onto the server, potentially checking out a tag or other
branch to get a specific version. When the docker containers are composed, the file content of this
repository is used to configure and build the containers. See the `run_interactive.sh` script for
an example of one way to run this app.

# Configuration

A `settings.toml` must be supplied in the root of this repository in the production environment,
based on the settings.tmpl.toml file in this repo. See the template file for details.

In addition, a docker-compose.override.yml may be supplied. This can be used for configuring a
development setup (as opposed to the production setup) in conjunction with an appropriate
`settings.toml` file like so:

```toml
services:
  worker:
    volumes:
      - type: bind
        # Relative to this repo, this is the location of the in-development blog content
        source: ../rstblog-content
        # This target location in the worker repo is also referenced in the local settings.toml
        # as "/repo" (vs a github URL) for the content repo url.
        target: /repo
```

# Blog Content

Blog content should be hosted in a separate repository. It is specified as a combination of Jinja2
and reStructuredText files, with a required pyproject.toml file at the root of the repository
containing settings.

## Settings

The following settings should be set in pyproject.toml of the content repository:

```toml
[tool.rstblog]
# General configuration for rstblog
paginate = 10

[tool.rstblog.templates]
# Template configuration for rstblog
#
# These paths are resolved relative to the pyproject.toml and disallowed from resolving to a path
# outside the repository. The paths point to Jinja2 templates.
#
# index: This is the template for the homepage of the blog. It is rendered for each page of the
#   post feed.
# tags: This is the template for a tag page, rendered for each page of the post feed for a
#   particular tag.
# page:  This is the template for a page, content that does not appear directly in the post feed.
# post: This is the template for a post, content which *does* appear directly in the post feed.
index = "./index.j2"
tags = "./tags.j2"
post = "./post.j2"
page = "./page.j2"

[tool.rstblog.paths]
# Path configuration for rstblog
#
# Any paths are resolved relative to the pyproject.toml and disallowed from resolving to a path
# outside the repository.
#
# static: List of paths under which to find static content. These files will be copied into the
#   HTML output directory at the root, preseving heirarchy as it's seen in the repo.
# pages: Path under which to find ReST files to be treated as pages
# posts: Path under which to find ReST files to be treated as posts
static = ["./css", "./js"]
pages = "./pages"
posts = "./posts"

[tool.rstblog.pygments]
# Settings for pygments used in the rstblog for syntax highlighting
#
# Any paths are resolved relative to the pyproject.toml and disallowed from resolving to a path
# outside the repository.
#
# style: This is the pygments style name to choose from. Only builtin styles are supported.
# csspath: This is the path in the HTML output folder to place the pygments style sheet
style = "friendly"
csspath = "./css/pygments.css"
```
## Posts

Blog posts can have arbitrary file names, but the standard extension is `.rst`. As configured in
the content pyproject.toml file, the posts folder in the content repository will be recursively
searched for all `.rst` files.

Post rst files are required to contain a `rstblog-settings` directive. This functions similar to
the `meta` directive in that it isn't directly rendered into the HTML. Rather than appearing in the
header, however, it instead controls how the blog post is placed:

 - `:title:` Sets the title of the post.
 - `:date:` Sets the date of the post.
 - `:url:` Sets the url name of the post. If this is simply a relative path (i.e. no leading
   `/`), The full URL to the post will be created from the `:date:` and `:url:` directives so that
    it is mounted at "/YYYY/MM/DD/url". Otherwise, it'll simply be mounted at the requested
    location.
 - `:tags:` Sets the list of tags to categorize this post under.

When rendered, the post will be rendered into an `index.html` page located under a folder
structured as noted earlier so that the post appears just another blog like wordpress where posts
look like folders in the URL.

Hyperlinks, images, and other things which link to other documents have their URLs rewritten
according the following rules:
 - All relative paths to media will be evaluated and the media uploaded into the same folder as the
   "index.html" for a post. Reusing the same media for many posts will result in many copies of the
   media being uploaded until I optimize this. Absolute paths to images and other media are not
   allowed (i.e. everything needs to be locally sourced in the content repo.
 - All hyperlinks to rst files should be done using relative paths. These will be parsed into a
   concrete link to the rendered path for the linked rst file, if the file is included in the
   parsing. If the file isn't included, then the link is removed.

I don't really have a recommendation for the actual file structure of posts, but here are some
thoughts:

 - All the posts could be "my-awesome-post.rst" file, possibly prefixed by a number if you like
   sequential ordered posts, like "0017-my-awesome-post.rst". Media for that post could be placed
   in "my-awesome-post/" or "0017-my-awesome-post/"
 - You could make folders for categories and structure the files that way.
 - Basically any other structure. The blog is designed to be mostly agnostic to how you choose to
   structure your files.

