# Makefile for dnf-plugin-p2p
# Simplifies testing, packaging, and building locally

SPECFILE = dnf-plugin-p2p.spec
NAME = $(shell rpm -q --specfile $(SPECFILE) --qf '%{NAME}\n' | head -n 1)
VERSION = $(shell rpm -q --specfile $(SPECFILE) --qf '%{VERSION}\n' | head -n 1)
DIST_DIR = build/rpmbuild

.PHONY: all test patch-libp2p tarball srpm rpm clean bump-version

all: test

test:
	@if [ -d .venv ]; then \
		.venv/bin/pytest tests/; \
	else \
		pytest tests/; \
	fi

patch-libp2p:
	@echo "Applying patches to py-libp2p-src..."
	@cd py-libp2p-src && \
	for p in ../patches/*.patch; do \
		if git apply --check "$$p" 2>/dev/null; then \
			git apply "$$p"; \
			echo "  Applied: $$(basename $$p)"; \
		else \
			echo "  Already applied or conflicts: $$(basename $$p)"; \
		fi; \
	done

tarball:
	@echo "Creating source tarball for $(NAME)-$(VERSION)..."
	mkdir -p $(DIST_DIR)/SOURCES
	tar --exclude-vcs --exclude='./build' --exclude='./.venv' \
		--transform 's/^\./$(NAME)-$(VERSION)/' \
		-czf $(DIST_DIR)/SOURCES/$(NAME)-$(VERSION).tar.gz .

srpm: tarball
	@echo "Building SRPM for $(NAME)-$(VERSION)..."
	mkdir -p $(DIST_DIR)/SPECS $(DIST_DIR)/SRPMS
	cp $(SPECFILE) $(DIST_DIR)/SPECS/
	# Copy local patches into SOURCES
	@if [ -d patches ]; then \
		cp patches/*.patch $(DIST_DIR)/SOURCES/ 2>/dev/null || true; \
	fi
	# Download external sources (skip local-only filenames)
	@for url in $$(grep -E '^Source[1-9][0-9]*:' $(SPECFILE) | awk '{print $$2}' | grep '^https\?://'); do \
		echo "Downloading $$url..."; \
		curl -s -L -o $(DIST_DIR)/SOURCES/$$(basename "$$url") "$$url"; \
	done
	rpmbuild --define "_topdir $(shell pwd)/$(DIST_DIR)" -bs $(DIST_DIR)/SPECS/$(SPECFILE)
	@echo "SRPM generated: $$(ls $(DIST_DIR)/SRPMS/*.src.rpm)"

rpm: srpm
	@echo "Building binary RPMs..."
	rpmbuild --define "_topdir $(shell pwd)/$(DIST_DIR)" --rebuild $(DIST_DIR)/SRPMS/$(NAME)-$(VERSION)-*.src.rpm
	@echo "RPMs generated: $$(find $(DIST_DIR)/RPMS/ -name '*.rpm')"

bump-version:
	@if [ -z "$(V)" ]; then \
		echo "Error: V variable is required. Usage: make bump-version V=X.Y.Z"; \
		exit 1; \
	fi
	python3 bump-version.py $(V)

clean:
	rm -rf build/

