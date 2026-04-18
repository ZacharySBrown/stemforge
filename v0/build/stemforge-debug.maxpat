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
					"text": "Test A: drag file onto drop zone | Test B: click BROWSE to pick file"
				}
			},
			{
				"box": {
					"id": "obj-drop",
					"maxclass": "dropfile",
					"numinlets": 1,
					"numoutlets": 2,
					"outlettype": ["", "int"],
					"patching_rect": [20, 40, 300, 60]
				}
			},
			{
				"box": {
					"id": "obj-browse-btn",
					"maxclass": "textbutton",
					"numinlets": 1,
					"numoutlets": 3,
					"outlettype": ["", "", "int"],
					"patching_rect": [340, 40, 100, 30],
					"text": "BROWSE"
				}
			},
			{
				"box": {
					"id": "obj-opendialog",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 2,
					"outlettype": ["", "bang"],
					"patching_rect": [340, 80, 150, 22],
					"text": "opendialog sound"
				}
			},
			{
				"box": {
					"id": "obj-regexp",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 5,
					"outlettype": ["", "", "", "", ""],
					"patching_rect": [20, 120, 200, 22],
					"text": "regexp (.+):(/.*) @substitute %2"
				}
			},
			{
				"box": {
					"id": "obj-print-path",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [500, 120, 140, 22],
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
					"patching_rect": [20, 160, 520, 22],
					"text": "sprintf /usr/local/bin/stemforge-native split %s --json-events --variant ft-fused"
				}
			},
			{
				"box": {
					"id": "obj-print-cmd",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [560, 160, 140, 22],
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
					"patching_rect": [20, 200, 80, 22],
					"text": "shell"
				}
			},
			{
				"box": {
					"id": "obj-raw",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [500, 200, 120, 22],
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
					"patching_rect": [20, 240, 260, 22],
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
					"patching_rect": [20, 280, 400, 22],
					"text": "route progress stem bpm slice_dir complete error"
				}
			},
			{
				"box": {
					"id": "obj-progress",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [20, 320, 100, 22],
					"text": "print PROGRESS"
				}
			},
			{
				"box": {
					"id": "obj-stem",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [130, 320, 80, 22],
					"text": "print STEM"
				}
			},
			{
				"box": {
					"id": "obj-bpm",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [220, 320, 80, 22],
					"text": "print BPM"
				}
			},
			{
				"box": {
					"id": "obj-complete",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [310, 320, 100, 22],
					"text": "print COMPLETE"
				}
			},
			{
				"box": {
					"id": "obj-error",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [420, 320, 80, 22],
					"text": "print ERROR"
				}
			},
			{
				"box": {
					"id": "obj-done",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [500, 240, 100, 22],
					"text": "print SHELL-DONE"
				}
			}
		],
		"lines": [
			{"patchline": {"source": ["obj-drop", 0], "destination": ["obj-regexp", 0]}},
			{"patchline": {"source": ["obj-browse-btn", 0], "destination": ["obj-opendialog", 0]}},
			{"patchline": {"source": ["obj-opendialog", 0], "destination": ["obj-regexp", 0]}},
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
			{"patchline": {"source": ["obj-route", 5], "destination": ["obj-error", 0]}}
		]
	}
}
