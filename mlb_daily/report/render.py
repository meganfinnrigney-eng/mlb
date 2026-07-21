"""Renders report data into the static HTML page via Jinja2."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATE_DIR = Path(__file__).resolve().parent


def render_report(report_data, generated_at):
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("template.html")
    return template.render(r=report_data, generated_at=generated_at)
