"""Design tokens, global CSS, and fonts for the workspace UI.

This module is pure data + string builders (no gradio import) so it can be unit
tested. The app ships a single "Carbon" theme: its CSS custom properties are
declared once on ``#ck-root`` and every component style references them via
``var(--token)``.
"""

from __future__ import annotations

_FONTS_HEAD = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link rel="stylesheet" '
    'href="https://fonts.googleapis.com/css2?'
    "family=IBM+Plex+Sans:wght@400;500;600;700&"
    'family=IBM+Plex+Mono:wght@400;500;600&display=swap">'
)

# Layout, component classes, and animations. Colours come from the active theme's
# CSS variables. Gradio's default chrome (container max-width, block borders, gaps)
# is neutralised inside #ck-root so the custom grid shows through.
_BASE_CSS = """
/* ---- gradio container reset ---- */
#ck-style-inject { display: none !important; }
gradio-app { background: var(--bg); }
.gradio-container { max-width: 100% !important; padding: 0 !important; margin: 0 !important; }
footer { display: none !important; }

#ck-root {
  /* Carbon theme tokens. Every component style references these via var(--token). */
  --bg: #14171c;
  --surface: #1b1f25;
  --surface2: #232830;
  --border: #2e343d;
  --text: #e7e9ec;
  --dim: #9aa1ab;
  --faint: #6b7280;
  --accent: #3fd9a8;
  --accent-dim: #1f6b56;
  --accent-soft: #16302a;
  --pos: #3fd98a;
  --neg: #f0616d;
  --paper: #f0b54a;
  --live: #ef4658;
  --live-glow: rgba(239,70,88,0.5);
  --shadow: rgba(0,0,0,0.4);
  /* Fixed to the viewport (not min-height) so the body row scrolls internally and
     the terminal stays pinned at the bottom. With min-height, tall screen content
     grew the page and pushed the terminal far below the fold. */
  min-width: 1180px; height: 100vh; overflow: hidden;
  display: grid; grid-template-rows: auto auto 1fr auto;
  background: var(--bg); color: var(--text);
  font-family: 'IBM Plex Sans', system-ui, sans-serif; font-size: 13px;
}
#ck-root .gap { gap: 0 !important; }
#ck-root .block { border: none !important; background: transparent !important;
  box-shadow: none !important; padding: 0 !important; }
#ck-root .form { border: none !important; background: transparent !important; }
.ck-mono, #ck-root .ck-mono { font-family: 'IBM Plex Mono', monospace; }
.ck-pos { color: var(--pos); }
.ck-neg { color: var(--neg); }

/* ---- header ---- */
.ck-header { display: flex; align-items: center; gap: 18px; height: 50px;
  padding: 0 18px; border-bottom: 1px solid var(--border); background: var(--surface); }
.ck-logo-sq { width: 22px; height: 22px; border-radius: 6px; background: var(--accent);
  display: inline-flex; align-items: center; justify-content: center; color: #0a1410;
  font-weight: 700; font-size: 13px; font-family: 'IBM Plex Mono', monospace; }
.ck-wordmark { font-weight: 600; font-size: 15px; letter-spacing: -0.2px; }
.ck-pill { font-family: 'IBM Plex Mono', monospace; font-size: 10px; color: var(--faint);
  border: 1px solid var(--border); border-radius: 4px; padding: 1px 5px; }
.ck-conn-chip { display: inline-flex; align-items: center; gap: 7px; padding: 4px 10px;
  border: 1px solid var(--border); border-radius: 7px; background: var(--bg); font-size: 11px; }
.ck-dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; }
.ck-dot-pos { background: var(--pos); }
.ck-dot-faint { background: var(--faint); }
.ck-balance-l { font-size: 10px; color: var(--faint); text-transform: uppercase;
  letter-spacing: 0.5px; }
.ck-balance-v { font-family: 'IBM Plex Mono', monospace; font-weight: 600; font-size: 15px; }
.ck-synced { display: inline-flex; align-items: center; gap: 6px; padding: 5px 9px;
  border: 1px solid var(--border); border-radius: 7px; font-size: 11px; color: var(--dim); }

/* ---- mode banner ---- */
.ck-banner { display: flex; align-items: center; gap: 11px; min-height: 34px;
  padding: 4px 18px; font-size: 12px; }
.ck-banner b { font-weight: 700; font-size: 13px; letter-spacing: 0.3px; }
.ck-banner span.ck-banner-sub { opacity: 0.85; }
.ck-banner-paper { background: rgba(240,181,74,0.13); border-bottom: 1px solid var(--border);
  color: var(--paper); }
.ck-banner-paper .ck-dot { background: var(--paper); }
.ck-banner-live { background: rgba(239,70,88,0.16); border-bottom: 1px solid var(--live);
  color: var(--live); }
.ck-banner-live .ck-dot { background: var(--live); }
.ck-pulse { animation: ck-pulse 1.6s infinite; }
#ck-banner-row { align-items: center; gap: 0; }
#ck-banner { flex: 1; }
.ck-banner-btn { margin-right: 14px; }
.ck-banner-btn button, button.ck-banner-btn { border-radius: 7px !important; padding: 6px 12px !important; }

/* ---- body grid ---- */
/* !important + min-width:0 override Gradio's .row flex + per-column min-width so the
   three tracks (sidebar | main | rail) size to the grid, not to content. */
.ck-body { display: grid !important; grid-template-columns: 212px 1fr 296px !important;
  min-height: 0; gap: 0 !important; }
/* min-height:0 lets each column shrink inside the fixed-height body row; overflow-y
   makes them scroll internally instead of growing the page (which hid the terminal). */
.ck-body > * { min-width: 0 !important; min-height: 0 !important; overflow-y: auto; }
.ck-sidebar { border-right: 1px solid var(--border); background: var(--surface);
  padding: 14px 10px; display: flex; flex-direction: column; gap: 4px; }
.ck-nav-group-label { font-size: 9.5px; font-weight: 600; letter-spacing: 1.2px;
  color: var(--faint); text-transform: uppercase; padding: 13px 9px 5px; }
.ck-nav-item button, button.ck-nav-item { display: flex !important; align-items: center; gap: 9px;
  width: 100%; padding: 8px 9px !important; border: none !important; border-radius: 8px !important;
  text-align: left !important; justify-content: flex-start !important;
  font-size: 13px !important; font-weight: 500 !important; background: transparent !important;
  color: var(--dim) !important; box-shadow: none !important; }
.ck-nav-item.ck-nav-active button, button.ck-nav-item.ck-nav-active {
  background: var(--accent-soft) !important; color: var(--text) !important; font-weight: 600 !important; }

/* ---- main canvas ---- */
.ck-main { min-width: 0; overflow-y: auto; }
.ck-screen-header { display: flex; align-items: flex-end; gap: 14px;
  padding: 15px 26px 12px; border-bottom: 1px solid var(--border); background: var(--bg); }
.ck-screen-title { font-size: 20px; font-weight: 600; letter-spacing: -0.3px; }
.ck-screen-sub { font-size: 12.5px; color: var(--dim); margin-top: 3px; max-width: 640px; }
.ck-screen-synced { font-size: 11px; color: var(--faint); display: inline-flex;
  align-items: center; gap: 7px; }
.ck-screen-body { padding: 22px 26px 40px; animation: ck-fadein 0.25s; }
.ck-col-300 { max-width: 320px; display: flex; flex-direction: column; gap: 14px; }
.ck-col-320 { max-width: 340px; display: flex; flex-direction: column; gap: 14px; }
.ck-col-main { display: flex; flex-direction: column; gap: 16px; min-width: 0; flex: 1; }
.ck-screen-cols { gap: 20px !important; align-items: flex-start; }

/* ---- cards & metrics ---- */
.ck-card { background: var(--surface); border: 1px solid var(--border); border-radius: 11px;
  padding: 14px 16px; }
.ck-card-title { font-size: 12.5px; font-weight: 600; margin-bottom: 10px; }
.ck-section-label { font-size: 11px; font-weight: 600; letter-spacing: 0.4px;
  color: var(--dim); text-transform: uppercase; }
.ck-metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.ck-metric { background: var(--surface); border: 1px solid var(--border); border-radius: 11px;
  padding: 13px 14px; }
.ck-metric-label { font-size: 10.5px; color: var(--faint); text-transform: uppercase;
  letter-spacing: 0.5px; }
.ck-metric-value { font-family: 'IBM Plex Mono', monospace; font-weight: 600; font-size: 21px;
  margin-top: 4px; }
.ck-metric-sub { font-size: 11px; color: var(--faint); margin-top: 2px; }
.ck-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.ck-table th { text-align: left; padding: 0 0 8px; font-weight: 500; color: var(--faint);
  font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.5px; }
.ck-table td { padding: 9px 0; border-top: 1px solid var(--border); }
.ck-num { font-family: 'IBM Plex Mono', monospace; text-align: right; }
.ck-coin { width: 28px; height: 28px; border-radius: 7px; flex: none; display: inline-flex;
  align-items: center; justify-content: center; font-family: 'IBM Plex Mono', monospace;
  font-weight: 700; font-size: 9.5px; color: #fff; }
.ck-stats-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.ck-stat-value { font-family: 'IBM Plex Mono', monospace; font-size: 18px; font-weight: 600;
  margin-top: 3px; }
.ck-kv-row { display: flex; justify-content: space-between; padding: 6px 0;
  border-bottom: 1px solid var(--border); font-size: 12px; }
.ck-pill-run { font-family: 'IBM Plex Mono', monospace; font-size: 10.5px; font-weight: 600;
  padding: 2px 8px; border-radius: 5px; color: var(--pos); background: var(--accent-soft); }
.ck-pill-idle { font-family: 'IBM Plex Mono', monospace; font-size: 10.5px; font-weight: 600;
  padding: 2px 8px; border-radius: 5px; color: var(--faint); background: var(--surface2); }

/* ---- status rail ---- */
.ck-rail { border-left: 1px solid var(--border); background: var(--surface);
  padding: 16px 15px; display: flex; flex-direction: column; gap: 16px; }
.ck-rail-label { font-size: 10px; font-weight: 600; letter-spacing: 1px; color: var(--faint);
  text-transform: uppercase; margin-bottom: 8px; }
.ck-rail-card { border: 1px solid var(--border); border-radius: 9px; padding: 11px 12px;
  background: var(--bg); }
.ck-rail-card.ck-running { background: var(--accent-soft); border-color: var(--accent-dim); }
.ck-rail-row { display: flex; justify-content: space-between; padding: 5px 0; font-size: 12px; }

/* ---- docked terminal ---- */
.ck-term-head { display: flex; align-items: center; gap: 12px; height: 34px; padding: 0 14px;
  border-top: 1px solid var(--border); background: var(--surface); }
.ck-term-title { font-size: 11.5px; font-weight: 600; }
.ck-term-meta { font-family: 'IBM Plex Mono', monospace; font-size: 10.5px; color: var(--faint); }
.ck-term-body { height: 150px; overflow-y: auto; padding: 9px 14px; background: var(--bg);
  font-family: 'IBM Plex Mono', monospace; font-size: 11.5px; }
.ck-term-body.ck-collapsed { height: 0; padding: 0 14px; overflow: hidden; }
.ck-term-line { display: flex; gap: 10px; padding: 1.5px 0; line-height: 1.5; }
.ck-term-tm { color: var(--faint); flex: none; }
.ck-term-src { flex: none; width: 62px; }
.ck-src-sys { color: var(--accent); }
.ck-src-data { color: #7aa2f7; }
.ck-src-bt { color: #bb9af7; }
.ck-src-pf { color: var(--accent); }
.ck-src-live { color: var(--paper); }
.ck-lvl-ok { color: var(--pos); }
.ck-lvl-info { color: var(--dim); }
.ck-lvl-warn { color: var(--paper); }
.ck-lvl-err { color: var(--neg); }
.ck-term-cursor { display: flex; gap: 8px; padding: 2px 0; color: var(--accent); }
.ck-blink-block { width: 7px; height: 14px; background: var(--accent); display: inline-block;
  animation: ck-blink 1s infinite; }
.ck-chip button, button.ck-chip { font-family: 'IBM Plex Mono', monospace; font-size: 10.5px !important;
  border-radius: 5px !important; padding: 3px 8px !important; background: transparent !important;
  color: var(--faint) !important; border: none !important; min-width: 0 !important; box-shadow: none !important; }
.ck-chip.ck-chip-active button, button.ck-chip.ck-chip-active {
  background: var(--surface2) !important; color: var(--text) !important; }

/* ---- buttons ---- */
.ck-btn-primary button, button.ck-btn-primary { background: var(--accent) !important;
  color: #0a1410 !important; border: none !important; border-radius: 8px !important;
  font-weight: 600 !important; }
.ck-btn-secondary button, button.ck-btn-secondary { background: var(--surface2) !important;
  color: var(--text) !important; border: 1px solid var(--border) !important; border-radius: 8px !important; }
.ck-btn-live button, button.ck-btn-live { background: var(--live) !important; color: #fff !important;
  border: none !important; border-radius: 8px !important; font-weight: 600 !important; }
.ck-btn-stop button, button.ck-btn-stop { background: var(--neg) !important; color: #fff !important;
  border: none !important; border-radius: 8px !important; font-weight: 600 !important; }

/* ---- verdict / badges ---- */
.ck-verdict { font-family: 'IBM Plex Mono', monospace; font-weight: 700; font-size: 30px; }
.ck-badge { font-family: 'IBM Plex Mono', monospace; font-size: 10.5px; font-weight: 600;
  padding: 2px 7px; border-radius: 4px; }

/* ---- confirm modal overlay ---- */
/* Always display:flex (so Gradio lays the card out to its real size); the hidden
   state uses visibility/opacity rather than display:none, which would collapse the
   card to 0x0 and never recompute when shown via a class toggle. */
.ck-modal { position: fixed; inset: 0; z-index: 100; background: rgba(0,0,0,0.62);
  display: flex; align-items: center; justify-content: center; animation: ck-fadein 0.15s; }
/* Gradio renders the card correctly when the Group is opened with visible=True, but
   gr.update(visible=False) does not close a Group once shown — so closing is done by
   a js class toggle that forces display:none. */
.ck-modal.ck-force-hidden { display: none !important; }
.ck-modal-card { background: var(--surface); border: 1px solid var(--live); border-radius: 14px;
  padding: 24px; width: 440px; box-shadow: 0 24px 60px rgba(0,0,0,0.5); }
.ck-modal-icon { width: 34px; height: 34px; border-radius: 9px; background: var(--live);
  display: inline-flex; align-items: center; justify-content: center; color: #fff;
  font-weight: 700; font-size: 18px; font-family: 'IBM Plex Mono', monospace; }
.ck-modal-title { font-weight: 700; font-size: 16px; }
.ck-modal-body { font-size: 13px; color: var(--dim); line-height: 1.55; }

/* ---- animations ---- */
@keyframes ck-pulse {
  0% { box-shadow: 0 0 0 0 var(--live-glow); }
  70% { box-shadow: 0 0 0 7px transparent; }
  100% { box-shadow: 0 0 0 0 transparent; }
}
@keyframes ck-blink { 0%, 60% { opacity: 1; } 61%, 100% { opacity: 0.25; } }
@keyframes ck-fadein { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
"""


def build_css() -> str:
    """Return the global CSS string for ``gr.Blocks(css=...)``.

    The single Carbon theme's CSS custom properties are declared on ``#ck-root``
    directly in the base CSS, so this just returns the layout/component CSS.
    """
    return _BASE_CSS


def fonts_head() -> str:
    """Return ``<link>`` tags for IBM Plex Sans + Mono (for ``gr.Blocks(head=...)``)."""
    return _FONTS_HEAD


def boot_js() -> str:
    """Return a JS function for ``gr.Blocks(js=...)`` run on app load.

    Forces Gradio's own components into dark mode and installs a small observer
    that keeps the docked terminal scrolled to the newest line.
    """
    return (
        "() => {"
        # Force Gradio's own components into dark mode so native inputs/markdown/code
        # match the Carbon surface instead of the default light theme.
        " document.body.classList.add('dark');"
        " const app = document.querySelector('gradio-app');"
        " if (app) app.classList.add('dark');"
        " const stick = () => { const el = document.getElementById('ck-term');"
        " if (el) el.scrollTop = el.scrollHeight; };"
        " setInterval(stick, 600);"
        "}"
    )
