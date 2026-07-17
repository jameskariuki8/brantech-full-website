# Server-rendered blog posts at real URLs

**Date:** 2026-05-29
**Status:** Approved (design)

## Goal

Make individual blog posts crawlable and shareable: server-render each post at a
real, slug-based URL (`/blog/<slug>/`), and server-render the `/blog/` list page
so crawlers can discover those URLs. This is the highest-impact SEO fix from the
audit — today blog content is client-rendered via JS with no per-post URLs, so
it is effectively invisible to search engines.

## Non-goals

- `sitemap.xml`, `robots.txt`, site-wide Open Graph/canonical (separate audit items).
- Server-rendering the homepage blog cards (they stay on the existing JS).
- Server-rendering projects (a later, parallel effort).
- A rich-text/Markdown editor in the admin panel (authoring stays a plain textarea;
  Markdown is rendered on display).

## Decisions (from brainstorming)

1. **URL scheme:** slug-based `/blog/<slug>/`.
2. **Scope:** server-render both the detail pages and the `/blog/` list page.
   Homepage blog cards remain JS-driven.
3. **Content format:** `content` is rendered as **Markdown → sanitized HTML**.

## Architecture / components

### 1. Model & data — `brand/models.py` + migrations

- Add to `BlogPost`:
  - `slug = models.SlugField(max_length=220, unique=True, blank=True)`
  - `get_absolute_url(self)` → `reverse('blog_detail', kwargs={'slug': self.slug})`
  - Override `save()`: if `slug` is empty, generate from `title` via
    `django.utils.text.slugify`, then ensure uniqueness by appending `-2`, `-3`, …
    until no other `BlogPost` has that slug. (Generate only when blank so existing
    slugs are stable across title edits.)
- **Migration A (schema):** add the `slug` field (nullable/blank during backfill).
- **Migration B (data):** `RunPython` backfilling slugs for existing posts from
  their titles, with the same uniqueness suffixing. Reverse op = no-op.

### 2. Markdown rendering — `brand/markdown_utils.py` (new)

- `render_markdown(text: str) -> str`:
  - `markdown.markdown(text or "", extensions=['extra', 'nl2br', 'sane_lists'])`
  - Sanitize the resulting HTML with **`nh3`** using an explicit allowlist:
    - Tags: `p, br, h1, h2, h3, h4, strong, em, b, i, ul, ol, li, a, code, pre,
      blockquote, hr, img, table, thead, tbody, tr, th, td`
    - Attributes: `a` → `href, title, rel`; `img` → `src, alt, title`
  - `nl2br` makes existing plain-text posts (single newlines) render with line breaks.
- Rendered in the view; the template receives pre-sanitized HTML and outputs it
  with `|safe`.

### 3. URLs & views — `brand/urls.py`, `brand/views.py`

- `path('blog/', views.blog, name='blog')` — now an SSR list view:
  - `BlogPost.objects.all()` (model Meta already orders `-created_at`),
    paginated with Django `Paginator` (9 per page, `?page=` param).
  - Renders `brand/blog.html` with `posts` (page object) in context.
- `path('blog/<slug:slug>/', views.blog_detail, name='blog_detail')`:
  - `post = get_object_or_404(BlogPost, slug=slug)`
  - `content_html = render_markdown(post.content)`
  - Increment views: `BlogPost.objects.filter(pk=post.pk).update(view_count=F('view_count') + 1)`
    (avoids read-modify-write races; does not bump `updated_at`).
  - Renders `brand/blog_detail.html` with `post` and `content_html`.
- Route ordering: `blog/` before `blog/<slug:slug>/`; no other `/blog/...` routes exist to shadow.

### 4. Templates & per-post SEO

- **`brand/blog.html` (rewrite content section):** replace the JS-injected grid
  with `{% for post in posts %}` cards, each linking to `{{ post.get_absolute_url }}`.
  Preserve existing `{% include 'brand/header.html' %}` / footer and styling.
  Add pagination controls using the page object. Keep exactly one `<h1>`.
- **`brand/blog_detail.html` (new):** follows existing standalone-template pattern
  (own `<head>`, header/footer includes). Renders cover image, title (`<h1>`),
  category, tags (`post.get_tags_list`), date, and `{{ content_html|safe }}`.
  SEO payload (the point of SSR):
  - `<title>{{ post.title }} — TekLora</title>`
  - `<meta name="description" content="{{ post.excerpt }}">`
  - `<link rel="canonical" href="{{ request.build_absolute_uri }}">`
  - Open Graph: `og:type=article`, `og:title`, `og:description`, `og:url`,
    `og:image` (post image if present).
  - `BlogPosting` JSON-LD (headline, datePublished `created_at`, dateModified
    `updated_at`, image, author/publisher = TekLora, mainEntityOfPage = canonical URL).

### 5. JS + API — `brand/static/brand/js/blog-integration.js`, `brand/api_views.py`

- Add `'slug': post.slug` to the JSON in `api_views.post_list` and `post_detail`.
- In `blog-integration.js`, change card links from `/blog/` to `/blog/${post.slug}/`
  (homepage cards now deep-link to real post pages).

### Dependencies — `brandtechsolution/requirements.txt`

- Add `markdown` and `nh3` (unpinned, matching existing style).

## Error handling

- Unknown slug → 404 via `get_object_or_404`.
- Empty/null `content` → `render_markdown("")` returns `""`; template shows the
  post chrome without a body.
- Malicious `content` (e.g. `<script>`, `onerror=`) → stripped by `nh3` allowlist.
- Slug collisions → uniqueness suffixing in `save()` and the data migration.

## Testing

- **Unit (`brand/tests.py` additions or a focused test module):**
  - Slug auto-generated from title on create; collision produces `-2` suffix;
    existing slug preserved on title change.
  - `get_absolute_url()` returns `/blog/<slug>/`.
  - `render_markdown` converts Markdown (heading/list/bold) and **strips a
    `<script>` payload**; single newlines become `<br>`.
- **View:**
  - `GET /blog/<slug>/` → 200, contains the post title and rendered body.
  - `GET /blog/does-not-exist/` → 404.
  - `GET /blog/` → 200, lists posts with links to their absolute URLs; pagination works.
  - `view_count` increments by 1 on a detail GET.

## Known tradeoffs

- Crawler hits on detail pages inflate `view_count` (acceptable; bot-filtering can
  come later).
- New tests live alongside the repo's existing (separately broken) blog tests;
  this work does not fix the pre-existing failures and must not depend on them.
