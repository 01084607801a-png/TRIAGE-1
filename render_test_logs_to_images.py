from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import textwrap


def render_log(log_path: Path, out_dir: Path):
    if not log_path.exists():
        return []

    out_dir.mkdir(parents=True, exist_ok=True)

    font = ImageFont.load_default()
    page_w, page_h = 1800, 2200
    margin = 40
    line_h = 22
    max_chars = 140

    text = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    wrapped = [f"FILE: {log_path.as_posix()}", ""]

    for ln in text:
        if ln.strip() == "":
            wrapped.append("")
            continue
        parts = textwrap.wrap(
            ln,
            width=max_chars,
            break_long_words=True,
            break_on_hyphens=False,
        )
        wrapped.extend(parts if parts else [""])

    lines_per_page = (page_h - margin * 2) // line_h
    pages = []

    for i in range(0, len(wrapped), lines_per_page):
        chunk = wrapped[i : i + lines_per_page]
        img = Image.new("RGB", (page_w, page_h), "white")
        draw = ImageDraw.Draw(img)

        draw.text((margin, 10), "TRIAGE-1 Test Result Snapshot", fill="black", font=font)
        y = margin
        for line in chunk:
            draw.text((margin, y), line, fill="black", font=font)
            y += line_h

        page_index = i // lines_per_page + 1
        out_file = out_dir / f"{log_path.stem}_page_{page_index:02d}.png"
        img.save(out_file)
        pages.append(out_file)

    return pages


def main():
    project = Path(__file__).parent
    out_dir = project / "assets" / "test_results"
    logs = [
        project / "logs" / "test_multi_injury.log",
        project / "test_multi_injury_latest.log",
    ]

    all_pages = []
    for log in logs:
        all_pages.extend(render_log(log, out_dir))

    print(f"CREATED {len(all_pages)}")
    for p in all_pages:
        print(p.as_posix())


if __name__ == "__main__":
    main()
