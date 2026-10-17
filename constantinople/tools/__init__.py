"""Tool registry. A workflow step with kind: tool names one of these as "module.function".
Every tool takes (ctx, **args) and returns a dict; the runner costs and logs it.
Each module runs for real when its keys are set and DRY_RUN=false, otherwise returns realistic fakes."""
import importlib

def resolve(name: str):
    mod, fn = name.rsplit(".", 1)
    return getattr(importlib.import_module(f"{__name__}.{mod}"), fn)
