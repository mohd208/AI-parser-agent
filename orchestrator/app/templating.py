from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    undefined=StrictUndefined,
    # trim_blocks/lstrip_blocks deliberately left off: the workflow templates
    # use {% raw %}...{% endraw %} inline (to emit GitHub Actions' ${{ }})
    # mid-line, and trim_blocks eats the newline right after {% endraw %},
    # silently merging the following line into the same YAML line.
    keep_trailing_newline=True,
)


def render(template_rel_path: str, **context) -> str:
    template = _env.get_template(template_rel_path)
    return template.render(**context)


def write_rendered(template_rel_path: str, dest: Path, **context) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render(template_rel_path, **context), encoding="utf-8", newline="\n")
