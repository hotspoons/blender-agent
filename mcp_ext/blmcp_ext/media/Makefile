BLENDER_BIN ?= blender

test:
	$(BLENDER_BIN) --background --factory-startup --python-exit-code 1 --python tests/bl_run.py -- -v

.PHONY: test
