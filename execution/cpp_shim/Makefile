# execution/cpp_shim/Makefile
# ============================
# Convenience wrapper around the CMake build.
# Requires: build-essential cmake pkg-config libzmq3-dev
#
# Targets:
#   make            — Release build (default)
#   make debug      — Debug build with AddressSanitizer
#   make clean      — Remove build directory
#   make run        — Build then start the shim in the background
#   make stop       — Kill any running shim process
#   make docker     — Build via Docker (no local toolchain needed)
#   make install    — Copy binary to /usr/local/bin/hopefx_shim

BUILD_DIR := build
BINARY    := $(BUILD_DIR)/hopefx_shim
NPROC     := $(shell nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)

.PHONY: all release debug clean run stop docker install help

all: release

release: ## Release build (O3, march=native, LTO)
	@bash build.sh

debug: ## Debug build with AddressSanitizer
	@bash build.sh --debug

clean: ## Remove build directory
	@bash build.sh --clean
	@echo "Clean complete."

run: release ## Build and start the shim in the background
	@echo "Starting hopefx_shim..."
	@$(BINARY) &
	@echo "Shim PID: $$!"

stop: ## Kill any running shim process
	@pkill -f hopefx_shim && echo "Shim stopped." || echo "No shim process found."

docker: ## Build via Docker (no local toolchain needed)
	@bash build.sh --docker

install: release ## Install binary to /usr/local/bin
	@install -m 755 $(BINARY) /usr/local/bin/hopefx_shim
	@echo "Installed to /usr/local/bin/hopefx_shim"

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'
