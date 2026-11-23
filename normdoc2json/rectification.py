"""Conservative perspective correction using a prominent closed table border."""
import cv2
import numpy as np
from .image_io import ImagePage


def rectify_table_plane(page):
    """Rectify a quadrilateral table while keeping the whole page and its text."""
    if page.image is None:
        return page
    h,w=page.image.shape[:2]
    factor=min(1.,1400/max(h,w))
    small=cv2.resize(page.image,None,fx=factor,fy=factor)
    gray=cv2.cvtColor(small,cv2.COLOR_RGB2GRAY)
    binary=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY_INV,31,15)
    contours,_=cv2.findContours(binary,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    candidates=[]
    for contour in contours:
        area=cv2.contourArea(contour)
        if not .08*gray.size < area < .65*gray.size:
            continue
        poly=cv2.approxPolyDP(contour,.02*cv2.arcLength(contour,True),True)
        if len(poly)==4 and cv2.isContourConvex(poly):
            candidates.append((area,poly.reshape(4,2).astype(np.float32)/factor))
    if not candidates:
        return page
    points=max(candidates,key=lambda p:p[0])[1]
    ordered=np.array([points[np.argmin(points.sum(1))],points[np.argmin(points[:,1]-points[:,0])],
                      points[np.argmax(points.sum(1))],points[np.argmax(points[:,1]-points[:,0])]],np.float32)
    if len(set(map(tuple,ordered)))!=4:
        return page
    tl,tr,br,bl=ordered
    width=(np.linalg.norm(tr-tl)+np.linalg.norm(br-bl))/2
    height=(np.linalg.norm(bl-tl)+np.linalg.norm(br-tr))/2
    center=ordered.mean(0)
    target=np.array([center+[-width/2,-height/2],center+[width/2,-height/2],
                     center+[width/2,height/2],center+[-width/2,height/2]],np.float32)
    if np.max(np.abs(target-ordered))<2:
        return page
    matrix=cv2.getPerspectiveTransform(ordered,target)
    corners=cv2.perspectiveTransform(np.array([[[0,0],[w,0],[w,h],[0,h]]],np.float32),matrix)[0]
    lo=np.floor(corners.min(0)); hi=np.ceil(corners.max(0)); size=(hi-lo).astype(int)
    if min(size)<=0 or size.prod()>2*w*h:
        return page
    matrix=np.array([[1,0,-lo[0]],[0,1,-lo[1]],[0,0,1]])@matrix
    image=cv2.warpPerspective(page.image,matrix,tuple(size),borderValue=(255,255,255))
    return ImagePage(page.source_file,page.page_number,image,page.dpi,
                     page.warnings+['Perspective corrected from table border; verify geometry'])
