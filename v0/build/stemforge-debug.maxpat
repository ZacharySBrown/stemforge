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
		"rect": [100, 100, 800, 600],
		"gridsize": [8.0, 8.0],
		"boxes": [
			{
				"box": {
					"id": "obj-cmd-version",
					"maxclass": "message",
					"numinlets": 2,
					"numoutlets": 1,
					"outlettype": [""],
					"patching_rect": [20, 20, 320, 22],
					"text": "/usr/local/bin/stemforge-native --version"
				}
			},
			{
				"box": {
					"id": "obj-cmd-split",
					"maxclass": "message",
					"numinlets": 2,
					"numoutlets": 1,
					"outlettype": [""],
					"patching_rect": [20, 50, 500, 22],
					"text": "/usr/local/bin/stemforge-native split /tmp/the_champ_30s.wav --json-events"
				}
			},
			{
				"box": {
					"id": "obj-shell",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 2,
					"outlettype": ["", "bang"],
					"patching_rect": [20, 100, 80, 22],
					"text": "shell"
				}
			},
			{
				"box": {
					"id": "obj-raw",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [400, 100, 120, 22],
					"text": "print SHELL-RAW"
				}
			},
			{
				"box": {
					"id": "obj-parser",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 1,
					"outlettype": [""],
					"patching_rect": [20, 140, 240, 22],
					"text": "js stemforge_ndjson_parser.v0.js"
				}
			},
			{
				"box": {
					"id": "obj-parsed",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [400, 140, 140, 22],
					"text": "print PARSED-EVENT"
				}
			},
			{
				"box": {
					"id": "obj-route",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 6,
					"outlettype": ["", "", "", "", "", ""],
					"patching_rect": [20, 180, 360, 22],
					"text": "route progress stem bpm slice_dir complete error"
				}
			},
			{
				"box": {
					"id": "obj-progress-print",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [20, 220, 120, 22],
					"text": "print PROGRESS"
				}
			},
			{
				"box": {
					"id": "obj-stem-print",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [150, 220, 100, 22],
					"text": "print STEM"
				}
			},
			{
				"box": {
					"id": "obj-bpm-print",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [260, 220, 100, 22],
					"text": "print BPM"
				}
			},
			{
				"box": {
					"id": "obj-complete-print",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [400, 220, 120, 22],
					"text": "print COMPLETE"
				}
			},
			{
				"box": {
					"id": "obj-error-print",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [540, 220, 100, 22],
					"text": "print ERROR"
				}
			},
			{
				"box": {
					"id": "obj-done",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [400, 260, 120, 22],
					"text": "print SHELL-DONE"
				}
			}
		],
		"lines": [
			{"patchline": {"source": ["obj-cmd-version", 0], "destination": ["obj-shell", 0]}},
			{"patchline": {"source": ["obj-cmd-split", 0], "destination": ["obj-shell", 0]}},
			{"patchline": {"source": ["obj-shell", 0], "destination": ["obj-raw", 0]}},
			{"patchline": {"source": ["obj-shell", 0], "destination": ["obj-parser", 0]}},
			{"patchline": {"source": ["obj-parser", 0], "destination": ["obj-parsed", 0]}},
			{"patchline": {"source": ["obj-parser", 0], "destination": ["obj-route", 0]}},
			{"patchline": {"source": ["obj-route", 0], "destination": ["obj-progress-print", 0]}},
			{"patchline": {"source": ["obj-route", 1], "destination": ["obj-stem-print", 0]}},
			{"patchline": {"source": ["obj-route", 2], "destination": ["obj-bpm-print", 0]}},
			{"patchline": {"source": ["obj-route", 4], "destination": ["obj-complete-print", 0]}},
			{"patchline": {"source": ["obj-route", 5], "destination": ["obj-error-print", 0]}},
			{"patchline": {"source": ["obj-shell", 1], "destination": ["obj-done", 0]}}
		]
	}
}
