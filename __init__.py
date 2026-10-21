import os

from .nodes import NODE_CLASS_MAPPINGS as _LEGACY_CLASS_MAPPINGS
from .nodes import NODE_DISPLAY_NAME_MAPPINGS as _LEGACY_DISPLAY_NAMES
from .nodes_analyze import NODE_CLASS_MAPPINGS as _ANALYZE_CLASS_MAPPINGS
from .nodes_analyze import NODE_DISPLAY_NAME_MAPPINGS as _ANALYZE_DISPLAY_NAMES
from .nodes_gpt_image_2 import NODE_CLASS_MAPPINGS as _GPT2_CLASS_MAPPINGS
from .nodes_gpt_image_2 import NODE_DISPLAY_NAME_MAPPINGS as _GPT2_DISPLAY_NAMES
from .nodes_gpt_image_25 import NODE_CLASS_MAPPINGS as _GPT25_CLASS_MAPPINGS
from .nodes_gpt_image_25 import NODE_DISPLAY_NAME_MAPPINGS as _GPT25_DISPLAY_NAMES
from .nodes_llm import NODE_CLASS_MAPPINGS as _LLM_CLASS_MAPPINGS
from .nodes_llm import NODE_DISPLAY_NAME_MAPPINGS as _LLM_DISPLAY_NAMES
from .nodes_minimax_h3 import NODE_CLASS_MAPPINGS as _H3_CLASS_MAPPINGS
from .nodes_minimax_h3 import NODE_DISPLAY_NAME_MAPPINGS as _H3_DISPLAY_NAMES
from .nodes_minimax_h3_context_ir import NODE_CLASS_MAPPINGS as _H3IR_CLASS_MAPPINGS
from .nodes_minimax_h3_context_ir import NODE_DISPLAY_NAME_MAPPINGS as _H3IR_DISPLAY_NAMES
from .nodes_minimax_h3_frames import NODE_CLASS_MAPPINGS as _H3F_CLASS_MAPPINGS
from .nodes_minimax_h3_frames import NODE_DISPLAY_NAME_MAPPINGS as _H3F_DISPLAY_NAMES
from .nodes_minimax_h3_ref import NODE_CLASS_MAPPINGS as _H3R_CLASS_MAPPINGS
from .nodes_minimax_h3_ref import NODE_DISPLAY_NAME_MAPPINGS as _H3R_DISPLAY_NAMES
from .nodes_minimax_h3_regen import NODE_CLASS_MAPPINGS as _H3RG_CLASS_MAPPINGS
from .nodes_minimax_h3_regen import NODE_DISPLAY_NAME_MAPPINGS as _H3RG_DISPLAY_NAMES
from .nodes_nano_banana import NODE_CLASS_MAPPINGS as _BANANA_CLASS_MAPPINGS
from .nodes_nano_banana import NODE_DISPLAY_NAME_MAPPINGS as _BANANA_DISPLAY_NAMES
from .nodes_seedream_v5 import NODE_CLASS_MAPPINGS as _SEEDREAM_CLASS_MAPPINGS
from .nodes_seedream_v5 import NODE_DISPLAY_NAME_MAPPINGS as _SEEDREAM_DISPLAY_NAMES

NODE_CLASS_MAPPINGS = {
    **_GPT25_CLASS_MAPPINGS,
    **_GPT2_CLASS_MAPPINGS,
    **_BANANA_CLASS_MAPPINGS,
    **_SEEDREAM_CLASS_MAPPINGS,
    **_H3_CLASS_MAPPINGS,
    **_H3F_CLASS_MAPPINGS,
    **_H3R_CLASS_MAPPINGS,
    **_H3RG_CLASS_MAPPINGS,
    **_H3IR_CLASS_MAPPINGS,
    **_LLM_CLASS_MAPPINGS,
    **_ANALYZE_CLASS_MAPPINGS,
    **_LEGACY_CLASS_MAPPINGS,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    **_GPT25_DISPLAY_NAMES,
    **_GPT2_DISPLAY_NAMES,
    **_BANANA_DISPLAY_NAMES,
    **_SEEDREAM_DISPLAY_NAMES,
    **_H3_DISPLAY_NAMES,
    **_H3F_DISPLAY_NAMES,
    **_H3R_DISPLAY_NAMES,
    **_H3RG_DISPLAY_NAMES,
    **_H3IR_DISPLAY_NAMES,
    **_LLM_DISPLAY_NAMES,
    **_ANALYZE_DISPLAY_NAMES,
    **_LEGACY_DISPLAY_NAMES,
}

current_dir = os.path.dirname(os.path.abspath(__file__))
if os.path.exists(os.path.join(current_dir, "js")):
    WEB_DIRECTORY = "./js"
elif os.path.exists(os.path.join(current_dir, "web")):
    WEB_DIRECTORY = "./web"

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
if 'WEB_DIRECTORY' in locals():
    __all__.append('WEB_DIRECTORY')
