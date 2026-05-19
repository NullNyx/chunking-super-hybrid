# Bugfix Requirements Document

## Introduction

The pipeline's B5 step (`split_pdf_to_lessons` in `src/page_split.py`) uses pypdfium2 to extract text from PDF pages. The extracted text includes layout artifacts — page numbers, repeated section headers/footers, and duplicate lesson titles — that should not appear in the final `.txt` output. The CMS system expects clean content: lesson header followed immediately by meaningful content, with `\r\n` line endings, no standalone page numbers, no repeated layout headers, and no duplicate titles. The reference format shows continuous lesson content without any PDF layout noise.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN a PDF page contains a printed page number as a standalone line (e.g. "85", "91", "6") THEN the system includes that page number as a line in the output text

1.2 WHEN a PDF page contains repeated section headers/footers (e.g. "Khám phá", "luyện tập", "Chủ đề", "hoạt động Hoạt động", "luyện tập Luyện tập") THEN the system includes those header/footer lines in the output text

1.3 WHEN the lesson title already exists in the injected header ("Bài X\nTITLE") AND the same title appears in the PDF page content THEN the system outputs the title twice (duplicate)

1.4 WHEN multiple pages are joined together THEN the system produces excessive consecutive blank lines between page boundaries

### Expected Behavior (Correct)

2.1 WHEN a PDF page contains a printed page number as a standalone line (a line consisting only of digits) THEN the system SHALL remove that line from the output text

2.2 WHEN a PDF page contains known repeated section headers/footers (short lines matching patterns like "Khám phá", "luyện tập", "Chủ đề", "hoạt động Hoạt động", "luyện tập Luyện tập", "Số ?") THEN the system SHALL remove those lines from the output text

2.3 WHEN the lesson title (or a case-insensitive variant) appears in the PDF page content AND it has already been injected as the file header THEN the system SHALL remove the duplicate title occurrence from the body content

2.4 WHEN multiple pages are joined together THEN the system SHALL collapse runs of more than two consecutive blank lines down to a single blank line

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a line contains digits as part of meaningful content (e.g. "1 cm = 10 mm", "Bài 30", math exercises) THEN the system SHALL CONTINUE TO preserve that line in the output

3.2 WHEN a line contains text that is actual lesson content (explanations, exercises, instructions) THEN the system SHALL CONTINUE TO include that line unchanged in the output

3.3 WHEN the output file is written THEN the system SHALL CONTINUE TO use CRLF line endings and UTF-8 encoding

3.4 WHEN the injected header format is "Bài X\nTITLE\n\n" THEN the system SHALL CONTINUE TO produce that header at the start of each file

3.5 WHEN pages are joined for a lesson THEN the system SHALL CONTINUE TO preserve the correct ordering of content across pages
