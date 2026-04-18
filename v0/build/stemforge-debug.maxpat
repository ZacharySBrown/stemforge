{
	"patcher": {
		"fileversion": 1,
		"appversion": {"major": 9, "minor": 0, "revision": 8, "architecture": "x64", "modernui": 1},
		"classnamespace": "box",
		"rect": [100, 100, 900, 600],
		"gridsize": [8.0, 8.0],
		"boxes": [
			{
				"box": {
					"id": "obj-title",
					"maxclass": "comment",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [20, 10, 500, 22],
					"text": "DROP a .wav here — auto-fires stem separation"
				}
			},
			{
				"box": {
					"id": "obj-drop",
					"maxclass": "dropfile",
					"numinlets": 1,
					"numoutlets": 2,
					"outlettype": ["", "int"],
					"patching_rect": [20, 40, 400, 80]
				}
			},
			{
				"box": {
					"id": "obj-regexp",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 5,
					"outlettype": ["", "", "", "", ""],
					"patching_rect": [20, 130, 200, 22],
					"text": "regexp (.+):(/.*) @substitute %2"
				}
			},
			{
				"box": {
					"id": "obj-print-path",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [500, 130, 140, 22],
					"text": "print POSIX-PATH"
				}
			},
			{
				"box": {
					"id": "obj-cmd-fmt",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 1,
					"outlettype": [""],
					"patching_rect": [20, 170, 520, 22],
					"text": "sprintf /usr/local/bin/stemforge-native split %s --json-events --variant ft-fused"
				}
			},
			{
				"box": {
					"id": "obj-print-cmd",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [560, 170, 140, 22],
					"text": "print COMMAND"
				}
			},
			{
				"box": {
					"id": "obj-shell",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 2,
					"outlettype": ["", "bang"],
					"patching_rect": [20, 210, 80, 22],
					"text": "shell"
				}
			},
			{
				"box": {
					"id": "obj-raw",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [500, 210, 120, 22],
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
					"patching_rect": [20, 250, 260, 22],
					"text": "js stemforge_ndjson_parser.v0.js"
				}
			},
			{
				"box": {
					"id": "obj-route",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 6,
					"outlettype": ["", "", "", "", "", ""],
					"patching_rect": [20, 290, 400, 22],
					"text": "route progress stem bpm slice_dir complete error"
				}
			},
			{
				"box": {
					"id": "obj-progress",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [20, 330, 100, 22],
					"text": "print PROGRESS"
				}
			},
			{
				"box": {
					"id": "obj-stem",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [130, 330, 80, 22],
					"text": "print STEM"
				}
			},
			{
				"box": {
					"id": "obj-bpm",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [220, 330, 80, 22],
					"text": "print BPM"
				}
			},
			{
				"box": {
					"id": "obj-complete",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [310, 330, 100, 22],
					"text": "print COMPLETE"
				}
			},
			{
				"box": {
					"id": "obj-error",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [420, 330, 80, 22],
					"text": "print ERROR"
				}
			},
			{
				"box": {
					"id": "obj-done",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [500, 250, 100, 22],
					"text": "print SHELL-DONE"
				}
			},
			{
				"box": {
					"id": "obj-version",
					"maxclass": "message",
					"numinlets": 2,
					"numoutlets": 1,
					"outlettype": [""],
					"patching_rect": [20, 390, 320, 22],
					"text": "/usr/local/bin/stemforge-native --version"
				}
			}
		],
		"lines": [
			{"patchline": {"source": ["obj-drop", 0], "destination": ["obj-regexp", 0]}},
			{"patchline": {"source": ["obj-regexp", 0], "destination": ["obj-print-path", 0]}},
			{"patchline": {"source": ["obj-regexp", 0], "destination": ["obj-cmd-fmt", 0]}},
			{"patchline": {"source": ["obj-cmd-fmt", 0], "destination": ["obj-print-cmd", 0]}},
			{"patchline": {"source": ["obj-cmd-fmt", 0], "destination": ["obj-shell", 0]}},
			{"patchline": {"source": ["obj-shell", 0], "destination": ["obj-raw", 0]}},
			{"patchline": {"source": ["obj-shell", 0], "destination": ["obj-parser", 0]}},
			{"patchline": {"source": ["obj-shell", 1], "destination": ["obj-done", 0]}},
			{"patchline": {"source": ["obj-shell", 1], "destination": ["obj-parser", 0]}},
			{"patchline": {"source": ["obj-parser", 0], "destination": ["obj-route", 0]}},
			{"patchline": {"source": ["obj-route", 0], "destination": ["obj-progress", 0]}},
			{"patchline": {"source": ["obj-route", 1], "destination": ["obj-stem", 0]}},
			{"patchline": {"source": ["obj-route", 2], "destination": ["obj-bpm", 0]}},
			{"patchline": {"source": ["obj-route", 4], "destination": ["obj-complete", 0]}},
			{"patchline": {"source": ["obj-route", 5], "destination": ["obj-error", 0]}},
			{"patchline": {"source": ["obj-version", 0], "destination": ["obj-shell", 0]}}
		]
	}
}
