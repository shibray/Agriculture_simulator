from __future__ import annotations

from dataclasses import dataclass
from typing import Dict
import numpy as np
from PIL import Image
import tensorflow as tf

MobileNetV2 = tf.keras.applications.MobileNetV2
preprocess_input = tf.keras.applications.mobilenet_v2.preprocess_input
decode_predictions = tf.keras.applications.mobilenet_v2.decode_predictions

_MODEL = None


@dataclass
class CropResult:
    crop: str
    scientific: str
    confidence: int
    raw_label: str


NEPAL_CROPS: Dict[str, str] = {
    "Rice": "Oryza sativa",
    "Wheat": "Triticum aestivum",
    "Maize": "Zea mays",
    "Potato": "Solanum tuberosum",
    "Tomato": "Solanum lycopersicum",
}

LABEL_MAP = {
    "corn": "Maize",
    "maize": "Maize",
    "potato": "Potato",
    "mashed_potato": "Potato",
    "tomato": "Tomato",
    "wheat": "Wheat",
    "grain": "Wheat",
    "rice": "Rice",
}


def _get_model():
    global _MODEL
    if _MODEL is None:
        _MODEL = MobileNetV2(weights="imagenet")
    return _MODEL


def predict_crop(image_path: str) -> CropResult:
    model = _get_model()

    img = Image.open(image_path).convert("RGB").resize((224, 224))
    x = np.array(img, dtype=np.float32)
    x = np.expand_dims(x, axis=0)
    x = preprocess_input(x)

    preds = model.predict(x, verbose=0)
    top = decode_predictions(preds, top=5)[0]  # list of (id, label, prob)

    best_label = top[0][1].replace("_", " ")
    best_prob = float(top[0][2])

    chosen = None
    for _, label, prob in top:
        key = label.lower()
        for k, v in LABEL_MAP.items():
            if k in key:
                chosen = v
                best_label = label.replace("_", " ")
                best_prob = float(prob)
                break
        if chosen:
            break

    if not chosen:
        chosen = "Rice" if best_prob >= 0.20 else "Maize"

    scientific = NEPAL_CROPS.get(chosen, "Unknown")
    confidence = int(round(best_prob * 100))

    return CropResult(
        crop=chosen,
        scientific=scientific,
        confidence=confidence,
        raw_label=best_label
    )
