"""New workspace screens introduced by the UI redesign (Dashboard, Settings).

Kept separate from ``web.tabs`` (the ported legacy screens) so the new read-only
monitoring/config views have a clean home. Importing this package does not pull in
gradio until a ``render()`` is called inside a ``gr.Blocks`` context.
"""
