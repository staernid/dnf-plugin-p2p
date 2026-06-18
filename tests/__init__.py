import os
import sys

# Add directories to python path for testing
sys.path.append(os.path.realpath(os.path.join(os.path.dirname(__file__), '..', 'plugins')))
sys.path.append(os.path.realpath(os.path.join(os.path.dirname(__file__), '..', 'p2p-proxy-server')))
