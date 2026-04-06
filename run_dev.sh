#!/bin/bash
echo "Installing dependencies..."
pip3 install -r requirements.txt --quiet
echo "Starting PGManager (dev mode)..."
python3 main.py
