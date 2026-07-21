"""Renders report data into the static HTML page via Jinja2."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATE_DIR = Path(__file__).resolve().parent


def _env():
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )


def render_report(report_data, generated_at):
    return _env().get_template("template.html").render(r=report_data, generated_at=generated_at)


def render_artifact_fragment(report_data, generated_at):
    """Content-only fragment (no <html>/<head>/<body>) for publishing as a
    Claude Artifact - see mlb_daily/report/artifact_template.html."""
    return _env().get_template("artifact_template.html").render(r=report_data, generated_at=generated_at)
