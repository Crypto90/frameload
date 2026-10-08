"""Setup configuration for FrameLoad."""
from setuptools import find_packages, setup

setup(
    name="frameload",
    version="1.3.4",
    license="GPL-3.0-only",
    description="All-in-One On-Device VR Sideloading, Catalog Downloader, and Game Manager for Steam Frame",
    author="Crypto90",
    packages=find_packages(),
    include_package_data=True,
    package_data={
        "frameload": [
            "catalog/*.json",
            "web/templates/*",
            "web/static/css/*",
            "web/static/js/*",
            "web/static/assets/*",
        ]
    },
    entry_points={
        "console_scripts": [
            "frameload=frameload.cli:main",
        ]
    },
    python_requires=">=3.8",
)
