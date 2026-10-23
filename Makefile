CLANG ?= clang-21
BPFTOOL ?= bpftool
PKG_CONFIG ?= pkg-config
CFLAGS ?= -O2 -g
CPPFLAGS += $(shell $(PKG_CONFIG) --cflags libbpf)
LDLIBS += $(shell $(PKG_CONFIG) --libs libbpf)

.PHONY: all test check clean
.DELETE_ON_ERROR:

all: loader

build:
	mkdir -p $@

build/vmlinux.h: /sys/kernel/btf/vmlinux | build
	$(BPFTOOL) btf dump file $< format c > $@

build/controller.bpf.o: controller.bpf.c accounting.h window.h recovery.h build/vmlinux.h
	$(CLANG) -target bpf -O2 -g -Wall -Werror $(CPPFLAGS) -Ibuild -c $< -o $@

build/controller.skel.h: build/controller.bpf.o
	$(BPFTOOL) gen skeleton $< > $@

loader: loader.c build/controller.skel.h
	$(CC) $(CFLAGS) -Wall -Wextra -Werror $(CPPFLAGS) -Ibuild $< -o $@ $(LDLIBS)

build/test_accounting: test_accounting.c accounting.h | build
	$(CC) $(CFLAGS) -Wall -Wextra -Werror $< -o $@

build/test_window: test_window.c window.h accounting.h | build
	$(CC) $(CFLAGS) -Wall -Wextra -Werror $< -o $@

build/test_recovery: test_recovery.c recovery.h window.h accounting.h | build
	$(CC) $(CFLAGS) -Wall -Wextra -Werror $< -o $@

test: build/test_accounting build/test_window build/test_recovery
	./build/test_accounting
	./build/test_window
	./build/test_recovery

check: loader
	./loader --check

clean:
	$(RM) -r build loader
