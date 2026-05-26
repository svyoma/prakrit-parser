"""
Vercel serverless function entry point for Flask app
"""
import sys
import os

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unified_parser import app

# This is the ASGI application instance that Vercel will use
# The 'app' variable must be the Flask application
