"""
Remote Image Gallery Server

This script creates a web server on linux01 that displays and serves
images stored on linux02 via SSH. It caches thumbnails locally for
better performance.

Usage:
  python remote_gallery.py [--port PORT] [--host HOST] [--remote-host REMOTE_HOST] [--remote-path PATH]

Example:
  python remote_gallery.py --port 8080 --remote-host linux02 --remote-path /path/to/comfy/outputs
"""

import os
import sys
import argparse
import subprocess
import hashlib
import shutil
from pathlib import Path
import threading
import time
from functools import lru_cache

from flask import Flask, render_template, send_file, request, url_for, abort
from werkzeug.serving import run_simple
from PIL import Image, ImageDraw, UnidentifiedImageError
from io import BytesIO

# Configuration
DEFAULT_PORT = 8080
DEFAULT_HOST = "0.0.0.0"
DEFAULT_REMOTE_HOST = "localhost"
DEFAULT_REMOTE_PATH = "/path/to/comfy/outputs"
THUMBNAIL_SIZE = (300, 300)
CACHE_DIR = Path(os.path.expanduser("~/.cache/pyremoteview"))
THUMBNAIL_DIR = CACHE_DIR / "thumbnails"
IMAGE_CACHE_DIR = CACHE_DIR / "images"
IMAGE_CACHE_TIME = 60 * 60 * 24  # 24 hours in seconds

# Ensure cache directories exist
THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, template_folder='templates')

# Global variables for remote path info
remote_host = DEFAULT_REMOTE_HOST
remote_path = DEFAULT_REMOTE_PATH

# Cache for directory listings
directory_cache = {}
directory_cache_time = {}
DIRECTORY_CACHE_TTL = 30  # seconds

# Supported image formats
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}

def get_file_hash(path):
    """Generate a hash for a remote file path to use as a cache key"""
    return hashlib.md5(path.encode()).hexdigest()

def list_remote_directory(path=None):
    """List files and directories on the remote server"""
    if path is None:
        path = remote_path
    
    # Check cache first
    now = time.time()
    if path in directory_cache and (now - directory_cache_time.get(path, 0)) < DIRECTORY_CACHE_TTL:
        return directory_cache[path]
    
    print(f"Listing remote directory: {path}")
    # Use a safer command where spaces in paths won't cause issues
    cmd = ["ssh", remote_host, f"cd '{path}' && find . -maxdepth 1 -type f -o -maxdepth 1 -type d | sort"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        stdout = result.stdout.strip()
        
        # Handle empty results
        if not stdout:
            print("No files or directories found")
            return {'directories': [], 'files': []}
            
        all_files = stdout.split('\n')
        
        # Process the relative paths returned by find
        all_files = []
        for f in stdout.split('\n'):
            if f and f != '.' and f != './':
                # Convert relative paths (./file) to absolute paths
                if f.startswith('./'):
                    f = f[2:]  # Remove './' prefix
                
                # Create absolute path
                full_path = os.path.join(path, f)
                all_files.append(full_path)
        
        if not all_files:
            print("No files or directories found after filtering")
            return {'directories': [], 'files': []}
        
        # Separate directories and files
        dirs = []
        files = []
        
        for f in all_files:
            if not f:  # Skip empty strings
                continue
                
            # Check if it's a directory - do one test per file instead of many individual calls
            check_cmd = ["ssh", remote_host, f"test -d '{f}' && echo 'dir:{f}' || echo 'file:{f}'"]
            try:
                result = subprocess.run(check_cmd, capture_output=True, text=True, check=True)
                result_text = result.stdout.strip()
                
                if result_text.startswith('dir:'):
                    basename = os.path.basename(f)
                    if basename:  # Only add if basename is not empty
                        dirs.append((basename, f))
                elif result_text.startswith('file:'):
                    # Only add files with image extensions
                    _, ext = os.path.splitext(f.lower())
                    if ext in IMAGE_EXTENSIONS:
                        basename = os.path.basename(f)
                        if basename:  # Only add if basename is not empty
                            files.append((basename, f))
                else:
                    print(f"Unexpected result for file check: {result_text}")
            except subprocess.CalledProcessError as e:
                print(f"Error checking if '{f}' is directory: {e}")
                print(f"stderr: {e.stderr}")
                continue
                
        result = {
            'directories': sorted(dirs),
            'files': sorted(files)
        }
        
        # Update cache
        directory_cache[path] = result
        directory_cache_time[path] = now
        
        print(f"Final result: {len(dirs)} directories and {len(files)} files")
        return result
    except subprocess.CalledProcessError as e:
        print(f"Error listing remote directory: {e}")
        print(f"stderr: {e.stderr}")
        return {'directories': [], 'files': []}
        
        result = {
            'directories': sorted(dirs),
            'files': sorted(files)
        }
        
        # Update cache
        directory_cache[path] = result
        directory_cache_time[path] = now
        
        print(f"Found {len(dirs)} directories and {len(files)} files")
        return result
    except subprocess.CalledProcessError as e:
        print(f"Error listing remote directory: {e}")
        print(f"stderr: {e.stderr}")
        return {'directories': [], 'files': []}

def fetch_remote_image(remote_path, thumbnail=False):
    """
    Fetch an image from the remote server and optionally create a thumbnail
    Returns the path to the local file
    """
    file_hash = get_file_hash(remote_path)
    
    if thumbnail:
        local_path = THUMBNAIL_DIR / f"{file_hash}.jpg"
    else:
        # Preserve original extension for full images
        _, ext = os.path.splitext(remote_path.lower())
        if not ext:
            ext = ".jpg"  # Default if no extension
        local_path = IMAGE_CACHE_DIR / f"{file_hash}{ext}"
    
    # Check if cached copy exists
    if local_path.exists():
        # For full images, check cache freshness
        if not thumbnail and (time.time() - os.path.getmtime(local_path)) > IMAGE_CACHE_TIME:
            # Cache expired, refresh
            pass
        else:
            return local_path

    # Fetch the file
    try:
        # Simplify path handling - just use the filename portion of the path
        filename = os.path.basename(remote_path)
        fixed_path = os.path.join(remote_path, filename)
        
        # Often the filename is already the full path, so let's check
        if fixed_path.count(filename) > 1:
            # This means we've duplicated the filename - fix it
            fixed_path = remote_path
        
        print(f"SCP will fetch: {fixed_path}")
        
        # Create a temporary file for downloading
        temp_file = f"/tmp/pyremoteview_{file_hash}{os.path.splitext(filename)[1]}"
        
        # Download the file directly (no streaming)
        scp_cmd = ["scp", f"{remote_host}:{fixed_path}", temp_file]
        print(f"SCP command: {' '.join(scp_cmd)}")
        
        subprocess.run(scp_cmd, check=True)
        
        if not os.path.exists(temp_file) or os.path.getsize(temp_file) == 0:
            print(f"Error: Downloaded file is empty or doesn't exist: {temp_file}")
            raise ValueError("Empty or missing downloaded file")
        
        if thumbnail:
            try:
                img = Image.open(temp_file)
                img_format = img.format
                img_size = img.size
                print(f"Successfully loaded image: format={img_format}, size={img_size}")
                
                img.thumbnail(THUMBNAIL_SIZE)
                img.save(local_path, "JPEG", quality=85)
                print(f"Created thumbnail: {local_path}")
                
                # Remove the temporary file
                os.unlink(temp_file)
            except Exception as e:
                print(f"Error processing image: {e}")
                # Create an error placeholder
                error_img = Image.new('RGB', THUMBNAIL_SIZE, color=(200, 0, 0))
                draw = ImageDraw.Draw(error_img)
                draw.text((10, 10), "Error", fill=(255, 255, 255))
                draw.text((10, 30), f"File: {filename}", fill=(255, 255, 255))
                draw.text((10, 50), f"Err: {str(e)[:15]}", fill=(255, 255, 255))
                error_img.save(local_path, "JPEG", quality=85)
                
                # Keep the temp file for debugging
                debug_file = f"/tmp/error_{file_hash}{os.path.splitext(filename)[1]}"
                shutil.copy(temp_file, debug_file)
                print(f"Copied problematic file to {debug_file} for debugging")
                
                # Remove the temporary file
                os.unlink(temp_file)
        else:
            # For full-size images, just move the temp file to the cache
            shutil.move(temp_file, local_path)
            print(f"Saved full-size image: {local_path}")
        
        return local_path
    except Exception as e:
        print(f"Error fetching remote image: {e}")
        if hasattr(e, 'stderr') and e.stderr:
            print(f"stderr: {e.stderr}")
        
        # Clean up temp file if it exists
        if 'temp_file' in locals() and os.path.exists(temp_file):
            os.unlink(temp_file)
        
        # Return a placeholder for thumbnails
        if thumbnail:
            print(f"Creating error placeholder for: {os.path.basename(remote_path)}")
            img = Image.new('RGB', THUMBNAIL_SIZE, color=(200, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.text((10, 10), "Error", fill=(255, 255, 255))
            draw.text((10, 30), f"File: {os.path.basename(remote_path)}", fill=(255, 255, 255))
            err_msg = str(e)[:15]
            draw.text((10, 50), f"Err: {err_msg}", fill=(255, 255, 255))
            img.save(local_path, "JPEG", quality=85)
            return local_path
        return None

# Cache the thumbnails to avoid regenerating them frequently
@lru_cache(maxsize=100)
def get_thumbnail_path(remote_path):
    """Get the path to a thumbnail, creating it if necessary"""
    return fetch_remote_image(remote_path, thumbnail=True)

@app.route('/')
def index():
    return browse()

@app.route('/browse/')
@app.route('/browse/<path:subpath>')
def browse(subpath=None):
    """Browse the remote directory"""
    try:
        if subpath is None:
            path = remote_path
        else:
            # Handle subpath cleanup
            subpath = subpath.lstrip('/')
            
            # Check for path duplication
            if remote_path in subpath:
                # Extract the part after remote_path
                clean_subpath = subpath[subpath.find(remote_path) + len(remote_path):].lstrip('/')
                print(f"Found path duplication in {subpath}, cleaned to {clean_subpath}")
                path = os.path.join(remote_path, clean_subpath)
            else:
                path = os.path.join(remote_path, subpath)
        
        # Clean up the path to prevent directory traversal
        path = os.path.normpath(path)
        if not path.startswith(remote_path):
            abort(403, "Access denied")
        
        print(f"Browsing directory: {path}")
        listing = list_remote_directory(path)
        
        # Get the parent directory
        parent = os.path.dirname(path) if path != remote_path else None
        
        # Create relative path for navigation
        if path != remote_path:
            try:
                rel_path = os.path.relpath(path, remote_path)
            except (ValueError, TypeError):
                rel_path = ""
        else:
            rel_path = ""
        
        return render_template(
            'gallery.html',
            directories=listing.get('directories', []),
            files=listing.get('files', []),
            current_path=path,
            rel_path=rel_path,
            parent=parent,
            remote_host=remote_host
        )
    except Exception as e:
        # Log the error and show a basic error page
        print(f"Error in browse route: {e}")
        import traceback
        traceback.print_exc()
        return f"""
        <html>
        <head><title>Error</title></head>
        <body>
            <h1>Error accessing remote directory</h1>
            <p>There was an error accessing the remote directory: {str(e)}</p>
            <p>Check the server logs for more details.</p>
            <p><a href="/">Go back to home</a></p>
        </body>
        </html>
        """, 500

@app.route('/thumbnail/<path:filepath>')
def thumbnail(filepath):
    """Serve a thumbnail of a remote image"""
    filepath = filepath.lstrip('/')
    
    # Get just the filename
    filename = os.path.basename(filepath)
    
    # Try directly with the filename first
    full_path = os.path.join(remote_path, filename)
    
    print(f"Thumbnail request for: {filepath}")
    print(f"Using path: {full_path}")
    
    # Try to get the thumbnail
    thumbnail_path = get_thumbnail_path(full_path)
    if thumbnail_path and os.path.exists(thumbnail_path):
        # Double check it's not an empty file
        if os.path.getsize(thumbnail_path) > 0:
            return send_file(thumbnail_path)
    
    # If that failed, try with the full path as provided
    if filepath != filename:
        alt_path = filepath
        if not alt_path.startswith('/'):
            alt_path = '/' + alt_path
            
        if not alt_path.startswith(remote_path):
            if not remote_path.startswith('/'):
                remote_prefix = '/' + remote_path
            else:
                remote_prefix = remote_path
                
            if not alt_path.startswith(remote_prefix):
                alt_path = os.path.join(remote_path, filepath)
        
        print(f"First attempt failed, trying with: {alt_path}")
        thumbnail_path = get_thumbnail_path(alt_path)
        if thumbnail_path and os.path.exists(thumbnail_path):
            if os.path.getsize(thumbnail_path) > 0:
                return send_file(thumbnail_path)
    
    # If we get here, both attempts failed - create an error image
    print(f"Both attempts failed, creating error thumbnail for: {filename}")
    error_img = Image.new('RGB', THUMBNAIL_SIZE, color=(200, 0, 0))
    draw = ImageDraw.Draw(error_img)
    draw.text((10, 10), "Not found", fill=(255, 255, 255))
    draw.text((10, 30), filename, fill=(255, 255, 255))
    
    # Save to a temp file
    error_path = THUMBNAIL_DIR / f"error_{get_file_hash(filepath)}.jpg"
    error_img.save(error_path, "JPEG", quality=85)
    return send_file(error_path)

@app.route('/image/<path:filepath>')
def image(filepath):
    """Serve a remote image"""
    # Handle leading slashes that might cause path issues
    filepath = filepath.lstrip('/')
    
    # Extract just the filename - simplify path handling
    filename = os.path.basename(filepath)
    
    # Create the full path using the remote_path and the filename
    full_path = os.path.join(remote_path, filename)
    
    print(f"Image request for: {filepath}")
    print(f"Using full path: {full_path}")
    
    image_path = fetch_remote_image(full_path)
    if image_path:
        return send_file(image_path)
    else:
        abort(404)

@app.route('/clear-cache')
def clear_cache():
    """Clear the image cache"""
    # Clear directory cache
    directory_cache.clear()
    directory_cache_time.clear()
    
    # Clear thumbnail disk cache
    for path in THUMBNAIL_DIR.glob('*'):
        if path.is_file():
            path.unlink()
    
    # Clear image disk cache
    for path in IMAGE_CACHE_DIR.glob('*'):
        if path.is_file():
            path.unlink()
    
    # Clear function cache
    get_thumbnail_path.cache_clear()
    
    return "Cache cleared successfully! <a href='/'>Back to gallery</a>"
    
@app.route('/debug')
def debug_info():
    """Display debug information"""
    # Test SSH connection
    ssh_test = subprocess.run(["ssh", remote_host, "echo 'SSH connection successful'"], 
                            capture_output=True, text=True)
    
    # Get remote directory listing
    try:
        remote_listing = subprocess.run(
            ["ssh", remote_host, f"ls -la '{remote_path}'"], 
            capture_output=True, text=True, timeout=5)
    except subprocess.TimeoutExpired:
        remote_listing = "Timeout listing directory"
    
    # Check exact command being used
    test_cmd_output = ""
    try:
        test_cmd = ["ssh", remote_host, f"cd '{remote_path}' && find . -maxdepth 1 -type f -o -maxdepth 1 -type d | sort"]
        test_cmd_output = subprocess.run(test_cmd, capture_output=True, text=True, timeout=5)
    except Exception as e:
        test_cmd_output = f"Error: {str(e)}"
    
    # Test directory listing function
    dir_test_result = ""
    try:
        dir_listing = list_remote_directory(remote_path)
        dir_test_result = f"Directories: {len(dir_listing.get('directories', []))}\nFiles: {len(dir_listing.get('files', []))}"
        
        # Add details about first few items
        if dir_listing.get('directories'):
            dir_test_result += "\n\nSample directories:"
            for i, (name, path) in enumerate(dir_listing.get('directories', [])[:3]):
                dir_test_result += f"\n{i+1}. Name: {name}, Path: {path}"
        
        if dir_listing.get('files'):
            dir_test_result += "\n\nSample files:"
            for i, (name, path) in enumerate(dir_listing.get('files', [])[:3]):
                dir_test_result += f"\n{i+1}. Name: {name}, Path: {path}"
    except Exception as e:
        dir_test_result = f"Error listing directory: {str(e)}"
        import traceback
        dir_test_result += "\n\n" + traceback.format_exc()
    
    # Check for common tools
    tools = {}
    for tool in ['find', 'ls', 'test', 'scp']:
        tool_check = subprocess.run(["ssh", remote_host, f"which {tool}"], 
                                  capture_output=True, text=True)
        tools[tool] = tool_check.stdout.strip() if tool_check.returncode == 0 else "Not found"
    
    # Check cache directories
    cache_status = {}
    for name, path in [("Main Cache", CACHE_DIR), ("Thumbnails", THUMBNAIL_DIR), ("Images", IMAGE_CACHE_DIR)]:
        if path.exists():
            file_count = sum(1 for _ in path.glob('*') if _.is_file())
            size_bytes = sum(f.stat().st_size for f in path.glob('**/*') if f.is_file())
            cache_status[name] = f"Exists: Yes, Files: {file_count}, Size: {size_bytes/1024/1024:.2f} MB"
        else:
            cache_status[name] = "Exists: No"
    
    # System information
    system_info = subprocess.run(["uname", "-a"], capture_output=True, text=True)
    
    # Gather environment info
    env_info = {
        "REMOTE_HOST": remote_host,
        "REMOTE_PATH": remote_path,
        "CACHE_DIR": str(CACHE_DIR),
        "THUMBNAIL_DIR": str(THUMBNAIL_DIR),
        "IMAGE_CACHE_DIR": str(IMAGE_CACHE_DIR),
        "PYTHON_VERSION": sys.version,
        "DIRECTORY_CACHE_SIZE": len(directory_cache),
        "Pillow Version": getattr(Image, "__version__", "Unknown"),
        "Flask Version": getattr(Flask, "__version__", "Unknown"),
    }
    
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>PyRemoteView Debug Info</title>
        <style>
            body { font-family: monospace; margin: 20px; }
            pre { background: #f5f5f5; padding: 10px; border-radius: 5px; overflow-x: auto; }
            .section { margin-bottom: 20px; border: 1px solid #ddd; padding: 15px; border-radius: 5px; }
            h2 { color: #333; margin-top: 0; }
            .btn { 
                padding: 8px 16px; 
                background-color: #4CAF50; 
                color: white; 
                border: none; 
                border-radius: 4px; 
                cursor: pointer; 
                text-decoration: none; 
                display: inline-block;
                margin-right: 10px;
            }
            .btn:hover { background-color: #45a049; }
            .btn-danger { background-color: #f44336; }
            .btn-danger:hover { background-color: #d32f2f; }
            .status-ok { color: green; }
            .status-error { color: red; }
        </style>
    </head>
    <body>
        <h1>PyRemoteView Debug Information</h1>
        
        <div class="section">
            <h2>Environment</h2>
            <pre>"""
    
    for k, v in env_info.items():
        html += f"{k}: {v}\n"
    
    html += """</pre>
        </div>
        
        <div class="section">
            <h2>SSH Connection Test</h2>
            <pre>Status: <span class="{ssh_status}">{ssh_status_text}</span>
returncode: {ssh_returncode}
stdout: {ssh_stdout}
stderr: {ssh_stderr}</pre>
        </div>
        
        <div class="section">
            <h2>Cache Status</h2>
            <pre>"""
    
    for k, v in cache_status.items():
        html += f"{k}: {v}\n"
    
    html += """</pre>
        </div>
        
        <div class="section">
            <h2>Directory Listing Test</h2>
            <pre>{dir_test_result}</pre>
        </div>
        
        <div class="section">
            <h2>Remote 'find' Command Test</h2>
            <pre>Command: ssh {remote_host} "cd '{remote_path}' && find . -maxdepth 1 -type f -o -maxdepth 1 -type d | sort"
Status: {test_cmd_status}
Output: {test_cmd_output}</pre>
        </div>
        
        <div class="section">
            <h2>Remote Directory Contents (ls -la)</h2>
            <pre>{remote_listing}</pre>
        </div>
        
        <div class="section">
            <h2>Available Tools on Remote</h2>
            <pre>"""
    
    for k, v in tools.items():
        html += f"{k}: {v}\n"
    
    html += """</pre>
        </div>
        
        <div class="section">
            <h2>System Information</h2>
            <pre>{system_info}</pre>
        </div>
        
        <div class="section">
            <h2>Actions</h2>
            <a href="/clear-cache" class="btn">Clear Cache</a>
            <a href="/" class="btn">Back to Gallery</a>
            <a href="/debug" class="btn">Refresh Debug Info</a>
        </div>
    </body>
    </html>
    """.format(
        ssh_returncode=ssh_test.returncode,
        ssh_stdout=ssh_test.stdout,
        ssh_stderr=ssh_test.stderr,
        ssh_status="status-ok" if ssh_test.returncode == 0 else "status-error",
        ssh_status_text="OK" if ssh_test.returncode == 0 else "ERROR",
        remote_listing=remote_listing.stdout if hasattr(remote_listing, 'stdout') else str(remote_listing),
        system_info=system_info.stdout,
        remote_host=remote_host,
        remote_path=remote_path,
        test_cmd_status="OK" if hasattr(test_cmd_output, 'returncode') and test_cmd_output.returncode == 0 else "ERROR",
        test_cmd_output=test_cmd_output.stdout if hasattr(test_cmd_output, 'stdout') else str(test_cmd_output),
        dir_test_result=dir_test_result
    )
    
    return html

# Create a simple HTML template
@app.template_filter('basename')
def basename_filter(path):
    return os.path.basename(path)

# Add template filter for relative paths
@app.template_filter('relpath')
def relpath_filter(path, start):
    # Handle undefined or None values
    if path is None or path == '':
        return ''
    if path == start:
        return ''
    try:
        # Check if path is a valid string
        if not isinstance(path, (str, bytes, os.PathLike)):
            return str(path)
        return os.path.relpath(path, start)
    except (ValueError, TypeError):
        return str(path)

def parse_args():
    parser = argparse.ArgumentParser(description='Remote Image Gallery Server')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT, help='Port to run the server on')
    parser.add_argument('--host', default=DEFAULT_HOST, help='Host to run the server on')
    parser.add_argument('--remote-host', default=DEFAULT_REMOTE_HOST, help='Remote host to fetch images from')
    parser.add_argument('--remote-path', default=DEFAULT_REMOTE_PATH, help='Path on remote host to browse')
    return parser.parse_args()

def main():
    args = parse_args()
    
    global remote_host, remote_path
    remote_host = args.remote_host
    remote_path = args.remote_path
    
    # Verify connection to remote host
    try:
        result = subprocess.run(
            ["ssh", remote_host, "echo 'Connection test successful'"], 
            capture_output=True, text=True, timeout=5, check=True
        )
        print(f"✓ Successfully connected to {remote_host}")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"✗ Failed to connect to {remote_host}: {e}")
        print("Make sure passwordless SSH is set up correctly.")
        print("You can test with: ssh", remote_host)
        sys.exit(1)
    
    # Verify remote path exists
    try:
        result = subprocess.run(
            ["ssh", remote_host, f"test -d '{remote_path}' && echo 'Directory exists'"], 
            capture_output=True, text=True, timeout=5, check=True
        )
        if "Directory exists" in result.stdout:
            print(f"✓ Remote directory exists: {remote_path}")
        else:
            print(f"✗ Remote directory not found: {remote_path}")
            print(f"Creating directory...")
            subprocess.run(["ssh", remote_host, f"mkdir -p '{remote_path}'"], check=True)
            print(f"✓ Created directory: {remote_path}")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"✗ Failed to verify remote directory: {e}")
        sys.exit(1)
        
    # Verify cache directories
    for cache_dir in [CACHE_DIR, THUMBNAIL_DIR, IMAGE_CACHE_DIR]:
        cache_dir.mkdir(parents=True, exist_ok=True)
        print(f"✓ Cache directory ready: {cache_dir}")
    
    print(f"\n🚀 Starting server at http://{args.host}:{args.port}")
    print(f"📁 Serving images from {remote_host}:{remote_path}")
    print(f"💾 Thumbnail cache: {THUMBNAIL_DIR}")
    print(f"💾 Image cache: {IMAGE_CACHE_DIR}")
    print(f"🛠️  Debug page available at: http://{args.host}:{args.port}/debug")
    
    # Start the server
    try:
        app.run(host=args.host, port=args.port, debug=True)
    except Exception as e:
        print(f"✗ Error starting server: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()