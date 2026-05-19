"""
Bug Condition Exploration Test — Property 1: Layout Artifacts Present in Output

**Validates: Requirements 2.1, 2.2, 2.3, 2.4**

This test is EXPECTED TO FAIL on unfixed code because `clean_lesson_text()` does not
exist yet in `src/page_split.py`. The failure (ImportError or assertion failure)
confirms the bug exists — no cleaning logic is present in the pipeline.

The test generates content containing known layout artifacts and asserts that
`clean_lesson_text(content, title)` removes all of them.
"""
import re

from hypothesis import given, settings, assume
from hypothesis import strategies as st


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

# --- Strategies for generating artifact-laden content ---

# Strategy: standalone page numbers (lines matching ^\d+$)
page_number_lines = st.integers(min_value=1, max_value=999).map(str)

# Strategy: known section headers (various casings)
section_header_lines = st.sampled_from(list(KNOWN_SECTION_HEADERS)).flatmap(
    lambda h: st.sampled_from([h, h.upper(), h.title(), h.capitalize()])
)

# Strategy: "Số" pattern lines matching ^Số\s?\d*$
so_pattern_lines = st.one_of(
    st.just("Số"),
    st.integers(min_value=1, max_value=99).map(lambda n: f"Số {n}"),
    st.integers(min_value=1, max_value=99).map(lambda n: f"Số{n}"),
)

# Strategy: meaningful content lines (should NOT be removed)
meaningful_content = st.sampled_from([
    "Tính giá trị biểu thức sau:",
    "1 cm = 10 mm",
    "Bài 30: Phép cộng trong phạm vi 10 000",
    "a) 2 + 3 = 5",
    "Hình vuông có 4 cạnh bằng nhau.",
    "Viết số thích hợp vào ô trống:",
    "Em hãy quan sát hình vẽ và trả lời câu hỏi.",
    "Số 1 000 gồm 1 nghìn, 0 trăm, 0 chục, 0 đơn vị.",
])

# Strategy: lesson titles
lesson_titles = st.sampled_from([
    "Ôn tập các số đến 1 000",
    "Phép cộng trong phạm vi 10 000",
    "Bảng nhân 6",
    "Chu vi hình tam giác",
    "Luyện tập chung",
])


@given(
    page_numbers=st.lists(page_number_lines, min_size=1, max_size=3),
    headers=st.lists(section_header_lines, min_size=1, max_size=2),
    so_lines=st.lists(so_pattern_lines, min_size=0, max_size=2),
    content_lines=st.lists(meaningful_content, min_size=2, max_size=5),
    title=lesson_titles,
)
@settings(max_examples=50, deadline=None)
def test_bug_condition_artifacts_removed(
    page_numbers, headers, so_lines, content_lines, title
):
    r"""
    **Validates: Requirements 2.1, 2.2, 2.3, 2.4**

    Property: For any content containing layout artifacts (standalone page numbers,
    known section headers, "Số" patterns, and duplicate lesson titles),
    clean_lesson_text() SHALL remove all artifacts from the output.

    This test is scoped to concrete failing cases — content with standalone page
    numbers (^\d+$), known section headers, duplicate lesson titles, and excessive
    blank lines.
    """
    # Import here so the test file itself can be collected by pytest
    # The ImportError when function doesn't exist confirms the bug
    from src.page_split import clean_lesson_text

    # Build content with artifacts interspersed with real content
    lines = []
    # Add some real content
    lines.append(content_lines[0])
    # Add page numbers as artifacts
    for pn in page_numbers:
        lines.append(pn)
    # Add more real content
    lines.append(content_lines[1])
    # Add section headers as artifacts
    for h in headers:
        lines.append(h)
    # Add "Số" pattern lines
    for s in so_lines:
        lines.append(s)
    # Add remaining content
    for c in content_lines[2:]:
        lines.append(c)
    # Add duplicate title (case-insensitive variant)
    lines.append(title)

    # Join with some excessive blank lines (3+ consecutive)
    content = "\n".join(lines[:3]) + "\n\n\n\n" + "\n".join(lines[3:])

    # --- Act ---
    result = clean_lesson_text(content, title)

    # --- Assert: All artifacts are removed ---

    result_lines = result.splitlines()

    # 2.1: No standalone digit-only lines remain
    for line in result_lines:
        stripped = line.strip()
        if stripped:
            assert not re.match(
                r"^\d+$", stripped
            ), f"Standalone page number '{stripped}' was not removed"

    # 2.2: No known section header lines remain
    for line in result_lines:
        stripped = line.strip()
        if stripped:
            assert (
                stripped.lower() not in KNOWN_SECTION_HEADERS
            ), f"Known section header '{stripped}' was not removed"
            # Also check "Số" pattern
            assert not re.match(
                r"^S\u1ed1\s?\d*$", stripped
            ), f"'Số' pattern line '{stripped}' was not removed"

    # 2.3: Title does not appear duplicated in result body
    title_lower = title.strip().lower()
    title_occurrences = sum(
        1 for line in result_lines if line.strip().lower() == title_lower
    )
    assert (
        title_occurrences == 0
    ), f"Duplicate title '{title}' still present in result ({title_occurrences} occurrences)"

    # 2.4: No runs of 3+ consecutive blank lines remain
    blank_run = 0
    for line in result_lines:
        if line.strip() == "":
            blank_run += 1
            assert (
                blank_run < 3
            ), "Run of 3+ consecutive blank lines found in result"
        else:
            blank_run = 0
