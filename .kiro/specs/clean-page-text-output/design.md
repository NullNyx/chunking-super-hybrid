# Clean Page Text Output Bugfix Design

## Overview

The `split_pdf_to_lessons()` function in `src/page_split.py` extracts text from PDF pages using pypdfium2 and writes per-lesson `.txt` files. The extracted text currently includes layout artifacts from the PDF — standalone page numbers, repeated section headers/footers, duplicate lesson titles, and excessive blank lines at page boundaries. This fix adds a text cleaning/post-processing step between extracting page text and writing the final output, removing these artifacts while preserving all meaningful lesson content.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug — when extracted PDF text contains layout artifacts (standalone page numbers, repeated headers/footers, duplicate titles, or excessive blank lines)
- **Property (P)**: The desired behavior — output text contains only meaningful lesson content with clean formatting
- **Preservation**: Existing behavior that must remain unchanged — lines with digits in meaningful context, actual lesson content, CRLF encoding, header format, and page ordering
- **split_pdf_to_lessons()**: The function in `src/page_split.py` that orchestrates PDF splitting and writes per-lesson `.txt` files
- **extract_pages_text()**: The function in `src/page_split.py` that extracts raw text per page using pypdfium2
- **Layout artifacts**: Non-content elements from PDF rendering — page numbers, section headers/footers, repeated titles
- **Section headers/footers**: Repeated short lines like "Khám phá", "luyện tập", "Chủ đề" that appear on multiple pages as navigation aids

## Bug Details

### Bug Condition

The bug manifests when pypdfium2 extracts text from PDF pages that contain layout artifacts. The `split_by_toc_pages()` function joins page texts with `"\n\n"` separators and passes the raw content directly to `split_pdf_to_lessons()`, which writes it without any cleaning. The artifacts are:
1. Standalone page numbers (lines with only digits)
2. Repeated section headers/footers (short Vietnamese navigation labels)
3. Duplicate lesson titles (title already injected as header)
4. Excessive consecutive blank lines from page joins

**Formal Specification:**
```
FUNCTION isBugCondition(line, context)
  INPUT: line of type str, context of type LessonContext (title, all_lines)
  OUTPUT: boolean
  
  // Condition 1: Standalone page number
  IF line.strip() matches regex ^\d+$ THEN
    RETURN TRUE
  END IF
  
  // Condition 2: Repeated section header/footer
  known_headers = {"khám phá", "luyện tập", "chủ đề", "hoạt động hoạt động",
                   "luyện tập luyện tập", "khởi động", "ghi nhớ", "vận dụng",
                   "thực hành"}
  IF normalize(line.strip()) IN known_headers THEN
    RETURN TRUE
  END IF
  IF line.strip() matches regex ^Số\s?\d*$ THEN
    RETURN TRUE
  END IF
  
  // Condition 3: Duplicate lesson title
  IF normalize(line.strip()) == normalize(context.title) THEN
    RETURN TRUE
  END IF
  
  // Condition 4: Excessive blank lines (handled at join level)
  // Three or more consecutive blank lines in joined content
  
  RETURN FALSE
END FUNCTION
```

### Examples

- **Standalone page number**: Line `"85"` appears between content lines → should be removed. But `"1 cm = 10 mm"` contains digits as part of math content → must be preserved.
- **Repeated header**: Line `"Khám phá"` appears at the top of every page in a lesson → should be removed. But `"Khám phá thế giới xung quanh"` is actual content → must be preserved.
- **Duplicate title**: Header injects `"Bài 1\nÔN TẬP CÁC SỐ ĐẾN 1 000"`, then content starts with `"Ôn tập các số đến 1 000"` → the duplicate in content should be removed.
- **Excessive blank lines**: Page join produces `"\n\n\n\n\n"` (5 newlines) → should collapse to `"\n\n"` (single blank line separator).

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Lines containing digits as part of meaningful content (e.g. "1 cm = 10 mm", "Bài 30", "2 + 3 = 5") must continue to appear in output
- All actual lesson content (explanations, exercises, instructions) must remain unchanged
- Output files must continue to use CRLF line endings and UTF-8 encoding
- The injected header format "Bài X\nTITLE\n\n" must remain at the start of each file
- Content ordering across pages must be preserved

**Scope:**
All inputs that do NOT match the bug condition should be completely unaffected by this fix. This includes:
- Lines with digits embedded in text (math expressions, numbered exercises)
- Lines longer than a short header that happen to contain header keywords
- The first occurrence of the lesson title (in the injected header)
- Single blank lines between paragraphs (normal spacing)

## Hypothesized Root Cause

Based on the bug description, the root cause is straightforward:

1. **No post-processing step exists**: The `split_by_toc_pages()` function joins raw page text with `"\n\n"` and returns it directly. The `split_pdf_to_lessons()` function prepends the header and writes the content without any cleaning. There is simply no text cleaning logic anywhere in the pipeline.

2. **pypdfium2 extracts everything**: The `get_text_bounded()` method extracts all visible text from the PDF page, including page numbers, headers, and footers that are part of the PDF's visual layout but not part of the lesson content.

3. **Page join creates blank line accumulation**: When pages are joined with `"\n\n"` and individual pages already have trailing/leading whitespace, the result can have 3+ consecutive blank lines.

4. **Title duplication is structural**: The code injects `f"Bài {lesson_num}\n{title.upper()}\n\n{content}"` but the content itself often starts with the same title text extracted from the first page of the lesson.

## Correctness Properties

Property 1: Bug Condition - Layout Artifacts Removed

_For any_ extracted page text that contains standalone page numbers (lines matching `^\d+$`), known section headers/footers, duplicate lesson titles, or runs of 3+ consecutive blank lines, the fixed `clean_lesson_text()` function SHALL remove those artifacts from the output while preserving all surrounding content.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4**

Property 2: Preservation - Meaningful Content Unchanged

_For any_ line in the extracted text that does NOT match the bug condition (lines with digits in context, actual lesson content, normal spacing), the fixed code SHALL produce exactly the same output as would be expected, preserving all meaningful content, CRLF line endings, UTF-8 encoding, header format, and page ordering.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `src/page_split.py`

**New Function**: `clean_lesson_text(content: str, title: str) -> str`

**Specific Changes**:

1. **Add a `clean_lesson_text()` helper function** that takes raw joined content and the lesson title, then applies cleaning rules in order:
   - Remove standalone page number lines (lines matching `^\d+$`)
   - Remove known section header/footer lines (exact match against a set of known patterns, case-insensitive)
   - Remove duplicate lesson title from content body (case-insensitive match against the injected title)
   - Collapse runs of 3+ consecutive blank lines to a single blank line

2. **Define the known headers set** as a module-level constant:
   ```python
   _KNOWN_SECTION_HEADERS = {
       "khám phá", "luyện tập", "chủ đề",
       "hoạt động hoạt động", "luyện tập luyện tập",
       "khởi động", "ghi nhớ", "vận dụng", "thực hành",
   }
   ```
   Plus a regex pattern for "Số" followed by optional digits: `^Số\s?\d*$`

3. **Standalone page number detection**: Use regex `^\d+$` on stripped lines. This is safe because meaningful lines with digits always have additional non-digit characters.

4. **Duplicate title removal**: Compare `line.strip().lower()` against `title.strip().lower()`. Remove only the first occurrence in the content body to avoid over-removal.

5. **Blank line collapsing**: Use regex substitution `re.sub(r'\n{3,}', '\n\n', content)` to collapse 3+ newlines to exactly 2 (one blank line).

6. **Integrate into `split_pdf_to_lessons()`**: Call `clean_lesson_text(content, title)` before formatting the output:
   ```python
   for lesson_num, (title, content) in sorted(lessons.items()):
       content = clean_lesson_text(content, title)
       out_text = f"Bài {lesson_num}\n{title.upper()}\n\n{content}\n"
   ```

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write tests that feed known PDF-extracted text (with artifacts) through `split_by_toc_pages()` and `split_pdf_to_lessons()`, then inspect the output for the presence of artifacts. Run these tests on the UNFIXED code to observe failures and understand the root cause.

**Test Cases**:
1. **Standalone Page Number Test**: Feed content with lines like "85", "91" between real content lines (will fail on unfixed code — numbers will be present in output)
2. **Section Header Test**: Feed content with "Khám phá", "luyện tập" lines (will fail on unfixed code — headers will be present in output)
3. **Duplicate Title Test**: Feed content where first line matches the lesson title (will fail on unfixed code — title appears twice)
4. **Excessive Blank Lines Test**: Feed content with 4+ consecutive newlines (will fail on unfixed code — blank lines will remain)

**Expected Counterexamples**:
- Output files contain lines that are just digits (e.g. "85\r\n")
- Output files contain repeated section headers between content
- Possible causes: no cleaning step exists in the pipeline

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL content WHERE containsArtifacts(content) DO
  result := clean_lesson_text(content, title)
  ASSERT no standalone digit-only lines in result
  ASSERT no known section headers in result
  ASSERT title does not appear duplicated in result body
  ASSERT no runs of 3+ consecutive blank lines in result
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL content WHERE NOT containsArtifacts(content) DO
  ASSERT clean_lesson_text(content, title) == content
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain
- It catches edge cases that manual unit tests might miss (e.g. lines that look like page numbers but aren't)
- It provides strong guarantees that behavior is unchanged for all non-buggy inputs

**Test Plan**: Observe behavior on UNFIXED code first for content without artifacts, then write property-based tests capturing that behavior. Generate random lesson content strings that do NOT contain artifacts and verify `clean_lesson_text()` returns them unchanged.

**Test Cases**:
1. **Math Content Preservation**: Verify lines like "1 cm = 10 mm", "2 + 3 = 5", "Bài 30" are preserved unchanged
2. **Normal Spacing Preservation**: Verify single blank lines between paragraphs remain unchanged
3. **Long Lines Preservation**: Verify lines containing header keywords as substrings (e.g. "Khám phá thế giới") are preserved
4. **Content Ordering Preservation**: Verify multi-page content maintains correct line ordering after cleaning

### Unit Tests

- Test `clean_lesson_text()` with content containing standalone page numbers
- Test `clean_lesson_text()` with content containing known section headers
- Test `clean_lesson_text()` with content containing duplicate lesson title
- Test `clean_lesson_text()` with excessive blank lines
- Test `clean_lesson_text()` with content that has NO artifacts (should pass through unchanged)
- Test edge cases: empty content, content with only artifacts, mixed artifacts

### Property-Based Tests

- Generate random lesson content without artifacts and verify `clean_lesson_text()` is identity (preservation)
- Generate random content with injected artifacts and verify all artifacts are removed (fix checking)
- Generate lines with digits embedded in text and verify they survive cleaning (preservation of meaningful digit content)

### Integration Tests

- Run `split_pdf_to_lessons()` on a real PDF and verify output files contain no standalone page numbers
- Run `split_pdf_to_lessons()` on a real PDF and verify output files contain no repeated section headers
- Verify output files maintain CRLF line endings and UTF-8 encoding after cleaning
- Verify the "Bài X\nTITLE\n\n" header format is intact in output files
