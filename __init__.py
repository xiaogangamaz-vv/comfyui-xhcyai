import os

from .nodes import NODE_CLASS_MAPPINGS as _NANO_CLASS_MAPPINGS
from .nodes import NODE_DISPLAY_NAME_MAPPINGS as _NANO_DISPLAY_NAMES
from .nodes_gpt_image_25 import NODE_CLASS_MAPPINGS as _GPT25_CLASS_MAPPINGS
from .nodes_gpt_image_25 import NODE_DISPLAY_NAME_MAPPINGS as _GPT25_DISPLAY_NAMES
from .nodes_minimax_h3 import NODE_CLASS_MAPPINGS as _H3_CLASS_MAPPINGS
from .nodes_minimax_h3 import NODE_DISPLAY_NAME_MAPPINGS as _H3_DISPLAY_NAMES

NODE_CLASS_MAPPINGS = {
    **_NANO_CLASS_MAPPINGS,
    **_GPT25_CLASS_MAPPINGS,
    **_H3_CLASS_MAPPINGS,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    **_NANO_DISPLAY_NAMES,
    **_GPT25_DISPLAY_NAMES,
    **_H3_DISPLAY_NAMES,
}

current_dir = os.path.dirname(os.path.abspath(__file__))
if os.path.exists(os.path.join(current_dir, "js")):
    WEB_DIRECTORY = "./js"
elif os.path.exists(os.path.join(current_dir, "web")):
    WEB_DIRECTORY = "./web"

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
if 'WEB_DIRECTORY' in locals():
    __all__.append('WEB_DIRECTORY')
