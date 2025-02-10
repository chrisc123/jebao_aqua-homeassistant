import json
from pathlib import Path
from homeassistant.core import HomeAssistant
from .const import LOGGER


async def load_attribute_models(hass: HomeAssistant) -> dict:
    """Load attribute models asynchronously."""
    models_path = Path(hass.config.path("custom_components/jebao_aqua/models"))
    attribute_models = {}

    def _load_model(file_path):
        """Load a single model file."""
        with open(file_path, "r") as file:
            model = json.load(file)
            return model["product_key"], model

    # Load all model files in executor
    for model_file in models_path.glob("*.json"):
        try:
            product_key, model = await hass.async_add_executor_job(
                _load_model, model_file
            )
            attribute_models[product_key] = model
        except Exception as e:
            LOGGER.error(f"Error loading model file {model_file}: {e}")

    return attribute_models
