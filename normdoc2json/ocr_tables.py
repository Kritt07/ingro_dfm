"""Reconstruct ruled tables in prepared images; retain uncertain results."""
from dataclasses import dataclass, field
import cv2
import numpy as np
from .ocr_engine import OCRWord


@dataclass
class OCRTable:
    """Raw grid in prepared-image pixels; merged ranges are 1-based inclusive."""
    bbox: tuple[int, int, int, int]
    values: list[list[str | None]]
    cell_bboxes: list[list[tuple[int, int, int, int] | None]]
    confidences: list[list[float | None]]
    merged_ranges: list[tuple[int, int, int, int]] = field(default_factory=list)


def _anchors(values, tolerance=6):
    groups = []
    for value in sorted(values):
        if groups and value - np.mean(groups[-1]) <= tolerance:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [round(float(np.mean(g))) for g in groups]


def detect_grid(image):
    """Find closed cell interiors and remove only long grid strokes for OCR."""
    ink = 255-image
    horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN,
                                 np.ones((1, max(40, image.shape[1]//25)), np.uint8))
    vertical = cv2.morphologyEx(ink, cv2.MORPH_OPEN,
                               np.ones((max(40, image.shape[0]//25), 1), np.uint8))
    lines = cv2.bitwise_or(horizontal, vertical)
    lines = cv2.morphologyEx(lines, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, hierarchy = cv2.findContours(lines, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    regions = []
    if hierarchy is not None:
        for index, contour in enumerate(contours):
            if hierarchy[0][index][3] != -1:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            cells = []
            for j, child in enumerate(contours):
                if hierarchy[0][j][3] == index:
                    cx, cy, cw, ch = cv2.boundingRect(child)
                    if cw >= 10 and ch >= 10:
                        cells.append((cx, cy, cx+cw, cy+ch))
            if len(cells) >= 4:
                regions.append(((x, y, x+w, y+h), cells))
    clean = image.copy()
    clean[cv2.dilate(lines,np.ones((3,3),np.uint8)) > 0] = 255
    return sorted(regions, key=lambda r: (r[0][1], r[0][0])), clean


def reconstruct_tables(regions, words: list[OCRWord], clean, threshold=.8):
    """Assign OCR words to cells, retaining blanks and confidence diagnostics."""
    tables, warnings, assigned = [], [], set()
    for table_index, (bbox, cells) in enumerate(regions, 1):
        xs = _anchors([v for c in cells for v in (c[0], c[2])],
                      max(6,float(np.median([c[2]-c[0] for c in cells]))*.15))
        ys = _anchors([v for c in cells for v in (c[1], c[3])],
                      max(6,float(np.median([c[3]-c[1] for c in cells]))*.15))
        rows, cols = len(ys)-1, len(xs)-1
        if rows < 2 or cols < 2 or rows*cols > 100000:
            warnings.append(f'Table {table_index}: invalid or oversized grid')
            continue
        table = OCRTable(bbox, [[None]*cols for _ in range(rows)],
                         [[None]*cols for _ in range(rows)], [[None]*cols for _ in range(rows)])
        for box in cells:
            x0, y0, x1, y1 = box
            c0, c1 = [min(range(len(xs)), key=lambda i: abs(xs[i]-v)) for v in (x0,x1)]
            r0, r1 = [min(range(len(ys)), key=lambda i: abs(ys[i]-v)) for v in (y0,y1)]
            if r1 <= r0 or c1 <= c0:
                warnings.append(f'Table {table_index}: ambiguous cell {box}')
                continue
            matched = []
            for i, word in enumerate(words):
                a,b,c,d = word.bbox
                if x0 <= (a+c)/2 <= x1 and y0 <= (b+d)/2 <= y1:
                    matched.append(word)
                    assigned.add(i)
            matched.sort(key=lambda w: (w.line, w.bbox[0]))
            text = ' '.join(w.text for w in matched) or None
            confidence = min((w.confidence for w in matched), default=None)
            interior = clean[y0+3:max(y0+3,y1-3), x0+3:max(x0+3,x1-3)]
            if confidence is not None and confidence < threshold:
                warnings.append(f'Table {table_index} R{r0+1}C{c0+1}: low confidence {confidence:.2f}: {text}')
            if not matched and np.count_nonzero(interior < 128) > 8:
                warnings.append(f'Table {table_index} R{r0+1}C{c0+1}: unreadable ink, stored null')
            if r1-r0 > 1 or c1-c0 > 1:
                table.merged_ranges.append((r0+1,c0+1,r1,c1))
            for r in range(r0,r1):
                for c in range(c0,c1):
                    table.values[r][c] = text
                    table.cell_bboxes[r][c] = box
                    table.confidences[r][c] = confidence
        if any(b is None for row in table.cell_bboxes for b in row):
            warnings.append(f'Table {table_index}: missing cell borders; review structure')
        tables.append(table)
    outside = [w for i,w in enumerate(words) if i not in assigned]
    if not tables:
        warnings.append('No closed table grid found; borderless/perspective tables require review')
    return tables, outside, warnings


def recognize_cells(regions, image, engine):
    """OCR a packed strip of cell interiors in one engine call, retaining coordinates."""
    patches=[]
    for _,cells in regions:
        for x0,y0,x1,y1 in cells:
            margin=max(4,round(min(x1-x0,y1-y0)*.08))
            crop=image[y0+margin:y1-margin,x0+margin:x1-margin]
            if not crop.size:
                continue
            ink=np.argwhere(crop<128)
            if len(ink)<8:
                continue
            top,left=ink.min(0);bottom,right=ink.max(0)+1
            patch=crop[top:bottom,left:right]
            scale=min(1.,60/patch.shape[0])
            patch=cv2.resize(patch,None,fx=scale,fy=scale)
            patches.append((patch,x0+margin+left,y0+margin+top,scale))
    if not patches:
        return []
    width=max(p[0].shape[1] for p in patches)+40
    height=sum(p[0].shape[0]+40 for p in patches)
    if width*height>40_000_000:
        raise ValueError('Cell OCR montage exceeds pixel limit')
    strip=np.full((height,width),255,np.uint8)
    placements=[];offset=0
    for patch,x,y,scale in patches:
        h,w=patch.shape
        strip[offset+20:offset+20+h,20:20+w]=patch
        placements.append((offset+20,offset+20+h,x,y,scale))
        offset+=h+40
    result=[]
    recognized=set()
    for word in engine.recognize(strip,psm=6):
        a,b,c,d=word.bbox
        for index,(top,bottom,x,y,scale) in enumerate(placements):
            if top <= (b+d)/2 <= bottom:
                recognized.add(index)
                result.append(OCRWord(word.text,(round(x+(a-20)/scale),round(y+(b-top)/scale),
                    round(x+(c-20)/scale),round(y+(d-top)/scale)),word.confidence,word.line))
                break
    for index,(patch,x,y,scale) in enumerate(patches):
        if index in recognized:
            continue
        padded=np.pad(patch,20,constant_values=255)
        for word in engine.recognize(padded,psm=7):
            a,b,c,d=word.bbox
            result.append(OCRWord(word.text,(round(x+(a-20)/scale),round(y+(b-20)/scale),
                round(x+(c-20)/scale),round(y+(d-20)/scale)),word.confidence,(100000+index,1,1)))
    return result
