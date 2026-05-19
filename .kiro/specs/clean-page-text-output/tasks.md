# Implementation Plan

## Overview

This task list implements the bugfix for cleaning layout artifacts from extracted PDF text output. It follows the exploratory bugfix workflow: write tests to confirm the bug exists, write preservation tests to capture baseline behavior, implement the fix, then verify everything passes.

## Tasks

- [~] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Layout Artifacts Present in Output
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate layout artifacts are not being removed
  - **Scoped PBT Approach**: Scope the property to concrete failing cases — content with standalone page numbers (`^\d+$`), known section headers ("Khám phá", "luyện tập", etc.), duplicate lesson titles, and excessive blank lines
  - Write a property-based test that generates content containing artifacts matching `isBugCondition` from design:
    - Lines matching regex `^\d+$` (standalone page numbers like "85", "91")
    - Lines matching known section headers set: {"khám phá", "luyện tập", "chủ đề", "hoạt động hoạt động", "luyện tập luyện tập", "khởi động", "ghi nhớ", "vận dụng", "thực hành"}
    - Lines matching `^Số\s?\d*$`
    - Lines that are case-insensitive duplicates of the lesson title
    - Runs of 3+ consecutive blank lines
  - Assert that `clean_lesson_text(content, title)` removes all artifacts:
    - No standalone digit-only lines remain in result
    - No known section header lines remain in result
    - Title does not appear duplicated in result body
    - No runs of 3+ consecutive blank lines remain
  - Run test on UNFIXED code (function does not exist yet)
  - **EXPECTED OUTCOME**: Test FAILS (ImportError or assertion failure — confirms the bug exists because no cleaning logic exists)
  - Document counterexamples found (e.g., "content with '85' on its own line passes through unchanged")
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [~] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Meaningful Content Unchanged
  - **IMPORTANT**: Follow observation-first methodology
  - Observe: Lines with digits in meaningful context (e.g. "1 cm = 10 mm", "2 + 3 = 5", "Bài 30") must pass through unchanged
  - Observe: Lines longer than short headers containing header keywords as substrings (e.g. "Khám phá thế giới xung quanh") must pass through unchanged
  - Observe: Single blank lines between paragraphs remain unchanged
  - Observe: Content ordering across pages is preserved
  - Write property-based test: for all content strings that do NOT match the bug condition (no standalone digit-only lines, no exact known header matches, no duplicate titles, no 3+ blank line runs), `clean_lesson_text(content, title)` returns the content unchanged (identity function for non-buggy inputs)
  - Generate random lesson content without artifacts and verify `clean_lesson_text()` is identity
  - Generate lines with digits embedded in text (math expressions, numbered exercises) and verify they survive cleaning
  - Generate lines containing header keywords as substrings in longer text and verify they survive cleaning
  - Run tests on UNFIXED code (function does not exist yet — stub or skip if needed)
  - **EXPECTED OUTCOME**: Tests PASS once `clean_lesson_text()` is available (confirms baseline preservation behavior)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [ ] 3. Fix for layout artifacts in extracted PDF text output

  - [~] 3.1 Implement the `clean_lesson_text()` function in `src/page_split.py`
    - Define module-level constant `_KNOWN_SECTION_HEADERS` with the set: {"khám phá", "luyện tập", "chủ đề", "hoạt động hoạt động", "luyện tập luyện tập", "khởi động", "ghi nhớ", "vận dụng", "thực hành"}
    - Add regex pattern for `^Số\s?\d*$` matching
    - Implement standalone page number removal: lines matching `^\d+$` on stripped content
    - Implement known section header removal: case-insensitive exact match against `_KNOWN_SECTION_HEADERS` and `^Số\s?\d*$` pattern
    - Implement duplicate title removal: compare `line.strip().lower()` against `title.strip().lower()`, remove only first occurrence in body
    - Implement blank line collapsing: `re.sub(r'\n{3,}', '\n\n', content)` to collapse 3+ newlines to exactly 2
    - _Bug_Condition: isBugCondition(line, context) where line matches `^\d+$`, or normalize(line) in known_headers, or normalize(line) == normalize(title), or 3+ consecutive blank lines_
    - _Expected_Behavior: clean_lesson_text(content, title) removes all lines matching bug condition and collapses excessive blank lines_
    - _Preservation: Lines with digits in context, actual lesson content, CRLF encoding, header format, and page ordering remain unchanged_
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5_

  - [~] 3.2 Integrate `clean_lesson_text()` into `split_pdf_to_lessons()`
    - Call `clean_lesson_text(content, title)` before formatting the output in the lesson writing loop
    - Ensure the call happens after page joining but before header injection and file writing
    - Verify CRLF line endings and UTF-8 encoding are still applied correctly after cleaning
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.3_

  - [~] 3.3 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Layout Artifacts Removed
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior (artifacts removed)
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed — all artifacts are removed)
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [~] 3.4 Verify preservation tests still pass
    - **Property 2: Preservation** - Meaningful Content Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions — meaningful content is unchanged)
    - Confirm all tests still pass after fix (no regressions)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [~] 4. Checkpoint - Ensure all tests pass
  - Run the full test suite to confirm both property tests pass
  - Verify bug condition test (Property 1) passes — artifacts are removed
  - Verify preservation test (Property 2) passes — meaningful content is unchanged
  - Ensure no other tests in the project are broken by the change
  - Ask the user if questions arise

## Task Dependency Graph

```json
{
  "waves": [
    ["1", "2"],
    ["3.1"],
    ["3.2"],
    ["3.3", "3.4"],
    ["4"]
  ]
}
```

## Notes

- Tasks 1 and 2 are independent and can be worked on in parallel
- Task 1 (exploration test) is expected to FAIL on unfixed code — this is correct behavior that confirms the bug exists
- Task 2 (preservation test) should PASS once the function stub exists, confirming baseline behavior
- The fix implementation (3.1, 3.2) must be completed before verification tasks (3.3, 3.4)
- Property-based testing is used for stronger guarantees across the input domain
