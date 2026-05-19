from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("缺少依赖 PyYAML，请先运行：pip install PyYAML", file=sys.stderr)
    raise


ROOT_DIR = Path(__file__).resolve().parent

PAGE_NAME_KEY = "页面名称"
MODULES_KEY = "包含模块"
ELEMENTS_KEY = "包含元素"


@dataclass(frozen=True)
class ConvertConfig:
    input_dir: Path
    output_dir: Path
    image_map_file: Path
    css_file: Path
    overwrite: bool = False


def parse_args() -> ConvertConfig:
    parser = argparse.ArgumentParser(description="批量将产品说明书 YAML 转换为 HTML。")
    parser.add_argument(
        "--input-dir",
        default=ROOT_DIR / "input_yaml",
        type=Path,
        help="YAML 输入目录，默认：input_yaml/",
    )
    parser.add_argument(
        "--output-dir",
        default=ROOT_DIR / "output",
        type=Path,
        help="HTML 输出目录，默认：output/",
    )
    parser.add_argument(
        "--image-map",
        default=ROOT_DIR / "image-map.json",
        type=Path,
        help="图片映射 JSON 文件，默认：image-map.json",
    )
    parser.add_argument(
        "--css",
        default=ROOT_DIR / "styles.css",
        type=Path,
        help="生成 HTML 引用的 CSS 文件，默认：styles.css",
    )
    parser.add_argument(
        "--overwrite",
        "--force",
        action="store_true",
        dest="overwrite",
        help="当输出 HTML 已存在时强制覆盖；默认跳过已有文件。",
    )
    args = parser.parse_args()

    return ConvertConfig(
        input_dir=args.input_dir.resolve(),
        output_dir=args.output_dir.resolve(),
        image_map_file=args.image_map.resolve(),
        css_file=args.css.resolve(),
        overwrite=args.overwrite,
    )


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        print(f"未找到图片映射文件：{path}，将全部使用空映射。", file=sys.stderr)
        return {}

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        print(f"图片映射文件顶层不是对象：{path}，将全部使用空映射。", file=sys.stderr)
        return {}

    return data


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def to_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def extract_pages(data: Any) -> tuple[str, list[dict[str, Any]]]:
    if isinstance(data, list):
        return "产品说明书页面结构", [item for item in data if isinstance(item, dict)]

    if isinstance(data, dict):
        for title, value in data.items():
            if isinstance(value, list):
                pages = [item for item in value if isinstance(item, dict)]
                if pages:
                    return str(title), pages

        if PAGE_NAME_KEY in data:
            return "产品说明书页面结构", [data]

    return "产品说明书页面结构", []


def html_relpath(target: Path, html_file: Path) -> str:
    try:
        return Path(os.path.relpath(target, html_file.parent)).as_posix()
    except ValueError:
        return target.as_posix()


def resolve_asset(asset: str, project_root: Path) -> Path:
    raw = Path(asset.replace("\\", "/"))
    candidate = raw if raw.is_absolute() else project_root / raw

    if candidate.exists():
        return candidate

    parent = candidate.parent
    if parent.exists():
        target_name = candidate.name.lower()
        for child in parent.iterdir():
            if child.name.lower() == target_name:
                return child

    return candidate


def image_map_for_file(image_map: dict[str, Any], yaml_file: Path) -> dict[str, Any]:
    for key in (yaml_file.stem, yaml_file.name):
        value = image_map.get(key)
        if isinstance(value, dict):
            return value
    return {}


def default_images(image_map: dict[str, Any]) -> list[str]:
    return [text(item) for item in to_list(image_map.get("default")) if text(item)]


def images_for_page(
    image_map: dict[str, Any],
    yaml_file: Path,
    page_name: str,
) -> tuple[list[str], bool]:
    page_map = image_map_for_file(image_map, yaml_file)
    mapped_images = page_map.get(page_name)
    if mapped_images is None:
        for key, value in page_map.items():
            if text(key) == page_name:
                mapped_images = value
                break

    images = [text(item) for item in to_list(mapped_images) if text(item)]

    if images:
        return images, False

    return default_images(image_map), True


def scalar_to_html(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    return escape(str(value))


def render_value(value: Any) -> str:
    if isinstance(value, dict):
        return render_meta_list(value)
    if isinstance(value, list):
        items = "".join(f"<li>{render_value(item)}</li>" for item in value)
        return f'<ul class="plain-list">{items}</ul>'
    return scalar_to_html(value)


def render_meta_list(data: dict[str, Any], skip_keys: set[str] | None = None) -> str:
    skip_keys = skip_keys or set()
    rows: list[str] = []

    for key, value in data.items():
        if key in skip_keys:
            continue
        rows.append(
            '<div class="meta-row">'
            f"<dt>{escape(str(key))}</dt>"
            f"<dd>{render_value(value)}</dd>"
            "</div>"
        )

    if not rows:
        return ""

    return '<dl class="meta-list">' + "".join(rows) + "</dl>"


def render_elements(elements: Any) -> str:
    items: list[str] = []

    for index, element in enumerate(to_list(elements), start=1):
        if isinstance(element, dict):
            element_name = text(element.get("元素名称")) or f"元素 {index}"
            element_type = text(element.get("元素类型"))
            type_pill = f'<span class="type-pill">{escape(element_type)}</span>' if element_type else ""
            fields = render_meta_list(element)
            items.append(
                '<li class="element-item">'
                "<details>"
                f'<summary class="element-title"><span>{escape(element_name)}</span>{type_pill}</summary>'
                f"{fields}"
                "</details>"
                "</li>"
            )
        else:
            items.append(
                '<li class="element-item">'
                "<details>"
                f'<summary class="element-title"><span>元素 {index}</span></summary>'
                f'<p class="muted">{scalar_to_html(element)}</p>'
                "</details>"
                "</li>"
            )

    if not items:
        return '<p class="muted">暂无元素</p>'

    return '<ul class="element-list">' + "".join(items) + "</ul>"


def render_modules(modules: Any) -> str:
    cards: list[str] = []

    for index, module in enumerate(to_list(modules), start=1):
        if isinstance(module, dict):
            module_name = text(module.get("模块名称")) or f"模块 {index}"
            module_type = text(module.get("模块类型"))
            type_pill = f'<span class="type-pill">{escape(module_type)}</span>' if module_type else ""
            module_meta = render_meta_list(module, skip_keys={ELEMENTS_KEY})
            elements = render_elements(module.get(ELEMENTS_KEY))
            cards.append(
                '<details class="module-card" open>'
                f'<summary class="module-heading"><h3>{escape(module_name)}</h3>{type_pill}</summary>'
                f"{module_meta}"
                f'<div class="element-section"><h4>包含元素</h4>{elements}</div>'
                "</details>"
            )
        else:
            cards.append(
                '<details class="module-card" open>'
                f'<summary class="module-heading"><h3>模块 {index}</h3></summary>'
                f'<p class="muted">{scalar_to_html(module)}</p>'
                "</details>"
            )

    if not cards:
        return '<p class="muted">暂无模块</p>'

    return "".join(cards)


def render_images(
    images: list[str],
    is_default: bool,
    html_file: Path,
    project_root: Path,
) -> str:
    if not images:
        return '<div class="empty-image-slot">未找到图片，也未配置 default 占位图</div>'

    figures: list[str] = []
    for image in images:
        source = html_relpath(resolve_asset(image, project_root), html_file)
        classes = "image-card is-placeholder" if is_default else "image-card"
        alt = "default placeholder" if is_default else Path(image).name
        figures.append(
            f'<figure class="{classes}">'
            f'<img src="{escape(source)}" alt="{escape(alt)}" loading="lazy">'
            f"<figcaption>{escape(image)}</figcaption>"
            "</figure>"
        )

    return '<div class="image-grid">' + "".join(figures) + "</div>"


def render_page(
    yaml_file: Path,
    html_file: Path,
    image_map: dict[str, Any],
    page: dict[str, Any],
    index: int,
    project_root: Path,
) -> str:
    page_name = text(page.get(PAGE_NAME_KEY)) or f"页面 {index}"
    images, is_default = images_for_page(image_map, yaml_file, page_name)
    badge_text = "default" if is_default else f"{len(images)} 张图"
    page_meta = render_meta_list(page, skip_keys={MODULES_KEY})
    modules = render_modules(page.get(MODULES_KEY))
    image_grid = render_images(images, is_default, html_file, project_root)

    return (
        '<article class="page-card">'
        '<header class="page-card-header">'
        f"<span>Page {index}</span>"
        f"<h1>{escape(page_name)}</h1>"
        f'<small class="muted">{escape(badge_text)}</small>'
        "</header>"
        '<div class="page-layout">'
        '<section class="structure-panel">'
        "<h2>页面结构</h2>"
        f"{page_meta}"
        '<div class="module-section">'
        "<h2>模块与元素</h2>"
        f"{modules}"
        "</div>"
        "</section>"
        '<section class="visual-panel">'
        '<div class="visual-heading"><h2>页面图片</h2></div>'
        f"{image_grid}"
        "</section>"
        "</div>"
        "</article>"
    )


def render_document(
    yaml_file: Path,
    html_file: Path,
    title: str,
    pages: list[dict[str, Any]],
    image_map: dict[str, Any],
    config: ConvertConfig,
) -> str:
    css_href = html_relpath(config.css_file, html_file)
    project_root = config.image_map_file.parent
    page_cards = [
        render_page(yaml_file, html_file, image_map, page, index, project_root)
        for index, page in enumerate(pages, start=1)
    ]

    if not page_cards:
        page_cards = ['<article class="page-card"><div class="empty-image-slot">未解析到页面数据</div></article>']

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(yaml_file.stem)} - {escape(title)}</title>
  <link rel="stylesheet" href="{escape(css_href)}">
</head>
<body>
  <main class="document-shell">
    <header class="document-header">
      <div>
        <h1>{escape(title)}</h1>
        <p>{escape(yaml_file.name)}</p>
      </div>
      <p>共 {len(pages)} 个页面</p>
    </header>
    {"".join(page_cards)}
  </main>
</body>
</html>
"""


def convert_file(
    yaml_file: Path,
    image_map: dict[str, Any],
    config: ConvertConfig,
) -> tuple[str, Path]:
    html_file = config.output_dir / f"{yaml_file.stem}.html"

    if html_file.exists() and not config.overwrite:
        return "skipped", html_file

    data = load_yaml(yaml_file)
    title, pages = extract_pages(data)
    html = render_document(yaml_file, html_file, title, pages, image_map, config)
    html_file.write_text(html, encoding="utf-8")
    return "written", html_file


def find_yaml_files(input_dir: Path) -> list[Path]:
    yaml_files = [*input_dir.glob("*.yaml"), *input_dir.glob("*.yml")]
    return sorted(set(path.resolve() for path in yaml_files))


def display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT_DIR).as_posix()
    except ValueError:
        return path.as_posix()


def main() -> int:
    config = parse_args()

    if not config.input_dir.exists():
        print(f"找不到输入目录：{config.input_dir}", file=sys.stderr)
        return 1

    config.output_dir.mkdir(parents=True, exist_ok=True)
    image_map = load_json(config.image_map_file)
    yaml_files = find_yaml_files(config.input_dir)

    if not yaml_files:
        print(f"未在 {config.input_dir} 中找到 YAML 文件")
        return 0

    written_count = 0
    skipped_count = 0

    for yaml_file in yaml_files:
        status, html_file = convert_file(yaml_file, image_map, config)
        relative_html = display_path(html_file)

        if status == "skipped":
            skipped_count += 1
            print(f"已跳过：{relative_html}（文件已存在，使用 --overwrite 可覆盖）")
        else:
            written_count += 1
            print(f"已生成：{relative_html}")

    print(f"完成：生成 {written_count} 个，跳过 {skipped_count} 个。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
