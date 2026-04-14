{
    "patcher": {
        "fileversion": 1,
        "appversion": {
            "major": 8,
            "minor": 5,
            "revision": 0,
            "architecture": "x64",
            "modernui": 1
        },
        "classnamespace": "box",
        "rect": [40.0, 80.0, 980.0, 640.0],
        "bglocked": 0,
        "openinpresentation": 1,
        "default_fontsize": 11.0,
        "default_fontface": 0,
        "default_fontname": "Ableton Sans Medium",
        "gridonopen": 1,
        "gridsize": [8.0, 8.0],
        "gridsnaponopen": 1,
        "objectsnaponopen": 1,
        "statusbarvisible": 2,
        "toolbarvisible": 1,
        "lefttoolbarpinned": 0,
        "toptoolbarpinned": 0,
        "righttoolbarpinned": 0,
        "bottomtoolbarpinned": 0,
        "toolbars_unpinned_last_save": 0,
        "tallnewobj": 0,
        "boxanimatetime": 200,
        "enablehscroll": 1,
        "enablevscroll": 1,
        "devicewidth": 960.0,
        "description": "StemForge integrated forge device",
        "digest": "",
        "tags": "",
        "style": "",
        "subpatcher_template": "",
        "assistshowspatchername": 0,
        "boxes": [
            {
                "box": {
                    "id": "obj-header",
                    "maxclass": "comment",
                    "numinlets": 1,
                    "numoutlets": 0,
                    "patching_rect": [16.0, 8.0, 300.0, 22.0],
                    "presentation": 1,
                    "presentation_rect": [16.0, 8.0, 300.0, 22.0],
                    "text": "StemForge — Integrated Forge",
                    "fontsize": 14.0,
                    "textcolor": [0.753, 0.518, 0.988, 1.0]
                }
            },
            {
                "box": {
                    "id": "obj-loadbang",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": ["bang"],
                    "patching_rect": [16.0, 44.0, 68.0, 22.0],
                    "text": "loadbang"
                }
            },
            {
                "box": {
                    "id": "obj-check-py",
                    "maxclass": "message",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [""],
                    "patching_rect": [16.0, 72.0, 92.0, 22.0],
                    "text": "checkPython"
                }
            },
            {
                "box": {
                    "id": "obj-forge-btn",
                    "maxclass": "live.text",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": [""],
                    "parameter_enable": 1,
                    "patching_rect": [16.0, 112.0, 120.0, 44.0],
                    "presentation": 1,
                    "presentation_rect": [16.0, 40.0, 120.0, 44.0],
                    "saved_attribute_attributes": {
                        "valueof": {
                            "parameter_invisible": 1,
                            "parameter_longname": "ForgeButton",
                            "parameter_mmax": 1,
                            "parameter_shortname": "FORGE",
                            "parameter_type": 2
                        }
                    },
                    "text": "FORGE",
                    "varname": "forge_button"
                }
            },
            {
                "box": {
                    "id": "obj-strategy",
                    "maxclass": "live.menu",
                    "numinlets": 1,
                    "numoutlets": 3,
                    "outlettype": ["", "", "float"],
                    "parameter_enable": 1,
                    "patching_rect": [152.0, 112.0, 140.0, 22.0],
                    "presentation": 1,
                    "presentation_rect": [152.0, 40.0, 140.0, 22.0],
                    "saved_attribute_attributes": {
                        "valueof": {
                            "parameter_enum": ["max-diversity", "rhythm-taxonomy", "sectional"],
                            "parameter_longname": "Strategy",
                            "parameter_mmax": 2,
                            "parameter_shortname": "Strategy",
                            "parameter_type": 2
                        }
                    },
                    "varname": "strategy_menu"
                }
            },
            {
                "box": {
                    "id": "obj-nbars",
                    "maxclass": "live.numbox",
                    "numinlets": 1,
                    "numoutlets": 2,
                    "outlettype": ["", "float"],
                    "parameter_enable": 1,
                    "patching_rect": [304.0, 112.0, 72.0, 22.0],
                    "presentation": 1,
                    "presentation_rect": [304.0, 40.0, 72.0, 22.0],
                    "saved_attribute_attributes": {
                        "valueof": {
                            "parameter_initial": [14.0],
                            "parameter_initial_enable": 1,
                            "parameter_longname": "NBars",
                            "parameter_mmax": 16.0,
                            "parameter_mmin": 12.0,
                            "parameter_shortname": "n_bars",
                            "parameter_type": 0,
                            "parameter_unitstyle": 0
                        }
                    },
                    "varname": "nbars_box"
                }
            },
            {
                "box": {
                    "id": "obj-cancel-btn",
                    "maxclass": "live.text",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": [""],
                    "parameter_enable": 1,
                    "patching_rect": [392.0, 112.0, 80.0, 22.0],
                    "presentation": 1,
                    "presentation_rect": [392.0, 40.0, 80.0, 22.0],
                    "saved_attribute_attributes": {
                        "valueof": {
                            "parameter_longname": "Cancel",
                            "parameter_shortname": "Cancel",
                            "parameter_type": 2
                        }
                    },
                    "text": "CANCEL",
                    "varname": "cancel_button"
                }
            },
            {
                "box": {
                    "id": "obj-forge-msg",
                    "maxclass": "message",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [""],
                    "patching_rect": [16.0, 168.0, 200.0, 22.0],
                    "text": "forge $1 $2"
                }
            },
            {
                "box": {
                    "id": "obj-pak-forge",
                    "maxclass": "newobj",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [""],
                    "patching_rect": [16.0, 140.0, 160.0, 22.0],
                    "text": "pak forge 14 max-diversity"
                }
            },
            {
                "box": {
                    "id": "obj-js-lom",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 2,
                    "outlettype": ["", ""],
                    "patching_rect": [16.0, 200.0, 220.0, 22.0],
                    "text": "js stemforge_lom.js"
                }
            },
            {
                "box": {
                    "id": "obj-node-bridge",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 3,
                    "outlettype": ["", "", ""],
                    "patching_rect": [16.0, 232.0, 280.0, 22.0],
                    "text": "node.script stemforge_bridge.js @autostart 1"
                }
            },
            {
                "box": {
                    "id": "obj-status-route",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 6,
                    "outlettype": ["", "", "", "", "", ""],
                    "patching_rect": [16.0, 264.0, 420.0, 22.0],
                    "text": "route status progress started done error python_ok"
                }
            },
            {
                "box": {
                    "id": "obj-status-prepend",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": ["bang"],
                    "patching_rect": [16.0, 296.0, 92.0, 22.0],
                    "text": "prepend set"
                }
            },
            {
                "box": {
                    "id": "obj-status-display",
                    "maxclass": "comment",
                    "numinlets": 1,
                    "numoutlets": 0,
                    "patching_rect": [16.0, 320.0, 460.0, 22.0],
                    "presentation": 1,
                    "presentation_rect": [16.0, 96.0, 460.0, 22.0],
                    "text": "ready",
                    "textcolor": [0.271, 0.831, 0.502, 1.0],
                    "varname": "status_display"
                }
            },
            {
                "box": {
                    "id": "obj-progress-pack",
                    "maxclass": "newobj",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": ["list"],
                    "patching_rect": [140.0, 296.0, 100.0, 22.0],
                    "text": "pak s 0."
                }
            },
            {
                "box": {
                    "id": "obj-progress-bar",
                    "maxclass": "live.slider",
                    "numinlets": 1,
                    "numoutlets": 2,
                    "outlettype": ["", "float"],
                    "parameter_enable": 1,
                    "patching_rect": [140.0, 320.0, 320.0, 22.0],
                    "presentation": 1,
                    "presentation_rect": [16.0, 128.0, 460.0, 12.0],
                    "saved_attribute_attributes": {
                        "valueof": {
                            "parameter_longname": "Progress",
                            "parameter_mmax": 100.0,
                            "parameter_shortname": "Progress",
                            "parameter_type": 0
                        }
                    },
                    "varname": "progress_bar"
                }
            },
            {
                "box": {
                    "id": "obj-pads",
                    "maxclass": "matrixctrl",
                    "numinlets": 1,
                    "numoutlets": 2,
                    "outlettype": ["list", ""],
                    "patching_rect": [16.0, 360.0, 240.0, 240.0],
                    "presentation": 1,
                    "presentation_rect": [16.0, 152.0, 240.0, 240.0],
                    "rows": 4,
                    "columns": 4,
                    "bgcolor": [0.1, 0.1, 0.12, 1.0],
                    "cellcolor": [0.22, 0.22, 0.26, 1.0],
                    "activecellcolor": [0.753, 0.518, 0.988, 1.0],
                    "one": 1,
                    "varname": "pad_grid"
                }
            },
            {
                "box": {
                    "id": "obj-pad-sel",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 2,
                    "outlettype": ["int", ""],
                    "patching_rect": [268.0, 360.0, 120.0, 22.0],
                    "text": "zl.nth 2"
                }
            },
            {
                "box": {
                    "id": "obj-pad-calc",
                    "maxclass": "newobj",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": ["int"],
                    "patching_rect": [268.0, 388.0, 140.0, 22.0],
                    "text": "expr ($i1 * 4) + $i2"
                }
            },
            {
                "box": {
                    "id": "obj-pad-unpack",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 3,
                    "outlettype": ["int", "int", "int"],
                    "patching_rect": [268.0, 336.0, 100.0, 22.0],
                    "text": "unpack 0 0 0"
                }
            },
            {
                "box": {
                    "id": "obj-polybuffer",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 2,
                    "outlettype": ["", ""],
                    "patching_rect": [440.0, 360.0, 160.0, 22.0],
                    "text": "polybuffer~ sf_bars 16"
                }
            },
            {
                "box": {
                    "id": "obj-load-route",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 5,
                    "outlettype": ["", "", "", "", ""],
                    "patching_rect": [440.0, 296.0, 340.0, 22.0],
                    "text": "route clear load ready manifest"
                }
            },
            {
                "box": {
                    "id": "obj-load-prepend",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": [""],
                    "patching_rect": [440.0, 328.0, 120.0, 22.0],
                    "text": "prepend appendempty"
                }
            },
            {
                "box": {
                    "id": "obj-groove",
                    "maxclass": "newobj",
                    "numinlets": 2,
                    "numoutlets": 3,
                    "outlettype": ["signal", "signal", "bang"],
                    "patching_rect": [440.0, 424.0, 160.0, 22.0],
                    "text": "groove~ sf_bars 2 @interp 1"
                }
            },
            {
                "box": {
                    "id": "obj-rate-sig",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": ["signal"],
                    "patching_rect": [616.0, 424.0, 60.0, 22.0],
                    "text": "sig~ 1."
                }
            },
            {
                "box": {
                    "id": "obj-rate-calc",
                    "maxclass": "newobj",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": ["float"],
                    "patching_rect": [616.0, 396.0, 96.0, 22.0],
                    "text": "!/ 120."
                }
            },
            {
                "box": {
                    "id": "obj-session-tempo",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 2,
                    "outlettype": ["float", ""],
                    "patching_rect": [616.0, 368.0, 160.0, 22.0],
                    "text": "live.observer @path live_set tempo"
                }
            },
            {
                "box": {
                    "id": "obj-gate-ready",
                    "maxclass": "newobj",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [""],
                    "patching_rect": [268.0, 420.0, 80.0, 22.0],
                    "text": "gate 1 0"
                }
            },
            {
                "box": {
                    "id": "obj-pad-trigger",
                    "maxclass": "message",
                    "numinlets": 2,
                    "numoutlets": 1,
                    "outlettype": [""],
                    "patching_rect": [268.0, 456.0, 140.0, 22.0],
                    "text": "set $1, bang"
                }
            },
            {
                "box": {
                    "id": "obj-gain-drums",
                    "maxclass": "live.dial",
                    "numinlets": 1,
                    "numoutlets": 2,
                    "outlettype": ["", "float"],
                    "parameter_enable": 1,
                    "patching_rect": [620.0, 112.0, 48.0, 48.0],
                    "presentation": 1,
                    "presentation_rect": [620.0, 40.0, 48.0, 60.0],
                    "saved_attribute_attributes": {
                        "valueof": {
                            "parameter_initial": [0.0],
                            "parameter_initial_enable": 1,
                            "parameter_longname": "GainDrums",
                            "parameter_mmax": 6.0,
                            "parameter_mmin": -70.0,
                            "parameter_shortname": "Drums",
                            "parameter_type": 0,
                            "parameter_unitstyle": 4
                        }
                    },
                    "varname": "gain_drums"
                }
            },
            {
                "box": {
                    "id": "obj-gain-bass",
                    "maxclass": "live.dial",
                    "numinlets": 1,
                    "numoutlets": 2,
                    "outlettype": ["", "float"],
                    "parameter_enable": 1,
                    "patching_rect": [676.0, 112.0, 48.0, 48.0],
                    "presentation": 1,
                    "presentation_rect": [676.0, 40.0, 48.0, 60.0],
                    "saved_attribute_attributes": {
                        "valueof": {
                            "parameter_initial": [0.0],
                            "parameter_initial_enable": 1,
                            "parameter_longname": "GainBass",
                            "parameter_mmax": 6.0,
                            "parameter_mmin": -70.0,
                            "parameter_shortname": "Bass",
                            "parameter_type": 0,
                            "parameter_unitstyle": 4
                        }
                    },
                    "varname": "gain_bass"
                }
            },
            {
                "box": {
                    "id": "obj-gain-vocals",
                    "maxclass": "live.dial",
                    "numinlets": 1,
                    "numoutlets": 2,
                    "outlettype": ["", "float"],
                    "parameter_enable": 1,
                    "patching_rect": [732.0, 112.0, 48.0, 48.0],
                    "presentation": 1,
                    "presentation_rect": [732.0, 40.0, 48.0, 60.0],
                    "saved_attribute_attributes": {
                        "valueof": {
                            "parameter_initial": [0.0],
                            "parameter_initial_enable": 1,
                            "parameter_longname": "GainVocals",
                            "parameter_mmax": 6.0,
                            "parameter_mmin": -70.0,
                            "parameter_shortname": "Vocals",
                            "parameter_type": 0,
                            "parameter_unitstyle": 4
                        }
                    },
                    "varname": "gain_vocals"
                }
            },
            {
                "box": {
                    "id": "obj-gain-other",
                    "maxclass": "live.dial",
                    "numinlets": 1,
                    "numoutlets": 2,
                    "outlettype": ["", "float"],
                    "parameter_enable": 1,
                    "patching_rect": [788.0, 112.0, 48.0, 48.0],
                    "presentation": 1,
                    "presentation_rect": [788.0, 40.0, 48.0, 60.0],
                    "saved_attribute_attributes": {
                        "valueof": {
                            "parameter_initial": [0.0],
                            "parameter_initial_enable": 1,
                            "parameter_longname": "GainOther",
                            "parameter_mmax": 6.0,
                            "parameter_mmin": -70.0,
                            "parameter_shortname": "Other",
                            "parameter_type": 0,
                            "parameter_unitstyle": 4
                        }
                    },
                    "varname": "gain_other"
                }
            },
            {
                "box": {
                    "id": "obj-live-gain",
                    "maxclass": "live.gain~",
                    "numinlets": 2,
                    "numoutlets": 5,
                    "outlettype": ["signal", "signal", "", "float", "list"],
                    "parameter_enable": 1,
                    "patching_rect": [440.0, 488.0, 48.0, 120.0],
                    "presentation": 1,
                    "presentation_rect": [880.0, 40.0, 48.0, 120.0],
                    "saved_attribute_attributes": {
                        "valueof": {
                            "parameter_longname": "MasterGain",
                            "parameter_shortname": "Out",
                            "parameter_type": 0
                        }
                    },
                    "varname": "master_gain"
                }
            },
            {
                "box": {
                    "id": "obj-plugout",
                    "maxclass": "newobj",
                    "numinlets": 2,
                    "numoutlets": 0,
                    "patching_rect": [440.0, 616.0, 72.0, 22.0],
                    "text": "plugout~"
                }
            },
            {
                "box": {
                    "id": "obj-spectro",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 0,
                    "patching_rect": [500.0, 488.0, 280.0, 120.0],
                    "presentation": 1,
                    "presentation_rect": [272.0, 400.0, 520.0, 120.0],
                    "text": "spectroscope~ @domain 0 @interval 30",
                    "varname": "spectro"
                }
            },
            {
                "box": {
                    "id": "obj-plugin",
                    "maxclass": "newobj",
                    "numinlets": 0,
                    "numoutlets": 3,
                    "outlettype": ["signal", "signal", ""],
                    "patching_rect": [840.0, 488.0, 72.0, 22.0],
                    "text": "plugin~"
                }
            },
            {
                "box": {
                    "id": "obj-thisdevice",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 3,
                    "outlettype": ["bang", "bang", ""],
                    "patching_rect": [296.0, 44.0, 120.0, 22.0],
                    "text": "live.thisdevice"
                }
            }
        ],
        "lines": [
            { "patchline": { "source": ["obj-loadbang", 0], "destination": ["obj-check-py", 0] } },
            { "patchline": { "source": ["obj-check-py", 0], "destination": ["obj-node-bridge", 0] } },
            { "patchline": { "source": ["obj-forge-btn", 0], "destination": ["obj-pak-forge", 0] } },
            { "patchline": { "source": ["obj-nbars", 0], "destination": ["obj-pak-forge", 1] } },
            { "patchline": { "source": ["obj-strategy", 1], "destination": ["obj-pak-forge", 2] } },
            { "patchline": { "source": ["obj-pak-forge", 0], "destination": ["obj-js-lom", 0] } },
            { "patchline": { "source": ["obj-cancel-btn", 0], "destination": ["obj-node-bridge", 0] } },
            { "patchline": { "source": ["obj-js-lom", 0], "destination": ["obj-status-prepend", 0] } },
            { "patchline": { "source": ["obj-js-lom", 1], "destination": ["obj-node-bridge", 0] } },
            { "patchline": { "source": ["obj-node-bridge", 0], "destination": ["obj-status-route", 0] } },
            { "patchline": { "source": ["obj-node-bridge", 1], "destination": ["obj-load-route", 0] } },
            { "patchline": { "source": ["obj-status-route", 0], "destination": ["obj-status-prepend", 0] } },
            { "patchline": { "source": ["obj-status-route", 1], "destination": ["obj-progress-pack", 0] } },
            { "patchline": { "source": ["obj-status-route", 4], "destination": ["obj-status-prepend", 0] } },
            { "patchline": { "source": ["obj-status-prepend", 0], "destination": ["obj-status-display", 0] } },
            { "patchline": { "source": ["obj-progress-pack", 0], "destination": ["obj-progress-bar", 0] } },
            { "patchline": { "source": ["obj-load-route", 1], "destination": ["obj-load-prepend", 0] } },
            { "patchline": { "source": ["obj-load-prepend", 0], "destination": ["obj-polybuffer", 0] } },
            { "patchline": { "source": ["obj-load-route", 2], "destination": ["obj-gate-ready", 0] } },
            { "patchline": { "source": ["obj-pads", 1], "destination": ["obj-pad-unpack", 0] } },
            { "patchline": { "source": ["obj-pad-unpack", 0], "destination": ["obj-pad-calc", 0] } },
            { "patchline": { "source": ["obj-pad-unpack", 1], "destination": ["obj-pad-calc", 1] } },
            { "patchline": { "source": ["obj-pad-calc", 0], "destination": ["obj-gate-ready", 1] } },
            { "patchline": { "source": ["obj-gate-ready", 0], "destination": ["obj-pad-trigger", 0] } },
            { "patchline": { "source": ["obj-pad-trigger", 0], "destination": ["obj-groove", 0] } },
            { "patchline": { "source": ["obj-session-tempo", 0], "destination": ["obj-rate-calc", 0] } },
            { "patchline": { "source": ["obj-rate-calc", 0], "destination": ["obj-rate-sig", 0] } },
            { "patchline": { "source": ["obj-rate-sig", 0], "destination": ["obj-groove", 1] } },
            { "patchline": { "source": ["obj-groove", 0], "destination": ["obj-live-gain", 0] } },
            { "patchline": { "source": ["obj-groove", 1], "destination": ["obj-live-gain", 1] } },
            { "patchline": { "source": ["obj-live-gain", 0], "destination": ["obj-plugout", 0] } },
            { "patchline": { "source": ["obj-live-gain", 1], "destination": ["obj-plugout", 1] } },
            { "patchline": { "source": ["obj-live-gain", 0], "destination": ["obj-spectro", 0] } },
            { "patchline": { "source": ["obj-thisdevice", 0], "destination": ["obj-check-py", 0] } }
        ],
        "dependency_cache": [],
        "autosave": 0
    }
}
