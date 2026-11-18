"""Model providers. All model calls go through this package (mock, kie, openrouter, elevenlabs)."""


class GenerationError(RuntimeError):
    """The service could not make the image or clip (it failed on its side; nothing was charged).
    The pipeline records it on the take and moves on, unlike a budget stop."""
