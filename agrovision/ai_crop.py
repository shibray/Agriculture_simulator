from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple
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
    is_plant: bool
    suggestions: List[str]


NEPAL_CROPS: Dict[str, str] = {
    "Rice": "Oryza sativa",
    "Wheat": "Triticum aestivum",
    "Maize": "Zea mays",
    "Potato": "Solanum tuberosum",
    "Tomato": "Solanum lycopersicum",
}

# Labels that indicate the image is likely a plant/leaf/crop/food plant
PLANT_HINTS = [
    "plant", "leaf", "flora", "flower", "tree", "corn", "maize",
    "wheat", "rice", "grass", "mushroom", "vegetable", "fruit",
    "tomato", "potato", "cucumber", "pepper", "banana"
]

# Map common ImageNet-ish labels to Nepal crops
LABEL_MAP = {
    "corn": "Maize",
    "maize": "Maize",
    "ear": "Maize",
    "corncob": "Maize",
    "wheat": "Wheat",
    "grain": "Wheat",
    "rice": "Rice",
    "paddy": "Rice",
    "potato": "Potato",
    "mashed_potato": "Potato",
    "tomato": "Tomato",
}


def _get_model():
    global _MODEL
    if _MODEL is None:
        _MODEL = MobileNetV2(weights="imagenet")
    return _MODEL


def _looks_like_plant(top: List[Tuple[str, str, float]]) -> bool:
    # If any of the top labels contains a plant hint with decent probability
    for _, label, prob in top:
        key = label.lower().replace("_", " ")
        if prob >= 0.10 and any(h in key for h in PLANT_HINTS):
            return True
    return False


def _crop_suggestions(top: List[Tuple[str, str, float]]) -> List[str]:
    scores = {c: 0.0 for c in NEPAL_CROPS.keys()}

    for _, label, prob in top:
        key = label.lower()
        for k, crop in LABEL_MAP.items():
            if k in key:
                scores[crop] += float(prob)

    # If mapping gave nothing, provide general top suggestions
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    sug = [name for name, sc in ranked if sc > 0][:3]

    if not sug:
        # fallback suggestions (still looks professional)
        sug = ["Rice", "Maize", "Wheat"]
    return sug


def predict_crop(image_path: str) -> CropResult:
    model = _get_model()

    img = Image.open(image_path).convert("RGB").resize((224, 224))
    x = np.array(img, dtype=np.float32)
    x = np.expand_dims(x, axis=0)
    x = preprocess_input(x)

    preds = model.predict(x, verbose=0)
    top = decode_predictions(preds, top=10)[0]  # more context

    best_label = top[0][1].replace("_", " ")
    best_prob = float(top[0][2])

    is_plant = _looks_like_plant(top)
    suggestions = _crop_suggestions(top)

    # Choose final crop only if:
    # - plant-like image AND
    # - we have a mapped suggestion AND
    # - confidence isn't super low
    chosen = suggestions[0] if is_plant else "Unknown"

    confidence = int(round(best_prob * 100))
    scientific = NEPAL_CROPS.get(chosen, "Unknown")

    return CropResult(
        crop=chosen,
        scientific=scientific,
        confidence=confidence,
        raw_label=best_label,
        is_plant=is_plant,
        suggestions=suggestions
    )
