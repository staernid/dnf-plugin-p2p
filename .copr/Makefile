# .copr/Makefile

.PHONY: srpm

srpm:
	$(eval NAME := $(shell rpm -q --specfile $(spec) --qf '%{NAME}\n' | head -n 1))
	$(eval VERSION := $(shell rpm -q --specfile $(spec) --qf '%{VERSION}\n' | head -n 1))
	
	mkdir -p build/SOURCES build/SPECS build/$(NAME)-$(VERSION)
	cp $(spec) build/SPECS/
	
	# Copy files to the build directory, excluding Git and build directories
	tar --exclude='.git' --exclude='.copr' --exclude='build' --exclude='test_outdir' --exclude='test_install_dir' --exclude='test_wheels' -cf - . | tar -x -C build/$(NAME)-$(VERSION)
	
	# Download the external Source URLs listed in the spec file into build/SOURCES
	# so that rpmbuild can find them and package them into the SRPM
	for url in $$(grep -E '^Source[1-9][0-9]*:' build/SPECS/$(notdir $(spec)) | awk '{print $$2}'); do \
		curl -s -L -o build/SOURCES/$$(basename "$$url") "$$url"; \
	done
	
	# Create final tarball containing everything
	tar -czf build/SOURCES/$(NAME)-$(VERSION).tar.gz -C build $(NAME)-$(VERSION)
	
	# Build the SRPM
	rpmbuild -bs \
		--define "_topdir $(shell pwd)/build" \
		--define "_sourcedir $(shell pwd)/build/SOURCES" \
		--define "_srcrpmdir $(outdir)" \
		build/SPECS/$(notdir $(spec))
