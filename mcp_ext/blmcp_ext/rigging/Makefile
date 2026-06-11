BLENDER_BIN ?= blender
BLENDER_ARGS = --background --factory-startup --python-exit-code 1

test:
	$(BLENDER_BIN) $(BLENDER_ARGS) --python tests/bl_run_all.py -- -v

test-fast:
	$(BLENDER_BIN) $(BLENDER_ARGS) --python tests/bl_run_all.py -- -v --tier property

test-deform:
	$(BLENDER_BIN) $(BLENDER_ARGS) --python tests/bl_run_all.py -- -v --tier deform

test-render:
	$(BLENDER_BIN) $(BLENDER_ARGS) --python tests/bl_run_all.py -- -v --tier render

.PHONY: test test-fast test-deform test-render
