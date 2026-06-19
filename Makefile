# Makefile for dnf-plugin-p2p
# Simplifies testing, packaging, and building locally

SPECFILE = dnf-plugin-p2p.spec
NAME = $(shell rpm -q --specfile $(SPECFILE) --qf '%{NAME}\n' | head -n 1)
VERSION = $(shell rpm -q --specfile $(SPECFILE) --qf '%{VERSION}\n' | head -n 1)
DIST_DIR = build/rpmbuild

.PHONY: all test tarball srpm rpm clean bump-version

all: test

test:
	@if [ -d .venv ]; then \
		.venv/bin/pytest tests/; \
	else \
		pytest tests/; \
	fi

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
	# Download external sources
	@for url in $$(grep -E '^Source[1-9][0-9]*:' $(SPECFILE) | awk '{print $$2}'); do \
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
