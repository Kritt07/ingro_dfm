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


def _anchors(values, tolerance: float = 6.0):
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
            # Even-depth contours are ink components; odd depths are holes.
            parent=int(hierarchy[0][index][3])
            depth=0
            while parent!=-1:
                depth+=1
                parent=int(hierarchy[0][parent][3])
            if depth%2:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            cells = []
            for j, child in enumerate(contours):
                if hierarchy[0][j][3] == index:
                    cx, cy, cw, ch = cv2.boundingRect(child)
                    if cw >= 10 and ch >= 10:
                        cells.append((cx, cy, cx+cw, cy+ch))
            if len(cells) >= 3:
                xs=_anchors([v for c in cells for v in (c[0],c[2])])
                ys=_anchors([v for c in cells for v in (c[1],c[3])])
                if len(xs)>=3 and len(ys)>=3:
                    # A short break in one border can hide a cell from contour
                    # detection. Recover only unoccupied slots supported by at
                    # least three actual line segments; never split merged cells.
                    for ya, yb in zip(ys, ys[1:]):
                        for xa, xb in zip(xs, xs[1:]):
                            if any(a <= (xa+xb)/2 <= c and b <= (ya+yb)/2 <= d
                                   for a,b,c,d in cells):
                                continue
                            if min(xb-xa, yb-ya) < 10:
                                continue
                            edges = [lines[max(0,ya-5):ya+6,xa:xb],
                                     lines[max(0,yb-5):yb+6,xa:xb],
                                     lines[ya:yb,max(0,xa-5):xa+6],
                                     lines[ya:yb,max(0,xb-5):xb+6]]
                            support = [np.mean(np.any(e > 0, axis=0 if i < 2 else 1))
                                       if e.size else 0 for i,e in enumerate(edges)]
                            if sum(v > .7 for v in support) >= 3:
                                cells.append((xa,ya,xb,yb))
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


def cell_interior(image, box):
    """Remove long border strokes only; retain symbols near cell edges."""
    x0,y0,x1,y1=box
    crop=image[y0:y1,x0:x1].copy()
    if not crop.size:
        return crop
    h,w=crop.shape
    ink=(crop<128).astype(np.uint8)
    horizontal=cv2.morphologyEx(ink,cv2.MORPH_OPEN,np.ones((1,max(2,round(w*.7))),np.uint8))
    vertical=cv2.morphologyEx(ink,cv2.MORPH_OPEN,np.ones((max(2,round(h*.7)),1),np.uint8))
    band=max(2,round(min(h,w)*.08))
    horizontal[band:max(band,h-band)]=0
    vertical[:,band:max(band,w-band)]=0
    mask=horizontal|vertical
    # Start with the proven inner area, then restore complete compact glyphs
    # from the edge band. Long connected grid strokes remain excluded.
    count,labels,stats,_=cv2.connectedComponentsWithStats(ink)
    keep=np.zeros_like(crop,dtype=bool)
    keep[band:h-band,band:w-band]=True
    core=ink[band:h-band,band:w-band]
    points=np.argwhere(core)
    if points.size:
        top=int(points[:,0].min())+band
        bottom=int(points[:,0].max())+band+1
        for label in range(1,count):
            x,y,cw,ch,area=stats[label]
            if cw<.5*w and ch<.5*h and y+ch>=top and y<=bottom:
                keep[labels==label]=True
        core_left=int(points[:,1].min())+band
        core_right=int(points[:,1].max())+band
        if core_left<=2*band or core_right>=w-2*band:
            detached=ink.copy()
            detached[mask>0]=0
            count,labels,stats,_=cv2.connectedComponentsWithStats(detached)
            for label in range(1,count):
                x,y,cw,ch,area=stats[label]
                if cw<.2*w and ch<.5*h and y+ch>=top and y<=bottom:
                    keep[labels==label]=True
    crop[~keep]=255

    return crop


def clean_header_crop(crop):
    """Remove isolated photo specks, retaining punctuation near the text band."""
    result = crop.copy()
    _, labels, stats, _ = cv2.connectedComponentsWithStats((crop < 128).astype(np.uint8))
    h, w = crop.shape
    components = [(i, s) for i, s in enumerate(stats[1:], 1)
                  if s[4] >= 12 and s[3] >= 8 and s[2] < w * .8
                  and not (s[3] > h * .7 and s[2] < 5)]
    if not components:
        return result
    typical = float(np.percentile([s[3] for _, s in components], 80))
    letters = [s for _, s in components if s[3] >= typical * .65]
    top = min(s[1] for s in letters)
    bottom = max(s[1] + s[3] for s in letters)
    for i, (x, y, cw, ch, area) in enumerate(stats[1:], 1):
        edge = (ch > h * .7 and cw < 5) or (cw > w * .8 and ch < 5)
        speck = area < max(3, typical * typical * .012)
        outside = y + ch < top - typical * .15 or y > bottom + typical * .15
        if edge or speck or outside:
            result[labels == i] = 255
    return result


def recognize_cells(regions, image, engine, *, text_image=None):
    """OCR a packed strip of cell interiors in one engine call, retaining coordinates."""
    patches=[]
    header_words=[]
    for bbox,cells in regions:
        header_bottom=bbox[1]+2*float(np.median([c[3]-c[1] for c in cells])) if cells else bbox[1]
        for x0,y0,x1,y1 in cells:
            margin=0
            crop=cell_interior(image,(x0,y0,x1,y1))
            if not crop.size:
                continue
            if y0 < header_bottom:
                original_crop = crop.copy()
                crop = clean_header_crop(crop)
            ink=np.argwhere(crop<128)
            if len(ink)<8:
                continue
            top,left=ink.min(0);bottom,right=ink.max(0)+1
            patch=crop[top:bottom,left:right]
            if y0 < header_bottom:
                # Keep multi-line header resolution; do not mix its lines with other cells.
                # Normalise glyph size, not cell size: photos can contain very large
                # letters after perspective correction and DPI resampling.
                _, _, stats, _ = cv2.connectedComponentsWithStats((patch < 128).astype(np.uint8))
                heights = [h for x, y, w, h, area in stats[1:]
                           if h >= 8 and w >= 2 and area >= 12 and w < patch.shape[1] * .8]
                scale = min(2., max(.2, 48 / float(np.percentile(heights, 80)))) if heights else 1.
                patch = cv2.resize(patch, None, fx=scale, fy=scale,
                                   interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
                padded=np.pad(patch,20,constant_values=255)
                recognized_header=engine.recognize(padded,psm=6)
                if not recognized_header:
                    recognized_header=engine.recognize(padded,psm=7)
                if text_image is not None:
                    # Local Otsu sees the original tonal information rather than
                    # the adaptive mask used to detect table borders.
                    inset = max(3, round(min(x1-x0, y1-y0) * .08))
                    gray = text_image[y0+inset:y1-inset, x0+inset:x1-inset]
                    local = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)[1]
                    local_words = engine.recognize(np.pad(local, 20, constant_values=255), psm=6)
                    if local_words:
                        recognized_header = local_words
                        top, left, scale = inset, inset, 1.
                # Compare independent image preparations; do not silently replace
                # a good baseline by a failed cleanup or resampling result.
                baseline = original_crop
                if baseline.shape[1] > 350 and min(baseline.shape) >= 7:
                    baseline = cv2.medianBlur(baseline, 7)
                points = np.argwhere(baseline < 128)
                disagreement = False
                if len(points) >= 8:
                    bt, bl = points.min(0)
                    bb, br = points.max(0) + 1
                    baseline_words = engine.recognize(np.pad(baseline[bt:bb, bl:br], 20,
                                                            constant_values=255), psm=6)
                    disagreement = (' '.join(w.text for w in baseline_words) !=
                                    ' '.join(w.text for w in recognized_header))
                    def score(words):
                        count = sum(len(w.text) for w in words)
                        return sum(w.confidence * len(w.text) for w in words) / max(1, count)
                    if score(baseline_words) >= score(recognized_header):
                        recognized_header = baseline_words
                        top, left, scale = bt, bl, 1.
                for word in recognized_header:
                    a,b,c,d=word.bbox
                    header_words.append(OCRWord(word.text,
                        (round(x0+left+(a-20)/scale),round(y0+top+(b-20)/scale),
                         round(x0+left+(c-20)/scale),round(y0+top+(d-20)/scale)),
                        min(word.confidence, .79) if disagreement else word.confidence,word.line))
                continue
            scale=min(1.,60/patch.shape[0])
            patch=cv2.resize(patch,None,fx=scale,fy=scale)
            patches.append((patch,x0+margin+left,y0+margin+top,scale))
    if not patches:
        return header_words
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
    result=list(header_words)
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
