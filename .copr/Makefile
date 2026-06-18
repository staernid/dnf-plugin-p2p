# .copr/Makefile

.PHONY: srpm

srpm:
	$(eval NAME := $(shell rpm -q --specfile $(spec) --qf '%{NAME}\n' | head -n 1))
	$(eval VERSION := $(shell rpm -q --specfile $(spec) --qf '%{VERSION}\n' | head -n 1))
	
	mkdir -p build/SOURCES build/SPECS build/$(NAME)-$(VERSION)
	cp $(spec) build/SPECS/
	
	# Copy files to the build directory, excluding Git and build directories
	tar --exclude='./.git' --exclude='./.copr' --exclude='./build' --exclude='./test_outdir' --exclude='./test_install_dir' --exclude='./test_wheels' -cf - . | tar -x -C build/$(NAME)-$(VERSION)
	
	# Download PyPI dependencies into bundled-deps
	mkdir -p build/$(NAME)-$(VERSION)/bundled-deps
	pip download --no-deps --no-binary :all: --dest build/$(NAME)-$(VERSION)/bundled-deps/ \
		fastecdsa py-multibase py-multihash py-multicodec py-cid trio-typing rpcudp
	
	# Build the local libp2p package as a wheel into bundled-deps
	pip wheel --no-deps -w build/$(NAME)-$(VERSION)/bundled-deps/ ./py-libp2p-src/
	
	# Create final tarball containing everything
	tar -czf build/SOURCES/$(NAME)-$(VERSION).tar.gz -C build $(NAME)-$(VERSION)
	
	# Build the SRPM
	rpmbuild -bs \
		--define "_topdir $(shell pwd)/build" \
		--define "_sourcedir $(shell pwd)/build/SOURCES" \
		--define "_srcrpmdir $(outdir)" \
		build/SPECS/$(notdir $(spec))
