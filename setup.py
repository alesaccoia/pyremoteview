#!/usr/bin/env python

from setuptools import setup, find_packages

setup(
    name="pyremoteview",
    version="1.0.0",
    description="Remote SSH Image Gallery Viewer",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="Alessandro Saccoia",
    author_email="alessandro.saccoia@gmail.com",
    url="https://github.com/alesaccoia/pyremoteview",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "flask>=2.0.0",
        "pillow>=8.0.0",
        "werkzeug>=2.0.0",
    ],
    entry_points={
        "console_scripts": [
            "pyremoteview=pyremoteview.remote_gallery:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: Web Environment",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Topic :: Multimedia :: Graphics :: Viewers",
        "Topic :: Internet :: WWW/HTTP :: Dynamic Content",
    ],
    keywords="ssh remote image gallery viewer thumbnail",
    python_requires=">=3.6",
    license="MIT",
    zip_safe=False,
)