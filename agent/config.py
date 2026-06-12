import os

# Groq model — override via GROQ_MODEL in .env
_raw_model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
MODEL_ID = _raw_model if _raw_model.startswith("groq:") else f"groq:{_raw_model}"
MODEL_TEMPERATURE = float(os.getenv("GROQ_TEMPERATURE", "0.2"))

UI_STYLE_PRESETS = {
    "Modern SaaS (dark)": (
        "Dark SaaS dashboard: slate/gray background (#0f172a), indigo/violet accents, "
        "card-based layout, soft shadows, rounded-xl corners, crisp typography"
    ),
    "Clean minimal (light)": (
        "Light minimal UI: white background, generous whitespace, neutral grays, "
        "single accent color, subtle borders, system font stack"
    ),
    "Glassmorphism": (
        "Glassmorphism: frosted glass cards, blur backgrounds, gradient overlays, "
        "semi-transparent panels, vibrant accent gradients"
    ),
    "Bold & playful": (
        "Bold playful UI: bright colors, large rounded buttons, friendly typography, "
        "high contrast CTAs, animated hover states"
    ),
}
