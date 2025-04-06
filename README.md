# PyRemoteView - Remote SSH Image Gallery Viewer

[![PyPI version](https://badge.fury.io/py/pyremoteview.svg)](https://badge.fury.io/py/pyremoteview)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/pyremoteview)](https://pypi.org/project/pyremoteview/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

PyRemoteView is a web-based application that allows you to remotely browse and view images stored on another server via SSH, with automatic thumbnail generation and caching for improved performance.

## Features

- Browse remote directories and view images via web interface
- Automatic thumbnail generation for faster browsing
- Local caching of images and thumbnails
- Supports common image formats (JPG, PNG, GIF, WebP, BMP)
- Responsive gallery with lightbox view and keyboard navigation
- Debug interface for troubleshooting
- Can be used to browse local files as well

## Requirements

- Python 3.6+
- Flask
- Pillow (PIL)
- SSH access to the remote server

## Installation

### Install from PyPI (Recommended)

You can install PyRemoteView directly from PyPI using pip:

```
pip install pyremoteview
```

This will install all required dependencies automatically.

### Manual Installation

If you prefer to install from source:

1. Clone or download this repository
2. Install required packages:
   ```
   pip install -r requirements.txt
   ```
3. Install the package:
   ```
   pip install .
   ```

## Setting Up Passwordless SSH

For PyRemoteView to work properly, you need to set up passwordless SSH access to the remote server:

1. Generate an SSH key pair (if you don't already have one):
   ```
   ssh-keygen -t rsa -b 4096
   ```

2. Copy your public key to the remote server:
   ```
   ssh-copy-id username@remote-server
   ```
   Or manually add the content of `~/.ssh/id_rsa.pub` to the remote server's `~/.ssh/authorized_keys` file.

3. Test your passwordless login:
   ```
   ssh username@remote-server
   ```
   You should be able to log in without entering a password.

## Usage

### After PyPI Installation

If you installed PyRemoteView from PyPI, you can start it directly from the command line:

```
pyremoteview --remote-host remoteserver --remote-path /path/to/images
```

### If Installed from Source

```
python remote_gallery.py --remote-host remoteserver --remote-path /path/to/images
```

### Command Line Options

- `--port PORT`: Port to run the server on (default: 8080)
- `--host HOST`: Host to run the server on (default: 0.0.0.0)
- `--remote-host REMOTE_HOST`: Remote host to fetch images from
- `--remote-path REMOTE_PATH`: Path on remote host to browse

### Serving Local Files

To browse images on your local machine, use `localhost` as the remote host:

```
python remote_gallery.py --remote-host localhost --remote-path /path/to/local/images
```

## Web Interface

After starting the server, access the gallery by opening a web browser and navigating to:

```
http://localhost:8080
```

### Features:

- Click on folders to navigate directories
- Click on images to view them in a lightbox
- Use arrow keys to navigate between images in lightbox view
- Press Escape to exit lightbox view
- Use "Clear Cache" button to refresh thumbnails and image cache

## Troubleshooting

Access the debug page for detailed information about the server status, SSH connection, and cache:

```
http://localhost:8080/debug
```

## Caching

The application caches thumbnails and recently viewed images in:
- `~/.cache/pyremoteview/thumbnails`
- `~/.cache/pyremoteview/images`

To clear the cache, use the "Clear Cache" button in the web interface or delete these directories.