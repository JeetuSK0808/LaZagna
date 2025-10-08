.PHONY: all init update build clean_openfpga clean_files clean

# Variables
MAKEFLAGS =

# Default target, run all tasks
all: init build

prereqs:
	./install_apt_packages.sh

# Initialize and update submodules recursively
init:
	git submodule update --init --recursive

# Build OpenFPGA
build:
	cd OpenFPGA && $(MAKE) $(MAKEFLAGS) all
	echo "LaZagna Build complete."

# Clean build outputs in the OpenFPGA
clean_openfpga:
	cd OpenFPGA && $(MAKE) clean

clean_files:
	rm -f ./rrg_3d/*
	rm -f ./base_rrg/*
	rm -r ./tasks_run/*
	rm -f ./arch_files/*.xml
	rm -r ./results/3d_*
	rm -r ./results/*x*
	rm -rf ./results/results_csvs/*

clean: clean_openfpga

make clean_all: clean_openfpga clean_files

# Allow passing -j and other flags to the build step
FLAGS ?= -j1
MAKEFLAGS += $(FLAGS)
