"""Assign surrounding text to one local table, never to a whole page of cards."""
from dataclasses import dataclass, field
import re
from statistics import median

from .pdf_types import TextBlock


TITLE = re.compile(r"^\s*(?:Карта|Card)\s*(?:№\s*)?\d", re.IGNORECASE)
REFERENCED_SCOPE = re.compile(
    r"\b(?:карт(?:а|е|ы|у|ам|ах)|таблиц(?:а|е|ы|у|ам|ах))\s*(?:№\s*)?\d"
    r"|\b(?:всех|обеих|обоих)\s+(?:карт|таблиц)", re.IGNORECASE)


@dataclass
class TableContext:
    header_lines: list[str] = field(default_factory=list)
    note_lines: list[str] = field(default_factory=list)


def ocr_text_lines(words):
    """Preserve reading order and split OCR lines that bridge page columns."""
    groups = {}
    for word in words:
        groups.setdefault(word.line, []).append(word)
    blocks = []
    for group in groups.values():
        height = median(max(1, w.bbox[3] - w.bbox[1]) for w in group)
        runs = []
        for word in sorted(group, key=lambda w: (w.bbox[0], w.bbox[1])):
            if (not runs or word.bbox[0] - runs[-1][-1].bbox[2] > 3 * height
                    or abs(word.bbox[1] - runs[-1][-1].bbox[1]) > height):
                runs.append([])
            runs[-1].append(word)
        for run in runs:
            bbox = (min(w.bbox[0] for w in run), min(w.bbox[1] for w in run),
                    max(w.bbox[2] for w in run), max(w.bbox[3] for w in run))
            blocks.append(TextBlock(bbox, ' '.join(w.text for w in run)))
    return sorted(blocks, key=lambda b: (b.bbox[1], b.bbox[0]))


def _horizontal_match(a, b):
    width = min(a[2] - a[0], b[2] - b[0])
    return width > 0 and min(a[2], b[2]) - max(a[0], b[0]) >= width * .5


def assign_table_context(tables, blocks):
    """Use columns, preceding tables and card titles as ownership boundaries.

    Text spanning parallel tables or lacking coordinates is retained in warnings.
    No nearest-table guess is made in these ambiguous cases. Explicit cross-page
    references and shared notes require manual review.
    """
    contexts = [TableContext() for _ in tables]
    warnings = []
    boxes = [getattr(table, 'bbox', None) for table in tables]
    usable = []
    for block in blocks:
        text = (getattr(block, 'text', '') or '').strip()
        if not text:
            continue
        if not TITLE.search(text) and REFERENCED_SCOPE.search(text):
            warnings.append(f'Unassigned local text (explicit/shared reference requires review): {text}')
            continue
        box = getattr(block, 'bbox', None)
        if box is None or len(box) != 4 or box[2] <= box[0] or box[3] <= box[1]:
            warnings.append(f'Unassigned local text (missing coordinates): {text}')
            continue
        # PDF extraction normally supplies separate lines. Preserve multi-line
        # block geometry as a unit rather than inventing precise line positions.
        matches = [i for i, table_box in enumerate(boxes)
                   if table_box and _horizontal_match(box, table_box)]
        matched_boxes = (boxes[i] for i in matches)
        if any(table_box is not None and table_box[1] < box[3] and table_box[3] > box[1]
               for table_box in matched_boxes):
            continue  # table-internal text is already in the grid
        parallel = any(
            min(boxes[i][3], boxes[j][3]) > max(boxes[i][1], boxes[j][1])
            and min(boxes[i][2], boxes[j][2]) <= max(boxes[i][0], boxes[j][0])
            for pos, i in enumerate(matches) for j in matches[pos + 1:])
        if not matches or parallel:
            warnings.append(f'Unassigned local text (ambiguous table ownership) at {box}: {text}')
            continue
        above = [i for i in matches if boxes[i][3] <= box[1]]
        below = [i for i in matches if boxes[i][1] >= box[3]]
        previous = max(above, key=lambda i: boxes[i][3]) if above else None
        following = min(below, key=lambda i: boxes[i][1]) if below else None
        usable.append((block, previous, following))

    # The final title before a table starts its local header and cuts off notes
    # belonging to the preceding table, even when the two are close together.
    title_tops = {}
    for block, _, following in usable:
        if following is not None and TITLE.search(block.text):
            title_tops[following] = max(title_tops.get(following, float('-inf')), block.bbox[1])

    for block, previous, following in sorted(usable, key=lambda item: (item[0].bbox[1], item[0].bbox[0])):
        if previous is not None and following is not None and following not in title_tops:
            warnings.append(f'Unassigned local text (no card boundary between tables) at {block.bbox}: {block.text}')
            continue
        in_header = following is not None and (
            previous is None or block.bbox[1] >= title_tops.get(following, float('inf')))
        if in_header:
            contexts[following].header_lines.append(block.text)
        elif previous is not None:
            contexts[previous].note_lines.append(block.text)
        else:
            warnings.append(f'Unassigned local text at {block.bbox}: {block.text}')
    return contexts, warnings
