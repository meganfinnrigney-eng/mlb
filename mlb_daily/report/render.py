"""Renders report data into the static HTML page via Jinja2."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATE_DIR = Path(__file__).resolve().parent


def _env():
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )


def render_report(report_data, generated_at, inline_font_css=""):
    """Full standalone page for docs/ (GitHub Pages). Wraps the same content
    used for the Claude Artifact fragment in a <!doctype html><html>...
    shell - the fragment's own leading <title>/<style> tags land in an
    HTML5 "implied head" ahead of the body content, same as how the
    Artifact tool itself wraps this file when publishing it directly."""
    fragment = _env().get_template("artifact_template.html").render(
        r=report_data, generated_at=generated_at, inline_font_css=inline_font_css
    )
    return f'<!doctype html>\n<html lang="en">\n{fragment}\n</html>\n'


def render_artifact_fragment(report_data, generated_at, inline_font_css=""):
    """Content-only fragment (no <html>/<head>/<body>) for publishing as a
    Claude Artifact - see mlb_daily/report/artifact_template.html."""
    return _env().get_template("artifact_template.html").render(
        r=report_data, generated_at=generated_at, inline_font_css=inline_font_css
    )
