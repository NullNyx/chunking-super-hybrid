from __future__ import annotations

from src.b5_export.page_split import parse_toc_from_text


def test_parse_toc_recovers_broken_vietnamese_glyphs() -> None:
    toc_text = """MỤC LỤC

| BÀI    | NỘI DUNG                                   |   Trang |
|--------|--------------------------------------------|---------|
|        | CHÀO EM VÀO L/ochoasacp 1                  |       6 |
| BÀI 1  | A a                                        |      14 |
| BÀI 5  | Ôn t/abthnangp và k/ebthhoi chuy/ebthnangn |      22 |
| BÀI 8  | D d /dhoa /dth                             |      28 |
| BÀI 9  | /ochoa /octh                               |      30 |
| BÀI 13 | U u /uchoa /ucth                           |      38 |
| BÀI 21 | R r S s                                    |      54 |
"""

    entries = parse_toc_from_text(toc_text)

    assert [entry.lesson_num for entry in entries] == [1, 5, 8, 9, 13, 21]
    assert entries[0].title == "A a"
    assert entries[1].title == "Ôn tập và kể chuyện"
    assert entries[2].title == "D d đ đ"
    assert entries[3].title == "ơ ơ"
    assert entries[4].title == "U u ư ư"
    assert entries[-1].start_page == 54


def test_parse_toc_extracts_both_columns_from_single_line_table() -> None:
    toc_text = (
        "| BÀI 1 | A a | 14 | BÀI 22 | T t Tr tr | 56 |\n"
        "| BÀI 2 | B b ` | 16 | BÀI 23 | Th th ia | 58 |"
    )

    entries = parse_toc_from_text(toc_text)

    assert [(entry.lesson_num, entry.title, entry.start_page) for entry in entries] == [
        (1, "A a", 14),
        (22, "T t Tr tr", 56),
        (2, "B b `", 16),
        (23, "Th th ia", 58),
    ]
