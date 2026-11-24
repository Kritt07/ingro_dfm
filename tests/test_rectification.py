import cv2
import numpy as np
from normdoc2json.rectification import rectify_table_plane
from normdoc2json.image_io import ImagePage
from normdoc2json.preprocessing import preprocess_page
from normdoc2json.ocr_tables import detect_grid


def test_perspective_table_keeps_grid():
    image=np.full((600,800,3),255,np.uint8)
    for x in (150,300,450,600):cv2.line(image,(x,150),(x,450),(0,0,0),3)
    for y in (150,250,350,450):cv2.line(image,(150,y),(600,y),(0,0,0),3)
    src=np.float32([[150,150],[600,150],[600,450],[150,450]])
    dst=np.float32([[110,190],[570,80],[660,390],[180,500]])
    image=cv2.warpPerspective(image,cv2.getPerspectiveTransform(src,dst),(800,600),borderValue=(255,255,255))
    page=ImagePage('test',1,image,(300,300))
    corrected=rectify_table_plane(page)
    assert corrected is not page
    prepared=preprocess_page(corrected,deskew=False)
    regions,_=detect_grid(prepared.image)
    assert len(regions)==1 and len(regions[0][1])==9
