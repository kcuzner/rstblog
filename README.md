# rstblog

This is some static blogging software based on reStructuredText hosted on a cloud git repository and compiled into
static HTML in response to webhooks.

This was born out of frustration with the resources required to run a wordpress-based blog on AWS with constant Russian
spam attacks. Even after giving up and getting rid of all commenting functionality, the server would experience frequent
crashes (running out of filesystem handles and the like). This is an attempt an extremely lightweight blog which can run
cheaply on the smallest AWS instance and handle reasonably sized DDOS attacks (I've counted only about 10 or 20 servers
per "spam cohort", as I call them, in my logs).

# Featuers

- Git-based publishing workflow, specifically tailored towards GitHub.
- No commenting functionality (yes, to me this is a feature).
- Static-only HTML. No resources required for every request to dynamically render things.

# Parts

The blog runs as a self-contained set of containers put together with `docker-compose`. There are a few components:

## nginx

The heart of the blog is nginx, set up to render the blog HTML and forward publish requests into a small pywsgi app.

## web

The web service runs a Flask application which handles the publish requests. In the future this could be extended to
also provide the commenting backend, should I decide I feel like moderating comments again.

## worker

The worker is a Celery app which handles long running work requests, such as rendering the content in a git repository.

## redis

Redis is used as the backbone for the communication between `web` and `worker`.

# Deployment

This is meant to be deployed on a single server, along with several other apps. I haven't quite figured this all out,
but my attack plan is as follows:

 - On the host server, have a "primary service group" which takes over ports 80 and 443, serving with nginx. It should
   have a named network and the nginx configuration file should have knowledge of the apps that are running and
reverse-proxy to them. One app, probably this one, will serve the `/` endpoint.
 - For each app to run, such as this blog, they'll be executed with a separate `docker-compose` invocation, but should
   be overridden to have their nginx instance attached to the aforementioned named network, probably with the hostname
overridden to something more global.

Things I still haven't worked out include how to survive reboots and whether or not the overhead of basically running
dozens of nginx servers on a single machine is well-advised.

# Blog Content

Blog content should be hosted in a separate repository. It is specified as a combination of Jinja2 and reStructuredText
files.

## Theming

The blog theme and homepage are explicitly set up using a set of Jinja2 templates:

 - index.j2: This is the template for the homepage of the blog. It is rendered for each page of the post feed.
 - tags.j2: This is the template for a tag page, rendered for each page of the post feed for a particular tag.
 - page.j2: This is the template for a page, content that does not appear directly in the post feed.
 - post.j2: This is the template for a post, content which *does* appear directly in the post feed.

Other than these templates, theme content can be supplied in a few ways:

 - Direct static content. As configured in settings.toml, everything in the designated "static" folder will be directly
   copied into the HTML output directory at the root, preserving directory heirarchy. This should include images, CSS and
Javascript used by the theming templates.
 - SASS stylesheets. The SASS preprocessor will be ran on any SASS (.scss) file located in the configured static folder,
   with the result being placed in the output folder in lieu of the source file.

## Posts

Blog posts can have arbitrary file names, but the standard extension is `.rst`. As configured in the settings.toml file,
the posts folder in the content repository will be recursively searched for all `.rst` files.

Post rst files are required to contain a `rstblog-settings` directive. This functions similar to the `meta` directive in
that it isn't directly rendered into the HTML. Rather than appearing in the header, however, it instead controls how the
blog post is placed:

 - `:title:` Sets the title of the post.
 - `:date:` Sets the date of the post.
 - `:url:` Sets the url name of the post. The full URL to the post will be created from the `:date:` and `:url:`
   directives so that it is mounted at "/YYYY/MM/DD/url".
 - `:tags:` Sets the list of tags to categorize this post under.

When rendered, the post will be rendered into an `index.html` page located under a folder structured as noted earlier so
that the post appears just another blog like wordpress where posts look like folders in the URL.

Hyperlinks, images, and other things which link to other documents have their URLs rewritten according the following
rules:
 - All relative paths to media will be evaluated and the media uploaded into the same folder as the "index.html" for a
   post. Reusing the same media for many posts will result in many copies of the media being uploaded until I optimize
this.
 - All hyperlinks to rst files should be done using relative paths. These will be parsed into a concrete link to the
   rendered path for the linked rst file, if the file is included in the parsing. If the file isn't included, then the
link is removed.

I don't really have a recommendation for the actual file structure of posts, but here are some thoughts:

 - All the posts could be "my-awesome-post.rst" file, possibly prefixed by a number if you like sequential ordered posts, like
   "0017-my-awesome-post.rst". Media for that post could be placed in "my-awesome-post/" or "0017-my-awesome-post/"
 - You could make folders for categories and structure the files that way.
 - Basically any other structure. The blog is designed to be mostly agnostic to how you choose to structure your files.

