{
	"patcher": {
		"fileversion": 1,
		"appversion": {
			"major": 9,
			"minor": 0,
			"revision": 8,
			"architecture": "x64",
			"modernui": 1
		},
		"classnamespace": "box",
		"rect": [
			40.0,
			80.0,
			480.0,
			340.0
		],
		"openinpresentation": 1,
		"default_fontsize": 11.0,
		"default_fontface": 0,
		"default_fontname": "Ableton Sans Medium",
		"gridonopen": 1,
		"gridsize": [
			8.0,
			8.0
		],
		"gridsnaponopen": 1,
		"objectsnaponopen": 1,
		"statusbarvisible": 2,
		"toolbarvisible": 1,
		"devicewidth": 400.0,
		"description": "StemForge \u2014 ONNX-native stem split + beat slice",
		"digest": "",
		"tags": "",
		"style": "",
		"boxes": [
			{
				"box": {
					"id": "obj-title",
					"maxclass": "comment",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [
						8,
						4,
						200.0,
						22.0
					],
					"presentation": 1,
					"presentation_rect": [
						8,
						4,
						200.0,
						22.0
					],
					"text": "StemForge",
					"fontsize": 16.0,
					"textcolor": [
						0.753,
						0.518,
						0.988,
						1.0
					]
				}
			},
			{
				"box": {
					"id": "obj-browse-btn",
					"maxclass": "textbutton",
					"numinlets": 1,
					"numoutlets": 3,
					"patching_rect": [
						8,
						28,
						80,
						24
					],
					"outlettype": [
						"",
						"",
						"int"
					],
					"presentation": 1,
					"presentation_rect": [
						8,
						28,
						80,
						24
					],
					"text": "Browse...",
					"fontsize": 11.0
				}
			},
			{
				"box": {
					"id": "obj-opendialog",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 2,
					"patching_rect": [
						8,
						56,
						150.0,
						22.0
					],
					"outlettype": [
						"",
						"bang"
					],
					"text": "opendialog sound"
				}
			},
			{
				"box": {
					"id": "obj-path-convert",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 5,
					"patching_rect": [
						8,
						82,
						220.0,
						22.0
					],
					"outlettype": [
						"",
						"",
						"",
						"",
						""
					],
					"text": "regexp (.+):(/.*) @substitute %2"
				}
			},
			{
				"box": {
					"id": "obj-file-path-msg",
					"maxclass": "message",
					"numinlets": 2,
					"numoutlets": 1,
					"patching_rect": [
						8,
						108,
						80,
						20.0
					],
					"outlettype": [
						""
					],
					"presentation": 1,
					"presentation_rect": [
						8,
						56,
						80,
						20.0
					],
					"text": ""
				}
			},
			{
				"box": {
					"id": "obj-load-btn",
					"maxclass": "textbutton",
					"numinlets": 1,
					"numoutlets": 3,
					"patching_rect": [
						96,
						28,
						72,
						24
					],
					"outlettype": [
						"",
						"",
						"int"
					],
					"presentation": 1,
					"presentation_rect": [
						96,
						28,
						72,
						24
					],
					"text": "Load",
					"fontsize": 11.0
				}
			},
			{
				"box": {
					"id": "obj-load-trigger",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 1,
					"patching_rect": [
						176,
						32,
						30.0,
						22.0
					],
					"outlettype": [
						"bang"
					],
					"text": "t b"
				}
			},
			{
				"box": {
					"id": "obj-load-seq",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 2,
					"patching_rect": [
						96,
						56,
						40.0,
						22.0
					],
					"outlettype": [
						"bang",
						"bang"
					],
					"text": "t b b"
				}
			},
			{
				"box": {
					"id": "obj-load-read-msg",
					"maxclass": "message",
					"numinlets": 2,
					"numoutlets": 1,
					"patching_rect": [
						176,
						56,
						60.0,
						22.0
					],
					"outlettype": [
						""
					],
					"text": "read"
				}
			},
			{
				"box": {
					"id": "obj-load-dict",
					"maxclass": "newobj",
					"numinlets": 2,
					"numoutlets": 4,
					"patching_rect": [
						176,
						82,
						140.0,
						22.0
					],
					"outlettype": [
						"dictionary",
						"",
						"",
						""
					],
					"text": "dict sf_manifest"
				}
			},
			{
				"box": {
					"id": "obj-load-dict-msg",
					"maxclass": "message",
					"numinlets": 2,
					"numoutlets": 1,
					"patching_rect": [
						96,
						82,
						180.0,
						22.0
					],
					"outlettype": [
						""
					],
					"text": "loadFromDict sf_manifest"
				}
			},
			{
				"box": {
					"id": "obj-backend",
					"maxclass": "umenu",
					"numinlets": 1,
					"numoutlets": 3,
					"patching_rect": [
						8,
						108,
						136.0,
						22.0
					],
					"outlettype": [
						"int",
						"",
						""
					],
					"presentation": 1,
					"presentation_rect": [
						8,
						108,
						136.0,
						22.0
					],
					"items": "auto demucs lalal musicai",
					"arrow": 1,
					"autopopulate": 1,
					"prefix": "Backend: "
				}
			},
			{
				"box": {
					"id": "obj-preset",
					"maxclass": "umenu",
					"numinlets": 1,
					"numoutlets": 3,
					"patching_rect": [
						152,
						108,
						136.0,
						22.0
					],
					"outlettype": [
						"int",
						"",
						""
					],
					"presentation": 1,
					"presentation_rect": [
						152,
						108,
						136.0,
						22.0
					],
					"items": "",
					"arrow": 1,
					"prefix": "Preset: "
				}
			},
			{
				"box": {
					"id": "obj-preset-dict",
					"maxclass": "newobj",
					"numinlets": 2,
					"numoutlets": 4,
					"patching_rect": [
						152,
						138,
						140.0,
						22.0
					],
					"outlettype": [
						"dictionary",
						"",
						"",
						""
					],
					"text": "dict sf_preset"
				}
			},
			{
				"box": {
					"id": "obj-preset-prepend",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 1,
					"patching_rect": [
						292,
						108,
						140.0,
						22.0
					],
					"outlettype": [
						""
					],
					"text": "prepend loadPreset"
				}
			},
			{
				"box": {
					"id": "obj-scan-deferlow",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 1,
					"patching_rect": [
						292,
						138,
						60.0,
						22.0
					],
					"outlettype": [
						""
					],
					"text": "deferlow"
				}
			},
			{
				"box": {
					"id": "obj-scan-presets-msg",
					"maxclass": "message",
					"numinlets": 2,
					"numoutlets": 1,
					"patching_rect": [
						292,
						164,
						100.0,
						22.0
					],
					"outlettype": [
						""
					],
					"text": "scanPresets"
				}
			},
			{
				"box": {
					"id": "obj-slice",
					"maxclass": "live.toggle",
					"numinlets": 1,
					"numoutlets": 1,
					"patching_rect": [
						300,
						108,
						22.0,
						22.0
					],
					"outlettype": [
						""
					],
					"presentation": 1,
					"presentation_rect": [
						300,
						108,
						22.0,
						22.0
					],
					"parameter_enable": 1,
					"saved_attribute_attributes": {
						"valueof": {
							"parameter_initial_enable": 1,
							"parameter_initial": [
								1
							]
						}
					}
				}
			},
			{
				"box": {
					"id": "obj-progress-bar",
					"maxclass": "live.slider",
					"numinlets": 1,
					"numoutlets": 2,
					"patching_rect": [
						8,
						60,
						384,
						16
					],
					"outlettype": [
						"",
						"float"
					],
					"presentation": 1,
					"presentation_rect": [
						8,
						60,
						384,
						16
					],
					"saved_attribute_attributes": {
						"valueof": {
							"parameter_longname": "StemForge Progress",
							"parameter_shortname": "Progress",
							"parameter_type": 0,
							"parameter_mmin": 0.0,
							"parameter_mmax": 100.0,
							"parameter_initial_enable": 1,
							"parameter_initial": [
								0
							]
						}
					},
					"orientation": 0,
					"parameter_enable": 1
				}
			},
			{
				"box": {
					"id": "obj-status-text",
					"maxclass": "live.comment",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [
						8,
						80,
						376,
						22.0
					],
					"presentation": 1,
					"presentation_rect": [
						8,
						80,
						376,
						22.0
					],
					"text": "idle",
					"fontsize": 11.0,
					"textcolor": [
						0.9,
						0.9,
						0.9,
						1.0
					]
				}
			},
			{
				"box": {
					"id": "obj-split-button",
					"maxclass": "textbutton",
					"numinlets": 1,
					"numoutlets": 3,
					"patching_rect": [
						336,
						108,
						72.0,
						28.0
					],
					"outlettype": [
						"",
						"",
						"int"
					],
					"presentation": 1,
					"presentation_rect": [
						336,
						108,
						72.0,
						28.0
					],
					"text": "Split",
					"fontsize": 12.0,
					"bgoncolor": [
						0.9,
						0.35,
						0.15,
						1.0
					]
				}
			},
			{
				"box": {
					"id": "obj-cmd-fmt",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 1,
					"patching_rect": [
						100,
						148,
						480.0,
						22.0
					],
					"outlettype": [
						""
					],
					"text": "sprintf /usr/local/bin/stemforge-native split %s --json-events --variant ft-fused"
				}
			},
			{
				"box": {
					"id": "obj-trigger-bang",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 1,
					"patching_rect": [
						416,
						112,
						30.0,
						22.0
					],
					"outlettype": [
						"bang"
					],
					"text": "t b"
				}
			},
			{
				"box": {
					"id": "obj-bridge",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 2,
					"patching_rect": [
						16.0,
						180,
						80.0,
						22.0
					],
					"outlettype": [
						"",
						"bang"
					],
					"text": "shell"
				}
			},
			{
				"box": {
					"id": "obj-ndjson-parser",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 1,
					"patching_rect": [
						16.0,
						210,
						240.0,
						22.0
					],
					"outlettype": [
						""
					],
					"text": "js stemforge_ndjson_parser.v0.js",
					"saved_object_attributes": {
						"filename": "stemforge_ndjson_parser.v0.js",
						"parameter_enable": 0
					}
				}
			},
			{
				"box": {
					"id": "obj-route-events",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 8,
					"patching_rect": [
						16.0,
						240,
						420.0,
						22.0
					],
					"outlettype": [
						"",
						"",
						"",
						"",
						"",
						"",
						"",
						""
					],
					"text": "route progress stem bpm slice_dir complete curated error"
				}
			},
			{
				"box": {
					"id": "obj-progress-route",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 2,
					"patching_rect": [
						16.0,
						270,
						160.0,
						22.0
					],
					"outlettype": [
						"float",
						"symbol"
					],
					"text": "unpack 0. s"
				}
			},
			{
				"box": {
					"id": "obj-phase-prepend",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 1,
					"patching_rect": [
						180.0,
						270,
						80.0,
						22.0
					],
					"outlettype": [
						"",
						"list"
					],
					"text": "prepend set"
				}
			},
			{
				"box": {
					"id": "obj-error-fmt",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 1,
					"patching_rect": [
						300.0,
						270,
						160.0,
						22.0
					],
					"outlettype": [
						""
					],
					"text": "sprintf set ERROR(%s): %s"
				}
			},
			{
				"box": {
					"id": "obj-loader",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 3,
					"patching_rect": [
						16.0,
						300,
						240.0,
						22.0
					],
					"outlettype": [
						"",
						"",
						""
					],
					"text": "js stemforge_loader.v0.js",
					"saved_object_attributes": {
						"filename": "stemforge_loader.v0.js",
						"parameter_enable": 0
					}
				}
			},
			{
				"box": {
					"id": "obj-complete-unpack",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 3,
					"patching_rect": [
						16.0,
						330,
						100.0,
						22.0
					],
					"outlettype": [
						"",
						"float",
						"int"
					],
					"text": "unpack s 0. 0"
				}
			},
			{
				"box": {
					"id": "obj-stems-dir-extract",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 5,
					"patching_rect": [
						16.0,
						356,
						280.0,
						22.0
					],
					"outlettype": [
						"",
						"",
						"",
						"",
						""
					],
					"text": "regexp (.+)/[^/]+$ @substitute %1"
				}
			},
			{
				"box": {
					"id": "obj-curate-cmd",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 1,
					"patching_rect": [
						16.0,
						382,
						700.0,
						22.0
					],
					"outlettype": [
						""
					],
					"text": "sprintf /Users/zak/.local/bin/uv run --project /Users/zak/zacharysbrown/stemforge python /Users/zak/zacharysbrown/stemforge/v0/src/stemforge_curate_bars.py --stems-dir %s --n-bars 16 --json-events"
				}
			},
			{
				"box": {
					"id": "obj-curated-unpack",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 3,
					"patching_rect": [
						16.0,
						412,
						100.0,
						22.0
					],
					"outlettype": [
						"",
						"int",
						"float"
					],
					"text": "unpack s 0 0."
				}
			},
			{
				"box": {
					"id": "obj-curated-prepend",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 1,
					"patching_rect": [
						16.0,
						438,
						160.0,
						22.0
					],
					"outlettype": [
						""
					],
					"text": "prepend loadCuratedBars"
				}
			},
			{
				"box": {
					"id": "obj-bpm-prepend",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 1,
					"patching_rect": [
						180.0,
						330,
						120.0,
						22.0
					],
					"outlettype": [
						""
					],
					"text": "prepend setBpm"
				}
			},
			{
				"box": {
					"id": "obj-console-print",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [
						320.0,
						300,
						120.0,
						22.0
					],
					"text": "print StemForge"
				}
			},
			{
				"box": {
					"id": "obj-print-complete",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [
						120.0,
						330,
						140.0,
						22.0
					],
					"text": "print COMPLETE-EVENT"
				}
			},
			{
				"box": {
					"id": "obj-print-curated",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [
						180.0,
						412,
						140.0,
						22.0
					],
					"text": "print CURATED-EVENT"
				}
			},
			{
				"box": {
					"id": "obj-print-curate-cmd",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [
						16.0,
						408,
						140.0,
						22.0
					],
					"text": "print CURATE-CMD"
				}
			},
			{
				"box": {
					"id": "obj-test-complete",
					"maxclass": "message",
					"numinlets": 2,
					"numoutlets": 1,
					"patching_rect": [
						500.0,
						240,
						300.0,
						22.0
					],
					"outlettype": [
						""
					],
					"text": "complete /Users/zak/stemforge/processed/the_champ_original_version/stems.json 112.35 4"
				}
			},
			{
				"box": {
					"id": "obj-test-curated",
					"maxclass": "message",
					"numinlets": 2,
					"numoutlets": 1,
					"patching_rect": [
						500.0,
						268,
						300.0,
						22.0
					],
					"outlettype": [
						""
					],
					"text": "curated /Users/zak/stemforge/processed/the_champ_original_version/curated/manifest.json 16 112.35"
				}
			},
			{
				"box": {
					"id": "obj-loadbang",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 1,
					"patching_rect": [
						500.0,
						20.0,
						60.0,
						22.0
					],
					"outlettype": [
						"bang"
					],
					"text": "loadbang"
				}
			},
			{
				"box": {
					"id": "obj-diag-print",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [
						500.0,
						50.0,
						180.0,
						22.0
					],
					"text": "print [StemForge-v0-loaded]"
				}
			},
			{
				"box": {
					"id": "obj-plugin-in",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 1,
					"patching_rect": [
						20.0,
						20.0,
						80.0,
						22.0
					],
					"text": "plugin~ 2",
					"outlettype": [
						"signal"
					]
				}
			},
			{
				"box": {
					"id": "obj-plugout",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [
						20.0,
						60.0,
						80.0,
						22.0
					],
					"text": "plugout~ 2"
				}
			}
		],
		"lines": [
			{
				"patchline": {
					"source": [
						"obj-browse-btn",
						0
					],
					"destination": [
						"obj-opendialog",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-opendialog",
						0
					],
					"destination": [
						"obj-path-convert",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-path-convert",
						0
					],
					"destination": [
						"obj-file-path-msg",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-load-btn",
						0
					],
					"destination": [
						"obj-load-trigger",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-load-trigger",
						0
					],
					"destination": [
						"obj-load-seq",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-load-seq",
						1
					],
					"destination": [
						"obj-load-read-msg",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-load-read-msg",
						0
					],
					"destination": [
						"obj-load-dict",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-load-seq",
						0
					],
					"destination": [
						"obj-load-dict-msg",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-load-dict-msg",
						0
					],
					"destination": [
						"obj-loader",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-preset",
						1
					],
					"destination": [
						"obj-preset-prepend",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-preset-prepend",
						0
					],
					"destination": [
						"obj-loader",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-loadbang",
						0
					],
					"destination": [
						"obj-scan-deferlow",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-scan-deferlow",
						0
					],
					"destination": [
						"obj-scan-presets-msg",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-scan-presets-msg",
						0
					],
					"destination": [
						"obj-loader",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-path-convert",
						0
					],
					"destination": [
						"obj-cmd-fmt",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-split-button",
						0
					],
					"destination": [
						"obj-trigger-bang",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-trigger-bang",
						0
					],
					"destination": [
						"obj-file-path-msg",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-file-path-msg",
						0
					],
					"destination": [
						"obj-cmd-fmt",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-cmd-fmt",
						0
					],
					"destination": [
						"obj-bridge",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-bridge",
						0
					],
					"destination": [
						"obj-ndjson-parser",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-bridge",
						1
					],
					"destination": [
						"obj-ndjson-parser",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-ndjson-parser",
						0
					],
					"destination": [
						"obj-route-events",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-route-events",
						0
					],
					"destination": [
						"obj-progress-route",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-progress-route",
						0
					],
					"destination": [
						"obj-progress-bar",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-progress-route",
						1
					],
					"destination": [
						"obj-phase-prepend",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-phase-prepend",
						0
					],
					"destination": [
						"obj-status-text",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-route-events",
						6
					],
					"destination": [
						"obj-error-fmt",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-error-fmt",
						0
					],
					"destination": [
						"obj-status-text",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-loader",
						2
					],
					"destination": [
						"obj-preset",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-route-events",
						4
					],
					"destination": [
						"obj-complete-unpack",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-complete-unpack",
						0
					],
					"destination": [
						"obj-stems-dir-extract",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-stems-dir-extract",
						0
					],
					"destination": [
						"obj-curate-cmd",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-curate-cmd",
						0
					],
					"destination": [
						"obj-bridge",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-route-events",
						5
					],
					"destination": [
						"obj-curated-unpack",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-curated-unpack",
						0
					],
					"destination": [
						"obj-curated-prepend",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-curated-prepend",
						0
					],
					"destination": [
						"obj-loader",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-route-events",
						2
					],
					"destination": [
						"obj-bpm-prepend",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-bpm-prepend",
						0
					],
					"destination": [
						"obj-loader",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-route-events",
						1
					],
					"destination": [
						"obj-console-print",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-route-events",
						3
					],
					"destination": [
						"obj-console-print",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-route-events",
						4
					],
					"destination": [
						"obj-print-complete",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-route-events",
						5
					],
					"destination": [
						"obj-print-curated",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-curate-cmd",
						0
					],
					"destination": [
						"obj-print-curate-cmd",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-test-complete",
						0
					],
					"destination": [
						"obj-route-events",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-test-curated",
						0
					],
					"destination": [
						"obj-route-events",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-loadbang",
						0
					],
					"destination": [
						"obj-diag-print",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-plugin-in",
						0
					],
					"destination": [
						"obj-plugout",
						0
					]
				}
			}
		],
		"dependency_cache": [
			{
				"name": "stemforge_ndjson_parser.v0.js",
				"bootpath": "~/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect",
				"type": "TEXT",
				"implicit": 1
			},
			{
				"name": "stemforge_loader.v0.js",
				"bootpath": "~/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect",
				"type": "TEXT",
				"implicit": 1
			}
		],
		"autosave": 0,
		"project": {
			"version": 1,
			"creationdate": 3590052493,
			"modificationdate": 3590052493,
			"viewrect": [
				0.0,
				0.0,
				300.0,
				500.0
			],
			"autoorganize": 1,
			"hideprojectwindow": 1,
			"showdependencies": 1,
			"autolocalize": 0,
			"contents": {
				"patchers": {},
				"code": {}
			},
			"layout": {},
			"searchpath": {},
			"detailsvisible": 0,
			"amxdtype": 1633771873,
			"readonly": 0,
			"devpathtype": 0,
			"devpath": ".",
			"sortmode": 0,
			"viewmode": 0,
			"includepackages": 0
		},
		"parameters": {
			"parameterbanks": {
				"0": {
					"index": 0,
					"name": "",
					"parameters": [
						"-",
						"-",
						"-",
						"-",
						"-",
						"-",
						"-",
						"-"
					]
				}
			},
			"inherited_shortname": 1
		}
	}
}