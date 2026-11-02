"""Palette and stylesheet for the terminal UI.

Colours are the ones the website and the app already use, so the CLI looks like
part of the same product rather than a different tool.
"""

BG = "#06070c"
PANEL = "#0a0c14"
PANEL_ALT = "#0d1018"
LINE = "#1a1f30"
ACCENT = "#7c5cff"
ACCENT_SOFT = "#a99bff"
BLUE = "#6d9cff"
CYAN = "#45d9f5"
TEXT = "#e6e8f0"
MUTED = "#7a8199"
OK = "#3ddc97"
WARN = "#ffb454"
ERR = "#ff5c7a"

BRAND = (
    f"[bold {ACCENT}]▌[/] [bold {TEXT}]WEHNIX[/]\n"
    f"[{MUTED}]  terminal client[/]"
)

CSS = f"""
Screen {{
    background: {BG};
    color: {TEXT};
}}

/* ------------------------------------------------------------------ chrome */

#topbar {{
    height: 1;
    background: {PANEL};
    color: {MUTED};
    padding: 0 1;
}}
#topbar-left {{ width: 1fr; }}
#topbar-right {{ width: auto; text-align: right; }}
#topbar .accent {{ color: {ACCENT_SOFT}; }}

#shell {{ height: 1fr; }}

#side {{
    width: 30;
    background: {PANEL};
    border-right: solid {LINE};
    padding: 1 0;
}}
#brand {{
    height: 3;
    padding: 0 2;
    content-align: left middle;
}}
#nav {{
    height: 1fr;
    background: transparent;
    padding: 1 1;
}}
#nav > ListItem {{
    padding: 0 1;
    color: {MUTED};
}}
#nav > ListItem.--highlight {{
    background: {ACCENT} 26%;
    color: {TEXT};
}}
#nav > ListItem > Label {{ width: 1fr; }}

#sidefoot {{
    height: auto;
    padding: 1 1;
    color: {MUTED};
}}

/* -------------------------------------------------------------------- main */

#main {{ width: 1fr; padding: 0 1; }}
#title {{
    height: 2;
    padding: 1 1 0 1;
    color: {TEXT};
}}
#title .sub {{ color: {MUTED}; }}

#content {{ height: 1fr; }}

/* ------------------------------------------------------------------ tables */

DataTable {{
    background: transparent;
    border: none;
    height: 1fr;
    padding: 0 1;
}}
DataTable > .datatable--header {{
    background: {BG};
    color: {MUTED};
    text-style: bold;
}}
DataTable > .datatable--cursor {{
    background: {ACCENT} 34%;
    color: #ffffff;
}}
DataTable > .datatable--hover {{
    background: {ACCENT} 14%;
}}
DataTable > .datatable--odd-row {{
    background: #ffffff 3%;
}}

#bottle-search {{
    display: none;
    height: 3;
    margin: 0 1;
    background: {PANEL_ALT};
    border: round {LINE};
    color: {TEXT};
}}
#bottle-search:focus {{ border: round {ACCENT}; }}

#bottle-detail {{
    height: auto;
    min-height: 7;
    max-height: 9;
    margin: 0 1 1 1;
    padding: 1 2;
    background: {PANEL_ALT};
    border: round {LINE};
    color: {MUTED};
}}
#bottle-detail .key {{ color: {MUTED}; }}
#bottle-detail .val {{ color: {TEXT}; }}
#bottle-detail .accent {{ color: {ACCENT_SOFT}; }}

/* ------------------------------------------------------------------ doctor */

#doctor-scroll {{ height: 1fr; padding: 0 1; }}
.doctor-row {{
    height: auto;
    padding: 0 1;
    background: transparent;
}}

/* -------------------------------------------------------------------- logs */

#log-view {{
    height: 1fr;
    margin: 0 1;
    background: {PANEL_ALT};
    border: round {LINE};
    padding: 0 1;
}}
#log-hint {{ height: 2; padding: 0 2; color: {MUTED}; }}

/* ---------------------------------------------------------------- storage */

#storage {{
    height: 1fr;
    padding: 0 1;
}}
.storage-card {{
    height: auto;
    margin: 1 1;
    padding: 1 2;
    background: {PANEL_ALT};
    border: round {LINE};
}}
.storage-value {{ color: {ACCENT_SOFT}; text-style: bold; }}

/* --------------------------------------------------------------- statusbar */

#status {{
    height: 1;
    background: {PANEL};
    color: {MUTED};
    padding: 0 1;
}}
#status .accent {{ color: {ACCENT_SOFT}; }}
#status .ok {{ color: {OK}; }}
#status .warn {{ color: {WARN}; }}

Footer {{
    background: {PANEL};
    color: {MUTED};
}}
Footer > .footer--key {{
    background: {ACCENT} 22%;
    color: {ACCENT_SOFT};
}}
Footer > .footer--description {{ color: {MUTED}; }}

/* ------------------------------------------------------------------ modals */

ModalScreen {{
    align: center middle;
    background: #000000 55%;
}}
#dialog {{
    width: 68;
    height: auto;
    max-height: 90%;
    background: {PANEL_ALT};
    border: round {ACCENT};
    padding: 1 2;
}}
#dialog .title {{ color: {TEXT}; text-style: bold; }}
#dialog .hint {{ color: {MUTED}; }}
#dialog Input {{
    background: {BG};
    border: round {LINE};
    color: {TEXT};
}}
#dialog Input:focus {{ border: round {ACCENT}; }}
#dialog Select {{
    background: {BG};
    margin-top: 1;
}}
#dialog-buttons {{
    height: auto;
    align-horizontal: right;
    padding-top: 1;
}}
#dialog.settings-dialog {{
    width: 76;
    max-height: 92%;
}}
#settings-form {{
    height: auto;
    max-height: 18;
}}
#settings-form Select {{
    margin-bottom: 1;
}}
#dialog-buttons Button {{
    margin-left: 1;
    min-width: 12;
}}
Button {{ background: {PANEL}; color: {TEXT}; border: none; }}
Button.-primary {{ background: {ACCENT}; color: #ffffff; }}
Button.-error {{ background: {ERR}; color: #ffffff; }}

/* -------------------------------------------------------------------- help */

#help {{
    width: 72;
    height: auto;
    max-height: 92%;
    background: {PANEL_ALT};
    border: round {ACCENT};
    padding: 1 2;
}}
#help .k {{ color: {ACCENT_SOFT}; }}
#help .d {{ color: {MUTED}; }}

/* ------------------------------------------------------------------- empty */

.empty {{
    color: {MUTED};
    padding: 2 3;
    height: auto;
}}
"""
