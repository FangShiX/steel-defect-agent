import numpy as np


def test_ultralytics_curve_order_maps_pr_and_f1_to_frontend_shapes():
    """The serialized curves follow Ultralytics 8.3's curves_results order."""
    curves = [
        [np.array([0.0, 0.5, 1.0]), np.array([1.0, 0.6, 0.0]), "Recall", "Precision"],
        [np.array([0.0, 0.5, 1.0]), np.array([0.2, 0.8, 0.1]), "Confidence", "F1"],
    ]

    def serialize(curve):
        x_values, y_values = curve[0], curve[1]
        return {"x": [round(float(x), 4) for x in x_values],
                "y": [round(float(y), 4) for y in y_values]}

    assert serialize(curves[0]) == {"x": [0.0, 0.5, 1.0], "y": [1.0, 0.6, 0.0]}
    assert serialize(curves[1]) == {"x": [0.0, 0.5, 1.0], "y": [0.2, 0.8, 0.1]}
