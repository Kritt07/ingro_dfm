import cv2
import numpy as np
from normdoc2json.ocr_engine import OCRWord
from normdoc2json.ocr_tables import detect_grid, reconstruct_tables


def test_cell_border_removal_preserves_edge_minus_and_digits():
    from normdoc2json.ocr_tables import cell_interior
    image=np.full((200,300),255,np.uint8)
    cv2.rectangle(image,(0,0),(299,199),0,2)
    cv2.line(image,(2,90),(12,90),0,2)
    cv2.putText(image,'0,28',(16,100),0,1,0,2)
    result=cell_interior(image,(0,0,300,200))
    assert np.array_equal(result[70:110,2:100],image[70:110,2:100])
    assert np.all(result[0]==255)


def test_merged_header_blank_zero_and_confidence():
    image = np.full((400, 500), 255, np.uint8)
    for y in (50,150,250,350):
        cv2.line(image,(50,y),(450,y),0,2)
    for x in (50,250,450):
        cv2.line(image,(x,150 if x==250 else 50),(x,350),0,2)
    regions, clean = detect_grid(image)
    words = [OCRWord('Header',(90,80,200,110),.99,(1,1,1)),
             OCRWord('0',(90,190,110,210),.9,(2,1,1)),
             OCRWord('0,28',(290,190,360,210),.5,(3,1,1)),
             OCRWord('Note',(60,370,120,390),.95,(4,1,1))]
    tables, outside, warnings = reconstruct_tables(regions,words,clean)
    assert len(tables)==1
    assert tables[0].values == [['Header','Header'],['0','0,28'],[None,None]]
    assert tables[0].merged_ranges == [(1,1,1,2)]
    assert outside[0].text=='Note'
    assert any('low confidence' in w for w in warnings)


def test_unreadable_is_not_silent_blank():
    image = np.full((300,300),255,np.uint8)
    for p in (20,140,260):
        cv2.line(image,(20,p),(260,p),0,2)
        cv2.line(image,(p,20),(p,260),0,2)
    cv2.putText(image,'?',(50,80),0,1,0,2)
    regions,clean=detect_grid(image)
    _,_,warnings=reconstruct_tables(regions,[],clean)
    assert any('unreadable' in w for w in warnings)


def test_table_inside_nested_page_frames_is_found_once():
    image=np.full((600,600),255,np.uint8)
    for p in (150,300,450):
        cv2.line(image,(150,p),(450,p),0,2)
        cv2.line(image,(p,150),(p,450),0,2)
    for offset in (20,60):cv2.rectangle(image,(offset,offset),(600-offset,600-offset),0,2)
    regions,_=detect_grid(image)
    assert len(regions)==1
    assert len(regions[0][1])==4
