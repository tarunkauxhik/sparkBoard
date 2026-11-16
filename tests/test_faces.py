"""The maths of the local face check. The models themselves are not needed here."""
import numpy as np

from adgen.faces import ARCFACE_POINTS, keep_distinct, similarity_transform


def test_similarity_transform_undoes_a_rotation_scale_and_shift():
    angle, scale, shift = np.radians(25), 3.0, np.array([400.0, 250.0])
    turn = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    in_photo = (ARCFACE_POINTS @ turn.T) * scale + shift  # the five face points somewhere in a photo
    matrix = similarity_transform(in_photo, ARCFACE_POINTS)
    back = in_photo @ matrix[:, :2].T + matrix[:, 2]
    assert np.allclose(back, ARCFACE_POINTS, atol=1e-3)


def test_overlapping_boxes_count_as_one_face():
    boxes = np.array([[10, 10, 110, 110], [14, 12, 112, 108], [300, 300, 380, 380]], dtype=np.float32)
    scores = np.array([0.80, 0.95, 0.60], dtype=np.float32)
    assert keep_distinct(boxes, scores) == [1, 2]  # the better of the two overlapping boxes, and the far one
