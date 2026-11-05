# Personal blog

A small blog for one author. Readers read posts and leave comments. No accounts and no login: the author's actions are open (the blog runs on a private machine).

## Features
- Write a post: title (1 to 120 characters), body (not empty), tags (optional list, at most 5, each tag made of lowercase letters and digits only), and `published` (boolean, false by default: a new post is a draft).
- Each post has a **slug** made from its title: lowercase, accents removed (`é` becomes `e`), every run of characters that are not letters or digits becomes a single hyphen, no hyphen at the start or the end. When the slug is already used, add `-2`, then `-3`, and so on. Editing a post never changes its slug.
- List the published posts, newest first. `?tag=python` keeps only the posts with that tag. Drafts are never in this list.
- Read a post by slug. A draft is not public: reading it answers 404.
- List the drafts (for the author), newest first.
- Edit a post (title, body, tags) and publish a draft.
- Delete a post: its comments go with it, and its slug becomes free again.
- Readers comment on a published post: author (1 to 50 characters) and body (1 to 1000 characters). Comments are listed oldest first. A draft cannot be commented.

## Screens
- A home page with the published posts and a tag filter.
- A page for one post with its comments and a comment form.
- A simple page for the author to write, publish and delete posts.

## Data model
- Post: slug, title, body, tags (list of text), published (boolean), created_at (ISO 8601 date and time), comment_count (integer).
- Comment: author, body, created_at.

## Constraints
- FastAPI backend, data kept on disk (it survives a restart).
- Usable on a phone screen.

## Out of scope
- Accounts, images, Markdown rendering, search, RSS, notifications.

## Acceptance criteria
- `GET /api/health` answers 200.
- `POST /api/posts` creates a post (201, the post as JSON with all its fields); invalid fields answer 422.
- `GET /api/posts` (published, newest first, optional `tag`), `GET /api/drafts`, `GET /api/posts/{slug}` (404 for a draft or an unknown slug).
- `PATCH /api/posts/{slug}` edits title, body, tags and `published` (404 if unknown). `DELETE /api/posts/{slug}` answers 204 (404 if unknown).
- `POST /api/posts/{slug}/comments` answers 201 (404 for an unknown or draft post, 422 for invalid fields); `GET /api/posts/{slug}/comments` lists them oldest first.
