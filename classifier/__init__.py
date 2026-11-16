"""Модуль распознавания КТЭ по AAG, 10-уровневого кодирования и кластеризации установов."""

from .aag_feature_recognizer import (
    AAGFeatureRecognizer,
    AAGGraph,
    BRepEdgeLink,
    BRepFaceNode,
    quantize_setup_direction,
)
from .setup_clusterer import SetupCluster, cluster_setups
from .tech_coder_10 import (
    build_cbnt_filters,
    classify_element,
    classify_passport,
    encode_l1_mass,
    encode_l5_heat_treatment,
    encode_l8_it_bucket,
    encode_l9_ra_bucket,
    lookup_transitions,
)

__all__ = [
    "BRepFaceNode",
    "BRepEdgeLink",
    "AAGGraph",
    "AAGFeatureRecognizer",
    "quantize_setup_direction",
    "SetupCluster",
    "cluster_setups",
    "encode_l1_mass",
    "encode_l5_heat_treatment",
    "encode_l8_it_bucket",
    "encode_l9_ra_bucket",
    "lookup_transitions",
    "build_cbnt_filters",
    "classify_element",
    "classify_passport",
]
