"""
Preservation Property Tests — Property 2: Meaningful Content Unchanged

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

These tests verify that for all content strings that do NOT match the bug condition
(no standalone digit-only lines, no exact known header matches, no duplicate titles,
no 3+ blank line runs), `clean_lesson_text(content, title)` returns the content
unchanged (identity function for non-buggy inputs).

Observation-first methodology:
- Lines with digits in meaningful context (e.g. "1 cm = 10 mm", "2 + 3 = 5", "Bài 30")
  must pass through unchanged
- Lines longer than short headers containing header keywords as substrings
  (e.g. "Khám phá thế giới xung quanh") must pass through unchanged
- Single blank lines between paragraphs remain unchanged
- Content ordering across pages is preserved
"""
import re

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.page_split import clean_lesson_text


# --- Constants matching the design spec ---

KNOWN_SECTION_HEADERS = {
    "khám phá",
    "luyện tập",
    "chủ đề",
    "hoạt động hoạt động",
    "luyện tập luyện tập",
    "khởi động",
    "ghi nhớ",
    "vận dụng",
    "thực hành",
}


# --- Helper: check if content contains any bug condition ---

def _contains_artifacts(content: str, title: str) -> bool:
    """Return True if content contains any bug condition artifacts."""
    lines = content.splitlines()

    # Check for standalone digit-only lines
    for line in lines:
        stripped = line.strip()
        if stripped and re.match(r"^\d+$", stripped):
            return True

    # Check for known section headers (exact match, case-insensitive)
    for line in lines:
        stripped = line.strip()
        if stripped and stripped.lower() in KNOWN_SECTION_HEADERS:
            return True
        # Check "Số" pattern
        if stripped and re.match(r"^Số\s?\d*$", stripped):
            return True

    # Check for duplicate title
    title_lower = title.strip().lower()
    for line in lines:
        if line.strip().lower() == title_lower:
            return True

    # Check for 3+ consecutive blank lines
    blank_run = 0
    for line in lines:
        if line.strip() == "":
            blank_run += 1
            if blank_run >= 3:
                return True
        else:
            blank_run = 0

    return False


# --- Strategies for generating artifact-free content ---

# Vietnamese text characters for generating realistic content
_viet_words = st.sampled_from([
    "hình", "vuông", "tam", "giác", "cạnh", "bằng", "nhau", "viết",
    "số", "thích", "hợp", "vào", "ô", "trống", "quan", "sát",
    "trả", "lời", "câu", "hỏi", "tính", "giá", "trị", "biểu",
    "thức", "sau", "phép", "cộng", "trừ", "nhân", "chia", "trong",
    "phạm", "vi", "em", "hãy", "đọc", "bài", "tập", "làm",
    "theo", "mẫu", "cho", "biết", "kết", "quả", "đúng", "sai",
])

# Strategy: meaningful content lines with digits in context (math expressions)
_math_content_lines = st.sampled_from([
    "1 cm = 10 mm",
    "2 + 3 = 5",
    "100 - 50 = 50",
    "Bài 30: Phép cộng trong phạm vi 10 000",
    "a) 234 + 567 = 801",
    "b) 1000 - 999 = 1",
    "Số 1 000 gồm 1 nghìn, 0 trăm, 0 chục, 0 đơn vị.",
    "Hình chữ nhật có chiều dài 5 cm, chiều rộng 3 cm.",
    "Chu vi = (5 + 3) × 2 = 16 cm",
    "Diện tích = 5 × 3 = 15 cm²",
    "Bảng nhân 6: 6 × 1 = 6, 6 × 2 = 12, 6 × 3 = 18",
    "Có 24 học sinh chia đều thành 4 nhóm.",
])

# Strategy: lines containing header keywords as substrings in longer text
_lines_with_header_keywords = st.sampled_from([
    "Khám phá thế giới xung quanh bằng toán học",
    "Em hãy luyện tập thêm ở nhà để nắm vững kiến thức",
    "Chủ đề này giúp em hiểu về phép nhân",
    "Hoạt động nhóm: thảo luận và trình bày kết quả",
    "Sau khi khởi động xong, em hãy làm bài tập sau",
    "Ghi nhớ các công thức đã học trong bài",
    "Vận dụng kiến thức vào thực tế cuộc sống",
    "Thực hành đo chiều dài bằng thước kẻ",
    "Bài luyện tập chung về phép cộng và phép trừ",
])

# Strategy: plain Vietnamese text lines (no artifacts)
_plain_text_lines = st.one_of(
    # Generated sentences from word lists
    st.lists(_viet_words, min_size=3, max_size=8).map(lambda ws: " ".join(ws).capitalize()),
    # Fixed realistic content
    st.sampled_from([
        "Tính giá trị biểu thức sau:",
        "Hình vuông có 4 cạnh bằng nhau.",
        "Viết số thích hợp vào ô trống:",
        "Em hãy quan sát hình vẽ và trả lời câu hỏi.",
        "Đặt tính rồi tính:",
        "Giải bài toán theo tóm tắt sau:",
        "Nối mỗi phép tính với kết quả đúng:",
        "Điền dấu >, <, = vào chỗ chấm:",
        "Tìm x biết:",
        "Một hình chữ nhật có chiều dài gấp đôi chiều rộng.",
    ]),
)

# Strategy: lesson titles that won't appear in generated content
_safe_titles = st.sampled_from([
    "Ôn tập các số đến 1 000",
    "Phép cộng trong phạm vi 10 000",
    "Bảng nhân 6",
    "Chu vi hình tam giác",
    "Đơn vị đo độ dài",
    "Phép chia hết và phép chia có dư",
    "Góc vuông, góc không vuông",
])


# --- Property Tests ---

@given(
    content_lines=st.lists(
        st.one_of(_plain_text_lines, _math_content_lines, _lines_with_header_keywords),
        min_size=1,
        max_size=10,
    ),
    title=_safe_titles,
)
@settings(max_examples=200, deadline=None)
def test_preservation_identity_for_clean_content(content_lines, title):
    """
    **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

    Property: For all content strings that do NOT match the bug condition,
    clean_lesson_text(content, title) returns the content unchanged
    (identity function for non-buggy inputs).

    Generates random lesson content without artifacts and verifies
    clean_lesson_text() is identity.
    """
    # Join lines with single blank lines (normal paragraph spacing)
    content = "\n\n".join(content_lines)

    # Precondition: content must not contain any artifacts
    assume(not _contains_artifacts(content, title))

    # Act
    result = clean_lesson_text(content, title)

    # Assert: identity — content is returned unchanged
    assert result == content, (
        f"clean_lesson_text() modified content that has no artifacts.\n"
        f"Input:  {content!r}\n"
        f"Output: {result!r}"
    )


@given(
    math_lines=st.lists(_math_content_lines, min_size=1, max_size=5),
    title=_safe_titles,
)
@settings(max_examples=100, deadline=None)
def test_preservation_digits_in_context_survive(math_lines, title):
    """
    **Validates: Requirements 3.1**

    Property: Lines with digits embedded in text (math expressions, numbered
    exercises like "1 cm = 10 mm", "2 + 3 = 5", "Bài 30") survive cleaning
    unchanged.
    """
    content = "\n".join(math_lines)

    # Precondition: none of these lines should be standalone digits
    assume(not _contains_artifacts(content, title))

    # Act
    result = clean_lesson_text(content, title)

    # Assert: all math content lines are preserved
    assert result == content, (
        f"Math content was modified by clean_lesson_text().\n"
        f"Input:  {content!r}\n"
        f"Output: {result!r}"
    )


@given(
    keyword_lines=st.lists(_lines_with_header_keywords, min_size=1, max_size=5),
    title=_safe_titles,
)
@settings(max_examples=100, deadline=None)
def test_preservation_header_keywords_in_longer_text_survive(keyword_lines, title):
    """
    **Validates: Requirements 3.2**

    Property: Lines containing header keywords as substrings in longer text
    (e.g. "Khám phá thế giới xung quanh") survive cleaning unchanged.
    These are NOT exact header matches and must be preserved.
    """
    content = "\n".join(keyword_lines)

    # Precondition: these lines are longer than exact headers
    assume(not _contains_artifacts(content, title))

    # Act
    result = clean_lesson_text(content, title)

    # Assert: all lines with header keywords as substrings are preserved
    assert result == content, (
        f"Lines with header keywords as substrings were modified.\n"
        f"Input:  {content!r}\n"
        f"Output: {result!r}"
    )


@given(
    paragraphs=st.lists(_plain_text_lines, min_size=2, max_size=6),
    title=_safe_titles,
)
@settings(max_examples=100, deadline=None)
def test_preservation_single_blank_lines_unchanged(paragraphs, title):
    """
    **Validates: Requirements 3.2**

    Property: Single blank lines between paragraphs remain unchanged.
    Normal paragraph spacing (one blank line) must not be collapsed or removed.
    """
    # Join with exactly one blank line between paragraphs
    content = "\n\n".join(paragraphs)

    # Precondition: no artifacts
    assume(not _contains_artifacts(content, title))

    # Act
    result = clean_lesson_text(content, title)

    # Assert: spacing is preserved exactly
    assert result == content, (
        f"Single blank lines between paragraphs were modified.\n"
        f"Input:  {content!r}\n"
        f"Output: {result!r}"
    )


@given(
    page1_lines=st.lists(_plain_text_lines, min_size=1, max_size=4),
    page2_lines=st.lists(_plain_text_lines, min_size=1, max_size=4),
    page3_lines=st.lists(_plain_text_lines, min_size=1, max_size=4),
    title=_safe_titles,
)
@settings(max_examples=100, deadline=None)
def test_preservation_content_ordering_across_pages(
    page1_lines, page2_lines, page3_lines, title
):
    """
    **Validates: Requirements 3.5**

    Property: Content ordering across pages is preserved. When multiple pages
    of content are joined, the order of lines must remain the same after cleaning.
    """
    # Simulate multi-page join (pages separated by double newline)
    page1 = "\n".join(page1_lines)
    page2 = "\n".join(page2_lines)
    page3 = "\n".join(page3_lines)
    content = f"{page1}\n\n{page2}\n\n{page3}"

    # Precondition: no artifacts
    assume(not _contains_artifacts(content, title))

    # Act
    result = clean_lesson_text(content, title)

    # Assert: content unchanged (ordering preserved)
    assert result == content, (
        f"Content ordering was changed by clean_lesson_text().\n"
        f"Input:  {content!r}\n"
        f"Output: {result!r}"
    )
