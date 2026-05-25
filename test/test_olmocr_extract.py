from __future__ import annotations

from pathlib import Path

from src.b1_extract import olmocr_extract


def test_extract_pdf_via_olmocr_to_files_writes_raw_outputs(tmp_path: Path, monkeypatch) -> None:
    def fake_extract_pdf_via_olmocr(*args, **kwargs):
        return "MỤC LỤC\n\n# Heading\n\nNội dung"

    monkeypatch.setattr(olmocr_extract, "extract_pdf_via_olmocr", fake_extract_pdf_via_olmocr)

    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    labels_path = tmp_path / "labels.json"
    labels_path.write_text('{"labels_to_heading": {}}', encoding="utf-8")

    result = olmocr_extract.extract_pdf_via_olmocr_to_files(
        pdf_path,
        out_dir=tmp_path / "out",
        path_labels_heading=labels_path,
    )

    assert result is not None
    assert (tmp_path / "out" / "raw_text.txt").exists()
    assert (tmp_path / "out" / "raw_with_headings.txt").exists()
