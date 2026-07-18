import os
from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

current_dir = os.path.dirname(os.path.abspath(__file__))
if os.path.exists(os.path.join(current_dir, "js")):
    WEB_DIRECTORY = "./js"
elif os.path.exists(os.path.join(current_dir, "web")):
    WEB_DIRECTORY = "./web"

__all__ =['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
if 'WEB_DIRECTORY' in locals():
    __all__.append('WEB_DIRECTORY')