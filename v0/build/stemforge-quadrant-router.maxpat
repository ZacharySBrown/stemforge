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
			100,
			100,
			500,
			300
		],
		"openinpresentation": 0,
		"default_fontsize": 11.0,
		"default_fontname": "Ableton Sans Medium",
		"gridsize": [
			8.0,
			8.0
		],
		"boxes": [
			{
				"box": {
					"id": "obj-midiin",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 1,
					"patching_rect": [
						20,
						20,
						80,
						22
					],
					"outlettype": [
						"int"
					],
					"text": "midiin"
				}
			},
			{
				"box": {
					"id": "obj-router",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 1,
					"patching_rect": [
						20,
						60,
						280,
						22
					],
					"outlettype": [
						"int"
					],
					"text": "js stemforge_quadrant_router.js",
					"saved_object_attributes": {
						"filename": "stemforge_quadrant_router.js",
						"parameter_enable": 0
					}
				}
			},
			{
				"box": {
					"id": "obj-midiout",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [
						20,
						100,
						80,
						22
					],
					"text": "midiout"
				}
			},
			{
				"box": {
					"id": "obj-loadbang",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 1,
					"patching_rect": [
						300,
						20,
						60,
						22
					],
					"outlettype": [
						"bang"
					],
					"text": "loadbang"
				}
			},
			{
				"box": {
					"id": "obj-colorize-msg",
					"maxclass": "message",
					"numinlets": 2,
					"numoutlets": 1,
					"patching_rect": [
						300,
						50,
						60,
						22
					],
					"outlettype": [
						""
					],
					"text": "colorize"
				}
			},
			{
				"box": {
					"id": "obj-test-msg",
					"maxclass": "message",
					"numinlets": 2,
					"numoutlets": 1,
					"patching_rect": [
						300,
						80,
						40,
						22
					],
					"outlettype": [
						""
					],
					"text": "test"
				}
			},
			{
				"box": {
					"id": "obj-diag",
					"maxclass": "newobj",
					"numinlets": 1,
					"numoutlets": 0,
					"patching_rect": [
						300,
						110,
						200,
						22
					],
					"text": "print [QuadrantRouter-loaded]"
				}
			}
		],
		"lines": [
			{
				"patchline": {
					"source": [
						"obj-midiin",
						0
					],
					"destination": [
						"obj-router",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-router",
						0
					],
					"destination": [
						"obj-midiout",
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
						"obj-colorize-msg",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-colorize-msg",
						0
					],
					"destination": [
						"obj-router",
						0
					]
				}
			},
			{
				"patchline": {
					"source": [
						"obj-test-msg",
						0
					],
					"destination": [
						"obj-router",
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
						"obj-diag",
						0
					]
				}
			}
		],
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
		"dependency_cache": [
			{
				"name": "stemforge_quadrant_router.js",
				"bootpath": "~/Documents/Max 9/Packages/StemForge/javascript",
				"type": "TEXT",
				"implicit": 1
			}
		],
		"autosave": 0
	}
}