#!/usr/bin/env bash
# exit on error
set -o errexit

STORAGE_DIR=$HOME/.cache/selenium

# Install Chrome
if [[ ! -d $STORAGE_DIR/chrome ]]; then
  echo "...Downloading Chrome"
  mkdir -p $STORAGE_DIR/chrome
  cd $STORAGE_DIR/chrome
  wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
  dpkg -x google-chrome-stable_current_amd64.deb .
  rm google-chrome-stable_current_amd64.deb
fi

# Add Chrome to PATH
export PATH=$PATH:$STORAGE_DIR/chrome/opt/google/chrome

pip install -r requirements.txt